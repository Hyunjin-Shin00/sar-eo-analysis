#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jul  7 15:05:36 2025

@author: yp
"""
from openpyxl import load_workbook
import pandas as pd
import matplotlib.pyplot as plt


fxlsx = '/home/yp/myPy/bluebon/calib/FM1_mean_output_PRNU_check.xlsx'
fcsv ='/home/yp/myPy/bluebon/calib/FM1_mean_output_PRNU_check.csv'

if 0: #to save as csv - slow
    wb = load_workbook(fxlsx, read_only=True)
    ws = wb['FM1_mean_output']  # or wb.active
    
    data = ws.values
    columns = next(data)  # first row is header
    df = pd.DataFrame(data, columns=columns)
    wb.close()
    df.to_csv(fcsv, index=False)
#read csv
df = pd.read_csv(fcsv) #this fast


column_names = df.columns.tolist()
print("Column names:", column_names)

from itertools import cycle
import numpy as np
from scipy.stats import linregress
import calib
dfrad = calib.get_df_inband_mean()
_bds =['PAN']+[f'MS{_}' for _ in range(1,8)]
_max=[17500,9500,9500,13200,7350,8000,11000,32000]
maxRad_dict=dict(zip(_bds, _max))
if 1: #graph showing variation over TDI
    # TDI=1,2,4,8,16
    band='MS6'
    l_rate=666
    pix='1000'
    title=f'{band} L_rate:{l_rate} pix:{pix}'
    df1 = df[ (df['BAND'] == band) &
        (df['Line rate'] == l_rate)]
    
    fig, ax = plt.subplots(dpi=100)
    # cols=['Radiant intensity','lmap_level',0]
    marker_list = ['o', 's', '^', 'v', '*', 'D', 'x', '+', 'h', 'p']
    marker_cycle = cycle(marker_list)
    color_list = plt.cm.tab10.colors
    color_cycle = cycle(color_list)
    for tdi in [1,2,4,8,16]:
        df2=df1[(df1['TDI'] == tdi)]
        rad=[]
        DN=[]
        for lmap_level in range(21):
            _df = df2[df2['lmap_level'] == lmap_level]
            # rad.append(_df['Radiant intensity'].values[0])
            DN.append(_df[pix].values[0])
            
        # print(rad)
        print(DN)
    
        rad=[0.]+dfrad[band].values.tolist()
        idx = np.array(DN)<4000
        idx2=np.array(rad)<maxRad_dict[band]
        x=np.array(DN)[idx & idx2]; y= np.array(rad)[idx & idx2]
        # DN1=np.array(DN)[idx]; rad1=np.array(rad)[idx]
        # idx2=np.array(rad1)<maxRad_dict[band]
        # x=np.array(DN1)[idx2]; y=np.array(rad1)[idx2]
        
        if 1:
            m, b, r_value, p_value, std_err = linregress(x, y)
            x_line = np.linspace(min(x), max(x), 100)
            y_line = m * x_line + b
            rsq=r_value*r_value
            label=f'TDI={tdi}: y={m:.3f}x+{b:.3f} (r2={rsq:.3f})'
        else: #log-log
            x1=x-x[0]
            a,b,c=np.polyfit(x1,y,2)
            x_line = np.linspace(min(x), max(x), 100)
            y_line=np.polyval([a,b,c],x_line-x[0])
            y_pred=np.polyval([a,b,c],x-x[0])
            rsq=1-np.sum((y-y_pred)**2)/np.sum((y-np.mean(y))**2)
            label=f'TDI={tdi}:y = {a:.4f}x^2 + {b:.4f}x + {c:.4f} (r2={rsq:.3f})'
        

        marker = next(marker_cycle)
        color = next(color_cycle)
        sc=ax.scatter(x, y, marker=marker,color=color, facecolors='none',label=label)#, label=f'band_{ib}')
        ax.plot(x_line, y_line, color=sc.get_edgecolor())
        
        # plt.plot(x,y,'-o', label=f'TDI={tdi}'); #plt.xscale('log')
    
    plt.legend()
    plt.xlabel('DN')
    plt.ylabel('radiance')
    plt.title(title)
    plt.tight_layout()

if 1: #graph showing variation over pix positions
    band='MS6'
    l_rate=666
    tdi=4   
    title=f'{band} L_rate:{l_rate} TDI:{tdi}' 
    df1 = df[ (df['BAND'] == band) &
        (df['Line rate'] == l_rate)]
    df2=df1[(df1['TDI'] == tdi)]
    plt.figure()
    marker_list = ['o', 's', '^', 'v', '*', 'D', 'x', '+', 'h', 'p']
    marker_cycle = cycle(marker_list)
    color_list = plt.cm.tab10.colors
    color_cycle = cycle(color_list)
    for pix in [f'{_}' for _ in [0, 100, 1000, 2000, 3000, 4000, 4095]]:
        rad=[]
        DN=[]
        for lmap_level in range(21):
            _df = df2[df2['lmap_level'] == lmap_level]
            # rad.append(_df['Radiant intensity'].values[0])
            DN.append(_df[pix].values[0])
            
        # print(rad)
        print(DN)
    
        rad=[0.]+dfrad[band].values.tolist()
        idx = np.array(DN)<4000
        idx2=np.array(rad)<maxRad_dict[band]
        x=np.array(DN)[idx & idx2]; y= np.array(rad)[idx & idx2]
        
        marker = next(marker_cycle)
        color = next(color_cycle)
        plt.plot(x,y,marker,linestyle='-',color=color,mfc='none', label=f'x={pix}'); #plt.xscale('log')    
    
    plt.legend()
    plt.xlabel('DN')
    plt.ylabel('radiance')
    plt.title(title)
    plt.tight_layout()
    
"""
---Stratege calibration
for loop over band:
    param_band = dict {band:, L_rate:, TDI: } from pdf 
    df1 = df[ (df['BAND'] == band) & (df['Line rate'] == l_rate)]
    df2 = df1[(df1['TDI'] == tdi)]
    for loop over pixel(column):
        extract (rad vs DN) relationship
        convert DN to rad (calibrate pixel) 
"""