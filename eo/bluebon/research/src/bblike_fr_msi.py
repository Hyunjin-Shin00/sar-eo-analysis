#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jul  7 09:27:31 2025
simulate bluebon rad from msi ref
1) costh0 correction to observation time of bluebon
2) spectral interpolation to bluebon
3) keep the pixel coordinates of msi
@author: yp
"""

import glob,sys,numpy as np
sys.path.append('./../../msipy/src')
import msitools
import s2a_angles
sys.path.append('./../../tools')
import scaling2D
sys.path.append('./../../polygonTools/src_pt')
import tiffcoordconv

def read_msi20m_refl_waves_cth0_lonlat_date(indir):    
    safedir = glob.glob(indir+'/*.SAFE')
    if len(safedir) != 1:
        print(f'indir={indir}')
        print('Error in finding SAFE dir!')
    safedir=safedir[0]
    #print(safedir)
    fxml = glob.glob(safedir+'/MTD*.xml')
    fxml=fxml[0]
    
    # 1) read 10m
    bds=[1,2,3,7] # bandId for 10m data
    refl = msitools.read_refl(safedir, bds, fpath_refl=None)
    # refl = np.transpose(refl,[1,2,0])
    print('10m refl.shape',refl.shape)

    # 2) resample to 20m if res=20m
    scale=2
    refl1=scaling2D.downscale_specImage(refl, scale, mask=None, binning=True)
    print(f'refl1.shape={refl1.shape}')
    print(refl1.dtype)

    # 3) read 20m if res==20m
    bds=[4,5,6,8,11,12] # bandId for 20m data
    refl2 = msitools.read_refl(safedir, bds, fpath_refl=None)
    # refl2 = np.transpose(refl2,[1,2,0])
    print(f'refl2.shape={refl2.shape}')
    # 4) write2file

    refl = np.zeros( ((10,)+refl1.shape[1:3]), dtype=np.float32)
    _idx=[0,1,2]
    refl[_idx,:,:]=refl1[_idx,:,:]
    refl[6,:,:] = refl1[3,:,:]
    refl[[3,4,5],:,:] = refl2[[0,1,2],:,:]
    refl[[7,8,9],:,:] = refl2[[3,4,5],:,:]

    print('final 20m refl shape',refl.shape)   
    
    idx=[1,2,3,4,5,6,7,8,11,12] #20m
    waves=msitools.get_waves(idx)
    
    (solz, sola)=s2a_angles.get_sunangles(safedir)
    print('viewing angles set to 0.; check later!')
    
    cth0 = np.cos(solz*np.pi/180.)
    
    ftif=msitools.get_fgeotif(safedir, '20m')
    nb, nrows, ncols = refl.shape
    xs = np.tile(np.arange(ncols), (nrows,1))
    ys = np.tile(np.arange(nrows).reshape(-1,1), (1, ncols))
    lons, lats = tiffcoordconv.read_msi20_lonlat(ftif, xs, ys)
    
    prod_info = msitools.get_productinfo(safedir)
    prod_date =prod_info['start_time'][:10].replace('-','') 
    
    return refl, waves, cth0, lons, lats, prod_date

def find_ind_reldist(arr_ref, arr):
    low_ind = []
    rel_dist = []

    for val in arr:
        # Find indices where a just smaller and just larger than val
        upper_idx = np.searchsorted(arr_ref, val, side='right')
        lower_idx = upper_idx - 1
    
        if lower_idx < 0:
            # val is below the range of arr_ref
            r_dist = 0.0
            lower_idx=0
        elif upper_idx >= len(arr_ref)-1:
            # val is above the range of a
            r_dist = 1.0
            lower_idx=len(arr_ref)-2
        else:
            lower = arr_ref[lower_idx]
            upper = arr_ref[upper_idx]
            r_dist = (val - lower) / (upper - lower) if upper != lower else 0.0
        low_ind.append(lower_idx)
        rel_dist.append(r_dist) 
    return low_ind, rel_dist
        
def refl_interpolation_to_bbwaves(refl_msi20m, waves_msi20m):
    waves_bb = [490, 560, 625, 665, 705, 740, 783, 842.]
    nb = len(waves_bb)
    # ind & rel_dist waves_bb to waves_msi
    low_ind, rel_dist=find_ind_reldist(waves_msi20m, waves_bb)
    _nb,nrows,ncols = refl_msi20m.shape
    refl_bb = np.array((nb, nrows, ncols), dtype=refl_msi20m.dtype)
    for ib in range(nb):
        refl_bb[ib] = (1-rel_dist[ib])*refl_msi20m[low_ind[ib]] \
        + rel_dist[ib]*refl_msi20m[low_ind[ib]+1]
    return refl_bb
    
# def msi_to_bluebon():
    # 1. read msi reflectance, lat/lon, solzen, earth-sun distance Dse 
    # 2. linear interpolation to wavebands bluebon -> refl_temp
    # 3. compute solar zenith (per pixel) for bluebon time, msi_lat/lon
    #   + earth-sun distance (single value)
    # 4. multiply the ratio of cos(th0) (per pixel), Dse (single)
    
