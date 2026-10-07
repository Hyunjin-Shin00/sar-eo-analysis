#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Sep  4 15:13:08 2025

@author: yp
"""

import calib

df = calib.load_cal_df()

tdi_arr=[1,4,8,8,16,16,16,4]
nb=len(tdi_arr)

bd_names=['PAN']+[f'MS{ib}' for ib in range(1, nb)]
cal_prms = [{'band':bd_names[ib], 'L_rate':666, 'TDI':tdi_arr[ib]} for ib in range(0,nb)]

dark_DN=[]
for ib in range(nb):
    param = cal_prms[ib]
    band=param['band']
    l_rate=param['L_rate']
    tdi = param['TDI']
    
    # T_rad=[0.]+dfrad[band].values.tolist()
    _bds =['PAN']+[f'MS{_}' for _ in range(1,8)]
    # _max=[17500,9500,9500,13200,7350,8000,11000,32000]
    # maxRad_dict=dict(zip(_bds, _max))
    
    df1 = df[ (df['BAND'] == band) & (df['Line rate'] == l_rate)]
    df2=df1[(df1['TDI'] == tdi)]
    
    lmap_level=0
    _df = df2[df2['lmap_level'] == lmap_level]
    _dn=[_df[f'{icol}'].values[0] for icol in range(4096)] 
    dark_DN.append(_dn)

import matplotlib.pyplot as plt    
for ib in range(nb):
    plt.plot(dark_DN[ib], alpha=0.5, label=f'{bd_names[ib]} TDI:{tdi_arr[ib]}')
plt.xlabel('Cross-track pixel no')
plt.ylabel('DN')
plt.title('DN for light level=0')
plt.legend()