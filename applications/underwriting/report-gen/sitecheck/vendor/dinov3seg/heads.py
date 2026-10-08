"""
Mask-IoU scoring head  (Tier 1).

WHY THIS IS THE FIRST THING TO FIX
----------------------------------
v1's ranking signal is `score = cls x mask_quality`. Measured over 1834 val
predictions:

    cls_scores        mean 0.964, std 0.041, 36% of them above 0.99
    mask_quality      mean 0.968, std 0.020
    24.5% of predictions overlap NO ground truth at all,
      and their mean score is 0.903 against 0.948 for true positives

With a single foreground class the classifier has nothing to discriminate, so
it saturated, and `mq` -- the mean probability inside an already-binarised
mask -- is very nearly a constant. Score thresholds from 0.5 to 0.8 change
TP/FP/FN by exactly zero.

Correlation of the score with the prediction's true IoU is r = 0.477. Re-scoring
every v1 prediction with its actual IoU and re-running COCOeval:

    random ranking     AP 0.285
    cls alone          AP 0.364
    cls x mq  (v1)     AP 0.378
    oracle IoU         AP 0.508      <-- +13 AP, zero mask pixels changed

So the head below is a pure READ-OUT: its inputs are detached, it cannot
influence a single mask pixel, and it cannot make segmentation worse. It only
sorts.

WHAT IT SEES
------------
Mask Scoring R-CNN regresses IoU from the mask branch's features. The analogue
here, per query:

  * the transformer decoder's query embedding -- what the model "thinks" it found
  * the stride-4 mask features pooled under the query's own mask probability --
    the actual image evidence the mask was drawn from
  * three geometry scalars that a linear probe showed carry signal the
    embedding alone does not obviously expose (see `_geom`)

Hand-crafted cues alone are not enough: a least-squares fit on
{score, cls, mq, rectangularity, compactness, log area} reaches only r = 0.524
against r = 0.477 for the score alone. The IoU has to be learned from features.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


def _geom(prob, mask_thr=0.5):
    """
    Three cheap per-query scalars, from the mask probability field alone.

    prob: (B, Q, h, w) in [0, 1]. Returns (B, Q, 3).

      0. mask_quality -- mean probability inside the binarised region. Nearly
         constant on its own (std 0.020) but free, and it is the v1 signal, so
         the head can never do worse than v1 by ignoring everything else.
      1. log10 area fraction -- log area correlates with IoU at r = 0.357,
         the strongest single hand-crafted cue measured. Small buildings
         genuinely are segmented worse (AP_S 0.147 vs AP_M 0.458), and the
         head should be allowed to know that about itself.
      2. edge softness -- fraction of the mask's own area whose probability
         sits in [0.25, 0.75]. A crisp mask has a thin uncertain rim; a
         smeared one is mostly rim. This is the "did I actually commit to a
         boundary" cue, and it is not recoverable from a mean.
    """
    b, q, h, w = prob.shape
    binm = (prob > mask_thr).float()
    area = binm.flatten(2).sum(-1)                              # (B, Q)
    a1 = area.clamp_min(1.0)

    mq = (prob * binm).flatten(2).sum(-1) / a1
    logaf = torch.log10(area / float(h * w) + 1e-6)
    soft = (((prob > 0.25) & (prob < 0.75)).float().flatten(2).sum(-1)) / a1

    # a query with an empty mask has no geometry; say so explicitly rather
    # than letting the clamp above fabricate mq = 0, logaf = -6, soft = 0
    alive = (area > 0).float()
    return torch.stack([mq * alive, logaf, soft * alive], dim=-1)


class MaskIoUHead(nn.Module):
    """
    (query embedding, mask-pooled features, geometry) -> predicted IoU in [0, 1].

    ~0.6M params at the default widths. Trained with L2 against
    `losses.maskiou_targets`.
    """

    def __init__(self, query_dim, mask_dim, hidden=256, pool_size=128):
        super().__init__()
        # `transformer_decoder_last_hidden_state` is the RAW last decoder layer
        # output -- HF applies its final layernorm only on the `intermediate`
        # states used for the class head. Normalise here rather than reaching
        # into the decoder for a tensor whose name has changed before.
        self.q_norm = nn.LayerNorm(query_dim)
        self.f_norm = nn.LayerNorm(mask_dim)
        self.pool_size = pool_size
        self.mlp = nn.Sequential(
            nn.Linear(query_dim + mask_dim + 3, hidden), nn.GELU(),
            nn.Linear(hidden, hidden), nn.GELU(),
            nn.Linear(hidden, 1),
        )
        # Zero BIAS only, so every prediction starts near sigmoid(0) = 0.5
        # rather than at whatever the default init implies.
        #
        # NOT the weight as well, which is the more usual "zero-init the last
        # layer" trick: with a zero weight matrix the gradient w.r.t. this
        # module's INPUT is identically zero, so --no-maskiou-detach would be a
        # silent no-op until the weight happened to move off zero. (Caught by
        # selftest.py [6].) The head itself still trains either way, since the
        # gradient w.r.t. the weight is the incoming activation, not the weight.
        nn.init.zeros_(self.mlp[-1].bias)

    def forward(self, query_emb, mask_features, mask_logits, detach=True):
        """
        query_emb     (B, Q, Cq)   outputs.transformer_decoder_last_hidden_state
        mask_features (B, Cm, h, w) outputs.pixel_decoder_last_hidden_state
                                    -- this IS the tensor the masks are made
                                    from (`mask_features` in HF's decoder), so
                                    it is pixel-aligned with mask_logits by
                                    construction, not by assumption.
        mask_logits   (B, Q, h, w) outputs.masks_queries_logits

        Returns (B, Q) predicted IoU in [0, 1].
        """
        if detach:
            # A pure read-out. Without this the model could lower its IoU
            # prediction instead of improving the mask, and the head's
            # gradient would reach the shared pixel decoder -- risking the
            # mask quality this change is supposed to leave untouched.
            query_emb = query_emb.detach()
            mask_features = mask_features.detach()
            mask_logits = mask_logits.detach()

        prob = mask_logits.sigmoid().float()
        g = _geom(prob)                                          # (B, Q, 3)

        # Mask-weighted average pooling of the mask features under each query.
        # Downsampled first: this is a global average, so half resolution
        # changes it negligibly, and the (B, Q, h*w) weight matrix is the one
        # genuinely large intermediate here -- 105 MB at B=2, Q=200, 256^2,
        # a quarter of that at 128^2.
        f = mask_features.float()
        if prob.shape[-1] > self.pool_size:
            k = prob.shape[-1] // self.pool_size
            prob = F.avg_pool2d(prob, k)
            f = F.avg_pool2d(f, k)
        wq = prob.flatten(2)                                     # (B, Q, hw)
        ff = f.flatten(2).transpose(1, 2)                        # (B, hw, Cm)
        pooled = (wq @ ff) / wq.sum(-1, keepdim=True).clamp_min(1e-6)

        x = torch.cat([self.q_norm(query_emb.float()),
                       self.f_norm(pooled), g], dim=-1)
        return self.mlp(x).squeeze(-1).sigmoid()


def attach_maskiou_head(model, hidden=256, pool_size=128):
    """
    Bolt the head onto a Mask2FormerForUniversalSegmentation.

    Attached as a plain attribute rather than by subclassing: it then appears
    in `state_dict()` under `maskiou_head.*` and round-trips through
    save/load with no custom serialisation, while `model(...)` keeps HF's exact
    signature and loss behaviour.

    Dimensions are read from the config, so this survives a Swin-B -> Swin-L
    checkpoint swap.
    """
    q = model.config.hidden_dim
    m = model.config.mask_feature_size
    model.maskiou_head = MaskIoUHead(q, m, hidden=hidden, pool_size=pool_size)
    n = sum(p.numel() for p in model.maskiou_head.parameters()) / 1e6
    print(f"[build] mask-IoU head: query_dim={q} mask_dim={m} ({n:.2f}M params)")
    return model


def predict_iou(model, outputs, detach=True):
    """
    (B, Q) predicted IoU, or None if this checkpoint has no head.

    Kept as a function so infer.py can ask for the score without knowing
    whether it loaded a v1 or v2 checkpoint.
    """
    head = getattr(model, "maskiou_head", None)
    if head is None:
        return None
    return head(outputs.transformer_decoder_last_hidden_state,
                outputs.pixel_decoder_last_hidden_state,
                outputs.masks_queries_logits,
                detach=detach)


@torch.no_grad()
def iou_head_stats(pred, tgt, pos_thr=0.5, neg_thr=0.1):
    """
    Diagnostics for the mask-IoU head that actually reflect what it is for.

    MAE OVER ALL QUERIES IS THE WRONG NUMBER, and it is the one this originally
    logged. With num_queries=200 and ~26 instances per tile, ~87% of queries
    are parked on nothing and have target ~0, so a plain MAE is mostly a
    measure of how well the head predicts zero -- while AP depends only on
    whether the head can ORDER the real detections above the garbage.
    Observed on a real run: MAE sat at 0.19 +/- 0.014 from epoch 5 to 16 and
    was unreadable as progress.

    Returns:
      mae      over all queries -- kept only for continuity with older logs
      mae_pos  over queries whose target is above `pos_thr`; the error on
               masks that actually matched something
      auc      P(pred higher for a well-matched query than for a garbage one),
               over pairs with target > pos_thr vs target < neg_thr. 0.5 is
               chance, 1.0 is perfect separation. THIS is the number that
               tracks AP, because it is a statement about ranking rather than
               about calibration.
      n_pos    how many queries the positive stats are averaged over, so a
               suspiciously good auc from three samples is visible
    """
    pred, tgt = pred.reshape(-1).float(), tgt.reshape(-1).float()
    out = {"mae": float((pred - tgt).abs().mean()), "mae_pos": None,
           "auc": None, "n_pos": 0}
    pos, neg = tgt > pos_thr, tgt < neg_thr
    n_pos = int(pos.sum())
    out["n_pos"] = n_pos
    if n_pos:
        out["mae_pos"] = float((pred[pos] - tgt[pos]).abs().mean())
    if n_pos and int(neg.sum()):
        # pairwise, not a sort: the tie term matters early on when the head is
        # still near-constant and would otherwise score a spurious 0 or 1
        a, b = pred[pos][:, None], pred[neg][None, :]
        out["auc"] = float((a > b).float().mean() + 0.5 * (a == b).float().mean())
    return out
