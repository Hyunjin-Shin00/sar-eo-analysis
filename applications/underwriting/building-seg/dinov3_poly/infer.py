"""
Stage 1 boxes -> stage 2 crops -> polygons.

TAKES STAGE 1's `_masks.npz` BY DEFAULT rather than re-running it. Detection is
unchanged by this project, those files already exist from dinov3_v2 runs, and
keeping the two stages decoupled means a stage-2 experiment costs one pass over
cached boxes instead of a full tiled scene inference. `--stage1-ckpt` runs
stage 1 inline when the npz is not available.

Writes `<stem>_polys.json` in dinov3_v2/polygonize.py's schema, so eval and
bench tooling reads it unchanged.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

from connect import build_polygon
from model import PolyNet
from targets import crop_window, decode

Image.MAX_IMAGE_PIXELS = None
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
MEAN = np.array([0.485, 0.456, 0.406], np.float32)[:, None, None]
STD = np.array([0.229, 0.224, 0.225], np.float32)[:, None, None]


def regularize_fn():
    """dinov3_v2's rule-based polygonizer, used only as the catastrophe floor."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dinov3_v2"))
    try:
        from polygonize import regularize
        return regularize
    except Exception as e:
        print(f"[warn] dinov3_v2.polygonize unavailable ({e}); "
              f"falling back to approxPolyDP for the guard")

        def _approx(m):
            c, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
            if not c:
                return None
            c = max(c, key=cv2.contourArea)
            p = cv2.approxPolyDP(c, 0.01 * cv2.arcLength(c, True), True)
            return p[:, 0, :].astype(np.float64) if len(p) >= 3 else None
        return _approx


SRC_COLOR = {"vertex": (60, 220, 120),     # the head did the work
             "angle": (250, 200, 60),      # contour walk failed, angular sort
             "baseline": (240, 70, 70)}    # guard fired, rule-based fallback


def draw_overlay(img, recs, alpha=0.35, dot=2, line=2):
    """
    Polygons on the image, COLOURED BY SOURCE.

    The colour is the diagnostic. A scene that looks good in green is the
    vertex head working; the same scene in red is `polygonize.regularize`
    doing the job behind a guard that fired on every instance, which would
    otherwise be invisible -- the polygons still look like buildings.
    """
    vis = img.copy()
    lay = img.copy()
    for r in recs:
        p = np.round(np.asarray(r["polygon"])).astype(np.int32)
        if len(p) < 3:
            continue
        c = SRC_COLOR.get(r.get("source", "vertex"), (200, 200, 200))
        cv2.fillPoly(lay, [p], c)
    vis = cv2.addWeighted(lay, alpha, vis, 1 - alpha, 0)
    for r in recs:
        p = np.round(np.asarray(r["polygon"])).astype(np.int32)
        if len(p) < 3:
            continue
        c = SRC_COLOR.get(r.get("source", "vertex"), (200, 200, 200))
        cv2.polylines(vis, [p], True, c, line, cv2.LINE_AA)
        if dot > 0:
            for x, y in p:
                cv2.circle(vis, (int(x), int(y)), dot, (90, 200, 255), -1,
                           cv2.LINE_AA)
    return vis


def caption(w, text, h=30):
    bar = np.zeros((h, w, 3), np.uint8)
    cv2.putText(bar, text, (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 1, cv2.LINE_AA)
    return bar


def two_panel(img, recs, counts, alpha=0.35, dot=2, line=2, scale=1.0):
    """Raw | overlay, side by side, each with its own caption bar."""
    vis = draw_overlay(img, recs, alpha=alpha, dot=dot, line=line)
    if scale != 1.0:
        wh = (max(1, int(img.shape[1] * scale)), max(1, int(img.shape[0] * scale)))
        img = cv2.resize(img, wh, interpolation=cv2.INTER_AREA)
        vis = cv2.resize(vis, wh, interpolation=cv2.INTER_AREA)
    w = img.shape[1]
    legend = "  ".join(f"{k} {counts.get(k, 0)}" for k in
                       ("vertex", "angle", "baseline") if counts.get(k))
    left = np.concatenate([caption(w, "image"), img], 0)
    right = np.concatenate([caption(w, f"polygons {len(recs)}   {legend}"), vis], 0)
    return np.concatenate([left, right], 1)


def side_of(m):
    ys, xs_ = np.nonzero(m)
    if len(ys) == 0:
        return 1.0
    return float(max(xs_.max() - xs_.min(), ys.max() - ys.min()) + 1)


def _norm(a):
    a = a.astype(np.float32)
    lo, hi = float(a.min()), float(a.max())
    return ((a - lo) / (hi - lo + 1e-9) * 255).astype(np.uint8)


def max_residual(poly, t, C):
    """Largest remaining arc-to-chord deviation, i.e. how close the next
    insertion was. Below `tol` and refinement stopped; that IS the answer to
    'why is that notch a V instead of a step'."""
    if poly is None or t is None or C is None or len(poly) < 3:
        return -1.0
    n, worst = len(C), 0.0
    for i in range(len(poly)):
        j = (i + 1) % len(poly)
        t0, t1 = int(t[i]), int(t[j])
        idx = (np.arange(t0 + 1, t1) if t1 > t0
               else np.concatenate([np.arange(t0 + 1, n), np.arange(0, t1)]))
        if len(idx) < 2:
            continue
        d = np.asarray(poly)[j] - np.asarray(poly)[i]
        L = np.linalg.norm(d)
        if L < 1e-9:
            continue
        worst = max(worst, float(np.abs(np.cross(d, C[idx] - np.asarray(poly)[i])).max() / L))
    return worst


def debug_panel(items, cell=180):
    """
    Four columns per instance: crop | mask + guide | heatmap + candidates |
    polygon with provenance.

    THE FOURTH COLUMN IS THE POINT. Detected corners are drawn cyan and
    mask-supplied ones magenta, so an unexpected step in a polygon is
    attributable on sight instead of by argument -- head or mask, which need
    opposite fixes (retrain / lower --vertex-thr, versus raise --refine-tol or
    --prune-width).
    """
    from connect import contour_of, prune_thin
    rows = []
    for rgb, m, vmap, cand, poly, meta, frame, side in items:
        xi, yi, n = frame
        S = m.shape[0]
        img = cv2.resize(_norm(rgb.transpose(1, 2, 0)), (cell, cell))
        sc = cell / float(S)

        mk = cv2.cvtColor((m.astype(np.uint8) * 90), cv2.COLOR_GRAY2RGB)
        C = contour_of(m)
        if C is not None:
            cv2.polylines(mk, [np.round(C).astype(np.int32)], True, (90, 90, 255), 1)
            P = prune_thin(C, 0.06 * side)
            cv2.polylines(mk, [np.round(P).astype(np.int32)], True, (60, 230, 120), 1)
        mk = cv2.resize(mk, (cell, cell), interpolation=cv2.INTER_NEAREST)

        hm = cv2.applyColorMap(_norm(vmap), cv2.COLORMAP_INFERNO)[:, :, ::-1].copy()
        hm = cv2.resize(hm, (cell, cell), interpolation=cv2.INTER_NEAREST)
        for x, y in np.asarray(cand).reshape(-1, 2):
            cv2.circle(hm, (int(x * sc), int(y * sc)), 3, (255, 255, 255), 1, cv2.LINE_AA)

        pv = cv2.resize(_norm(rgb.transpose(1, 2, 0)), (cell, cell))
        if poly is not None and len(poly) >= 3:
            q = np.round(np.asarray(poly) * sc).astype(np.int32)
            cv2.polylines(pv, [q], True, (60, 230, 120), 1, cv2.LINE_AA)
            add = meta.get("added")
            for i, (x, y) in enumerate(q):
                mask_made = add is not None and i < len(add) and bool(add[i])
                col = (255, 80, 255) if mask_made else (90, 220, 255)
                cv2.circle(pv, (int(x), int(y)), 3, col, -1, cv2.LINE_AA)
        lab = np.zeros((16, cell * 4, 3), np.uint8)
        # the residual is the number that explains "why not one MORE corner":
        # refinement stops when every arc is within tol, so a notch shallower
        # than tol is reported as a single V instead of a square step
        res = max_residual(poly, meta.get("t"), C) if C is not None else -1
        cv2.putText(lab, f"det {meta['n_detected']}  add {meta['n_added']}  "
                         f"final {0 if poly is None else len(poly)}   "
                         f"tol {meta.get('tol', 0):.1f}  "
                         f"max residual {res:.1f} cells", (4, 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
        rows.append(np.concatenate([lab,
                                    np.concatenate([img, mk, hm, pv], 1)], 0))
    return np.concatenate(rows, 0)


def make_input(img, box, crop, side=None):
    """(4, crop, crop) float32, plus the frame needed to map results back."""
    H, W = img.shape[:2]
    x0, y0, s = crop_window(box, side=side)
    xi, yi = int(np.floor(x0)), int(np.floor(y0))
    n = int(np.ceil(s)) + 1
    pl, pt = max(0, -xi), max(0, -yi)
    pr, pb = max(0, xi + n - W), max(0, yi + n - H)
    sub = img[max(yi, 0):min(yi + n, H), max(xi, 0):min(xi + n, W)]
    if sub.size == 0:
        return None, None
    if pl or pt or pr or pb:
        sub = np.pad(sub, ((pt, pb), (pl, pr), (0, 0)), mode="reflect")
    c = cv2.resize(sub, (crop, crop), interpolation=cv2.INTER_LINEAR)
    sc = crop / float(n)
    bx = np.zeros((crop, crop), np.float32)
    xa, ya, xb, yb = np.clip(np.round([(box[0] - xi) * sc, (box[1] - yi) * sc,
                                       (box[2] - xi) * sc, (box[3] - yi) * sc]
                                      ).astype(int), 0, crop)
    bx[ya:yb, xa:xb] = 1.0
    rgb = (c.astype(np.float32).transpose(2, 0, 1) / 255.0 - MEAN) / STD
    return np.concatenate([rgb, bx[None]], 0), (xi, yi, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True, help="stage-2 checkpoint (.pth)")
    ap.add_argument("--images", required=True, help="scene image, or a folder")
    ap.add_argument("--stage1", required=True,
                    help="folder of dinov3_v2 <stem>_masks.npz")
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--vertex-thr", type=float, default=0.3)
    ap.add_argument("--merge", type=float, default=1.0)
    ap.add_argument("--mask-thr", type=float, default=0.5)
    ap.add_argument("--max-dist-frac", type=float, default=0.08,
                    help="candidate-to-contour gate, as a fraction of the "
                         "mask's long side. THE DOMINANT KNOB: 0.25 measured "
                         "0.765 polygon IoU and 8.7%% self-intersecting rings "
                         "against 0.918 / 2.0%% at a tight gate. "
                         "SAMPolyBuild's equivalent is ~0.05 of the frame.")
    ap.add_argument("--no-fit-edges", action="store_true",
                    help="disable wall refitting. ON by default: the head "
                         "picks how many corners and which walls are which, "
                         "the mask says where each wall sits, and corners come "
                         "from intersecting the fitted walls. Worth +0.05 "
                         "polygon IoU and 9x lower corner error at realistic "
                         "noise, but it loses to the raw corners once the mask "
                         "carries more than ~2 px of systematic bias.")
    ap.add_argument("--prune-width", type=float, default=0.06,
                    help="cut tentacles and bays out of the mask contour "
                         "before using it as a guide, as a fraction of the "
                         "building's long side. Without it a 15px tentacle "
                         "reads as a missed corner and --refine-tol inserts "
                         "vertices along it: 8.34 verts/polygon vs 6.00. "
                         "0 disables.")
    ap.add_argument("--refine-tol", type=float, default=0.06,
                    help="let the mask contour insert a corner wherever the "
                         "vertex polygon departs from it by more than this "
                         "fraction of the building's long side. Fixes the "
                         "well-masked L-shape that the head reports as a quad: "
                         "IoU 0.738 -> 0.970 with one corner missed. Safe "
                         "while mask IoU >= 0.90; 0 disables.")
    ap.add_argument("--max-add", type=int, default=4,
                    help="cap on inserted corners per polygon; bounds the "
                         "damage when a mask is much worse than typical")
    ap.add_argument("--min-turn", type=float, default=10.0,
                    help="drop vertices whose turn is below this many degrees "
                         "(a straight wall) or inside 175-185 (a spike). "
                         "SAMPolyBuild's simple_polygon. Costs 0.50%% of real "
                         "GT corners here and removes ~20%% of predicted "
                         "vertices. 0 disables.")
    ap.add_argument("--angle-tol", type=float, default=0,
                    help="drop vertices whose direction disagrees with the "
                         "contour by more than this many degrees. 0 disables. "
                         "Worth +0.002 IoU synthetically once the gate is "
                         "right; try 50 for an A/B on real scenes.")
    ap.add_argument("--guard-min-iou", type=float, default=0.35)
    ap.add_argument("--min-area", type=float, default=64)
    ap.add_argument("--viz", action="store_true",
                    help="write <stem>_overlay.png: raw image | polygons, "
                         "coloured by source (green vertex / yellow angular "
                         "fallback / red rule-based guard)")
    ap.add_argument("--viz-scale", type=float, default=1.0,
                    help="downscale the panels AFTER drawing, so thin "
                         "outlines survive instead of vanishing between pixels")
    ap.add_argument("--viz-alpha", type=float, default=0.35)
    ap.add_argument("--debug-crops", type=int, default=0,
                    help="dump <stem>_debug.png: for the first N instances, "
                         "crop | mask + guide contour | vertex heatmap + "
                         "candidates | final polygon with mask-supplied "
                         "corners marked. This is what answers 'why is that "
                         "corner there' -- an odd step is either one the head "
                         "invented or one the mask did.")
    ap.add_argument("--viz-dot", type=int, default=2,
                    help="vertex marker radius; 0 hides them")
    a = ap.parse_args()

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    blob = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    cfg = blob.get("cfg", {})
    crop = cfg.get("crop", 256)
    out_sz = cfg.get("out_size", 128)
    model = PolyNet(cin=4, dim=cfg.get("dim", 128),
                    encoder=cfg.get("encoder", "resnet18"), pretrained=False,
                    edge=not cfg.get("no_edge", False))
    miss, unexp = model.load_state_dict(blob["model"], strict=False)
    if miss or unexp:
        raise SystemExit(f"[fatal] checkpoint does not match the model: "
                         f"{len(miss)} missing, {len(unexp)} unexpected "
                         f"(e.g. {(list(miss)+list(unexp))[:3]})")
    model.to(dev).eval()
    print(f"[load] epoch {blob.get('epoch','?')}  "
          f"F1@2px {blob.get('metrics',{}).get('f1_2','?')}")

    regularize = regularize_fn()
    src = Path(a.images)
    files = [src] if src.is_file() else sorted(
        p for p in src.iterdir() if p.suffix.lower() in IMG_EXT)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    st1 = Path(a.stage1)
    n_src = {}

    for p in files:
        npz = st1 / f"{p.stem}_masks.npz"
        if not npz.exists():
            print(f"  [skip] {p.name}: no {npz.name}")
            continue
        img = np.asarray(Image.open(p).convert("RGB"))
        H, W = img.shape[:2]
        z = np.load(npz)
        boxes, scores = z["boxes"], z["scores"]

        xs, frames, keep = [], [], []
        for i, b in enumerate(boxes):
            if (b[2] - b[0]) < 2 or (b[3] - b[1]) < 2:
                continue
            x, fr = make_input(img, b, crop)
            if x is None:
                continue
            xs.append(x)
            frames.append(fr)
            keep.append(i)

        recs, dbg = [], []
        n_add = n_det = n_fit = 0
        for s in range(0, len(xs), a.batch):
            xb = torch.from_numpy(np.stack(xs[s:s + a.batch])).to(dev)
            with torch.no_grad():
                o = model(xb)
                vm = torch.sigmoid(o["vmap"])[:, 0].cpu().numpy()
                vo = torch.sigmoid(o["voff"]).cpu().numpy()
                mk = (torch.sigmoid(o["mask"])[:, 0] > a.mask_thr).cpu().numpy()
            for j in range(len(xb)):
                k = s + j
                xi, yi, n = frames[k]
                m = mk[j]
                if m.sum() * (n / out_sz) ** 2 < a.min_area:
                    continue
                cand, _ = decode(vm[j], vo[j], thr=a.vertex_thr, merge=a.merge)
                base = regularize(m.astype(np.uint8))
                poly, srcname, meta = build_polygon(
                    cand, m, baseline=base, max_dist_frac=a.max_dist_frac,
                    angle_tol=(a.angle_tol or None), min_turn=a.min_turn,
                    refine_tol=a.refine_tol, max_add=a.max_add,
                    prune_width=a.prune_width,
                    fit=not a.no_fit_edges,
                    guard_min_iou=a.guard_min_iou)
                if poly is None or len(poly) < 3:
                    n_src["none"] = n_src.get("none", 0) + 1
                    continue
                # THE DEBUG PANEL NEEDS CELL COORDINATES. Everything else in
                # the panel -- mask, heatmap, candidates -- lives in the crop's
                # cell grid, and the polygon is about to leave it for scene
                # pixels. Capturing it after the transform drew it thousands of
                # pixels off-canvas, which is why column 4 came back empty.
                poly_cells = np.asarray(poly, np.float64).copy()
                # cells -> scene px, the exact inverse of make_input's framing
                sc = n / float(out_sz)
                poly = np.asarray(poly, np.float64) * sc + np.array([xi, yi])
                n_src[srcname] = n_src.get(srcname, 0) + 1
                n_add += meta["n_added"]
                n_fit += meta.get("n_fitted", 0)
                n_det += meta["n_detected"]
                recs.append({"polygon": [[float(u), float(v)] for u, v in poly],
                             "score": float(scores[keep[k]]),
                             "n_vertices": int(len(poly)),
                             # provenance per vertex: True where the MASK
                             # supplied the corner rather than the head. An odd
                             # step in a polygon is one or the other, and they
                             # need opposite fixes.
                             "from_mask": ([bool(x) for x in meta["added"]]
                                           if meta.get("added") is not None
                                           else []),
                             "n_detected": meta["n_detected"],
                             "n_added": meta["n_added"],
                             "source": srcname,
                             "stage1_index": int(keep[k])})
                if a.debug_crops and len(dbg) < a.debug_crops:
                    dbg.append((xs[k][:3], m, vm[j], cand, poly_cells, meta,
                                frames[k], side_of(m)))
        (out / f"{p.stem}_polys.json").write_text(
            json.dumps({"shape": [H, W], "polygons": recs}, indent=1))
        per = {}
        for r in recs:
            per[r["source"]] = per.get(r["source"], 0) + 1
        if a.viz:
            panel = two_panel(img, recs, per, alpha=a.viz_alpha, dot=a.viz_dot,
                              scale=a.viz_scale)
            cv2.imwrite(str(out / f"{p.stem}_overlay.png"),
                        cv2.cvtColor(panel, cv2.COLOR_RGB2BGR))
        if dbg:
            grid = debug_panel(dbg)
            cv2.imwrite(str(out / f"{p.stem}_debug.png"),
                        cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
        detail = "  ".join(f"{k} {v}" for k, v in sorted(per.items()))
        v_tot = sum(r["n_vertices"] for r in recs)
        print(f"  {p.name}: {len(boxes)} boxes -> {len(recs)} polygons"
              f"{('   [' + detail + ']') if detail else ''}"
              f"   vertices {v_tot} ({n_det} detected, {n_add} added by mask"
              f" = {n_add/max(v_tot,1):.0%}), {n_fit} wall-fitted")

    t = max(sum(n_src.values()), 1)
    print("[done] " + "  ".join(f"{k} {v} ({v/t:.1%})" for k, v in n_src.items()))


if __name__ == "__main__":
    main()
