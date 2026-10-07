#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep  2 09:20:50 2025
@author: yp

Bluebon cross-track nonuniformity
pixel to pixel comparison between Bb and msi
investigate along-track variability of cross-track nonuniformity (ctnu)
find the ctnu is offset or slope 
design how to correct Bb CTNU
Use glint-cloud-free image (e.g. SoffSydney data)


Steps
1. irow -> compute lat, lon : use bbcoords_tool
2. sample (every n pixel)
3. find MSI pixel coordinates 
    :xs, ys=tiffcoordconv.geotiff_xy2lonlat(ftif, lons, lats, inverse=True)
4. compare Bb to (simed) MSI reflectance(rhot)
    - for given irow
    - for given icol 
"""
import numpy as np
import sys
sys.path.append('../../polygonTools/src_pt')
import tiffcoordconv

from bbcoords_tool import wrapper_look_latlon_sim, bluebon_ij_to_latlon
from datetime import datetime, timezone

sys.path.append('../../tools')
import ncutils, tiffutils

def fit_common_slope_per_column_intercepts(x, y, sample_weight=None, return_r2=True):
    """
    Fit y_{i,j} = a * x_{i,j} + b_j  with one global slope 'a' and per-column intercepts 'b_j'.
    - x, y: arrays of shape (I, J)
    - sample_weight (optional): same shape (I, J); non-negative weights
    - return_r2: if True, returns per-column R^2
    Returns: a (scalar), b (J,), r2 (J,) or None
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != y.shape:
        raise ValueError("x and y must have the same shape (I, J).")
    I, J = x.shape

    # Only use pairs where both x and y are finite
    msk = np.isfinite(x) & np.isfinite(y)

    # Weights
    if sample_weight is None:
        w = np.where(msk, 1.0, 0.0)
    else:
        w = np.asarray(sample_weight, dtype=float)
        if w.shape != x.shape:
            raise ValueError("sample_weight must have shape (I, J).")
        # Zero-out weights where data are missing
        w = np.where(msk, w, 0.0)

    # Weighted column sums and means (over valid pairs)
    wsum = w.sum(axis=0)  # (J,)
    x_bar = np.divide((w * x).sum(axis=0), wsum, out=np.full(J, np.nan), where=wsum != 0)
    y_bar = np.divide((w * y).sum(axis=0), wsum, out=np.full(J, np.nan), where=wsum != 0)

    # Within-column centered data (zeros where invalid)
    x_c = np.where(msk, x - x_bar[None, :], 0.0)
    y_c = np.where(msk, y - y_bar[None, :], 0.0)

    # Common slope a_hat from centered data (fixed-effects OLS)
    num = (w * x_c * y_c).sum()        # Σ_j Σ_i w * (x - x̄_j)(y - ȳ_j)
    den = (w * x_c * x_c).sum()        # Σ_j Σ_i w * (x - x̄_j)^2
    a = np.divide(num, den) if den != 0 else np.nan

    # Per-column intercepts
    b = y_bar - a * x_bar              # (J,)

    # Optional: per-column R^2
    r2 = None
    if return_r2:
        y_hat = a * x + b[None, :]
        resid = np.where(msk, y - y_hat, 0.0)
        rss = (w * resid**2).sum(axis=0)
        tss = (w * np.where(msk, (y - y_bar[None, :])**2, 0.0)).sum(axis=0)
        r2 = np.divide(1.0 - rss / tss, 1.0, out=np.full(J, np.nan), where=tss != 0)

    return a, b, r2

def column_intercepts_for_fixed_slope(x, y, a):
    """
    x, y: shape (I, J)
    a: scalar slope (shared)
    returns b: shape (J,)
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if x.shape != y.shape:
        raise ValueError("x and y must have the same shape (I, J).")

    # b_j = mean_i (y_ij - a * x_ij), ignoring NaNs
    b = np.nanmean(y - a * x, axis=0)
    return b

def slope_given_b(x, y, b):
    """
    Given per-column intercepts b[j], estimate the common slope 'a' in
    y_ij = a * x_ij + b_j  by least squares (no weights).

    x, y : arrays of shape (I, J)
    b    : array of shape (J,)
    Returns: a (scalar)
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    b = np.asarray(b, float)

    if x.shape != y.shape:
        raise ValueError(f"x and y must have same shape, got {x.shape} vs {y.shape}")
    if b.ndim != 1 or b.shape[0] != x.shape[1]:
        raise ValueError(f"b must be (J,), got {b.shape} for data (I,J)={x.shape}")

    # Mask valid entries; exclude columns where b is NaN
    msk = np.isfinite(x) & np.isfinite(y) & np.isfinite(b)[None, :]

    # Adjust y by known intercepts per column, then fit a through the origin
    y_adj = np.where(msk, y - b[None, :], 0.0)
    x_used = np.where(msk, x, 0.0)

    num = np.sum(x_used * y_adj)  # Σ x * (y - b)
    den = np.sum(x_used * x_used) # Σ x^2
    return num / den if den != 0 else np.nan


def linreg_per_column(x, y):
    """
    Fit y = a_j * x + b_j independently for each column j.
    Returns:
      a: slopes, shape (J,)
      b: intercepts, shape (J,)
      r2: coefficient of determination per column (J,)
    NaNs in x or y are ignored pairwise.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != y.shape:
        raise ValueError("x and y must have the same shape (I, J).")

    I, J = x.shape
    msk = ~np.isnan(x) & ~np.isnan(y)

    n   = msk.sum(axis=0).astype(float)                      # (J,)
    sx  = np.where(msk, x, 0.0).sum(axis=0)                  # Σx
    sy  = np.where(msk, y, 0.0).sum(axis=0)                  # Σy
    sxx = np.where(msk, x*x, 0.0).sum(axis=0)                # Σx^2
    sxy = np.where(msk, x*y, 0.0).sum(axis=0)                # Σxy

    denom = n * sxx - sx * sx
    a = np.divide(n * sxy - sx * sy, denom,
                  out=np.full_like(denom, np.nan), where=denom != 0)
    b = np.divide(sy - a * sx, n,
                  out=np.full_like(n, np.nan), where=n != 0)

    # Optional: R^2 per column
    # Predictions and residuals (mask out NaNs)
    y_hat = a[None, :] * x + b[None, :]
    resid = np.where(msk, y - y_hat, 0.0)
    rss = (resid**2).sum(axis=0)

    y_col_mean = np.divide(sy, n, out=np.full_like(n, np.nan), where=n != 0)
    tss = np.where(msk, (y - y_col_mean[None, :])**2, 0.0).sum(axis=0)
    r2 = np.divide(1.0 - rss / tss, 1.0,
                   out=np.full_like(tss, np.nan), where=tss != 0)

    return a, b, r2


import matplotlib.pyplot as plt
if __name__=="__main__":
    
    # #--[time of origin: can be arbitrary for this simulation]
    # yr=2025; mo=7; dd=12; hr=2; mn=46; se=25
    # t0_utc=datetime(yr,mo,dd,hr,mn,se,tzinfo=timezone.utc)
    # #--[satellite latitude and longitue]
    # phi0_deg,lam0_deg =-33.8172,150.9986
    # ascending=False
    # alt_bb = 494. #Perigee: 499.9km, Apogee:500.4km
    # inc_bb = 97.4-0.2#+0.4   
    # #--[roll and yaw]
    # roll_bb = 2.4948+0.4; 
    # yaw_deg=0.8+0.8
    # #--[grid intervals]
    # roll_width=3.; roll_step_deg=0.02; minutes=0.5; step_s=0.05
    
    from setting_250806_SoffSydney import yr, mo, dd, hr, mn, se, phi0_deg, lam0_deg, \
        ascending, alt_bb, inc_bb, roll_bb, yaw_deg, roll_width, roll_step_deg, minutes, step_s, \
        gcps_ll, \
        fnc, ftif, irange_int_1, irange_int_2
    t0_utc=datetime(yr,mo,dd,hr,mn,se,tzinfo=timezone.utc)
    look_lat, look_lon =  wrapper_look_latlon_sim(t0_utc, phi0_deg, lam0_deg, ascending, alt_bb, inc_bb,yaw_deg, roll_bb, roll_width, roll_step_deg, minutes, step_s)  

    print(f'bluebon DN data: {fnc}')
    data_bb=ncutils.getimage(fnc)
    waves_bb=ncutils.readheader(fnc)['waves']
    ncols=data_bb.shape[2]
    
    data_msi=tiffutils.getraster(ftif,None)
    waves_msi=tiffutils.get_waves_tif(ftif)
    
    from scipy.interpolate import interp1d

    f = interp1d(
        waves_msi,            # length Nwave
        data_msi,             # shape (Nwave, I, J)
        kind='linear',
        axis=0,            # interpolate along the wave axis
        bounds_error=False,
        fill_value='extrapolate'
    )
    data_msi_sim = f(waves_bb)   # shape (len(waves1), I, J)
    
    #---resampling intervals
    jint=1; iint=3; 
    
    # irow = 1900
    # ij_list =[[irow, j ] for j in range(ncols)] 
    # lats, lons= bluebon_ij_to_latlon(look_lat, look_lon, gcps_ll, ij_list)
    
    # xs, ys=tiffcoordconv.geotiff_xy2lonlat(ftif, lons, lats, inverse=True)
    # jarr=np.round(xs).astype(np.int32)
    # iarr=np.round(ys).astype(np.int32)
    # line_data_msi = data_msi[:,iarr,jarr][:,::jint]
    # line_data_bb=data_bb[:,irow,:][:,::jint]
    
    # ib=1
    
    # plt.figure()
    # plt.plot(line_data_msi[ib,:], alpha=0.5)
    # plt.twinx()
    # plt.plot(line_data_bb[ib,:], color='r', alpha=0.5)
    # plt.ylim(bottom=500)
    # plt.title(f'cross track profile band={ib+1}, row no={irow}')
    
    #--- 2d array 
    #--- first attempt
    
    
    si, ei, iint = irange_int_1
    print(f'irange & int = {irange_int_1}')
    ij_list =[[irow, j ] for irow in range(si, ei, iint) for j in range(0, ncols, jint)] 
    
    lats, lons= bluebon_ij_to_latlon(look_lat, look_lon, gcps_ll, ij_list)
    
    xs, ys=tiffcoordconv.geotiff_xy2lonlat(ftif, lons, lats, inverse=True)
    jarr=np.round(xs).astype(np.int32)
    iarr=np.round(ys).astype(np.int32)
    msi_res = data_msi_sim[:,iarr,jarr]
    bb_res=data_bb[:,si:ei:iint,0:ncols:jint]
    nb,ny,nx = bb_res.shape
    msi_res1=np.reshape(msi_res, (nb,ny,nx))    
        
    #--[per band slope, per-column(cross-track) offset ]
    slope=[]
    offset=[]
    for ib in range(8): #[0 to 7] : band-1
        x_msi = msi_res1[ib,:,:]
        y_bb = bb_res[ib,:,:]
        # x, y are defined for fitting convenience
        
        idx = np.flatnonzero(y_bb[0,:])           # indices where x != 0
        first, last = (idx[0], idx[-1]) if idx.size else (None, None)
        print('first, last:',first, last)
        # x, y are shape (I, J)
        y = np.asarray(y_bb[:,first:last+1])
        x = np.asarray(x_msi[:,first:last+1])
          
        a_hat, b_hat, r2 = fit_common_slope_per_column_intercepts(x, y)
        print(b_hat.shape)
        
        slope.append(a_hat)
        offset.append(b_hat)
        
   
    si=8000; ei=10000;iint=2
    # si=1950; ei=4500
    si, ei, iint = irange_int_2
    print(f'irange & int = {irange_int_2}')
    ij_list =[[irow, j ] for irow in range(si, ei, iint) for j in range(0, ncols, jint)] 
    
    lats, lons= bluebon_ij_to_latlon(look_lat, look_lon, gcps_ll, ij_list)
    
    xs, ys=tiffcoordconv.geotiff_xy2lonlat(ftif, lons, lats, inverse=True)
    jarr=np.round(xs).astype(np.int32)
    iarr=np.round(ys).astype(np.int32)
    msi_res = data_msi_sim[:,iarr,jarr]
    bb_res=data_bb[:,si:ei:iint,0:ncols:jint]
    nb,ny,nx = bb_res.shape
    msi_res1=np.reshape(msi_res, (nb,ny,nx))    
        
    #--[per band slope, per-column(cross-track) offset ]
    offset=[]
    for ib in range(8): #[0 to 7] : band-1
        x_msi = msi_res1[ib,:,:]
        y_bb = bb_res[ib,:,:]
        # x, y are defined for fitting convenience
        
        idx = np.flatnonzero(y_bb[0,:])           # indices where x != 0
        first, last = (idx[0], idx[-1]) if idx.size else (None, None)
        print('first, last:',first, last)
        # x, y are shape (I, J)
        y = np.asarray(y_bb[:,first:last+1])
        x = np.asarray(x_msi[:,first:last+1])
          
        a_hat=slope[ib]
        b_hat=column_intercepts_for_fixed_slope(x, y, a_hat)
        print(b_hat.shape)
        offset.append(b_hat)

    if 0:#----save as a npz file for use in calibration
        idx_panfirst=[2,0,1,3,4,5,6,7]
        _sl=np.array(slope); _sl=_sl[idx_panfirst]
        _off = [_o[::-1] for _o in offset]
        _off=np.array(_off); _off=_off[idx_panfirst]
        np.savez_compressed("coefs_rad_to_DN.npz", slope=_sl, pixelwise_offset=_off)
        # rhot = (ND-offset[ib,j])/slope[i]            
    
    if 0: #graph for offset
        #need %matplotlib
        ib=3
        plt.figure()
        plt.plot(offset[ib], alpha=0.5)
        plt.title(f'band={ib+1} slope={slope[ib]:e}')


    

    if 0: #verification
        with np.load("coefs_rhot_to_ND.npz") as z:
            slope = z["slope"]
            offset = z["pixelwise_offset"]   
            
        idx_pan3rd=[1,2,0,3,4,5,6,7]
        slope=np.array(slope); slope=slope[idx_pan3rd]
        offset = [_off[::-1] for _off in offset]
        offset=np.array(offset); offset=offset[idx_pan3rd]
        
        irow = 300#12000
        ij_list =[[irow, j ] for j in range(ncols)] 
        lats, lons= bluebon_ij_to_latlon(look_lat, look_lon, gcps_ll, ij_list)
        
        xs, ys=tiffcoordconv.geotiff_xy2lonlat(ftif, lons, lats, inverse=True)
        jarr=np.round(xs).astype(np.int32)
        iarr=np.round(ys).astype(np.int32)
        line_data_msi = data_msi_sim[:,iarr,jarr][:,::jint]
        line_data_bb=data_bb[:,irow,:][:,::jint]
        
        ib=3
        idx = np.flatnonzero(line_data_bb[0,:])           # indices where x != 0
        first, last = (idx[0], idx[-1]) if idx.size else (None, None)
        #recover b_hat dimension
        ntails = line_data_bb.shape[1]-(last+1)
        b_hat = offset[ib]
        b_hat1=np.copy(b_hat)
        if first > 0 or ntails>0:
            b_hat1 = np.pad(b_hat, (first, ntails), mode='constant', constant_values=0)
            
        plt.figure()
        plt.plot(line_data_msi[ib,:], alpha=0.5)
        # plt.twinx()
        plt.plot((line_data_bb[ib,:]-b_hat1)/a_hat, color='r', alpha=0.5)
        # plt.ylim(bottom=500)
        plt.title(f'cross track profile band={ib+1}, row no={irow}')