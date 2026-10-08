"""
Crop framing, target rendering, and vertex decoding.

COORDINATE CONVENTION, stated once and obeyed everywhere:

  * rings arrive in SCENE pixels (COCO edge convention -- the image spans
    [0, W], pixel i covers [i, i+1))
  * a crop is a square window in scene pixels, `(x0, y0, side)`
  * crop pixels        p_crop  = p_scene - (x0, y0)
  * output cells       c       = p_crop * (out / side)
  * a cell index is the FLOOR of c, and the offset is the remainder in [0, 1)

The floor/remainder pair is SAMPolyBuild's, and it is what makes a sigmoid the
right activation for the offset head: the target genuinely lives in [0, 1).
Pairing `round` with a [-0.5, 0.5] offset is equally valid but then a sigmoid
is wrong, and mixing the two silently biases every corner by half a cell.
"""
import numpy as np

SIGMA = 1.0          # Gaussian radius in CELLS, SAMPolyBuild's value
GAUSS_SIZE = 3       # window side in cells; 3 keeps blobs from merging


def crop_side(m, base=1.25, gain=1.25, tau=60.0):
    """
    Side of the square crop for a box whose long side is `m` scene px.

        side = m * (base + gain * exp(-m / tau))

    SMOOTH AND MONOTONE, unlike a tiered rule. Small buildings need
    proportionally more context because the surroundings are what separate them
    from neighbours 3 px away, so the factor has to fall with size -- but
    SAMPolyBuild's step thresholds make it jump: at their m=120 cut a 119 px
    building gets a 214 px crop and a 120 px building gets 156, so two nearly
    identical buildings train at very different magnifications.

    This form gives 26 -> 54, 65 -> 109, 133 -> 185 (the p10 / median / p90 of
    this dataset) with no discontinuity.
    """
    m = float(max(m, 1.0))
    return m * (base + gain * np.exp(-m / tau))


def crop_window(box, side=None, jitter=None, rng=None, **kw):
    """
    (x0, y0, side) square window in scene px for an xyxy box.

    jitter, when given, is (scale_lo, scale_hi, shift_frac): the side is scaled
    and the centre displaced by up to shift_frac of the side. Training uses it
    because at inference the box comes from stage 1, not from GT.

    THE RANGE IS MEASURED, NOT PICKED. Stage-1 boxes against matched GT, 836
    instances from run6 TTA: long-side ratio p10 0.938 / p90 1.077, centre
    offset median 1.58 px and p90 10.6 px. On a median 65 px building the crop
    is 109 px, so a 10.6 px offset is 9.7% of the crop -- the default 0.12
    shift covers the p90 with margin, and an earlier 0.06 did not.
    """
    x1, y1, x2, y2 = map(float, box)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    if side is None:
        side = crop_side(max(x2 - x1, y2 - y1), **kw)
    if jitter is not None:
        rng = rng or np.random
        lo, hi, sh = jitter
        side *= rng.uniform(lo, hi)
        cx += rng.uniform(-sh, sh) * side
        cy += rng.uniform(-sh, sh) * side
    side = max(side, 8.0)
    return cx - side / 2.0, cy - side / 2.0, side


def to_cells(ring, x0, y0, side, out):
    """Scene ring -> output-cell coordinates."""
    s = out / float(side)
    return np.stack([(ring[:, 0] - x0) * s, (ring[:, 1] - y0) * s], 1)


def to_scene(pts, x0, y0, side, out):
    """Output-cell coordinates -> scene px. Exact inverse of to_cells."""
    s = float(side) / out
    return np.stack([pts[:, 0] * s + x0, pts[:, 1] * s + y0], 1)


def d4_points(p, k, flip, size):
    """
    The D4 element np.rot90(img, k) (+ flip) applies, for CONTINUOUS points.

    The constant is `size`, not `size - 1`. These are edge-convention
    coordinates: the crop spans [0, size] and pixel i covers [i, i+1), so a
    reflection is p -> size - p. `size - 1` is the reflection of a pixel INDEX,
    and using it displaces every corner by one pixel on 7 of the 8 elements --
    verified against a rasteriser, not derived on paper.
    """
    p = np.asarray(p, np.float64).copy()
    c = float(size)
    for _ in range(k % 4):
        p = np.stack([p[:, 1], c - p[:, 0]], 1)
    if flip:
        p = np.stack([c - p[:, 0], p[:, 1]], 1)
    return p


def render_vertex(ring_c, out, sigma=SIGMA, size=GAUSS_SIZE):
    """
    (vmap, voff, vmask) for one instance's ring already in cell coordinates.

    vmap  (out, out)      Gaussian peaks, combined by MAXIMUM
    voff  (2, out, out)   remainder in [0, 1) written at the peak cell only
    vmask (1, out, out)   1 where voff has a target

    Gaussians combine by max, not sum: two corners a few cells apart would
    otherwise build a single brighter blob between them and NMS would return
    one vertex where there are two.
    """
    vmap = np.zeros((out, out), np.float32)
    voff = np.zeros((2, out, out), np.float32)
    vmask = np.zeros((1, out, out), np.float32)
    half = size // 2
    for cx, cy in ring_c:
        if not (0 <= cx < out and 0 <= cy < out):
            continue                       # corner outside the crop
        xi, yi = int(cx), int(cy)          # floor; cx >= 0 here
        xi, yi = min(xi, out - 1), min(yi, out - 1)
        x_lo, x_hi = max(0, xi - half), min(out, xi + half + 1)
        y_lo, y_hi = max(0, yi - half), min(out, yi + half + 1)
        gx = np.arange(x_lo, x_hi)[None, :] - xi
        gy = np.arange(y_lo, y_hi)[:, None] - yi
        g = np.exp(-0.5 * (gx ** 2 + gy ** 2) / sigma ** 2).astype(np.float32)
        np.maximum(vmap[y_lo:y_hi, x_lo:x_hi], g, out=vmap[y_lo:y_hi, x_lo:x_hi])
        vmap[yi, xi] = 1.0                 # the peak cell is exactly 1
        voff[0, yi, xi] = cx - xi
        voff[1, yi, xi] = cy - yi
        vmask[0, yi, xi] = 1.0
    return vmap, voff, vmask


def gt_points(vmask, voff):
    """
    GT corners in CELL coordinates, recovered from the targets themselves.

    THE SUB-CELL OFFSET IS PART OF THE GT POSITION. Taking the peak cell index
    alone -- which is the obvious thing to write -- throws away exactly the
    remainder render_vertex stored there, so a head predicting the offset
    perfectly is scored as up to a full cell wrong, one-sidedly.
    """
    ys, xs = np.nonzero(vmask[0] > 0.5)
    if len(ys) == 0:
        return np.zeros((0, 2))
    return np.stack([xs + voff[0][ys, xs], ys + voff[1][ys, xs]], 1)


def render_mask(ring_c, out):
    """Filled instance mask at cell resolution."""
    import cv2
    m = np.zeros((out, out), np.uint8)
    cv2.fillPoly(m, [np.round(ring_c).astype(np.int32)], 1)
    return m.astype(np.float32)


def render_edge(ring_c, out, sigma=1.0):
    """
    Boundary map, 1 px polyline blurred and renormalised to peak 1.

    A hard 1-cell line is ~1% of the crop and trains poorly; the blur turns it
    into a regression target with a gradient either side of the true boundary.
    """
    import cv2
    e = np.zeros((out, out), np.uint8)
    cv2.polylines(e, [np.round(ring_c).astype(np.int32)], True, 1, 1)
    e = e.astype(np.float32)
    k = int(sigma * 2) + 1
    e = cv2.GaussianBlur(e, (k, k), sigma)
    mx = e.max()
    return e / mx if mx > 0 else e


def decode(vmap, voff, thr=0.3, max_n=64, merge=1.0):
    """
    (N, 2) candidate corners in CELL coordinates, plus scores.

    vmap/voff are probabilities and [0,1) offsets -- apply the sigmoids before
    calling. 3x3 max-pool NMS, then the offset is added to the FLOOR cell,
    inverting render_vertex exactly.

    `merge` collapses candidates closer than this many cells. NMS keeps ties
    (`p >= pooled`), so a corner sitting exactly between two cells makes both
    equal maxima whose offsets point back to the same place -- a duplicate
    vertex and a zero-length polygon edge.
    """
    import torch
    import torch.nn.functional as F
    p = torch.as_tensor(vmap, dtype=torch.float32)[None, None]
    keep = (p >= F.max_pool2d(p, 3, 1, 1)) & (p > thr)
    ys, xs = torch.nonzero(keep[0, 0], as_tuple=True)
    if len(ys) == 0:
        return np.zeros((0, 2)), np.zeros(0, np.float32)
    sc = p[0, 0][ys, xs]
    if len(sc) > max_n:
        k = torch.argsort(sc, descending=True)[:max_n]
        ys, xs, sc = ys[k], xs[k], sc[k]
    o = torch.as_tensor(voff, dtype=torch.float32)
    pts = torch.stack([xs.float() + o[0][ys, xs],
                       ys.float() + o[1][ys, xs]], 1).numpy().astype(np.float64)
    sc = sc.numpy()
    if merge > 0 and len(pts) > 1:
        order = np.argsort(-sc)
        q = pts[order]
        d = np.linalg.norm(q[:, None, :] - q[None, :, :], axis=2)
        taken = np.zeros(len(q), bool)
        keep_i = []
        for i in range(len(q)):
            if taken[i]:
                continue
            keep_i.append(order[i])
            taken |= d[i] <= merge
        keep_i = np.array(sorted(keep_i))
        pts, sc = pts[keep_i], sc[keep_i]
    return pts, sc
