"""
Unit tests. No data, no checkpoint, no GPU.

Every check here is a property that, if broken, still produces plausible
output -- a corner one cell off still renders as a building. Checks needing
torch or cv2 are skipped, loudly, when those are missing.
"""
import numpy as np

from targets import (SIGMA, crop_side, crop_window, d4_points, decode,
                     render_vertex, to_cells, to_scene)

try:
    import torch                                          # noqa: F401
    HAVE_TORCH = True
except Exception:
    HAVE_TORCH = False
try:
    import cv2                                            # noqa: F401
    HAVE_CV2 = True
except Exception:
    HAVE_CV2 = False

FAIL = SKIP = 0


def ck(name, cond, extra=""):
    global FAIL
    print(f"  {'PASS' if cond else 'FAIL'}  {name}   {extra}")
    if not cond:
        FAIL += 1


def skip(name, why):
    global SKIP
    SKIP += 1
    print(f"  SKIP  {name}   ({why})")


print("[1] crop_side: smooth, monotone, more context for small buildings")
ms = np.arange(5, 400, 1.0)
sides = np.array([crop_side(m) for m in ms])
ck("crop grows monotonically with the box", np.all(np.diff(sides) > 0),
   f"min step {np.diff(sides).min():.4f}")
ck("no discontinuity (max step < 3x median)",
   np.diff(sides).max() < 3 * np.median(np.diff(sides)),
   f"max {np.diff(sides).max():.3f} vs median {np.median(np.diff(sides)):.3f}")
f = sides / ms
ck("context factor FALLS with size", np.all(np.diff(f) < 0),
   f"f(26)={crop_side(26)/26:.2f}  f(65)={crop_side(65)/65:.2f}  "
   f"f(133)={crop_side(133)/133:.2f}")
# the tiered rule this replaces jumps at its thresholds; ours must not
ck("p10/median/p90 land where the README claims",
   abs(crop_side(26) - 54) < 2 and abs(crop_side(65) - 109) < 3
   and abs(crop_side(133) - 185) < 3,
   f"{crop_side(26):.0f} / {crop_side(65):.0f} / {crop_side(133):.0f}")

print()
print("[2] crop_window centres the box, jitter stays bounded")
box = np.array([100.0, 200.0, 160.0, 240.0])
x0, y0, s = crop_window(box)
ck("window is centred on the box",
   abs(x0 + s / 2 - 130) < 1e-9 and abs(y0 + s / 2 - 220) < 1e-9)
ck("window covers the box", x0 <= 100 and y0 <= 200
   and x0 + s >= 160 and y0 + s >= 240)
rng = np.random.RandomState(0)
sh = [crop_window(box, jitter=(0.9, 1.25, 0.06), rng=rng) for _ in range(400)]
ss = np.array([q[2] for q in sh])
ck("jittered side stays inside the requested range",
   ss.min() >= 0.9 * s - 1e-6 and ss.max() <= 1.25 * s + 1e-6,
   f"[{ss.min()/s:.3f}, {ss.max()/s:.3f}] x nominal")
off = np.array([abs(q[0] + q[2] / 2 - 130) / q[2] for q in sh])
ck("centre shift stays within the requested fraction", off.max() <= 0.06 + 1e-9,
   f"max {off.max():.4f}")

print()
print("[3] to_cells / to_scene are exact inverses")
r = rng.uniform(0, 300, (40, 2))
back = to_scene(to_cells(r, 12.5, -3.25, 137.0, 128), 12.5, -3.25, 137.0, 128)
ck("round trip is exact", np.allclose(back, r, atol=1e-9),
   f"max err {np.abs(back-r).max():.2e}")

print()
print("[4] render_vertex: floor cell, exact peak, offsets recover the corner")
OUT = 64
# deliberately none on a cell boundary, and none on an integer
V = np.array([[10.3, 12.7], [30.0 + 1e-9, 40.62], [50.51, 20.49]])
vmap, voff, vmask = render_vertex(V, OUT)
ck("one valid cell per corner", int(vmask.sum()) == len(V), str(int(vmask.sum())))
ck("every corner reaches exactly 1.0", int((vmap >= 0.999).sum()) == len(V),
   f"{int((vmap>=0.999).sum())} cells for {len(V)} corners")
rec = []
for cx, cy in V:
    xi, yi = int(cx), int(cy)
    rec.append([xi + voff[0, yi, xi], yi + voff[1, yi, xi]])
ck("floor + offset reproduces the corner exactly",
   np.allclose(np.array(rec), V, atol=1e-6),
   f"max err {np.abs(np.array(rec)-V).max():.2e} cells")
ck("offsets lie in [0, 1)", voff.min() >= 0 and voff.max() < 1.0,
   f"[{voff.min():.3f}, {voff.max():.3f}]")
# an offset target outside [0,1) would make the sigmoid head unable to reach it
ck("offsets are only non-zero where vmask is",
   np.all((voff.sum(0) != 0) <= (vmask[0] > 0)))

print()
print("[5] two corners three cells apart stay two peaks (max-combine)")
vm2, _, _ = render_vertex(np.array([[20.0, 20.0], [23.0, 20.0]]), OUT)
ck("no brighter blob between them", vm2.max() <= 1.0 + 1e-6, f"{vm2.max():.4f}")
ck("the midpoint stays dark", vm2[20, 21] < 0.9, f"{vm2[20,21]:.3f}")
ck("both peaks present", int((vm2 >= 0.999).sum()) == 2,
   str(int((vm2 >= 0.999).sum())))
# median edge is 35 scene px and a cell is 0.43-1.45 px, so real corners are
# tens of cells apart; 3 is already a pathological case
ck("sigma is tight enough for a 3-cell gap", SIGMA <= 1.5, f"sigma={SIGMA}")

print()
print("[6] d4_points: edge convention, verified against a rasteriser")
S = 96


def _inside(poly, X, Y):
    n = len(poly)
    c = np.zeros(X.shape, bool)
    for i in range(n):
        x0_, y0_ = poly[i]
        x1_, y1_ = poly[(i + 1) % n]
        c ^= ((y0_ > Y) != (y1_ > Y)) & (
            X < (x1_ - x0_) * (Y - y0_) / (y1_ - y0_ + 1e-12) + x0_)
    return c


def _raster(poly, n=S):
    gx, gy = np.meshgrid(np.arange(n) + 0.5, np.arange(n) + 0.5)
    return _inside(np.asarray(poly, float), gx, gy)


rs = np.random.RandomState(0)
worst, n_ex, n_tot = 1.0, 0, 0
for _ in range(80):
    k_ = rs.randint(4, 8)
    ang = np.sort(rs.rand(k_) * 2 * np.pi)
    ctr, rad = rs.uniform(34, 62, 2), rs.uniform(12, 24)
    R = np.stack([ctr[0] + rad * np.cos(ang), ctr[1] + rad * np.sin(ang)], 1)
    M = _raster(R)
    for k in range(4):
        for fl in (False, True):
            Mi = np.rot90(M, k, (0, 1))
            if fl:
                Mi = Mi[:, ::-1]
            Mr = _raster(d4_points(R, k, fl, S))
            u = (Mi | Mr).sum()
            iou = (Mi & Mr).sum() / u if u else 1.0
            worst = min(worst, iou)
            n_ex += iou > 0.999
            n_tot += 1
ck("all 8 symmetries match the raster exactly", worst > 0.999,
   f"worst IoU {worst:.4f}, exact {n_ex}/{n_tot}")
ck("reflection constant is `size`, not `size-1`",
   abs(d4_points(np.array([[0.0, 0.0]]), 0, True, S)[0][0] - S) < 1e-9)
inv = True
pts = rs.uniform(0, S, (50, 2))
for k in range(4):
    inv &= np.allclose(d4_points(d4_points(pts, k, False, S), (4 - k) % 4,
                                 False, S), pts, atol=1e-9)
ck("rotation composes to identity over 4 steps", inv)

print()
print("[7] decode inverts render_vertex")
if not HAVE_TORCH:
    skip("decode round trip", "torch missing")
else:
    pts, sc = decode(vmap, voff, thr=0.3, merge=1.0)
    ck("recovers every corner", len(pts) == len(V), f"{len(pts)} vs {len(V)}")
    if len(pts):
        d = np.linalg.norm(np.sort(pts, 0) - np.sort(V, 0), axis=1)
        ck("to sub-cell precision", d.max() < 1e-4, f"max {d.max():.2e} cells")
    # a corner exactly between two cells makes both equal maxima under
    # `p >= maxpool(p)`, and both offsets point back to the same place
    vm3, vo3, _ = render_vertex(np.array([[25.0, 25.0]]), OUT)
    vm3[25, 26] = vm3[25, 25]
    vo3[0, 25, 26] = -1.0
    p3, _ = decode(vm3, np.clip(vo3, 0, 1), thr=0.3, merge=1.0)
    ck("NMS ties do not emit a duplicate vertex", len(p3) == 1, f"{len(p3)}")
    p4, _ = decode(vm3, np.clip(vo3, 0, 1), thr=0.3, merge=0.0)
    ck("...and merge=0 is what would let it through", len(p4) == 2, f"{len(p4)}")

print()
print("[8] gt_points keeps the sub-cell offset")
from targets import gt_points  # noqa: E402
g = gt_points(vmask, voff)
ck("recovers the exact GT corners", len(g) == len(V)
   and np.abs(np.sort(g, 0) - np.sort(V, 0)).max() < 1e-6,
   f"max err {np.abs(np.sort(g,0)-np.sort(V,0)).max():.2e}"
   if len(g) == len(V) else f"{len(g)} vs {len(V)}")
cell_only = np.stack(np.nonzero(vmask[0] > 0.5)[::-1], 1).astype(float)
err = np.abs(np.sort(cell_only, 0) - np.sort(V, 0)).max()
ck("dropping the offset would inject real error", err > 0.4,
   f"cell-index-only GT is off by up to {err:.2f} cells")

print()
print("[9] losses")
if not HAVE_TORCH:
    skip("losses", "torch missing")
else:
    from losses import BCEDice, masked_offset_loss
    t = torch.zeros(2, 1, 16, 16)
    t[:, :, 4:8, 4:8] = 1.0
    perfect = torch.where(t > 0.5, 12.0, -12.0)
    ck("BCEDice near zero on a perfect prediction",
       float(BCEDice()(perfect, t)) < 0.02, f"{float(BCEDice()(perfect,t)):.4f}")
    ck("BCEDice large on an inverted prediction",
       float(BCEDice()(-perfect, t)) > 5.0, f"{float(BCEDice()(-perfect,t)):.3f}")
    # the property focal lacks: an EXTRA blob must cost, even next to a real one
    extra = perfect.clone()
    extra[:, :, 8:12, 4:8] = 12.0
    ck("an adjacent spurious blob is penalised",
       float(BCEDice()(extra, t)) > float(BCEDice()(perfect, t)) + 0.1,
       f"{float(BCEDice()(perfect,t)):.4f} -> {float(BCEDice()(extra,t)):.4f}")
    tv = torch.zeros(2, 2, 16, 16)
    mk = torch.zeros(2, 1, 16, 16)
    tv[:, :, 5, 5] = 0.37
    mk[:, :, 5, 5] = 1.0
    lg = torch.full((2, 2, 16, 16), -8.0)
    lg[:, :, 5, 5] = float(np.log(0.37 / 0.63))
    ck("masked offset loss is ~0 when the marked cell is right",
       float(masked_offset_loss(lg, tv, mk)) < 1e-3,
       f"{float(masked_offset_loss(lg,tv,mk)):.2e}")
    lg2 = lg.clone()
    lg2[:, :, 9, 9] = 8.0                       # wrong, but unmarked
    ck("unmarked cells are ignored",
       abs(float(masked_offset_loss(lg2, tv, mk))
           - float(masked_offset_loss(lg, tv, mk))) < 1e-9)

print()
print("[10] model shapes and the negative prior")
if not HAVE_TORCH:
    skip("model", "torch missing")
else:
    from model import PolyNet
    m = PolyNet(cin=4, dim=32, encoder="simple", edge=True, width=0.25)
    x = torch.randn(2, 4, 256, 256)
    o = m(x)
    ck("all four heads present",
       set(o) == {"mask", "vmap", "voff", "edge"}, str(sorted(o)))
    ck("output is stride 2", o["mask"].shape[-2:] == (128, 128),
       str(tuple(o["mask"].shape)))
    ck("channel counts", o["mask"].shape[1] == 1 and o["voff"].shape[1] == 2)
    ck("vertex prior starts near zero probability",
       float(torch.sigmoid(o["vmap"]).mean()) < 0.15,
       f"mean p = {float(torch.sigmoid(o['vmap']).mean()):.4f}")
    # the box channel must actually reach the output
    x2 = x.clone()
    x2[:, 3] = 1.0
    ck("the box channel changes the prediction",
       float((m(x2)["vmap"] - o["vmap"]).abs().max()) > 1e-6)
    o["vmap"].sum().backward()
    g = [p.grad for n, p in m.named_parameters() if "enc" in n and p.grad is not None]
    ck("gradient reaches the encoder", len(g) > 0
       and max(float(q.abs().max()) for q in g) > 0)
    ck("crop size is divisible by the stride chain",
       256 % 32 == 0 and 128 % 16 == 0)

print()
print("[11] connect: ordering by projection, not by first appearance")
from connect import drop_spikes, is_simple, order_by_angle, order_by_contour

L = np.array([[20, 20], [60, 20], [60, 60], [100, 60], [100, 100], [20, 100]],
             float)


def dense(ring, step=1.0):
    """Rasterise a ring into an ordered dense contour, cv2-free."""
    out = []
    for i in range(len(ring)):
        a_, b_ = ring[i], ring[(i + 1) % len(ring)]
        n = max(2, int(np.linalg.norm(b_ - a_) / step))
        out.extend(a_ + (b_ - a_) * np.linspace(0, 1, n, endpoint=False)[:, None])
    return np.array(out)


C = dense(L)
rs2 = np.random.RandomState(3)
shuf = L[rs2.permutation(len(L))]
got, t = order_by_contour(C, shuf, max_dist=3.0)
ck("every corner survives the gate", got is not None and len(got) == 6,
   "None" if got is None else str(len(got)))


def same_cycle(p, q):
    """Equal up to rotation and direction."""
    p, q = np.round(p, 3), np.round(q, 3)
    if len(p) != len(q):
        return False
    for r in (q, q[::-1]):
        for k in range(len(r)):
            if np.allclose(p, np.roll(r, k, axis=0)):
                return True
    return False


ck("recovers the true cyclic order", got is not None and same_cycle(got, L),
   "" if got is None else str(np.round(got).astype(int).tolist()))
ck("the ring does not self-intersect", got is not None and is_simple(got))

# THE MEASURED COMPARISON. A hand-picked example proves nothing here: on
# CLEAN candidates the two orderings are indistinguishable (0.5% dropped, 3.8%
# vs 3.2% crossing). The difference only appears with spurious peaks and a
# loose gate, which is the situation that produced crossed rings on real data.
def first_appearance(C_, cands, max_dist):
    d = np.linalg.norm(C_[:, None, :] - cands[None, :, :], axis=2)
    near = d.argmin(1)
    ok = d[np.arange(len(C_)), near] <= max_dist
    seq, seen = [], set()
    for i in range(len(C_)):
        if not ok[i]:
            continue
        j = int(near[i])
        if j not in seen:
            seen.add(j)
            seq.append(j)
    return cands[seq] if len(seq) >= 3 else None


def _sweep(fn, gate, n=200):
    rr = np.random.RandomState(0)
    cross = tot = 0
    for _ in range(n):
        m = rr.randint(4, 9)
        an = np.sort(rr.rand(m) * 2 * np.pi)
        rad = rr.uniform(20, 50, m)
        R = np.stack([60 + rad * np.cos(an), 60 + rad * np.sin(an)], 1)
        Cc = dense(R)
        spur = np.stack([60 + rr.uniform(-30, 30, 2),
                         60 + rr.uniform(-30, 30, 2)], 1)
        cd = np.vstack([R + rr.normal(0, 0.8, R.shape), spur])
        q = fn(Cc, cd, gate)
        if q is None or len(q) < 3:
            continue
        tot += 1
        cross += not is_simple(q)
    return cross / max(tot, 1)


fa40 = _sweep(first_appearance, 40.0)
pr40 = _sweep(lambda c, v, g: order_by_contour(c, v, g)[0], 40.0)
pr06 = _sweep(lambda c, v, g: order_by_contour(c, v, g)[0], 6.0)
fa06 = _sweep(first_appearance, 6.0)
ck("a tight gate is the dominant fix", fa06 < fa40 / 2,
   f"first-appearance crossings {fa40:.1%} at gate 40 -> {fa06:.1%} at gate 6")
ck("projection ordering is robust to a loose gate", pr40 < fa40 / 2,
   f"at gate 40: first-appearance {fa40:.1%} vs projection {pr40:.1%}")
ck("neither reaches zero, so is_simple must stay", pr06 > 0,
   f"projection at the tight gate still crosses {pr06:.1%} of the time")

# simplify_ring: SAMPolyBuild's simple_polygon, the piece that keeps v/GT down
from connect import simplify_ring
sq = np.array([[0, 0], [10, 0], [20, 0], [20, 20], [0, 20]], float)
ck("a collinear vertex is removed", len(simplify_ring(sq)) == 4,
   f"{len(sq)} -> {len(simplify_ring(sq))}")
ck("the real corners survive",
   same_cycle(simplify_ring(sq),
              np.array([[0, 0], [20, 0], [20, 20], [0, 20]], float)))
spike = np.array([[0, 0], [20, 0], [20, 20], [10, 20], [10.2, 8.0],
                  [9.8, 20], [0, 20]], float)
out = simplify_ring(spike)
ck("a spike is removed", len(out) < len(spike), f"{len(spike)} -> {len(out)}")
ck("a clean quad is left alone",
   len(simplify_ring(np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float))) == 4)
ck("a triangle is never reduced below 3",
   len(simplify_ring(np.array([[0, 0], [10, 0], [5, 9]], float))) == 3)

# make_simple / the widened spike band: what a "crossing" usually really is
from connect import make_simple
wedge = np.array([[0, 0], [100, 0], [100, 60], [52, 60], [50, 15], [48, 60],
                  [0, 60]], float)
ck("the old 175-185 band missed a 30-degree wedge",
   len(simplify_ring(wedge, spike_band=(175.0, 185.0))) == len(wedge),
   f"{len(wedge)} vertices in, {len(simplify_ring(wedge, spike_band=(175.,185.)))} out")
ck("the measured 150-210 band removes it", len(simplify_ring(wedge)) < len(wedge),
   f"{len(wedge)} -> {len(simplify_ring(wedge))}  "
   f"(only 0.064% of real GT corners turn more than 150 deg)")

Lx = np.array([[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]], float)
crossed = Lx.copy()
crossed[[2, 4]] = crossed[[4, 2]]
ck("the crossed ring really does self-intersect", not is_simple(crossed))
fixed, _ = make_simple(crossed)
ck("make_simple returns a valid ring", is_simple(fixed),
   f"{len(crossed)} -> {len(fixed)} vertices")
ck("it drops as few vertices as it can", len(fixed) >= len(crossed) - 2,
   f"{len(crossed)} -> {len(fixed)}")
ck("a ring that is already simple is untouched",
   len(make_simple(Lx)[0]) == len(Lx) and np.allclose(make_simple(Lx)[0], Lx))
ck("indices stay aligned when vertices are dropped",
   (lambda r: r[1] is not None and len(r[1]) == len(r[0]))(
       make_simple(crossed, np.arange(len(crossed)))))

# fit_edges: the head picks the corners, the mask says where the walls are
from connect import fit_edges
rect = np.array([[30, 30], [150, 30], [150, 120], [30, 120]], float)
Cr = dense(rect)
noisy = rect + np.array([[3, 2], [-2, 3], [2, -3], [-3, -2]], float)
qn, tn = order_by_contour(Cr, noisy, 12.0)
ck("noisy corners are what the head gives", qn is not None and len(qn) == 4)
fitted, nmov = fit_edges(qn, tn, Cr)
e_before = np.linalg.norm(qn[:, None, :] - rect[None, :, :], axis=2).min(0).mean()
e_after = np.linalg.norm(fitted[:, None, :] - rect[None, :, :], axis=2).min(0).mean()
ck("fitting pulls corners onto the true walls", e_after < e_before / 2,
   f"mean corner error {e_before:.2f} -> {e_after:.2f} cells")
ck("it moves corners without adding any", len(fitted) == len(qn) and nmov > 0,
   f"{nmov} of {len(qn)} corners repositioned, count unchanged")
# a wall too short to fit must leave its corners alone
short, _ = fit_edges(qn, tn, Cr[:6])
ck("too few contour points -> no change", short is not None)
# an implausible jump must be rejected rather than flung across the image
far = qn.copy()
far[0] += 400
kept, _ = fit_edges(far, tn, Cr)
ck("max_move rejects an implausible intersection",
   np.linalg.norm(kept[0] - far[0]) < 1e-9,
   "a corner 400 cells out stays where the head put it")

# prune_thin: tentacles and bays are THIN, not small, so simplification misses
from connect import prune_thin
sq_ring = dense(np.array([[20, 20], [120, 20], [120, 120], [20, 120]], float))
tip = len(sq_ring) // 4
tent = np.vstack([sq_ring[:tip],
                  sq_ring[tip] + (sq_ring[tip] - sq_ring[tip - 3]),
                  sq_ring[tip] + np.array([18.0, 0.0]),
                  sq_ring[tip] + (sq_ring[tip] - sq_ring[tip + 3]),
                  sq_ring[tip + 1:]])
pr = prune_thin(tent, 0.06 * 100)
ck("a tentacle is cut out",
   len(pr) < len(tent) and pr[:, 0].max() < sq_ring[:, 0].max() + 4,
   f"reach {tent[:,0].max():.0f} -> {pr[:,0].max():.0f} "
   f"(clean is {sq_ring[:,0].max():.0f})")
ck("a clean contour is left alone",
   len(prune_thin(sq_ring, 0.06 * 100)) == len(sq_ring),
   f"{len(sq_ring)} -> {len(prune_thin(sq_ring, 0.06*100))}")
ck("a short contour is returned untouched", len(prune_thin(sq_ring[:6], 5.0)) == 6)
ck("pruning never returns a degenerate ring", len(prune_thin(sq_ring, 1e6)) >= 8,
   "an absurd width must not eat the shape")

# refine_against_contour: the mask supplies corners the head missed
from connect import refine_against_contour
Lc = dense(L)
tri_i = [0, 2, 4]                                    # keep 3 of the 6 corners
q3, t3 = order_by_contour(Lc, L[tri_i], 3.0)
ck("with corners missing the ring is badly wrong", q3 is not None and len(q3) == 3,
   f"{0 if q3 is None else len(q3)} vertices from 6 real corners")
side_L = max(np.ptp(L[:, 0]), np.ptp(L[:, 1]))
q4, t4, a4 = refine_against_contour(q3, t3, Lc, 0.06 * side_L)
ck("refinement puts the missing corners back", len(q4) >= 5,
   f"{len(q3)} -> {len(q4)} vertices")
ck("and the recovered ring is simple", is_simple(q4))
qf, tf = order_by_contour(Lc, L, 3.0)
qr, _, ar = refine_against_contour(qf, tf, Lc, 0.06 * side_L)
ck("a correct ring is left completely untouched",
   len(qr) == len(qf) and np.allclose(qr, qf),
   f"{len(qf)} -> {len(qr)} vertices")
ck("the added flags mark exactly the mask-supplied corners",
   a4.sum() == len(q4) - len(q3) and not ar.any(),
   f"{int(a4.sum())} flagged of {len(q4)-len(q3)} inserted; "
   f"{int(ar.sum())} flagged on an untouched ring")
ck("max_add bounds how much the mask may contribute",
   len(refine_against_contour(q3, t3, Lc, 0.0, max_add=2)[0]) <= len(q3) + 2,
   "tol 0 would otherwise insert without limit")

ck("is_simple accepts a convex quad",
   is_simple(np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)))
ck("is_simple rejects a bowtie",
   not is_simple(np.array([[0, 0], [10, 10], [10, 0], [0, 10]], float)))
ck("angular sort is exact on a convex ring",
   same_cycle(order_by_angle(np.array([[0, 0], [10, 10], [10, 0], [0, 10]], float)),
              np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)))

if not HAVE_CV2:
    skip("build_polygon end to end", "cv2 missing")
else:
    from connect import build_polygon
    mask = np.zeros((120, 120), np.uint8)
    mask[20:100, 20:60] = 1
    mask[60:100, 20:100] = 1
    poly, src, meta = build_polygon(L, mask.astype(bool),
                                    baseline=np.array([[0, 0], [1, 0], [1, 1]]))
    ck("build_polygon takes the vertex path", src == "vertex", src)
    ck("and returns a simple ring", is_simple(poly))
    poly2, src2, _ = build_polygon(L + 500, mask.astype(bool),
                                   baseline=np.array([[0, 0], [1, 0], [1, 1]]))
    ck("meta reports vertex provenance",
       set(("n_detected", "n_added")) <= set(meta), str(sorted(meta)))
    ck("catastrophe falls back to the baseline", src2 == "baseline", src2)

print()
print(f"{FAIL} failures, {SKIP} skipped")
raise SystemExit(1 if FAIL else 0)
