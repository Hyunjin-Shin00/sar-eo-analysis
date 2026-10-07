# cloud and land flagging Preliminary
import numpy as np

def flagging(refl, flag_in=None, debris=None):
#input refl[nb, nlin, npix]
#flag, flagarr=flagarr

    if refl.ndim !=3:
        print("refl must have 3 dims!")
        return
    nlin,npix,nb=refl.shape
    if nb != 7:
        print("nb is wrong:", nb)
        return
    blu=0; gre=1; red=2; nir=6
    #planetscope/PS2: Blue: 455 - 515 nm Green: 500 - 590 nm Red: 590 - 670 nm NIR: 780 - 860 nm
    #waves=[485, 545, 630, 820]
    #bands : (0)470, (1)510, (2)640, (3)857, (4)1610, (5)2260
    #msi: 492, 559, 665, 833
    #bb = [483.2, 562.4, 664.6, 704.8, 739.2, 781.9, 836.6]
    land_thresh  = 0.13 #0.1 #0.06; at 630nm 0.13 for msi B490 JSShoal
    land_thresh2  = 0.2#0.16#0.09
    cloud_thresh = 0.22#0.2 # at 812nm  and see below refl_b0 < 10*refl_b5
    if flag_in is not None:
        flag=flag_in
    else:
        flag = np.zeros((nlin, npix), dtype='uint8')

    flagarr = np.zeros( ((nlin,npix)+(8,)), dtype='uint8' )
    _flag = flag

    #land
    
    #idx = ( ((refl[:,:,2] > land_thresh) & (refl[:,:,3] > land_thresh)) | (refl[:,:,3]>land_thresh2))
    # idx = (refl[:,:,2]>land_thresh) | (refl[:,:,3]>land_thresh2)
    #idx = (refl[:,:,2]>land_thresh) & (refl[:,:,3]-refl[:,:,2] < -0.01)
    idx = (refl[:,:,5]>land_thresh) & (refl[:,:,5]> land_thresh) & (refl[:,:,nir]>refl[:,:,2] ) #for rhorc
    if debris:
        # idx = idx | (refl[:,:,3]> land_thresh2)
        idx = idx | ( (refl[:,:,nir]>refl[:,:,2]) & (refl[:,:,3]>0.24) )#for ex turbid water ganghwa 20220810 
    if np.count_nonzero(idx)>0: #if len(idx[0]) > 0:
        _flag[idx]=1
        flagarr[:,:,0]=_flag
        _flag[:,:]=0
    #cloud
    idx = ((refl[:,:,nir] > cloud_thresh) & (refl[:,:,2] > cloud_thresh) & (refl[:,:,0] < 2.*refl[:,:,3])  ) #need to check
    if np.count_nonzero(idx)>0: #if len(idx[0]) > 0:
        _flag[idx]=1
        flagarr[:,:,1]=_flag
        _flag[:,:]=0

    #no observation
    idx = (refl[:,:,0] < 0.0001)
    if np.count_nonzero(idx)>0:
        _flag[idx]=1
        flagarr[:,:,7]=_flag
        
        #0: land
        #1: cloud
        #2: floating algae or landcontam
        #3: variation
        #4: cloud edge, goci_specific
        #6: ext turbid
        #7: no observation
        #128B #64B #32B  #16B
    flag =  flagarr[:,:,0]*0x80 \
        | flagarr[:,:,1]*0x40 \
        | flagarr[:,:,2]*0x20 \
        | flagarr[:,:,7]*0x01

    return (flag, flagarr)