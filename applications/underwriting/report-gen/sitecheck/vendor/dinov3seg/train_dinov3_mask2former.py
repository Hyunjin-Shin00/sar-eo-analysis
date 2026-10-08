"""
DINOv3 (frozen) + Mask2Former instance segmentation, for building extraction.

v2. Changes over v1, each sized against a measured v1 failure mode on the
52-tile val split (see README.md for the full diagnosis):

  Tier 0  `iscrowd` regions are no longer trained as background. 100% of them
          are buildings clipped by the tile edge, and calling them background
          teaches the model to suppress buildings at tile borders.
  Tier 1  A mask-IoU head supplies the ranking signal. v1's `cls x mq` score
          correlates r=0.477 with true IoU; oracle ranking is worth +13 AP.
  Tier 2  `collision_loss` penalises one query covering two GT buildings --
          45% of v1's "missed" buildings were absorbed into a neighbour.
  Tier 3  The feature pyramid taps FOUR ViT layers instead of resampling one.

Design intent (matters for a ~250-tile dataset):
  * DINOv3 backbone is FROZEN. It is the only part that needs lots of data,
    and it already has it. Nothing you own can improve it.
  * The Mask2Former head is warm-started from COCO instance weights, so the
    pixel decoder / transformer decoder are not learning from scratch either.
  * Only the feature pyramid adapter + Mask2Former head + IoU head are trained.

Usage (see README.md for every argument, its default and a recommendation):
    python train_dinov3_mask2former.py
        --data-root ../dataset/new_data/data_stride256
        --image-size 1024 --num-queries 200 --epochs 60
        --taps auto --crowd instance --maskiou-weight 1.0
        --collision-weight 1.0 --boundary-weight 2.0 --crowd-weight 3.0
        --p-mosaic 0.3 --out ./runs/v2

Each run writes three artefacts into --out:
    best_ep<N>.pth     lowest val loss so far; N is the 1-based epoch
    last_ep<N>.pth     the FINAL epoch only -- written once, at the end
    run_config.json    every argument, which were explicit on the command
                       line, the resolved settings, the environment, results
Only two .pth ever exist: each save deletes the older file with its own tag.
Pass the DIRECTORY to infer.py --ckpt and it picks the newest best_ep*.pth.
"""

import argparse
import datetime
import json
import os
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from tqdm.auto import tqdm

from transformers import (
    AutoModel,
    Mask2FormerForUniversalSegmentation,
    Mask2FormerImageProcessor,
)
from transformers.modeling_outputs import BackboneOutput

from augment import aug_full, basa, mosaic
from heads import attach_maskiou_head, iou_head_stats, predict_iou
from losses import (boundary_loss, collision_loss, fragmentation_loss,
                    maskiou_targets)
from runlog import (append_loss_row, fresh_run_dir, save_ckpt,
                    save_run_config)


def val_predictions(out, pred_iou, ids, sizes, score_mode,
                    score_thr=0.05, mask_thr=0.5, min_area=100):
    """
    COCO-format predictions for one already-computed val batch.

    Costs no extra forward pass. `out` was produced with mask_labels attached
    so the loss could be read, but the label path does not touch
    class_queries_logits / masks_queries_logits -- the same tensors inference
    would post-process are already in hand.

    score_thr is deliberately LOW. AP integrates the whole precision-recall
    curve, so cutting predictions early truncates the tail and depresses AP for
    reasons that have nothing to do with the model. This is not the operating
    threshold; --threshold in infer.py is.

    The pipeline here is post_process + dedup, NOT the full clean_instances
    path infer.py runs. Selection needs a criterion that is consistent across
    epochs and correlates with the reported number, not one that reproduces it
    exactly -- and every extra stage is another thing that can drift away from
    what infer.py does.
    """
    from infer import _post_from_prob, dedup, from_full
    from eval import rle_of

    cls = out.class_queries_logits.float().softmax(-1)
    cls_score = cls[..., :-1].max(-1).values                 # (B, Q)
    preds = []
    for b, (iid, size) in enumerate(zip(ids, sizes)):
        logits = torch.nn.functional.interpolate(
            out.masks_queries_logits[b][None].float(), size=size,
            mode="bilinear", align_corners=False)[0]
        tup = _post_from_prob(
            logits.sigmoid(), cls_score[b], score_thr=score_thr,
            mask_thr=mask_thr, min_area=min_area,
            pred_iou=(pred_iou[b].float() if pred_iou is not None else None),
            score_mode=score_mode)
        insts = [from_full(m, s, cls=c, mq=q, iou=v) for m, s, c, q, v in tup]
        for i in dedup([x for x in insts if x is not None]):
            full = np.zeros(size, bool)
            full[i.y0:i.y1, i.x0:i.x1] = i.mask
            preds.append({"image_id": int(iid), "category_id": 1,
                          "segmentation": rle_of(full),
                          "score": float(i.score)})
    return preds


# --------------------------------------------------------------------------
# 1. DINOv3 -> multi-scale feature pyramid
# --------------------------------------------------------------------------
def _vit_blocks(vit):
    """
    The transformer block list, whatever this checkpoint calls it.

    DINOv3 is not a standard HF architecture, so the attribute name varies by
    transformers version (layer / layers / blocks, under encoder or not).
    Rather than hardcode a path that silently returns None on the next
    upgrade -- leaving the backbone frozen while the log says otherwise --
    pick the longest ModuleList in the model, which is the block stack in
    every ViT variant.
    """
    best = []
    for _, m in vit.named_modules():
        if isinstance(m, (nn.ModuleList, nn.Sequential)) and len(m) > len(best):
            if all(sum(p.numel() for p in b.parameters()) > 0 for b in m):
                best = list(m)
    return best if len(best) >= 4 else []


def resolve_taps(vit, spec):
    """
    Which transformer blocks feed which pyramid level (Tier 3).

    `spec` is "off" (v1: one layer, resampled four ways), "auto", or an
    explicit comma-separated list of 4 block indices, finest level first.

    "auto" spreads the taps evenly through the stack -- for ViT-L/24 that is
    blocks 5/11/17/23. Early blocks carry more local texture and less semantic
    abstraction, which is what the stride-4 level actually wants; the last
    block goes to stride 32, where global context is the point.

    Returns a list of 4 indices into `hidden_states`, i.e. block index + 1
    (hidden_states[0] is the embedding output, before any block), or None.
    """
    if not spec or spec == "off":
        return None
    depth = len(_vit_blocks(vit)) or int(
        getattr(vit.config, "num_hidden_layers", 0))
    if depth < 4:
        print("[warn] cannot locate >=4 transformer blocks; taps disabled")
        return None
    if spec == "auto":
        blocks = [round(depth * f) - 1 for f in (0.25, 0.5, 0.75, 1.0)]
    else:
        blocks = [int(v) for v in spec.split(",")]
        if len(blocks) != 4:
            raise SystemExit(f"--taps needs exactly 4 indices, got {len(blocks)}")
        if any(b < 0 or b >= depth for b in blocks):
            raise SystemExit(f"--taps indices must be in [0, {depth - 1}]")
    print(f"[build] pyramid taps: blocks {blocks} of {depth} "
          f"-> strides 4/8/16/32")
    return [b + 1 for b in blocks]


class DINOv3Pyramid(nn.Module):
    """
    Mask2Former's pixel decoder wants 4 feature maps at strides 4/8/16/32.
    A plain ViT gives you exactly one, at stride `patch_size`.

    v1 was the ViTDet "simple feature pyramid": build the other scales by
    (de)convolution from that single map. It works -- the ViT features are
    already globally contextualized, so you are resampling one hierarchy
    rather than rebuilding it -- but every level is then a different *view of
    the same tensor*, and the transposed convs are asked to invent stride-4
    detail that the stride-16 map does not contain. Measured cost on v1:
    AP_S 0.147 against AP_M 0.458, and 139 of the 183 genuinely-undetected
    buildings are under 1000 px.

    v2 taps FOUR DIFFERENT BLOCKS (`taps`), one per level, so the pixel
    decoder receives genuinely different representations and the resampling
    only has to change scale, not manufacture information. This is what
    ViT-Adapter and DPT do. The resamplers are unchanged -- all ViT blocks
    share one width, so the channel arithmetic is identical and the cost is
    four LayerNorms.

    The lateral 1x1 convs match channel counts to whatever the pretrained
    Mask2Former checkpoint expects (Swin-B -> [128, 256, 512, 1024]).
    """

    def __init__(self, vit, out_channels, embed_dim, patch_size=16,
                 freeze_vit=True, use_stem=True, unfreeze_last=0, taps=None):
        super().__init__()
        self.vit = vit
        self.patch_size = patch_size
        self.n_prefix = None  # auto-detected on first forward (CLS + registers)
        self.taps = taps

        if freeze_vit:
            self.vit.eval()
            for p in self.vit.parameters():
                p.requires_grad = False
            # DINOv3 was pretrained on natural imagery; 0.5 m/px nadir
            # satellite is a long way outside that. Adapting the last few
            # blocks is the one change that alters what the backbone can
            # represent -- everything else only reshapes frozen features.
            # Keep it to the last few: the whole encoder on 248 tiles overfits.
            if unfreeze_last > 0:
                blocks = _vit_blocks(vit)
                if not blocks:
                    print("[warn] could not locate transformer blocks; "
                          "backbone stays fully frozen")
                else:
                    for b in blocks[-unfreeze_last:]:
                        for p in b.parameters():
                            p.requires_grad = True
                    n = sum(p.numel() for p in vit.parameters()
                            if p.requires_grad) / 1e6
                    print(f"[build] unfroze last {unfreeze_last} of "
                          f"{len(blocks)} ViT blocks ({n:.1f}M params)")

        self._vit_frozen = not any(p.requires_grad for p in self.vit.parameters())

        c = embed_dim

        # Stride-4 stem on the raw image.
        #
        # A patch-16 ViT emits one stride-16 map: at 512 input that is 32x32,
        # i.e. one feature cell per 8 m of ground at 0.5 m GSD. There is no
        # high-frequency content in it, so the transposed convs below are asked
        # to invent stride-4 detail -- which is what produces rounded, inset
        # masks on small buildings.
        #
        # This path carries real image detail at stride 4 and is added to the
        # finest pyramid level, giving the decoder genuine edges alongside
        # upsampled semantics. ~0.2M params. ConvNeXt does not need it: its
        # stage-1 features are already stride 4.
        self.stem = nn.Sequential(
            nn.Conv2d(3, 64, 7, 2, 3), nn.GroupNorm(32, 64), nn.GELU(),
            nn.Conv2d(64, c // 4, 3, 2, 1), nn.GroupNorm(32, c // 4), nn.GELU(),
        ) if use_stem else None
        # stride 4  : upsample x4
        self.up4 = nn.Sequential(
            nn.ConvTranspose2d(c, c // 2, 2, 2),
            nn.GroupNorm(32, c // 2),
            nn.GELU(),
            nn.ConvTranspose2d(c // 2, c // 4, 2, 2),
        )
        # stride 8  : upsample x2
        self.up8 = nn.ConvTranspose2d(c, c // 2, 2, 2)
        # stride 16 : identity
        # stride 32 : downsample x2
        self.dn32 = nn.MaxPool2d(2, 2)

        src = [c // 4, c // 2, c, c]
        self.lateral = nn.ModuleList(
            nn.Sequential(nn.Conv2d(s, o, 1, bias=False), nn.GroupNorm(32, o))
            for s, o in zip(src, out_channels)
        )
        self.channels = list(out_channels)

        # One LayerNorm per tap. NOT cosmetic: activation scale in a ViT grows
        # by roughly an order of magnitude from block 5 to block 23, so feeding
        # raw intermediate states into four resamplers that share an optimizer
        # makes the early levels invisible and the late ones dominate. DPT and
        # ViT-Adapter both normalise per tap for this reason. Cheap (2C params
        # each) and it keeps the pyramid levels commensurate.
        self.tap_norm = nn.ModuleList(
            [nn.LayerNorm(c) for _ in range(4)]) if taps else None

    def train(self, mode=True):
        super().train(mode)
        # Eval mode even when some blocks are being tuned: it only disables
        # dropout and stochastic depth, which is what you want when fine-tuning
        # a 300M-parameter encoder on 248 tiles. requires_grad, not train
        # mode, is what decides whether a block learns.
        self.vit.eval()
        return self

    def forward(self, pixel_values, **kwargs):
        B, _, H, W = pixel_values.shape
        h, w = H // self.patch_size, W // self.patch_size

        # An unconditional no_grad here would make --unfreeze-last a silent
        # no-op: requires_grad=True on a block means nothing if the graph never
        # reaches it. Respect any outer no_grad (eval) and enable only when
        # something in the backbone is actually being tuned.
        with torch.set_grad_enabled(torch.is_grad_enabled() and
                                    not self._vit_frozen):
            if self.taps is None:
                tokens = self.vit(pixel_values).last_hidden_state
                stack = [tokens] * 4
            else:
                hs = self.vit(pixel_values,
                              output_hidden_states=True).hidden_states
                if len(hs) <= max(self.taps):
                    raise RuntimeError(
                        f"--taps asked for hidden_states[{max(self.taps)}] but "
                        f"the backbone returned {len(hs)}. Re-run with "
                        f"--taps off, or pass explicit indices.")
                tokens = hs[self.taps[-1]]
                stack = [hs[t] for t in self.taps]

        if self.n_prefix is None:
            self.n_prefix = tokens.shape[1] - h * w
            print(f"[DINOv3Pyramid] detected {self.n_prefix} prefix tokens "
                  f"(CLS + registers)")

        def grid(t, level):
            t = t[:, self.n_prefix:, :]
            if self.tap_norm is not None:
                t = self.tap_norm[level](t)
            return t.transpose(1, 2).reshape(B, -1, h, w).contiguous().float()

        g = [grid(t, k) for k, t in enumerate(stack)]

        fine = self.up4(g[0])
        if self.stem is not None:
            fine = fine + self.stem(pixel_values.float())
        feats = [fine, self.up8(g[1]), g[2], self.dn32(g[3])]
        return BackboneOutput(
            feature_maps=tuple(l(x) for l, x in zip(self.lateral, feats))
        )


def expand_queries(model, n_new, sigma=0.02, seed=0):
    """
    Grow the query set past the COCO checkpoint's 100 without losing its warm
    start.

    Mask2Former can only ever match num_queries ground-truth instances. Past
    that the surplus is silently dropped -- Hungarian matching raises nothing
    and the loss actually FALLS (measured: 100 GT -> 74.22, 160 GT -> 51.84),
    so the signal degrades in a way that looks like progress. At ~26
    annotations per tile, mosaic pushes samples to 80-110 instances and hits
    this wall.

    Passing num_queries=200 to from_pretrained instead reinitialises both query
    embeddings from scratch, discarding what the COCO decoder learned. So load
    at 100, then append perturbed copies of the pretrained embeddings, which is
    the GOOSE-M2F trick: new queries start near useful ones rather than at
    random.

    Only two tensors are sized by num_queries, so nothing else needs touching.
    """
    tm = model.model.transformer_module
    g = torch.Generator().manual_seed(seed)
    for name in ("queries_embedder", "queries_features"):
        emb = getattr(tm, name)
        w = emb.weight.data
        n_old, d = w.shape
        if n_new <= n_old:
            continue
        extra = n_new - n_old
        idx = torch.arange(extra) % n_old
        noise = torch.randn(extra, d, generator=g).to(w.device, w.dtype) * sigma
        new_emb = nn.Embedding(n_new, d).to(w.device, w.dtype)
        new_emb.weight.data.copy_(torch.cat([w, w[idx] + noise], dim=0))
        setattr(tm, name, new_emb)
    model.config.num_queries = n_new
    for obj in (tm, getattr(tm, "decoder", None)):
        if obj is not None and hasattr(obj, "num_queries"):
            obj.num_queries = n_new
    print(f"[build] queries {n_old} -> {n_new} "
          f"(first {n_old} preserved, rest perturbed copies, sigma={sigma})")
    return model


class DINOv3ConvNeXtPyramid(nn.Module):
    """
    Hierarchical backbone -> Mask2Former.

    ConvNeXt already emits strides 4/8/16/32 (at 512 input: 128x128, 64x64,
    32x32, 16x16 with channels 192/384/768/1536 for the Large variant), so
    there is nothing to hallucinate. This is pure channel matching, and the
    stride-4 map is a real early-stage feature rather than an upsampled
    stride-16 one -- which is the whole reason to prefer it here.
    """

    def __init__(self, net, out_channels, freeze=True):
        super().__init__()
        self.net = net
        if freeze:
            self.net.eval()
            for p in self.net.parameters():
                p.requires_grad = False
        self.lateral = nn.ModuleList(
            nn.Sequential(nn.Conv2d(s, o, 1, bias=False), nn.GroupNorm(32, o))
            for s, o in zip(net.config.hidden_sizes, out_channels)
        )
        self.channels = list(out_channels)

    def train(self, mode=True):
        super().train(mode)
        self.net.eval()
        return self

    def forward(self, pixel_values, **kwargs):
        with torch.no_grad():
            # hidden_states[0] is the input image; stages 1..4 follow
            hs = self.net(pixel_values,
                          output_hidden_states=True).hidden_states[1:]
        return BackboneOutput(
            feature_maps=tuple(l(h.float())
                               for l, h in zip(self.lateral, hs))
        )


def build_model(dinov3_id, m2f_id, num_labels=1, image_size=512,
                backbone="auto", use_stem=True, num_queries=None,
                unfreeze_last=0, taps="off", maskiou=True,
                maskiou_hidden=256):
    """Load pretrained Mask2Former, then transplant the DINOv3 backbone."""
    model = Mask2FormerForUniversalSegmentation.from_pretrained(
        m2f_id, num_labels=num_labels, ignore_mismatched_sizes=True
    )

    # channels the pretrained pixel decoder was built for
    probe = torch.randn(1, 3, image_size, image_size)
    with torch.no_grad():
        ch = [f.shape[1]
              for f in model.model.pixel_level_module.encoder(probe).feature_maps]
    print(f"[build] pixel decoder expects channels {ch}")

    if num_queries and num_queries != model.config.num_queries:
        expand_queries(model, num_queries)

    if backbone == "auto":
        backbone = "convnext" if "convnext" in dinov3_id.lower() else "vit"
    print(f"[build] backbone type: {backbone}")

    net = AutoModel.from_pretrained(dinov3_id)

    if backbone == "convnext":
        dims = list(net.config.hidden_sizes)
        print(f"[build] ConvNeXt stage dims {dims} -> strides 4/8/16/32")
        # ConvNeXt already emits four real stages, so Tier 3 does not apply.
        if taps not in (None, "off"):
            print("[warn] --taps is ViT-only; ignored for a ConvNeXt backbone")
        model.model.pixel_level_module.encoder = DINOv3ConvNeXtPyramid(
            net, ch, freeze=True)
    else:
        embed_dim = net.config.hidden_size
        patch = getattr(net.config, "patch_size", 16)
        print(f"[build] ViT hidden={embed_dim} patch={patch} "
              f"stem={'on' if use_stem else 'off'}")
        model.model.pixel_level_module.encoder = DINOv3Pyramid(
            net, ch, embed_dim, patch_size=patch, freeze_vit=True,
            use_stem=use_stem, unfreeze_last=unfreeze_last,
            taps=resolve_taps(net, taps))

    if maskiou:
        attach_maskiou_head(model, hidden=maskiou_hidden)
    return model


# --------------------------------------------------------------------------
# 2. Dataset (COCO instance format)
# --------------------------------------------------------------------------
class BuildingInstanceDataset(Dataset):
    """
    Expects:
        root/images/*.png
        root/annotations.json     (COCO instance format, 1 category)

    Returns per-instance binary masks, which is what Mask2Former's loss wants
    (mask_labels + class_labels), NOT a semantic map.

    TIER 0 -- `crowd`. v1 loaded annotations with `iscrowd=False`, which makes
    every crowd region a BACKGROUND target. That is wrong here, and measurably
    so: 100% of the 1173 train / 273 val crowd annotations touch a tile border,
    i.e. `iscrowd` in this dataset does not mean "an unresolvable heap of
    objects" (COCO's meaning) -- it means "a building the tiler clipped".
    Training them as background teaches the model to suppress buildings at tile
    edges, which is precisely where sliding-window inference has to work.

        instance    (default) load them as ordinary instances. They ARE
                    buildings; a clipped one is still a positive, and it
                    matches what inference sees, since tiling clips buildings
                    there too. infer.py already drops edge-touching
                    predictions, so this costs nothing at test time.
                    Needs no special handling anywhere downstream -- which is
                    the point: the augmentation pipeline is (img, masks), so
                    anything "special" would have to be smuggled through
                    mosaic and rotate_any in the mask VALUES.
        background  v1 behaviour, kept so the change can be A/B'd.
    """

    def __init__(self, root, ann_file, processor, augment=False,
                 p_mosaic=0.3, p_rot_any=0.5, p_scale=0.8, out_size=512,
                 crowd="instance", max_instances=None, rot_mode="pad"):
        from pycocotools.coco import COCO

        self.root = Path(root)
        self.coco = COCO(ann_file)
        self.ids = sorted(self.coco.imgs.keys())
        self.processor = processor
        self.augment = augment
        self.p_mosaic = p_mosaic
        self.p_rot_any = p_rot_any
        self.p_scale = p_scale
        self.rot_mode = rot_mode
        self.out_size = out_size
        self.crowd = crowd
        # Hard cap on instances per sample, normally --num-queries.
        #
        # VERIFIED against scipy's linear_sum_assignment on a (Q, N) cost
        # matrix: once N >= Q every query is matched, so NO query is left
        # carrying a no-object target. That step trains the classifier with
        # zero negatives, and the N - Q surplus buildings contribute no mask
        # loss at all -- the total loss FALLS (v1 measured 100 GT -> 74.22,
        # 160 GT -> 51.84), which reads as instability and teaches the model to
        # stop suppressing anything.
        #
        # A 2x2 mosaic on this dataset has an upper bound of 219 instances
        # (max over 20k draws; p99 191, median 125), so at --num-queries 200
        # roughly 0.3% of draws could starve the matcher. Rare, but the damage
        # per occurrence is large and the fix is free.
        self.max_instances = max_instances
        self.n_mosaic_skipped = 0

        # kept as attributes, not just printed, so save_run_config() can record
        # what the run actually trained on
        self.n_crowd = sum(len(self.coco.getAnnIds(i, iscrowd=True)) for i in self.ids)
        self.n_inst = sum(len(self.coco.getAnnIds(i, iscrowd=False)) for i in self.ids)
        print(f"[data] {root}: {self.n_inst} instances + {self.n_crowd} crowd "
              f"({'kept as instances' if crowd == 'instance' else 'DROPPED to background'})")

    def __len__(self):
        return len(self.ids)

    def _load_raw(self, i):
        """Image + per-instance masks, no augmentation."""
        info = self.coco.imgs[self.ids[i]]
        img = np.array(Image.open(self.root / "images" / info["file_name"])
                       .convert("RGB"))
        # iscrowd=None means "no filter" in pycocotools, NOT "iscrowd only".
        kw = {} if self.crowd == "instance" else {"iscrowd": False}
        anns = self.coco.loadAnns(self.coco.getAnnIds(self.ids[i], **kw))
        if len(anns):
            masks = np.stack([self.coco.annToMask(a) for a in anns]).astype(np.uint8)
        else:
            masks = np.zeros((0, info["height"], info["width"]), np.uint8)
        return img, masks

    def __getitem__(self, i):
        if self.augment and np.random.rand() < self.p_mosaic:
            # Mosaic is the only augmentation that shrinks apparent building
            # size AND raises instance density at the same time -- the two
            # confirmed gaps between the large-shed training scene and the
            # dense small-workshop fabric. Measured: 3.7x instances, 0.29x
            # median instance area.
            idxs = [i] + list(np.random.randint(0, len(self), 3))
            raws = [self._load_raw(j) for j in idxs]
            # Checked on the SUM before compositing: that is an upper bound on
            # what mosaic can emit (cropping, downscaling into a quarter cell
            # and the min-area filter only ever remove instances), so the guard
            # is conservative and costs nothing when it does not fire. Falling
            # back to the plain tile is strictly better than a mosaic that
            # silently starves the matcher.
            n_up = sum(len(m) for _, m in raws)
            if self.max_instances and n_up > self.max_instances:
                self.n_mosaic_skipped += 1
                img, masks = raws[0]
            else:
                img, masks = mosaic(raws, out_size=self.out_size)
        else:
            img, masks = self._load_raw(i)

        if self.augment:
            # aug_full handles len(masks) == 0, so empty tiles still get
            # photometric variation (the old inline _aug skipped them).
            img, masks = aug_full(img, masks,
                                  p_rot_any=self.p_rot_any,
                                  p_scale=self.p_scale,
                                  rot_mode=self.rot_mode)

        # Drop instances that augmentation reduced to nothing.
        # NOTE: sum over axes (1, 2) rather than reshape(len(masks), -1) --
        # numpy cannot infer -1 for an empty array, so the reshape form raises
        # on tiles that contain no buildings. Empty tiles are legitimate
        # negatives and Mask2Former handles zero-instance samples fine.
        masks = masks[masks.sum(axis=(1, 2)) > 16]

        enc = self.processor(images=img, segmentation_maps=None,
                             return_tensors="pt")
        return {
            "pixel_values": enc["pixel_values"][0],
            "mask_labels": torch.from_numpy(masks).float(),
            "class_labels": torch.zeros(len(masks), dtype=torch.long),
            # val AP has to name the COCO image each prediction belongs to.
            # Deriving it from batch order would work only while the loader
            # stays shuffle=False and drop_last=False, and would fail silently
            # -- as a scrambled image_id, i.e. a plausible but wrong AP -- if
            # either ever changed.
            "idx": i,
        }


def collate(batch):
    return {
        "pixel_values": torch.stack([b["pixel_values"] for b in batch]),
        "mask_labels": [b["mask_labels"] for b in batch],
        "class_labels": [b["class_labels"] for b in batch],
        "idx": [b["idx"] for b in batch],
    }


# --------------------------------------------------------------------------
# 3. Train
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default="./data")
    ap.add_argument("--dinov3", default="facebook/dinov3-vitl16-pretrain-lvd1689m",
                    help="ViT: facebook/dinov3-vitl16-pretrain-lvd1689m | "
                         "ConvNeXt: facebook/dinov3-convnext-large-pretrain-lvd1689m")
    ap.add_argument("--num-queries", type=int, default=None,
                    help="grow the query set (COCO default 100). Mask2Former "
                         "can match at most this many GT instances per tile; "
                         "the surplus is dropped silently. Use ~2x your max "
                         "instances-per-tile.")
    ap.add_argument("--backbone", choices=["auto", "vit", "convnext"],
                    default="auto",
                    help="auto = infer from --dinov3 (looks for 'convnext')")
    ap.add_argument("--p-mosaic", type=float, default=0.0)
    ap.add_argument("--p-rot-any", type=float, default=0.2,
                    help="probability of an arbitrary-angle rotation on top of "
                         "D4. NOTE D4 alone contributes nothing to orientation "
                         "diversity -- mod 90 it is the identity on an "
                         "axis-aligned building -- so this is the ONLY source "
                         "of off-axis training signal. Train GT here is 99.6% "
                         "axis-aligned.")
    ap.add_argument("--rot-mode", choices=["pad", "crop"], default="pad",
                    help="how rotate_any avoids border fill. pad (default) "
                         "rotates in place and accepts black corners, "
                         "PRESERVING SCALE. crop takes the inscribed square and "
                         "resizes back -- no black, but a 2.0x area zoom, which "
                         "meant rotated buildings only ever reached the model "
                         "magnified (median instance area 2288 -> 5398 px) and "
                         "cost supervision (29.6 -> 11.4 instances/sample). "
                         "crop reproduces runs 1-3.")
    ap.add_argument("--p-scale", type=float, default=0.8)
    ap.add_argument("--basa-p", type=float, default=0.0,
                    help="BaSA probability. Only useful with multi-scene data "
                         "and batch>=4; near-useless on one scene (it can only "
                         "shuffle styles that already exist).")
    ap.add_argument("--boundary-weight", type=float, default=2.0,
                    help="weight of the auxiliary boundary loss. 0 = off. In "
                         "BCE units, comparable with the existing mask terms; "
                         "1-5 is the sane range. Defaults ON in v2 (v1 was 0) "
                         "because matched masks sit 2.78 px off the true edge "
                         "and --crowd-weight rides on this term.")
    ap.add_argument("--boundary-width", type=int, default=3,
                    help="half-width in mask-logit pixels of the band around "
                         "the GT edge that the boundary loss scores")
    ap.add_argument("--unfreeze-last", type=int, default=0,
                    help="fine-tune the last N transformer blocks of the "
                         "backbone at --backbone-lr-mult x --lr. 0 keeps it "
                         "fully frozen (the previous behaviour). Try 4-6.")
    ap.add_argument("--backbone-lr-mult", type=float, default=0.1,
                    help="backbone LR relative to --lr; the head is 1x and the "
                         "randomly-initialised adapter 10x")
    ap.add_argument("--no-stem", action="store_true",
                    help="disable the stride-4 stem (ViT only; for ablation)")
    ap.add_argument("--m2f", default="facebook/mask2former-swin-base-coco-instance")
    ap.add_argument("--image-size", type=int, default=512)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--out", default="./runs/dinov3_m2f")

    # ---- v2 -------------------------------------------------------------
    ap.add_argument("--crowd", choices=["instance", "background"],
                    default="instance",
                    help="TIER 0. What to do with iscrowd annotations. All of "
                         "them are tile-edge-clipped buildings, so 'instance' "
                         "(default) is correct; 'background' is v1 behaviour.")
    ap.add_argument("--taps", default="auto",
                    help="TIER 3. Which ViT blocks feed the 4 pyramid levels: "
                         "'auto' (evenly spread, e.g. 5,11,17,23 for ViT-L), "
                         "'off' for v1's single-layer resampling, or 4 explicit "
                         "block indices, finest level first.")
    ap.add_argument("--maskiou-weight", type=float, default=1.0,
                    help="TIER 1. Weight of the mask-IoU regression loss. The "
                         "head is a detached read-out, so this only trades off "
                         "against itself -- 1.0 is fine. 0 disables the head.")
    ap.add_argument("--maskiou-hidden", type=int, default=256)
    ap.add_argument("--no-maskiou-detach", action="store_true",
                    help="let the IoU head's gradient reach the pixel decoder. "
                         "OFF by default: detached, the head cannot make masks "
                         "worse, and the measured +13 AP ceiling is pure "
                         "ranking. Only for ablation.")
    ap.add_argument("--collision-weight", type=float, default=1.0,
                    help="TIER 2. Weight of the query-collision loss, which "
                         # '%%' not '%': argparse runs help through
                         # `help % params`, so a bare % is a format spec and
                         # --help crashes with a TypeError.
                         "penalises one query covering two GT buildings. 45%% "
                         "of v1's missed buildings were absorbed this way.")
    ap.add_argument("--select-by", choices=("ap", "loss"), default="ap",
                    help="which val metric picks best_ep*.pth. DEFAULT CHANGED "
                         "to 'ap' -- runs up to and including run4 used 'loss'. "
                         "Val loss is dominated by the mask/cls terms, which "
                         "converge early, while the IoU head that AP ranks on "
                         "converges later: run4's val loss bottomed at ep6 with "
                         "iou_auc 0.9136, against its own peak of 0.9426 at "
                         "ep12. run3 escaped this only because its loss minimum "
                         "(ep33) happened to sit beside its auc peak (ep34). "
                         "'loss' is kept to reproduce those older runs.")
    ap.add_argument("--ckpt-every", type=int, default=0, metavar="N",
                    help="also save snap_ep*.pth every N epochs, keeping ALL of "
                         "them (~1.6 GB each). Insurance against the selection "
                         "criterion being wrong: the checkpoint you want may "
                         "not be the one it picked. 0 = off. Recommended: 4.")
    ap.add_argument("--seed", type=int, default=0,
                    help="seeds python/numpy/torch and the DataLoader workers. "
                         "SET THE SAME VALUE ON BOTH SIDES OF AN A/B or a "
                         "2-point val difference cannot be attributed. None "
                         "disables seeding.")
    ap.add_argument("--fragment-weight", type=float, default=1.0,
                    help="TIER 2b. Mirror of --collision-weight: penalises "
                         "TWO queries splitting ONE GT building. New in "
                         "run2 and ON by default, because run1 showed the "
                         "one-sided collision term left merges unchanged "
                         "(5.1%% -> 5.2%%) while fragmentation got worse "
                         "(7.3%% -> 9.9%%) and thin slivers went 0.3%% -> "
                         "6.0%%. Set 0 to reproduce run1.")
    ap.add_argument("--collision-active-thr", type=float, default=0.2,
                    help="a query counts as 'active' (and so is charged) once "
                         "it covers this fraction of some GT instance")
    ap.add_argument("--crowd-weight", type=float, default=3.0,
                    help="TIER 2. Extra weight the boundary loss puts on the "
                         "band where two buildings are within --crowd-gap px "
                         "of each other -- the narrow alleys that get merged. "
                         "Needs --boundary-weight > 0 to do anything.")
    ap.add_argument("--crowd-gap", type=int, default=3,
                    help="how close (in mask-logit px) two instances must be "
                         "to count as a crowded pair")
    args = ap.parse_args()

    if args.crowd_weight > 0 and args.boundary_weight <= 0:
        print("[warn] --crowd-weight has no effect while --boundary-weight is 0")

    # Seed everything reachable. Without this, two runs differing only in a
    # loss weight are not comparable: augmentation (mosaic, rotation, scale) is
    # driven by np.random, the IoU head and adapter are randomly initialised,
    # and DataLoader shuffles. Comparing run1 to run2 on a ~2-point val
    # difference was guesswork for exactly this reason.
    if args.seed is not None:
        import random
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed)
        print(f"[run] seed {args.seed}")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    # Training starts from a clean directory: stale checkpoints and an appended
    # loss_log.csv from a previous attempt are worse than useless (see
    # fresh_run_dir).
    fresh_run_dir(args.out)
    # First write happens before anything can fail, so even a run that dies in
    # from_pretrained leaves a record of what it was asked to do.
    cfg_path = save_run_config(args.out, args)
    print(f"[run] config -> {cfg_path}")

    processor = Mask2FormerImageProcessor(
        do_resize=True,
        size={"height": args.image_size, "width": args.image_size},
        do_normalize=True,
        image_mean=[0.485, 0.456, 0.406],   # DINOv3 uses ImageNet stats
        image_std=[0.229, 0.224, 0.225],
        do_reduce_labels=False,
        ignore_index=255,
    )

    root = Path(args.data_root)
    tr = BuildingInstanceDataset(root / "train", root / "train/annotations.json",
                                 processor, augment=True,
                                 p_mosaic=args.p_mosaic,
                                 p_rot_any=args.p_rot_any,
                                 p_scale=args.p_scale,
                                 out_size=args.image_size,
                                 crowd=args.crowd,
                                 max_instances=args.num_queries,
                                 rot_mode=args.rot_mode)
    # Val uses the SAME crowd policy as train, so the val loss stays a
    # like-for-like number across the two settings. Scoring against the COCO
    # ground truth is eval.py's job, and it ignores crowd properly.
    va = BuildingInstanceDataset(root / "val", root / "val/annotations.json",
                                 processor, augment=False, crowd=args.crowd)
    print(f"[data] train={len(tr)} val={len(va)}")

    # worker_init_fn: each DataLoader worker is a separate process with its own
    # np.random state, and without this they all inherit the same seed and draw
    # IDENTICAL augmentations -- so 4 workers would produce 4 copies of every
    # augmented sample rather than 4 different ones.
    def _winit(wid):
        if args.seed is not None:
            np.random.seed(args.seed + 1000 * (wid + 1))

    tl = DataLoader(tr, batch_size=args.batch_size, shuffle=True,
                    num_workers=4, collate_fn=collate, drop_last=True,
                    worker_init_fn=_winit)
    vl = DataLoader(va, batch_size=args.batch_size, shuffle=False,
                    num_workers=4, collate_fn=collate)

    model = build_model(args.dinov3, args.m2f,
                        num_labels=1, image_size=args.image_size,
                        backbone=args.backbone,
                        use_stem=not args.no_stem,
                        num_queries=args.num_queries,
                        unfreeze_last=args.unfreeze_last,
                        taps=args.taps,
                        maskiou=args.maskiou_weight > 0,
                        maskiou_hidden=args.maskiou_hidden).to(dev)

    trainable = [p for p in model.parameters() if p.requires_grad]
    total = sum(p.numel() for p in model.parameters())
    print(f"[params] trainable {sum(p.numel() for p in trainable)/1e6:.1f}M "
          f"/ total {total/1e6:.1f}M")

    # adapter (pyramid + stem + laterals) is randomly initialized ->
    # higher LR than the COCO-pretrained head.
    #
    # ORDER MATTERS: the backbone lives INSIDE pixel_level_module.encoder, so
    # testing for the adapter first would hand a pretrained 300M ViT the 10x
    # adapter rate and destroy it in a few hundred steps.
    adapter, head, backbone = [], [], []
    for n, p in model.named_parameters():
        if not p.requires_grad:
            continue
        if ".encoder.vit." in n or ".encoder.net." in n:
            backbone.append(p)
        elif "pixel_level_module.encoder" in n or n.startswith("maskiou_head."):
            # The IoU head belongs with the adapter, not the head: both are
            # randomly initialised and neither inherits anything from COCO.
            # At 1x it converges long after the masks have stopped moving,
            # which wastes most of the schedule.
            adapter.append(p)
        else:
            head.append(p)

    groups = [{"params": adapter, "lr": args.lr * 10},
              {"params": head, "lr": args.lr}]
    maxlr = [args.lr * 10, args.lr]
    if backbone:
        blr = args.lr * args.backbone_lr_mult
        groups.append({"params": backbone, "lr": blr})
        maxlr.append(blr)
        print(f"[params] backbone {sum(p.numel() for p in backbone)/1e6:.1f}M "
              f"@ {blr:.2e} | adapter {sum(p.numel() for p in adapter)/1e6:.1f}M "
              f"@ {args.lr*10:.2e} | head {sum(p.numel() for p in head)/1e6:.1f}M "
              f"@ {args.lr:.2e}")

    opt = torch.optim.AdamW(groups, weight_decay=0.05)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=maxlr,
        total_steps=args.epochs * len(tl), pct_start=0.1)
    scaler = torch.amp.GradScaler(dev, enabled=(dev == "cuda"))

    # Everything here is RESOLVED rather than requested: `--taps auto` becomes
    # the block indices it actually picked, `--num-queries` becomes the count
    # the model ended up with. Recording the request alone is what makes two
    # runs look identical when they were not.
    enc = model.model.pixel_level_module.encoder
    save_run_config(args.out, args, derived={
        "device": dev,
        "params_total_M": round(total / 1e6, 2),
        "params_trainable_M": round(sum(p.numel() for p in trainable) / 1e6, 2),
        "params_adapter_M": round(sum(p.numel() for p in adapter) / 1e6, 3),
        "params_head_M": round(sum(p.numel() for p in head) / 1e6, 3),
        "params_backbone_M": round(sum(p.numel() for p in backbone) / 1e6, 3),
        "lr_adapter": args.lr * 10,
        "lr_head": args.lr,
        "lr_backbone": (args.lr * args.backbone_lr_mult) if backbone else None,
        "num_queries_effective": int(model.config.num_queries),
        "taps_resolved": list(getattr(enc, "taps", None) or []) or None,
        "taps_note": ("hidden_states indices, i.e. block index + 1"
                      if getattr(enc, "taps", None) else "single-layer (v1)"),
        "has_maskiou_head": hasattr(model, "maskiou_head"),
        "maskiou_detached": not args.no_maskiou_detach,
        "patch_size": getattr(enc, "patch_size", None),
        "token_grid": (args.image_size // enc.patch_size
                       if getattr(enc, "patch_size", None) else None),
        "tiles_train": len(tr), "tiles_val": len(va),
        "instances_train": tr.n_inst, "crowd_train": tr.n_crowd,
        "instances_val": va.n_inst, "crowd_val": va.n_crowd,
        "steps_per_epoch": len(tl),
        "total_steps": args.epochs * len(tl),
    })

    def aux_losses(out, mls):
        """
        The three v2 terms. Returns (total, {name: float}) so the progress bar
        and the epoch line can report each one separately -- with four terms
        summed into one number, a term that silently collapses to zero or
        explodes is invisible.

        Computed OUTSIDE autocast: all three do elementwise log / division
        arithmetic on probabilities, which bf16 either refuses (BCE) or
        quantises badly (a coverage ratio of 0.02 has ~2 bf16 mantissa bits).
        The tensors are already fp32 internally; this just stops autocast from
        re-casting the matmuls inside `collision_loss`.
        """
        parts, total = {}, None
        if args.boundary_weight > 0:
            lb = boundary_loss(out, mls, width=args.boundary_width,
                               crowd_weight=args.crowd_weight,
                               crowd_gap=args.crowd_gap)
            parts["bnd"] = float(lb.detach())
            total = args.boundary_weight * lb
        if args.collision_weight > 0:
            lc = collision_loss(out, mls,
                                active_thr=args.collision_active_thr)
            parts["col"] = float(lc.detach())
            total = args.collision_weight * lc if total is None else \
                total + args.collision_weight * lc
        if args.fragment_weight > 0:
            lf = fragmentation_loss(out, mls,
                                    active_thr=args.collision_active_thr)
            parts["frg"] = float(lf.detach())
            total = args.fragment_weight * lf if total is None else \
                total + args.fragment_weight * lf
        if args.maskiou_weight > 0 and hasattr(model, "maskiou_head"):
            tgt = maskiou_targets(out, mls)
            pred = predict_iou(model, out, detach=not args.no_maskiou_detach)
            # L2, as in Mask Scoring R-CNN. Averaged over ALL queries including
            # the parked ones: "my mask is worthless" is exactly what we need a
            # parked query to predict, so those are training signal, not noise.
            li = ((pred - tgt) ** 2).mean()
            parts["iou"] = float(li.detach())
            # reported separately: MAE is readable (0.05 == "5 IoU points out"),
            # the L2 is not
            parts["iou_mae"] = float((pred - tgt).abs().mean().detach())
            total = args.maskiou_weight * li if total is None else \
                total + args.maskiou_weight * li
        return total, parts

    # AP is maximised, loss minimised; one sign flip rather than two
    # branches at every comparison and every print.
    higher_better = args.select_by == "ap"
    best, best_ep = (-1.0 if higher_better else float("inf")), None
    print(f"[select] best_ep*.pth chosen by val {args.select_by.upper()}"
          + ("" if higher_better else "  (legacy criterion, see --select-by)"))
    for ep in range(args.epochs):
        t_ep = time.time()
        model.train()
        run = 0.0
        acc = {}
        bar = tqdm(tl, desc=f"ep {ep+1}/{args.epochs}", unit="b", leave=False,
                   dynamic_ncols=True)
        for step, batch in enumerate(bar):
            opt.zero_grad(set_to_none=True)
            px = batch["pixel_values"].to(dev)
            if args.basa_p > 0:
                # Batch-level, so it cannot live in __getitem__. Applied after
                # the processor's normalization, and never at val/inference.
                px = basa(px, p=args.basa_p)
            mls = [m.to(dev) for m in batch["mask_labels"]]
            with torch.amp.autocast(dev, dtype=torch.bfloat16, enabled=(dev == "cuda")):
                out = model(
                    pixel_values=px,
                    mask_labels=mls,
                    class_labels=[c.to(dev) for c in batch["class_labels"]],
                )
            loss = out.loss
            extra, parts = aux_losses(out, mls)
            if extra is not None:
                loss = loss + extra
            for k, v in parts.items():
                acc[k] = acc.get(k, 0.0) + v
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(trainable, 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            run += out.loss.item()
            # running mean, not the instantaneous value: with batch-size 2 and
            # 26-95 instances per tile the per-step loss swings too much to
            # read a trend from
            post = {"loss": f"{run/(step+1):.3f}"}
            for k in ("bnd", "col", "frg", "iou_mae"):
                if k in acc:
                    post[k] = f"{acc[k]/(step+1):.3f}"
            post["lr"] = f"{sched.get_last_lr()[0]:.2e}"
            bar.set_postfix(post, refresh=False)
        bar.close()

        model.eval()
        vloss, vmae, vn = 0.0, 0.0, 0
        vauc, vmpos, vnp = 0.0, 0.0, 0
        # cls_iou is what infer.py defaults to and what the AP numbers in the
        # README were produced with; without the head it is not an option.
        sel_mode = ("cls_iou" if hasattr(model, "maskiou_head") else "cls_mq")
        vpreds = []
        with torch.no_grad():
            for batch in tqdm(vl, desc=f"ep {ep+1} val", unit="b", leave=False,
                              dynamic_ncols=True):
                mls = [m.to(dev) for m in batch["mask_labels"]]
                out = model(
                    pixel_values=batch["pixel_values"].to(dev),
                    mask_labels=mls,
                    class_labels=[c.to(dev) for c in batch["class_labels"]],
                )
                vloss += out.loss.item()
                # Model selection stays on the BASE loss (below), but the IoU
                # head's val MAE is the only direct read on whether Tier 1 is
                # working, and it is invisible in the base loss by design --
                # the head is detached from it.
                p = predict_iou(model, out)
                if args.select_by == "ap":
                    ids = [va.ids[j] for j in batch["idx"]]
                    sizes = [(va.coco.imgs[i]["height"], va.coco.imgs[i]["width"])
                             for i in ids]
                    vpreds += val_predictions(out, p, ids, sizes, sel_mode)
                if p is not None:
                    st = iou_head_stats(p, maskiou_targets(out, mls))
                    vmae += st["mae"]
                    if st["auc"] is not None:
                        vauc += st["auc"]
                        vmpos += st["mae_pos"]
                        vnp += 1
                    vn += 1
        vloss /= max(len(vl), 1)
        vap = None
        if args.select_by == "ap":
            from eval import coco_ap
            # No predictions at all is a real state early in training, and
            # coco_ap returns {} for it. Treat it as AP 0 rather than letting a
            # KeyError kill the run at epoch 1.
            vap = float(coco_ap(va.coco, vpreds).get("AP", 0.0)) if vpreds else 0.0
        crit = vap if higher_better else vloss
        # evaluate BEFORE `best` is updated
        improved = (crit > best) if higher_better else (crit < best)
        msg = (f"[ep {ep+1}/{args.epochs}] train {run/max(len(tl),1):.4f}  "
               f"val {vloss:.4f}")
        if vap is not None:
            msg += f"  AP {vap:.4f}"
        for k in ("bnd", "col", "frg"):
            if k in acc:
                msg += f"  {k} {acc[k]/max(len(tl),1):.4f}"
        if vn:
            # AUC first: it is the number that tracks AP. MAE over all 200
            # queries is ~87% parked queries and is nearly unreadable as
            # progress -- see heads.iou_head_stats.
            if vnp:
                msg += f"  iou_auc {vauc/vnp:.3f}  iou_mae+ {vmpos/vnp:.3f}"
            msg += f"  iou_mae {vmae/vn:.4f}"
        tqdm.write(msg + ("  *" if improved else ""))

        # Built ONCE and saved under both tags when this epoch is also the best.
        # state_dict() is ~1.6 GB here (the frozen backbone is in it too), so
        # materialising it twice for the same epoch is a second full copy in
        # RAM for no reason.
        payload = {
            "model": model.state_dict(),
            "epoch": ep + 1,          # 1-based, matching the log line
            "val": vloss,
            "val_ap": vap,
            "select_by": args.select_by,
            # Recorded so inference rebuilds the IDENTICAL architecture.
            # Without this, a stem/backbone/size mismatch loads with
            # strict=False and silently produces garbage (verified: 8 missing
            # keys, no error).
            "cfg": {"dinov3": args.dinov3, "m2f": args.m2f,
                    "backbone": args.backbone,
                    "use_stem": not args.no_stem,
                    "image_size": args.image_size,
                    "num_queries": args.num_queries,
                    # v2: infer.py must rebuild the taps and the head or every
                    # trained weight lands in the wrong place / not at all.
                    "taps": args.taps,
                    "maskiou": args.maskiou_weight > 0,
                    "maskiou_hidden": args.maskiou_hidden,
                    "crowd": args.crowd},
        }
        # `last` only on the FINAL epoch. Writing it every epoch cost ~13 s
        # of the 115 s epoch here (a ~1.6 GB state_dict, backbone included),
        # i.e. ~13 min over 60 epochs, for a file that is normally never
        # loaded. The trade: a run killed mid-way now leaves only
        # best_ep*.pth, so the newest weights are the best ones rather than
        # the latest ones.
        last_path = (save_ckpt(args.out, "last", ep + 1, payload)
                     if ep + 1 == args.epochs else None)
        best_path = None
        if improved:
            best, best_ep = crit, ep + 1
            best_path = save_ckpt(args.out, "best", ep + 1, payload)
            tqdm.write(f"  saved {best_path.name} "
                       f"({args.select_by} {crit:.4f})")
        # Periodic snapshots are independent of the criterion -- that is the
        # entire point of them.
        if args.ckpt_every and (ep + 1) % args.ckpt_every == 0:
            snap = save_ckpt(args.out, "snap", ep + 1, payload, roll=False)
            tqdm.write(f"  saved {snap.name} (periodic)")

        if args.p_mosaic > 0 and tr.n_mosaic_skipped:
            tqdm.write(f"  [mosaic] {tr.n_mosaic_skipped} draws so far fell back "
                       f"to a plain tile (would have exceeded "
                       f"{args.num_queries} queries)")

        # One row per epoch, appended. This is the artefact that must survive a
        # kill with its history intact, which is why it is appended rather than
        # rewritten like run_config.json.
        append_loss_row(args.out, {
            "epoch": ep + 1,
            "train": run / max(len(tl), 1),
            "val": vloss,
            "val_ap": vap,
            "bnd": (acc["bnd"] / max(len(tl), 1)) if "bnd" in acc else None,
            "col": (acc["col"] / max(len(tl), 1)) if "col" in acc else None,
            "frg": (acc["frg"] / max(len(tl), 1)) if "frg" in acc else None,
            "iou_l2": (acc["iou"] / max(len(tl), 1)) if "iou" in acc else None,
            "iou_auc": (vauc / vnp) if vnp else None,
            "iou_mae_pos": (vmpos / vnp) if vnp else None,
            "iou_mae_all": (vmae / vn) if vn else None,
            "lr_head": sched.get_last_lr()[1],
            "is_best": improved,
            "secs": round(time.time() - t_ep, 1),
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
        })

        # Rewritten every epoch, not only at the end: the common way a 60-epoch
        # run ends is being killed, and a config file that only records
        # finished runs is missing exactly the ones you need to look at.
        # The checkpoint names go in it because they carry an epoch number and
        # therefore change during the run.
        save_run_config(args.out, args, result={
            "epochs_completed": ep + 1,
            "select_by": args.select_by,
            "best_val": best,
            "last_val_ap": vap,
            "best_epoch": best_ep,
            "best_ckpt": (best_path or Path(args.out) /
                          f"best_ep{best_ep:02d}.pth").name,
            "last_ckpt": last_path.name if last_path else None,
            "last_val": vloss,
            "last_train": run / max(len(tl), 1),
            "last_boundary": (acc["bnd"] / max(len(tl), 1)) if "bnd" in acc else None,
            "last_collision": (acc["col"] / max(len(tl), 1)) if "col" in acc else None,
            "last_val_iou_mae": (vmae / vn) if vn else None,
        })

    save_run_config(args.out, args, result={"finished": True})
    print(f"[done] best val {args.select_by} {best:.4f} at epoch {best_ep} -> "
          f"{Path(args.out)/f'best_ep{best_ep:02d}.pth'}")
    if args.ckpt_every:
        snaps = sorted(Path(args.out).glob("snap_ep*.pth"))
        print(f"[done] {len(snaps)} periodic snapshots kept: "
              f"{', '.join(s.name for s in snaps)}")
    print(f"[done] run config -> {Path(args.out)/'run_config.json'}")
    print(f"[done] infer with:  --ckpt {args.out}   "
          f"(resolves to the newest best_ep*.pth)")


# --------------------------------------------------------------------------
# 4. Inference
# --------------------------------------------------------------------------
@torch.no_grad()
def predict(model, processor, image, device="cuda", threshold=0.5):
    """Returns a list of (binary_mask, score). Feed these straight into MCR/PST."""
    model.eval()
    enc = processor(images=image, return_tensors="pt").to(device)
    out = model(pixel_values=enc["pixel_values"])

    res = processor.post_process_instance_segmentation(
        out,
        target_sizes=[image.shape[:2]],
        threshold=threshold,
        overlap_mask_area_threshold=0.8,
        return_binary_maps=True,          # per-instance binary masks
    )[0]

    masks = res["segmentation"]           # (N, H, W) or empty
    infos = res["segments_info"]
    if masks is None or len(infos) == 0:
        return []
    return [(masks[i].cpu().numpy().astype(np.uint8), s["score"])
            for i, s in enumerate(infos)]


if __name__ == "__main__":
    main()