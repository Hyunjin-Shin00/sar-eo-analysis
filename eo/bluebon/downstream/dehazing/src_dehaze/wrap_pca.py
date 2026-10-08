#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Nov  9 00:48:11 2025

@author: yp
"""
import pca, pcaX   
import numpy as np
import re
import box_average2 as BA
import sys
sys.path.append('./../../tools')
import ncutils
from genrgb import gen_rgb
import gen_png_simple as GPS
if __name__ == "__main__":
    # fnc = '<WORK_ROOT>/Downloads/bluebon/251022_TakhliAP/myout/251022_042629_stacked_rhot.nc'; sensor='bb'
    # fnc = '<WORK_ROOT>/Downloads/bluebon/250928_Thai_KKairport/myout/250928_041857_stacked_rhot.nc'
    # fnc = '<WORK_ROOT>/Downloads/bluebon/250903_Namhae/myout/250903_023532_stacked_rhorc.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/250629_Andong/myout/250629_023708_stacked_rhot.nc'
    # fnc = '<WORK_ROOT>/Downloads/bluebon/251030_Seorak/myout/251030_024535_stacked_rhot.nc'; sensor='bb'
    # fnc = '<WORK_ROOT>/Downloads/bluebon/250712_Seoul/myout/250712_024621_stacked_rhot.nc' #tdi[bd8]
    # fnc = '<WORK_ROOT>/Downloads/bluebon/250903_Namhae/myout/250903_023532_stacked_npz_rhot.nc'
    # fnc = '<WORK_ROOT>/Downloads/bluebon/250821_Busan/myout/250821_023741_stacked0_rhot.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/250806_SoffSydney/myout/250806_002855_stacked0_rhot.nc'; sensor='bb'
    fnc='<WORK_ROOT>/Downloads/bluebon/251022_TakhliAP_msi/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m';
    
    # fnc='<WORK_ROOT>/Downloads/bluebon/250926_Khovsgol/myout/250926_045459_stacked_rhot.nc'; sensor='bb'
    
    img0 = ncutils.getimage(fnc, bip=False)
    nb,nrows,ncols = img0.shape
    
    if 'bb' in sensor:
        bds=[0,1,3,7];
        X0=pcaX.dataX() #need to update
        #u=[1.1,1.0,0.9,0.9] #no good
        # u=[1. for _ in range(nb) ]#[1.,1.,1.,1.]
        if nb==8:
            img = img0[bds,:,:] #use 4 bands
    elif 'msi_20m' in sensor:
        bds=[_ for _ in range(nb)] #[0,1,2,7]
        if 'rhorc' in fnc:
            X0=pcaX.dataX()
        else: #need to update
            X0=pcaX.dataX()
        
        img = img0[bds,:,:]

    
    X=np.array(X0)[:,bds]
    res = pca.pca_svd(X)
    PCs = res["components_"]                     # (d, 5)
    pca.plot_pc_loadings(PCs, pcs=[1,2,3,4], title="Top-3 PC Loadings")
    
    # img_s = downsample_mean_chw(img,fx=5,fy=5)
    
    fnc_base=re.sub(r'(?<!^)\.([^./\\:]*$)', '',fnc)
    fnc_deh_base = re.sub(r'_[^_]*$', '_dehSpec', fnc_base, count=1)
    fnc_aero_base = re.sub(r'_[^_]*$', '_aeroSpec', fnc_base, count=1)
    
    pc_idx=0
    pc1_map = pca.project_one_pc_grid(img, res, pc_index=pc_idx) 
    
    _=GPS.gen_png_simple(pc1_map, None, fnc_base+'_pc1',linear=1)#,vrange=[-0.1,1])
    
    maskvalid=(pc1_map<0.5)# & (pc1_map>0.0)#0.3; 
    mask=~maskvalid #c_star>=0.3
    if 0: #average
        bxsize=20 if 'msi_20m' in sensor else 50
        ave,perc=BA.wrap_boxaverage(pc1_map, maskvalid, bxsize, 5) #50
    else: #no aeerage
        ave=pc1_map
    ave[mask]=np.nan; ave=BA.fill_nearest(ave)

    
    aer = np.array([ave[:,:]*_ for _ in PCs[:,pc_idx]])
    # header=ncutils.readheader(fnc); waves=header['waves']
    # ncutils.writeSpecData2file_2nc(aer, fnc_aero_base+'.nc', waves=waves, slope=1./65535, offset=0.)
    
    _mask=None#aer[1]>0.15
    _=gen_rgb(aer, mask=_mask, linear=1, ofilepath=fnc_aero_base, bds=[2,1,0])
    
    _=gen_rgb(img-aer, mask=_mask, linear=1, ofilepath=fnc_deh_base,bds=[2,1,0])
    # ncutils.writeSpecData2file_2nc(img0-aer, fnc_deh_base+'.nc', waves=waves, slope=1./65535, offset=0.)
    # _=gen_rgb(img[:,:,:], mask=_mask, linear=1, ofilepath=fnc_base+'_ori',bds=[2,1,0])