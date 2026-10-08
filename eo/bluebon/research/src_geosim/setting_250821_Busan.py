#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Sep  7 18:22:40 2025 @author: yp
setting for bluebon lonlat simulation
"""
_gcps_ll = [

    [35.4159114,129.0342659, 0, 216.4,173.0],
    [35.3290811,129.2156822, 0, 3903.5,1616.1],
    [35.1806674,129.1865512, 0, 4083.9,5140.9 ],
    [35.0445725,128.9680980, 0, 779.5,8966.3]
]
gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]
    
#--[time of origin: can be arbitrary for this simulation]
yr=2025; mo=7; dd=12; hr=2; mn=46; se=25

#--[satellite latitude and longitue]
phi0_deg,lam0_deg =35.0912,129.0855

ascending=False
alt_bb = 494. #Perigee: 499.9km, Apogee:500.4km
inc_bb = 97.4-0.2#+0.4
#https://celestrak.org/satcat/search.php -> bluebon -> click graph

#--[roll]
roll_bb = -0.4647+0.4;     
yaw_deg=0.8+0.8

#--[grid intervals]
roll_width=3. #in degree
roll_step_deg=0.02
minutes=0.5; step_s=0.05

#--[bluebon DN]
fnc = '<WORK_ROOT>/Downloads/bluebon/250821_Busan/myout/250821_023741_stacked_DN.ncc'
#--[msi rad(radiance)]
ftif = ''

#--- first attempt
irange_int_1=[200, 2500+2000, 3] #si, ei, iint
#--- 2nd attempt for offset to refine offset
irange_int_2=[7000, 9000, 2]