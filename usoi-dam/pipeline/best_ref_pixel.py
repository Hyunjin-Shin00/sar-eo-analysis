#!/usr/bin/env python3
# Pick a reference pixel that is reliable (connComp>0) in as many KEPT interferograms as
# possible, with the highest average coherence. Auto maxCoherence picks high-average but
# per-ifg-unreliable pixels, which corrupts the SBAS inversion (temporalCoherence -> 0).
# Usage: best_ref_pixel.py <ifgramStack.h5>   -> prints "Y X" (radar row col)
import sys, numpy as np, h5py
f = h5py.File(sys.argv[1], 'r')
drop = np.array(f['dropIfgram']).astype(bool)
keep = np.where(drop)[0]
nk = len(keep)
cc = f['connectComponent']; coh = f['coherence']
H, W = cc.shape[1], cc.shape[2]
relcount = np.zeros((H, W), dtype=np.int32)
cohsum = np.zeros((H, W), dtype=np.float64)
for i in keep:
    relcount += (cc[i] > 0)
    g = coh[i]; cohsum += np.where(np.isfinite(g), g, 0.0)
cohavg = cohsum / max(nk, 1)
# prefer pixels reliable in the most ifgs; break ties by average coherence
best = None
for thr in [nk, int(nk*0.99), int(nk*0.98), int(nk*0.95), int(nk*0.90), int(nk*0.80), relcount.max()]:
    m = relcount >= thr
    if m.sum() > 0:
        ca = np.where(m, cohavg, -1.0)
        idx = np.unravel_index(np.argmax(ca), ca.shape)
        best = (int(idx[0]), int(idx[1]))
        sys.stderr.write("ref y,x=%d,%d relcount=%d/%d cohavg=%.3f (thr=%d)\n" %
                         (best[0], best[1], relcount[idx], nk, cohavg[idx], thr))
        break
print("%d %d" % best)
