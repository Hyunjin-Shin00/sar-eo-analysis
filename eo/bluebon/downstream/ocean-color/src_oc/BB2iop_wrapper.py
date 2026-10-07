#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Aug  4 00:30:45 2025

@author: yp
"""
import os,sys,time, math
import numpy as np
from BBrhorc2iop import proc_rhorc2iop_by_fitting

sys.path.append(r'./../../tools')
import gen_png_simple as GPS
import ncutils, tiffutils
from genrgb import gen_rgb



def blkproc(frhorc, ofbase):
    
    rhorc = tiffutils.getraster(frhorc, None)
    rhorc = np.transpose(rhorc,(1,2,0))
    nlin, npix, nb =rhorc.shape
    
    niop = 6; niop_f=5
    #-----initialize block processing
    Rrs_out = np.zeros((nlin, npix, nb), dtype=np.float32)
    iop = np.zeros((nlin, npix, niop), dtype=np.float32)
    mask = np.zeros((nlin, npix), dtype=np.uint8)
    relerr=np.zeros((nlin, npix), dtype=np.float32)
    niter=np.zeros((nlin, npix), dtype=np.int32)
    iop_f = np.zeros((nlin, npix, niop_f), dtype=np.float32)
    niopw=4
    relnormdif_f = np.zeros((nlin,npix,niopw),dtype=np.float32)

    blklin=600 ; addlin=10 ; nblk = math.ceil(float(nlin)/blklin)-1# last block
    
    for iblk in range( nblk):

        stime = time.time()
        if(iblk == 0):
            #read 0~blklin+100 writing 0~blklin+100
            slin = 0; elin = blklin+addlin-1 ; _nlin=elin-slin+1
            shiftlin = 0 ; wslin=slin+shiftlin
        elif (iblk < nblk-1) :
            #read: blkline~2*blkline+100 writing blkline+100/2 ~ endline
            slin = blklin*iblk ; elin = slin+blklin+addlin-1 #&  elin = elin < (nlin-1)
            _nlin=elin-slin+1
            shiftlin = round(addlin/2) ; wslin = slin+shiftlin
        else: #last 2 blks merged
            slin = blklin*iblk ; elin = (nlin-1)
            _nlin=elin-slin+1
            shiftlin = round(addlin/2) ; wslin = slin+shiftlin

        _rhorc = rhorc[slin:(elin+1), : , :].astype(np.float64)
        amratio =np.ones((_nlin,npix),dtype=np.float64)
        LUTratio=np.ones((_nlin,npix,nb), dtype=np.float64)
        _mask, _Rrs_out, _iop, _relerr,_niter, _iop_f, _relnormdif_f = proc_rhorc2iop_by_fitting(_rhorc, LUTratio,  amratio, None,flagging=True,subset=None)
        
        Rrs_out[wslin:elin+1,:,:]       = _Rrs_out[shiftlin:_nlin,:,:].astype(np.float32)
        iop[wslin:elin+1,:,:]           = _iop[shiftlin:_nlin,:,:].astype(np.float32)
        mask[wslin:elin+1,:]            = _mask[shiftlin:_nlin,:]
        relerr[wslin:elin+1,:]          = _relerr[shiftlin:_nlin,:].astype(np.float32)
        niter[wslin:elin+1,:]           = _niter[shiftlin:_nlin,:]
        iop_f[wslin:elin+1,:,:]         = _iop_f[shiftlin:_nlin,:,:].astype(np.float32)
        relnormdif_f[wslin:elin+1,:,:]  = _relnormdif_f[shiftlin:_nlin,:,:].astype(np.float32)
        
        etime=time.time()
        print( 'processed block ='+ ("%d" % (iblk+1)) \
             +' slin:'+ ("%5d" % slin) \
             +' elin:'+ ("%5d" % elin) \
             +' out of ' + ("%5d" % nlin ) \
             + ' elapsed(min): '+("{:.1f}".format((etime-stime)/60)) )
    
    rhowSpec =np.pi*Rrs_out 
    ind= (mask!=0)
    for ib in range(nb):
        rhowSpec[:,:,ib][ind]=0. #


    tr = [1., 1., 1., 1., 1.,  1.,1. ]
    tr=np.array(tr)

    naer=niop-niopw#=4
    for iaer in range(naer):
        if iaer==0:
            aerosum=iop[:,:,4+iaer]
        else: aerosum = aerosum+iop[:,:,4+iaer]
    
    rhoa = np.zeros_like(rhorc)
    for ib in range(nb):
        # rhoa[:,:,ib]=rhorc[:,:,ib]-rhowSpec[:,:,ib]*np.power(trayFix[ib],amratio[:,:])*(taer0[ib]+taer_slope[ib]*(aerosum[:,:]-0.08))
        rhoa[:,:,ib]=rhorc[:,:,ib]-rhowSpec[:,:,ib]#*np.power(tr[ib],amratio[:,:])
    waves = [483.2, 562.4, 664.6, 704.8, 739.2, 781.9, 836.6]
    waves=np.array(waves)
    
    if ofbase is not None:
        frhowSpec=ofbase+'_rhowSpec'
        ncutils.write2nc(frhowSpec+'.nc', rhowSpec, waves=waves, noproj=True)
        
        bds_rgb = [2,1,0]; bds_ngb=[6,1,0]
        # gen_rgb(np.copy(rhowSpec), ofilepath=frhowSpec, bds=[10,5,2], log=1,limits=[[0.003,0.01],[0.01,0.1],[0.007,0.07]])
        # gen_rgb(np.copy(rhowSpec), ofilepath=frhowSpec, bds=[7,5,2], log=1,limits=[[0.003,0.05],[0.01,0.1],[0.007,0.07]])
        gen_rgb(np.copy(rhowSpec), mask=mask, ofilepath=frhowSpec, bds=bds_ngb, limits=[[0.005,0.15],[0.005,0.15],[0.005,0.15]])
        gen_rgb(np.copy(rhowSpec), mask=mask, ofilepath=frhowSpec, bds=bds_rgb, limits=[[0.005,0.15],[0.005,0.15],[0.005,0.15]])

        opathbase=ofbase  + '_aphf'
        # PGS.gen_png_simple(iop[:,:,0], mask, vrange=[0.03,1], opathbase=opathbase, coastline=coastline)
        # PGS.gen_png_simple(iop[:,:,0], mask, vrange=[0.005,0.5], opathbase=opathbase, coastline=coastline)
        # PGS.gen_png_simple(iop[:,:,0], mask, vrange=[0.001,0.1], opathbase=opathbase, coastline=None)
        GPS.gen_png_simple(iop_f[:,:,0], mask, vrange=[0.0,0.2], linear=1, opathbase=opathbase)

        opathbase=ofbase  + '_TChlf'
        _data=np.copy(iop_f[:,:,0])
        idx = _data>0.
        # _data[idx]=np.power(_data[idx]/0.0654,  1./0.728)
        _data[idx] = np.power(10, 1.772*np.log10(_data[idx])+2.403) #tentative result from kiost-nifs validation
        # GPS.gen_png_simple(_data, mask, vrange=[0.1,30], linear=None, opathbase=opathbase)
        GPS.gen_png_simple(_data, mask, vrange=[0.0,5.], linear=1, opathbase=opathbase)
        opathbase=ofbase  + '_TSMf'
        _data=np.copy(iop_f[:,:,3])
        idx = _data>0.
        _data[idx] = np.power(10, 0.786*np.log10(_data[idx])+2.005) #tentative result from kiost-nifs validation
        # GPS.gen_png_simple(_data, mask, vrange=[0.1,50], linear=None, opathbase=opathbase)
        GPS.gen_png_simple(_data, mask, vrange=[0.,10], linear=1, opathbase=opathbase)


        opathbase=ofbase  + '_agf'
        # GPS.gen_png_simple(iop[:,:,1], mask, vrange=[0.003,0.5],  opathbase=opathbase, coastline=None)
        GPS.gen_png_simple(iop_f[:,:,1], mask, vrange=[0.003,0.5],  opathbase=opathbase)
        # GPS.gen_png_simple(iop[:,:,1], mask, vrange=[0.0,0.5], linear=1, opathbase=opathbase, coastline=None)
        opathbase=ofbase + '_aflf'
        # GPS.gen_png_simple(iop[:,:,2], mask, vrange=[0.003,0.5],  opathbase=opathbase, coastline=None)
        GPS.gen_png_simple(iop_f[:,:,2], mask, vrange=[0.003,0.5],  opathbase=opathbase)
        # GPS.gen_png_simple(iop[:,:,2], mask, vrange=[0.0,0.5], linear=1, opathbase=opathbase, coastline=None)
        opathbase=ofbase  + '_adgf'
        vrange_adg=[0.01,1.0]#[0.003,0.5]
        # GPS.gen_png_simple(iop[:,:,1]+iop[:,:,2], mask, vrange=[0.03,1.0],  opathbase=opathbase, coastline=None)
        GPS.gen_png_simple(iop_f[:,:,1]+iop[:,:,2], mask, vrange=vrange_adg,  opathbase=opathbase)
        # GPS.gen_png_simple(iop[:,:,1]+iop[:,:,2], mask, vrange=[0.0,0.5], linear=1, opathbase=opathbase, coastline=None)
        opathbase=ofbase  + '_bbpf'
        GPS.gen_png_simple(iop_f[:,:,3], mask, vrange=[0.001,0.5], opathbase=opathbase)
        # GPS.gen_png_simple(iop[:,:,3], mask, vrange=[0.0003,0.05], opathbase=opathbase, coastline=None)
        # GPS.gen_png_simple(iop[:,:,3], mask, vrange=[0.0,0.5], linear=1, opathbase=opathbase, coastline=None)
        naer=niop-niopw#=4
        for iaer in range(naer):
            opathbase=ofbase  + f'_aero{iaer+1}'
            # GPS.gen_png_simple(iop[:,:,4], mask, vrange=[0.003,0.5], opathbase=opathbase, coastline=None)
            # GPS.gen_png_simple(iop[:,:,4], mask, vrange=[0.0,0.1], linear=1,opathbase=opathbase, coastline=None)
            GPS.gen_png_simple(iop[:,:,4+iaer], mask, vrange=[0.0,0.05], linear=1,opathbase=opathbase)
            if iaer==0:
                aerosum=iop[:,:,niopw+iaer]
            else: aerosum = aerosum+iop[:,:,niopw+iaer]

        opathbase=ofbase  + '_aerosum'
        # GPS.gen_png_simple(iop[:,:,5], mask, vrange=[0.003,0.5], opathbase=opathbase, coastline=None)
        # GPS.gen_png_simple(iop[:,:,4]+iop[:,:,5], mask, vrange=[0.0,0.3], linear=1, opathbase=opathbase, coastline=None)
        GPS.gen_png_simple(aerosum, mask, vrange=[0.0,0.1], linear=1, opathbase=opathbase)
        opathbase=ofbase  + '_relerr'
        GPS.gen_png_simple(relerr[:,:], mask, vrange=[0.0,0.1], linear=1, opathbase=opathbase)
        opathbase=ofbase  + '_niter'
        GPS.gen_png_simple(niter[:,:], mask, vrange=[0.0,2000], linear=1, opathbase=opathbase)
        opathbase=ofbase  + '_atobb'
        a2bb=np.zeros_like(iop_f[:,:,0])
        _a  = np.copy(iop_f[:,:,0])
        _bb = np.copy(iop_f[:,:,3])
        ind=_bb>0.
        a2bb[ind]=_a[ind]/_bb[ind];
        GPS.gen_png_simple(a2bb, mask, vrange=[0.1,20], linear=1, opathbase=opathbase)

        #dchl=10**(2.4/1.77-1)/relnorndif_f
        # opathbase=ofbase  + '_relnorm_aph'
        # GPS.gen_png_simple(relnormdif_f[:,:,0], mask, vrange=[0.0,1], linear=1, opathbase=opathbase, coastline=coastline)
        opathbase=ofbase  + '_rel_aph'
        idx=relnormdif_f[:,:,0]>1.e-6
        relaph=np.zeros_like(relnormdif_f[:,:,0])
        relaph[idx]=0.1/relnormdif_f[:,:,0][idx]
        GPS.gen_png_simple(relaph, mask, vrange=[0.1,1], linear=None, opathbase=opathbase)
        # idx=relnormdif_f[:,:,0]>1.e-6
        # dchl = np.zeros_like(relnormdif_f[:,:,0])
        # dchl[idx] =  10**(2.4/1.77)*0.05/relnormdif_f[:,:,0][idx]
        # opathbase=ofbase  + '_dchl'
        # GPS.gen_png_simple(dchl[:,:], mask, vrange=[0.01,20],  opathbase=opathbase, coastline=coastline)

        # opathbase=ofbase  + '_relnorm_adg'
        relnormdif_adg=relnormdif_f[:,:,1]*iop_f[:,:,1]+relnormdif_f[:,:,2]*iop_f[:,:,2]
        ind = (iop_f[:,:,1]+iop_f[:,:,2]) > 1.e-6
        relnormdif_adg[ind] = relnormdif_adg[ind]/(iop_f[:,:,1]+iop_f[:,:,2])[ind]
        reladg=np.zeros_like(relnormdif_adg)
        reladg[ind]=0.1/relnormdif_adg[ind]
        opathbase=ofbase  + '_rel_adg'
        GPS.gen_png_simple(reladg, mask, vrange=[0.1,1], linear=None, opathbase=opathbase)
        #dadg=0.1/relnorm
        # dadg = np.zeros_like(relnormdif_f[:,:,1])
        # idx = relnormdif_adg >1.e-6
        # dadg[idx] = 0.05/relnormdif_adg[idx]
        # opathbase=ofbase  + '_dadg'
        # GPS.gen_png_simple(dadg, mask, vrange=[0.01,1],  opathbase=opathbase, coastline=coastline)

        # opathbase=ofbase  + '_relnorm_bbp'
        # GPS.gen_png_simple(relnormdif_f[:,:,3], mask, vrange=[0.0,1], linear=1, opathbase=opathbase, coastline=coastline)
        idx=relnormdif_f[:,:,3]>1.e-6
        relbbp=np.zeros_like(relnormdif_f[:,:,3])
        relbbp[idx] = 0.1/relnormdif_f[:,:,3][idx]
        opathbase=ofbase  + '_rel_bbp'
        GPS.gen_png_simple(relbbp, mask, vrange=[0.1,1], linear=None, opathbase=opathbase)
        # dTSM=0.0786*10**(2.005)*bbp**(1-0.0786)*0.05/relnorm
        # idx=relnormdif_f[:,:,3]>1.e-6
        # dTSM = np.zeros_like(relnormdif_f[:,:,3])
        # dTSM[idx]=10**(1/0.0786)*0.05/relnormdif_f[:,:,3][idx]
        # opathbase=ofbase  + '_dTSM'
        # GPS.gen_png_simple(dTSM, mask, vrange=[0.1,50],  opathbase=opathbase, coastline=coastline)

        fiops=ofbase+'_iops'
        ncutils.write2nc(fiops+'.nc', iop, noproj=True)

        fiops=ofbase+'_iopw'
        ncutils.write2nc(fiops+'.nc', iop_f, noproj=True)

import re
if __name__=="__main__":
    # frhorc='/home/yp/Downloads/bluebon/250716_Bahrain/myout/250716_074255_stacked_warped_rhorc.tif'
    # subset=[2117,7643, 4440,9911]
    # subset=[1967.2,7562.5, 3550.1,10007.2]
    # sj, si, ej, ei = [int(_) for _ in subset]
    # ofbase='/home/yp/Downloads/bluebon/250716_Bahrain/myout/250716_074255_test'
    
    # frhorc='/home/yp/Downloads/bluebon/250626_Chesapeake/myout/250626_161648_stacked_warped_rhorc.tif'
    # ofbase='/home/yp/Downloads/bluebon/250626_Chesapeake/myout/250626_161648_stacked_warped_test'
    frhorc='/home/yp/Downloads/bluebon/250926_Khuvsgul/myout/250926_045459_stacked_warped_rhorc.tif'
    ofbase=re.sub(r'_[^_]*$','',frhorc, count=1)
    
    blkproc(frhorc, ofbase)