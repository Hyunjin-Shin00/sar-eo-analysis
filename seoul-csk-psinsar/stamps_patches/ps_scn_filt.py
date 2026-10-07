import numpy as np
import os
import pyamg


_SCN_SHARED = None


def _scn_lowpass_block(bounds):
    """Gaussian-weighted spatial low-pass over the KD-tree neighbourhood."""
    lo, hi = bounds
    pts, ph_hpt, tree, sigma_sq_times_2, patch_dist = _SCN_SHARED
    q = pts[lo:hi]
    nbrs = tree.query_ball_point(q, patch_dist, workers=1)
    out = np.zeros((hi - lo, ph_hpt.shape[1]), dtype=np.float32)
    for k, idx in enumerate(nbrs):
        idx = np.asarray(idx, dtype=np.intp)
        if idx.size == 0:
            continue
        d = pts[idx] - q[k]
        w = np.exp(-(d[:, 0] ** 2 + d[:, 1] ** 2) / sigma_sq_times_2)
        sw = w.sum()
        if sw <= 0:
            continue
        out[k, :] = (w / sw) @ ph_hpt[idx, :]
    return lo, hi, out

import multiprocessing
from scipy.sparse import csr_matrix, eye
from scipy.spatial import Delaunay
from psi_python.getparm import getparm
from psi_python.logit import logit


ml_global = None
A_T_global = None
dph_hpt_global = None

def init_worker(ml_, A_T_, dph_hpt_):
    global ml_global, A_T_global, dph_hpt_global
    ml_global = ml_
    A_T_global = A_T_
    dph_hpt_global = dph_hpt_

def solve_one(i):
    rhs = A_T_global @ dph_hpt_global[:, i]
    return i, ml_global.solve(rhs, tol=1e-6)


def ps_scn_filt():
        
    print("Estimating other spatially-correlated noise...")
    
    pix_size = getparm("unwrap_grid_size", 1)
    time_win = getparm("scn_time_win", 1)
    deramp_ifg = getparm("scn_deramp_ifg", 1)
    scn_wavelength = getparm("scn_wavelength", 1)
    drop_ifg_index = getparm("drop_ifg_index", 1)
    small_baseline_flag = getparm("small_baseline_flag", 1)
    
    psver = np.load("psver.npy", allow_pickle=True).item()
    ps = np.load(f"ps{psver}.npy", allow_pickle=True).item()
    uw = np.load(f"phuw{psver}.npy", allow_pickle=True).item()
    
    if small_baseline_flag == "y":
        unwrap_ifg_index = np.arange(ps["n_image"])
    else:
        unwrap_ifg_index = np.setdiff1d(np.arange(ps["n_ifg"]), drop_ifg_index)
    
    day = ps["day"][unwrap_ifg_index]
    master_ix = np.sum(ps["master_day"] > ps["day"]) + 1
    n_ifg = len(unwrap_ifg_index)
    n_ps = ps["n_ps"]
    
    ph_all = uw["ph_uw"][:, unwrap_ifg_index].astype(np.float32)
    
    sclaname = f"scla{psver}.npy"
    if os.path.exists(sclaname):
        scla = np.load(sclaname, allow_pickle=True).item()
        ph_all -= scla["ph_scla"][:, unwrap_ifg_index].astype(np.float32)
        ph_all -= np.tile(scla["C_ps_uw"][:, None], (1, len(unwrap_ifg_index)))
        if scla["ph_ramp"] is not None:
            ph_all -= scla["ph_ramp"][:, unwrap_ifg_index].astype(np.float32)
    
    ph_all[np.isnan(ph_all)] = 0
    print(f"   Number of points per ifg: {n_ps}")
    
    xy = ps["xy"]
    tri = Delaunay(xy[:, 1:3])
    edge_set = set()
    for simplex in tri.simplices:
        for i in range(3):
            for j in range(i + 1, 3):
                edge_set.add(tuple(sorted((simplex[i], simplex[j]))))
    edges_nz = np.array(list(edge_set))
    N = edges_nz.shape[0]
    
    if isinstance(deramp_ifg, str) and deramp_ifg == "all":
        deramp_ifg = np.arange(ps["n_ifg"])
    deramp_ifg = np.intersect1d(deramp_ifg, unwrap_ifg_index)
    deramp_ix = []
    ph_ramp = np.zeros((n_ps, len(deramp_ifg)))
    
    if len(deramp_ifg) > 0:
        print("   deramping selected ifgs...")
        G = np.vstack([np.ones(n_ps), xy[:, 1], xy[:, 2]]).T
        for i, idx in enumerate(deramp_ifg):
            i3 = np.where(unwrap_ifg_index == idx)[0][0]
            deramp_ix.append(i3)
            d = ph_all[:, i3]
            m, *_ = np.linalg.lstsq(G, d, rcond=None)
            ramp = G @ m
            ph_all[:, i3] -= ramp
            ph_ramp[:, i] = ramp
    
    deramp_ix = np.array(deramp_ix)
    dph = ph_all[edges_nz[:, 1], :] - ph_all[edges_nz[:, 0], :]
    dph_lpt = np.zeros_like(dph)
    n_edges = dph.shape[0]
    
    print("   low-pass filtering pixel-pairs in time...")
    #%
    for i1 in range(n_ifg):
        time_diff_sq = (day[i1].astype(int) - day.astype(int)) ** 2
        weight_factor = np.exp(-time_diff_sq / (2 * time_win ** 2))
        weight_factor[master_ix - 1] = 0
        weight_factor /= weight_factor.sum()
        dph_lpt[:, i1] = dph @ weight_factor
    
    dph_hpt = (dph - dph_lpt).astype(np.float32)
    A = csr_matrix((
        np.concatenate([-np.ones(n_edges), np.ones(n_edges)]),
        (np.concatenate([np.arange(n_edges), np.arange(n_edges)]),
         np.concatenate([edges_nz[:, 0], edges_nz[:, 1]]))
    ), shape=(n_edges, n_ps)).tocsc().astype(np.float32)
    ref_ix = 0
    mask = np.arange(n_ps) != ref_ix
    A = A[:, mask]
    
    print("   solving for high-frequency (in time) pixel phase...")
    
    ATA = A.T @ A
    ATA += 1e-6 * eye(ATA.shape[0], format='csr', dtype=np.float32)
    ml = pyamg.ruge_stuben_solver(ATA)
    # FIX: cap fork-based workers (PSI_MAX_WORKERS, default 8) - cpu_count()
    # on a 32-core box forked 32 copies of large arrays and OOM'd.
    import os as _os
    num_cores = multiprocessing.cpu_count()
    num_workers = max(1, min(int(_os.environ.get('PSI_MAX_WORKERS', 8)),
                             round(num_cores * 2 / 3)))
        
    with multiprocessing.Pool(processes=num_workers, initializer=init_worker, initargs=(ml, A.T, dph_hpt)) as pool:
        results = pool.map(solve_one, range(n_ifg))
    
    ph_hpt = np.zeros((n_ps - 1, n_ifg), dtype=np.float32)
    for i, result in results:
        ph_hpt[:, i] = result
    
    ph_hpt = np.insert(ph_hpt, ref_ix, 0, axis=0)

    if len(deramp_ix) > 0:
        ph_hpt[:, deramp_ix] += ph_ramp
    
    sigma_sq_times_2 = 2 * scn_wavelength ** 2
    ph_scn = np.full((n_ps, n_ifg), np.nan, dtype=np.float32)
    patch_dist = scn_wavelength * 4
    patch_dist_sq = patch_dist ** 2
    
    # FIX: the upstream loop measured the distance from every PS to ALL n_ps
    # points (6.3M x 6.3M = 4e13 distance evaluations, single threaded ->
    # measured 16.7 PS/s = 4.4 days). Only neighbours inside patch_dist matter,
    # so index them with a KD-tree and fan the blocks out over workers.
    print("   low-pass filtering in space...")
    import os as _os
    from scipy.spatial import cKDTree as _KDTree

    global _SCN_SHARED
    _pts = np.ascontiguousarray(xy[:, 1:3], dtype=np.float64)
    _tree = _KDTree(_pts)
    _SCN_SHARED = (_pts, ph_hpt, _tree, sigma_sq_times_2, patch_dist)

    _nw = max(1, min(int(_os.environ.get('PSI_MAX_WORKERS', 8)),
                     multiprocessing.cpu_count()))
    _BLK = 2000
    _bounds = [(lo, min(lo + _BLK, n_ps)) for lo in range(0, n_ps, _BLK)]
    print(f"   {n_ps:,} PS in {len(_bounds)} blocks, {_nw} workers", flush=True)
    _done = 0
    with multiprocessing.get_context('fork').Pool(processes=_nw) as _pool:
        for _lo, _hi, _blk in _pool.imap_unordered(_scn_lowpass_block, _bounds):
            ph_scn[_lo:_hi, :] = _blk
            _done += 1
            if _done % 200 == 0 or _done == len(_bounds):
                print(f"   spatial low-pass {_done}/{len(_bounds)} blocks", flush=True)
    _SCN_SHARED = None
    
    ph_scn -= ph_scn[0, :]
    ph_scn_slave = np.zeros_like(uw["ph_uw"], dtype=np.float32)
    ph_scn_slave[:, unwrap_ifg_index] = ph_scn
    ph_scn_slave[:, master_ix - 1] = 0
    
    np.save(f"scn{psver}", {"ph_scn_slave": ph_scn_slave, "ph_hpt": ph_hpt, "ph_ramp": ph_ramp})
    logit(1)
