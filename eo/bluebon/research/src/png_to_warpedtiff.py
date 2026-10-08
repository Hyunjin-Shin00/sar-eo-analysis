#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jul  2 18:09:11 2025

@author: yp
"""

from osgeo import gdal

# png_path='<WORK_ROOT>/Downloads/bluebon/250626_Chesapeake/registered_band7_RGB0.png'
# tif_path='<WORK_ROOT>/Downloads/bluebon/250626_Chesapeake/temp.tif'
# warpedtif='<WORK_ROOT>/Downloads/bluebon/250626_Chesapeake/registered_band7_RGB0.tif'

# Input/output
png_path = '<WORK_ROOT>/Downloads/bluebon/250629_AndongDam/250629_023708_stacked_DN_RGB310.png'
warped_tif = '<WORK_ROOT>/Downloads/bluebon/250629_AndongDam/250629_023708_stacked_DN_RGB310.tif'


# Step 1: Open the PNG
src_ds = gdal.Open(png_path, gdal.GA_ReadOnly)

# Step 2: Create a memory copy so we can assign GCPs
mem_driver = gdal.GetDriverByName("MEM")
mem_ds = mem_driver.CreateCopy('', src_ds, strict=0)

# Step 3: Define and assign GCPs
# Add GCPs (pixel, line, x, y)
# gcps = [ #gcps for Chesapeake bay
#         gdal.GCP(-75.984604, 37.376722, 0, 2725.7,594.7),
#         gdal.GCP(-75.922833, 37.364066, 0, 3857.6,690.1),
#         gdal.GCP(-76.018268, 37.297689, 0, 2499.0,2522.4),
#         gdal.GCP(-75.938514, 37.280645, 0, 3964.7,2664.9),
#         gdal.GCP(-75.988540, 37.165131, 0 ,3622.7,5493.6),
#         gdal.GCP(-76.034741, 36.930154, 0, 3887.1,11081.8),
#         gdal.GCP(-76.249516, 36.953523, 0, 23.5,11219.4),
#         gdal.GCP(-76.169917,36.761451, 0, 2268.9,15413.1),
#         gdal.GCP(-76.084043,36.728818, 0, 3924.0,15899.0),

#         gdal.GCP(-75.98351, 37.38537, 0, 2706, 379),
#         gdal.GCP(-76.0905, 36.9076, 0, 3009, 11780),
#         gdal.GCP(-76.17634, 36.93279, 0, 1398, 11468),
#         gdal.GCP(-76.29467, 36.77759, 0, 10, 15434)
# ]

gcps = [
    gdal.GCP(128.940136, 36.905860, 0, 3682.6, 41.7),
    gdal.GCP(128.745926, 36.921330, 0, 207.8, 244.3),
    gdal.GCP(128.677553, 36.641338, 0, 297.2, 6900.6),
    gdal.GCP(128.866308, 36.609926, 0, 3763.4, 7089.5),
    gdal.GCP(128.748957, 36.568404, 0, 1893.1, 8379.4),
    gdal.GCP(128.771625, 36.242205, 0, 3786.0, 15840.7),
    gdal.GCP(128.579130, 36.277582, 0, 218.9, 15570.4),
]
mem_ds.SetGCPs(gcps, "")
mem_ds.SetMetadataItem('GCPProjection', 'EPSG:4326')

# Step 4: Warp from the GCP-tagged memory dataset
gdal.Warp(
    warped_tif,
    mem_ds,
    dstSRS='EPSG:4326',
    format='GTiff'
)
del mem_ds

print("✅ Warp complete. Output saved to:", warped_tif)

