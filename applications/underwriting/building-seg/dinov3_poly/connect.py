"""
Candidates + the predicted mask -> an ordered polygon.

The vertex head gives an unordered point set. The mask supplies the one thing
it cannot: the cyclic ORDER. Note which mask -- stage 2's own, predicted at
0.43-1.45 scene px per cell, not stage 1's at 2 px. The mask decides the order
of the corners, never their position.

ORDER BY EACH CANDIDATE'S OWN PROJECTION ONTO THE CONTOUR, not by walking the
contour and taking first appearances. The walk version is what produced
self-intersecting rings in the first real run, and it fails two ways at once:

  * a candidate that is never any contour point's nearest neighbour is dropped
    entirely -- a four-corner building comes out a triangle
  * a spurious candidate captures a short run of contour points and is spliced
    into the middle of the ring -- a spike, and usually a crossing

Projecting instead gives every candidate exactly one position, decided by
itself, and the traversal is monotone along the boundary.

MEASURED, because an earlier draft of this docstring claimed projection
ordering "cannot cross" and that is false -- it can, when a candidate sits far
enough off the boundary that its projection lands out of spatial order. 300
random rings, true corners plus two spurious peaks each:

    ordering            gate    self-intersect    polygon IoU
    first appearance      40           8.7%          0.765
    projection            40           1.3%          0.799
    first appearance      12           5.7%          0.853
    projection            12           1.7%          0.869
    first appearance       6           2.3%          0.911
    projection             6           2.0%          0.918

Two things follow. THE GATE IS THE DOMINANT FIX: 0.25 of the building side was
about four times SAMPolyBuild's, and it cost 0.15 of polygon IoU. Projection
ordering is a real but secondary gain, worth most exactly when the gate is
loose -- it holds 1.3-2.0% across the whole range where first appearance runs
2.3-8.7%. And crossings never reach zero, which is why `is_simple` and the
fallback exist rather than being trusted away.
"""
import numpy as np


def contour_of(mask):
    import cv2
    c, _ = cv2.findContours(np.ascontiguousarray(mask.astype(np.uint8)),
                            cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not c:
        return None
    return max(c, key=cv2.contourArea)[:, 0, :].astype(np.float64)


def polygon_iou(poly, mask):
    import cv2
    if poly is None or len(poly) < 3:
        return 0.0
    c = np.zeros(mask.shape, np.uint8)
    cv2.fillPoly(c, [np.round(poly).astype(np.int32)], 1)
    c = c.astype(bool)
    u = np.logical_or(c, mask).sum()
    return float(np.logical_and(c, mask).sum() / u) if u else 0.0


def order_by_contour(C, cands, max_dist):
    """
    Order candidates by where each PROJECTS onto the closed contour C.

    C     (n, 2)  contour points in traversal order
    cands (m, 2)  unordered candidates
    max_dist      candidates further than this from the contour are dropped

    Pure numpy so it can be tested without cv2.
    """
    if C is None or len(C) < 4 or len(cands) == 0:
        return None, None
    d = np.linalg.norm(C[:, None, :] - np.asarray(cands)[None, :, :], axis=2)
    t = d.argmin(0)                                   # contour index per candidate
    dv = d[t, np.arange(d.shape[1])]                  # distance to the contour
    keep = np.nonzero(dv <= max_dist)[0]
    if len(keep) < 3:
        return None, None
    # two candidates projecting to the same contour point would give a
    # zero-length edge; keep the closer one
    order = keep[np.argsort(t[keep], kind="stable")]
    out, last = [], -1
    for j in order:
        if t[j] == last and out:
            if dv[j] < dv[out[-1]]:
                out[-1] = j
            continue
        out.append(j)
        last = t[j]
    return np.asarray(cands)[out], t[out]


def drop_spikes(poly, C, t, angle_tol=75.0):
    """
    Remove a vertex whose local direction disagrees with the contour's.

    SAMPolyBuild's test, in the same spirit: between consecutive kept vertices
    the step along the CONTOUR and the step between the VERTICES should point
    roughly the same way. A candidate sitting off the boundary -- a neighbour's
    corner, or a stray peak -- breaks that agreement while still being close
    enough to pass a distance gate.

    Applied repeatedly, worst first, because removing one vertex changes its
    neighbours' vectors.

    OFF BY DEFAULT, because on the synthetic benchmark above it earns almost
    nothing once the gate is correct: at tol 75 it moved polygon IoU by +0.0008
    and left the crossing rate unchanged; even tol 50 gave +0.0023 and
    1.7% -> 1.3%. The gate already removes what this was meant to catch.
    Kept because the synthetic spurious peaks are uniform inside the shape
    while real ones cluster near the boundary, so it may behave differently on
    real data -- `--angle-tol 50` turns it on for an A/B.
    """
    if len(poly) <= 3:
        return poly
    poly = np.asarray(poly, np.float64)
    t = np.asarray(t)
    while len(poly) > 3:
        n = len(poly)
        worst, worst_a = -1, angle_tol
        for i in range(n):
            j = (i + 1) % n
            vc = C[int(t[j])] - C[int(t[i])]
            vv = poly[j] - poly[i]
            nc, nv = np.linalg.norm(vc), np.linalg.norm(vv)
            if nc < 1e-6 or nv < 1e-6:
                continue
            cos = float(np.dot(vc, vv) / (nc * nv))
            a = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
            if a > worst_a:
                worst, worst_a = j, a
        if worst < 0:
            break
        poly = np.delete(poly, worst, axis=0)
        t = np.delete(t, worst)
    return poly


def simplify_ring(poly, min_turn=10.0, spike_band=(150.0, 210.0)):
    """
    Drop near-collinear vertices and spikes. SAMPolyBuild's `simple_polygon`.

    Two removals in one pass, both keyed on the TURN angle at a vertex (0 =
    straight on, 180 = doubling back):

      * turn below min_turn -- the vertex sits on a straight run. Two candidate
        peaks on one wall of a building produce this, and the extra vertex
        costs precision and `v/GT` while changing the shape by nothing.
      * turn inside spike_band -- the ring folds back on itself, which is the
        thin wedge a stray or mis-fitted corner creates.

    THE BAND IS 150-210, NOT 175-185. Measured over 31 070 refined GT corners,
    the turn magnitude has p99.9 = 143.2 degrees and only 0.064% of real
    corners fall in [150, 210] at all -- real buildings simply do not fold back.
    The original 175-185 only caught an exact reversal, so a wedge with a 30
    degree opening (turn 150) sailed through and rendered as a triangular slice
    cut out of the building. Widening costs 0.064% of real corners.

    SAMPolyBuild runs this on the VERTEX polygon as well as on the contour,
    which is the part worth copying: the vertex head is exactly what produces
    redundant collinear corners.
    """
    p = np.asarray(poly, np.float64)
    if len(p) > 3 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    if len(p) < 4:
        return p
    v0 = np.roll(p, -1, axis=0) - p                  # edge i -> i+1
    v1 = np.roll(v0, -1, axis=0)                     # edge i+1 -> i+2
    a0 = np.degrees(np.arctan2(v0[:, 1], v0[:, 0]))
    a1 = np.degrees(np.arctan2(v1[:, 1], v1[:, 0]))
    ang = np.abs(a0 - a1)
    keep = (((ang > min_turn) & (ang < spike_band[0]))
            | ((ang > spike_band[1]) & (ang < 360.0 - min_turn)))
    # `keep[i]` is computed from the two edges meeting at vertex i+1
    out = p[np.roll(keep, 1, axis=0)]
    return out if len(out) >= 3 else p


def prune_thin(C, max_width, max_arc=0.35):
    """
    Cut tentacles and bays out of a contour before it is used as a guide.

    A BAD MASK'S ARTIFACTS ARE THIN, NOT SMALL, and that is why simplification
    does not remove them. A tentacle 15 px deep is a large deviation, so
    Douglas-Peucker at any epsilon that preserves real notches keeps it --
    measured: a DP guide at eps 0.05*side left 8.33 vertices per polygon
    against 6.00 on a clean contour, i.e. it removed none of the artifact.

    What identifies a thin feature is that the contour LEAVES AND RETURNS to
    nearly the same place: the two flanks of a tentacle sit within its width of
    each other, however deep it goes. So scan for pairs (i, j) whose contour
    points are within `max_width` while the arc between them is long enough to
    be an excursion rather than a corner, and replace that arc with the chord.
    Symmetric in sign, so it removes bays as well as tentacles.

    max_arc caps the fraction of the contour a single cut may remove, so a
    genuine narrow wing of an L is never swallowed whole.
    """
    C = np.asarray(C, np.float64)
    n = len(C)
    if n < 12:
        return C
    lim = max(4, int(max_arc * n))
    keep = np.ones(n, bool)
    i = 0
    while i < n - 1:
        if not keep[i]:
            i += 1
            continue
        best = -1
        for j in range(min(i + lim, n - 1), i + 3, -1):
            chord = C[j] - C[i]
            if np.linalg.norm(chord) > max_width:
                continue
            # THE ARC MUST ACTUALLY GO SOMEWHERE. Without this the filter eats
            # straight walls: on a 1 px-spaced contour any two points within
            # max_width are only max_width steps apart, so every run of a
            # dense boundary looks like a returning excursion. Measured before
            # the check was added -- a clean 400-point square came back as 67.
            arc = C[i:j + 1]
            L = np.linalg.norm(chord)
            dev = (np.abs(np.cross(chord, arc - C[i])).max() / L if L > 1e-9
                   else np.linalg.norm(arc - C[i], axis=1).max())
            if dev > max_width:
                best = j
                break
        if best > 0:
            keep[i + 1:best] = False
            i = best
        else:
            i += 1
    out = C[keep]
    return out if len(out) >= 8 else C


def refine_against_contour(poly, t, C, tol, max_add=4):
    """
    Insert contour points where the vertex ring departs badly from the mask.

    THE CASE THIS EXISTS FOR: the mask covers an L- or T-shaped building
    perfectly and the head finds only the outer corners, so the polygon cuts
    straight across the notch. Nothing else in this file recovers that -- the
    IoU guard fires only below 0.35 and such a polygon scores ~0.75, so it
    passes -- and the result is a confidently wrong shape on an instance whose
    mask was right.

    Douglas-Peucker, but SEEDED WITH THE DETECTED VERTICES rather than run from
    scratch. Between two consecutive detected corners lies a known arc of the
    contour; if that arc bows away from the straight edge by more than `tol`,
    the point of maximum deviation is a corner the head missed, so it is
    inserted and the two halves are re-checked.

    This is a deliberate, bounded re-introduction of mask dependence, and the
    boundary is `tol`. Below it the mask says nothing and the head's corners
    stand exactly as predicted; above it the mask is describing a shape the
    head did not report at all. `tol` is a fraction of the building's long
    side, so it means the same thing at 26 px and at 133 px.

    MEASURED, both directions. Recovering missed corners (L/T shapes, tol 0.06):

        corners missed     no refine     refined
              0             0.9670       0.9670    <- untouched when correct
              1             0.7377       0.9697
              2             0.5534       0.9588

    And the cost when the MASK is the thing that is wrong, vertices correct:

        mask IoU      no refine    tol 0.06    tol 0.03
          0.999        0.9670       0.9670      0.9670
          0.952        0.9678       0.9678      0.9670
          0.907        0.9678       0.9660      0.9130
          0.823        0.9662       0.8429      0.8758

    So the safe envelope is roughly mask IoU >= 0.90, and tol 0.03 is already
    outside it. Stage 2 validates at 0.9266, inside with a modest margin --
    which is exactly why this is worth doing here and would not have been on
    stage 1's 0.825 masks. `max_add` bounds the damage if a mask is much worse
    than typical: at mask IoU 0.823 a cap of 4 holds 0.8836 where 8 gives
    0.8394, while at 0.907 the two are identical.
    """
    if poly is None or len(poly) < 3 or C is None:
        return poly, t, np.zeros(0 if poly is None else len(poly), bool)
    P = [np.asarray(v, np.float64) for v in poly]
    T = [int(k) for k in t]
    A = [False] * len(P)          # provenance: did the MASK invent this vertex?
    n = len(C)
    added = 0

    def dev(a, b, arc):
        """Max perpendicular deviation of arc points from segment a-b."""
        d = b - a
        L = np.linalg.norm(d)
        if L < 1e-9 or len(arc) == 0:
            return -1.0, -1
        w = np.abs(np.cross(d, arc - a)) / L
        k = int(np.argmax(w))
        return float(w[k]), k

    i = 0
    while i < len(P) and added < max_add:
        j = (i + 1) % len(P)
        t0, t1 = T[i], T[j]
        idx = (np.arange(t0 + 1, t1) if t1 > t0
               else np.concatenate([np.arange(t0 + 1, n), np.arange(0, t1)]))
        if len(idx) < 2:
            i += 1
            continue
        arc = C[idx]
        w, k = dev(P[i], P[j], arc)
        if w <= tol:
            i += 1
            continue
        P.insert(j, arc[k])
        T.insert(j, int(idx[k]))
        A.insert(j, True)
        added += 1
        # do not advance: the new left half may still deviate
    return np.array(P), np.array(T), np.array(A)


def fit_edges(poly, t, C, trim=0.20, min_pts=8, max_move=0.12):
    """
    Keep the head's corners, refit the WALLS to the mask, corners = intersections.

    THE DIVISION OF LABOUR THIS ENFORCES. The head is the only thing that knows
    the TOPOLOGY -- how many corners a building has and which stretches of
    boundary are one wall -- which is why tracing a mask gives twelve vertices
    on a rounded eight-corner shed. The mask is the only thing that knows where
    each wall actually SITS, and it knows it far better than a heatmap peak
    does: a total-least-squares line through fifty contour points averages the
    wobble away, while a peak is one guess at one pixel.

    So the corner count comes from the head and the corner POSITION comes from
    intersecting two fitted walls. This is what closes the coverage gap without
    paying polygonize's vertex count.

    trim discards the fraction of each arc nearest the corners, where a raster
    boundary rounds off and would drag the fit.

    max_move (fraction of the building's long side) rejects an intersection
    that lands implausibly far from the head's corner -- two nearly parallel
    walls intersect at infinity, and a bad fit must fall back rather than fling
    a vertex across the image.
    """
    if poly is None or t is None or C is None or len(poly) < 3:
        return poly, 0
    P = np.asarray(poly, np.float64)
    t = np.asarray(t)
    n = len(C)
    # `t` indexes the contour that produced the ordering. If a caller passes a
    # different or truncated contour those indices address nothing, and the
    # arcs would be silently wrong rather than obviously so -- refuse instead.
    if len(t) != len(P) or n < 4 or int(t.max()) >= n:
        return P, 0
    ys, xs = P[:, 1], P[:, 0]
    side = max(xs.max() - xs.min(), ys.max() - ys.min()) + 1
    lim = max_move * side

    lines = []
    for i in range(len(P)):
        j = (i + 1) % len(P)
        t0, t1 = int(t[i]), int(t[j])
        idx = (np.arange(t0 + 1, t1) if t1 > t0
               else np.concatenate([np.arange(t0 + 1, n), np.arange(0, t1)]))
        if len(idx) < min_pts:
            lines.append(None)
            continue
        k = int(trim * len(idx))
        seg = C[idx[k:len(idx) - k]] if len(idx) - 2 * k >= min_pts else C[idx]
        mu = seg.mean(0)
        # direction = first right-singular vector: total least squares, which
        # is correct here because a wall may be vertical and y-on-x regression
        # would blow up on exactly those
        d = np.linalg.svd(seg - mu, full_matrices=False)[2][0]
        lines.append((mu, d / (np.linalg.norm(d) + 1e-12)))

    out, moved = P.copy(), 0
    for i in range(len(P)):
        a, b = lines[i - 1], lines[i]
        if a is None or b is None:
            continue
        (m0, d0), (m1, d1) = a, b
        den = d0[0] * d1[1] - d0[1] * d1[0]
        if abs(den) < 1e-6:                       # parallel walls
            continue
        w = m1 - m0
        s_ = (w[0] * d1[1] - w[1] * d1[0]) / den
        q = m0 + s_ * d0
        if np.linalg.norm(q - P[i]) <= lim:
            out[i] = q
            moved += 1
    return out, moved


def make_simple(poly, t=None, max_drop=3):
    """
    Drop the fewest vertices needed to stop the ring crossing itself.

    A BETTER FALLBACK THAN AN ANGULAR SORT. When a ring crosses, exactly one
    candidate is usually to blame, and the contour ordering of the rest is
    correct -- so discarding the offender keeps a shape that still follows the
    building. Re-sorting everything by angle about the centroid throws that
    ordering away, and on the 26.4% of these polygons that are non-convex it
    produces a ring that is simple and wrong, which is worse than one that is
    visibly broken.
    """
    p = np.asarray(poly, np.float64)
    tt = None if t is None else np.asarray(t)
    for _ in range(max_drop):
        if is_simple(p) or len(p) <= 3:
            break
        hit = None
        for i in range(len(p)):
            if is_simple(np.delete(p, i, axis=0)):
                hit = i
                break
        if hit is None:
            # no single removal fixes it: drop the sharpest fold and re-try
            v0 = np.roll(p, -1, axis=0) - p
            v1 = np.roll(v0, -1, axis=0)
            a0 = np.degrees(np.arctan2(v0[:, 1], v0[:, 0]))
            a1 = np.degrees(np.arctan2(v1[:, 1], v1[:, 0]))
            fold = np.abs(a0 - a1) % 360
            fold = np.minimum(fold, 360 - fold)
            hit = int(np.roll(np.argsort(-fold), 1)[0])
        p = np.delete(p, hit, axis=0)
        if tt is not None:
            tt = np.delete(tt, hit)
    return p, tt


def is_simple(poly):
    """No two non-adjacent edges of the closed ring may cross."""
    p = np.asarray(poly, np.float64)
    n = len(p)
    if n < 4:
        return True

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or j == (i + 1) % n:
                continue
            c, d = p[j], p[(j + 1) % n]
            d1, d2 = cross(a, b, c), cross(a, b, d)
            d3, d4 = cross(c, d, a), cross(c, d, b)
            if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
                return False
    return True


def order_by_angle(cands):
    """Last resort: 73.6% of these polygons are convex, where this is exact."""
    if len(cands) < 3:
        return None
    c = np.asarray(cands).mean(0)
    a = np.arctan2(np.asarray(cands)[:, 1] - c[1], np.asarray(cands)[:, 0] - c[0])
    return np.asarray(cands)[np.argsort(a)]


def build_polygon(cands, mask, baseline=None, max_dist_frac=0.08,
                  angle_tol=None, min_turn=10.0, refine_tol=0.06, max_add=4,
                  prune_width=0.06, fit=True, guard_min_iou=0.35,
                  check_simple=True):
    """
    (polygon, source) with source in {'vertex', 'angle', 'baseline'}.

    max_dist_frac is the candidate-to-contour gate as a fraction of the mask's
    long side, which makes it scale-free. THE DEFAULT IS CALIBRATED, not
    guessed: SAMPolyBuild gates at 10-13 px on a 224 crop, about 5% of the
    frame, and the first version of this file used 0.25 -- roughly four times
    looser, which admitted every stray peak and is why the rings crossed.

    fit refits each wall to the mask and puts corners at the intersections
    (see fit_edges). It is what closes the coverage gap against the rule-based
    polygonizer without paying its vertex count: at 2.5 cells of head corner
    noise it took polygon IoU 0.9442 -> 0.9949 and mean corner error 3.04 ->
    0.33 with the vertex count unchanged. It DOES make corner position depend
    on the mask, and the crossover is about 2 px of systematic mask bias --
    beyond that the head's own corners are better. Measure before trusting it
    on a new checkpoint; train.py reports the bias each epoch.

    prune_width cuts tentacles and bays out of the guide contour first. It
    matters BECAUSE of refine_tol: a 15 px tentacle is a large deviation, so
    refinement reads it as a missed corner and inserts vertices along it.
    Measured on a contour carrying one artifact, vertices per polygon 8.34 ->
    6.00 and polygon IoU 0.9697 -> 0.9774, with a clean contour unchanged.
    Simplifying the guide instead does NOT work -- see prune_thin.

    refine_tol lets the MASK insert corners the head missed, but only where the
    two disagree by more than that fraction of the building's long side. See
    refine_against_contour: it is what stops a perfectly-masked L-shaped
    building coming out as a quadrilateral. 0 disables it.

    min_turn drops near-collinear vertices and spikes (see simplify_ring).
    MEASURED SAFE ON THIS GT: at 10 degrees it would delete 0.50% of real
    corners, because real turns cluster at 90 (p5 = 85.3) and only 0.039% of GT
    vertices fall in the 175-185 spike band. Synthetically it takes vertices per
    true corner from 1.28 to 1.06 for -0.002 polygon IoU -- almost pure
    precision, which is the metric this project is judged on.

    THE GUARD IS AN ABSOLUTE FLOOR, NOT A COMPARISON AGAINST THE BASELINE.
    Keeping the detection only when it beats a mask-derived polygon on IoU
    against that same mask rejects even exact GT vertices on almost every
    instance -- a truth-shaped polygon scores worse against an imperfect mask
    than one traced from it, and departing from the mask is the entire purpose.
    So the floor only catches catastrophe.
    """
    ys, xs = np.nonzero(mask)
    meta = {"n_detected": int(len(cands)), "n_added": 0, "added": None,
            "n_fitted": 0}
    if len(ys) == 0:
        return baseline, "baseline", meta
    side = max(xs.max() - xs.min(), ys.max() - ys.min()) + 1
    gate = max(2.0, max_dist_frac * side)

    C = contour_of(mask)
    if C is not None and prune_width > 0:
        C = prune_thin(C, prune_width * side)
    poly, t = order_by_contour(C, cands, gate)
    src = "vertex"
    added = None
    if poly is not None and refine_tol > 0:
        poly, t, added = refine_against_contour(poly, t, C, refine_tol * side,
                                                max_add=max_add)
        meta["n_added"] = int(added.sum())
        meta["added"] = added
    if poly is not None and fit and src == "vertex":
        poly, nmov = fit_edges(poly, t, C)
        meta["n_fitted"] = int(nmov)
    if poly is not None and angle_tol is not None and len(poly) > 3:
        poly = drop_spikes(poly, C, t, angle_tol)
    if poly is not None and min_turn > 0 and len(poly) > 3:
        before = poly
        poly = simplify_ring(poly, min_turn=min_turn)
        if added is not None and len(poly) != len(before):
            # keep provenance aligned by matching surviving vertices back
            keep_i = [int(np.argmin(np.linalg.norm(before - v, axis=1)))
                      for v in poly]
            added = added[keep_i]
            meta["added"] = added
            meta["n_added"] = int(added.sum())
    if poly is not None and check_simple and not is_simple(poly):
        # ordering by projection cannot cross on its own, so a crossing here
        # means a candidate is off the boundary; the angular sort is the
        # cheapest ring that is guaranteed not to cross
        poly, t = make_simple(poly, t)
        meta["added"] = None
        meta["n_unfolded"] = 1
        if not is_simple(poly):
            alt = order_by_angle(poly)
            if alt is not None and is_simple(alt):
                poly, src = alt, "angle"
            else:
                poly = None
    if poly is None or len(poly) < 3:
        poly = order_by_angle(cands)
        src, meta["added"] = "angle", None
    if poly is None or len(poly) < 3:
        return baseline, "baseline", meta
    if guard_min_iou > 0 and baseline is not None:
        if polygon_iou(poly, mask) < guard_min_iou:
            return baseline, "baseline", meta
    meta["n_vertices"] = int(len(poly))
    meta["t"] = t if src == "vertex" else None
    meta["tol"] = float(refine_tol * side)
    return poly, src, meta
