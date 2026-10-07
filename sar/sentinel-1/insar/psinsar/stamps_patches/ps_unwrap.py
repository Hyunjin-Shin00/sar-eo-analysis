import os
import numpy as np

from psi_python.logit import logit
from psi_python.getparm import getparm 
from psi_python.load_isce import load_psi_npy
from psi_python.uw_3d import uw_3d

def ps_unwrap():
    logit(0)
    print('Phase-unwrapping...')
    small_baseline_flag = getparm('small_baseline_flag', 1)
    unwrap_patch_phase = getparm('unwrap_patch_phase', 1)
    scla_deramp = getparm('scla_deramp', 1)
    subtr_tropo = getparm('subtr_tropo', 1)
    aps_name = getparm('tropo_method', 1)

    psver = np.load('psver.npy')
    psname = f'ps{psver}.npy'
    rcname = f'rc{psver}.npy'
    pmname = f'pm{psver}.npy'
    bpname = f'bp{psver}.npy'
    incname = f'inc{psver}.npy'
    goodname = f'phuw_good{psver}.npy'

    if small_baseline_flag.lower() != 'y':
        sclaname = f'scla_smooth{psver}.npy'
        apsname = f'tca{psver}.npy'
        phuwname = f'phuw{psver}.npy'
    else:
        sclaname = f'scla_smooth_sb{psver}.npy'
        apsname = f'tca_sb{psver}.npy'
        phuwname = f'phuw_sb{psver}.npy'

    ps = np.load(psname, allow_pickle=True).item()
    drop_ifg_index = getparm('drop_ifg_index', 1)
    unwrap_ifg_index = np.setdiff1d(np.arange(ps['n_ifg']), drop_ifg_index)

    if os.path.isfile(f'./{bpname}'): #, f'./{bpname}'], dtype='U') == True):
        bp = np.load(bpname, allow_pickle=True).item()
    else:
        bperp = ps['bperp']
        if small_baseline_flag.lower() != 'y':
            bperp = np.hstack((bperp[:ps['master_ix']], 0, bperp[ps['master_ix']:]))
            # print(bperp, 'bperp')
        bp['bperp_mat'] = np.tile(bperp, (ps['n_ps'], 1)).astype('float32')
    
    if small_baseline_flag.lower() != 'y':
        bperp_mat = np.hstack((bp['bperp_mat'][:, :ps['master_ix']], 
                               np.zeros((ps['n_ps'], 1), dtype='float32'),
                               bp['bperp_mat'][:, ps['master_ix']:]))
    
    else:
        bperp_mat = bp['bperp_mat']
    
    if unwrap_patch_phase.lower() == 'y':
        pm = np.load(pmname, allow_pickle=True)
        ph_w = pm['ph_patch'] / np.abs(pm['ph_patch'])
        del pm
        if small_baseline_flag.lower() != 'y':
            ph_w = np.concatenate((ph_w[:, :ps['master_ix']], 
                                np.ones((ps['n_ps'], 1), dtype=np.float32), 
                                ph_w[:, ps['master_ix']:]), axis=1)
    else:
        rc = np.load(rcname, allow_pickle=True).item()
        ph_w = rc['ph_rc']
        del rc
        if os.path.isfile(f'./{pmname}'):
            pm = np.load(f'{pmname}', allow_pickle=True).item()
    
            if 'K_ps' in pm:
                if pm['K_ps'] is not None:
                    # FIX(memory): the one-shot expression built np.tile + the
                    # product + 1j* + np.exp + the final multiply, i.e. four or
                    # five 3GB complex128 temporaries live at once (n_ps=6.3M).
                    # Apply it in row blocks, in place.
                    _K = np.reshape(np.asarray(pm['K_ps']), (-1, 1))
                    _BLK = 200000
                    for _lo in range(0, ph_w.shape[0], _BLK):
                        _hi = min(_lo + _BLK, ph_w.shape[0])
                        ph_w[_lo:_hi, :] *= np.exp(
                            1j * (_K[_lo:_hi, :] * bperp_mat[_lo:_hi, :]))
                    del _K
            del pm

    # FIX(memory): boolean fancy-indexing copied ~200M complex128 elements three
    # times over (extract, abs, divide). Normalise block-wise in place instead.
    _BLK = 200000
    for _lo in range(0, ph_w.shape[0], _BLK):
        _hi = min(_lo + _BLK, ph_w.shape[0])
        _blk = ph_w[_lo:_hi, :]          # view
        _m = _blk != 0
        _blk[_m] /= np.abs(_blk[_m])     # normalize, avoids high freq artifacts in adaptive filtering

    scla_subtracted_sw = 0
    ramp_subtracted_sw = 0

    options = {'master_day': ps['master_day']}
    unwrap_hold_good_values = getparm('unwrap_hold_good_values', 1)
    if small_baseline_flag.lower() != 'y' or not os.path.isfile(phuwname):
        unwrap_hold_good_values = 'n'
        logit('Code to hold good values skipped')

    if unwrap_hold_good_values.lower() == 'y':
        sb_identify_good_pixels
        options['ph_uw_predef'] = np.full(ph_w.shape, np.nan, dtype=np.float32)
        uw = np.load(phuwname, allow_pickle=True).item()
        good = np.load(goodname, allow_pickle=True).item()
        if ps.n_ps == good['good_pixels'].shape[0] and ps.n_ps == uw['ph_uw'].shape[0]:
            options['ph_uw_predef'][good['good_pixels']] = uw['ph_uw'][good['good_pixels']]
        else:
            print('   wrong number of PS in keep good pixels - skipped...')
        del uw, good

    options['time_win'] = getparm('unwrap_time_win', 1)
    options['unwrap_method'] = getparm('unwrap_method', 1)
    options['grid_size'] = getparm('unwrap_grid_size', 1)
    options['prefilt_win'] = getparm('unwrap_gold_n_win', 1)
    options['goldfilt_flag'] = getparm('unwrap_prefilter_flag', 1)
    options['gold_alpha'] = getparm('unwrap_gold_alpha', 1)
    options['la_flag'] = getparm('unwrap_la_error_flag', 1)
    options['scf_flag'] = getparm('unwrap_spatial_cost_func_flag', 1)

    max_topo_err = getparm('max_topo_err', 1)
    lambda_val = getparm('lambda', 1)

    # ===============================================
    # The code below needs to be made sensor specific
    # ===============================================
    rho = 830000  # mean range - need only be approximately correct
    # [TODO]
    if os.path.isfile(incname):
        print("Found inc angle file")
        inc = load_psi_npy(incname, 'inc')
        inc_mean = np.nanmean(inc[inc != 0])
    elif 'mean_incidence' in ps:
        inc_mean = ps['mean_incidence']
    else:
        laname = f'./la{psver}'
        if os.path.isfile(laname):
            la = np.load(laname, allow_pickle=True).item()
            inc_mean = np.mean(la['la']) + 0.052  # incidence angle approx equals look angle + 3 deg
            del la
        else:
            inc_mean = 34 * np.pi / 180  # guess the incidence angle
    max_K = max_topo_err / (lambda_val * rho * np.sin(inc_mean) / 4 / np.pi)
    # ===============================================
    # The code above needs to be made sensor specific
    # ===============================================

    bperp_range = np.max(ps['bperp']) - np.min(ps['bperp'])
    options['n_trial_wraps'] = bperp_range * max_K / (2 * np.pi)
    logit(f"n_trial_wraps={options['n_trial_wraps']}")

    if small_baseline_flag.lower() == 'y':
        options['lowfilt_flag'] = 'n'
        ifgday_ix = ps['ifgday_ix']
        day = ps['day'] - ps['master_day']
    else:
        lowfilt_flag = 'n'
        ifgday_ix = np.concatenate([np.ones((ps['n_ifg'], 1)) * ps['master_ix'], np.arange(0, ps['n_ifg'])[:, None]], axis=1)
        master_ix = np.sum(ps['master_day'] > ps['day']) 
        unwrap_ifg_index = np.setdiff1d(unwrap_ifg_index, master_ix)  # leave master ifg (which is only noise) out
        day = ps['day'] - ps['master_day']
    logit(f'unwrap_hold_good_values {unwrap_hold_good_values.lower()}')
    if unwrap_hold_good_values.lower() == 'y':
        options['ph_uw_predef'] = options['ph_uw_predef'][:, unwrap_ifg_index]
    else:
        options['ph_uw_predef'] = None
    arch = os.uname().machine
    if not arch.startswith('win'):
        ph_uw_some, msd_some = uw_3d(ph_w[:, unwrap_ifg_index], ps['xy'], day, ifgday_ix[unwrap_ifg_index, :], ps['bperp'][unwrap_ifg_index], options)
    else:
        logit('Windows detected: using old unwrapping code without statistical cost processing')
        ph_uw_some = uw_nosnaphu(ph_w[:, unwrap_ifg_index], ps['xy'], day, options)

    ph_uw = np.zeros((ps['n_ps'], ps['n_ifg']), dtype=np.float32)
    msd = np.zeros((ps['n_ifg'],), dtype=np.float32)

    ph_uw[:, unwrap_ifg_index] = ph_uw_some
    if 'msd_some' in locals():
        msd[unwrap_ifg_index] = np.squeeze(msd_some)

 
    if unwrap_patch_phase.lower() == 'y':
        pm = np.load(f'{pmname}.npy')
        ph_w = pm['ph_patch'] / np.abs(pm['ph_patch'])
        del pm
        if not small_baseline_flag.lower() == 'y':
            ph_w = np.concatenate([ph_w[:, :ps['master_ix']-1], np.zeros((ps['n_ps'], 1)), ph_w[:, ps['master_ix']-1:]], axis=1)
        rc = np.load(f'{rcname}.npy', allow_pickle=True).item()
        ph_uw = ph_uw + np.angle(rc['ph_rc'] * np.conj(ph_w))

    ph_uw[:, np.setdiff1d(np.arange(0, ps['n_ifg']), unwrap_ifg_index)] = 0

    np.save(phuwname, {'ph_uw': ph_uw, 'msd': msd})
    logit(1)
