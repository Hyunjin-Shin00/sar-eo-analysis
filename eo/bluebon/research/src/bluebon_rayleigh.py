#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Jul 13 21:07:32 2025

@author: yp
"""
import numpy as np
import rayleigh_bluebon
def satang_fr_inclination(roll, desc=True):    
    incl=97.4282 #inclination counterclockwise w.r.t +x axis for ascending
    if desc: #from mission
        incl=360-incl
    # roll = -5.648 #from mission
    satazi = incl-90 if roll>0. else incl+90 
    satazi = 90-satazi #clockwise from +yaxis
    if satazi<-180:
        satazi += 360.
    satzen = abs(roll)    
    return satzen, satazi

import pvlib
def compute_solang(time, lons, lats):
    if not isinstance(lons, np.ndarray):
        lons=np.array(lons); 
        lats=np.array(lats)
    zenith_list=[]
    azimuth_list=[]
    for la, lo in zip(lats.ravel(),lons.ravel()):
        solar_pos = pvlib.solarposition.get_solarposition(time, la, lo)
        zenith_list.append(solar_pos['zenith'].values[0])
        azimuth_list.append(solar_pos['azimuth'].values[0])

    # Reshape back to original shape
    zenith = np.array(zenith_list).reshape(lats.shape)
    azimuth = np.array(azimuth_list).reshape(lats.shape)
    
    return zenith, azimuth

def azimuth_fix(azi):
    if azi<0:
        azi=-azi
    azi=azi%360.
    if azi>180.:
        azi=360.-azi
    return azi
def get_rayleigh(time, lon, lat, roll, desc=True):
    solz, sola = compute_solang(time, [lon], [lat])
    solz=solz[0]; sola=sola[0]
    senz, sena = satang_fr_inclination(roll, desc=desc)
    print('solz,sola,senz,sena:',solz, sola, senz, sena)
    rela = azimuth_fix(sola-sena)
    th0arr=np.array([solz]); tharr=np.array([senz]); phiarr=np.array([rela])
    rho_r=rayleigh_bluebon.get_rayleigh_1D(th0arr, tharr, phiarr)
    return rho_r

import pandas as pd
if __name__=='__main__':
    roll=-5.648 #from mission
    timestr = '2025-06-29T02:37:12Z'
    time=pd.Timestamp(timestr)
    cen_lon, cen_lat = [128.8, 36.58]
    r=get_rayleigh(time, cen_lon, cen_lat, roll)
    print(np.squeeze(r))
