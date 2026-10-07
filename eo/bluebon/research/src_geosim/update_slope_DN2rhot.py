#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Sep  8 16:01:30 2025
@author: yp
Update slope coefs for rhot->DN conversion
Use different bb-msi data pair other than those used for 1st computation
Use b[j] from coefs_rhot2DN.npz based on glint-cloud-free image (e.g. SoffSydney data) 
"""
import sys
sys.path.append('../../polygonTools/src_pt')
import tiffcoordconv
import numpy as np
from bbcoords_tool import wrapper_look_latlon_sim, bluebon_ij_to_latlon
from datetime import datetime, timezone
sys.path.append('../../tools')
import ncutils, tiffutils
import compute_coef_DN2rhot
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
    

    from setting_250903_Namhae import yr, mo, dd, hr, mn, se, phi0_deg, lam0_deg, \
        ascending, alt_bb, inc_bb, roll_bb, yaw_deg, roll_width, roll_step_deg, minutes, step_s, \
        gcps_ll, \
        fnc, ftif, irange_int_1, irange_int_2
   
    t0_utc=datetime(yr,mo,dd,hr,mn,se,tzinfo=timezone.utc)
    look_lat, look_lon =  wrapper_look_latlon_sim(t0_utc, phi0_deg, lam0_deg, ascending, alt_bb, inc_bb,yaw_deg, roll_bb, roll_width, roll_step_deg, minutes, step_s) 
    
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
    
    
    #--- 2d array 

    # si=200; ei=2500+2000
    # si=5450; ei=9450 #Chesapeake
    # ij_list =[[irow, j ] for irow in range(si, ei, iint) for j in range(0, ncols, jint)] 
    
    # lats, lons= bluebon_ij_to_latlon(look_lat, look_lon, gcps_ll, ij_list)
    
    # xs, ys=tiffcoordconv.geotiff_xy2lonlat(ftif2, lons, lats, inverse=True)
    # jarr=np.round(xs).astype(np.int32)
    # iarr=np.round(ys).astype(np.int32)
    # msi_res = data_msi_sim[:,iarr,jarr]
    # bb_res=data_bb[:,si:ei:iint,0:ncols:jint]
    # nb,ny,nx = bb_res.shape
    # msi_res1=np.reshape(msi_res, (nb,ny,nx))    
    
    with np.load("coefs_rhot_to_ND.npz") as z:
        _slope = z["slope"]
        _offset = z["pixelwise_offset"]   
        #band reordering to wavelength
        idx_pan3rd=[1,2,0,3,4,5,6,7]
        slope=np.array(_slope); slope=slope[idx_pan3rd]
        offset = [_off[::-1] for _off in _offset]
        offset=np.array(offset); offset=offset[idx_pan3rd]

        
    si=200; ei=900;iint=2
    # si=1950; ei=4500
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
    slope_new=[]
    offset_new=[]
    for ib in range(8): #[0 to 7] : band-1
        x_msi = msi_res1[ib,:,:]
        y_bb = bb_res[ib,:,:]
        b=offset[ib,:]
        
        idx = np.flatnonzero(y_bb[0,:])           # indices where x != 0
        first, last = (idx[0], idx[-1]) if idx.size else (None, None)
        print('first, last:',first, last)
        # x, y are shape (I, J)
        y = np.asarray(y_bb[:,first:last+1])
        x = np.asarray(x_msi[:,first:last+1])
        
        a_hat = compute_coef_DN2rhot.slope_given_b(x, y, b)
        
        print(a_hat)
        slope_new.append(a_hat)
        offset_new.append(b)

    if 1:#----save as a npz file for use in calibration
        idx_panfirst=[2,0,1,3,4,5,6,7]
        _sl=np.array(slope_new); _sl=_sl[idx_panfirst]
        _off = [_o[::-1] for _o in offset_new]
        _off=np.array(_off); _off=_off[idx_panfirst]
        np.savez_compressed("coefs_rhot_to_ND_updated.npz", slope=_sl, pixelwise_offset=_off)
        #(DN-offset)/slope -> rad        
    
    if 0: #graph for offset
        #need %matplotlib
        ib=4
        plt.figure()
        plt.plot(offset_new[ib], alpha=0.5)
        plt.title(f'band={ib+1} slope={slope_new[ib]:e}')
    

    if 0: #verification
        irow = 8163#300#12000
        ij_list =[[irow, j ] for j in range(ncols)] 
        lats, lons= bluebon_ij_to_latlon(look_lat, look_lon, gcps_ll, ij_list)
        
        xs, ys=tiffcoordconv.geotiff_xy2lonlat(ftif, lons, lats, inverse=True)
        jarr=np.round(xs).astype(np.int32)
        iarr=np.round(ys).astype(np.int32)
        
        ib=6
        line_data_msi = data_msi_sim[ib,iarr,jarr]
        line_data_bb=data_bb[ib,irow,:]
        
        idx = np.flatnonzero(line_data_bb)           # indices where x != 0
        first, last = (idx[0], idx[-1]) if idx.size else (None, None)
        #recover b_hat dimension
        ntails = line_data_bb.shape[0]-(last+1)
        b_hat = offset_new[ib]
        b_hat1=np.copy(b_hat)
        if first > 0 or ntails>0:
            b_hat1 = np.pad(b_hat, (first, ntails), mode='constant', constant_values=0)
            
        plt.figure()
        plt.plot(line_data_msi, alpha=0.5)
        # plt.twinx()
        plt.plot((line_data_bb-b_hat1)/slope[ib], color='r', alpha=0.5)
        
        # plt.ylim(bottom=500)
        plt.title(f'cross track profile band={ib+1}, row no={irow}')