#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug  2 18:09:09 2025
Generate constants for BBinvfit
@author: yp
"""
import numpy as np
import sys
sys.path.append('./../../bidir/src_bd')
sys.path.append('./../src')
import rsr_f0_bluebon as RFB
from read_spectraldata import get_aw_ext,get_BricAE,get_bsw_ext
if __name__=="__main__":
    # owave=np.arange(350.,2000.,5)
    # #owave = [i*5.+400. for i in range(121)] #; [400, 410, 420, ... 1000]
    wave0, rsr, _colnames = RFB.read_bb_srf()# 
    wave_band = np.sum(wave0*rsr, axis=1)/np.sum(rsr, axis=1) #Numpy broadcasting
    x =wave_band[:-1]
    print([eval(f'{_:.1f}') for _ in x])

    homedir = "./../../bidir/DirRrs"
    #read spectral data
    aw = get_aw_ext(homedir, wave0)
    aw_band = np.sum(aw*rsr, axis=1)/np.sum(rsr, axis=1)
    x =aw_band[:-1]
    print([eval(f'{_:.4f}') for _ in x])
    
    #read aph from Brico
    (BricA, BricE) = get_BricAE(homedir, wave0, aph=1); BricE[:]=1.
    BricA_band = np.sum(BricA*rsr, axis=1)/np.sum(rsr, axis=1)
    #normalize to band1
    aph_band= BricA_band/BricA_band[0]
    x =aph_band[:-1]
    print([eval(f'{_:.4f}') for _ in x])
    
    adg=np.exp(-0.01*(wave0-440.))
    adg_band = np.sum(adg*rsr, axis=1)/np.sum(rsr, axis=1)
    adg_band = adg_band/adg_band[0]
    x =adg_band[:-1]
    print([eval(f'{_:.4f}') for _ in x])

    bsw = get_bsw_ext(homedir, wave0)
    bbw = 0.5*bsw
    bbw_band = np.sum(bbw*rsr, axis=1)/np.sum(rsr, axis=1)
    x =bbw_band[:-1]
    print([eval(f'{_:.5f}') for _ in x])
    
    
    bbp = np.power(550./wave0,0.5)
    bbp_band = np.sum(bbp*rsr, axis=1)/np.sum(rsr, axis=1)
    bbp_band = bbp_band/bbp_band[1]
    x =bbp_band[:-1]
    print([eval(f'{_:.3f}') for _ in x])

    #aerosol glint
    #aerosol model
    aero = np.power(550./wave0,0.5)
    aero_band = np.sum(bbp*rsr, axis=1)/np.sum(rsr, axis=1)
    aero_band = aero_band/aero_band[-2]
    x =aero_band[:-1]
    print([eval(f'{_:.3f}') for _ in x])
    #glint spec from image
    # glint_h = np.array([1.01e-01, 1.06e-01, 1.06e-01, 1.03e-01, 1.03e-01, 1.05e-01, 1.01e-01])
    # glint_l = np.array([7.73e-02, 7.49e-02, 6.94e-02, 6.33e-02, 6.38e-02, 6.32e-02, 6.26e-02])
    #
    glint_h = np.array([9.64e-02, 9.94e-02, 9.26e-02, 8.16e-02, 8.19e-02, 8.06e-02, 7.56e-02])
    glint_l = np.array([8.12e-02, 7.81e-02, 6.70e-02, 5.75e-02, 5.83e-02, 5.44e-02, 5.14e-02])
    glint=glint_h-glint_l
    glint = glint/glint[-1]
    x =glint[:]
    print([eval(f'{_:.3f}') for _ in x])
