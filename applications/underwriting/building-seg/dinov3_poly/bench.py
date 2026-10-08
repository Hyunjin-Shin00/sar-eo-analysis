"""
End-to-end scoring against the rule-based pipeline this replaces.

Three rows, identically scored:

    baseline   polygonize.regularize() on stage 1's masks   -- the status quo
    model      dinov3_poly's vertex head
    GT itself  the sanity row; must be 100% / 1.00

BOTH DIRECTIONS, AT 2 AND 4 PX. Recall (GT vertex -> nearest predicted) cannot
fall as the vertex count rises, so a head emitting twice as many corners scores
better on it while being worse. Precision (predicted -> nearest GT) is what
falls, and F1 is the headline. `v/GT` makes the trade visible directly.

Restricted to the VAL BAND by default -- the rightmost `--val-width` px of each
scene, stage 1's own split. Scoring the whole scene mixes in pixels stage 1
trained on and flatters everything.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SKIP = {"gt_overlay.png"}


def gt_rings(ann_path):
    out = []
    for an in json.loads(Path(ann_path).read_text())["annotations"]:
        if an.get("iscrowd"):
            continue
        s = an["segmentation"]
        if isinstance(s, str):
            s = json.loads(s)
        r = np.asarray(s[0], np.float64).reshape(-1, 2)
        if len(r) > 3 and np.allclose(r[0], r[-1]):
            r = r[:-1]
        if len(r) >= 3:
            out.append(r)
    return out


def fill(poly, shape):
    c = np.zeros(shape, np.uint8)
    cv2.fillPoly(c, [np.round(np.asarray(poly)).astype(np.int32)], 1)
    return c.astype(bool)


def iou(a, b):
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 0.0


def bbox(r):
    return np.array([r[:, 0].min(), r[:, 1].min(), r[:, 0].max(), r[:, 1].max()])


def corner_stats(pred, gt):
    d = np.linalg.norm(np.asarray(pred)[:, None, :] - gt[None, :, :], axis=2)
    return d.min(0), d.min(1)          # per GT vertex, per predicted vertex


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", default="../dataset/refined_data/scenes")
    ap.add_argument("--pred", required=True, help="folder of *_polys.json")
    ap.add_argument("--stage1", required=True, help="folder of *_masks.npz")
    ap.add_argument("--val-width", type=int, default=725)
    ap.add_argument("--whole-scene", action="store_true",
                    help="score everything, not just the val band. Mixes in "
                         "stage-1 training pixels; for inspection only.")
    ap.add_argument("--match-iou", type=float, default=0.5)
    a = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dinov3_v2"))
    from polygonize import regularize

    err = {"baseline": [], "model": []}
    rev = {"baseline": [], "model": []}
    nv = {"baseline": [], "model": [], "gt": []}
    piou = {"baseline": [], "model": []}
    n_match = 0

    for d in sorted(Path(a.scenes).iterdir()):
        if not d.is_dir():
            continue
        img_f = next((f for f in sorted(d.iterdir())
                      if f.suffix.lower() in IMG_EXT and f.name not in SKIP), None)
        ann_f = d / "annotations.json"
        pf = Path(a.pred) / f"{img_f.stem}_polys.json" if img_f else None
        zf = Path(a.stage1) / f"{img_f.stem}_masks.npz" if img_f else None
        if img_f is None or not ann_f.is_file() or not pf.exists() or not zf.exists():
            print(f"  [skip] {d.name}")
            continue

        z = np.load(zf)
        H, W = (int(v) for v in z["shape"])
        cut = -1 if a.whole_scene else W - a.val_width
        rings = [r for r in gt_rings(ann_f)
                 if (r[:, 0].min() + r[:, 0].max()) / 2 >= cut]
        if not rings:
            continue
        gms = [fill(r, (H, W)) for r in rings]
        for r in rings:
            nv["gt"].append(len(r))

        # stage-1 masks -> the baseline polygons, in the same frame
        boxes = z["boxes"]
        base_m, base_p = [], []
        for i in range(len(z["scores"])):
            b = boxes[i]
            if b[2] <= b[0] or b[3] <= b[1]:
                continue
            m = np.zeros((H, W), np.uint8)
            m[int(b[1]):int(b[3]), int(b[0]):int(b[2])] = z[f"m{i}"]
            if m.sum() < 64:
                continue
            base_m.append(m.astype(bool))
            base_p.append(regularize(m))

        model_p = [np.asarray(r["polygon"], np.float64)
                   for r in json.loads(pf.read_text())["polygons"]
                   if len(r["polygon"]) >= 3]
        model_m = [fill(p, (H, W)) for p in model_p]

        for name, polys, masks in (("baseline", base_p, base_m),
                                   ("model", model_p, model_m)):
            used = set()
            for k, m in enumerate(masks):
                best, bj = 0.0, -1
                for j, g in enumerate(gms):
                    if j in used:
                        continue
                    v = iou(m, g)
                    if v > best:
                        best, bj = v, j
                if bj < 0 or best < a.match_iou:
                    continue
                used.add(bj)
                p = polys[k]
                if p is None or len(p) < 3:
                    continue
                rc, pr = corner_stats(p, rings[bj])
                err[name].extend(rc.tolist())
                rev[name].extend(pr.tolist())
                nv[name].append(len(p))
                piou[name].append(iou(fill(p, (H, W)), gms[bj]))
                if name == "model":
                    n_match += 1

    print(f"matched instances (model): {n_match}   "
          f"GT polygons scored: {len(nv['gt'])}")
    print()
    hdr = (f"  {'':10s}{'rec<2':>8s}{'prc<2':>8s}{'F1<2':>8s}"
           f"{'rec<4':>8s}{'prc<4':>8s}{'F1<4':>8s}"
           f"{'verts':>8s}{'v/GT':>7s}{'polyIoU':>9s}")
    print("=" * len(hdr))
    print(hdr)
    print("=" * len(hdr))
    ngt = np.mean(nv["gt"]) if nv["gt"] else float("nan")

    def f1(name, t):
        e, r = np.array(err[name]), np.array(rev[name])
        if not len(e):
            return 0.0, 0.0, 0.0
        rc, pr = float(np.mean(e < t)), float(np.mean(r < t))
        return rc, pr, 2 * rc * pr / max(rc + pr, 1e-9)

    for name in ("baseline", "model"):
        if not err[name]:
            continue
        r2, p2, f2 = f1(name, 2)
        r4, p4, f4 = f1(name, 4)
        print(f"  {name:10s}{r2:8.1%}{p2:8.1%}{f2:8.1%}"
              f"{r4:8.1%}{p4:8.1%}{f4:8.1%}"
              f"{np.mean(nv[name]):8.2f}{np.mean(nv[name])/ngt:7.2f}"
              f"{np.mean(piou[name]):9.4f}")
    print(f"  {'GT itself':10s}{'100%':>8s}{'100%':>8s}{'100%':>8s}"
          f"{'100%':>8s}{'100%':>8s}{'100%':>8s}"
          f"{ngt:8.2f}{1.0:7.2f}{'':>9s}")

    if err["model"] and err["baseline"]:
        b2, m2 = f1("baseline", 2)[2], f1("model", 2)[2]
        b4, m4 = f1("baseline", 4)[2], f1("model", 4)[2]
        print()
        print(f"  F1<2px  {b2:.1%} -> {m2:.1%}   ({m2-b2:+.1%})")
        print(f"  F1<4px  {b4:.1%} -> {m4:.1%}   ({m4-b4:+.1%})")
        print()
        print("  v/GT far above 1.0 means recall was bought with extra vertices;")
        print("  check that polyIoU did not fall at the same time.")


if __name__ == "__main__":
    main()
