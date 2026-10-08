"""
pst.py -- HoliTracer-style second-stage polygon refinement.

    mask -> MCR (uniform contour resampling) -> PST (learned tracer) -> polygon

The point of this stage, and why it is worth training at all: every geometric
polygonizer -- Douglas-Peucker, rectilinear snapping, line fitting -- can only
reshape the mask it is given. It has no way to know where the roof edge
actually is. PST samples IMAGE features at each contour point and regresses an
offset, so it can move a boundary that the mask got wrong.

Two components, following HoliTracer:

  MCR  Mask Contour Reformer. Not a network: contour -> Douglas-Peucker ->
       re-interpolate at a uniform spacing. The uniform spacing is what makes
       the sequence model tractable. During training it also labels which
       resampled points are real vertices, by matching against ground truth.

  PST  Polygon Sequence Tracer. A transformer over the point sequence that
       (a) iteratively regresses a position offset per point, DeepSnake-style,
       and (b) classifies each corrected point as vertex / not-vertex.

GSD WARNING. The paper's defaults (dp_eps 5, interp 25) are for 0.075 m/px
aerial imagery. At 0.5 m SkySat, interp=25 is 12.5 m between samples -- wider
than a whole side of a small workshop, leaving ~9 points around an entire
building. Defaults here are scaled for 0.5 m; set --gsd to rescale.

    # 1. build training pairs from predicted masks + GT polygons
    python pst.py prep --masks preds/ --coco data/train/annotations.json \\
        --images data/train/images --out pst_data.npz

    # 2. train
    python pst.py train --data pst_data.npz --out runs/pst

    # 3. apply to new masks
    python pst.py infer --ckpt runs/pst/best.pth --masks preds/ --out polys/
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


# ==========================================================================
# MCR -- Mask Contour Reformer
# ==========================================================================
def mcr(mask, dp_eps=1.0, interp=4.0, max_points=512):
    """
    Binary mask -> (M, 2) uniformly spaced contour points.

    Uniform spacing matters: PST is a sequence model and needs points at a
    predictable density. Douglas-Peucker output is neither dense nor evenly
    spaced, so feeding it directly would be out of distribution.
    """
    m = np.ascontiguousarray(mask.astype(np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_KCOS)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 16:
        return None

    simp = cv2.approxPolyDP(c.astype(np.float32), dp_eps, True).reshape(-1, 2)
    if len(simp) < 3:
        return None

    ring = np.vstack([simp, simp[:1]]).astype(np.float64)
    seg = np.linalg.norm(np.diff(ring, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total < interp * 4:
        return None
    n = int(min(np.ceil(total / interp), max_points))
    t = np.linspace(0.0, total, n, endpoint=False)
    return np.stack([np.interp(t, cum, ring[:, 0]),
                     np.interp(t, cum, ring[:, 1])], axis=1)


def match_gt(points, gt_poly, max_dist=8.0):
    """
    Label each resampled point: is it a vertex, and where should it move?

    Bidirectional: every GT vertex claims its nearest contour point (so no GT
    corner is missed), and any contour point already within max_dist of a GT
    vertex is also labelled positive (so near-misses are not taught as
    negatives). Targets are offsets to the nearest point on the GT OUTLINE,
    not to the nearest vertex -- pulling every point toward a corner would
    collapse the edges.
    """
    P = points
    G = np.asarray(gt_poly, dtype=np.float64)
    ring = np.vstack([G, G[:1]])

    # offset target: closest point on each GT segment
    best = np.full(len(P), np.inf)
    tgt = P.copy()
    for a, b in zip(ring[:-1], ring[1:]):
        ab = b - a
        L2 = float(ab @ ab)
        if L2 < 1e-9:
            continue
        t = np.clip(((P - a) @ ab) / L2, 0.0, 1.0)[:, None]
        proj = a + t * ab
        d = np.linalg.norm(P - proj, axis=1)
        upd = d < best
        best[upd] = d[upd]
        tgt[upd] = proj[upd]

    # vertex labels
    lab = np.zeros(len(P), np.float32)
    d_to_vert = np.linalg.norm(P[:, None, :] - G[None, :, :], axis=2)
    lab[d_to_vert.min(1) < max_dist] = 1.0
    lab[np.argmin(d_to_vert, axis=0)] = 1.0        # every GT vertex claims one
    return tgt - P, lab, best


# ==========================================================================
# PST -- Polygon Sequence Tracer
# ==========================================================================
def sample_features(feat, pts, H, W):
    """Bilinear-sample a (C, h, w) feature map at (N, 2) pixel coords."""
    g = pts.clone()
    g[:, 0] = g[:, 0] / max(W - 1, 1) * 2 - 1
    g[:, 1] = g[:, 1] / max(H - 1, 1) * 2 - 1
    out = F.grid_sample(feat[None], g[None, None], mode="bilinear",
                        padding_mode="border", align_corners=True)
    return out[0, :, 0].transpose(0, 1)             # (N, C)


def angle_features(pts, scales=(1, 2, 3)):
    """
    Turn angle at each point, measured at several neighbour distances.

    A corner looks like a corner at every scale; boundary noise looks like one
    only at s=1. Giving the classifier all three lets it tell them apart.
    """
    out = []
    for s in scales:
        prev = torch.roll(pts, s, 0)
        nxt = torch.roll(pts, -s, 0)
        a = prev - pts
        b = nxt - pts
        a = a / (a.norm(dim=1, keepdim=True) + 1e-6)
        b = b / (b.norm(dim=1, keepdim=True) + 1e-6)
        cos = (a * b).sum(1, keepdim=True)
        cross = (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])[:, None]
        out += [cos, cross]
    return torch.cat(out, dim=1)                    # (N, 2*len(scales))


class PST(nn.Module):
    def __init__(self, feat_dim=256, d_model=256, nhead=8, layers=3,
                 iters=3, scales=(1, 2, 3), offset_scale=1.0):
        super().__init__()
        self.iters = iters
        self.scales = scales
        # Multiplier on the predicted offset.
        #
        # I added this believing the near-zero head init was what limited
        # offset recovery to ~23%. Testing did not support that: with
        # INFORMATIVE features and enough steps, scale 1.0 reached 103-108% of
        # the target, and scale 10.0 overshot to 161%. The earlier
        # under-correction was under-training and uninformative features, not
        # the parameterisation. Left at 1.0 (a no-op) and exposed only as a
        # convergence knob; raising it makes offsets larger and less stable.
        self.offset_scale = offset_scale

        self.feat_proj = nn.Linear(feat_dim, d_model - 2)
        enc = lambda: nn.TransformerEncoder(
            nn.TransformerEncoderLayer(d_model, nhead, d_model * 4,
                                       batch_first=True, norm_first=True),
            layers)
        self.offset_tf = enc()
        self.offset_head = nn.Linear(d_model, 2)

        self.vtx_in = nn.Linear(d_model + 2 * len(scales), d_model)
        self.vtx_tf = enc()
        self.vtx_head = nn.Linear(d_model, 1)

    def forward(self, feat, pts, H, W):
        """
        feat: (C, h, w) image features, frozen upstream
        pts : (N, 2) contour points in pixel coords
        returns refined points (N, 2) and vertex logits (N,)
        """
        cur = pts
        offs = []
        for _ in range(self.iters):
            f = self.feat_proj(sample_features(feat, cur, H, W))
            norm = torch.stack([cur[:, 0] / W, cur[:, 1] / H], 1) * 2 - 1
            x = torch.cat([f, norm], 1)[None]
            d = self.offset_head(self.offset_tf(x))[0] * self.offset_scale
            cur = cur + d
            offs.append(cur)

        f = self.feat_proj(sample_features(feat, cur, H, W))
        norm = torch.stack([cur[:, 0] / W, cur[:, 1] / H], 1) * 2 - 1
        ang = angle_features(cur, self.scales)
        x = self.vtx_in(torch.cat([f, norm, ang], 1))[None]
        logit = self.vtx_head(self.vtx_tf(x))[0, :, 0]
        return cur, logit, offs


def pst_loss(pred_pts, logits, offs, tgt_off, vtx_lab, pts0,
             w_off=1.0, w_vtx=2.0, w_ang=1.0, theta_thr=135.0, pos_weight=7.6):
    """
    Smooth-L1 on offsets (supervised at every iteration, not just the last),
    BCE on vertex classification, plus an angle penalty that discourages
    predicting a vertex where the turn is nearly straight.

    POS_WEIGHT IS NOT OPTIONAL. Only ~11.7% of resampled contour points are
    vertices, and plain BCE has an easy optimum -- predict negative everywhere,
    loss 0.124. The model finds it, corner detection never learns, and at
    inference sigmoid(logit) > 0.5 returns nothing so every polygon falls back
    to the topk fixed count. (1 - p) / p = 7.6 rebalances it.

    w_vtx defaults to 2.0 because the offset term is ~56% of the loss at init
    and otherwise dominates.
    """
    tgt = pts0 + tgt_off
    l_off = sum(F.smooth_l1_loss(o, tgt) for o in offs) / len(offs)
    l_vtx = F.binary_cross_entropy_with_logits(
        logits, vtx_lab,
        pos_weight=torch.tensor(pos_weight, device=logits.device))

    ang = angle_features(pred_pts, (2,))
    cos = ang[:, 0].clamp(-1 + 1e-6, 1 - 1e-6)
    theta = torch.rad2deg(torch.acos(cos))
    straight = (theta > theta_thr).float()
    l_ang = (torch.sigmoid(logits) * straight).mean()

    total = w_off * l_off + w_vtx * l_vtx + w_ang * l_ang
    return total, {"off": float(l_off.detach()), "vtx": float(l_vtx.detach()),
                   "ang": float(l_ang.detach())}


# ==========================================================================
# features
# ==========================================================================
class FrozenFeatures(nn.Module):
    """
    Image -> (C, h, w) features, frozen.

    HoliTracer reuses the segmentation encoder. Here that is the same DINOv3
    you already train against, so PST sees exactly the representation the
    masks came from -- and costs no extra backbone.
    """

    def __init__(self, model_id="facebook/dinov3-convnext-large-pretrain-lvd1689m",
                 out_dim=256, device="cpu"):
        super().__init__()
        from transformers import AutoModel
        self.net = AutoModel.from_pretrained(model_id).to(device).eval()
        for p in self.net.parameters():
            p.requires_grad = False
        cfg = self.net.config
        c = (cfg.hidden_sizes[0] if hasattr(cfg, "hidden_sizes")
             else cfg.hidden_size)
        self.proj = nn.Conv2d(c, out_dim, 1)
        self.mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)

    @torch.no_grad()
    def _raw(self, img_u8, device):
        """
        Image -> (1, C, h, w) spatial features.

        ConvNeXt and ViT report hidden_states in DIFFERENT shapes, and the
        branch has to be chosen on dimensionality, not on how many entries
        there are:

          ConvNeXt  hidden_states[i] is (B, C, h, w)   -- already spatial
          ViT       hidden_states[i] is (B, N, D)      -- token sequence

        Selecting hs[1] unconditionally handed a ViT's layer-1 tokens
        (1, 1029, 1024) to a Conv2d, which reads a 3-D input as (C, H, W) and
        therefore saw 1 channel where 1024 were expected.
        """
        x = torch.from_numpy(img_u8).permute(2, 0, 1).float().div(255)
        x = ((x - self.mean) / self.std)[None].to(device)
        H, W = x.shape[-2:]
        o = self.net(x, output_hidden_states=True)

        hs = getattr(o, "hidden_states", None)
        if hs is not None and len(hs) > 1 and hs[1].dim() == 4:
            return hs[1]                       # ConvNeXt stage 1, stride 4

        # ViT: drop the prefix tokens (CLS + registers) and fold back to 2-D.
        # The prefix count is derived from the patch grid rather than assumed,
        # since DINOv3 carries 4 register tokens on top of CLS.
        t = o.last_hidden_state
        patch = getattr(self.net.config, "patch_size", 16)
        gh, gw = H // patch, W // patch
        n_prefix = t.shape[1] - gh * gw
        if n_prefix < 0:
            raise RuntimeError(
                f"token count {t.shape[1]} is smaller than the {gh}x{gw} patch "
                f"grid for a {H}x{W} input at patch {patch}")
        return t[:, n_prefix:].transpose(1, 2).reshape(1, -1, gh, gw)

    def forward(self, img_u8, device="cpu"):
        return self.proj(self._raw(img_u8, device))[0]


def rectify(pts, dp_eps=2.0, angle_tol=25.0, min_edge=4.0):
    """
    Impose right angles on PST's output.

    PST is a TRACER, not a regularizer -- none of its losses mention 90
    degrees, so it follows the true contour and leaves the vertex spacing that
    MCR gave it. Measured on real output: median 17 vertices, evenly spread
    along edges. The rectilinearity in the geometric pipeline came from the
    dominant-angle rotation and axis snapping in polygonize.regularize(), and
    replacing that step with PST simply removed it.

    So snap PST's points rather than choosing between the two: PST supplies
    what geometry cannot (image-informed boundary correction), snapping
    supplies what PST cannot (the rectilinear prior). Measured 17 -> 4
    vertices at IoU 0.97-0.99 against the true rectangle.
    """
    from polygonize import _rot, _snap_axis, _drop_short_and_collinear
    p = np.asarray(pts, dtype=np.float64)
    if len(p) < 4:
        return p
    theta = cv2.minAreaRect(p.astype(np.float32))[2] % 90.0
    ctr = p.mean(axis=0)
    q = _rot(p, -theta, ctr)
    q = cv2.approxPolyDP(q.astype(np.float32), dp_eps, True).reshape(-1, 2)
    q = q.astype(np.float64)
    if len(q) < 4:
        return p
    q = _snap_axis(q, angle_tol=angle_tol)
    q = _drop_short_and_collinear(q, min_edge=min_edge)
    if len(q) < 4:
        return p
    return _rot(q, theta, ctr)


# ==========================================================================
# visualization
# ==========================================================================
def _caption(img, text):
    bar = np.zeros((26, img.shape[1], 3), np.uint8)
    cv2.putText(bar, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA)
    return np.concatenate([bar, img], axis=0)


def overlay_panels(img, insts, polys, alpha=0.42, seed=0):
    """
    raw | mask | polygon, side by side, sharing one colour per instance so a
    building can be followed across the three panels.
    """
    rng = np.random.default_rng(seed)
    n = max(len(insts), len(polys))
    cols = [rng.integers(60, 255, 3).tolist() for _ in range(n)]

    lay = img.copy()
    for k, m in enumerate(insts):
        lay[m] = cols[k % len(cols)]
    mask_vis = cv2.addWeighted(lay, alpha, img, 1 - alpha, 0)

    lay = img.copy()
    for k, p in enumerate(polys):
        pts = np.round(np.asarray(p)).astype(np.int32)
        if len(pts) >= 3:
            cv2.fillPoly(lay, [pts], cols[k % len(cols)])
    poly_vis = cv2.addWeighted(lay, alpha, img, 1 - alpha, 0)
    for k, p in enumerate(polys):
        pts = np.round(np.asarray(p)).astype(np.int32)
        if len(pts) < 3:
            continue
        cv2.polylines(poly_vis, [pts], True, cols[k % len(cols)], 2, cv2.LINE_AA)
        for (x, y) in pts:                    # vertex markers: where PST put corners
            cv2.circle(poly_vis, (int(x), int(y)), 3, (255, 255, 255), -1)
            cv2.circle(poly_vis, (int(x), int(y)), 3, (0, 0, 0), 1)

    nv = [len(p) for p in polys]
    return np.concatenate([
        _caption(img, "raw"),
        _caption(mask_vis, f"mask  (n={len(insts)})"),
        _caption(poly_vis, f"PST polygon  (n={len(polys)}"
                 + (f", verts med {int(np.median(nv))} max {max(nv)})" if nv else ")")),
    ], axis=1)                                # axis=1 -> horizontal


# ==========================================================================
# CLI
# ==========================================================================
def cmd_prep(a):
    from pycocotools.coco import COCO
    from PIL import Image
    coco = COCO(a.coco)
    interp = a.interp * (0.5 / a.gsd)
    dp = a.dp_eps * (0.5 / a.gsd)
    print(f"[prep] gsd {a.gsd} m/px -> interp {interp:.1f}px, dp_eps {dp:.1f}px")

    from tqdm import tqdm
    samples = []
    for f in tqdm(sorted(Path(a.masks).glob("*_masks.npz")), desc="prep", unit="tile"):
        stem = f.stem[:-6]
        img_p = next((Path(a.images) / f"{stem}{e}" for e in
                      (".png", ".jpg", ".tif") if (Path(a.images) / f"{stem}{e}").exists()), None)
        if img_p is None:
            continue
        iid = next((i for i in coco.imgs if Path(coco.imgs[i]["file_name"]).stem == stem), None)
        if iid is None:
            continue
        gts = [np.array(an["segmentation"][0]).reshape(-1, 2)
               for an in coco.loadAnns(coco.getAnnIds(iid, iscrowd=False))
               if an.get("segmentation")]
        if not gts:
            continue
        z = np.load(f)
        b, s = z["boxes"], z["scores"]
        for i in range(len(s)):
            m = np.zeros(tuple(int(v) for v in z["shape"]), bool)
            m[int(b[i][1]):int(b[i][3]), int(b[i][0]):int(b[i][2])] = z[f"m{i}"]
            pts = mcr(m, dp, interp)
            if pts is None or len(pts) < 8:
                continue
            # pair with the GT polygon whose centroid is nearest
            cen = pts.mean(0)
            gt = min(gts, key=lambda g: np.linalg.norm(g.mean(0) - cen))
            if np.linalg.norm(gt.mean(0) - cen) > a.max_pair_dist:
                continue
            off, lab, dist = match_gt(pts, gt)
            if dist.mean() > a.max_pair_dist:
                continue
            samples.append({"img": str(img_p), "pts": pts.astype(np.float32),
                            "off": off.astype(np.float32), "lab": lab})
    print(f"[prep] {len(samples)} (contour, GT) pairs")
    if not samples:
        raise SystemExit("no pairs -- check --masks / --coco / --images pairing")
    np.savez_compressed(a.out, meta=json.dumps([s["img"] for s in samples]),
                        **{f"p{i}": s["pts"] for i, s in enumerate(samples)},
                        **{f"o{i}": s["off"] for i, s in enumerate(samples)},
                        **{f"l{i}": s["lab"] for i, s in enumerate(samples)})
    print(f"[save] {a.out}")


def cmd_train(a):
    from PIL import Image
    from tqdm import tqdm
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    z = np.load(a.data)
    imgs = json.loads(str(z["meta"]))
    n = len(imgs)

    # Split by IMAGE, not by sample: contours from the same tile share pixels,
    # so a per-sample split would leak.
    uniq = sorted(set(imgs))
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(uniq))
    cut = max(1, int(len(uniq) * 0.85))
    tr_imgs = {uniq[i] for i in perm[:cut]}
    tr = np.array([k for k in range(n) if imgs[k] in tr_imgs])
    va = np.array([k for k in range(n) if imgs[k] not in tr_imgs])

    # Group samples by image. The feature cache is keyed by image, so a
    # shuffled order thrashes it: measured 84.6% misses vs 3.8% when grouped,
    # i.e. 22x more backbone forwards than necessary. This IS the epoch time.
    def group(ids):
        by = {}
        for k in ids:
            by.setdefault(imgs[k], []).append(k)
        return by

    tr_by, va_by = group(tr), group(va)
    print(f"[train] {len(tr)} samples / {len(tr_by)} tiles  |  "
          f"val {len(va)} samples / {len(va_by)} tiles")

    feat = FrozenFeatures(a.dinov3, a.feat_dim, dev).to(dev)
    model = PST(a.feat_dim, iters=a.iters,
                offset_scale=a.offset_scale).to(dev)
    trainable = list(model.parameters()) + list(feat.proj.parameters())
    print(f"[train] PST {sum(p.numel() for p in model.parameters())/1e6:.2f}M trainable")
    opt = torch.optim.AdamW(trainable, lr=a.lr, weight_decay=0.05)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs)

    best = float("inf")
    Path(a.out).mkdir(parents=True, exist_ok=True)

    for ep in range(a.epochs):
        for split, by, train in (("train", tr_by, True), ("val", va_by, False)):
            model.train(train)
            keys = list(by)
            if train:
                rng.shuffle(keys)              # shuffle TILES, not samples
            tot = 0.0
            parts = {"off": 0.0, "vtx": 0.0, "ang": 0.0}
            nseen = 0
            pos_hit = 0.0
            bar = tqdm(keys, desc=f"ep{ep:02d} {split:5s}", leave=False,
                       unit="tile", dynamic_ncols=True)
            for path in bar:
                im = np.array(Image.open(path).convert("RGB"))
                H, W = im.shape[:2]
                with torch.no_grad():
                    raw = feat._raw(im, dev)   # ONE backbone pass per tile
                fm = feat.proj(raw)[0]

                if train:
                    opt.zero_grad(set_to_none=True)
                ks = by[path]
                # Sum over the tile and back-prop ONCE. All contours here share
                # the same fm, so per-sample backward would need retain_graph
                # and would traverse feat.proj len(ks) times.
                tile_loss = 0.0
                for k in ks:
                    pts = torch.from_numpy(z[f"p{k}"]).to(dev)
                    off = torch.from_numpy(z[f"o{k}"]).to(dev)
                    lab = torch.from_numpy(z[f"l{k}"]).to(dev)
                    with torch.set_grad_enabled(train):
                        pred, logit, offs = model(fm, pts, H, W)
                        loss, d = pst_loss(pred, logit, offs, off, lab, pts,
                                           w_vtx=a.w_vtx, pos_weight=a.pos_weight)
                    if train:
                        tile_loss = tile_loss + loss / len(ks)
                    tot += float(loss.detach())
                    for kk in parts:
                        parts[kk] += d[kk]
                    with torch.no_grad():
                        pos_hit += float(((torch.sigmoid(logit) > 0.5) &
                                          (lab > 0.5)).sum() / lab.sum().clamp_min(1))
                    nseen += 1
                if train:
                    tile_loss.backward()
                    torch.nn.utils.clip_grad_norm_(trainable, 1.0)
                    opt.step()
                bar.set_postfix(loss=f"{tot/max(nseen,1):.3f}",
                                vtx_recall=f"{pos_hit/max(nseen,1):.2f}")
            bar.close()
            m = max(nseen, 1)
            print(f"  ep{ep:02d} {split:5s} loss {tot/m:.4f}  "
                  + "  ".join(f"{kk} {v/m:.4f}" for kk, v in parts.items())
                  + f"  vtx_recall {pos_hit/m:.3f}")
            if split == "val" and tot / m < best:
                best = tot / m
                torch.save({"model": model.state_dict(),
                            "proj": feat.proj.state_dict(),
                            "cfg": {"feat_dim": a.feat_dim, "iters": a.iters,
                                    "dinov3": a.dinov3,
                                    "offset_scale": a.offset_scale}},
                           Path(a.out) / "best.pth")
                print(f"    saved (val {best:.4f})")
        sched.step()


def cmd_infer(a):
    from PIL import Image
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    ck = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    cfg = ck["cfg"]
    feat = FrozenFeatures(cfg["dinov3"], cfg["feat_dim"], dev).to(dev)
    feat.proj.load_state_dict(ck["proj"])
    model = PST(cfg["feat_dim"], iters=cfg["iters"],
                offset_scale=cfg.get("offset_scale", 1.0)).to(dev).eval()
    model.load_state_dict(ck["model"])
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    interp = a.interp * (0.5 / a.gsd)
    dp = a.dp_eps * (0.5 / a.gsd)

    from tqdm import tqdm
    for f in tqdm(sorted(Path(a.masks).glob("*_masks.npz")), desc="infer", unit="tile"):
        stem = f.stem[:-6]
        img_p = next((Path(a.images) / f"{stem}{e}" for e in (".png", ".jpg", ".tif")
                      if (Path(a.images) / f"{stem}{e}").exists()), None)
        if img_p is None:
            print(f"  [skip] no image for {stem}")
            continue
        img = np.array(Image.open(img_p).convert("RGB"))
        H, W = img.shape[:2]
        with torch.no_grad():
            fm = feat(img, dev)
        z = np.load(f)
        b, s = z["boxes"], z["scores"]
        polys = []
        full_masks = []
        for i in range(len(s)):
            m = np.zeros(tuple(int(v) for v in z["shape"]), bool)
            m[int(b[i][1]):int(b[i][3]), int(b[i][0]):int(b[i][2])] = z[f"m{i}"]
            pts = mcr(m, dp, interp)
            if pts is None or len(pts) < 8:
                continue
            with torch.no_grad():
                pred, logit, _ = model(fm, torch.from_numpy(pts).float().to(dev), H, W)
            keep = torch.sigmoid(logit) > a.vtx_thr
            if int(keep.sum()) < 4:
                k = torch.topk(logit, min(8, len(logit))).indices.sort().values
                keep = torch.zeros_like(logit, dtype=torch.bool)
                keep[k] = True
            v = pred[keep].cpu().numpy()
            n_raw = len(v)
            if a.rectify:
                v = rectify(v, a.dp_eps_rect, a.angle_tol, a.min_edge)
            polys.append({"polygon": v.tolist(), "score": float(s[i]),
                          "n_vertices": int(len(v)), "n_traced": int(n_raw)})
            full_masks.append(m)
        (out / f"{stem}_polys.json").write_text(json.dumps(
            {"shape": [H, W], "polygons": polys}))

        if a.viz:
            viz_dir = out / "overlay"
            viz_dir.mkdir(parents=True, exist_ok=True)
            vis = overlay_panels(img, full_masks,
                                 [p["polygon"] for p in polys], alpha=a.alpha)
            cv2.imwrite(str(viz_dir / f"{stem}_overlay.png"),
                        cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))

        v = [p["n_vertices"] for p in polys]
        t = [p.get("n_traced", p["n_vertices"]) for p in polys]
        print(f"  {stem}: {len(polys)} polygons, verts med "
              f"{int(np.median(v)) if v else 0}"
              + (f" (traced {int(np.median(t))} -> rectified {int(np.median(v))})"
                 if a.rectify and v else ""))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--gsd", type=float, default=0.5,
                       help="m/px. Spatial params are given for 0.5 and "
                            "rescaled from this.")
        p.add_argument("--interp", type=float, default=4.0)
        p.add_argument("--dp-eps", type=float, default=1.0)

    p = sub.add_parser("prep"); common(p)
    p.add_argument("--masks", required=True); p.add_argument("--coco", required=True)
    p.add_argument("--images", required=True); p.add_argument("--out", required=True)
    p.add_argument("--max-pair-dist", type=float, default=30.0)

    p = sub.add_parser("train")
    p.add_argument("--data", required=True); p.add_argument("--out", default="runs/pst")
    p.add_argument("--dinov3", default="facebook/dinov3-convnext-large-pretrain-lvd1689m")
    p.add_argument("--feat-dim", type=int, default=256)
    p.add_argument("--iters", type=int, default=3)
    p.add_argument("--offset-scale", type=float, default=1.0,
                   help="multiplier on the predicted offset. Tested: 1.0 "
                        "reaches 103-108%% of the target given informative "
                        "features and enough steps; 10.0 overshoots to 161%%. "
                        "Leave at 1.0 unless offsets converge too slowly.")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--w-vtx", type=float, default=2.0,
                   help="weight on vertex classification; the offset term is "
                        "~56%% of the loss at init and otherwise dominates")
    p.add_argument("--pos-weight", type=float, default=7.6,
                   help="BCE positive weight. Only ~11.7%% of points are "
                        "vertices; without this the model predicts all-negative "
                        "and corner detection never learns.")

    p = sub.add_parser("infer"); common(p)
    p.add_argument("--ckpt", required=True); p.add_argument("--masks", required=True)
    p.add_argument("--images", required=True); p.add_argument("--out", required=True)
    p.add_argument("--vtx-thr", type=float, default=0.5)
    p.add_argument("--rectify", action="store_true",
                   help="snap PST's traced points to right angles. PST has no "
                        "rectilinearity objective, so without this the output "
                        "keeps MCR's dense spacing (measured median 17 verts).")
    p.add_argument("--dp-eps-rect", type=float, default=2.0)
    p.add_argument("--angle-tol", type=float, default=25.0)
    p.add_argument("--min-edge", type=float, default=4.0)
    p.add_argument("--viz", action="store_true",
                   help="write raw|mask|polygon panels to <out>/overlay/")
    p.add_argument("--alpha", type=float, default=0.42)

    a = ap.parse_args()
    {"prep": cmd_prep, "train": cmd_train, "infer": cmd_infer}[a.cmd](a)


if __name__ == "__main__":
    main()