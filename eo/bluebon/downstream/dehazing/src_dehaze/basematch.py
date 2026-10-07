#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Oct 28 15:38:40 2025

@author: yp
"""

import numpy as np
import basematch_sub as BS

# import basematch_2u
import baseu as BU
# import baseu_bb4b_rhot_251022_TakhliAP as BU
import re
import box_average2 as BA
import sys
sys.path.append('./../../tools')
import ncutils, tiffutils
from genrgb import gen_rgb
import gen_png_simple as GPS
from PIL import Image
if __name__ == "__main__":
    # fnc = '/home/yp/Downloads/bluebon/251022_TakhliAP/myout/251022_042629_stacked_rhorc.nc'; sensor='bb'
    # fnc = '/home/yp/Downloads/bluebon/250928_Thai_KKairport/myout/250928_041857_stacked_rhorc.nc'; sensor='bb'
    # fnc = '/home/yp/Downloads/bluebon/250903_Namhae/myout/250903_023532_stacked_rhorc.nc'
    # fnc='/home/yp/Downloads/bluebon/250629_Andong/myout/250629_023708_stacked_rhot.nc'
    # fnc = '/home/yp/Downloads/bluebon/251030_Seorak/myout/251030_024535_stacked_rhot.nc'; sensor='bb'
    # fnc = '/home/yp/Downloads/bluebon/250712_Seoul/myout/250712_024621_stacked_rhot.nc' #tdi[bd8]
    # fnc = '/home/yp/Downloads/bluebon/250903_Namhae/myout/250903_023532_stacked_npz_rhot.nc'
    # fnc = '/home/yp/Downloads/bluebon/250821_Busan/myout/250821_023741_stacked0_rhot.nc'
    # fnc='/home/yp/Downloads/bluebon/250806_SoffSydney/myout/250806_002855_stacked0_rhot.nc'; sensor='bb'
    # fnc='/home/yp/Downloads/bluebon/251022_TakhliAP_msi/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m';
    # fnc='/home/yp/Downloads/bluebon/251022_TakhliAP_msi/myout_sr/MSI_ressr_rhorc.tif'; sensor='msi_20m';
    # fnc='/media/yp/T7_msi/msidata/20250324_T52SDF_smoke/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m';
    # fnc='/media/yp/T7_msi/msidata/20200820_BT52SCD_Yeosu/myout/MSI_res20_rhorc.nc'; sensor='msi_20m';
    # fnc='/media/yp/T7_msi/msidata/20210607_T51STU_Qingdao_6h1B/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m';
    
    # fnc='/home/yp/Downloads/bluebon/250903_Namhae_msi_T52SCD/myout/MSI_res20m_rhot.nc'; sensor='msi_20m' #glint-corr test
    
    # # fnc='/home/yp/Downloads/bluebon/250926_Khovsgol/myout/250926_045459_stacked_rhot.nc'; sensor='bb'
    # fnc='/home/yp/Downloads/bluebon/251022_TakhliAP/myout/251022_042629_stacked_rhot.nc'; sensor='bb' 
    # fnc='/home/yp/Downloads/bluebon/251022_TakhliAP/myout/251022_042629_stacked_rhot_RGB210.png'; sensor='rgb'
    # # fnc='/home/yp/Downloads/bluebon/251109_BanNongYaKaew/myout/251119_041834_stacked_rhorc.nc'; sensor='bb'
    # # fnc='/home/yp/Downloads/bluebon/251123_Thai/myout/251123_041547_stacked_rhot.nc'; sensor='bb'
    # # fnc='/home/yp/Downloads/bluebon/251127_Thai/myout/251127_041230_stacked_rhorc.nc'; sensor='bb'
    # fnc='/home/yp/Downloads/bluebon/260209_Suwon/myout/260209_025928_stacked_rhot.nc'; sensor='bb'; 
    # # fnc='/home/yp/Downloads/bluebon/260215_msi_T52SCG_dehazingtest/myout/MSI_res20m_rhot.nc'; sensor='msi_20m'
    
    # fnc = '/home/yp/Downloads/bluebon/260322_msi_T52SCG_Suwon/myout/MSI_res20m_rhot.nc'; sensor='msi_20m'
    # fnc='/home/yp/Downloads/bluebon/260320_LC09_116034_Suwon/OLI_rhot.nc'; sensor='oli'
    # fnc='/home/yp/Downloads/bluebon/260304_LC09_116034_GG/OLI_rhorc.nc'; sensor='oli'
    # fnc='/media/yp/T7_win31/olidata/20240313_117037_WoffJeju/OLI_rhorc.nc'; sensor='oli'
    
    # fnc='/home/yp/Downloads/bluebon/250821_Busan_msi_T52SDD/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m'
    # fnc='/media/yp/T7_win31/olidata/20250728_119035_Qingdao/OLI_rhorc.nc'; sensor='oli'
    # fnc='/home/yp/Downloads/bluebon/250903_Geoje_oli_114036/OLI_rhorc.nc'; sensor='oli'
    # fnc='/home/yp/Downloads/bluebon/260413_Kuwait/myout/260413_081143_stacked_rhot.nc'; sensor='bb' #Fail
    fnc='/media/yp/T7_msi/msidata/20260330_T38RQT_dehTest/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m'
    
    if '.nc' in fnc:
        img0 = ncutils.getimage(fnc, bip=False)
    elif '.tif' in fnc:
        img0 = tiffutils.getraster(fnc, None)
    elif fnc.endswith(('png','jpg')):
        _data = Image.open(fnc)
        img0 = np.transpose(np.array(_data),[2,0,1])[0:3]/255.

    nb,nrows,ncols = img0.shape
    
    if 'bb' in sensor:
            
        # # bases, u0 = BU.set_basis_u(bds)
        # if 'rhorc' in fnc:
        #     bases, u0 = BU.basis_u_bb4b_rhorc()
        # else:
        #     bases, u0 = BU.basis_u_bb4b_rhot()

        

        #u=[1.1,1.0,0.9,0.9] #no good
        # u=[1. for _ in range(nb) ]#[1.,1.,1.,1.]
        # if nb==8: #use 4bands out of 8bands
        #     bds=[0,1,3,7];
        #     img = img0[bds,:,:] #use 4 bands
        # else: #use all band 4 or 7
        #     img = img0
        
        # bases, u_prm = BU.basis_u_bb8b_rhot()
        bases, u_prm, u0 = BU.basis_u_bb8b_rhot_260413_Kuwait() #Fail
        u0=np.ones((nb), dtype=np.float32)#[1.,1.,1.,1.]
        #8 -> 4
        bds = [0,1,3,4,5,6,7]
        u=u0[bds]        
        bases=bases[:,bds]
        img = img0[bds,:,:]
        bds_rgb=[3,1,0]
        
        # add_spec=np.array([0.32,0.16,0.08,0.04,0.02,0.01,0.005,0.])[bds]
        # bases = bases +add_spec[None,:]
        # img = img + add_spec[:,None,None]
        
    elif 'msi_20m' in sensor:
        bds=[0,1,2,7]
        # bds=[0,1,2,5,7,8]
        # bds=[0,1,2,7,9]
        # bds=[_ for _ in range(10)]
        if 'rhorc' in fnc:
            # bases0, u0 = BU.basis_u_msi20m_rhorc()
            # bases0,u_prm,u0=BU.basis_u_msi20m_rhorc_glint()
            bases0,u_prm,u0=BU.basis_u_msi20m_rhorc_Kuwait()
        else:
            # bases0, u0 = BU.basis_u_msi20m_rhot_260215()
            bases0, u_prm=BU.basis_u_msi20m_rhot_260322()
            # bases0, u0 = BU.basis_u_msi20m_rhot_glint()
            
        # u0=u_prm['a']*0.03+u_prm['b']
        # u0=u0/u0[0]
        bases = bases0[:,bds]
        u=u0[bds]
        img = img0[bds,:,:]
        bds_rgb=[2,1,0]
        
        # add_spec=[_*0.1 for _ in range(10)]
        # add_spec.reverse()
        # add_spec=np.array(add_spec)[bds]
        # bases = bases +add_spec[None,:]
        # img = img + add_spec[:,None,None]
        
    elif 'oli' in sensor:
        bds=[_ for _ in range(7)]
        # bds=[1,2,3]#[1,2,3,4]
        # bases0, u_prm = BU.basis_u_oli_rhorc_260304()#260320()
        # bases0, u_prm, u0=BU.basis_u_oli_rhorc_240313_117037_Ocean()
        # bases0, u_prm, u0=BU.basis_u_oli_rhorc_250728_119035_glintTest()
        bases0, u_prm, u0=BU.basis_u_oli_rhorc_250903_114036_hazeglint()

        bases = bases0[:,bds]
        u=u0[bds]
        img = img0[bds,:,:]
        bds_rgb=[3,2,0]
        
    elif 'rgb' in sensor: #No sense -> No more try
        bds=[0,1,2]
        bases, u_prm = BU.basis_u_rgb_rhot()
        u0=u_prm['a']*0.03+u_prm['b']
        u0=u0/u0[0]
        u=u0[bds]
        img = img0[bds,:,:]
        bds_rgb=[0,1,2]

    print(f'# of base vectors={len(bases)}')
    
    
    # img_s = downsample_mean_chw(img,fx=5,fy=5)
    
    fnc_base=re.sub(r'(?<!^)\.([^./\\:]*$)', '',fnc)
    fnc_deh_base = re.sub(r'_[^_]*$', '_dehSpec', fnc_base, count=1)
    fnc_aero_base = re.sub(r'_[^_]*$', '_aeroSpec', fnc_base, count=1)
    

    # # best_k, c_star, score=match_4band_image(img, bases)
    # best_basis, best_c, best_score = match_4band_image_topk(img, bases, topk=3)
    # c_star=np.mean(best_c, axis=0)
    
    u_img0 = np.broadcast_to(u0[:, None, None], (nb, nrows, ncols))
    u_img = np.broadcast_to(u[:, None, None], (len(bds), nrows, ncols))
    if 1:
        topk=3
        # best_basis, alpha_star, score = BS.match_image_templateu_topk(img, bases, u, topk=topk)
        # best_basis, alpha_star, score = BS.match_image_templateu_topk_nnalpha(img, bases, u, topk=topk)
        # best_basis, alpha_star, best_dist2=BS.match_image_linear_bias_fast(img, bases, u, topk=topk)
        # best_basis, alpha_star, best_dist2 = BS.match_image_linear_bias_nnalpha(img, bases, u, topk=topk)
        # best_basis, alpha_star, best_dist2 = BS.match_image_linear_bias_fast_tiled(img, bases, u, topk=topk) #tiled version
        best_basis, alpha_star, best_dist2 = BS.match_image_linear_bias_nnalpha_tiled(img, bases, u_img, topk=topk) #tiled version
        # best_basis, alpha_star, best_dist2=basematch_2u.match_image_two_templates_nnalpha_topk(img, bases, u, topk=topk)
        
        weights=np.ones(topk)
        c_star=np.average(alpha_star, axis=0, weights=weights)
    
    
    if 0: #iterate
        idx = c_star<0.01
        c_star[idx]=0.01
        idx = c_star>0.2
        c_star[idx]=0.2
        u_img0=np.zeros_like(img0)
        # for i, ib in enumerate(bds):
        for ib in range(nb):
            u_img0[ib,:,:] = u_prm['a'][ib]*c_star+u_prm['b'][ib]
        
        u_img_b0=u_img0[0,:,:].copy()
        # Option B: vectorized (no loop needed)
        with np.errstate(invalid='ignore', divide='ignore'):
            safe = u_img_b0 != 0                             # (R, C) mask
            u_img0 = np.where(safe[None, :, :],
                              u_img0 / u_img_b0[None, :, :],  0.0)
            
        u_img=u_img0[bds,:,:]
        img = img0[bds,:,:]
        best_basis, alpha_star, best_dist2 = BS.match_image_linear_bias_nnalpha_tiled(img, bases, u_img, topk=topk) #tiled version
        c_star=np.average(alpha_star, axis=0, weights=weights)
    
    _=GPS.gen_png_simple(c_star, None, fnc_base+'_cstar0',linear=1)#,vrange=[-0.1,1])
    
    rhos1=img0[0]-c_star
    # c_star=c_star*(1.-rhos1*rhos1)
    c_star=c_star*(1.-rhos1)
    #2nd iteration
    rhos1=img0[0]-c_star
    c_star=c_star*(1.-rhos1)
    # if 'bb' in sensor:
    #     c_star=c_star*1.5
    
    thresh=0.5
    maskvalid=c_star<thresh #0.1#0.20#0.15#0.1,0.3#0.5; 
    mask=~maskvalid #c_star>=0.3
    if 0: #spatial average
        bxsize=5
        if 'msi_20m' in sensor: bxsize=5  
        if 'oli' in sensor: bxsize=5
        ave,perc=BA.wrap_boxaverage(c_star, maskvalid, bxsize, 5) #50
    else: #no aeerage
        ave=c_star
    ave[mask]=np.nan; 
    ave=BA.fill_nearest(ave)
    # ave[1]=BA.fill_nearest(ave[1])
    # _=gen_rgb(ave, None, linear=None, ofilepath=fnc_deh_base+'_aero')
    _=GPS.gen_png_simple(ave, None, fnc_deh_base+'_cstar',linear=1)#,vrange=[0.0,0.5])
    
    if 1: #for 
        aer = np.array([ave[:,:]*_ for _ in u0])
    else:
        aer = ave[None,:,:]*u_img0
    
    if '.nc' in fnc:
        header=ncutils.readheader(fnc); waves=header['waves']
    elif '.tif' in fnc:
        waves=tiffutils.get_waves_tif(fnc)
    elif fnc.endswith(('jpg','png')):
            waves = None; #['R','G','B']
    ncutils.writeSpecData2file_2nc(aer, fnc_aero_base+'.nc', waves=waves, slope=1./65535, offset=-0.1)
    
    _mask=aer[0]>thresh#0.10#0.15 #None
    _mask=None
    _=gen_rgb(aer, mask=_mask, linear=1, ofilepath=fnc_aero_base, bds=bds_rgb, data4alpha=img0[0,:,:])
    
    _=gen_rgb(img0-aer, mask=_mask, linear=0, ofilepath=fnc_deh_base,bds=bds_rgb, data4alpha=img0[0,:,:])

    ncutils.writeSpecData2file_2nc(img0-aer, fnc_deh_base+'.nc', waves=waves, slope=1./65535, offset=-0.1)
    _=gen_rgb(img0[:,:,:], mask=_mask, linear=1, ofilepath=fnc_base+'_ori',bds=bds_rgb, data4alpha=img0[0,:,:])




