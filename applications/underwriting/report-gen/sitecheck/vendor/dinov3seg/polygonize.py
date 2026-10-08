"""
Mask -> polygon, for the DINOv3 + Mask2Former building segmenter.

Runs AFTER stitching and de-duplication, on complete scene-level instances.
See polygonize_scene() for the ordering rationale.

    python polygonize.py --masks out/scene_masks.npz --out out/scene_polys.json
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt


# --------------------------------------------------------------------------
# 1. Non-overlap partition
# --------------------------------------------------------------------------
def partition(instances, shape):
    """
    Buildings cannot physically overlap, so make the output a partition.

    Pixels claimed by exactly one instance are settled. Contested pixels go
    to whichever claimant's uncontested core is NEAREST, not to whichever
    has the higher score.

    Score priority is the obvious rule and it is a bad one: it lets a
    confident instance whose mask bleeds over a neighbour carve an arbitrary
    ragged bite out of that neighbour, and the bite is then faithfully traced
    as polygon vertices. Measured on the val split, one building lost 46% of
    its area that way (GT IoU 0.43, against 0.84 uncarved). Proximity instead
    puts the boundary between two adjacent buildings roughly where a wall
    would be, so it costs about two vertices rather than five. Against GT, on
    the instances this function carves: 0.417 -> 0.487 mean IoU, mean
    vertices 6.85 -> 6.27, and total polygon overlap downstream *falls*
    (932 -> 675 px), because a proximity seam is nearly straight.

    instances: list of dicts with keys mask (bool, cropped), x0, y0, score
    Returns the same structure with disjoint masks.
    """
    H, W = shape
    n = len(instances)
    cnt = np.zeros((H, W), np.int32)            # how many instances claim it
    top = np.zeros((H, W), np.int32)            # score-priority label, 0 = bg
    for rank in sorted(range(n), key=lambda i: instances[i]["score"]):
        ins = instances[rank]                   # low score first, high wins
        h, w = ins["mask"].shape
        sl = (slice(ins["y0"], ins["y0"] + h), slice(ins["x0"], ins["x0"] + w))
        cnt[sl] += ins["mask"]
        top[sl][ins["mask"]] = rank + 1

    label = np.where(cnt == 1, top, 0)          # uniquely claimed: settled
    contested = cnt > 1
    if contested.any() and label.any():
        _, idx = distance_transform_edt(label == 0, return_indices=True)
        ys, xs = np.nonzero(contested)
        cand = label[idx[0][contested], idx[1][contested]]

        # The nearest core may belong to an instance that never claimed this
        # pixel -- taking it would grow an instance past its own mask. Verify
        # membership and fall back to score priority where it fails.
        ok = np.zeros(len(ys), bool)
        for rank in np.unique(cand):
            if rank == 0:
                continue
            ins = instances[rank - 1]
            h, w = ins["mask"].shape
            sel = cand == rank
            ly, lx = ys[sel] - ins["y0"], xs[sel] - ins["x0"]
            inside = (ly >= 0) & (ly < h) & (lx >= 0) & (lx < w)
            hit = np.zeros(int(sel.sum()), bool)
            hit[inside] = ins["mask"][ly[inside], lx[inside]]
            ok[sel] = hit
        label[ys[ok], xs[ok]] = cand[ok]
        label[ys[~ok], xs[~ok]] = top[ys[~ok], xs[~ok]]
    elif contested.any():
        label = np.where(cnt >= 1, top, 0)      # no cores to be near

    out = []
    for rank, ins in enumerate(instances):
        keep = label == rank + 1
        if not keep.any():
            continue                                       # fully overwritten
        ys, xs = np.nonzero(keep)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        out.append({"mask": keep[y0:y1, x0:x1].copy(),
                    "x0": int(x0), "y0": int(y0),
                    "score": ins["score"]})
    return out


# --------------------------------------------------------------------------
# 2. Rectilinear regularization
# --------------------------------------------------------------------------
def _dominant_angle(contour):
    """Orientation of the minimum-area rectangle, folded to [0, 90)."""
    return cv2.minAreaRect(contour.astype(np.float32))[2] % 90.0


def _edge_weighted_angle(contour, dp_eps=2.0):
    """
    Orientation from edge directions weighted by edge length, folded to
    [0, 90).

    Complements _dominant_angle, which is fixed by the four extreme points:
    an L, U or Z plan tilts its own minimum-area box to hug the diagonal, and
    the walls then come out off-axis. Measured on one Z-plan instance,
    minAreaRect returned 10.5 deg for a building whose walls were already at
    0 and 90; this estimator returns 0.0.

    It has the opposite failure. A raster mask draws a rotated wall as a
    staircase of short axis-aligned steps, and CHAIN_APPROX_SIMPLE does not
    collapse those, so the length-weighted mean is dragged toward 0 for
    genuinely rotated buildings. Simplifying FIRST is what keeps that in
    check -- weighting the raw contour instead costs 0.003 mean IoU on the
    val split, because the staircase steps outvote the walls they approximate.

    Swapping this in wholesale is still a net loss (96 instances worse, 21
    better). Neither estimator is safe alone -- regularize() builds both and
    keeps whichever fits the mask.
    """
    p = cv2.approxPolyDP(contour.astype(np.float32), dp_eps, True)
    p = p.reshape(-1, 2).astype(np.float64)
    d = np.roll(p, -1, axis=0) - p
    L = np.linalg.norm(d, axis=1)
    ok = L > 1e-6
    if not ok.any():
        return _dominant_angle(contour)
    # circular mean over 4x the angle, so 0 and 90 are the same direction and
    # the average cannot be dragged to 45 by an even mix of H and V edges
    a = np.deg2rad((np.degrees(np.arctan2(d[ok, 1], d[ok, 0])) % 90.0) * 4.0)
    v = np.array([(L[ok] * np.cos(a)).sum(), (L[ok] * np.sin(a)).sum()])
    return float(np.degrees(np.arctan2(v[1], v[0])) / 4.0) % 90.0


def _rot(pts, deg, center):
    t = np.deg2rad(deg)
    R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    return (pts - center) @ R.T + center


def _snap_axis(pts, angle_tol=20.0, iters=3):
    """
    Force near-horizontal / near-vertical edges to be exactly axis-aligned.

    Naively overwriting one endpoint per edge breaks the ring -- consecutive
    edges share vertices, so the last edge will not close. Instead classify
    every edge, then average the shared coordinate over each run of edges that
    constrain it, and iterate. A few passes converge.
    """
    p = pts.copy()
    n = len(p)
    for _ in range(iters):
        d = np.roll(p, -1, axis=0) - p
        ang = np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 180.0
        is_h = np.minimum(ang, 180 - ang) < angle_tol
        is_v = np.abs(ang - 90) < angle_tol

        acc = np.zeros_like(p)
        cnt = np.zeros((n, 2))
        for i in range(n):
            j = (i + 1) % n
            if is_h[i]:
                y = 0.5 * (p[i, 1] + p[j, 1])
                acc[i, 1] += y; cnt[i, 1] += 1
                acc[j, 1] += y; cnt[j, 1] += 1
            elif is_v[i]:
                x = 0.5 * (p[i, 0] + p[j, 0])
                acc[i, 0] += x; cnt[i, 0] += 1
                acc[j, 0] += x; cnt[j, 0] += 1
        upd = cnt > 0
        p[upd] = acc[upd] / cnt[upd]
    return p


def _drop_short_and_collinear(pts, min_edge=3.0, angle_eps=8.0):
    """Merge consecutive near-collinear edges, then remove tiny edges."""
    p = pts
    for _ in range(3):
        if len(p) <= 4:
            break
        prev = p - np.roll(p, 1, axis=0)
        nxt = np.roll(p, -1, axis=0) - p
        a1 = np.degrees(np.arctan2(prev[:, 1], prev[:, 0]))
        a2 = np.degrees(np.arctan2(nxt[:, 1], nxt[:, 0]))
        turn = np.abs((a2 - a1 + 180) % 360 - 180)
        keep = turn > angle_eps
        if keep.all():
            break
        p = p[keep] if keep.sum() >= 4 else p
        if keep.sum() < 4:
            break

    # Remove short edges until none remain. A fixed iteration count caps how
    # many vertices can be deleted, which leaves noisy contours barely
    # simplified (measured: 954 -> 229 vertices with a 3-iteration cap).
    for _ in range(4 * len(p) + 16):
        if len(p) <= 4:
            break
        seg = np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1)
        i = int(np.argmin(seg))
        if seg[i] >= min_edge:
            break
        j = (i + 1) % len(p)
        p[i] = 0.5 * (p[i] + p[j])
        p = np.delete(p, j, axis=0)
    return p


def _restore_corners(pts, max_len=12.0, min_ratio=2.0, max_push=3.0):
    """
    Replace a chamfered corner with the intersection of its two walls.

    Segmentation rounds building corners, and the contour comes back with a
    short diagonal cutting across where the right angle should be. Measured on
    the val split: 40.1% of polygons carry at least one, median 6.8 px long,
    against 1.7% of GT polygons. They survive everything else because they sit
    at ~45 deg -- too far off-axis for _snap_axis at angle_tol=20 -- and are
    longer than min_edge, so _drop_short_and_collinear never reaches them.

    Raising min_edge would not fix it either: that function collapses an edge
    to the MIDPOINT of its endpoints, which is right for a collinear jog and
    wrong here. The true corner lies OUTSIDE the chamfer, where the two walls
    would have met, so the midpoint pulls it inward and loses area. Intersect
    the walls instead.

    Two guards keep this from eating real geometry: the neighbouring walls
    must be min_ratio times longer than the chamfer, and the computed
    intersection must land within max_push chamfer-lengths of it -- near
    parallel walls otherwise throw the vertex far off the building.

    Measured effect: right-angle share 0.602 -> 0.755, vertices 6.09 -> 5.52,
    GT IoU 0.5814 -> 0.5816. Unlike widening the snap tolerance, this moves
    only vertices that were already wrong, so shape fidelity is unaffected.
    """
    p = np.asarray(pts, float).copy()
    for _ in range(len(p)):
        n = len(p)
        if n <= 4:
            break
        d = np.roll(p, -1, axis=0) - p
        L = np.linalg.norm(d, axis=1)
        ang = np.degrees(np.arctan2(d[:, 1], d[:, 0]))
        hit = None
        for i in range(n):
            a, b = (i - 1) % n, (i + 1) % n
            if L[i] > max_len or L[a] < min_ratio * L[i] or L[b] < min_ratio * L[i]:
                continue
            if not (70 <= abs((ang[b] - ang[a] + 180) % 360 - 180) <= 110):
                continue                       # walls must be perpendicular
            if not (25 <= abs((ang[i] - ang[a] + 180) % 360 - 180) <= 65):
                continue                       # and the edge a true diagonal
            P, r = p[a], d[a]
            Q, s = p[b], d[b]
            den = r[0] * s[1] - r[1] * s[0]
            if abs(den) < 1e-9:
                continue
            t = ((Q[0] - P[0]) * s[1] - (Q[1] - P[1]) * s[0]) / den
            X = P + t * r
            if np.linalg.norm(X - 0.5 * (p[i] + p[(i + 1) % n])) > max_push * L[i]:
                continue
            hit = (i, X)
            break
        if hit is None:
            break
        i, X = hit
        p[i] = X
        p = np.delete(p, (i + 1) % len(p), axis=0)
    return p


def _build_in_frame(pts, theta, center, dp_eps, angle_tol, min_edge,
                    corner_restore=True):
    """Simplify, then square up, inside the frame rotated by theta."""
    p = _rot(pts, -theta, center)
    p = cv2.approxPolyDP(p.astype(np.float32), dp_eps, True).reshape(-1, 2)
    p = p.astype(np.float64)
    if len(p) < 4:
        return None
    p = _snap_axis(p, angle_tol=angle_tol)
    p = _drop_short_and_collinear(p, min_edge=min_edge)
    if corner_restore:
        # after snapping, so the neighbouring walls are already axis-aligned
        # and the perpendicularity test is meaningful
        p = _restore_corners(p)
    if len(p) < 4:
        return None
    return _rot(p, theta, center)


def regularize(mask, dp_eps=2.0, angle_tol=20.0, min_edge=3.0,
               rectilinear=True, corner_restore=True):
    """
    Binary mask -> polygon vertex array (N, 2) in (x, y), or None.

    Korean factory roofs are overwhelmingly rectangles or unions of
    rectangles with one dominant orientation per building. That prior is far
    stronger than anything a vertex head learns from 300 tiles, so impose it
    rather than predict it. Finding that orientation is the hard part: see
    _edge_weighted_angle for why two estimates are built and scored.

    These defaults are deliberately conservative. Loosening them to 4.0 /
    35.0 / 8.0 raises the share of turns that land within 10 deg of a right
    angle from 59% to 94%, which looks like a large win and is not: measured
    against each polygon's OWN mask over 1670 val instances, mean IoU falls
    0.954 -> 0.918, and 434 instances (26%) lose more than 0.05. The damage
    concentrates on exactly the buildings that are not rectangles -- L, U and
    Z plans drop to 4 vertices -- and on tile-clipped fragments, whose
    minAreaRect orientation is meaningless, so a wide angle_tol snaps them
    into a wrong frame. Right-angle share is not a safe objective here: the
    transform that maximises it is the transform that causes the damage.
    """
    m = np.ascontiguousarray(mask.astype(np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 8:
        return None

    pts = c.reshape(-1, 2).astype(np.float64)
    if not rectilinear:
        return cv2.approxPolyDP(
            pts.astype(np.float32), dp_eps, True).reshape(-1, 2)

    center = pts.mean(axis=0)

    # The two angle estimators fail on disjoint cases, so pick per instance by
    # measuring rather than betting on either. Costs one extra build; this
    # stage is offline and runs in seconds.
    thetas = [_dominant_angle(c), _edge_weighted_angle(c, dp_eps=dp_eps)]
    gap = abs(thetas[0] - thetas[1])
    if min(gap, 90.0 - gap) < 0.5:          # same frame, do not build twice
        thetas = thetas[:1]

    best, best_iou = None, -1.0
    for theta in thetas:
        cand = _build_in_frame(pts, theta, center, dp_eps, angle_tol, min_edge,
                               corner_restore=corner_restore)
        if cand is None:
            continue
        v = polygon_iou(cand, mask, (0, 0))
        if v > best_iou:
            best, best_iou = cand, v
    return best


# --------------------------------------------------------------------------
# 3. Quality filters
# --------------------------------------------------------------------------
def polygon_iou(poly, mask, offset):
    """IoU between the regularized polygon and the mask it came from."""
    h, w = mask.shape
    canvas = np.zeros((h, w), np.uint8)
    shifted = np.round(poly - np.array(offset)).astype(np.int32)
    cv2.fillPoly(canvas, [shifted], 1)
    inter = int(np.logical_and(canvas, mask).sum())
    union = int(np.logical_or(canvas, mask).sum())
    return inter / max(union, 1)


def _free_form(mask, x0, y0, max_verts, dp_eps=2.0):
    """
    Shape-preserving fallback: simplified contour, no rectilinear snapping.

    Used when regularization is rejected. The rejects are dominated by
    buildings that genuinely are not rectangles -- an L or U plan fails the
    min_rect test precisely because it is an L or U -- so falling back to a
    minimum-area box would replace "no answer" with a confidently wrong one.
    Simplify progressively instead, until the vertex budget is met.
    """
    m = np.ascontiguousarray(mask.astype(np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea).astype(np.float32)
    eps = dp_eps
    for _ in range(12):
        p = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(p) <= max_verts:
            return (p.astype(np.float64) + np.array([x0, y0])
                    if len(p) >= 4 else None)
        eps *= 1.5
    return None


def polygonize_scene(instances, shape, min_area=100, max_verts=24,
                     min_rect=0.45, min_iou=0.70, fallback=True, **kw):
    """
    Full mask -> polygon stage.

    ORDER MATTERS. Stitch and de-duplicate in raster space BEFORE this, then
    polygonize complete instances once. Polygonizing per tile and merging
    polygons afterwards leaves seam vertices along every tile boundary a
    building crossed, and forces de-duplication to operate on approximations.
    """
    parts = partition(instances, shape)
    out = []
    for ins in parts:
        if ins["mask"].sum() < min_area:
            continue

        # Every check below rejects the REGULARIZATION, not the detection. The
        # mask is still a building the segmenter found, so falling back to a
        # simplified contour keeps the instance instead of silently deleting
        # it -- which also keeps masks.npz and polys.json index-aligned, since
        # a dropped instance here shifted every polygon index after it.
        poly, iou = regularize(ins["mask"], **kw), 0.0
        ok = poly is not None and len(poly) <= max_verts
        if ok:
            # rectangularity: area / min-area-rect area. Blobs that are
            # nothing like a rectangle are usually merged instances or
            # vegetation.
            rect = cv2.minAreaRect(poly.astype(np.float32))
            ra = rect[1][0] * rect[1][1]
            ok = ra > 0 and cv2.contourArea(poly.astype(np.float32)) / ra >= min_rect
        if ok:
            # regularization must not have wandered away from the mask
            # NB: regularize() works on the cropped mask, so poly is already in
            # crop-local coordinates. Subtracting the scene offset here pushed
            # every polygon off-canvas and silently zeroed the IoU.
            iou = polygon_iou(poly, ins["mask"], (0, 0))
            ok = iou >= min_iou

        if ok:
            poly = poly + np.array([ins["x0"], ins["y0"]])
        elif fallback:
            poly = _free_form(ins["mask"], ins["x0"], ins["y0"], max_verts,
                              dp_eps=kw.get("dp_eps", 2.0))
            if poly is None:
                continue
            # measured against the mask like the regularized path, so the two
            # stay comparable -- a fallback polygon is not automatically worse
            iou = polygon_iou(poly - np.array([ins["x0"], ins["y0"]]),
                              ins["mask"], (0, 0))
        else:
            continue

        out.append({
            "polygon": poly.tolist(),
            "score": float(ins["score"]),
            "n_vertices": int(len(poly)),
            "mask_iou": float(iou),
            "fallback": not ok,
        })
    return out


# --------------------------------------------------------------------------
def load_npz(path):
    z = np.load(path)
    # int() the shape: np.int32 scalars are not JSON-serializable, and the
    # failure surfaces only at write time, after all the work is done.
    shape = tuple(int(v) for v in z["shape"])
    boxes, scores = z["boxes"], z["scores"]
    inst = [{"mask": z[f"m{i}"].astype(bool),
             "x0": int(boxes[i][0]), "y0": int(boxes[i][1]),
             "score": float(scores[i])}
            for i in range(len(scores))]
    return inst, shape


IMG_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")


def find_source_image(stem, npz_dir, images_dir=None):
    """
    Locate the raw tile for the 'raw' panel.

    The *_overlay.png sitting next to the npz already has masks burned into
    it, so it cannot serve as the raw panel. Look in --images first, then fall
    back to a same-stem file in the npz folder. Returns None if neither hits,
    in which case the raw panel is simply omitted.
    """
    for d in ([Path(images_dir)] if images_dir else []) + [Path(npz_dir)]:
        for ext in IMG_EXT:
            f = d / f"{stem}{ext}"
            if f.exists():
                return f
    return None


def load_gt_polys(ann_path):
    """
    COCO annotations -> {image_stem: [ring, ...]}.

    iscrowd rings are kept but flagged, because a GT panel that silently omits
    them looks like a labelling gap when it is really a region the tiler
    deliberately declined to supervise.
    """
    with open(ann_path, "r") as fh:
        j = json.load(fh)
    stem = {i["id"]: Path(i["file_name"]).stem for i in j["images"]}
    out = {}
    for a in j["annotations"]:
        s = stem.get(a["image_id"])
        if s is None:
            continue
        for seg in a.get("segmentation", []):
            if not isinstance(seg, list) or len(seg) < 6:
                continue
            r = np.asarray(seg, np.float64).reshape(-1, 2)
            out.setdefault(s, []).append((r, bool(a.get("iscrowd", 0))))
    return out


def _caption(img, text):
    bar = np.zeros((26, img.shape[1], 3), np.uint8)
    cv2.putText(bar, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (255, 255, 255), 1, cv2.LINE_AA)
    return np.concatenate([bar, img], axis=0)


def render_panels(img, insts, polys, alpha=0.45, seed=0, gt_polys=None):
    """raw / mask / polygon, stacked vertically with captions."""
    rng = np.random.default_rng(seed)
    colors = [rng.integers(60, 255, 3).tolist() for _ in range(max(len(insts), len(polys)))]

    mask_vis = img.copy()
    layer = img.copy()
    for k, ins in enumerate(insts):
        full = np.zeros(img.shape[:2], np.uint8)
        full[ins["y0"]:ins["y0"] + ins["mask"].shape[0],
             ins["x0"]:ins["x0"] + ins["mask"].shape[1]] = ins["mask"]
        layer[full.astype(bool)] = colors[k]
    mask_vis = cv2.addWeighted(layer, alpha, mask_vis, 1 - alpha, 0)

    poly_vis = img.copy()
    layer = img.copy()
    for k, p in enumerate(polys):
        pts = np.round(np.array(p["polygon"])).astype(np.int32)
        cv2.fillPoly(layer, [pts], colors[k])
    poly_vis = cv2.addWeighted(layer, alpha, poly_vis, 1 - alpha, 0)
    for k, p in enumerate(polys):
        pts = np.round(np.array(p["polygon"])).astype(np.int32)
        cv2.polylines(poly_vis, [pts], True, colors[k], 2, cv2.LINE_AA)
        for (x, y) in pts:                      # vertex markers: where corners landed
            cv2.circle(poly_vis, (int(x), int(y)), 3, (255, 255, 255), -1)
            cv2.circle(poly_vis, (int(x), int(y)), 3, (0, 0, 0), 1)

    panels = []
    if img is not None:
        panels.append(_caption(img, "raw"))
    panels.append(_caption(mask_vis, f"mask  (n={len(insts)})"))
    nv = [p["n_vertices"] for p in polys]
    panels.append(_caption(
        poly_vis,
        f"polygon  (n={len(polys)}" +
        (f", verts med {int(np.median(nv))} max {max(nv)})" if nv else ")")))

    if gt_polys is not None:
        gt_vis = img.copy()
        layer = img.copy()
        nc = 0
        for k, (r, crowd) in enumerate(gt_polys):
            pts = np.round(r).astype(np.int32)
            if len(pts) >= 3 and not crowd:
                cv2.fillPoly(layer, [pts], colors[k % len(colors)]
                             if colors else (0, 200, 255))
        gt_vis = cv2.addWeighted(layer, alpha, gt_vis, 1 - alpha, 0)
        gvn = []
        for k, (r, crowd) in enumerate(gt_polys):
            pts = np.round(r).astype(np.int32)
            if len(pts) < 3:
                continue
            # iscrowd = clipped below min_keep, not trained on and not scored:
            # thin and orange so it cannot be mistaken for a real target
            col = (255, 165, 0) if crowd else (0, 255, 255)
            cv2.polylines(gt_vis, [pts], True, col, 1 if crowd else 2, cv2.LINE_AA)
            if crowd:
                nc += 1
                continue
            gvn.append(len(pts) - 1 if np.allclose(r[0], r[-1]) else len(pts))
            for (x, y) in pts:
                cv2.circle(gt_vis, (int(x), int(y)), 3, (255, 255, 255), -1)
                cv2.circle(gt_vis, (int(x), int(y)), 3, (0, 0, 0), 1)
        panels.append(_caption(
            gt_vis,
            f"ground truth  (n={len(gvn)}" +
            (f", verts med {int(np.median(gvn))}" if gvn else "") +
            (f", +{nc} iscrowd)" if nc else ")")))

    return np.concatenate(panels, axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--masks", required=True,
                    help="folder of *_masks.npz from infer --save-masks "
                         "(a single .npz also works)")
    ap.add_argument("--out", default=None,
                    help="output folder for JSON. Default: alongside the npz.")
    ap.add_argument("--images", default=None,
                    help="folder holding the source tiles, for the raw panel. "
                         "The *_overlay.png next to the npz already has masks "
                         "drawn on it and cannot be used.")
    ap.add_argument("--ann", default=None,
                    help="COCO annotations.json; adds a ground-truth polygon "
                         "panel to --viz so predictions can be read against "
                         "the labels in the same frame")
    ap.add_argument("--viz", action="store_true",
                    help="write raw/mask/polygon panels to <npz folder>/polygon/")
    ap.add_argument("--alpha", type=float, default=0.45)
    ap.add_argument("--dp-eps", type=float, default=3.0)
    ap.add_argument("--angle-tol", type=float, default=20.0)
    ap.add_argument("--min-edge", type=float, default=3.0)
    ap.add_argument("--no-corner-restore", action="store_true",
                    help="keep chamfered corners instead of reconstructing the "
                         "right angle from the two adjoining walls")
    ap.add_argument("--no-fallback", action="store_true",
                    help="drop instances whose regularization fails instead "
                         "of falling back to a simplified contour")
    ap.add_argument("--min-area", type=int, default=200)
    ap.add_argument("--min-iou", type=float, default=0.70)
    ap.add_argument("--free-form", action="store_true",
                    help="skip rectilinear snapping (plain Douglas-Peucker)")
    a = ap.parse_args()

    src = Path(a.masks)
    if src.is_dir():
        files = sorted(src.glob("*.npz"))
        npz_dir = src
    else:
        files, npz_dir = [src], src.parent
    if not files:
        raise SystemExit(f"no .npz found in {src}")

    out_dir = Path(a.out) if a.out else npz_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    viz_dir = npz_dir / "polygon"
    if a.viz:
        viz_dir.mkdir(parents=True, exist_ok=True)

    # loaded once, not per tile: a val annotations.json is a few MB and there
    # are 52 tiles
    gt_by_stem = None
    if a.ann:
        gt_by_stem = load_gt_polys(a.ann)
        hit = sum(1 for f in files
                  if (f.stem[:-6] if f.stem.endswith("_masks") else f.stem)
                  in gt_by_stem)
        print(f"[gt] {a.ann}: {sum(len(v) for v in gt_by_stem.values())} rings "
              f"over {len(gt_by_stem)} images; {hit}/{len(files)} tiles matched")
        if hit == 0:
            print("[warn] no tile stem matched the annotations -- the GT panel "
                  "will be empty. Check that --ann belongs to this split.")
        if not a.viz:
            print("[warn] --ann given without --viz; it only affects the "
                  "visualisation, so nothing will use it")

    n_missing = 0
    for n, f in enumerate(files, 1):
        stem = f.stem[:-6] if f.stem.endswith("_masks") else f.stem
        inst, shape = load_npz(f)
        polys = polygonize_scene(inst, shape,
                                 min_area=a.min_area, min_iou=a.min_iou,
                                 dp_eps=a.dp_eps, angle_tol=a.angle_tol,
                                 min_edge=a.min_edge,
                                 fallback=not a.no_fallback,
                                 corner_restore=not a.no_corner_restore,
                                 rectilinear=not a.free_form)
        (out_dir / f"{stem}_polys.json").write_text(json.dumps(
            {"shape": list(shape), "polygons": polys}, indent=1))

        note = ""
        if a.viz:
            img_path = find_source_image(stem, npz_dir, a.images)
            if img_path is None:
                img = np.zeros((shape[0], shape[1], 3), np.uint8)
                n_missing += 1
                note = "  [no source image -- raw panel blank]"
            else:
                img = np.array(Image.open(img_path).convert("RGB"))
            vis = render_panels(img, inst, polys, alpha=a.alpha,
                                gt_polys=(gt_by_stem.get(stem) if gt_by_stem
                                          is not None else None))
            cv2.imwrite(str(viz_dir / f"{stem}_polygon.png"),
                        cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))

        v = [p["n_vertices"] for p in polys]
        i = [p["mask_iou"] for p in polys]
        stats = (f"verts med {np.median(v):.0f} max {max(v)} | "
                 f"IoU {np.mean(i):.3f}") if polys else "FILTERS REJECTED ALL"
        print(f"  [{n}/{len(files)}] {stem}: {len(inst)} masks -> "
              f"{len(polys)} polygons | {stats}{note}")

    if n_missing:
        print(f"\n[warn] {n_missing} tiles had no source image. Pass --images "
              f"<folder of the tiles you ran inference on>.")
    print(f"[save] json -> {out_dir}" + (f"\n[save] viz  -> {viz_dir}" if a.viz else ""))


if __name__ == "__main__":
    main()