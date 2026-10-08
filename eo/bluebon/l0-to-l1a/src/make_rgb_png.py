# 방사보정 TIFF를 이용해 contrast/gamma 조절된 RGB PNG를 생성하는 코드

import os
import re
import sys
import shutil
import numpy as np
import rasterio
import matplotlib.pyplot as plt


def normalize(img):
    img_min = np.min(img)
    img_max = np.max(img)
    if img_max == img_min:
        return np.zeros_like(img, dtype=np.float32)
    return (img - img_min) / (img_max - img_min)


def contrast_stretching(img, cs_min, cs_max):
    # cs_min/cs_max 백분위수 범위 밖의 값을 클리핑
    # cs_min 높일수록 어두운 픽셀을 더 많이 날림 → 전체적으로 밝아짐
    # cs_max 낮출수록 밝은 픽셀을 더 많이 날림 → 대비 강화, 과포화 억제
    vmin = np.nanpercentile(img, cs_min)
    vmax = np.nanpercentile(img, cs_max)
    return np.clip(img, vmin, vmax)


def gamma_correction(img, gamma=2.2):
    # gamma > 1: 중간톤이 어두워짐 (자연스러운 모니터 표준은 2.2)
    # gamma 높일수록 전체적으로 어두워지고 과포화 완화
    # gamma 낮출수록 (1.0 방향) 전체적으로 밝아짐
    # 반드시 normalize 후 [0,1] 범위에서 적용해야 음수값으로 인한 NaN 방지
    return np.power(img, 1.0 / gamma)


def read_band(tif_path):
    with rasterio.open(tif_path) as src:
        return src.read(1).astype(np.float32), src.profile


def save_colorbalance_tiff(l1b_path, r, g, b, profile):
    # 기하보정에 사용할 12bit colorbalance TIFF 저장 (MS3=R, MS2=G, MS1=B)
    p = profile.copy()
    p.update(dtype='uint16', width=r.shape[1], height=r.shape[0])
    for band_num, img in [(3, r), (2, g), (1, b)]:
        tif_path = os.path.join(l1b_path, f'MS{band_num}_colorbalance.tiff')
        img_12bit = (np.clip(img, 0, 1) * 4095).astype(np.uint16)
        with rasterio.open(tif_path, 'w', **p) as dst:
            dst.write(img_12bit, 1)
        print(f'Saved: {tif_path}')


def make_rgb_png(bluebon_path, cs_min, cs_max, gamma, r_scale, g_scale, b_scale, save_tiff, upload):
    l1b_path = bluebon_path + '/radiometric'

    red_path = os.path.join(l1b_path, 'MS3_DN_dark_rc_p_float32.tiff')
    green_path = os.path.join(l1b_path, 'MS2_DN_dark_rc_p_float32.tiff')
    blue_path = os.path.join(l1b_path, 'MS1_DN_dark_rc_p_float32.tiff')

    r, profile = read_band(red_path)
    g, _       = read_band(green_path)
    b, _       = read_band(blue_path)

    # 1단계: contrast stretching - 백분위수 범위로 클리핑
    r = contrast_stretching(r, cs_min, cs_max)
    g = contrast_stretching(g, cs_min, cs_max)
    b = contrast_stretching(b, cs_min, cs_max)

    # 2단계: normalize - [0, 1] 범위로 정규화 (gamma 적용 전 필수)
    r = normalize(r)
    g = normalize(g)
    b = normalize(b)

    # 3단계: gamma correction - 중간톤 밝기 조절
    r = gamma_correction(r, gamma)
    g = gamma_correction(g, gamma)
    b = gamma_correction(b, gamma)

    # 4단계: 밴드별 스케일 조절 - 특정 색이 강하면 해당 밴드를 낮춤
    # 초록이 강할 때: g_scale 낮춤 (0.6~0.9)
    # 붉은기가 강할 때: r_scale 낮춤
    # 파란기가 강할 때: b_scale 낮춤
    # 반대로 특정 색을 더 살리려면 해당 scale을 1.0 이상으로 높임 (최대 ~1.5)
    r = np.clip(r * r_scale, 0, 1)
    g = np.clip(g * g_scale, 0, 1)
    b = np.clip(b * b_scale, 0, 1)

    rgb = np.dstack([r, g, b])

    out_filename = f'DN_dark_rc_cs{cs_min}_{cs_max}_g{gamma}_rs{r_scale}_gs{g_scale}_bs{b_scale}.png'

    # radiometric 폴더에 PNG 저장 (항상 자동)
    out_png = os.path.join(l1b_path, out_filename)
    plt.imsave(out_png, rgb)
    print(f'Saved: {out_png}')

    # colorbalance TIFF 저장 (save_tiff=True일 때만)
    if save_tiff:
        save_colorbalance_tiff(l1b_path, r, g, b, profile)

    # 같은 날짜/시간의 upload 폴더에도 PNG 복사 (upload=True일 때만)
    if not upload:
        return
    # gray tiff 파일명(예: 260318_071833_0_gray.tiff)에서 YYMMDD_HHMMSS 추출
    upload_base = '<WORK_ROOT>/prep/data/upload'
    gray_files = [f for f in os.listdir(bluebon_path) if re.match(r'\d{6}_\d{6}_\d+_gray\.tiff', f)]
    if gray_files:
        datetime_str = '_'.join(gray_files[0].split('_')[:2])  # 예: 260318_071833
        upload_dir = os.path.join(upload_base, datetime_str)
        if os.path.isdir(upload_dir):
            shutil.copy2(out_png, os.path.join(upload_dir, out_filename))
            print(f'Copied: {upload_dir}/{out_filename}')
        else:
            print(f'Warning: upload 폴더를 찾을 수 없음 ({upload_dir})')
    else:
        print('Warning: gray tiff 파일을 찾을 수 없어 upload 폴더 매칭 불가')


if __name__ == '__main__':
    bluebon_path = sys.argv[1]
    save_tiff = False  # colorbalance TIFF도 저장하려면 True 변경 / False -> 그냥 항상 false로 해두면 됨
    # =============================================
    # 조절 파라미터
    # =============================================
    cs_min = 0.1       # 어두운 쪽 클리핑 백분위수. 높일수록 밝아짐
    cs_max = 75     # 밝은 쪽 클리핑 백분위수. 낮출수록 대비 강화
    gamma = 2.2      # 중간톤 밝기. 높일수록 어두워짐, 낮출수록 밝아짐
    r_scale = 1.0    # Red 밝기 배율. 낮추면 붉은기 억제
    g_scale = 0.9    # Green 밝기 배율. 낮추면 초록 억제 (권장 범위: 0.6~0.9)
    b_scale = 1.0    # Blue 밝기 배율. 낮추면 파란기 억제
    upload = True     # upload 폴더에도 PNG 저장하려면 True 변경 / False
    # =============================================

# 코드 입력 예시     python make_rgb_png.py <WORK_ROOT>/prep/data/20260323_Bab_al_Mandab_Strait

    make_rgb_png(bluebon_path, cs_min, cs_max, gamma, r_scale, g_scale, b_scale, save_tiff, upload)
