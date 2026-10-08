#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jul  7 21:23:23 2025

@author: yp
"""
import math

import numpy as np

def find_ind_reldist(arr_ref, arr):
    arr_ref = np.array(arr_ref)
    arr = np.array(arr)

    upper_idx = np.searchsorted(arr_ref, arr, side='right')
    lower_idx = upper_idx - 1

    # Clamp out-of-bound indices
    lower_idx = np.clip(lower_idx, 0, len(arr_ref) - 2)
    upper_idx = lower_idx + 1

    # Get the reference values at lower and upper indices
    lower_vals = arr_ref[lower_idx]
    upper_vals = arr_ref[upper_idx]

    # Avoid division by zero
    denom = upper_vals - lower_vals
    denom = np.where(denom == 0, 1e-10, denom)

    rel_dist = (arr - lower_vals) / denom

    # Clamp rel_dist to [0, 1] for values outside arr_ref
    rel_dist = np.where(arr < arr_ref[0], 0.0, rel_dist)
    rel_dist = np.where(arr > arr_ref[-1], 1.0, rel_dist)

    return lower_idx, rel_dist

from scipy.stats import linregress
#param_band = dict {band:MS1, L_rate:666, TDI:4 }
def calibrate_bb_band(image_band, param, df,dfrad, linear_cal=True):
    band=param['band']
    l_rate=param['L_rate']
    tdi = param['TDI']
    
    T_rad=[0.]+dfrad[band].values.tolist()
    _bds =['PAN']+[f'MS{_}' for _ in range(1,8)]
    _max=[17500,9500,9500,13200,7350,8000,11000,32000]
    maxRad_dict=dict(zip(_bds, _max))
    
    
    df1 = df[ (df['BAND'] == band) & (df['Line rate'] == l_rate)]
    df2=df1[(df1['TDI'] == tdi)]
    
    nrows, ncols = image_band.shape
    orad = np.zeros_like(image_band, dtype=np.float32) #
    for icol in range(ncols):
        # T_rad=[]; 
        T_DN=[]
        for lmap_level in range(21):
            _df = df2[df2['lmap_level'] == lmap_level]
            # T_rad.append(_df['Radiant intensity'].values[0])
            colname=f'{icol}' #ncols-1-icol: wrong, strong line noise
            T_DN.append(_df[colname].values[0])
        
        idx = np.array(T_DN)<4000
        idx2=np.array(T_rad)<maxRad_dict[band]
        x=np.array(T_DN)[idx & idx2]; y= np.array(T_rad)[idx & idx2]
        
        #ref: calibrtion_curve.py
        if linear_cal:#linear regression
            m, b, r_value, p_value, std_err = linregress(x, y)
            arrDN = image_band[:,icol]
            _rad = m*arrDN + b
        else: #quadratic regression
            x1=x-x[0]
            a,b,c=np.polyfit(x1,y,2)
            arrDN = image_band[:,icol]
            _rad=np.polyval([a,b,c],arrDN-x[0])
        
        # rsq=r_value*r_value; #print(f'icol, rsq: {icol}, {rsq}')
        
        # OLD stuff: piecewise linear interpolation!!
        # T_rad =np.asarray(T_rad)
        # logT_DN=[math.log10(_) for _ in T_DN]
        # idx_valid = arrDN > 0
        # logDN = np.log10(arrDN[idx_valid])
        # low_idx, rel_dist = find_ind_reldist(logT_DN, logDN) 
        # _rad = (1.-rel_dist)*T_rad[low_idx]+rel_dist*T_rad[low_idx+1]
        # orad[idx_valid,icol] = _rad
        
        orad[:,icol] = _rad*(tdi/4) #16./tdi testing
        
    return orad.astype(np.float32)/1000.


def bb_DN2rad(image_band, slope, offset, maxDN ):
    #use "rad2DN" perband slope and percolumn offset
    # l_rate=param['L_rate']
    # tdi = param['TDI'] [1,4,4,]
    
    # band order _bds =['PAN']+[f'MS{_}' for _ in range(1,8)]
    
    
    nrows, ncols = image_band.shape
    # orad = np.zeros_like(image_band, dtype=np.float32) #
    orad = (image_band - offset[None,:])/slope
    orad[image_band>maxDN]=0.
        
    return orad.astype(np.float32)

def bb_DN2rad_NEW(image_band, coeff_band):
    #Use "DN2rad" percolumn slope and offset
    
    nrows, ncols = image_band.shape
    # orad = np.zeros_like(image_band, dtype=np.float32) #
    slope=coeff_band[:,0]
    offset=coeff_band[:,1]
    orad = image_band*slope[None,:] + offset[None,:]
    # orad[image_band>maxDN]=0.
    return orad.astype(np.float32)

import pandas as pd
def load_cal_df():
    fcsv ='<WORK_ROOT>/myPy/bluebon/calib/FM1_mean_output_PRNU_check.csv'
    #read csv
    df = pd.read_csv(fcsv)
    return df
import rasterio
def read_raster_tif(ftif):
    with rasterio.open(ftif) as src:
        data = src.read()  # shape: (bands, rows, cols)
        profile = src.profile  # metadata like crs, transform, dtype
    return data, profile   

def get_df_inband_mean():
    finband = '<WORK_ROOT>/myPy/bluebon/calib/in-band_radiance.csv'
    df = pd.read_csv(finband, index_col=0)
    # len(df)/20=55 repeated measurements
    df.columns.to_list() #['PAN', 'MS1', 'MS2', 'MS3', 'MS4', 'MS5', 'MS6', 'MS7']
    
    df_out= pd.DataFrame()
    df_out['lmap_level']=[_ for _ in range(1,21)]
    for column in df.columns.to_list():
        ave=[]
        for i in range(20):
            si=i*55
            ei=(i+1)*55
            data=df[column].values[si:ei]
            # print(np.mean(data))
            ave.append(np.mean(data))
        # print(ave)
        df_out[column]=np.sort(ave).tolist()
        
    return df_out

import sys
sys.path.append('./../../tools')
from genrgb import gen_rgb
if __name__=='__main__':
    indir='<WORK_ROOT>/Downloads/bluebon/250626_Chesapeake'; nb=8
    keystr='250626_161648'
    ib=0
    fband_array=[indir+f'/{keystr}_{ib}_gray.tiff' for ib in range(0,nb)]
    ftif = fband_array[ib]
    image_band0, profile1 = read_raster_tif(ftif)
    image_band0=np.squeeze(image_band0)
    image_band=image_band0[:,::-1]
    print(image_band[500,500])
    limits=None
    _=gen_rgb(image_band, ofilepath=indir+f'/{keystr}_before', limits=limits)
    df = load_cal_df()
    param={'band':'MS1','L_rate':666, 'TDI':4}
    orad0 = calibrate_bb_band(image_band0, param, df)
    print(orad0.dtype)
    orad=np.squeeze(orad0)[:,::-1]
    print(orad[500,500])
    limits = None#[[700.,1800],[1000.,2200],[1500.,3500]]
    _=gen_rgb(orad, ofilepath=indir+f'/{keystr}_after', limits=limits)
  
  