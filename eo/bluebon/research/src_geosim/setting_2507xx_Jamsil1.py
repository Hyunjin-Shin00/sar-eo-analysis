#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Sep  7 18:22:40 2025 @author: yp
setting for bluebon lonlat simulation
"""

#--[time of origin: can be arbitrary for this simulation]
yr=2025; mo=7; dd=12; hr=2; mn=46; se=25


#--[satellite latitude and longitue]
phi0_deg,lam0_deg =37.4918,127.2223

ascending=False    
alt_bb = 494. #Perigee: 499.9km, Apogee:500.4km
inc_bb = 97.4+0.4
#https://celestrak.org/satcat/search.php -> bluebon -> click graph

#--[roll]
roll_bb = -1.6705+0.4;     
yaw_deg=0.8+0.8

#--[grid intervals]
roll_width=3. #in degree
roll_step_deg=0.02
minutes=0.4; step_s=0.05