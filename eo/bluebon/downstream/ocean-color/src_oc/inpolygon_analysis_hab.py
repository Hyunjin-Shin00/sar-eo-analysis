#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jul  4 16:57:11 2025
extract data for polygons from a geojson file
@author: yp
"""

import rasterio
from rasterio.features import rasterize
from shapely.geometry import Polygon
from shapely.ops import transform
import json
import numpy as np
from pyproj import Transformer

def inpolygons_to_pixelcoords(ftif,fjson):
    # Open raster to get transform and shape
    with rasterio.open(ftif) as src:
        transform_raster = src.transform
        height, width = src.height, src.width
        # print(transform_raster, height, width)
        raster_crs = src.crs.to_string()
        
    with open(fjson) as f:
        jdata = json.load(f)

    # Extract all sub-polygons from the one feature
    rings = jdata["features"][0]["geometry"]["coordinates"]
    
    # Step 3: Create coordinate transformer (from EPSG:4326 → raster CRS)
    transformer = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)

    pixel_map = []

    for i, ring_coords in enumerate(rings):
        # Create a polygon from each ring
        geom_wgs84 = Polygon(ring_coords)
        geom_utm = transform(transformer.transform, geom_wgs84)
    
        # Rasterize it
        mask = rasterize(
            [(geom_utm, 1)],
            out_shape=(height, width),
            transform=transform_raster,
            fill=0,
            dtype="uint8"
        )
    
        # Extract pixel coordinates
        rows, cols = np.where(mask == 1)
        pixels = list(zip(rows, cols))
        
        pixel_map.append({
            "ring_id": i,
            "pixel_coords": pixels
        })
    
    # print(pixel_map[0]['pixel_coords'])
    return pixel_map, rings

import ast
import sys
sys.path.append('./../../tools')
import ncutils, tiffutils
def inpolygon_pixel2data_tif(ftif, pixel_map):
    data = tiffutils.getraster(ftif, None)
    
    data_pixels=[]
    for i, ring in enumerate(pixel_map):
       rows, cols = zip(*ring['pixel_coords'])
       rows=np.array(rows)
       cols=np.array(cols)
       data_pixels.append(data[:,rows,cols])
    return data_pixels
    
def inpolygon_pixel2data_nc(fnc, pixel_map):
    data = ncutils.getimage(fnc)

    data_pixels=[]
    for i, ring in enumerate(pixel_map):
       rows, cols = zip(*ring['pixel_coords'])
       rows=np.array(rows)
       cols=np.array(cols)
       data_pixels.append(data[:,rows,cols])
       
    return data_pixels
    
def get_waves_tif(ftif):
    with rasterio.open(ftif) as src:
        # print("Metadata:", src.meta)
        # print("Tags:", src.tags())
        _str = src.tags()['waves']
        if _str is None:
            return None
        waves=np.fromstring(_str.strip('[]'), sep=' ')    
    return waves

def get_waves_nc(fnc):
    return ncutils.readheader(fnc)['waves']

def compute_mean_std(data_pixels,minv=None):
    means=[]
    stds =[]
    for i,data in enumerate(data_pixels):
        print(data.shape)
        data[data < minv]=np.nan
        _mean=np.nanmean(data,axis=1)
        means.append(_mean)
        _std=np.nanstd(data,axis=1)
        stds.append(_std)
    return means, stds
        
import matplotlib.pyplot as plt
def to_graph(data_pixels, waves, rtype):
    marker_list = ['o', 's', '^', 'v', '*', 'D', 'x', '+', 'h', 'p']
    means, stds = compute_mean_std(data_pixels)
    fig, ax = plt.subplots(dpi=100)
    for i, (_mean, _std) in enumerate(zip(*[means,stds])):     
        marker = marker_list[i % len(marker_list)]
        line, = ax.plot(waves,_mean, f'-{marker}',mfc='none', label=f'area_{i}')
        # ax.errorbar(waves, y=_mean, yerr=_std, fmt='none', ecolor=line.get_color(), capsize=4, capthick=1)
        ax.fill_between(waves, _mean-_std, _mean+_std, color=line.get_color(), alpha=0.3)
    ax.set_xticks(waves)    
    ax.set_xticklabels(waves, rotation=70)
    ax.legend()
    # ax.set_tile('')
    ax.set_xlabel('Wavelength (nm)')
    ax.set_ylabel(f'{rtype}')
    plt.tight_layout()
    plt.show()
# import numpy as np
# import matplotlib.pyplot as plt

def plot_two_hist_twin_counts(a, b, vmin, vmax, bins=40):
    # 1) Common bin edges
    edges = np.linspace(vmin, vmax, bins + 1)

    # 2) Clean NaNs and compute counts (no density)
    a = np.asarray(a).ravel()
    b = np.asarray(b).ravel()
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]

    ha, edges = np.histogram(a, bins=edges, density=False)
    hb, _     = np.histogram(b, bins=edges, density=False)

    # 3) Plot with twin y-axes
    centers = 0.5 * (edges[:-1] + edges[1:])
    fig, ax1 = plt.subplots(figsize=(7, 4))

    label_1="Bluebon"
    label_2="GOCI-II"
    (l1,) = ax1.step(centers, ha, where="mid", label=label_1, color="tab:blue")
    ax1.set_xlabel("Value")
    ax1.set_ylabel(f"Count ({label_1})")
    ax1.set_xlim(vmin, vmax)

    ax2 = ax1.twinx()
    (l2,) = ax2.step(centers, hb, where="mid", label=label_2, color="tab:orange", linestyle="--")
    ax2.set_ylabel(f"Count ({label_2})")

    # Single legend for both axes
    lines = [l1, l2]
    labels = [ln.get_label() for ln in lines]
    ax1.legend(lines, labels, loc="best")

    fig.tight_layout()
    return fig, (ax1, ax2)
    
from scipy.interpolate import interp1d
from scipy.stats import linregress
    
if 0:#__name__=="__main__":
    # ftif = '/home/yp/Downloads/bluebon/250626_Chesapeake/250626_161648_stacked_warped_rhot.tif' ; ncfile=False
    # # fnc = '/media/yp/T7_msi/msi_for_bluebon/20250628_T18SUF_ChesapeakeS/myout/MSI_res20m_rhot.nc'; ncfile=True
    # # ftif = '/media/yp/T7_msi/msi_for_bluebon/20250628_T18SUF_ChesapeakeS/T18SUF_20250628T154819_B05.jp2'
    # fjson = '/home/yp/myPy/zview/src_zv/polygon_bb_Chesapeake_land.json'
    
    # ftif = '/home/yp/Downloads/bluebon/250629_Andong/myout_rhot_intercal/250629_023708_stacked_warped_rhot.tif' ; ncfile=False
    # fnc = '/media/yp/T7_msi/msi_for_bluebon/20250627_T52SDF_Andong/myout/MSI_res20m_rhot.nc'; ncfile=True
    # ftif='/media/yp/T7_msi/msi_for_bluebon/20250627_T52SDF_Andong/T52SDF_20250627T020711_B05.jp2'
    # fnc = '/home/yp/Downloads/bluebon/250629_Andong_PS/files_myout/20250629_024028_75_2539_3B_AnalyticMS_8b_clip_deb_rhot.nc'; ncfile=True
    # ftif ='/home/yp/Downloads/bluebon/250629_Andong_PS/files/20250629_024028_75_2539_3B_AnalyticMS_8b_clip.tif'
    
    # rtype='rhorc'
    # ftif = f'/home/yp/Downloads/bluebon/250629_Andong/250629_023708_stacked_warped_{rtype}.tif'; ncfile=False
    # # fnc = f'/home/yp/Downloads/bluebon/250629_Andong_PS/files_myout/20250629_024028_75_2539_3B_AnalyticMS_8b_clip_deb_{rtype}.nc'; ncfile=True
    # # ftif ='/home/yp/Downloads/bluebon/250629_Andong_PS/files/20250629_024028_75_2539_3B_AnalyticMS_8b_clip.tif'
    # fjson = '/home/yp/myPy/zview/src_zv/polygon_Andong.json'
    
    # rtype='rhot'
    # ftif = f'/home/yp/Downloads/bluebon/250712_Seoul/myout/250712_024621_stacked_warped_{rtype}.tif'; ncfile=False
    # # fnc=f'/home/yp/Downloads/bluebon/250712_Seoul_msi/myout/MSI_res20m_{rtype}.nc'; ncfile=True
    # # ftif='/home/yp/Downloads/bluebon/250712_Seoul_msi/T52SCG_20250712T022131_B05.jp2'
    # fjson = '/home/yp/myPy/zview/src_zv/polygon_Seoul.json'
    
    # rtype='rhorc'
    # ftif = f'/home/yp/Downloads/bluebon/250716_Bahrain/myout/250716_074255_stacked_warped_{rtype}.tif'; ncfile=False
    # # fnc=f'/home/yp/Downloads/bluebon/250717_Bahrain_msi/myout/MSI_res20m_{rtype}.nc'; ncfile=True
    # # ftif='/home/yp/Downloads/bluebon/250717_Bahrain_msi/T39RVJ_20250717T070651_B05.jp2'
    # fjson = '/home/yp/myPy/zview/src_zv/polygon_Bahrain.json'
    
    rtype='rhot'
    ftif = f'/home/yp/Downloads/bluebon/250806_SoffSydney/myout/250806_002855_stacked_warped_{rtype}.tif'; ncfile=False
    # fnc=f'/home/yp/Downloads/bluebon/250806_SoffSydney_msi/myout/MSI_res20m_{rtype}.nc'; ncfile=True
    # ftif='/home/yp/Downloads/bluebon/250806_SoffSydney_msi/T56HLH_20250806T000219_B05.jp2'
    ftif = f'/home/yp/Downloads/bluebon/250806_SoffSydney_msi/myout/MSI_res20m_merged_{rtype}.tif'; ncfile=False
    fjson = '/home/yp/myPy/zview/dist/polygon_SoffSydney.json'
    
    rtype='rhot'
    # ftif = f'/home/yp/Downloads/bluebon/250903_Namhae/myout/250903_023532_stacked_warped_{rtype}.tif'; ncfile=False
    fnc = f'/home/yp/Downloads/bluebon/250903_Namhae_msi_T52SCD/myout/MSI_res20m_{rtype}.nc' ; ncfile=True
    ftif = '/home/yp/Downloads/bluebon/250903_Namhae_msi_T52SCD/T52SCD_20250903T021529_B05.jp2'
    fjson = '/home/yp/myPy/zview/dist/polygon_Namhae_noglint.json'
    
    pixel_map, rings =  inpolygons_to_pixelcoords(ftif,fjson)
    
    if not ncfile:
        data_pixels = inpolygon_pixel2data_tif(ftif, pixel_map)
        waves = get_waves_tif(ftif)
    else:
        data_pixels = inpolygon_pixel2data_nc(fnc, pixel_map)
        waves = get_waves_nc(fnc)
    
    # 
    to_graph(data_pixels, waves, rtype)
    
if 0: #for hRE comparison    
    
    #Namhae--rho_t
    rtype='hRE'
    ftif1 = f'/home/yp/Downloads/bluebon/250903_Namhae/myout_hRE/250903_023532_stacked_warped_{rtype}.tif'; ncfile=False
    ftif2 = f'/media/yp/T9/GOCI2_Data/temp/20250903_03/GK2_GOCI2_L1B_20250903_031500_RLA_S0007_HG_{rtype}.tif'
    fjson = '/home/yp/myPy/zview/dist/polygon_Yeosu-man.json'
    
    #bluebon
    pixel_map, rings =  inpolygons_to_pixelcoords(ftif1,fjson)
    data_pixels_1 = inpolygon_pixel2data_tif(ftif1, pixel_map)
    waves1 = get_waves_tif(ftif1)
    mean1, std1 = compute_mean_std(data_pixels_1, minv=0.001)
    
    #msi
    pixel_map, rings =  inpolygons_to_pixelcoords(ftif2,fjson)
    data_pixels_2 = inpolygon_pixel2data_tif(ftif2, pixel_map)
    # waves2 = get_waves_tif(ftif2)
    # data_pixels = inpolygon_pixel2data_tif(ftif2, pixel_map)
    # waves2 = get_waves_tif(ftif2)
    mean2, std2 = compute_mean_std(data_pixels_2, minv=0.001)
    

    plot_two_hist_twin_counts(data_pixels_1[0], data_pixels_2[0], 0.001, 0.03, bins=40)
    
    #msi-to-blubon inter/extra polation
    means_sim=[]
    for _mean in mean2:
        f = interp1d(waves2, _mean, kind='linear', fill_value='extrapolate')
        _mean_sim = f(waves1)
        means_sim.append(_mean_sim)
    
    if len(waves1)==8: #include pan band
        bandnames = ['PAN']+[f'MS{ib}' for ib in range(1,8)]
        bandnames = np.array(bandnames)[[1,2,0,3,4,5,6,7]]
    else:
        bandnames = np.array([f'MS{ib}' for ib in range(1,8)])
    
    marker_list = ['o', 's', '^', 'v', '*', 'D', 'x', '+', 'h', 'p']
    
    means_sim=np.array(means_sim)
    mean1=np.array(mean1)     
    fig, ax = plt.subplots(dpi=100)
    for ib in range(len(waves1)):
        marker = marker_list[ib % len(marker_list)]
        y = means_sim[:,ib]
        x = mean1[:,ib]
        # Linear regression
        m, b, r_value, p_value, std_err = linregress(x, y)
        x_line = np.linspace(min(x), max(x), 100)
        y_line = m * x_line + b
        rsq=r_value*r_value

        sc=ax.scatter(x, y, marker=marker,label=f'{bandnames[ib]}: y={m:.3e}x+{b:.3e} (r2={rsq:.3f})')#, label=f'band_{ib}')
        ax.plot(x_line, y_line, color=sc.get_facecolor())
    
    plt.ylabel('MSI_sim')
    plt.xlabel('Bluebon')
    plt.legend();
        
