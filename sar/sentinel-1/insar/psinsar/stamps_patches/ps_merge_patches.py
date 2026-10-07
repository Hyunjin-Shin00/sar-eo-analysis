import numpy as np
import os
import glob
from psi_python.logit import logit
from psi_python.stamps_save import stamps_save
from psi_python.getparm import getparm 
from psi_python.setparm import setparm 
from psi_python.llh2local import llh2local

def ps_merge_patches(psver=2):
    logit(0)
    print("Merging patches...")
    psver = 2
    small_baseline_flag = getparm('small_baseline_flag')
    grid_size = getparm('merge_resample_size', 1)
    merge_stdev = getparm('merge_standard_dev', 1)
    phase_accuracy = 10 * np.pi / 180  # gives minimum possible accuracy for a pixel
    min_weight = 1 / merge_stdev ** 2
    np.random.seed(1001)
    max_coh = abs(np.sum(np.exp(1j * np.random.randn(1000) * phase_accuracy))) / 1000
    
    psname = f'ps{psver}.npy'
    phname = f'ph{psver}.npy'
    rcname = f'rc{psver}.npy'
    pmname = f'pm{psver}.npy'
    phuwname = f'phuw{psver}.npy'
    sclaname = f'scla{psver}.npy'
    sclasbname = f'scla_sb{psver}.npy'
    scnname = f'scn{psver}.npy'
    bpname = f'bp{psver}.npy'
    laname = f'la{psver}.npy'
    incname = f'inc{psver}.npy'
    hgtname = f'hgt{psver}.npy'
    
    if os.path.exists('./patch.list'):
        dirname = []
        with open('patch.list', 'r') as f:
            for line in f:
                dirname.append(line.strip())
    else:
        dirname = glob.glob('PATCH_*')
        
        
    ps = np.load(f'{dirname[0]}/{psname}', allow_pickle=True).item()
    n_ifg = ps['n_ifg'] ####should be change
    n_patch = len(dirname)
    remove_ix = np.array([], dtype=bool)
    ij = np.empty((0, 2))
    lonlat = np.empty((0, 2))
    ph = np.empty((0, n_ifg))
    ph_rc = np.empty((0, n_ifg))
    ph_reref = np.empty((0, n_ifg))
    ph_uw = np.empty((0, n_ifg))
    ph_patch = np.empty((0, n_ifg-1))
    ph_res = np.empty((0, n_ifg-1))
    ph_scla = np.empty((0, 0), dtype=np.single)
    ph_scla_sb = np.empty((0, 0), dtype=np.single)
    ph_scn_master = np.empty((0, 0))
    ph_scn_slave = np.empty((0, 0))
    K_ps = np.empty((0))
    C_ps = np.empty((0))
    coh_ps = np.empty((0))
    K_ps_uw = np.empty((0, 0), dtype=np.single)
    K_ps_uw_sb = np.empty((0, 0), dtype=np.single)
    C_ps_uw = np.empty((0, 0), dtype=np.single)
    C_ps_uw_sb = np.empty((0, 0), dtype=np.single)
    bperp_mat = np.empty((0, n_ifg-1), dtype=np.single)
    la = np.empty((0))
    inc = np.empty((0))
    hgt = np.empty((0))
    amp = np.empty((0, 0), dtype=np.single)
    
    for i in range(n_patch):
        if dirname[i]:
            print(f"   Processing {dirname[i]}")
            os.chdir(dirname[i])
            ps = np.load(psname, allow_pickle=True).item()
            n_ifg = ps['n_ifg']
            if 'n_image' in ps:
                n_image = ps['n_image']
            else:
                n_image = ps['n_ifg']
    
            patch_ij = np.loadtxt('patch_noover.in')
    
            ix = (ps['ij'][:, 1] >= patch_ij[2] - 1) & (ps['ij'][:, 1] <= patch_ij[3] - 1) & (ps['ij'][:, 2] >= patch_ij[0] - 1) & (ps['ij'][:, 2] <= patch_ij[1] - 1)
    
            if np.sum(ix) == 0:
                ix_no_ps = 1  # no PS left after removing overlapping patches
            else:
                ix_no_ps = 0
    
            if grid_size == 0:
                psij = ps['ij'][:, 1: ]
                structured_array1 = np.array(list(map(tuple, psij)), dtype=[('f0', int), ('f1', int)])
    
                # FIX 1: `if not ij[:, 0]` raises ValueError as soon as the
                # accumulator holds more than one row (i.e. from the 2nd patch on).
                # FIX 2: ij_target was only bound in the empty branch, so the
                # non-empty path hit NameError below. It is meant to be `ij`.
                if ij.size == 0:
                    ij_target = np.empty((0, 2))
                    structured_array2 = np.array([], dtype=[('f0', int), ('f1', int)])
                else:
                    ij_target = ij
                    structured_array2 = np.array(list(map(tuple, ij)), dtype=[('f0', int), ('f1', int)])

                intersecting_elements_mask = np.in1d(structured_array1, structured_array2)
                intersecting_elements = structured_array1[intersecting_elements_mask]
                C = np.array(intersecting_elements.tolist(), dtype=int)
                IA = np.argwhere(intersecting_elements_mask).flatten()
                # FIX 3: the original scanned all of ij_target for every element of
                # C (O(|C|x|ij|)); with millions of PS that never finishes. Same
                # result via a sorted-key lookup.
                if C.size == 0:
                    IB = np.array([], dtype=int)
                else:
                    _SH = np.int64(1) << np.int64(32)
                    _tk = ij_target[:, 0].astype(np.int64) * _SH + ij_target[:, 1].astype(np.int64)
                    _ck = C[:, 0].astype(np.int64) * _SH + C[:, 1].astype(np.int64)
                    _ord = np.argsort(_tk, kind='stable')
                    _pos = np.searchsorted(_tk[_ord], _ck)
                    IB = _ord[_pos]
                remove_ix = np.hstack([remove_ix, IB])  # now more reliable values for these pixels
                ix_ex = np.ones(ps['n_ps'], dtype=bool)
                ix_ex[IA] = False  # exclusive index (non-intersecting)
                ix[ix_ex] = True  # keep those in patch proper + those outside not already kept
            elif grid_size != 0 and ix_no_ps != 1:
                g_ij = np.zeros_like(ps['xy'][ix, :])
                xy_min = np.min(ps['xy'][ix, :], axis=0)
                g_ij[:, 0] = np.ceil((ps['xy'][ix, 2] - xy_min[2] + 1e-9) / grid_size)
                g_ij[:, 1] = np.ceil((ps['xy'][ix, 1] - xy_min[1] + 1e-9) / grid_size)
                n_i = np.max(g_ij[:, 0])
                n_j = np.max(g_ij[:, 1])
                g_ij, I, g_ix = np.unique(g_ij, axis=0, return_index=True, return_inverse=True)
                g_ix_sorted = np.sort(g_ix)
                ix = np.where(ix)[0][g_ix_sorted]
                pm = np.load(pmname, allow_pickle=True).item()
    
                pm_ph_res = np.angle(np.exp(1j * (pm['ph_res'] - np.tile(pm['C_ps'][:, np.newaxis], (1, pm['ph_res'].shape[1])))))  # centralise about zero
                if small_baseline_flag != 'y':
                    pm_ph_res = np.hstack([pm_ph_res, pm['C_ps'][:, np.newaxis]])  # include master noise too
    
                sigsq_noise = np.var(pm_ph_res, axis=1, ddof=0)
                coh_ps_all = np.abs(np.sum(np.exp(1j * pm_ph_res), axis=1)) / n_ifg
                coh_ps_all[coh_ps_all > max_coh] = max_coh  # prevent unrealistic weights
                sigsq_noise[sigsq_noise < phase_accuracy**2] = phase_accuracy**2  # prevent unrealistic weights
                ps_weight = 1 / sigsq_noise[ix]
                ps_snr = 1 / (1 / coh_ps_all[ix]**2 - 1)
                del pm
    
    
                l_ix = np.hstack([np.where(np.diff(g_ix) != 0)[0], g_ix.size - 1])
                f_ix = np.hstack([0, np.diff(l_ix)[:-1] + 1])
                n_ps_g = f_ix.size
                weightsave = np.zeros(n_ps_g)
                for i in range(n_ps_g):
                    weights = ps_weight[f_ix[i]:l_ix[i] + 1]
                    weightsum = np.sum(weights)
                    weightsave[i] = weightsum
                    if weightsave[i] < min_weight:
                        ix[f_ix[i]:l_ix[i] + 1] = 0
    
                g_ix = g_ix[ix > 0]
    
                if len(g_ix) == 0:
                    ix_no_ps = 1  # Remaining PS are rejected because sum of weights is smaller than threshold min_weight
    
                l_ix = np.concatenate([np.where(np.diff(g_ix))[0], [g_ix.size-1]])
                f_ix = np.concatenate([[0], l_ix[:-1]+1])
                ps_weight = ps_weight[ix > 0]
                ps_snr = ps_snr[ix > 0]
                ix = ix[ix > 0]
                n_ps_g = f_ix.size
                n_ps = ix.size
                
            if grid_size == 0:
                ij = np.concatenate([ij, ps['ij'][ix, 1:3]])
                lonlat = np.concatenate([lonlat, ps['lonlat'][ix, :]])
            elif grid_size != 0 and ix_no_ps != 1:
                ij_g = np.zeros((n_ps_g, 2))
                lonlat_g = np.zeros((n_ps_g, 2))
                ps_ij = ps.ij[ix, :]
                ps_lonlat = ps.lonlat[ix, :]
                for i in range(n_ps_g):
                    weights = np.tile(ps_weight[f_ix[i]:l_ix[i]], (2, 1)).T
                    ij_g[i,:] = np.round(np.sum(ps_ij[f_ix[i]:l_ix[i], 1:2] * weights, axis=0) / np.sum(weights[:, 0]))
                    lonlat_g[i,:] = np.sum(ps_lonlat[f_ix[i]:l_ix[i], :] * weights, axis=0) / np.sum(weights[:, 0])
                ij = np.concatenate([ij, ij_g])
                lonlat = np.concatenate([lonlat, lonlat_g])
    
            if os.path.isfile(f'./{phname}'):
                phin = np.load(f'{phname}', allow_pickle=True).item()
                ph_w = phin['ph']
                phin.clear()
            elif hasattr(ps, 'ph'):
                ph_w = ps.ph
    
            if 'ph_w' in locals():
                if grid_size == 0:
                    ph = np.concatenate([ph, ph_w[ix, :]])
                elif grid_size != 0 and ix_no_ps != 1:
                    ph_w = ph_w[ix, :]
                    ph_g = np.zeros((n_ps_g, n_ifg))
                    for i in range(n_ps_g):
                        weights = np.tile(ps_snr[f_ix[i]:l_ix[i]], (n_ifg, 1)).T
                        ph_g[i,:] = np.sum(ph_w[f_ix[i]:l_ix[i], :] * weights, axis=0)
                    ph = np.concatenate([ph, ph_g])
                    ph_g.clear()
                del ph_w
    
            rc = np.load(rcname, allow_pickle=True).item()
            rc_ph_rc = rc['ph_rc']
            if grid_size == 0:
                ph_rc = np.concatenate([ph_rc, rc_ph_rc[ix, :]])
                if small_baseline_flag.lower() != 'y':
    
                    ph_reref = np.concatenate([ph_reref, rc['ph_reref'][ix, :]])
            elif grid_size != 0 and ix_no_ps != 1:
                rc_ph_rc = rc_ph_rc[ix, :]
                ph_g = np.zeros((n_ps_g, ps['n_ifg']))
                if small_baseline_flag.lower() != 'y':
                    rc_ph_reref = rc['ph_reref'][ix, :]
                    ph_reref_g = np.zeros((n_ps_g, ps['n_ifg']))
                for i in range(n_ps_g):
                    weights = np.tile(ps_snr[f_ix[i]:l_ix[i]], (ps['n_ifg'], 1)).T
                    ph_g[i,:] = np.sum(rc_ph_rc[f_ix[i]:l_ix[i], :] * weights, axis=0)
                    if small_baseline_flag.lower() != 'y':
                        ph_reref_g[i,:] = np.sum(rc_ph_reref[f_ix[i]:l_ix[i], :] * weights, axis=0)
                ph_rc = np.concatenate([ps['ph_rc'], ph_g])
                del ph_g
    
                if small_baseline_flag.lower() != 'y':
                    ph_reref = np.concatenate([ps['ph_reref'], ph_reref_g])
                    del ph_reref_g
    
            # Load data from npy file
            pm = np.load(pmname, allow_pickle=True).item()
    
            if grid_size == 0:
                ph_patch = np.concatenate([ph_patch, pm['ph_patch'][ix, :]])
                if 'ph_res' in pm:
                    ph_res = np.concatenate([ph_res, pm['ph_res'][ix, :]])
                if 'K_ps' in pm:
                    K_ps = np.concatenate([K_ps, pm['K_ps'][ix]])
                if 'C_ps' in pm:
                    C_ps = np.concatenate([C_ps, pm['C_ps'][ix]])
                if 'coh_ps' in pm:
                    coh_ps = np.concatenate([coh_ps, pm['coh_ps'][ix]])
            elif grid_size != 0 and ix_no_ps != 1:
                pm_ph_patch = pm['ph_patch'][ix, :]
                ph_g = np.zeros((n_ps_g, pm_ph_patch.shape[1]))
                if 'ph_res' in pm:
                    pm_ph_res = pm['ph_res'][ix, :]
                    ph_res_g = ph_g
                if 'K_ps' in pm:
                    pm_K_ps = pm['K_ps'][ix, :]
                    K_ps_g = np.zeros((n_ps_g, 1))
                if 'C_ps' in pm:
                    pm_C_ps = pm['C_ps'][ix, :]
                    C_ps_g = np.zeros((n_ps_g, 1))
                if 'coh_ps' in pm:
                    pm_coh_ps = pm['coh_ps'][ix, :]
                    coh_ps_g = np.zeros((n_ps_g, 1))
                for i in range(n_ps_g):
                    weights = np.tile(ps_snr[f_ix[i]:l_ix[i]], (pm_ph_patch.shape[1], 1)).T
                    ph_g[i,:] = np.sum(pm_ph_patch[f_ix[i]:l_ix[i], :] * weights, axis=0)
                    if 'ph_res' in pm:
                        ph_res_g[i,:] = np.sum(pm_ph_res[f_ix[i]:l_ix[i], :] * weights, axis=0)
                    if 'coh_ps' in pm:
                        snr = np.sqrt(np.sum(weights[:, 0]**2, axis=0))
                        coh_ps_g[i] = np.sqrt(1./(1+1./snr))
                    weights = ps_weight[f_ix[i]:l_ix[i]]
                    if 'K_ps' in pm:
                        K_ps_g[i] = np.sum(pm_K_ps[f_ix[i]:l_ix[i], :] * weights, axis=0) / np.sum(weights, axis=0)
                    if 'C_ps' in pm:
                        C_ps_g[i] = np.sum(pm_C_ps[f_ix[i]:l_ix[i], :] * weights, axis=0) / np.sum(weights, axis=0)
                # if sum(sum(np.isnan(C_ps_g)))>0 or sum(sum(np.isnan(weights)))>0 or sum(sum(np.isnan(ph_g)))>0 or sum(sum(np.isnan(K_ps_g)))>0 or sum(sum(np.isnan(coh_ps_g)))>0 or sum(sum(np.isnan(snr)))>0:
                #     keyboard()
                #     sys.exit(1)
    
                ph_patch = np.concatenate((ph_patch, ph_g))
                del ph_g
    
                if 'ph_res' in pm:
                    ph_res_g = pm['ph_res']
                    ph_res = np.concatenate((ph_res, ph_res_g))
                    del ph_res_g
    
                if 'K_ps' in pm:
                    K_ps_g = pm['K_ps'][ix]
                    K_ps = np.concatenate((K_ps, K_ps_g))
                    del K_ps_g
    
                if 'C_ps' in pm:
                    C_ps_g = pm['C_ps'][ix]
                    C_ps = np.concatenate((C_ps, C_ps_g))
                    del C_ps_g
    
                if 'coh_ps' in pm:
                    coh_ps_g = pm['coh_ps'][ix]
                    coh_ps = np.concatenate((coh_ps, coh_ps_g))
                    del coh_ps_g
    
            del pm
    
            bp = np.load(bpname, allow_pickle=True).item()  # load bpname npy file and convert to dictionary
    
            if grid_size == 0:
                bperp_mat = np.concatenate((bperp_mat, bp['bperp_mat'][ix, :]))
            elif grid_size != 0 and ix_no_ps != 1:
                bperp_g = np.zeros((n_ps_g, bp['bperp_mat'].shape[1]))
                bp['bperp_mat'] = bp['bperp_mat'][ix, :]
                for i in range(n_ps_g):
                    weights = np.tile(ps_weight[f_ix[i]:l_ix[i]], (1, bperp_g.shape[1]))
                    weights[weights == 0] = 1e-9  # pixels with zero phase cause this problem
                    bperp_g[i, :] = np.sum(bp['bperp_mat'][f_ix[i]:l_ix[i], :] * weights, axis=0) / np.sum(weights[:, 0])
                bperp_mat = np.concatenate((bperp_mat, bperp_g))
                del bperp_g
    
            del bp
            # [TODO]
            if os.path.exists(f'./{laname}.npy'):
                lain = np.load(f'{laname}', allow_pickle=True).item()
                if grid_size == 0:
                    la = np.concatenate((la, lain['la'][ix]))
                elif grid_size != 0 and ix_no_ps != 1:
                    la_g = np.zeros((n_ps_g, 1))
                    lain['la'] = lain['la'][ix, :]
                    for i in range(n_ps_g):
                        weights = ps_weight[f_ix[i]:l_ix[i]]
                        la_g[i] = np.sum(lain['la'][f_ix[i]:l_ix[i]] * weights) / np.sum(weights[:, 0])
                    la = np.concatenate((la, la_g))
                    del la_g
                del lain
    
            if os.path.exists(f'./{incname}'):
                incin = np.load(f'{incname}', allow_pickle=True).item()
                if grid_size == 0:
                    inc = np.concatenate((inc, incin['inc'][ix].flatten()))
                elif grid_size != 0 and ix_no_ps != 1:
                    inc_g = np.zeros((n_ps_g, 1))
                    incin['inc'] = incin['inc'][ix]
                    for i in range(n_ps_g):
                        weights = ps_weight[f_ix[i]:l_ix[i]]
                        inc_g[i] = np.sum(incin['inc'][f_ix[i]:l_ix[i]] * weights) / np.sum(weights[:, 0])
                    inc = np.concatenate((inc, inc_g))
                    del inc_g
                del incin
            
            if os.path.exists(f'./{hgtname}'):
                hgtin = np.load(f'{hgtname}', allow_pickle=True).item()
                if grid_size == 0:
                    hgt = np.concatenate((hgt, hgtin['hgt'][ix].flatten()))
                elif grid_size != 0 and ix_no_ps != 1:
                    hgt_g = np.zeros((n_ps_g, 1))
                    hgtin['hgt'] = hgtin['hgt'][ix, :]
                    for i in range(n_ps_g):
                        weights = ps_weight[f_ix[i]:l_ix[i]]
                        hgt_g[i] = np.sum(hgtin['hgt'][f_ix[i]:l_ix[i]] * weights) / np.sum(weights[:, 0])
                    hgt = np.concatenate((hgt, hgt_g))
                    del hgt_g
                del hgtin
    
            #[TODO] disabled for development. 
            if grid_size==100:
    
            # if grid_size==0:
                if os.path.exists(f'./{phuwname}'):
                    phuw = np.load(f'{phuwname}', allow_pickle=True).item()
                    if C.any():
                        ph_uw_diff = np.mean(phuw['ph_uw'][IA, :] - phuw['ph_uw'][IB, :], axis=0)
                        if small_baseline_flag.lower() != 'y':
                            ph_uw_diff = np.round(ph_uw_diff / (2 * np.pi)) * (2 * np.pi)  # round to nearest 2 pi
                    else:
                        ph_uw_diff = np.zeros((1, phuw['ph_uw'].shape[1]))
                    ph_uw = np.concatenate((ph_uw, phuw['ph_uw'][ix, :] - np.tile(ph_uw_diff, (np.sum(ix), 1))))
                    del phuw
                else:
                    ph_uw = np.concatenate((ph_uw, np.zeros((sum(ix), n_image), dtype=np.float32)))
    
                if os.path.exists(f'./{sclaname}'):
                    scla = np.load(f'{sclaname}', allow_pickle=True).item()
                    if C.any():
                        ph_scla_diff = np.mean(scla['ph_scla'][IA, :] - ph_scla[IB, :], axis=0)
                        K_ps_diff = np.mean(scla['K_ps_uw'][IA, :] - K_ps_uw[IB, :], axis=0)
                        C_ps_diff = np.mean(scla['C_ps_uw'][IA, :] - C_ps_uw[IB, :], axis=0)
                    else:
                        ph_scla_diff = np.zeros((1, scla['ph_scla'].shape[1]))
                        K_ps_diff = 0
                        C_ps_diff = 0
                    ph_scla = np.concatenate((ph_scla, scla['ph_scla'][ix, :] - np.tile(ph_scla_diff, (sum(ix), 1))))
                    K_ps_uw = np.concatenate((K_ps_uw, scla['K_ps_uw'][ix, :] - np.tile(K_ps_diff, (sum(ix), 1))))
                    C_ps_uw = np.concatenate((C_ps_uw, scla['C_ps_uw'][ix, :] - np.tile(C_ps_diff, (sum(ix), 1))))
                    del scla
    
                if small_baseline_flag.lower() == 'y':
                    if os.path.exists(f'./{sclasbname}'):
                        sclasb = np.load(f'{sclasbname}', allow_pickle=True).item()
                        ph_scla_diff = np.mean(sclasb['ph_scla'][IA, :] - ph_scla_sb[IB, :], axis=0)
                        K_ps_diff = np.mean(sclasb['K_ps_uw'][IA, :] - K_ps_uw_sb[IB, :], axis=0)
                        C_ps_diff = np.mean(sclasb['C_ps_uw'][IA, :] - C_ps_uw_sb[IB, :], axis=0)
                        ph_scla_sb = np.concatenate((ph_scla_sb, sclasb['ph_scla'][ix, :] - np.tile(ph_scla_diff, (sum(ix), 1))))
                        K_ps_uw_sb = np.concatenate((K_ps_uw_sb, sclasb['K_ps_uw'][ix, :] - np.tile(K_ps_diff, (sum(ix), 1))))
                        C_ps_uw_sb = np.concatenate((C_ps_uw_sb, sclasb['C_ps_uw'][ix, :] - np.tile(C_ps_diff, (sum(ix), 1))))
                        del sclasb
    
                if os.path.exists(f'./{scnname}'):
                    scn = np.load(f'{scnname}', allow_pickle=True).item()
                    if C.any():
                        ph_scn_diff = np.mean(scn['ph_scn_slave'][IA, :] - ph_scn_slave[IB, :], axis=0)
                    else:
                        ph_scn_diff = np.zeros((1, scn['ph_scn_slave'].shape[1]))
                    ph_scn_slave = np.concatenate((ph_scn_slave, scn['ph_scn_slave'][ix, :] - np.tile(ph_scn_diff, (sum(ix), 1))))
                    del scn
            os.chdir('../')
            
    tempdir = os.getcwd()
    logit(f'save merged files in {tempdir}')
    ps_new = ps.copy()
    n_ps_orig = ij.shape[0] # before duplicates removed
    keep_ix = np.ones((n_ps_orig,), dtype=bool)
    # FIX: remove_ix accumulates integer row indices (from IB), so casting it to
    # bool turned indices into a mask of the wrong length (and treated index 0 as
    # "keep"). Index with integers instead.
    remove_ix = np.unique(np.asarray(remove_ix, dtype=np.int64)) if np.size(remove_ix) else np.array([], dtype=np.int64)
    if remove_ix.size:
        keep_ix[remove_ix] = False
    lonlat_save = lonlat.copy()
    coh_ps_weed = coh_ps[keep_ix]
    lonlat = lonlat[keep_ix, :]
    
    # Some non-adjacent pixels are allocated the same lon/lat by DORIS. If duplicates occur, 
    # the pixel with the highest coherence is kept.
    [dummy, I] = np.unique(lonlat, axis=0, return_index=True)
    dups = np.setxor1d(I, np.arange(lonlat.shape[0])) # pixels with duplicate lon/lat
    keep_ix_num = np.where(keep_ix)[0]
    
    for i in range(len(dups)):
        dups_ix_weed = np.where(np.logical_and(lonlat[:, 0] == lonlat[dups[i], 0], 
                                            lonlat[:, 1] == lonlat[dups[i], 1]))[0]
        dups_ix = keep_ix_num[dups_ix_weed]
        I = np.argmax(coh_ps_weed[dups_ix_weed])
        keep_ix[dups_ix[dups_ix != dups_ix[I]]] = False # drop dups with lowest coh
    
    if len(dups) != 0:
        lonlat = lonlat_save[keep_ix, :]
        print(f'   {len(dups)} pixel with duplicate lon/lat dropped\n\n')
        
    lonlat_save = None
    
    ll0 = (np.max(lonlat, axis=0) + np.min(lonlat, axis=0)) / 2
    xy = llh2local(lonlat, ll0) * 1000
    sort_x = xy[xy[:, 0].argsort(), :]
    sort_y = xy[xy[:, 1].argsort(), :]
    n_pc = int(round(xy.shape[0] * 0.001))
    
    bl = np.mean(sort_x[:n_pc, :], axis=0) # bottom left corner
    tr = np.mean(sort_x[-n_pc - 1:, :], axis=0) # top right corner
    br = np.mean(sort_y[:n_pc, :], axis=0) # bottom right corner
    tl = np.mean(sort_y[-n_pc - 1:, :], axis=0) # top left corner
    
    heading = getparm('heading')
    if heading == '':
        heading = 0
    theta = (180 - float(heading)) * np.pi / 180
    if theta > np.pi:
        theta = theta - 2 * np.pi
    rotm = np.array([[np.cos(theta), np.sin(theta)], [-np.sin(theta), np.cos(theta)]])
    xy = xy.T
    xynew = np.dot (rotm, xy) # rotate so that scene axes approx align with x=0 and y=0
    if np.max(xynew[0, :]) - np.min(xynew[0, :]) < np.max(xy[0, :]) - np.min(xy[0, :]) and \
    np.max(xynew[1, :]) - np.min(xynew[1, :]) < np.max(xy[1, :]) - np.min(xy[1, :]):
        xy = xynew # check that rotation is an improvement
        print(f'   Rotating xy by {theta * 180 / np.pi} degrees')
    xynew = None
    
    xy = xy.T.astype(np.float32)
    #xy[weightsave < min_weight, :] = 1e9
    sort_ix = np.argsort(xy[:, [1, 0]], axis=0)[:, 0] # sort in ascending y order
    xy = xy[sort_ix, :]
    xy = np.concatenate([np.arange(1, xy.shape[0] + 1)[:, np.newaxis], xy], axis=1)
    xy[:, 1:3] = np.round(xy[:, 1:3] * 1000) / 1000 # round to mm
    lonlat = lonlat[sort_ix, :]
    
    all_ix = np.arange(ij.shape[0])
    keep_ix = all_ix[keep_ix]
    sort_ix = keep_ix[sort_ix]
    
    n_ps = sort_ix.shape[0]
    print(f'   Writing merged dataset (contains {n_ps} pixels)\n')
    ij = ij[sort_ix, :]
    
    ph_rc = ph_rc[sort_ix, :]
    # FIX(memory): ph_rc[ph_rc!=0] /= np.abs(ph_rc[ph_rc!=0]) makes three or four
    # full copies of an n_ps x n_ifg complex128 array at once. Normalise in row
    # blocks, in place.
    _BLK = 100000
    for _lo in range(0, ph_rc.shape[0], _BLK):
        _b = ph_rc[_lo:min(_lo + _BLK, ph_rc.shape[0]), :]   # view
        _m = _b != 0
        _b[_m] /= np.abs(_b[_m])
    if small_baseline_flag.lower() != 'y':
        ph_reref = ph_reref[sort_ix, :]
    
    stamps_save(rcname, ph_rc=ph_rc, ph_reref=ph_reref)
    del ph_rc, ph_reref
    
    if ph_uw.shape[0] == n_ps_orig:
        ph_uw = ph_uw[sort_ix, :]
        stamps_save(phuwname, ph_uw=ph_uw)
    del ph_uw
    
    ph_patch = ph_patch[sort_ix, :]
    if ph_res.shape[0] == n_ps_orig:
        ph_res = ph_res[sort_ix, :]
    else:
        ph_res = np.array([])
    
    if K_ps.shape[0] == n_ps_orig:
        K_ps = K_ps[sort_ix]
    else:
        K_ps = np.array([])
    
    if C_ps.shape[0] == n_ps_orig:
        C_ps = C_ps[sort_ix]
    else:
        C_ps = np.array([])
    
    if coh_ps.shape[0] == n_ps_orig:
        coh_ps = coh_ps[sort_ix]
    else:
        coh_ps = np.array([])
    stamps_save(pmname, ph_patch=ph_patch, ph_res=ph_res, K_ps=K_ps, C_ps=C_ps, coh_ps=coh_ps)
    
    del ph_patch, ph_res, K_ps, C_ps, coh_ps
    
    if ph_scla.shape[0] == n_ps:
        ph_scla = ph_scla[sort_ix, :]
        K_ps_uw = K_ps_uw[sort_ix, :]
        C_ps_uw = C_ps_uw[sort_ix, :]
        stamps_save(sclaname, ph_scla=ph_scla, K_ps_uw=K_ps_uw, C_ps_uw=C_ps_uw)
    
    # clear memory by deleting numpy arrays
    del ph_scla, K_ps_uw, C_ps_uw
    
    if small_baseline_flag.lower() == 'y' and ph_scla_sb.shape[0] == n_ps:
        ph_scla = ph_scla_sb[sort_ix, :]
        K_ps_uw = K_ps_uw_sb[sort_ix, :]
        C_ps_uw = C_ps_uw_sb[sort_ix, :]
        stamps_save(sclasbname, ph_scla=ph_scla, K_ps_uw=K_ps_uw, C_ps_uw=C_ps_uw)
        del ph_scla, K_ps_uw, C_ps_uw 
    del ph_scla_sb, K_ps_uw_sb, C_ps_uw_sb
    
    if ph_scn_slave.shape[0] == n_ps:
        ph_scn_slave = ph_scn_slave[sort_ix, :]
        stamps_save(scnname, ph_scn_slave=ph_scn_slave)
    del ph_scn_slave
    
    if ph.shape[0] == n_ps_orig:
        ph = ph[sort_ix, :]
    else:
        ph = np.array([])
    stamps_save(phname, ph=ph)
    del ph
    
    if la.shape[0] == n_ps_orig:
        la = la[sort_ix, :]
    else:
        la = np.array([])
    stamps_save(laname, la=la)
    del la
    
    if inc.shape[0] == n_ps_orig:
        inc = inc[sort_ix]
    else:
        inc = np.array([])
    stamps_save(incname, inc=inc)
    
    if hgt.shape[0] == n_ps_orig:
        hgt = hgt[sort_ix]
    else:
        hgt = np.array([])
    stamps_save(hgtname, hgt=hgt)
    
    bperp_mat = bperp_mat[sort_ix, :]
    stamps_save(bpname, bperp_mat=bperp_mat)
    
    ps_new['n_ps'] = n_ps
    ps_new['ij'] = np.hstack((np.arange(1, n_ps+1)[:, np.newaxis], ij))
    ps_new['xy'] = xy 
    ps_new['lonlat'] = lonlat
    # print(ps_new)
    np.save(psname, ps_new)
    
    np.save('psver.npy', psver)