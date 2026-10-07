# ;LUT = array[10,10,19]
# ;LUT_ray
# ;LUT_aer1_a = r_a : aerosol reflectance
# ;LUT_aer1_s = r_sg: sunglint reflectancce
# ;LUT_aer1_d = r_dg: sky(diffuse) reflectance
# ;LUT_aer1_tu    =
# ;LUT_aer1_td    =
# ;LUT_aer1_sa    =
# ;LUT_aer2_....
import sys
sys.path.append('./../src')
import rsr_f0_bluebon as RFB
sys.path.append('./../../viirs/genLUT')
from read_6SspectralLoop_ex_columns_to_6stool import read_6SspectralLoop as R6S
import numpy as np

import sys
sys.path.append(r'../../g2l1bpy/LUT')
import read_Thuillier
def gen_bluebon_LUT():

    #read F0
    (_wave,_f0) = read_Thuillier.read_Thuillier_F0()# f0[wave]
    #read RSR
    wave0, rsr, _colnames = RFB.read_bb_srf()# 
    nb = rsr.shape[0]

#     ;interpolate f0 at wave0, wavelength for rsr
    f0 = np.interp(wave0, _wave, _f0)

#     ;rsr weighted band wavelength
#     wave_band = np.zeros(nb)
    wave_band = np.sum(wave0*rsr, axis=1)/np.sum(rsr, axis=1) #Numpy broadcasting
#     for i=0, nb-1 do wave_band[i]=total(wave0[*]*rsr[i,*])/total(rsr[i,*])

    inDir='/home/yp/6SV-1.1/batch_LUT_TOA_M70/' #14 columns (old) 

    st_aer    = ['1','2']
    naer = len(st_aer)
    st_aot    = '0.2'
    st_ws     = '5'
    st_mu0    = ['0.1','0.2','0.3','0.4','0.5','0.6','0.7','0.8','0.9','1']
    nmu0 = len(st_mu0)
    st_mus    = ['0.1','0.2','0.3','0.4','0.5','0.6','0.7','0.8','0.9','1']
    nmus = len(st_mus)
    st_ph         = ['0','10','20','30','40','50','60','70','80','90','100','110','120','130','140','150','160','170','180']
    nph = len(st_ph)

    LUT_ray = np.zeros((nmu0, nmus, nph, nb))
    LUT_aer = np.zeros((naer, nmu0, nmus, nph, nb))
    LUT_sun = np.zeros((naer, nmu0, nmus, nph, nb))
    LUT_sky = np.zeros((naer, nmu0, nmus, nph, nb))
    LUT_td  = np.zeros((naer, nmu0, nmus, nph, nb))
    LUT_tu  = np.zeros((naer, nmu0, nmus, nph, nb))
    LUT_sa  = np.zeros((naer, nmu0, nmus, nph, nb))
    s_aot = st_aot
    s_ws = st_ws

    #The order of next loops was corrected on 30 Nov 2010
    #LUTs generated before 30 Nov 2010 are wrong!!
    for imu0 in range(nmu0) :
        s_mu0 = st_mu0[imu0]
        for imus in range(nmus):
            s_mus = st_mus[imus]
            for iph in range(nph):
                s_ph = st_ph[iph]
                for iaer in range(naer):
                    s_aer = st_aer[iaer]

                    if iaer == 0 : #read Rayleigh
                        fname_Ray = 'spectralLoop_'+'mu0_'+s_mu0+'-mus_'+s_mus+'-ph_'+s_ph+'_Ray.dat'
                        fname = inDir+fname_Ray
                        wave_um, tgas, tdown, tup, sa, r_ra, F0temp, r_sg_sfc, r_t, tau_r, tau_a,_ = R6S( fname) 
                        print(fname)
                        r_ray = r_t
                        _wave = wave_um*1000.
                        #band average
                        _rayl=np.interp(wave0, _wave, r_ray)
                        # for ib in range(nb): 
                        #     LUT_ray[imu0, imus, iph,ib] =np.sum(_rayl*f0*rsr[ib,:])/np.sum(f0*rsr[ib,:])
                        LUT_ray[imu0, imus, iph,:] =np.sum(_rayl*f0*rsr, axis=1)/np.sum(f0*rsr, axis=1)
                    continue #rayleigh LUT only
                    
                    fname_aer = 'spectralLoop_'+'mu0_'+s_mu0+'-mus_'+s_mus+'-ph_'+s_ph+'-aern_'+s_aer+'-aot_'+s_aot+'-w_'+s_ws+'.dat'
                    fname = inDir+fname_aer
                    wave, tgas, tdown, tup, sa, r_ra, F0temp, r_sg_sfc, r_t, tau_r, tau_a, r_dsun = R6S(fname) 
                    #print, fname
                    r = r_ra - r_ray #r_a
                    _r = np.interp(wave0, _wave, r)
                    # for ib=0, nb-1 do LUT_aer[ib,iph,imus,imu0, iaer] =total(_r*f0*rsr[ib,*])/total(f0*rsr[ib,*])
                    LUT_aer[iaer,imu0,imus,iph,:]=np.sum(_r*f0*rsr, axis=1)/np.sum(f0*rsr, axis=1)

                    r = r_dsun;
                    _r = np.interp(wave0,_wave,r)
                    # for ib=0, nb-1 do LUT_sun[ib,iph,imus,imu0, iaer] =total(_r*f0*rsr[ib,*])/total(f0*rsr[ib,*])
                    LUT_sun[iaer,imu0,imus,iph,:] = np.sum(_r*f0*rsr,axis=1)/np.sum(f0*rsr,axis=1)

                    r = r_t-r_ra-r_dsun# sky glint
                    _r = np.interp(wave0,_wave, r)
                    # for ib=0, nb-1 do LUT_sky[ib,iph,imus,imu0, iaer] =total(_r*f0*rsr[ib,*])/total(f0*rsr[ib,*])
                    LUT_sky[iaer,imu0,imus,iph,:] = np.sum(_r*f0*rsr,axis=1)/np.sum(f0*rsr,axis=1)

                    r = tdown
                    _r = np.interp(wave0,_wave,r)
                    # for ib=0, nb-1 do LUT_td[ib,iph,imus,imu0, iaer] =total(_r*f0*rsr[ib,*])/total(f0*rsr[ib,*])
                    LUT_td[iaer,imu0,imus,iph,:] = np.sum(_r*f0*rsr,axis=1)/np.sum(f0*rsr,axis=1)

                    r = tup
                    _r = np.interp(wave0,_wave,r)
                    # for ib=0, nb-1 do LUT_tu[ib,iph,imus,imu0, iaer] =total(_r*f0*rsr[ib,*])/total(f0*rsr[ib,*])
                    LUT_tu[iaer,imu0,imus,iph,:] = np.sum(_r*f0*rsr,axis=1)/np.sum(f0*rsr,axis=1)

                    r = sa
                    _r = np.interp(wave0,_wave,r)
                    # for ib=0, nb-1 do LUT_sa[ib,iph,imus,imu0, iaer] =total(_r*f0*rsr[ib,*])/total(f0*rsr[ib,*])
                    LUT_sa[iaer,imu0,imus,iph,:] = np.sum(_r*f0*rsr,axis=1)/np.sum(f0*rsr,axis=1)
                    # res= check_math()
                    # if res ne 0 then begin
                    #     print, iaer, imu0, imus, iph
                    #     print, 'check_math', res
                    # endif


    odir = '/home/yp/myPy/bluebon/LUT/'
    str='wave_band='
    for i in range(nb):  
        str += ("%6.1f" % wave_band[i]).strip()+' '
    str += '\n'# add newline
    str +='phi(azimuth)='
    for i in range(nph): 
        str += st_ph[i]+ ' '
    str += '\n'# add newline

    str +='mus(sensor)='
    for i in range(nmus): 
        str += st_mus[i]+ ' '
    str += '\n' #add newline
    str +='mu0(solar)='
    for i in range(nmu0): str += st_mu0[i]+ ' '
    str += '\n' #add newline
    str_dims= ("%i" % nmu0)+' '+("%i" % nmus)+' '+("%i" % nph)+' '+ ("%i" % nb)
    # str_dims= 'dims='+string(nb,format='(i0)')+' '+string(nph,format='(i0)')+' '+string(nmus,format='(i0)')+' '+string(nmu0,format='(i0)')


    tail= ''

    #write Ray
    header = str+'dims='+str_dims+'\n'
    ofname=odir+'LUT_Ray'+tail
    write_LUT(ofname, header, LUT_ray)
    exit() #rayleigh only

    str += 'aer_models='
    for i in range(naer): str += st_aer[i]+' '
    str += '\n'
    str_dims = ('%i' % naer)+' '+str_dims
    header = str+'dims='+str_dims+'\n'

    #
    ofname=odir+'/LUT_aer'+tail
    write_LUT(ofname, header, LUT_aer)
    #
    ofname=odir+'/LUT_sun'+tail
    write_LUT(ofname, header, LUT_sun)
    #
    ofname=odir+'/LUT_sky'+tail
    write_LUT(ofname, header, LUT_sky)
    #
    ofname=odir+'/LUT_td'+tail
    write_LUT(ofname, header, LUT_td)
    #
    ofname=odir+'/LUT_tu'+tail
    write_LUT(ofname, header, LUT_tu)
    #
    ofname=odir+'/LUT_sa'+tail
    write_LUT(ofname, header, LUT_sa)


def write_LUT (ofname, header, data):
    with open(ofname+'.readme', "wt") as f:
        f.write(header)
    with open(ofname, "wb") as f:
        data.tofile(f)

# gen_bluebon_LUT()

