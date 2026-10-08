import numpy as np
from scipy.ndimage import uniform_filter1d
# from scipy.ndimage import median_filter

import scipy.ndimage as nd
def fill_nan_nearest(img, mask):
    # mask = np.isnan(img)
    # Get indices of valid pixels
    idx = nd.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return img[tuple(idx)]

def line_noise_correction(data, mask, mask1d, vertical=True, w=21): #w = 21  # box size
    data_w = fill_nan_nearest(data, mask)
    # data_w=np.copy(data)
    # data_w[mask]=0.

    axis_no=1 if vertical else 0

    # edge handling: 'nearest' ~ like extending edge pixels; use 'constant' to mimic zero-padding
    box_mean = uniform_filter1d(data_w, size=w, axis=axis_no, mode='nearest')

    # box_mean = median_filter(data, size=(1,w))# slightly slow, nogood for linear noise
    diff_data = data_w - box_mean
    diff_data[mask]=np.nan
    mean_diff = np.nanmean(diff_data, axis=1-axis_no)
    

    mean_diff[mask1d==1]=0.
    
    data_c = data - np.expand_dims(mean_diff, axis=1-axis_no)
    # if vertical:
    #     data_c = data - mean_diff[None,:]
    # else:
    #     data_c = data - mean_diff[:,None]

    # data_c[mask]=data[mask]

    return data_c, mean_diff

def bluebon_linecorrection(indata, v=True, h=True) :
    print(f'v={v},h={h}')
    ibd=6
    data_b6 = indata[ibd,:,:]
    mask = data_b6 > 0.1 #0.03 #land or cloud
    # --mask 1D for vertical line
    count = mask.sum(axis=0)
    mask1d_v = np.zeros(count.shape)
    mask1d_v[count > 0.5*mask.shape[0]]=1
    print(f'np.count_nonzero(mask1d_v)={np.count_nonzero(mask1d_v)}')
    
    count = mask.sum(axis=1)
    mask1d_h = np.zeros(count.shape)
    mask1d_h[count > 0.5*mask.shape[1]]=1
    print(f'np.count_nonzero(mask1d_h)={np.count_nonzero(mask1d_h)}')

    nb = indata.shape[0]
    outdata=[]
    for ibd in range(nb):
        data = indata[ibd,:,:]
        if v:
            data_v, mean_diff  = line_noise_correction(data, mask, mask1d_v, vertical=True, w=31)#, w=201)
        else:
            data_v = data
        if h:
            data_vc, mean_diff_ = line_noise_correction(data_v, mask, mask1d_h, vertical=False, w=51)
        else:
            data_vc =data_v
        outdata.append(data_vc)
        print(f'line noise corrected for band {ibd+1}')
    outdata = np.array(outdata)
    return outdata

import rsr_f0_bluebon
import sys
sys.path.append('./../../tools')
import ncutils
from genrgb import gen_rgb
def main(fnc):
    indata = ncutils.getimage(fnc, bip=False, noScale=False)
    
    outdata = bluebon_linecorrection(indata)
    
    if True: #creatubg pngs
        odir='<WORK_ROOT>/myPy_inout/bluebon'
        ngb=[7,1,0]
        rgb=[3,1,0]
        gen_rgb(indata, ofilepath=odir+'/indata', bds=rgb)
        gen_rgb(outdata, ofilepath=odir+'/outdata', bds=rgb)
        gen_rgb(indata, ofilepath=odir+'/indata', bds=ngb)
        gen_rgb(outdata, ofilepath=odir+'/outdata', bds=ngb)
    if True: #write to nc file
        fnc_out=fnc.replace('_stacked_rhot', '_stacked_linescorr_rhot')
        f0_bb, waves_bb = rsr_f0_bluebon.compute_F0() #order MS1 MS2 ...MS7 PAN
        _idx=np.argsort(waves_bb) #rearrange the order of increasing wavelengths
        waves_bb=waves_bb[_idx]
        ncutils.writeSpecData2file_2nc(outdata, fnc_out, waves=waves_bb, slope=1./65535, offset=0.)
        print(f'Writing to {fnc_out}')

if __name__=="__main__":
    # fnc = '<WORK_ROOT>/Downloads/bluebon/250716_Bahrain/myout/250716_074255_stacked_rhot.nc'
    fnc = '<WORK_ROOT>/Downloads/bluebon/250806_Australia/myout/250806_002855_stacked_rhot.nc'
    main(fnc)