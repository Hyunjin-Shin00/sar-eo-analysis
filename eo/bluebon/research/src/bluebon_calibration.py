#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jun  5 09:35:35 2025
1. band coregister -> stacked DN
2. apply calibration -> stacked_rhot.nc (output)
@author: yp
"""
import numpy as np

# from scipy.ndimage import shift
import sys
sys.path.append('./../../tools')
from genrgb import gen_rgb
from uniquify import uniquify

import os, re

import rasterio
def read_raster_tif(ftif):
    with rasterio.open(ftif) as src:
        data = src.read()  # shape: (bands, rows, cols)
        profile = src.profile  # metadata like crs, transform, dtype
    return data, profile

import coreg_tools as CRT
# import coreg_FourierMelin as CRFM
# import coreg_FourierMelin_twotile as CRFM2T
# import coreg_FourierMelin_multitile as CRFMMT
# import coreg_FourierMelin_multitile_2d as CRFMMT2d

#update for no loss stacking Sep 5, 2025
#---reading all bands once is necessary to compute final canvas
import calib
def calib_and_coreg(fband_array, cal_prms, solzen, d_r, setting={'prod_type':'DN'}, upsample_f=100, bg=0., valid_ranges=None, roi=None):
    calflag=False if setting['prod_type'] == 'DN' else True
    if calflag:
        use_caldf=setting['use_caldf']
    if calflag:
        if use_caldf: # twoline for calibrate_bb_band
            dfrad = calib.get_df_inband_mean()
            df = calib.load_cal_df()
        else:
            #lines follows for use bb_DN2rad
            # print('DN2rad using bb_DN2rad for tdi_arr=[1,4,8,8,16,16,16,4]')
            # maxDN=[17500,9500,9500,13200,7350,8000,11000,32000]
            # with np.load("coefs_rad_to_DN.npz") as z:
            #     slope = z["slope"]
            #     offset = z["pixelwise_offset"]   
            # add_L10=np.array([0., 0., 0, -0.05, 0.13, 0.21, 0.25,-0.06])*10. #radiance to-add based on 250926 Khuvsgul image since 2025.Nov.14
            with np.load('dn2rad_coeffs_calpar.npz', allow_pickle=True) as z:
                coeff = np.array(z['coeffs'])
                # metadata = z['meta_data'].item()
                print(f'dn2rad_coeff shape: {coeff.shape}')
    if setting['prod_type'] in ['rhot','rhorc']:
        f0_bb, waves_bb = rsr_f0_bluebon.compute_F0() #order MS1 MS2 ...MS7 PAN
        _idx=[7]+[_ for _ in range(7)]
        f0_bb =f0_bb[_idx] #PAN,MS1,..,MS7
        cth0=np.cos(solzen*np.pi/180.)
        
    bdsM = [ ib for ib in range(len(cal_prms)) if cal_prms[ib]['TDI'] != 0]
        
    images=[]
    for ib in range(len(fband_array)):
        if ib not in bdsM:
            continue
        ftif = fband_array[ib]
        _dn, _profile = read_raster_tif(ftif)
        if not calflag:
            _rad = np.squeeze(_dn)[:,::-1] #DN
        else:
            if use_caldf:
                _rad = calib.calibrate_bb_band(np.squeeze(_dn), cal_prms[ib], df, dfrad)
            else:
                #OLd:Use rad2DN
                # _rad=calib.bb_DN2rad(np.squeeze(_dn), slope[ib], offset[ib], maxDN[ib] )
                # _rad += add_L10[ib]
                _rad=calib.bb_DN2rad_NEW(np.squeeze(_dn),coeff[ib,:,:])
            _rad=_rad[:,::-1] *0.1
        if setting['prod_type'] in ['rhot','rhorc']: #L->R
            _rad = np.pi*_rad/f0_bb[ib]/cth0*(d_r*d_r)
        images.append(_rad)
        
    # ===Test option 0) - phase correlation + one band reference    
    vis_idxs = [_ for _ in range(len(bdsM))]
    ref_vis = 4 #red
    nir_idxs = None
    ref_nir=None
    # use_gradient=True #sobel
    # valid=valid_ranges #exCloud if valid_ranges
    
    # ===Test Option 1) - phase correlation + one band reference + sobel 
    # use_gradient=True
    
    # ===Test Option 1) - phase correlation + one band reference 
    use_gradient=True
    valid=None
    
    # ===Test Option 1) - phase correlation + one band reference + sobel 
    # use_gradient=True
    # valid=valid_ranges

    # ===Option 2 & 3) - phase correlation + two band reference + sobel
    # use_gradient=True
    
    #2ref : 2steps for NIR
    # vis_idxs =[0,1,2,3,4]; ref_vis=4; nir_idxs=[5,6,7]; ref_nir=5
    
    if 0: # === to be finalized
        # use_gradient=True
        # if len(bdsM)==8:
        #     vis_idxs =[0,1,2,3,4]; ref_vis=4; nir_idxs=[5,6,7]; ref_nir=5
        # else:
        #     vis_idxs = [_ for _ in range(len(bdsM))]
        #     ref_vis = vis_idxs[-2]
        #     nir_idxs = None
        #     ref_nir=None
        
        valid=None
        exCloud=True if valid is not None else False
        print(f"\n[INPUT] ref_vis={ref_vis},ref_nir={ref_nir},sobel={use_gradient},exCloud={exCloud}")    
        
        stack, shifts, sh_int, out_shape = \
            CRT.coreg_two_refs(images, vis_idxs, ref_vis, nir_idxs, ref_nir, 
            upsample_f=upsample_f, bg=bg, use_gradient=use_gradient, valid_ranges=valid, roi=roi)
        
    else:
        # stack, models, out_shape = \
        #     coreg_single_ref_affine_sobel(images, ref_idx, bg=bg)
        
        if len(bdsM)==8:
            vis_idxs =[0,1,2,3,4]; ref_vis=4; nir_idxs=[5,6,7]; ref_nir=5
        else:
            vis_idxs = [_ for _ in range(len(bdsM))]
            ref_vis = vis_idxs[-2]
            nir_idxs = None
            ref_nir=None
        use_gradient=True
        
        
        stack, models, out_shape = \
            CRT.coreg_two_refs_affine_sobel_mask(
            images, vis_idxs, ref_vis, nir_idxs, ref_nir,
            upsample_f=100,           # kept for API compatibility; not used
            mode='edge',
            sat_threshold=None,
            n_keypoints=2000,
            fast_threshold=0.05,
            verbose=True,
            valid_ranges=valid,
            roi = roi,
            use_sobel=use_gradient
        )
        
    ##save affinetransform to *_affineModels.npz fora all bands
        matrices = [m.params for m in models]
        outdir = os.path.dirname(fband_array[0])+'/../myout'
        os.makedirs(outdir, exist_ok=True)
        fnpz = outdir+'/'+re.sub(r'_\d+_gray\.tiff$', '', os.path.basename(fband_array[0]))+'_affineMtx_bandRegister.npz'
        fnpz = uniquify(fnpz)
        np.savez(fnpz,*matrices)
        print(f"[INFO].... Affine models has been stored in {fnpz}")
    
    # stack, params, tforms, out_shape = CRFM.coreg_two_refs_similarity_fm(
    #     images,
    #     vis_idxs, ref_vis, nir_idxs, ref_nir,
    #     upsample_f=50,      # good starting point
    #     bg=0,
    #     use_gradient=True,
    #     verbose=True,
    # )
    
    #upsample_f=1000 for anlge .3f
    # stack, Ttop, Tbot, diags, out_shape = CRFM2T.coreg_two_refs_similarity_fm_tiles(
    #     images,    vis_idxs,    ref_vis,    nir_idxs,    ref_nir,
    #     upsample_f=1000,    overlap=256,    bg=0,
    #     use_gradient=use_gradient,    verbose=True, 
    #     valid_ranges=valid
    # )
    
    # n_tiles=1#4
    # print(f"\n[INPUT] n_tiles={n_tiles}")
    # stack, tforms_tiles, diags_tiles, out_shape = CRFMMT.coreg_two_refs_similarity_fm_multitiles(
    #     images,    vis_idxs,    ref_vis,    nir_idxs,    ref_nir,
    #     upsample_f=100,   n_tiles=n_tiles,   overlap=256,     bg=0,
    #     use_gradient=use_gradient,
    #     verbose=True,
    #     valid_ranges=valid
    # )
    
    # n_tiles_x=2#4
    # n_tiles_y=1
    # estimate_rs=False
    # print(f"\n[INPUT] n_tiles_x, _y={n_tiles_x}, {n_tiles_y}, estimate_rs={estimate_rs}")
    # stack, tforms_tiles, diags_tiles, out_shape = CRFMMT2d.coreg_two_refs_similarity_fm_multitiles(
    #     images,    vis_idxs,    ref_vis,    nir_idxs,    ref_nir,
    #     upsample_f=1000,  n_tiles_y=n_tiles_y,  # Changed from n_tiles
    #     n_tiles_x=n_tiles_x,  # Added   overlap=256,     bg=0,
    #     use_gradient=use_gradient,
    #     verbose=True,
    #     valid_ranges=valid,
    #     estimate_rs=estimate_rs
    # )
    return stack
    

# import os
# _dir = os.path.expanduser('~/myPy/bluebon/src')
# os.chdir(_dir)
# import sys
# sys.path.append('./../../tools')
import os
import rsr_f0_bluebon
import line_correction
# def bb_coregister_calibrate(indir, keystr, tdi_arr, solzen, d_r, linear_cal=True, rhor=None, intercal=False, torho=True, linecorrection=False):
def bb_coregister_calibrate(indir, keystr, tdi_arr, solzen, d_r, 
                            setting={'prod_type':'DN','excl_Pan':False}, rhor=None, valid_ranges=None, roi=None):
    excl_Pan=setting['excl_Pan']
    #nocal=True write rawDN without calibration to nc file
    nb=8
    fband_array=[indir+f'/{keystr}_{ib}_gray.tiff' for ib in range(0,nb)]
    bd_names=['PAN']+[f'MS{ib}' for ib in range(1, nb)]
    cal_prms = [{'band':bd_names[ib], 'L_rate':666, 'TDI':tdi_arr[ib]} for ib in range(0,nb)]
    
    stacked = calib_and_coreg(fband_array, cal_prms, solzen, d_r,  setting=setting, valid_ranges=valid_ranges, roi=roi)
    # stacked = calib_and_coreg(fband_array, cal_prms, solzen, d_r, setting=setting)
    bdsM = [ ib for ib in range(len(cal_prms)) if cal_prms[ib]['TDI'] != 0]
    
    if len(bdsM)==8:
        stacked = stacked[[1,2,0,3,4,5,6,7],:,:] #reorder to 'MS1 MS2 PAN MS3 ... MS7'
        # shiftyx = shift_arr[[1,2,0,3,4,5,6,7],:]
        #this order need to match the order os waves_bb and f0_bb
    elif len(bdsM)==4: #[1,2,3,7]
        bdsM = [x-1 if 0<x<3 else x for x in bdsM]
    
    outdir = os.path.dirname(indir)+'/myout'
    os.makedirs(outdir, exist_ok=True)
    prod_type=setting['prod_type']
    fnc_out=outdir+'/'+f'{keystr}_stacked_{prod_type}.nc'
    
    f0_bb, waves_bb = rsr_f0_bluebon.compute_F0() #order MS1 MS2 ...MS7 PAN
    _idx=np.argsort(waves_bb) #rearrange the order of increasing wavelengths
    waves_bb=waves_bb[_idx]
    
    #select measured bands
    waves_bb=waves_bb[bdsM]
 
    # waves_bb=[490, 560, 625, 665, 705, 740, 783, 842.]   
    if (prod_type=='DN') or (prod_type=='rad'): #write coregistered DN or rad
        if excl_Pan and len(bdsM)==8:
            _idx=[0,1,3,4,5,6,7]
            stacked = stacked[_idx,:,:]
            waves_bb=waves_bb[_idx]
        ncutils.writeSpecData2file_2nc(stacked, fnc_out, waves=waves_bb)

    else: 
        #two lines done in calib_and_coreg
        # cth0=np.cos(solzen*np.pi/180.)
        # stacked = np.pi*stacked/f0_bb[:,None,None]/cth0*(d_r*d_r)
        
        if any(setting.get('linecor_vh',[])) :
            v,h=setting.get('linecor_vh')
            stacked = line_correction.bluebon_linecorrection(stacked,v=v,h=h)
        
        if setting['use_caldf'] & setting['intercal']:
            print('intercal applied')
            
            #radiant intensity Andong
            # sl  = np.array([ 2.507, 1.392, 2.466, 1.885, 2.145, 1.365, 1.811, 3.725])
            # off = np.array([-0.374,-0.075,-0.133,-0.027,-0.003, 0.027, 0.008,-0.107])
            #level -> inband radiance Andong: same results
            # sl  = np.array([ 1.788, 3.469, 0.910, 4.333, 9.483, 5.196, 4.412, 1.322])
            # off = np.array([-0.033,-0.030,-0.147,-0.020,-0.013, 0.022, 0.006,-0.090])
            #level -> inband radiance msi Seoul : intercal_rhot_msivsbb_250719.png
            # sl  = np.array([ 1.840, 3.834, 0.906, 4.947, 10.001, 10.473, 8.115, 1.539])
            # off = np.array([-0.019,-0.019,-0.100,-0.009,  0.010, -0.009,-0.040,-0.115])
            #Bahrain 250716 ※
            # sl  = np.array([ 1.262, 2.935, 1.866, 3.989, 8.661, 8.434, 6.560, 1.271])
            # off = np.array([ 0.050, 0.025,-0.305, 0.017, 0.026, 0.046, 0.044,-0.025])
            #Bahrain 250716 ※apply *tdi/4
            sl  = np.array([ 1.262, 1.467, 7.465, 1.995, 2.165, 2.108, 1.640, 1.271])
            off = np.array([ 0.050, 0.025,-0.305, 0.017, 0.026, 0.046, 0.044,-0.025]) #nochange tdi/4
            
            #Namhae temporary
            # sl  = np.array([ 1.724 , 1.066,  0.4105, 1.412, 2.090, 2.393,  1.819,  1.472])
            # off = np.array([-0.0307, 0.0092, 0.0162, 0.00276, 0.00608, 0.00515, -0.0065,-0.0635])
            
            sl = sl[bdsM]; off=off[bdsM]
            stacked = stacked*sl[:,None,None]+off[:,None,None]
        
        if rhor is not None:
            rhor = rhor[_idx][bdsM]
            print(f'rhor=f{rhor} is removed from stacked')
            stacked = stacked -rhor[:,None,None]
        
        if excl_Pan and len(bdsM)==8:
            _idx=[0,1,3,4,5,6,7]
            stacked = stacked[_idx,:,:]
            waves_bb=waves_bb[_idx]
        ncutils.writeSpecData2file_2nc(stacked, fnc_out, waves=waves_bb, slope=1./65535, offset=0.)
   
    abd=1 if excl_Pan else 0
    bdsN=[7-abd,1,0];    bdsV=[3-abd,1,0]
    if len(bdsM)==4:
        bdsN=[3,1,0];    bdsV=[2,1,0]
        
    limits = None#[[700.,1800],[1000.,2200],[1500.,3500]]
    _=gen_rgb(stacked, ofilepath=os.path.splitext(fnc_out)[0], bds=bdsN, data4alpha=stacked[0,:,:], limits=limits)#, linear=1)
    _=gen_rgb(stacked, ofilepath=os.path.splitext(fnc_out)[0], bds=bdsV, data4alpha=stacked[0,:,:], limits=limits, linear=1)
    # ibd=bdsM[-1]; _=gen_rgb(stacked[-1], ofilepath=outdir+f'/{keystr}_band{ibd}')



def earthSun_distance_factor(doy):
    d_r = 1+0.033*np.cos (2.*np.pi*doy/365)
    return d_r

import bluebon_rayleigh
import pandas as pd
import ncutils
if __name__=="__main__":
    # indir = '/home/yp/Downloads/bluebon/250523_Ukraine'
    # keystr='250523_090154'
    
    # indir='/home/yp/Downloads/bluebon/250626_Chesapeake/rawDN'
    # timestr = '2025-06-26T16:16:48Z'; time=pd.Timestamp(timestr)
    # keystr='250626_161648'
    # cen_lon, cen_lat = -76., 37.; roll = -5.8006
    # tdi_arr=[2,4,8,16,8,8,8,8] #order: pan, ms1, ...
    # linear_cal=False #False=quadratic fitting for DN-rad conversion
    # # solzen=17.5 #degree see solarpos.py
    # # d_r=0.96715 #earthSun_distance_factor(doy)
    
    # intercal=True; RayleighCorr=True; 
    
    # indir='/home/yp/Downloads/bluebon/250629_Andong'; keystr = '250629_023708'
    # timestr = '2025-06-29T02:37:12Z'
    # time=pd.Timestamp(timestr)
    # cen_lon, cen_lat = [128.8, 36.58]; roll=-5.648 #from mission
    # tdi_arr=[2,4,8,16,8,8,8,8] 
    
    # indir='/home/yp/Downloads/bluebon/250712_Seoul/rawDN'
    # keystr = '250712_024621'
    # timestr = '2025-07-12T02:46:21Z'; time=pd.Timestamp(timestr)
    # cen_lon, cen_lat = 127.0724, 37.5151; roll = -1.6705
    # tdi_arr=[1,4,8,8,16,16,16,4]
    # linear_cal=False #False=quadratic fitting for DN-rad conversion
    
    
    # indir='/home/yp/Downloads/bluebon/250716_Bahrain/rawDN'
    # #fr mission table
    # timestr = '2025-07-16T07:42:59Z'; time=pd.Timestamp(timestr)
    # # keystr = timestr[2:19].replace('-','').replace('T','_').replace(':','')
    # keystr = '250716_074255'
    # cen_lon, cen_lat = 50.6181, 25.8272; roll = -4.6357 
    # tdi_arr=[1,4,8,8,16,16,16,4]
    
    # indir='/home/yp/Downloads/bluebon/250806_SoffSydney/rawDN'
    # #fr mission table 2025-08-06T00:28:59.654(1754440139654)
    # timestr = '2025-08-06T00:28:59.654Z'; time=pd.Timestamp(timestr)
    # keystr = '250806_002855'
    # cen_lon, cen_lat = 151.162414, -34.465546; roll = 2.4948 
    # tdi_arr=[1,4,8,8,16,16,16,4]

    # indir='/home/yp/Downloads/bluebon/250821_Busan/rawDN'
    # #fr mission table 2025-08-21T02:37:45.145(1755743865145)
    # timestr = '2025-08-21T02:37:45.145Z'; time=pd.Timestamp(timestr)
    # keystr = '250821_023741'
    # cen_lon, cen_lat = 129.047, 35.1032; roll = -0.4647
    # tdi_arr=[1,4,8,8,16,16,16,4]
    
    # indir='/home/yp/Downloads/bluebon/250903_Namhae/rawDN'
    # #fr mission table 2025-09-03T02:35:36.098(1756866936098)
    # timestr = '2025-09-03T02:35:36.098Z'; time=pd.Timestamp(timestr)
    # keystr = '250903_023532'
    # cen_lon, cen_lat = 128.0133, 34.7098; roll = -17.5061 
    # tdi_arr=[2,4,8,8,16,16,16,4]
    # valid_rhot=[
    #     [0.,0.5],#0.2],#0.5],
    #     [0.,0.3],
    #     [0.,0.3],
    #     [0.,0.3],
    #     [0.,0.3],
    #     [0.,0.5],
    #     [0.,0.5],
    #     [0.,0.5]
    #     ] #order: PAN,MS1..7
    
    # indir='/home/yp/Downloads/bluebon/250928_Thai_KKairport/rawDN'
    # timestr = '2025-09-28T04:19:01.105Z'; time=pd.Timestamp(timestr)
    # keystr = '250928_041857'
    # cen_lon, cen_lat = 100.663, 14.875; roll = -0.0739 
    # tdi_arr=[0,4,8,8,0,0,0,4]
    
    # indir='/home/yp/Downloads/bluebon/250926_GBR6/rawDN'
    # timestr='2025-09-26T00:30:52.681Z'; time=pd.Timestamp(timestr)
    # keystr = '250926_003048'
    # cen_lon, cen_lat = 152.0095, -21.416; roll = -10.5786
    # tdi_arr=[2,4,8,8,16,16,16,4]
    
    # indir='/home/yp/Downloads/bluebon/250926_Khuvsgul/rawDN'
    # timestr='2025-09-26T04:55:03.607Z'; time=pd.Timestamp(timestr)
    # keystr = '250926_045459'
    # cen_lon, cen_lat = 100.5084, 51.0867; roll = 13.0299
    # tdi_arr=[2,4,8,8,16,16,16,4]
    
    # indir='/home/yp/Downloads/bluebon/251022_TakhliAP/rawDN'
    # timestr='2025-10-22T04:26:33.588Z'; time=pd.Timestamp(timestr)
    # keystr = '251022_042629'
    # cen_lon, cen_lat = 100.296, 15.277; roll = 16.493
    # tdi_arr=[0,4,8,8,0,0,0,4]
    
    # indir='/home/yp/Downloads/bluebon/251030_Seorak/rawDN'
    # timestr='2025-10-30T02:45:39.226Z'; time=pd.Timestamp(timestr)
    # keystr='251030_024535'
    # cen_lon, cen_lat = 128.4656, 38.1194; roll = 3.7502
    # tdi_arr=[2,4,8,8,16,16,16,4]

    #next 4 lines for rho_rc    
    # indir='/home/yp/Downloads/bluebon/..'
    # timestr='2025-09-24T07:22:10.355Z'; time=pd.Timestamp(timestr)
    # keystr='..'
    # cen_lon, cen_lat = 55.103137, 24.946894; roll = -15.1464
    
    # indir='/home/yp/Downloads/bluebon/251109_BanNongYaKaew/rawDN'
    # timestr='2025-11-19T04:18:38.194'; time=pd.Timestamp(timestr)
    # keystr = '251119_041834'
    # cen_lon, cen_lat = 102.7363, 13.8189; roll = 22.274
    # tdi_arr=[0,4,8,8,0,0,0,4]
    
    # indir='/home/yp/Downloads/bluebon/251123_Thai/rawDN'
    # timestr='2025-11-23T04:15:51.668'; time=pd.Timestamp(timestr)
    # keystr='251123_041547'
    # cen_lon, cen_lat = 102.7, 13.8; roll = 12.8818
    # tdi_arr=[0,4,8,8,0,0,0,4]
    
    # indir='/home/yp/Downloads/bluebon/251127_Thai/rawDN'
    # timestr='2025-11-27T04:12:34.136'; time=pd.Timestamp(timestr)
    # keystr='251127_041230'
    # cen_lon, cen_lat = 103.6992, 14.4364; roll = 13.5946
    # tdi_arr=[0,4,8,8,0,0,0,4]
    
    # indir='/home/yp/Downloads/bluebon/260122_025059_Ongjin/rawDN'
    # timestr='2026-01-22T02:51:03.084'; time=pd.Timestamp(timestr)
    # keystr='260122_025059'
    # cen_lon, cen_lat = 126.5591, 37.9785; roll =-8.5362
    # tdi_arr=[2,4,8,8,16,16,16,4]
    valid_rhot=[
        [0.,0.5],#0.2],#0.5],
        [0.,0.3],
        [0.,0.3],
        [0.,0.3],
        [0.,0.3],
        [0.,0.5],
        [0.,0.5],
        [0.,0.5]
        ] #order: PAN,MS1..7
    
    # indir='/home/yp/Downloads/bluebon/260209_Suwon/rawDN'
    # timestr='2026-02-09T02:59:28.200'; time=pd.Timestamp(timestr)
    # keystr='260209_025928'
    # cen_lon, cen_lat = 127.0534, 37.289; roll =17.4467
    # tdi_arr=[2,4,8,8,16,16,16,4]
    
    indir='/home/yp/Downloads/bluebon/260220_Suwon/rawDN'
    timestr='2026-02-20T02:56:32.979'; time=pd.Timestamp(timestr)
    keystr='260220_025632'
    cen_lon, cen_lat = 127.0534, 37.289; roll =9.402
    tdi_arr=[2,4,8,8,16,16,16,4]
    roi=None#[12500, 15250, 100, 3700] #same for all bands, no improvment even in the roi area
    
    # indir='/home/yp/Downloads/bluebon/260221_Oman/rawDN'
    # timestr='2026-02-21T07:16:53.743'; time=pd.Timestamp(timestr)
    # keystr='260221_071653'
    # cen_lon, cen_lat = 58.0905, 23.7096; roll =-6.8836
    # tdi_arr=[2,4,8,8,16,16,16,4]
    # roi=None
    
    # indir="/home/yp/Downloads/bluebon/251029_Teheran/rawDN"
    # timestr="2025-10-29T07:53:16.263"; time=pd.Timestamp(timestr)
    # keystr="251029_075312"
    # cen_lon, cen_lat = 51.3305, 35.7176; roll=6.8168
    # tdi_arr=[2,4,8,8,16,16,16,4]
    # roi=[9850, 10960, 2010, 3075] #y0, y1, x0, x1 image coordinates
    
    # indir="/home/yp/Downloads/bluebon/260306_Teheran/rawDN"
    # timestr="2026-03-06T07:49:44.365"; time=pd.Timestamp(timestr)
    # keystr="260306_074940"
    # cen_lon, cen_lat = 51.3305, 35.7176; roll=-13.7419
    # tdi_arr=[2,4,8,8,16,16,16,4]
    # roi=None # [y0, y1, x0, x1] same for all bands
    
    # indir='/home/yp/Downloads/bluebon/260413_Kuwait/rawDN'
    # timestr='2026-04-13T08:11:47.482'; time=pd.Timestamp(timestr)
    # keystr='260413_081143'
    # cen_lon, cen_lat = 47.5214, 29.3477; roll =13.3781; pitch=0.2414
    # tdi_arr=[2,4,8,8,16,16,16,4]
    # roi=None
    # # valid_rhot=None
    
    # torho = one of prms0, prms1, prms2
    # prod_type one of DN, rad, rhot, rhorc
    # DN: raw DN no calibration
    prms0 = {'prod_type':'DN'}
    prms1 = {'prod_type':'rad','use_caldf':False,'use_npz':True,  'linear_cal':False, 'intercal':True}
    prms2 = {'prod_type':'rhot','use_caldf':False, 'use_npz':True, 'intercal':False, 'linecor_vh':[False, False], 'excl_Pan':False}
    prms3 = {'prod_type':'rhorc','use_caldf':False, 'use_npz':True, 'intercal':False, 'linecor_vh':[False, False], 'excl_Pan':True}
    # linear_cal=False #False=quadratic fitting for DN-rad conversion
    # intercal=False;  #inter-sensor calibration applied to rhot data
    # torho=True # False=>output DN, True => output rhot or rhorc 
    
    setting = prms2 #prms1
    
    RayleighCorr=True if setting['prod_type']=='rhorc' else False
    
    rhor=None
    if RayleighCorr:
        r=bluebon_rayleigh.get_rayleigh(time, cen_lon, cen_lat, roll)
        rhor=np.squeeze(r)
        print(f'rhor={rhor}')
        # exit()
    
    print(f'Rayleigh reflectance rhor={rhor}')

    zenith_arr, azimuth_arr = bluebon_rayleigh.compute_solang(time, [cen_lon], [cen_lat])
    solzen=zenith_arr[0]
    d_r = earthSun_distance_factor(time.dayofyear)
    
    # bb_coregister_calibrate(indir, keystr, tdi_arr, solzen, d_r,  rhor=rhor, linear_cal=linear_cal, intercal=intercal, linecorrection=linecorrection, torho=torho)
    bb_coregister_calibrate(indir, keystr, tdi_arr, solzen, d_r,  setting=setting, rhor=rhor, valid_ranges=valid_rhot, roi=roi)
