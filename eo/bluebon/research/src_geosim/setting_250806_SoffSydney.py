#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Sep  7 18:22:40 2025 @author: yp
setting for bluebon lonlat simulation
"""
_gcps_ll = [

    [-34.1023407,151.0979848, 0, 532.1,157.0],
    [-34.1119556,151.1392172, 0, 1317.7,280.0],
    [-34.1595661,151.0730588, 0, 337.3,1553.5 ]
]
gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    
#--[time of origin: can be arbitrary for this simulation]
yr=2025; mo=7; dd=12; hr=2; mn=46; se=25

#--[satellite latitude and longitue]
phi0_deg,lam0_deg =-33.8172,150.9986

ascending=False
alt_bb = 494. #Perigee: 499.9km, Apogee:500.4km
inc_bb = 97.4-0.2#+0.4
#https://celestrak.org/satcat/search.php -> bluebon -> click graph

#--[roll]
roll_bb = 2.4948+0.4;     
yaw_deg=0.8+0.8

#--[grid intervals]
roll_width=3. #in degree
roll_step_deg=0.02
minutes=0.5; step_s=0.05

#--[bluebon DN]
fnc = '/home/yp/Downloads/bluebon/250806_SoffSydney/myout/250806_002855_stacked_DN.nc'
#--[msi rad(radiance)]
ftif = '/home/yp/Downloads/bluebon/250806_SoffSydney_msi/myout/MSI_res20m_merged_rad.tif'

#--- first attempt
irange_int_1=[200, 2500+2000, 3] #si, ei, iint
#--- 2nd attempt for offset to refine offset
irange_int_2=[7000, 9000, 2]