#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul 10 15:08:45 2025
Exercise unwarped gcps
@author: yp
"""

from osgeo import gdal, osr
import numpy as np

def is_georeferenced(ftif):
    ds = gdal.Open(ftif)
    gt = ds.GetGeoTransform()
    gcps = ds.GetGCPs()

    has_geotransform = not np.allclose((tuple(abs(x) for x in gt)), (0, 1, 0, 0, 0, 1))
    has_gcps = len(gcps) > 0

    
    print(has_geotransform, has_gcps)
    if has_geotransform:
        return "Warped (georeferenced via affine transform)"
    elif has_gcps:
        return "Unwarped (GCPs only)"
    else:
        return "Not georeferenced"

ftif = '/home/yp/Downloads/bluebon/250626_Chesapeake/250626_161648_stacked_nowarp_rhot.tif'
# ftif = '/home/yp/Downloads/bluebon/250626_Chesapeake/250626_161648_stacked_warped_rhot_RGB710.png'
print(is_georeferenced(ftif))

# np.allclose((0.0, 1.0, 0.0, 0.0, 0.0, 1.0),(0, 1, 0, 0, 0, -1))

def gcps_pixel_to_lonlat(ftif, jpix, ipix, inverse=False):
    ds = gdal.Open(ftif)
    gcps = ds.GetGCPs()
    gcp_srs = ds.GetGCPProjection()

    geo_transform = gdal.GCPsToGeoTransform(gcps)


    src_srs = osr.SpatialReference()
    src_srs.ImportFromWkt(gcp_srs)
    src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst_srs = osr.SpatialReference()
    dst_srs.ImportFromEPSG(4326)
    dst_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    
    if not inverse:
        transform = osr.CoordinateTransformation(src_srs, dst_srs)
    else:
        transform = osr.CoordinateTransformation(dst_srs, src_srs)
    
    #single pixel
    # x = geo_transform[0] + jpix * geo_transform[1] + ipix * geo_transform[2]
    # y = geo_transform[3] + jpix * geo_transform[4] + ipix * geo_transform[5]
    # lon, lat, _ = transform.TransformPoint(x, y)
    if not inverse:
        def pixels_to_lonlat(jpix_list, ipix_list, geotransform, coord_transform):
            x_geo = geotransform[0] + jpix_list * geotransform[1] + ipix_list * geotransform[2]
            y_geo = geotransform[3] + jpix_list * geotransform[4] + ipix_list * geotransform[5]
            lonlat = [coord_transform.TransformPoint(x, y)[:2] for x, y in zip(x_geo, y_geo)]
            return lonlat
        
        lonlat = pixels_to_lonlat(jpix, ipix, geo_transform, transform)
    else:
        
        def lonlat_to_pixels(lons, lats, geotransform, coord_transform):
            xy_proj = [coord_transform.TransformPoint(x, y)[:2] for x, y in zip(lons, lats)]
            x_proj, y_proj = zip(*xy_proj)
            det = geotransform[1] * geotransform[5] - geotransform[2] * geotransform[4]
            if det == 0:
                raise ValueError("GeoTransform is not invertible")
            
            dx = np.array([x - geotransform[0] for x in x_proj])
            dy = np.array([y - geotransform[3] for y in y_proj])
        
            jpix = (dx * geotransform[5] - dy * geotransform[2]) / det
            ipix = (dy * geotransform[1] - dx * geotransform[4]) / det
        
            return jpix, ipix
        
        lonlat=lonlat_to_pixels(jpix, ipix, geo_transform, transform)
        
    return lonlat

jpix = np.array([100, 200, 300])
ipix = np.array([50,  60,  70])
lonlat=gcps_pixel_to_lonlat(ftif, jpix, ipix)
print(lonlat)


lons, lats = zip(*lonlat)
jipix=gcps_pixel_to_lonlat(ftif, lons, lats, inverse=True)
print(jipix)
# print([(x, y) for x, y in zip(*xylist)])
