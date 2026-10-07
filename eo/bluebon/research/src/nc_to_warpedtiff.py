#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jul  2 18:09:11 2025
from nc to warped tiff with gcps
::nc -> memory(tif)->add gcps -> warp
@author: yp
"""

from osgeo import gdal, gdal_array, osr
import numpy as np
import sys
sys.path.append('./../../tools')
import ncutils
from genrgb import gen_rgb
def ncgcp_to_warp(fnc, gcps_ll, warped_tif, epsg_no, no_warp=False, no_Pan=True):
    # Read nc file
    header = ncutils.readheader(fnc)
    waves = header['waves']
    indata, scale, offset = ncutils.getimage(fnc, bip=False, noScale=True)
    if no_Pan:
        idx_nopan=[0,1,3,4,5,6,7]
        waves=waves[idx_nopan]
        indata=indata[idx_nopan]
        header['waves']=waves

    if len(indata.shape)==2: #2D
        indata = indata[np.newaxis,:,:]
    nb, ny, nx = indata.shape
    
    # Specify compression options (e.g., LZW compression)
    # co_opt = [
    #     # "COMPRESS=None",       # No Compression
    #     # "COMPRESS=LZW",       # LZW Compression
    #     "COMPRESS=DEFLATE",       # png-level? Compression
    #     "TILED=YES",          # Tile the output for better performance (optional)
    #     "PREDICTOR=2"         # Predictor for better compression (optional)
    # ]

    # Define source (WGS84) and target (UTM) projections
    src_srs = osr.SpatialReference()
    src_srs.ImportFromEPSG(4326)
    src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    
    # epsg = 32618  # UTM zone 18N for example
    utm_srs = osr.SpatialReference()
    utm_srs.ImportFromEPSG(epsg_no)
    utm_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    
    transform = osr.CoordinateTransformation(src_srs, utm_srs)
    gcps_utm = [
        gdal.GCP(*transform.TransformPoint(lon, lat), jpix, ipix)
        for lon, lat, _, jpix, ipix in gcps_ll
    ]

    # Create a new GeoTIFF file with the same dimensions as the PNG file
    mem_driver = gdal.GetDriverByName('MEM')
    gdal_dtype = gdal_array.NumericTypeCodeToGDALTypeCode(indata.dtype)
    mem_ds = mem_driver.Create('',nx, ny, nb, gdal_dtype)#, options=co_opt)
    # geotiff_ds = driver.CreateCopy(fouttif, png_ds, options=co_opt)
    
    mem_ds.SetMetadata(header)
    # Copy the PNG data to the new GeoTIFF file
    scalelist=[]
    offsetlist=[]
    for i in range(nb):
        banddata = indata[i,:,:]
        mem_ds.GetRasterBand(i+1).WriteArray(banddata)
        if waves is not None:
            mem_ds.GetRasterBand(i+1).SetDescription(f"{waves[i]}")
        if scale is not None:
            mem_ds.GetRasterBand(i+1).SetScale(scale)
            scalelist.append(scale)
        if offset is not None:
            mem_ds.GetRasterBand(i+1).SetOffset(offset)
            offsetlist.append(offset)
    
    mem_ds.SetGCPs(gcps_utm, utm_srs.ExportToWkt())
    mem_ds.SetMetadataItem('GCPProjection', f'EPSG:{epsg_no}')
    
    if no_warp:
        gtiff_driver = gdal.GetDriverByName('GTiff')
        co_opt = ["COMPRESS=DEFLATE", "PREDICTOR=2"]
        nowarp_tif = warped_tif.replace('_warped_','_nowarp_')
        gtiff_ds = gtiff_driver.CreateCopy(nowarp_tif, mem_ds, strict=0, options=co_opt)
        gtiff_ds.FlushCache()
        out_data = gtiff_ds.ReadAsArray()
        gtiff_ds=None
        ofilepath = os.path.splitext(nowarp_tif)[0]
    else:
        # Step 4: Define output UTM projection (e.g., UTM zone 18N = EPSG:32618)
        target_srs = osr.SpatialReference()
        target_srs.ImportFromEPSG(epsg_no)  # Change to your desired UTM zone
        warped_ds = gdal.Warp(
            warped_tif,
            mem_ds,
            # dstSRS='EPSG:4326',
            # dstSRS=f'EPSG:{epsg_no}',
            dstSRS=utm_srs.ExportToWkt(),
            # --- Quality Improvements ---
            resampleAlg='cubicspline',  # Use a higher-quality algorithm
            #resampleAlg='lanczos',       # High-quality resampling for small objects
            errorThreshold=0,            # 0 means no approximation (highest precision)
            warpOptions=['CUTLINE_ALL_TOUCHED=TRUE'], # Optional: helps with edge pixels
            
            format='GTiff',
            multithread=True,            # Recommended when errorThreshold is 0
            # tps=True,
            creationOptions=["COMPRESS=DEFLATE",'PREDICTOR=2']
        )
        
        out_data = warped_ds.ReadAsArray()
        ofilepath = os.path.splitext(warped_tif)[0]
        
    ngb=[6,1,0] if no_Pan else [7,1,0]
    rgb=[2,1,0] if no_Pan else [3,1,0]
    limits = None#[[700.,1800],[1000.,2200],[1500.,3500]]
    _=gen_rgb(out_data, ofilepath=ofilepath, bds=rgb, data4alpha=out_data[0,:,:], limits=limits)
    _=gen_rgb(out_data, ofilepath=ofilepath, bds=ngb, data4alpha=out_data[0,:,:], limits=limits)
    # Clean up
    # mem_ds.FlushCache()
    del mem_ds
    


def lonlat_to_utm_epsg(lon, lat):
    zone = int((lon + 180) / 6) + 1
    if lat >= 0:
        epsg = 32600 + zone  # Northern hemisphere
    else:
        epsg = 32700 + zone  # Southern hemisphere
    return epsg, zone

import os
if __name__=='__main__':
    # indir='/home/yp/Downloads/bluebon/250629_Andong/myout'; keystr = '250629_023708'
    # gcps_ll = [
    #     [128.940136, 36.905860, 0, 3682.6, 41.7],
    #     [128.745926, 36.921330, 0, 207.8, 244.3],
    #     [128.677553, 36.641338, 0, 297.2, 6900.6],
    #     [128.866308, 36.609926, 0, 3763.4, 7089.5],
    #     [128.748957, 36.568404, 0, 1893.1, 8379.4],
    #     [128.771625, 36.242205, 0, 3786.0, 15840.7],
    #     [128.579130, 36.277582, 0, 218.9, 15570.4]
    # ]
    # epsg_no = lonlat_to_utm_epsg(128.8, 36.58)[0]
    
    # # Chesapeake 250626_161648
    # indir='/home/yp/Downloads/bluebon/250626_Chesapeake/myout'; keystr='250626_161648'
    # gcps_ll =[ #gcps for lonlat - Chesapeake bay
    #     [-75.984604, 37.376722, 0, 2725.7,594.7],
    #     [-75.922833, 37.364066, 0, 3857.6,690.1],
    #     [-76.018268, 37.297689, 0, 2499.0,2522.4],
    #     [-75.938514, 37.280645, 0, 3964.7,2664.9],
    #     [-75.988540, 37.165131, 0 ,3622.7,5493.6],
    #     [-76.034741, 36.930154, 0, 3887.1,11081.8],
    #     [-76.249516, 36.953523, 0, 23.5,11219.4],
    #     [-76.169917,36.761451, 0, 2268.9,15413.1],
    #     [-76.084043,36.728818, 0, 3924.0,15899.0],

    #     [-75.98351, 37.38537, 0, 2706, 379],
    #     [-76.0905, 36.9076, 0, 3009, 11780],
    #     [-76.17634, 36.93279, 0, 1398, 11468],
    #     [-76.29467, 36.77759, 0, 10, 15434]
    #     ]
    # epsg_no = lonlat_to_utm_epsg(-75.9, 37.2)[0]
    
    # indir='/home/yp/Downloads/bluebon/250712_Seoul/myout'; keystr = '250712_024621'
    # gcps_ll = [
    #     [127.05305907,37.70527911, 0, 117.6,3955.7],
    #     [127.01118086,37.52975063, 0, 247.2,8147.9],
    #     [126.9570986, 37.2294121,  0, 784.9,15256.2],
    #     [127.02162837,37.20857353, 0, 2023.3,15553.4],
    #     [127.074859,  37.214396,   0, 2926.4,15265.4], 
    #     [127.2157175, 37.5534093,  0, 3712.5,7007.9],
    #     [127.30803021,37.82867332, 0, 3965.6,367.9],
    #     [127.21252026,37.82574644, 0, 2308.5,712.0]
    # ]
    # epsg_no = lonlat_to_utm_epsg(127.07,37.52)[0]
    
    # indir='/home/yp/Downloads/bluebon/250716_Bahrain/myout'; keystr = '250716_074255'
    # _gcps_ll = [
    #     [26.1698286,50.5977895,0, 80.7,72.1],
    #     [26.1598851,50.6712761,0, 1582.9,133.0],
    #     [26.1006882,50.7752918, 0, 3913.9,1268.8],        
    #     [26.017103,50.748344,0, 3750.6,3276.7],
    #     [25.904429,50.729881,0, 3889.1,5940.9],
    #     [25.886885,50.703229,0, 3434.5,6407.4],
    #     [25.884685,50.647786,0, 2340.8,6585.8],
    #     [25.9119249,50.6164917,0,1597.1,6026.8 ],
    #     [25.92054974,50.55984475, 0, 428.5,5955.8],
    #     [25.8635618,50.5287950,0,64.5,7351.2],
    #     [25.8315051,50.6266496,0,2157.3,7870.8],
    #     [25.7317427,50.5635553,0,1345.3,10330.0],
    #     [25.7264427,50.6788829,0,3675.5,10192.5]      
    # ]
    # gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    # epsg_no = lonlat_to_utm_epsg(50.6, 25.8)[0]
    
    
    # indir='/home/yp/Downloads/bluebon/250806_SoffSydney/myout'; keystr = '250806_002855'
    # _gcps_ll = [
    #     # [-34.1023407,151.0979848, 0, 468.2,100.0],
    #     # [-34.1119556,151.1392172, 0, 1256.9,228.0],
    #     # [-34.1595661,151.0730588, 0, 273.3,1501.3 ]
        
    #     #--no stack loss
    #     [-34.1023407,151.0979848, 0, 532.1,157.0],
    #     [-34.1119556,151.1392172, 0, 1317.7,280.0],
    #     [-34.1595661,151.0730588, 0, 337.3,1553.5 ]

    #     # [-34.1090867,151.0869532, 0, 299.5,284.3],
    #     # [-34.1023773,151.0979594, 0, 468.6,101.0],
    #     # [-34.1163177,151.1357457, 0, 1212.8,340.0],
    #     # [-34.1227377,151.1166167, 0, 938.4,589.3],
    #     # [-34.1119497,151.0861516, 0, 298.0,354.3],
    #     # [-34.1265318,151.0712040, 0, 91.5,732.0],
    #     # [-34.1302758,151.0810829, 0, 287.5,796.3],
    #     # [-34.1413365,151.1175404, 0, 998.7,969.5],
    #     # [-34.1517982,151.0906414, 0, 559.1,1278.6],
    #     # [-34.1595705,151.0730547, 0, 272.3,1502.3],
    #     # [-34.1720582,151.0631424, 0, 159.1,1848.2]
    # ]
    # gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    # epsg_no = lonlat_to_utm_epsg(151.162414, -34.465546)[0]
    
    # indir='/home/yp/Downloads/bluebon/250821_Busan/myout'; keystr='250821_023741'
    # _gcps_ll = [
    #     [35.4159114,129.0342659, 0, 216.4,173.0],
    #     [35.3290811,129.2156822, 0, 3903.5,1616.1],
    #     [35.1806674,129.1865512, 0, 4083.9,5140.9 ],
    #     [35.0445725,128.9680980, 0, 779.5,8966.3]
    # ]
    # gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    # epsg_no = lonlat_to_utm_epsg(129.047, 35.1032)[0]
    
    # indir='/home/yp/Downloads/bluebon/250903_Namhae/myout'; keystr='250903_023532'
    # _gcps_ll = [
    #     [34.9306829,127.7951508, 0 , 230.6,2437.2],
    #     [34.9423535,128.0311940, 0 , 4056.0,1544.8],
    #     [34.4094784,127.7986461, 0, 2290.4,14542.2]
    # ]
    # gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    # epsg_no = lonlat_to_utm_epsg(128.0133, 34.7098)[0]
    
    # indir='/home/yp/Downloads/bluebon/250926_Khuvsgul/myout'; keystr='250926_045459'
    # _gcps_ll = [
    #     # [50.96998512,100.52621456, 0 , 2496.2,10573.6], #x-2, y-1
    #     # [51.1620244,100.7321171, 0 , 4079.5,5475.7], #x-2
    #     # [50.75550444,100.51314359, 0, 3548.7,15473.2],
    #     # [51.3822700,100.8038093, 0, 3755.2,229.5]
        
    #     [50.96998344,100.52621050, 0, 2486.5,10550.5],
    #     [50.9783405,100.4809444, 0, 1846.0,10526.2],
    #     [51.3764714,100.8047033, 0 , 3787.0,338.5],
    #     [51.30510752,100.78940838, 0, 3994.2,2008.2],
    #     [50.8917195,100.5794015, 0, 3626.0,12128.0],
    #     [50.80433038,100.53623967, 0, 3561.0,14262.0],
    #     [50.7554938,100.5131371, 0, 3538.8,15451.2]
    # ]
    # gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    # epsg_no = lonlat_to_utm_epsg(100.5084, 51.0867)[0]
    
    # indir='/home/yp/Downloads/bluebon/260122_025059_Ongjin/myout_affine_2refs_sobelF'; keystr='260122_025059'
    # _gcps_ll = [
    #     [37.48481244,126.43578039, 0 , 399.8,336.3], 
    #     [37.4095943,126.5742523, 0 , 3194.9,1667.8],
    #     [37.25217359,126.49844573, 0, 2568.7,5501.2],
    #     [36.8564607,126.4643683, 0, 3762.7,14766.5]
    # ]
    # gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    # epsg_no = lonlat_to_utm_epsg(126.5591, 37.9785)[0] 
    
    # indir='/home/yp/Downloads/bluebon/260209_Suwon/myout'; keystr='260209_025928'
    # _gcps_ll = [
    #     # [37.75802978,127.02903915, 0 , 228.2,753.8], 
    #     # [37.7231155,127.2084585, 0 , 3315.0,910.8],
    #     # [37.52080315,127.09389213, 0, 2435.8,5926.5],
    #     # [37.3125767,126.9468200, 0, 1046.0,11202.0],
    #     # [37.14426233,126.86234585, 0,468.9,15347.1],
    #     # [37.09571406,127.04248852,0, 3646.1,15807.0]
        
    #     [37.75775217,127.02705939, 0, 196.1,765.5],
    #     [37.75135398,127.229090580,0, 3508.3,193.6],
    #     [37.51105368,126.94859142, 0, 109.4,6668.8],
    #     [37.4535184,127.1599113, 0, 3829.5,7225.8],
    #     [37.12552429,126.86321974,0,575.5,15770.4],
    #     [37.10483624,127.05049526,0,3731.8,15570.4]
    # ]
    # gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    # epsg_no = lonlat_to_utm_epsg(126.95, 37.31)[0] 
    
    indir='/home/yp/Downloads/bluebon/251029_Teheran/myout'; keystr='251029_075312'
    _gcps_ll = [
        
        [, 0, ],

    ]
    gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    epsg_no = lonlat_to_utm_epsg(100.5084, 51.0867)[0]
    
    prod='rhot'; no_Pan=True #if intersensor cal applied
    fnc = indir+f'/{keystr}_stacked_{prod}.nc'
    warped_tif=os.path.splitext(fnc)[0].replace('_stacked','_stacked_warped')+'.tif'
    #no success to write tiff with UTM projection
    ncgcp_to_warp(fnc, gcps_ll, warped_tif, epsg_no, no_warp=False, no_Pan=no_Pan)