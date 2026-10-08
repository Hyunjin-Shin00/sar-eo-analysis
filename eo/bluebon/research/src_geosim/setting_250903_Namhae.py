#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Sep  7 18:22:40 2025 @author: yp
setting for bluebon lonlat simulation
"""
_gcps_ll = [
        [34.9306829,127.7951508, 0 , 230.6,2437.2],
        [34.9423535,128.0311940, 0 , 4056.0,1544.8],
        [34.4094784,127.7986461, 0, 2290.4,14542.2]
    ]
gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
#epsg_no = lonlat_to_utm_epsg(128.0133, 34.7098)[0]
    
#--[time of origin: can be arbitrary for this simulation]
yr=2025; mo=9; dd=3; hr=2; mn=46; se=25

#--[satellite nadir latitude and longitue]
phi0_deg,lam0_deg =35.05,129.5607

ascending=False
alt_bb = 494. #Perigee: 499.9km, Apogee:500.4km
inc_bb = 97.4-0.2#+0.4
#https://celestrak.org/satcat/search.php -> bluebon -> click graph

#--[roll]
roll_bb = -17.5061+1.2;     
yaw_deg=0.8-0.7#-0.5#+0#-1.8

#--[grid intervals]
roll_width=3. #in degree
roll_step_deg=0.02
minutes=0.5; step_s=0.05

#--[bluebon DN]
fnc = '<WORK_ROOT>/Downloads/bluebon/250903_Namhae/myout_intercal_nogood/250903_023532_stacked_DN.nc'
#--[msi rad(radiance)]
ftif = '<WORK_ROOT>/Downloads/bluebon/250903_Namhae_msi_T52SCD/myout/MSI_res20m_merged_rad.tif'

# [..?]
irange_int_1=[200,900,2]
irange_int_2=[200,900,2]