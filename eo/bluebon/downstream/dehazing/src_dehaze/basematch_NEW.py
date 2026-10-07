#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Oct 28 15:38:40 2025

@author: yp
"""
from scipy.ndimage import zoom

def upsample_to_shape(img_down, target_shape):
    """
    Upsample to an exact target shape (nb, nl, ns).
    Useful when original was cropped before downsampling.
    """
    nb, nl_target, ns_target = target_shape
    nb, nl_down, ns_down = img_down.shape
    factors = (1, nl_target / nl_down, ns_target / ns_down)
    return zoom(img_down, zoom=factors, order=1)

import numpy as np
import basematch_sub_NEW as BSNEW

# import basematch_2u
import baseu_NEW as BUNEW
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
    fin='/home/yp/Downloads/bluebon/260220_Suwon/myout/260220_025632_stacked_rhot.nc'; sensor='bb'; 
    # # fnc='/home/yp/Downloads/bluebon/260215_msi_T52SCG_dehazingtest/myout/MSI_res20m_rhot.nc'; sensor='msi_20m'
    
    # fnc = '/home/yp/Downloads/bluebon/260322_msi_T52SCG_Suwon/myout/MSI_res20m_rhot.nc'; sensor='msi_20m'
    # fnc='/home/yp/Downloads/bluebon/260320_LC09_116034_Suwon/OLI_rhot.nc'; sensor='oli'
    # fnc='/home/yp/Downloads/bluebon/260304_LC09_116034_GG/OLI_rhorc.nc'; sensor='oli'
    # fnc='/media/yp/T7_win31/olidata/20240313_117037_WoffJeju/OLI_rhorc.nc'; sensor='oli'
    
    # fnc='/home/yp/Downloads/bluebon/250821_Busan_msi_T52SDD/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m'
    # fnc='/media/yp/T7_win31/olidata/20250728_119035_Qingdao/OLI_rhorc.nc'; sensor='oli'
    # fnc='/home/yp/Downloads/bluebon/250903_Geoje_oli_114036/OLI_rhorc.nc'; sensor='oli'
    # fnc='/home/yp/Downloads/bluebon/260413_Kuwait/myout/260413_081143_stacked_rhot.nc'; sensor='bb' #Fail
    # fnc='/media/yp/T7_msi/msidata/20260330_T38RQT_dehTest/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m'
    # fnc='/media/yp/T7_msi/msidata/20240809_T52SCJ_Wonsan1/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m'
    # fnc='/media/yp/T7_msi/msidata/20240809_T52SCJ_Wonsan1/myout/MSI_res10m_rhorc.nc'; sensor='msi_10m'
    fin='/media/yp/T7_msi/msidata/20260401_T51SYD_Pyeongyang/myout/MSI_res10m_rhorc.tif'; sensor='msi_10m'
    # fin='/media/yp/T7_msi/msidata/20260416_T52SCG_Seoul/myout/MSI_res20m_rhorc.nc'; sensor='msi_20m'
    # fin='/home/yp/Downloads/CASdata/C1_20240807014521_18758_01041614_RGBN_rhot.nc'; sensor='cas'
    # fin='/home/yp/Downloads/CASdata/20240823/C1_20240823013448_19001_00858507_RGBN_rhot.nc'; sensor='cas'
    
    fin='/home/yp/Downloads/skydata/SkySatCollect_20250603_004246_ssc13/u0001_myout/20250603_004246_ssc13_u0001_analytic_rhorc.tif'; sensor='skysat'
    # fin='/media/yp/T7_win31/olidata/20260506_116033_Wonsan/OLI_rhorc.nc'; sensor='oli'
    fin='/home/yp/Downloads/CASdata/20250619/C1_20250619012456_23559_00573599_L2G_RGBN_rhot.nc'; sensor='cas'
    fin='/home/yp/Downloads/CASdata/20250619_1/C1_20250619012456_23559_00611431_L2G_RGBN_rhot.nc'; sensor='cas'
    fin='/media/yp/T7_win31/olidata/20250613_116033_Wonsan/OLI_rhorc.nc'; sensor='oli'
    fin='/media/yp/T7_win31/olidata/20250425_165051_Aden/OLI_rhorc.nc'; sensor='oli'
    fin='/media/yp/T7_win31/olidata/20260422_163042_Bahrain/OLI_rhorc.nc'; sensor='oli'
    
    fin='/media/yp/T7_msi/msidata/20260423_T39RVJ_Bahrain/myout/MSI_res10m_rhorc.nc'; sensor='msi_10m'
    
    if '.nc' in fin:
        img0 = ncutils.getimage(fin, bip=False)
    elif '.tif' in fin:
        img0 = tiffutils.getraster(fin, None)
    elif fin.endswith(('png','jpg')):
        _data = Image.open(fin)
        img0 = np.transpose(np.array(_data),[2,0,1])[0:3]/255.

    # nb,nrows,ncols = img0.shape

    
    from skimage.measure import block_reduce
    factor = 3
    img0r = block_reduce(img0,
                            block_size=(1, factor, factor),  # don't reduce band axis
                            func=np.mean)
    nb,nrows,ncols = img0r.shape

    if 'bb' in sensor:
        
        bases, u0 = BUNEW.basis_u_bb8b_rhot()
        # bases, u_prm, u0 = BU.basis_u_bb8b_rhot_260413_Kuwait() #Fail
        # u0=np.ones((nb), dtype=np.float32)#[1.,1.,1.,1.]
        #8 -> 4
        bds = [0,1,3,7];#[0,1,3,4,5,6,7]
        u=u0[bds]        
        bases=bases[:,bds]
        img = img0r[bds,:,:]
        bds_rgb=[3,1,0]
        
        # add_spec=np.array([0.32,0.16,0.08,0.04,0.02,0.01,0.005,0.])[bds]
        # bases = bases +add_spec[None,:]
        # img = img + add_spec[:,None,None]    
    elif 'msi_20m' in sensor:
        bds=[0,1,2,7]
        # bds=[0,1,2,5,7,8]
        # bds=[0,1,2,7,9]
        # bds=[_ for _ in range(10)]
        if 'rhorc' in fin:
            # bases0, u0 = BUNEW.basis_u_NEW_msi20m_rhorc_Kuwait() 
            # bases0, u0 = BUNEW.basis_u_NEW_msi20m_rhorc_240809_Wonsan1()
            # bases0, u0 = BUNEW.basis_u_NEW_msi20m_rhorc_260401_Pyeongyang()
            bases0, u0 = BUNEW.basis_u_msi20m_rhorc_20260423_Bahrain()
        else:
            bases0, u0 =BUNEW.basis_u_msi20m_rhot_260322()    
        #     # bases0, u0 = BU.basis_u_msi20m_rhot_260215()
        #     bases0, u_prm=BU.basis_u_msi20m_rhot_260322()
        #     # bases0, u0 = BU.basis_u_msi20m_rhot_glint()
            
        # u0=u_prm['a']*0.03+u_prm['b']
        # u0=u0/u0[0]
        bases = bases0[:,bds]
        u=u0[bds]
        img = img0r[bds,:,:]
        bds_rgb=[2,1,0]
        
        # add_spec=[_*0.1 for _ in range(10)]
        # add_spec.reverse()
        # add_spec=np.array(add_spec)[bds]
        # bases = bases +add_spec[None,:]
        # img = img + add_spec[:,None,None]

    elif 'msi_10m' in sensor:
        bds=[_ for _ in range(4)]
        bds20to10=[0,1,2,7]
        if 'rhorc' in fin:
            # bases0, u0 = BUNEW.basis_u_NEW_msi20m_rhorc_Kuwait() 
            # bases0, u0 = BUNEW.basis_u_NEW_msi20m_rhorc_240809_Wonsan1()
            bases0, u0 = BUNEW.basis_u_msi20m_rhorc_20260423_Bahrain()
        else:
            bases0, u0 =BUNEW.basis_u_msi20m_rhot_260322()    

        bases0 = bases0[:,bds20to10]
        u0=u0[bds20to10]
        bases=bases0[:,bds]
        u=u0[bds]
        img = img0r[bds,:,:]
        bds_rgb=[2,1,0]
    elif 'oli' in sensor:
        # bds=[_ for _ in range(nb)]
        bds=[0,1,2,3,4]
        bases0, u0 = BUNEW.basis_u_oli_rhorc_20250425_desert()
        bases = bases0[:,bds]
        u=u0[bds]
        img = img0r[bds,:,:]
        bds_rgb=[3,2,1]
    elif 'sky' in sensor:
        bds=[_ for _ in range(nb)]
        bases0, u0 = BUNEW.basis_u_sky_rhorc()
        bases = bases0[:,bds]
        u=u0[bds]
        img = img0r[bds,:,:]
        bds_rgb=[2,1,0]
    elif 'cas' in sensor:
        bds=[_ for _ in range(nb)]
        bases0, u0 = BUNEW.basis_u_cas_rhot_20250619_1()
        bases = bases0[:,bds]
        u=u0[bds]
        img = img0r[bds,:,:]
        bds_rgb=[0,1,2]

    print(f'# of base vectors={len(bases)}')
    
    # img_s = downsample_mean_chw(img,fx=5,fy=5)
    
    fin_base=re.sub(r'(?<!^)\.([^./\\:]*$)', '',fin)
    fin_deh_base = re.sub(r'_[^_]*$', '_dehSpec', fin_base, count=1)
    fin_aero_base = re.sub(r'_[^_]*$', '_aeroSpec', fin_base, count=1)
    

    # # best_k, c_star, score=match_4band_image(img, bases)
    # best_basis, best_c, best_score = match_4band_image_topk(img, bases, topk=3)
    # c_star=np.mean(best_c, axis=0)
    
    u_img0r = np.broadcast_to(u0[:, None, None], (nb, nrows, ncols))
    u_img = np.broadcast_to(u[:, None, None], (len(bds), nrows, ncols))
    if 1:
        topk=3
        
        best_basis, alpha_star, best_dist2 = BSNEW.match_image_linear_bias_nnalpha_tiled(img, bases, u_img, tile_rows=1024,topk=topk) #tiled version
        
        weights=np.ones(topk)
        c_star=np.average(alpha_star, axis=0, weights=weights)
        
        reconR = np.zeros((nb, nrows, ncols), dtype=np.float32)
    
        for i in range(topk):
            # Get the i-th best match data
            idx_i = best_basis[i].astype(np.intp)  # (R, C)
            alpha_i = alpha_star[i]                # (R, C)
            
            for b in range(len(bds)):
                # bases[:, b] gets the b-th band for all 40 basis vectors
                # bases[idx_i, b] creates a (R, C) map of the b-th band spectral values
                basis_val = bases[idx_i, b]
                
                # Handle u (bias) - scalar or pixelwise
                u_val = u[b] if u.ndim == 1 else u[b, :, :]
                
                # Calculate the model for this match/band: (1-alpha)B + alpha*u
                # Add it to the accumulator (averaging on the fly)
                # reconstructed[b] += ((1.0 - alpha_i) * basis_val + alpha_i * u_val) / topk
                reconR[b] +=  basis_val  / topk
    
    c_star = img[0]-reconR[0]; c_star[c_star<0.]=0.
    
        
    if 0: ##equalize c_star for best_basis=> No work
        valid= img[0].ravel() > 1.0e-5
        flat_idx = best_basis[0].ravel()[valid]
        flat_aod = c_star.ravel()[valid]
        n_bases = flat_idx.max() + 1
    
        s = np.bincount(flat_idx, weights=flat_aod, minlength=n_bases)
        c = np.bincount(flat_idx,                   minlength=n_bases)
        aod_per_idx=s / np.maximum(c, 1)
        
        aod_count = np.bincount(flat_idx, minlength=n_bases)
        nonempty  = aod_count > 0
        aod_mean=aod_per_idx[nonempty].mean()
        aod_ratio=np.where(nonempty, aod_per_idx / aod_mean, np.nan)
        
        valid_2d=img[0]>1.e-5
        c_star[valid_2d] *=1-0.3+0.3/aod_ratio[best_basis[0][valid_2d]]
    
    if 'bb' in sensor:
        c_star=c_star*1.2
    
    
    _=GPS.gen_png_simple(c_star, None, fin_base+'_cstar0',linear=1)#,vrange=[-0.1,1])
    
    
    thresh=0.1#0.05#0.15#0.03 for cas
    maskvalid=c_star<thresh #0.1#0.20#0.15#0.1,0.3#0.5; 
    mask=~maskvalid #c_star>=0.3
    if 1: #spatial average
        bxsize=5
        if 'msi_20m' in sensor: bxsize=5  
        if 'oli' in sensor: bxsize=5
        if 'msi_10m' in sensor: bxsize=11  
        if 'sky' in sensor: bxsize=11 
        if 'cas' in sensor: bxsize=11
        
        
        # ave,perc=BA.wrap_boxaverage(c_star, maskvalid, bxsize, 5) #50 crashed for skysat image
        
        # Tune tile_size based on available RAM
        # tile_size=4096 → ~1-2 GB per band, safe for 8 GB RAM
        ave, pct = BA.wrap_boxaverage_tiled(c_star, maskvalid, boxsize=bxsize, q=5,
                                           tile_size=8192, n_workers=4)
        ave=ave.astype(np.float32)
        print(f'ave of c_star has been computed with boxsize={bxsize}')
    else: #no aeerage
        ave=c_star
    ave[mask]=np.nan; 
    ave=BA.fill_nearest(ave)
    _=GPS.gen_png_simple(ave, None, fin_deh_base+'_cstar',linear=1)#,vrange=[0.0,0.5])
    
    if 1: #for 
        aer = np.array([ave[:,:]*_ for _ in u0.astype(np.float32)])
    else:
        aer = ave[None,:,:]*u_img0r
    del ave, u_img0r, u_img

    #back to original shape

    aer = upsample_to_shape(aer, img0.shape)
    print(f'upsampled aer.shape={aer.shape}')
    if '.nc' in fin:
        header=ncutils.readheader(fin); waves=header['waves']
    elif '.tif' in fin:
        waves=tiffutils.get_waves_tif(fin)
    elif fin.endswith(('jpg','png')):
            waves = None; #['R','G','B']
    if '.nc' in fin:
        ncutils.writeSpecData2file_2nc(aer, fin_aero_base+'.nc', waves=waves, slope=1./65535, offset=-0.1)
    else:
        tiffutils.writeData_to_geotif(aer,fin, fin_aero_base+'.tif', waves=waves, slope=1./65535, offset=-0.1)
    
    _mask=aer[0]>thresh#0.10#0.15 #None
    _mask=None
    _=gen_rgb(aer, mask=_mask, linear=1, ofilepath=fin_aero_base, bds=bds_rgb, data4alpha=img0[0,:,:])
    
    _=gen_rgb(img0-aer, mask=_mask, linear=1, ofilepath=fin_deh_base,bds=bds_rgb, data4alpha=img0[0,:,:])
    # _=gen_rgb(reconR, mask=_mask, linear=1, ofilepath=fin_deh_base,bds=bds_rgb, data4alpha=img0[0,:,:])

    if '.nc' in fin:
        ncutils.writeSpecData2file_2nc(img0-aer, fin_deh_base+'.nc', waves=waves, slope=1./65535, offset=-0.1)
    else:
        tiffutils.writeData_to_geotif(img0-aer, fin, fin_deh_base+'.tif', waves=waves, slope=1./65535, offset=-0.1)
    # _=gen_rgb(img0[:,:,:], mask=_mask, linear=1, ofilepath=fin_base+'_ori',bds=bds_rgb, data4alpha=img0[0,:,:])




