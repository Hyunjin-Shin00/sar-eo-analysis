import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import os, sys
import rasterio
from skimage.registration import phase_cross_correlation
from scipy.ndimage import shift
import gc
from rasterio.transform import Affine



def calculate_statistics(channel_array, saturation_max):
    pixels = channel_array.flatten()
    stats = {
        'Min': np.min(pixels),
        'Max': np.max(pixels),
        'Mean': round(np.mean(pixels), 1),
        'Median': np.median(pixels),
        'Std': round(np.std(pixels), 1),
        'Saturation(min) pixel': np.sum((pixels == 0)),
        'Saturation(max) pixel': np.sum((pixels == saturation_max))
    }
    return stats, pixels


def normalize(img):
    return (img-img.min())/(img.max()-img.min())


def normalize_3d(rgb_img):
    r = normalize(rgb_img[:, :, 0])
    g = normalize(rgb_img[:, :, 1])
    b = normalize(rgb_img[:, :, 2])
    rgb_nor = np.dstack([r, g, b])
    return rgb_nor


def radiometric_cal_par(correction_file_path, band, TDI, lp = 667) :
    correction = pd.read_csv(correction_file_path)
    df_2d = correction.to_numpy()
    
    dark_list = []
    coefficients_ms = []
    intercepts_ms = []


    for t, b in enumerate(band) :
        if b == 0 :
            band_i = 'PAN'
        else :
            band_i = f'MS{b}'
        
        cutch = np.where((correction['BAND'] == band_i) & (correction['Line rate'] == lp) & (correction['TDI'] == TDI[t]))[0]
        cutch0 = np.where((correction['BAND'] == band_i) & (correction['Line rate'] == lp) & (correction['TDI'] == TDI[t]) & (correction['lmap_level'] == 0))[0]
        I = df_2d[cutch, 6]
        I = I.reshape(-1, 1)
        dn = df_2d[cutch, 10:]
        for i in range(len(cutch)) :
            if df_2d[cutch[i+1], 9] - df_2d[cutch[i], 9] != 0 :
                break

        if i == 0 :
            I_ch = I[:-1, :]
            dn_ch = dn[:-1, :]
        else :
            I_ch = I[(i+1):-1, :]
            dn_ch = dn[(i+1):-1, :]
        
        dark = df_2d[cutch0, 10:]
        dn_dark = dn_ch - dark
        dark_list.append(dark)

        coefficients_ = []
        intercepts_ = []
        for i in range(dn_dark.shape[1]):
            X_0 = dn_dark[:, i].reshape(-1, 1)
            model_0 = LinearRegression() ;
            model_0.fit(X_0, I_ch)
            coefficients_.append(model_0.coef_[0, 0])
            intercepts_.append(model_0.intercept_[0])
        coefficients_ms.append(coefficients_)
        intercepts_ms.append(intercepts_)
        print(f'MS{b} Radiometric correction parameters get')
        del I, dn, I_ch, dn_ch, dark, dn_dark, coefficients_, intercepts_, model_0
    return dark_list, coefficients_ms, intercepts_ms


def ch_min_max(TDI) :
    saturation_v = []
    for tdi in TDI :
        if tdi == 1 :
            min_ms = -1023 ; max_ms = 1023 ; 
        elif tdi == 2 :
            min_ms = -2026 ; max_ms = 2026 ; 
        elif tdi == 4 :
            min_ms = -4032 ; max_ms = 4032 ; 
        else :
            min_ms = -4095 ; max_ms = 4095 ; 
        saturation_v.append(np.array([min_ms, max_ms]))
    return saturation_v


def dark_correction(ms_img, dark_list) :
    ms_dark_img = []
    for n, ms in enumerate(ms_img) :
        ms_dark = ms - dark_list[n]
        ms_dark_img.append(ms_dark.astype(float))
    return ms_dark_img
    

def radiometric_cal(img_list, coefficients_ms, intercepts_ms) :
    ms_dark_rc_img = []
    for n, img in enumerate(img_list) :
        c = coefficients_ms[n]
        i = intercepts_ms[n]
        ms_dark_rc = (img * np.array(c)) + np.array(i)
        ms_dark_rc_img.append(ms_dark_rc.astype('float32'))
    return ms_dark_rc_img


def read_tiff(img) :
    with rasterio.open(img) as src :
        raw_image = src.read(1).astype(np.float32)
    return raw_image


def pixel_shift(ms_img, band) :
    j = band.index(1)
    shift_px = []
    for s in range(len(band)) :
        shift_est, error, diffphase = phase_cross_correlation(ms_img[j], ms_img[s], upsample_factor=10)
        shift_ms1_2 = [round(x) for x in list(shift_est)]
        # (dx, dy), response = cv2.phaseCorrelate(ms_img[s], ms_img[j])
        # shift_ms1_2 = [round(x) for x in [dy, dx]]
        shift_px.append(shift_ms1_2)
    return shift_px


def ms_matching(ms_data, shift_px) : # ms_dark_rc_img, ms_shift_img[1]
    if len(ms_data) > 5 :
        jj = band.index(6)
    else :
        jj = np.argmax(abs(np.array(shift_px)[:, 0]))
    img_sh_crip = []
    for i, img_ in enumerate(ms_data) :
        img_s = shift(img_, shift = shift_px[i])
        if (shift_px[jj][0] >= 0) and (shift_px[jj][1] >= 0) :
            img_sh_crip.append(img_s[shift_px[jj][0]:, shift_px[jj][1]:])
        elif (shift_px[jj][0] >= 0) and (shift_px[jj][1] < 0) :
            img_sh_crip.append(img_s[shift_px[jj][0]:, :shift_px[jj][1]])
        elif (shift_px[jj][0] < 0) and (shift_px[jj][1] >= 0) :
            img_sh_crip.append(img_s[:shift_px[jj][0], shift_px[jj][1]:])
        elif (shift_px[jj][0] < 0) and (shift_px[jj][1] < 0) :
            img_sh_crip.append(img_s[:shift_px[jj][0], :shift_px[jj][1]])
        # if shift_px[jj][1] > 0 :
        #     img_sh_crip.append(img_s[:shift_px[jj][0], shift_px[jj][1]:])
        # elif shift_px[jj][1] < 0 :
        #     img_sh_crip.append(img_s[:shift_px[jj][0], :shift_px[jj][1]])
        # elif shift_px[jj][1] == 0 :
        #     img_sh_crip.append(img_s[:shift_px[jj][0], :])
    return img_sh_crip


def rgb_save(rgb_sh, path, direction, tit = 'DN') :
    if direction == 1 : 
        rgb_sh = np.fliplr(rgb_sh)
    elif direction == 0 :
        rgb_sh = np.flipud(rgb_sh)
    
    rgb_sh_norm = normalize_3d(rgb_sh)
    plt.imsave(f'{path}/{tit}.png', rgb_sh_norm, dpi = 200)
    print(f'{tit} RGB image saves.')
    del rgb_sh, rgb_sh_norm


def save_12bit_tiff(profile_count_1, ms, path, band, direction, tit) :
    profile_count_1.update(width=ms[0].shape[1])
    profile_count_1.update(height=ms[0].shape[0])
    if direction == 1 :
        profile_count_1.update(transform=Affine(1.0, 0.0, 0.0, 0.0, -1.0, 0.0))
    elif direction == 0 :
        profile_count_1.update(transform=Affine(-1.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    
    for n, tmp in enumerate(ms) :
        tif_tit = f'{path}/MS{band[n]}_{tit}.tiff'
        if direction == 1 :
            tmp = np.fliplr(tmp)
        elif direction == 0 :
            tmp = np.flipud(tmp)
        tmp_nor = normalize(tmp)
        tmp_12bit = (tmp_nor * 4095).astype(np.uint16)
        with rasterio.open(tif_tit, 'w', **profile_count_1) as dst :
            dst.write(tmp_12bit, 1)
            dst.close()
    print("Save the tiff file.")


def contrast_stretching(img_1d, min, max) :
    band_small = np.nanpercentile(img_1d, min)
    band_large = np.nanpercentile(img_1d, max)
    img_cs = np.clip(img_1d, band_small, band_large)
    return img_cs


def gamma_correction(img_1d, gamma = 2.2) :
    img_gm = np.power(img_1d, 1/gamma)
    return img_gm


def prnu_calibration(ms_shift_img, window = 21) :
    prnu_gain_v = []
    for b, bb in enumerate(ms_shift_img) : 
        ms_v_mean = np.mean(bb, axis = 0)
        prnu_gain_v.append(corr_table(ms_v_mean))

    prnu_gain_v_mv = []
    for b in range(len(prnu_gain_v)) :
        mv_v = mvr(np.array(prnu_gain_v[b]), window)
        offset_v = np.array(prnu_gain_v[b])/mv_v
        prnu_gain_v_mv.append(offset_v)
    
    prnu_img = []
    for b, bb in enumerate(ms_shift_img) :
        prnu_img.append(bb * prnu_gain_v_mv[b])
    return prnu_img


def save_f32_tiff(profile_count_1, ms, path, band, direction, tit) :
    profile_count_2 = profile_count_1.copy()
    profile_count_2.update(dtype = 'float32')
    profile_count_2.update(width=ms[0].shape[1])
    profile_count_2.update(height=ms[0].shape[0])
    if direction == 1 :
        profile_count_2.update(transform=Affine(1.0, 0.0, 0.0, 0.0, -1.0, 0.0))
    elif direction == 0 :
        profile_count_2.update(transform=Affine(-1.0, 0.0, 0.0, 0.0, 1.0, 0.0))

    for n, tmp in enumerate(ms) :
        tif_tit = f'{path}/MS{band[n]}_{tit}_float32.tiff'
        if direction == 1 :
            tmp = np.fliplr(tmp)
        elif direction == 0 :
            tmp = np.flipud(tmp)
        
        tmp = tmp.astype(np.float32)
        with rasterio.open(tif_tit, 'w', **profile_count_2) as dst :
            dst.write(tmp, 1)
            dst.close()
    print("Save the tiff file.")


def radiometric_calibration(bluebon_path, band, tdi, direction, lp, band_width) :
    new_path = bluebon_path + '/radiometric'
    if not os.path.exists(new_path) : 
        os.mkdir(new_path)
    ms_img, profile_count_1 = read_tiff(bluebon_path)
    for n, bb in enumerate(ms_img) :
        print(f'DN - MS{band[n]} min : {bb.min()}, max : {bb.max()}, mean : {bb.mean()}')
    shift_px = pixel_shift(ms_img, band)     
    j = band.index(1)
    gc.collect() ; 
    
    
    # statistic
    saturation_v = ch_min_max(tdi)
    pixels = []
    for n, img in enumerate(ms_img) :
        stats, pixel = calculate_statistics(img, saturation_v[n][1])
        df = pd.DataFrame([stats], index=[f'MS{band[n]}'])
        if n == 0 :
            df_con = df.copy(deep = True)
        else :
            df_con = pd.concat([df_con, df], axis = 0)
        pixels.append(pixel)     

    indx_sp = [f'MS{f}' for f in band]
    sp = pd.DataFrame(shift_px, index = indx_sp, columns = ['shift pixel_y', 'shift pixel_x'])
    df_con_sp = pd.concat([df_con, sp], axis = 1)


    # check saturation pixel
    band_sat_p = {}
    for b, tmp_img in enumerate(ms_img) :
        mx = saturation_v[b][1]
        sat_p = tmp_img == mx
        saturation_ratio = np.sum(sat_p) / tmp_img.size*100
        if saturation_ratio > 0 :
            band_sat_p[b] = sat_p
        del tmp_img, saturation_ratio, sat_p, mx
    gc.collect()
    

    # Radiometric Calibration
    correction_file_path = '<WORK_ROOT>/prep/src/03_code/sub/FM1_mean_output_PRNU_check.csv' # Correction data path
    dark_list, coefficients_ms, intercepts_ms = radiometric_cal_par(correction_file_path, band, tdi, lp)

    ms_dark_img = dark_correction(ms_img, dark_list) # dark correction
    ms_dark_rc_full = radiometric_cal(ms_dark_img, coefficients_ms, intercepts_ms) # Radiometric Correction
    
    dark_c = []
    for n, bb in enumerate(ms_dark_img) :
        print(f'Dark correction - MS{band[n]} min : {bb.min()}, max : {bb.max()}, mean : {bb.mean()}')
        dark_c.append([round(bb.min(), 1), round(bb.max(), 1), round(bb.mean(), 1)])
    gc.collect()
    sp = pd.DataFrame(dark_c, index = indx_sp, columns = ['dark_c_min', 'dark_c_max', 'dark_c_mean'])
    df_con_sp = pd.concat([df_con_sp, sp], axis = 1)

    ms_dark_rc_img = []
    for n, bb in enumerate(ms_dark_rc_full) :
        ms_dark_rc_img.append(bb/band_width[band[n]])
    
    for n, bb in enumerate(ms_dark_rc_img) :
        print(f'Gain correction - MS{band[n]} min : {bb.min()}, max : {bb.max()}, mean : {bb.mean()}')
    
    # saturation pixel to maximum radiance
    if len(band_sat_p) > 0 :
        for b, p in band_sat_p.items() :
            ms_dark_rc_img[b][p] = ms_dark_rc_img[b][p].max()

    # residual_prnu_coef_ms1 = 'E:/TPX_2022/02_project/2025/07_블루본/03_촬영영상/02_code/MS1_residul_prnu_coef.dat'
    # residual_prnu_coef_ms2 = 'E:/TPX_2022/02_project/2025/07_블루본/03_촬영영상/02_code/MS2_residul_prnu_coef.dat'

    # if 1 in band :
    #     rpc_ms1 = np.loadtxt(residual_prnu_coef_ms1)
    #     ms_dark_rc_img[j] = ms_dark_rc_img[j] * rpc_ms1[None, :]

    # if 2 in band :
    #     rpc_ms2 = np.loadtxt(residual_prnu_coef_ms2)
    #     ms_dark_rc_img[j+1] = ms_dark_rc_img[j+1] * rpc_ms1[None, :]
    
    ms_dark_rc_shift_img = ms_matching(ms_dark_rc_img, shift_px)
    prnu_img = prnu_calibration(ms_dark_rc_shift_img, window = 21)
    ms_dark_rc_prnu_rgb = np.dstack([prnu_img[j+2], prnu_img[j+1], prnu_img[j]])
    rgb_save(ms_dark_rc_prnu_rgb, new_path, direction, tit = 'DN_dark_rc_prnu_rp')
    
    st_rad = []
    for n, bb in enumerate(prnu_img) :
        print(f'PRNU correction - MS{band[n]} min : {bb.min()}, max : {bb.max()}, mean : {bb.mean()}')
        st_rad.append([bb.min(), bb.max(), bb.mean()])
    gc.collect()
    sp = pd.DataFrame(st_rad, index = indx_sp, columns = ['radiance_min', 'radiance_max', 'radiance_mean'])
    df_con_sp_rd = pd.concat([df_con_sp, sp], axis = 1)
    df_con_sp_rd.to_excel(f'{new_path}/rgb_statistics.xlsx') 

    save_12bit_tiff(profile_count_1, prnu_img, new_path, band, direction, tit = 'DN_dark_rc_p')
    save_f32_tiff(profile_count_1, prnu_img, new_path, band, direction, tit = 'DN_dark_rc_p')

    ms_shift_img_lr = np.fliplr(ms_dark_rc_prnu_rgb)
    
    del ms_img, ms_dark_img, ms_dark_rc_full, ms_dark_rc_img, ms_dark_rc_shift_img, prnu_img, ms_dark_rc_prnu_rgb
    print('Finish a radiometric calibration.')
    return ms_shift_img_lr, profile_count_1


def corr_table(data_sub_mean):
    corr_data = []
    norm = data_sub_mean.mean()
    for i in range(len(data_sub_mean)):
        corr_data.append(norm/data_sub_mean[i])
    return corr_data


def mvr(data, window_size):
    if window_size % 2 == 0:
        window_size += 1    
    mv_avg = np.zeros_like(data)
    for j in range(data.shape[0]):
        mv_avg[j] = np.mean(data[max(0, j-(window_size - 1)//2):j+(window_size + 1)//2], axis=0)
    return mv_avg



# Main
if __name__ == '__main__':
    
    rFile=f"{sys.argv[3]}/MS3_DN_dark_rc_p.tiff"
    gFile=f"{sys.argv[3]}/MS2_DN_dark_rc_p.tiff"
    bFile=f"{sys.argv[3]}/MS1_DN_dark_rc_p.tiff"

    ms_r = read_tiff(rFile)
    ms_g = read_tiff(gFile)
    ms_b = read_tiff(bFile)

    cs_min = float(sys.argv[1])
    cs_max = float(sys.argv[2])
    #cs_min = 0.0001; cs_max = 99.9999; #default 99.999 / 구름 : cs_max = 95;
    #cs_min = 0.01; cs_max = 95.0;
    r_c = contrast_stretching(ms_r, cs_min, cs_max)
    g_c = contrast_stretching(ms_b, cs_min, cs_max)
    b_c = contrast_stretching(ms_b, cs_min, cs_max)
    
    gm = 2.2 # 2.2, contrast X 6.2
    r_c = gamma_correction(r_c, gm)
    g_c = gamma_correction(g_c, gm)
    b_c = gamma_correction(b_c, gm)
    
    r_c_n = normalize(r_c)
    g_c_n = normalize(g_c)
    b_c_n = normalize(b_c)
    ms_shift_cs_n = np.dstack([r_c_n, g_c_n, b_c_n])
    #plt.imshow(ms_shift_cs_n) ; plt.show()

    l1b_path = os.path.dirname(rFile)    
    plt.imsave(f'{l1b_path}/DN_dark_rc_cs{cs_min}_{cs_max}_gm{gm}_pc_v.png', ms_shift_cs_n)
    print(f'[Img save] {l1b_path}/DN_dark_rc_cs{cs_min}_{cs_max}_gm{gm}_pc_v.png')