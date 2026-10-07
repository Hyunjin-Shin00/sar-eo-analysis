import numpy as np
import sys
import pandas as pd
import pvlib
import os
import rasterio
import matplotlib.pyplot as plt
import datetime


sys.path.append(r'E:\TPX_2022\02_project\2025\07_블루본\11_L1B_to_L1C\01_code\sub')
sys.path.append('./../../tools')
import read_Thuillier


def read_bb_srf():
    fcsv_srf = r'E:\TPX_2022\02_project\2025\07_블루본\11_L1B_to_L1C\01_code\sub_data/Spectral Response Function.csv'
    df = pd.read_csv(fcsv_srf) #this fast
    column_names = df.columns.tolist()
    print('srf colnames:', column_names)
    waves = df['wavelength(nm)'].to_numpy()
    srf_data = df.iloc[:, 1:].to_numpy().transpose()
    return waves, srf_data, column_names


def compute_F0():
    wave0, rsr, col_names = read_bb_srf()
    wave_ave = np.sum(wave0*rsr, axis=1)/np.sum(rsr, axis=1)
    
    (_wave, _f0) = read_Thuillier.read_Thuillier_F0()
    f0 = np.interp(wave0, _wave, _f0*10)
    f0_ave = np.sum(f0*rsr, axis=1)/np.sum(rsr,axis=1)
    return f0_ave, wave_ave


def read_tiff(img_path) :
    file_list = [file for file in os.listdir(img_path) if file.endswith("gc_pc2.tiff")]
    file_list = sorted(file_list)
    ms_img = []
    for e, f_name in enumerate(file_list) :
        with rasterio.open(f'{img_path}/{f_name}') as src :
            data = src.read()
            # data = data/1000
            if e == 0 :
                profile_count_1 = src.profile
        data_tmp = data.reshape(data.shape[1], data.shape[2])
        ms_img.append(data_tmp)
        del data, data_tmp
    return ms_img, profile_count_1


def normalize(img):
    return (img-img.min())/(img.max()-img.min())


def contrast_stretching(img_1d, min, max) :
    band_small = np.nanpercentile(img_1d, min)
    band_large = np.nanpercentile(img_1d, max)
    img_cs = np.clip(img_1d, band_small, band_large)
    return img_cs


def save_f32_tiff(profile_count_1, rgb, path) :
    profile_count_1.update(count = rgb.shape[0])
    tif_tit = f'{path}/TOAR_stack.tiff'
    rgb = rgb.astype(np.float32)
    with rasterio.open(tif_tit, 'w', **profile_count_1) as dst :
        dst.write(rgb)
        dst.close()
    print("Save the tiff file.")


def bb_coregister_calibrate(indir, solzen, d_r):
    toa_l, profile = read_tiff(indir)
    order = [1, 2, 0, 3, 4, 5, 6, 7] #'MS1 MS2 PAN MS3 ... MS7' Radiance
    print('stacked band:', order)

    reordered = [toa_l[i] for i in order]
    stacked = np.stack(reordered, axis=0) # this order need to match the order os waves_bb and f0_bb
      
    f0_bb, waves_bb = compute_F0() # order MS1 MS2 ...MS7 PAN
    _idx = np.argsort(waves_bb) # rearrange the order of increasing wavelengths
    waves_bb = waves_bb[_idx]
    f0_bb = f0_bb[_idx]
 
    # waves_bb=[490, 560, 625, 665, 705, 740, 783, 842]   
    
    cth0 = np.cos(solzen*np.pi/180.)
    
    stacked = np.pi*stacked/f0_bb[:, None, None]/cth0*(d_r*d_r)
    # save_f32_tiff(profile, stacked, indir)
    return stacked, order, profile


def compute_solzen(time, lons, lats):
    if not isinstance(lons, np.ndarray):
        lons = np.array(lons); 
        lats = np.array(lats)
    zenith_list = []
    azimuth_list = []
    for la, lo in zip(lats.ravel(),lons.ravel()):
        solar_pos = pvlib.solarposition.get_solarposition(time, la, lo)
        zenith_list.append(solar_pos['zenith'].values[0])
        azimuth_list.append(solar_pos['azimuth'].values[0])

    # Reshape back to original shape
    zenith = np.array(zenith_list).reshape(lats.shape)
    azimuth = np.array(azimuth_list).reshape(lats.shape)
    return zenith, azimuth

def earthSun_distance_factor(doy):
    d_r = 1+0.033*np.cos (2.*np.pi*doy/365)
    return d_r
    

def gamma_correction(img_1d, gamma = 2.2) :
    img_gm = np.power(img_1d, 1/gamma)
    return img_gm


def save_f32_tiff(profile_count_1, ms, band, path) :
    profile_count_2 = profile_count_1.copy()
    profile_count_2.update(dtype = 'float32')

    for n, tmp in enumerate(ms) :
        tif_tit = f'{path}/MS{band[n]}_toal.tiff'
        tmp = tmp.astype(np.float32)
        with rasterio.open(tif_tit, 'w', **profile_count_2) as dst :
            dst.write(tmp, 1)
            dst.close()
    print("Save the tiff file.")


if __name__=="__main__":
    
    date = '251001_185010'
    # indir = f'E:/TPX_2022/02_project/2025/07_블루본/03_촬영영상/capture-{date}/imagery/radiometric'; 
    indir = f"E:/TPX_2022/02_project/2025/07_블루본/11_L1B_to_L1C/03_test/{date}" 
    timestr = datetime.datetime(int(f'20{date[:2]}'), int(date[2:4]), int(date[4:6]), int(date[7:9]), int(date[9:11]), int(date[11:])).strftime("%Y-%m-%dT%H:%M:%SZ")
    tdi_arr = [2, 4, 8, 8, 16, 16, 16, 4]

    # 1) solzen, d_r
    cen_lon, cen_lat = [-114.65, 32.35] # (E, N)
    time = pd.Timestamp(timestr)
    zenith_arr, azimuth_arr = compute_solzen(time, [cen_lon], [cen_lat])
    solzen = zenith_arr[0]
    d_r = earthSun_distance_factor(time.dayofyear)
    
    # 2) F0 & TOAR
    stacked, band, profile = bb_coregister_calibrate(indir, solzen, d_r)
    for n in range(stacked.shape[0]) :
        print(f'MS{band[n]} min : {stacked[n, :, :].min()}, max : {stacked[n, :, :].max()}, mean : {stacked[n, :, :].mean()}')

    # 3) Save tiff
    save_f32_tiff(profile, stacked, band, indir)

    # 4) Save RGB png
    cs_min = 0.0001; cs_max = 99.9999; # cs_min = 0.5; cs_max = 99; #구름 : cs_max = 90; 
    r_c = contrast_stretching(stacked[3, :, :], cs_min, cs_max)
    g_c = contrast_stretching(stacked[1, :, :], cs_min, cs_max)
    b_c = contrast_stretching(stacked[0, :, :], cs_min, cs_max)

    gm = 2.2 # 2.2
    r_c = gamma_correction(r_c, gm)
    g_c = gamma_correction(g_c, gm)
    b_c = gamma_correction(b_c, gm)
    
    r_c_n = normalize(r_c)
    g_c_n = normalize(g_c)
    b_c_n = normalize(b_c)
    rgb_toar = np.dstack([r_c_n, g_c_n, b_c_n])
    # plt.imshow(rgb_toar) ; plt.show()
    
    plt.imsave(f'{indir}/{date}_TOAL_rgb.png', rgb_toar) ; 
    del r_c, g_c, b_c, r_c_n, g_c_n, b_c_n, rgb_toar, stacked
