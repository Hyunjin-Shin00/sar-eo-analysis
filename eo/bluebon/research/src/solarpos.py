#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jul  8 15:55:17 2025

@author: yp
"""

# import numpy as np
# from numpy.polynomial.polynomial import polyfit, polyval2d



# # Define polyfit2d helper:
# def polyfit2d(x, y, z, deg):
#     import itertools
#     x = np.asarray(x)
#     y = np.asarray(y)
#     z = np.asarray(z)

#     ncols = (deg + 1) * (deg + 2) // 2
#     G = np.zeros((x.size, ncols))
#     ij = list(itertools.combinations_with_replacement(range(deg+1), 2))
#     for k, (i,j) in enumerate(ij):
#         G[:,k] = (x**i) * (y**j)
#     m, _, _, _ = np.linalg.lstsq(G, z, rcond=None)
#     return m

# def polyval2d(x, y, m, deg):
#     import itertools
#     x = np.asarray(x)
#     y = np.asarray(y)

#     ij = list(itertools.combinations_with_replacement(range(deg+1), 2))
#     z = np.zeros_like(x, dtype=np.float64)
#     for a, (i,j) in zip(m, ij):
#         z += a * x**i * y**j
#     return z


# def compute_lonlats_grid_from_gcps(gcps, H, W, step):
#     lons = gcps[:, 0]
#     lats = gcps[:, 1]
#     jpixels = gcps[:, 3]  # x-axis
#     ipixels = gcps[:, 4]  # y-axis

# # Fit up to 2nd-order polynomial (you can try higher if needed)
#     deg = 2
#     coeffs_lon = polyfit2d(jpixels, ipixels, lons, deg)
#     coeffs_lat = polyfit2d(jpixels, ipixels, lats, deg)
    
#     H, W = 1000, 1000  # example size of image
#     step = 5

#     x_pix, y_pix = np.meshgrid(np.arange(0, W, step), np.arange(0, H, step))
    
#     lat_grid = polyval2d(x_pix, y_pix, coeffs_lat, deg)
#     lon_grid = polyval2d(x_pix, y_pix, coeffs_lon, deg)
    
#     return lon_grid, lat_grid

from osgeo import gdal
import numpy as np
def lonlat_fr_gcps(gcps, rasterYSize, rasterXSize, step):
    # Assume you already have a list of gdal.GCP objects
    
    
    # Convert GCPs to geotransform
    gt = gdal.GCPsToGeoTransform(gcps)
    
    # gt: (x0, dx, dx_skew, y0, dy_skew, dy)
    # represents affine transform from pixel (jpix, ipix) to projected coords

    H, W = rasterYSize, rasterXSize
    
    x_pix, y_pix = np.meshgrid(np.arange(0, W, step), np.arange(0, H, step))
    
    # Apply the affine geotransform
    x_geo = gt[0] + x_pix * gt[1] + y_pix * gt[2]
    y_geo = gt[3] + x_pix * gt[4] + y_pix * gt[5]
    return x_geo, y_geo

import pandas as pd
import pvlib

def compute_solzen(time, lons, lats):
    zenith_list=[]
    azimuth_list=[]
    for la, lo in zip(lats.ravel(),lons.ravel()):
        solar_pos = pvlib.solarposition.get_solarposition(time, la, lo)
        zenith_list.append(solar_pos['zenith'].values[0])
        azimuth_list.append(solar_pos['azimuth'].values[0])

    # Reshape back to original shape
    zenith = np.array(zenith_list).reshape(lats.shape)
    azimuth = np.array(azimuth_list).reshape(lats.shape)
    
    # compute_sza = lambda la, lo: pvlib.solarposition.get_solarposition(time, la, lo)['zenith'].values[0]
    # v_compute_sza = np.vectorize(compute_sza)
    # zenith = v_compute_sza(lats, lons)
    # compute_azi = lambda la, lo: pvlib.solarposition.get_solarposition(time, la, lo)['azimuth'].values[0]
    # v_compute_azi = np.vectorize(compute_azi)
    # azimuth = v_compute_azi(lats, lons)
    
    return zenith, azimuth

def earthSun_distance_factor(doy):
    d_r = 1+0.033*np.cos (2.*np.pi*doy/365)
    return d_r

if 0:#__name__=="__main__":
    
    gcps = [ #gcps for Chesapeake bay
            gdal.GCP(-75.984604, 37.376722, 0, 2725.7,594.7),
            gdal.GCP(-75.922833, 37.364066, 0, 3857.6,690.1),
            gdal.GCP(-76.018268, 37.297689, 0, 2499.0,2522.4),
            gdal.GCP(-75.938514, 37.280645, 0, 3964.7,2664.9),
            gdal.GCP(-75.988540, 37.165131, 0 ,3622.7,5493.6),
            gdal.GCP(-76.034741, 36.930154, 0, 3887.1,11081.8),
            gdal.GCP(-76.249516, 36.953523, 0, 23.5,11219.4),
            gdal.GCP(-76.169917,36.761451, 0, 2268.9,15413.1),
            gdal.GCP(-76.084043,36.728818, 0, 3924.0,15899.0),
    
            gdal.GCP(-75.98351, 37.38537, 0, 2706, 379),
            gdal.GCP(-76.0905, 36.9076, 0, 3009, 11780),
            gdal.GCP(-76.17634, 36.93279, 0, 1398, 11468),
            gdal.GCP(-76.29467, 36.77759, 0, 10, 15434)
    ]
    
    lons, lats = lonlat_fr_gcps(gcps, 16000, 4096, 100) #
    
    # Specify time (UTC)
    time = pd.Timestamp('2025-06-26T16:16:48Z')  # UTC
    
    zenith, azimuth = compute_solzen(time, lons, lats)
    
    print(np.min(zenith), np.max(zenith))
    
    doy=time.dayofyear
    earthSun_distance_factor(doy)
