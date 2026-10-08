#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep  9 15:27:07 2025

@author: yp
"""
import numpy as np
import sys
sys.path.append(r'./../../tools')
import gen_png_simple as GPS
import ncutils, tiffutils

import flagging_bb

def base_subtraction(rhorc, waves,base_bds, o_bd, relband=None):
    # #bb = (0)483.2, (1)562.4, (2)664.6, (3)704.8, (4)739.2, (5)781.9, (6)836.6]
    bd1,bd2=base_bds
    wave1=waves[bd1]
    wave2=waves[bd2]
    owave=waves[o_bd]

    baseline=(rhorc[:,:,bd1]-rhorc[:,:,bd2])/(wave1-wave2)*(owave-wave2)+rhorc[:,:,bd2]
    ret = rhorc[:,:,o_bd] - baseline
    if relband:
        ret = ret/rhorc[:,:,relband]
    return ret

def rededge_chl_index(rhorc, waves):
    base_bds=[2,4]
    o_bd1=3;  
    return base_subtraction(rhorc, waves,base_bds, o_bd1)


if 0:#__name__=="__main__":
    # frhorc='<WORK_ROOT>/Downloads/bluebon/250903_Namhae/myout/250903_023532_stacked_warped_rhorc.tif'
    frhorc='<WORK_ROOT>/Downloads/bluebon/250821_Busan/myout/250821_023741_stacked_warped_rhorc.tif'
    ofbase=frhorc.replace('_rhorc.tif','')
    
    rhorc = tiffutils.getraster(frhorc, None)
    rhorc = np.transpose(rhorc,(1,2,0))
    nlin, npix, nb =rhorc.shape
    waves=tiffutils.get_waves_tif(frhorc)
    
    flag, _flagarr = flagging_bb.flagging(rhorc)
    
    hRE  = rededge_chl_index(rhorc, waves)
    
    
    ofilepath=ofbase+'_hRE'
    vrange=[0.000,0.020]
    GPS.gen_png_simple(hRE, flag, ofilepath, vrange=vrange, linear=1, coastline=None )
    
    hRE[flag !=0]=0.
    hRE[hRE<0.]=0.
    tiffutils.write2geotiff(frhorc, hRE, ofilepath+'.tif', ulji=None,waves=None, scale=None, offset=None)

import landpolygon
if 0:#__name__=="__main__":
    frhorc='<WORK_ROOT>/Downloads/bluebon/250903_Namhae/myout/250903_023532_stacked_warped_rhorc.tif'
    ofbase=frhorc.replace('_rhorc.tif','')
    
    fshp='../../coastline/land-polygons-complete-4326/land_polygons.shp'
    landmask = landpolygon.get_landmask(frhorc,fshp)
    
    rhorc = tiffutils.getraster(frhorc, None)
    rhorc = np.transpose(rhorc,(1,2,0))
    nlin, npix, nb =rhorc.shape
    
    flag, _flagarr = flagging_bb.flagging(rhorc,flag_in=landmask)
    ofilepath=ofbase+'_mask'
    flag[flag!=0]=1
    tiffutils.write2geotiff(frhorc, flag, ofilepath+'.tif', ulji=None,waves=None, scale=None, offset=None)
    
if 0:#__name__=="__main__":
    import rasterio as rio
    frhorc='<WORK_ROOT>/Downloads/bluebon/250903_Namhae/myout/250903_023532_stacked_warped_rhorc.tif'
    arr = tiffutils.getraster(frhorc, None)
    ofbase=frhorc.replace('_rhorc.tif','_rhorc')
    with rio.open(frhorc) as ref:
        height, width = arr.shape[1], arr.shape[2]
        prof = ref.profile.copy()
        prof.update(count=1, height=height, width=width, dtype=arr.dtype)
    
        for i in range(arr.shape[0]):
            out_path = f"{ofbase}_bandidx_{i+1:02d}.tif"
            with rio.open(out_path, "w", **prof) as dst:
                dst.write(arr[i], 1)