#bluebone image-based dehazing
#bright cloud pixel mask keeping land with threshold b483 > 0.6
#moving quantile 10 percentile: q10 over large kernel size 1000
#rhoa(b483) = rhot-q10
#moving average of rhoa

import numpy as np
import sys
sys.path.append('./../../tools')
import ncutils
from genrgb import gen_rgb
import re

def mask_cloud(refl):
    nb,nlin,npix = refl.shape #bsq
    mask = np.zeros((nlin, npix), dtype='uint8')
    idx = refl[0,:,:] > 0.6
    mask[idx]=1
    for ib in range(nb):
        idx = refl[ib,:,:]<0.0001
        mask[idx]=1
    return mask

from scipy import ndimage

def fill_nearest(arr):
    mask = np.isnan(arr)
    # indices of nearest non-nan elements
    idx = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return arr[tuple(idx)]

# import box_average2 as BA
# def wrap_boxaverage(img, msk_clean, boxsize, q):
#     moved to box_average2.py


import moving_percentile as MP
import moving_average as MA

import masked_histogram as MH
if 0:#__name__=="__main__":
    # fnc = '<WORK_ROOT>/Downloads/bluebon/250928_Thai_KKairport/myout/250928_041857_stacked_rhot.nc'
    fnc = '<WORK_ROOT>/Downloads/bluebon/251022_TakhliAP/myout/251022_042629_stacked_rhot.nc'
    img = ncutils.getimage(fnc, bip=False)
    msk1 = mask_cloud(img)
    msk_clean=1-msk1
    # _=gen_rgb(np.copy(img), mask=1-msk, ofilepath='./test_msk', bds=[2,1,0])
    # full, coarse = MP.local_percentile_interpolated(img[0,:,:], msk, q=10, window=1001, stride=500, min_count=10000)
    # _=gen_rgb(full, mask=1-msk, ofilepath='./full')
    # _=gen_rgb(img[0,:,:]-full, mask=None, ofilepath='./aero_nomask')
    # img[0,:,:]-full
    
    # #never try next, too long!
    # mean_map = MA.moving_average_masked(img[0,:,:]-full, 1-msk, window=101, min_count=1000)
    # _=gen_rgb(mean_map, mask=1-msk, ofilepath='./mean_aero')
    
    # full2, coarse, cnt = BA.box_average_no_overlap_interpolated(
    #     image=img[0,:,:]-full, mask=msk, box=100, min_count=1000, upsample="bilinear"  )
    # _=gen_rgb(full2, mask=1-msk, ofilepath='./mean_aero2')
    
    
    boxsize=500
    q=20
    
    rhot_ave, rhot_p = wrap_boxaverage(img, msk_clean==1, boxsize, q)
    rhoa=np.array(rhot_ave)-np.asarray(rhot_p)[:,None,None]
    
    # _=gen_rgb(img[:,:,:]-rhoa, mask=None, ofilepath='./test_enhanced',bds=[2,1,0])#,data4alpha=msk)
    # _=gen_rgb(rhoa, mask=None, ofilepath='./rhoa',bds=[2,1,0])
    
    rhoa[2]=rhoa[1]
    img_enc1 = img[:,:,:]-rhoa
   
    header = ncutils.readheader(fnc)
    fnc_enc = re.sub(r'(?=_[^_]*$)', '_enc', fnc, count=1)
    ncutils.writeSpecData2file_2nc(img_enc1, fnc_enc, waves=header['waves'])
    _=gen_rgb(img_enc1, mask=msk1, ofilepath=re.sub(r'(?<!^)\.([^./\\:]*$)', '',fnc_enc),bds=[2,1,0])#,data4alpha=msk)
    
    #histogram img[0,:,:]-rhoa excluding mask
    
    hist, edges, centers, n = MH.masked_histogram(img_enc1[0], mask=(msk1==0), bins=200, range=None)
    print(f"Included {n} valid pixels")
    
    import matplotlib.pyplot as plt
    plt.figure()
    plt.step(centers, hist, where="mid")
    plt.xlabel("Value")
    plt.ylabel('Count')
    plt.title('Histogram (step)')
    plt.tight_layout()
    plt.show()
    
    array=img_enc1[0]
    valid = (msk1==0) & np.isfinite(array)
    # idx = valid & (array > 0.39) #depend on boxsize
    idx = valid & (array > 0.2) 
    msk=np.copy(msk1)
    msk[idx]=1
    msk_clean=1-msk
    
    boxsize=50; q=20
    rhot_ave, rhot_p = wrap_boxaverage(img, msk_clean==1, boxsize, q)
    rhoa1=np.array(rhot_ave)-np.asarray(rhot_p)[:,None,None]
    
    rhoa_f = (rhoa+rhoa1)/2.
    rhoa_f[2]=rhoa_f[1]
    img_enc = img[:,:,:]-rhoa_f
   
    fnc_enc2 = re.sub(r'(?=_[^_]*$)', '_enc2', fnc, count=1)
    _=gen_rgb(img_enc, mask=msk, ofilepath=re.sub(r'(?<!^)\.([^./\\:]*$)', '',fnc_enc2),bds=[2,1,0])#,data4alpha=msk)
    ncutils.writeSpecData2file_2nc(img_enc, fnc_enc2, waves=header['waves'])
    
    import pc1_share as PS
    share_map, corr_part = PS.compute_share_maps_with_interpolation(
        img, box_h=128, box_w=128, overlap_h=0.5, overlap_w=0.5, valid_mask=(msk_clean==1)
    )
    print("share_map shape:", share_map.shape)   # (n_boxes_h, n_boxes_w)
    print("corr_part shape:", corr_part.shape)   # (B, H, W)
    print("median share (ignoring NaN):", np.nanmedian(share_map))
    _=gen_rgb(np.abs(corr_part), mask=None, ofilepath='./corr_part',bds=[2,1,0])
