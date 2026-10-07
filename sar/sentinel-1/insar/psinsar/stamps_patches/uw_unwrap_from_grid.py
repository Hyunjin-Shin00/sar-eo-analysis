import numpy as np
import multiprocessing
from psi_python.logit import logit
from psi_python.stamps_save import stamps_save

# 전역 변수 선언
global_uw = None
global_uu = None
global_gridix = None
global_grid_ij = None

global_ph_in_is_real = None


def init_worker(uw_, uu_, gridix_, grid_ij_):
    global global_uw, global_uu, global_gridix, global_grid_ij, global_ph_in_is_real
    global_uw = uw_
    global_uu = uu_
    global_gridix = gridix_
    global_grid_ij = grid_ij_
    # FIX: upstream evaluated np.isreal(ph_in).all() INSIDE compute_ph_uw, i.e.
    # once per PS. ph_in is n_ps x n_ifg (196M elements here), so every one of
    # the 6.3M iterations allocated a ~200MB boolean array. It is a property of
    # the whole array - evaluate it once per worker.
    global_ph_in_is_real = bool(np.isrealobj(uw_['ph_in']))

def compute_ph_uw(i):
    ix = global_gridix[int(global_grid_ij[i, 0]), int(global_grid_ij[i, 1])]
    if ix == 0:
        ph_uw = np.nan  # wrapped phase values were zero
    else:
        ph_uw_pix = global_uu['ph_uw'][ix , :]
        if global_ph_in_is_real:
            ph_uw = ph_uw_pix + np.angle(np.exp(1j * (global_uw['ph_in'][i, :] - ph_uw_pix)))
        else:
            ph_uw = ph_uw_pix + np.angle(global_uw['ph_in'][i, :] * np.exp(-1j * ph_uw_pix))

    return i, ph_uw


def compute_ph_uw_block(bounds):
    """FIX: process a contiguous slice and return one array.

    Upstream mapped over every PS individually, so 6.3M small (i, row) tuples
    were pickled back to the parent. Returning blocks cuts that to a few dozen
    transfers and keeps the arithmetic vectorised.
    """
    lo, hi = bounds
    n_ifg = global_uw['ph_in'].shape[1]
    out = np.empty((hi - lo, n_ifg), dtype=np.float32)
    gi = global_grid_ij[lo:hi, 0].astype(np.intp)
    gj = global_grid_ij[lo:hi, 1].astype(np.intp)
    ixs = global_gridix[gi, gj]
    ph_in = global_uw['ph_in'][lo:hi, :]
    good = ixs != 0
    out[~good, :] = np.nan
    if np.any(good):
        pix = global_uu['ph_uw'][ixs[good], :]
        if global_ph_in_is_real:
            out[good, :] = pix + np.angle(np.exp(1j * (ph_in[good, :] - pix)))
        else:
            out[good, :] = pix + np.angle(ph_in[good, :] * np.exp(-1j * pix))
    return lo, hi, out

def uw_unwrap_from_grid():
    print('Unwrapping from grid...')

    uw = np.load('uw_grid.npy', allow_pickle=True).item()
    uu = np.load('uw_phaseuw.npy', allow_pickle=True).item()

    n_ps, n_ifg = uw['ph_in'].shape
    gridix = np.zeros(uw['nzix'].shape, dtype=int)
    gridix[uw['nzix']] = np.arange(0, uw['n_ps'])
    grid_ij = uw['grid_ij'] - 1
    ph_uw = np.zeros((n_ps, n_ifg), dtype=np.float32)

    # FIX: cap fork-based workers (PSI_MAX_WORKERS, default 8) - cpu_count()
    # on a 32-core box forked 32 copies of large arrays and OOM'd.
    import os as _os
    num_cores = multiprocessing.cpu_count()
    num_workers = max(1, min(int(_os.environ.get('PSI_MAX_WORKERS', 8)), num_cores))

    BLK = 20000
    bounds = [(lo, min(lo + BLK, n_ps)) for lo in range(0, n_ps, BLK)]
    print(f'  {n_ps:,} PS in {len(bounds)} blocks, {num_workers} workers')
    # FIX: passing uw/uu through initargs pickles a private ~4GB copy into every
    # worker (32GB at 8 workers, which blew the cgroup limit). Bind them as
    # parent globals first: fork then shares the pages copy-on-write, so memory
    # is flat in the worker count and far more workers fit.
    init_worker(uw, uu, gridix, grid_ij)
    with multiprocessing.get_context('fork').Pool(
        processes=num_workers
    ) as pool:
        done = 0
        for lo, hi, blk in pool.imap_unordered(compute_ph_uw_block, bounds):
            ph_uw[lo:hi, :] = blk
            done += 1
            if done % 25 == 0 or done == len(bounds):
                print(f'  unwrap-from-grid {done}/{len(bounds)} blocks', flush=True)

    msd = uu['msd']
    stamps_save('uw_unwrap_grid.npy', ph_uw=ph_uw, uu=uu)
    return ph_uw, msd