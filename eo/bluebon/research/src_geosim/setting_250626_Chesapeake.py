#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Sep  7 18:22:40 2025 @author: yp
setting for bluebon lonlat simulation
"""
gcps_ll =[ #gcps for lonlat - Chesapeake bay
    # [-75.984604, 37.376722, 0, 2725.7,594.7],
    # [-75.922833, 37.364066, 0, 3857.6,690.1],
    # [-76.018268, 37.297689, 0, 2499.0,2522.4],
    # [-75.938514, 37.280645, 0, 3964.7,2664.9],
    # [-75.988540, 37.165131, 0 ,3622.7,5493.6],
    # [-76.034741, 36.930154, 0, 3887.1,11081.8],
    # [-76.249516, 36.953523, 0, 23.5,11219.4],
    # [-76.169917,36.761451, 0, 2268.9,15413.1],
    # [-76.084043,36.728818, 0, 3924.0,15899.0],

    # [-75.98351, 37.38537, 0, 2706, 379],
    # [-76.0905, 36.9076, 0, 3009, 11780],
    # [-76.17634, 36.93279, 0, 1398, 11468],
    # [-76.29467, 36.77759, 0, 10, 15434]
    ]
    
#--[time of origin: can be arbitrary for this simulation]
yr=2025; mo=6; dd=26; hr=16; mn=16; se=52

#--[satellite latitude and longitue from mission]
phi0_deg,lam0_deg =36.9473,-75.5617

ascending=False
alt_bb = 494. #Perigee: 499.9km, Apogee:500.4km
inc_bb = 97.4-0.2#-0.15#-0.08#-0.2#
#https://celestrak.org/satcat/search.php -> bluebon -> click graph

#--[roll from mission]
roll_bb = -5.8006+0.0 #0.4;     
yaw_deg=0.8-1.8#-2.0#-1.5 -0.5 0.8

#--[grid intervals]
roll_width=3. #in degree
roll_step_deg=0.02
minutes=0.5; step_s=0.05