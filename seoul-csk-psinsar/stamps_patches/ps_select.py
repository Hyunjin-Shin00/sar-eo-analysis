import numpy as np
import os
from sklearn.utils import resample
import matplotlib.pyplot as plt
import multiprocessing

from psi_python.setpsver import setpsver, getpsver
from psi_python.getparm import getparm
from psi_python.clap_filt_patch import clap_filt_patch
from psi_python.logit import logit
from psi_python.ps_topofit import ps_topofit
from psi_python.stamps_save import stamps_save

# FIX: upstream built one task tuple per PS (n_ps can be >1.5M) with `pm`
# inside it, so Pool.map pickled pm - including the multi-GB ph_grid - once per
# task. On Linux we fork, so stash the shared args in a module global instead:
# children inherit them copy-on-write and only integers cross the pipe.
_SHARED = None


def _max_workers():
    import os as _os, multiprocessing as _mp
    return max(1, min(int(_os.environ.get('PSI_MAX_WORKERS', 8)), _mp.cpu_count()))


def compute_ph_patch_idx(i):
    return compute_ph_patch((i,) + _SHARED)


def compute_ph_patch(args):
    i, ix, pm, n_win, n_i, n_j, n_ifg, clap_alpha, clap_beta, slc_osf = args
    ps_ij = pm['grid_ij'][ix[i], :]
    if ps_ij[0] - n_win // 2 < 1:
        i_min = max(ps_ij[0] - n_win // 2, 0) + 1
        i_max = i_min + n_win - 1
    else:
        i_min = max(ps_ij[0] - n_win // 2, 0)
        i_max = i_min + n_win - 1

    if i_max > n_i:
        i_min = i_min - i_max + n_i
        i_max = n_i
        
    if ps_ij[1] - n_win // 2 < 1: 
        j_min = max(ps_ij[1] - n_win // 2, 0) + 1
        j_max = j_min + n_win - 1
    else:
        j_min = max(ps_ij[1] - n_win // 2, 0)
        j_max = j_min + n_win - 1

    if j_max > n_j:
        j_min = j_min - j_max + n_j
        j_max = n_j

    if j_min < 1 or i_min < 1:
        ph_patch2 = np.zeros(pm['ph_grid'].shape[2])
    else:
        ps_bit_i = int(ps_ij[0] - i_min) + 1
        ps_bit_j = int(ps_ij[1] - j_min) + 1
        ph_bit = pm['ph_grid'][int(i_min - 1):int(i_max), int(j_min - 1):int(j_max), :].copy()
        ph_bit[ps_bit_i - 1, ps_bit_j - 1, :] = 0

        ix_i = np.arange(ps_bit_i - (slc_osf - 1), ps_bit_i + slc_osf)[0]
        ix_j = np.arange(ps_bit_j - (slc_osf - 1), ps_bit_j + slc_osf)[0]
        ph_bit[int(ix_i) - 1, int(ix_j) - 1] = 0

        ph_filt = np.zeros_like(ph_bit)
        for i_ifg in range(n_ifg):
            ph_filt[:, :, i_ifg] = clap_filt_patch(ph_bit[:, :, i_ifg], clap_alpha, clap_beta, pm['low_pass'])

        ph_patch2 = ph_filt[ps_bit_i - 1, ps_bit_j - 1, :].squeeze()

    if i % 10000 == 0:
        logit(f'{i} patches re-estimated')
    
    return i, ph_patch2

def bootstrap(func, data, func_args=(), n_samples=1000, random_seed=None):
    rng = np.random.default_rng(seed=random_seed)
    results = []
    for _ in range(n_samples):
        sample = resample(data, replace=True, random_state=rng)
        results.append(func(sample, *func_args))
    return np.array(results)

def ps_select(reest_flag=0, plot_flag=0):
    print("Selecting stable-phase pixels...")

    if reest_flag is None:
        reest_flag = 0

    if plot_flag is None:
        plot_flag = 0

    print("Selecting stable-phase pixels...")
    psver = getpsver()
    psver = 1
    if psver > 1:
        setpsver(1)
    
    # Load parameters
    slc_osf = getparm('slc_osf', 1)
    clap_alpha = getparm('clap_alpha', 1)
    clap_beta = getparm('clap_beta', 1)
    n_win = getparm('clap_win', 1)
    select_method = getparm('select_method', 1)
    if select_method.upper() == 'PERCENT':
        max_percent_rand = getparm('percent_rand', 1)
    else:
        max_density_rand = getparm('density_rand', 1)
    gamma_stdev_reject = getparm('gamma_stdev_reject', 1)
    small_baseline_flag = getparm('small_baseline_flag', 1)
    drop_ifg_index = getparm('drop_ifg_index', 1)
    
    if small_baseline_flag.upper() == 'Y':
        low_coh_thresh = 15
    else:
        low_coh_thresh = 31
    
    psver_data = np.load('psver.npy', allow_pickle=True).item()
    
    psname = f'ps{psver}.npy'
    phname = f'ph{psver}.npy'
    pmname = f'pm{psver}.npy'
    selectname = f'select{psver}.npy'
    daname = f'da{psver}.npy'
    bpname = f'bp{psver}.npy'
    
    ps = np.load(psname, allow_pickle=True).item()
    
    if os.path.isfile(phname):
        print(f'{phname} found')
        ph = np.load(phname, allow_pickle=True).item()['ph']
    else:
        ph = ps['ph']
    
    bperp = ps['bperp'].flatten()
    n_ifg = ps['n_ifg']
    if small_baseline_flag.upper() != 'y':
        master_ix = ps['master_ix']
        master_ix = master_ix
        no_master_ix = np.setdiff1d(np.arange(0, ps['n_ifg']), master_ix)
        ifg_index = np.setdiff1d(np.arange(0, ps['n_ifg']), drop_ifg_index)
        ifg_index = np.setdiff1d(ifg_index, master_ix)
        ifg_index[ifg_index > master_ix] -= 1
        ph = ph[:, no_master_ix]
        bperp = bperp[no_master_ix]
        n_ifg = len(no_master_ix)
    n_ps = ps['n_ps']
    xy = ps['xy']
    
    pm = np.load(pmname, allow_pickle=True).item()
    
    if os.path.isfile(daname):
        da = np.load(daname, allow_pickle=True).item()
        D_A = da['D_A']
        del da
    else:
        D_A = []
    
    if D_A.ndim == 2:
        D_A = D_A[:, 0]
    #if n_ps.ndim == 2:
    #    n_ps = n_ps[:, 0]
    
    if len(D_A) >= 10000:
        D_A_sort = np.sort(D_A.flatten())
        bin_size = 10000 if len(D_A) >= 50000 else 2000
        D_A_max = np.concatenate(([0], D_A_sort[bin_size - 1:len(D_A_sort) - bin_size:bin_size], [D_A_sort[-1]]))
    else:
        D_A_max = np.array([0, 1])
        D_A = np.ones(pm['coh_ps'].shape)
    
    if select_method.upper() != 'PERCENT':
        patch_area = np.prod(np.amax(xy[:, 1:3], axis=0) - np.amin(xy[:, 1:3], axis=0)) / 1e6
        max_percent_rand = max_density_rand * patch_area / (len(D_A_max) - 1)
    
    min_coh = np.zeros(len(D_A_max) - 1)
    D_A_mean = np.zeros(len(D_A_max) - 1)
    Nr_dist = pm['Nr']
    coh_bins = pm['coh_bins']
    coh_bins_tmp = np.arange(0.005, 0.996, 0.01)
    coh_bins_tmp = coh_bins_tmp[:-1] + np.diff(coh_bins_tmp)/2
    coh_bins_tmp = np.concatenate(([-np.inf], coh_bins_tmp, [np.inf]))
    
    if reest_flag == 3:
        coh_thresh = 0
        coh_thresh_coeffs = []
    else:
        for i in range(len(D_A_max) - 1):
            coh_chunk = pm['coh_ps'][(D_A > D_A_max[i]) & (D_A <= D_A_max[i + 1])]
            D_A_mean[i] = np.mean(D_A[(D_A > D_A_max[i]) & (D_A <= D_A_max[i + 1])])
            coh_chunk = coh_chunk[coh_chunk != 0]
            Na, _ = np.histogram(coh_chunk, coh_bins_tmp)
            Nr = Nr_dist * np.sum(Na[0:low_coh_thresh]) / np.sum(Nr_dist[0:low_coh_thresh])
            if i == len(D_A_max) - 2 and plot_flag == 1:
                plt.plot(pm['coh_bins'], Na, 'g')
                plt.plot(pm['coh_bins'], Nr, 'r')
                plt.legend(['data', 'random'])
                plt.title('Before Gamma Reestimation')
                plt.show()
    
            Na[Na == 0] = 1
    
            if select_method.upper() == 'PERCENT':
                percent_rand = np.cumsum(np.flip(Nr)) / np.cumsum(np.flip(Na)) * 100
                percent_rand = np.flip(percent_rand)
            else:
                percent_rand = np.flip(np.cumsum(np.flip(Nr)))
            ok_ix = np.where(percent_rand < max_percent_rand)[0]
            if len(ok_ix) == 0:
                min_coh[i] = 1
            else:
                min_fit_ix = np.min(ok_ix) - 3
                if min_fit_ix <= 0:
                    min_coh[i] = np.nan
                else:
                    max_fit_ix = np.min(ok_ix) + 2
                    max_fit_ix = np.minimum(max_fit_ix, 100)
                    p = np.polyfit(percent_rand[min_fit_ix:max_fit_ix+1],
                                   np.arange(min_fit_ix * 0.01, max_fit_ix * 0.01+0.00001, 0.01), 3)
                    min_coh[i] = np.polyval(p, max_percent_rand)
    
        nonnanix = ~np.isnan(min_coh)
        if np.sum(nonnanix) < 1:
            print('Warning: Not enough random phase pixels to set gamma threshold - using default threshold of 0.3')
            coh_thresh = np.ones(1)*0.3
            coh_thresh_coeffs = []
        else:
            min_coh = min_coh[nonnanix]
            D_A_mean = D_A_mean[nonnanix]
            if len(min_coh) > 1:
                coh_thresh_coeffs = np.polyfit(D_A_mean, min_coh, 1)  # fit polynomial to the curve
                if coh_thresh_coeffs[0] > 0:  # positive slope (as expected)
                    coh_thresh = np.polyval(coh_thresh_coeffs, D_A)
                else:  # unable to ascertain correct slope
                    coh_thresh = np.polyval(coh_thresh_coeffs, 0.35)  # set an average threshold for all D_A
                    coh_thresh_coeffs = []
            else:
                coh_thresh = min_coh
                coh_thresh_coeffs = []
    coh_thresh[coh_thresh < 0] = 0  # to ensure pixels with coh=0 are rejected
    logit(f'Initial gamma threshold: {min(coh_thresh):.3f} at D_A={min(D_A):.2f} to {max(coh_thresh):.3f} at D_A={max(D_A):.2f}')
    
    
    
    if plot_flag == 1:
        plt.figure()
        plt.plot(D_A_mean, min_coh, '*')
        if coh_thresh_coeffs:
            plt.plot(D_A_mean, np.polyval(coh_thresh_coeffs, D_A_mean), 'r')
        plt.ylabel('γ_{thresh}')
        plt.xlabel('D_A')
        plt.show()
    
    ix = np.where(pm['coh_ps'] > coh_thresh)[0]  # select those below threshold
    n_ps = len(ix)
    logit(f'{n_ps} PS selected initially')
    
    if gamma_stdev_reject > 0:
        print(gamma_stdev_reject, 'gamma_std_dev_rejected')
        ph_res_cpx = np.exp(1j * pm['ph_res'][:, ifg_index])
        coh_std = np.zeros(len(ix))
    
        for i in range(len(ix)):
            coh_std[i] = np.std(bootstrap(np.mean, ph_res_cpx[ix[i], ifg_index], func=lambda ph: np.abs(np.sum(ph)) / len(ph), n_samples=100))
    
        ix = ix[coh_std < gamma_stdev_reject]
        n_ps = len(ix)
        logit(f'{n_ps} PS left after pps rejection')
    if reest_flag != 1:
    
        if reest_flag != 2:
            for i in range(len(drop_ifg_index)):
                if small_baseline_flag.lower() == 'y':
                    logit(f'{datestr(ps["ifgday"][drop_ifg_index[i], 0])}-{datestr(ps["ifgday"][drop_ifg_index[i], 1])} is dropped from noise re-estimation')
                else:
                    logit(f'{datestr(ps["day"][drop_ifg_index[i]])} is dropped from noise re-estimation')
    
            del pm['ph_res']
            del pm['ph_patch']
    
            ph_res2 = np.zeros((n_ps, n_ifg), dtype=np.float32)
            ph = ph[ix, :]
    
            if len(coh_thresh) > 1:
                coh_thresh = coh_thresh[ix]
    
            n_i = max(pm['grid_ij'][:, 0])
            n_j = max(pm['grid_ij'][:, 1])
            K_ps2 = np.zeros(n_ps)
            C_ps2 = np.zeros(n_ps)
            coh_ps2 = np.zeros(n_ps)
            ph_filt = np.zeros((n_win, n_win, n_ifg))
            ph_patch2 = np.zeros((n_ps, n_ifg)).astype(np.complex128)       
            num_workers = _max_workers()

            global _SHARED
            _SHARED = (ix, pm, n_win, n_i, n_j, n_ifg, clap_alpha, clap_beta, slc_osf)
            try:
                with multiprocessing.get_context('fork').Pool(processes=num_workers) as pool:
                    results = pool.map(compute_ph_patch_idx, range(n_ps),
                                       chunksize=max(1, n_ps // (num_workers * 16)))
            finally:
                _SHARED = None
    
            for i, result in results:
                ph_patch2[i, :] = result
                
            del pm['ph_grid']
            bp = np.load(bpname, allow_pickle=True).item()
            bperp_mat = bp['bperp_mat'][ix, :]
            del bp
    
            for i in range(n_ps):
                psdph = ph[i, :] * np.conj(ph_patch2[i, :])
                if np.sum(psdph == 0) == 0:  # insist on a non-null value in every ifg
                    psdph = psdph / np.abs(psdph)
                    Kopt, Copt, cohopt, ph_residual = ps_topofit(psdph[ifg_index], bperp_mat[i, ifg_index], pm['n_trial_wraps'], 'n')
                    K_ps2[i] = Kopt
                    C_ps2[i] = Copt
                    coh_ps2[i] = cohopt
                    ph_res2[i, ifg_index] = np.angle(ph_residual)
                else:
                    K_ps2[i] = np.nan
                    coh_ps2[i] = np.nan
    
                if i % 10000 == 0:
                    logit(f'{i} coherences re-estimated')
        else:
            sl = np.load(selectname, allow_pickle=True).item()
            ix = sl['ix']
            coh_ps2 = sl['coh_ps2']
            K_ps2 = sl['K_ps2']
            C_ps2 = sl['C_ps2']
            ph_res2 = sl['ph_res2']
            ph_patch2 = sl['ph_patch2']
        coh_ps_select = np.zeros(pm['coh_ps'].shape).flatten()
        coh_ps_select[ix] = coh_ps2
    
        # Calculate threshold again based on recalculated coh
        D_A_max_length = len(D_A_max)
        min_coh = np.empty(D_A_max_length - 1)
        D_A_mean = np.empty(D_A_max_length - 1)
        for i in range(D_A_max_length - 1):
            coh_chunk = coh_ps_select[(D_A > D_A_max[i]) & (D_A <= D_A_max[i+1])]
            D_A_mean[i] = np.mean(D_A[(D_A > D_A_max[i]) & (D_A <= D_A_max[i+1])])
            coh_chunk = coh_chunk[coh_chunk != 0]  # Discard PSC for which coherence was not calculated
            Na, _ = np.histogram(coh_chunk, bins=coh_bins_tmp)
            Nr = Nr_dist * np.sum(Na[:low_coh_thresh]) / np.sum(Nr_dist[:low_coh_thresh])
    
            if i == D_A_max_length - 2 and plot_flag == 1:
                plt.figure()
                plt.plot(pm['coh_bins'][:-1], Na, 'g')
                plt.plot(pm['coh_bins'][:-1], Nr, 'r')
                plt.legend(['data', 'random'])
                plt.title('After Gamma Reestimation')
                plt.show()
    
            Na[Na == 0] = 1  # Avoid divide by zero
    
            if select_method.upper() == 'PERCENT':
                percent_rand = np.flip(np.cumsum(np.flip(Nr)) / np.cumsum(np.flip(Na)) * 100)
            else:
                percent_rand = np.flip(np.cumsum(np.flip(Nr)))
    
            ok_ix = np.where(percent_rand < max_percent_rand)[0]
    
            if len(ok_ix) == 0:
                min_coh[i] = 1
            else:
                min_fit_ix = min(ok_ix) - 2
                if min_fit_ix <= 0:
                    min_coh[i] = np.nan
                else:
                    max_fit_ix = min(ok_ix) + 3
                    max_fit_ix = min(100, max_fit_ix)  
                    coh_x = percent_rand[min_fit_ix - 1:max_fit_ix]
                    coh_y = np.arange(min_fit_ix * 0.01, max_fit_ix * 0.01 + 0.005, 0.01)
                    coh_x_mean = np.mean(coh_x)
                    coh_x_std = np.std(coh_x, ddof = 1)
                    p = np.polyfit((coh_x - coh_x_mean) / coh_x_std, coh_y, 3)
                    min_coh[i] = np.poly1d(p)((max_percent_rand-coh_x_mean) / coh_x_std)
    
        nonnanix = ~np.isnan(min_coh)
        if np.sum(nonnanix) < 1:
            coh_thresh = 0.3
            coh_thresh_coeffs = []
        else:
            min_coh = min_coh[nonnanix]
            D_A_mean = D_A_mean[nonnanix]
        
            if len(min_coh) > 1:
                coh_thresh_coeffs = np.polyfit(D_A_mean, min_coh, 1)  # Fit polynomial to the curve
                if coh_thresh_coeffs[0] > 0:  # Positive slope (as expected)
                    coh_thresh = np.polyval(coh_thresh_coeffs, D_A[ix])
                else:  # Unable to ascertain correct slope
                    coh_thresh = np.polyval(coh_thresh_coeffs, 0.35)  # Set an average threshold for all D_A
                    coh_thresh_coeffs = []
            else:
                coh_thresh = min_coh
                coh_thresh_coeffs = []
        
        # Ensure coh_thresh is array-like so we can apply mask safely
        if not isinstance(coh_thresh, np.ndarray):
            coh_thresh = np.array([coh_thresh])  # Convert scalar to 1D array
        
        coh_thresh[coh_thresh < 0] = 0  # Ensures pixels with coh=0 are rejected
                
        logit(f"Reestimation gamma threshold: {np.min(coh_thresh):.3f} at D_A={np.min(D_A):.2f} to {np.max(coh_thresh):.3f} at D_A={np.max(D_A):.2f}")
        
        bperp_range = np.max(bperp) - np.min(bperp)
        keep_ix = (coh_ps2 > coh_thresh) & (np.abs(pm['K_ps'][ix].flatten() - K_ps2) < 2 * np.pi / bperp_range)
        del pm
        logit(f"{np.sum(keep_ix)} ps selected after re-estimation of coherence")
    
    else:
        del pm['ph_grid']
        ph_patch2 = pm['ph_patch'][ix, :]
        ph_res2 = pm['ph_res'][ix, :]
        K_ps2 = pm['K_ps'][ix]
        C_ps2 = pm['C_ps'][ix]
        coh_ps2 = pm['coh_ps'][ix]
        keep_ix = np.ones_like(ix, dtype=bool)
        
    # Keep information about the number of PS left.
    if not os.path.isfile('no_ps_info.npy'):
        stamps_step_no_ps = np.zeros((5, 1))
    else:
        stamps_step_no_ps = np.load('no_ps_info.npy')
        stamps_step_no_ps[3:] = 0
    
    if np.sum(keep_ix) == 0:
        print('***No PS points left. Updating the stamps log for this****')
        # Update the flag indicating no PS left in step 3
        stamps_step_no_ps[3] = 1
    
    np.save('no_ps_info.npy', stamps_step_no_ps)
    
    if plot_flag == 1:
        plt.figure()
        plt.plot(D_A_mean, min_coh, '*')
        plt.hold(True)
        if not np.isnan(coh_thresh_coeffs).any():
            plt.plot(D_A_mean, np.polyval(coh_thresh_coeffs, D_A_mean), 'r')
        plt.ylabel('γ_{thresh}')
        plt.xlabel('D_A')
        plt.show()
    
    # Save the output to the file
    output_data = {'ix': ix, 'keep_ix': keep_ix, 'ph_patch2': ph_patch2, 'ph_res2': ph_res2, 'K_ps2': K_ps2, 'C_ps2': C_ps2, 'coh_ps2': coh_ps2, 'coh_thresh': coh_thresh, 'coh_thresh_coeffs': coh_thresh_coeffs, 'clap_alpha': clap_alpha, 'clap_beta': clap_beta, 'n_win': n_win, 'max_percent_rand': max_percent_rand, 'gamma_stdev_reject': gamma_stdev_reject, 'small_baseline_flag': small_baseline_flag, 'ifg_index': ifg_index}
    np.save(selectname, output_data)
    
    logit(1)
