

import os,sys,time
import numpy as np
import flagging_bb

sys.path.append(r'./../../tools')
import gen_png_simple as GPS
import ncutils, tiffutils
from genrgb import gen_rgb

# --- PyCUDA initialization
import pycuda.driver as cuda
import pycuda.autoinit
from pycuda.compiler import SourceModule

import BBinvfit as invgpu

def iDivUp(a, b):
    return a // b + 1

def proc_rhorc2iop_by_fitting(rhorc, LUTratio,  amratio, ofbase,flagging=True,subset=None):
    print(f'.... file: {os.path.basename(__file__)}') 
    fncName=sys._getframe().f_code.co_name
    if flagging: flag, _flagarr = flagging_bb.flagging(rhorc)

    rhorc=np.ascontiguousarray(rhorc)
    # print(type(rhorc))
    print(np.shape(rhorc))
    # print(rhorc.flags)
    LUTratio=np.ascontiguousarray(LUTratio)
    amratio=np.ascontiguousarray(amratio)
    # print('LUTratio: '+' '.join([f'{_:.5f}' for _ in LUTratio[1549,2195,:]])); exit()

    nlin, npix, nb=np.shape(rhorc)

    mask=np.zeros((nlin,npix),dtype=np.uint8)
    # ind = rhorc[:,:,5]<1.e-6
    if flagging:
        ind = flag !=0
        mask[ind]=1
    else:
        print('in proc_rhorc2iop_by_fitting: mask not applied TEMPORARY!!')

    if subset is not None: #[ul_j,ul_i, lr_j, lr_i]
        print(f'...in {fncName}: Subsetting for ul_j,ul_i, lr_j, lr_i={subset}')
        ulj,uli,lrj,lri=subset
        mask[0:uli,:]=1; mask[lri:,:]=1
        mask[:,0:ulj]=1; mask[:,lrj:]=1

    stime = time.time()
    _s=time.strftime("%a, %d %b %Y %H:%M:%S",time.localtime(stime))
    print(f'...{fncName}: gpu optimization started at: {_s}')

    niop=6
    iop = np.zeros((nlin,npix,niop),dtype=np.float64)
    rhorc_mod = np.zeros_like(rhorc)
    Rrs_mod = np.zeros_like(rhorc)
    relerr=np.zeros((nlin,npix),dtype=np.float64)
    niter=np.zeros((nlin,npix),dtype=np.int32)
    Rrs_out = np.zeros_like(rhorc)

    niop_f=5 #second optimization for iopw+1 comps
    iop_f = np.zeros((nlin,npix,niop_f),dtype=np.float64)
    Rrs_mod_f = np.zeros_like(rhorc)
    relerr_f=np.zeros((nlin,npix),dtype=np.float64)
    niter_f=np.zeros((nlin,npix),dtype=np.int32)
    

    niopw=4
    relnormdif_f = np.zeros((nlin,npix,niopw),dtype=np.float64) #rel norm diff in Rrs_f due to [aph, ag, ad, bbp]

    BLOCKSIZE = 16#8 16 #32 #32 #256
    # --- Define a reference to the __global__ function and call it
    gpu_rhorc_fitting = invgpu.mod.get_function("gpu_rhorc_fitting_onestep")
    bDim  = (BLOCKSIZE, BLOCKSIZE, 1)
    gridDim   = (iDivUp(npix, BLOCKSIZE), iDivUp(nlin, BLOCKSIZE), 1) ## Caution (ncol, nrow)!

    
    gpu_rhorc_fitting(cuda.Out(iop),cuda.Out(rhorc_mod),cuda.Out(Rrs_mod),cuda.Out(relerr),cuda.Out(niter),cuda.Out(Rrs_out),\
        cuda.Out(iop_f),cuda.Out(Rrs_mod_f),cuda.Out(relerr_f),cuda.Out(niter_f),cuda.Out(relnormdif_f),\
        cuda.In(rhorc), cuda.In(LUTratio), cuda.In(amratio), cuda.In(mask),
        np.int32(nlin), np.int32(npix),
        block = bDim, grid = gridDim )

    cuda.Context.synchronize()

    etime=time.time()
    print(' time for rhorc2iop_gpu (sec): '+("{:.1f}".format(etime-stime)) )

    print('iop.shape:',np.shape(iop))
    print('Rrs_out.shape:',np.shape(Rrs_out))

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
        rhoa[:,:,ib]=rhorc[:,:,ib]-rhowSpec[:,:,ib]*np.power(tr[ib],amratio[:,:])
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
        GPS.gen_png_simple(_data, mask, vrange=[0.1,30], linear=None, opathbase=opathbase)
        opathbase=ofbase  + '_TSMf'
        _data=np.copy(iop_f[:,:,3])
        idx = _data>0.
        _data[idx] = np.power(10, 0.786*np.log10(_data[idx])+2.005) #tentative result from kiost-nifs validation
        GPS.gen_png_simple(_data, mask, vrange=[0.1,50], linear=None, opathbase=opathbase)


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
        
    return mask, Rrs_out, iop, relerr,niter, iop_f, relnormdif_f

if __name__=="__main__":
    frhorc='<WORK_ROOT>/Downloads/bluebon/250716_Bahrain/myout/250716_074255_stacked_warped_rhorc.tif'
    subset=[2117,7643, 4440,9911]
    subset=[1967.2,7562.5, 3550.1,10007.2]
    sj, si, ej, ei = [int(_) for _ in subset]

    rhorc = tiffutils.getraster(frhorc, None)
    
    
    rhorc = rhorc[:, si:ei+1, sj:ej+1]
    rhorc = np.transpose(rhorc,(1,2,0)).astype(np.float64)
    nlin, npix, nb =rhorc.shape

    _r=np.ones(nb,dtype=np.float64)
    am_r=1.
    amratio =np.ones((nlin,npix),dtype=np.float64)
    LUTratio=np.ones((nlin,npix,nb), dtype=np.float64)
    ofbase = '<WORK_ROOT>/Downloads/bluebon/250716_Bahrain/myout/250716_074255_subset_test'
    proc_rhorc2iop_by_fitting(rhorc, LUTratio,  amratio, ofbase,flagging=True,subset=None)