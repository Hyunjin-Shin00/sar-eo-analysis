#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug 30 17:00:34 2025

@author: yp
"""

import numpy as np
from scipy.interpolate import RegularGridInterpolator, griddata
from scipy.spatial import cKDTree
from scipy.optimize import least_squares

R_E = 6371008.8  # mean Earth radius (m)

def _unwrap_lon_around(lon_deg, ref_deg):
    """Return lon unwrapped near ref_deg so differences are continuous."""
    L = np.deg2rad(lon_deg)
    ref = np.deg2rad(ref_deg)
    d = np.arctan2(np.sin(L - ref), np.cos(L - ref))  # in (-pi, pi]
    return np.rad2deg(ref + d)

def build_swath_inverse(look_lat, look_lon):
    """
    Prepare helpers to invert (lat,lon)->(i,j) on a grid of shape (Nt, Nr).
    Returns a dict with interpolators and a KDTree for fast initial guesses.
    """
    Nt, Nr = look_lat.shape
    i_axis = np.arange(Nt, dtype=float)
    j_axis = np.arange(Nr, dtype=float)

    # We'll unwrap longitudes on-the-fly per query, but also keep a
    # default unwrapped version around the central meridian for KDTree.
    lon0_ref = np.nanmedian(look_lon)
    lon_unw0 = _unwrap_lon_around(look_lon, lon0_ref)

    # Interpolators take (i,j) and return lat, lon (we'll pass unwrapped lon per query)
    f_lat = RegularGridInterpolator((i_axis, j_axis), look_lat,
                                    bounds_error=False, fill_value=np.nan)

    helpers = {
        "Nt": Nt, "Nr": Nr,
        "i_axis": i_axis, "j_axis": j_axis,
        "f_lat": f_lat,
        "look_lat": look_lat,            # keep originals
        "look_lon": look_lon,
        "lon_unw0": lon_unw0,
        "tree": cKDTree(np.c_[look_lat.ravel(), lon_unw0.ravel()]),
    }
    return helpers

def latlon_to_ij(lat_q, lon_q, helpers, search_halfwin=3):
    """
    Solve for fractional (i,j) such that (lat(i,j), lon(i,j)) ~= (lat_q, lon_q).
    Returns (i_hat, j_hat, success_flag).
    """
    look_lat = helpers["look_lat"]
    look_lon = helpers["look_lon"]
    Nt, Nr   = helpers["Nt"], helpers["Nr"]
    i_axis   = helpers["i_axis"]; j_axis = helpers["j_axis"]
    f_lat    = helpers["f_lat"]
    tree     = helpers["tree"]

    # Unwrap longitude field around this query (prevents seam problems)
    lon_unw = _unwrap_lon_around(look_lon, lon_q)

    # Build lon interpolator on-the-fly with this unwrapping
    f_lon = RegularGridInterpolator((i_axis, j_axis), lon_unw,
                                    bounds_error=False, fill_value=np.nan)

    # Initial guess: nearest node (by lat/lon in degrees, already unwrapped for lon)
    d, idx = tree.query([lat_q, _unwrap_lon_around(lon_q, np.nanmedian(look_lon))])
    i0, j0 = np.unravel_index(idx, (Nt, Nr))
    x0 = np.array([float(i0), float(j0)])

    # Local bounds: keep solver near the nearest cell (improves robustness)
    lo = np.array([max(-0.5, i0 - search_halfwin), max(-0.5, j0 - search_halfwin)])
    hi = np.array([min(Nt-0.5, i0 + search_halfwin), min(Nr-0.5, j0 + search_halfwin)])

    # Residual in meters (north/east small-angle on sphere)
    lat_q_rad = np.deg2rad(lat_q)
    def resid(x):
        i, j = x
        lat_p = f_lat([[i, j]])[0]
        lon_p = f_lon([[i, j]])[0]
        if np.isnan(lat_p) or np.isnan(lon_p):
            return np.array([1e6, 1e6])  # large penalty
        dlat = np.deg2rad(lat_p - lat_q)
        dlon = np.deg2rad(lon_p - lon_q)
        # wrap dlon to (-pi,pi]
        dlon = np.arctan2(np.sin(dlon), np.cos(dlon))
        north = R_E * dlat
        east  = R_E * np.cos(lat_q_rad) * dlon
        return np.array([north, east])

    res = least_squares(resid, x0, bounds=(lo, hi), xtol=1e-10, ftol=1e-10, gtol=1e-10, max_nfev=100)

    return res.x[0], res.x[1], res.success

def latlon_array_to_ij(lat_arr, lon_arr, helpers, **kw):
    """
    Vector helper: arrays of targets -> arrays of (i,j).
    """
    lat_arr = np.asarray(lat_arr)
    lon_arr = np.asarray(lon_arr)
    out_i = np.empty(lat_arr.shape, float)
    out_j = np.empty(lat_arr.shape, float)
    ok    = np.zeros(lat_arr.shape, bool)
    it = np.nditer(lat_arr, flags=['multi_index'])
    while not it.finished:
        mi = it.multi_index
        ii, jj, success = latlon_to_ij(lat_arr[mi], lon_arr[mi], helpers, **kw)
        out_i[mi] = ii; out_j[mi] = jj; ok[mi] = success
        it.iternext()
    return out_i, out_j, ok

# from scipy.interpolate import RegularGridInterpolator
def make_latlon_interpolators(look_lat, look_lon):
    i = np.arange(look_lat.shape[0])  # row indices
    j = np.arange(look_lat.shape[1])  # col indices
    lat_interp = RegularGridInterpolator((i,j), look_lat)
    lon_interp = RegularGridInterpolator((i,j), look_lon, method='linear')
    return lat_interp, lon_interp


import math
from simulation_lonlat import ground_intercepts_sweep
from datetime import datetime, timezone

from myaffine import affine_from_points, apply_affine

def wrapper_look_latlon_sim(t0_utc, phi0_deg, lam0_deg, ascending, alt_bb, inc_bb,yaw_deg, roll_bb, roll_width, roll_step_deg, minutes, step_s ):
    
    roll_c = -roll_bb #(opposite in LVLH where +z = earth-to-spacecraft direction)
    roll_min_deg=roll_c-roll_width/2.; roll_max_deg=roll_c+roll_width/2.; 
    
    times, rolls_deg, nadir_lat, nadir_lon, look_lat, look_lon, offset_m = ground_intercepts_sweep(
        alt_km=alt_bb,
        inc_deg=inc_bb,
        phi0_deg=phi0_deg,            # known nadir lat
        lam0_deg=lam0_deg,           # known nadir lon
        t0_utc=t0_utc,
        roll_min_deg=roll_min_deg,
        roll_max_deg=roll_max_deg,
        roll_step_deg=roll_step_deg,          # roll step
        yaw_deg=yaw_deg,   # <-- NEW: constant yaw
        ascending=ascending,
        minutes=minutes,                  # time span
        step_s=step_s,                    # time step (seconds)
        start_offset_s=-12 # start 1.5 minutes before
    )
    
    # to reverse left-right
    look_lat=look_lat[:,::-1]
    look_lon=look_lon[:,::-1]
    return look_lat, look_lon

def form_affine(look_lat, look_lon, gcps_ll ):

    # look_lat, look_lon are your (Nt, Nr) arrays
    helpers = build_swath_inverse(look_lat, look_lon)
    
    # # Single query
    # i_hat, j_hat, ok = latlon_to_ij(37.5, 127.0, helpers)
    # i0,j0 = math.floor(i_hat), math.floor(j_hat) 
    # print(look_lat[i0,j0], look_lat[i0+1,j0])
    # print(look_lon[i0,j0], look_lon[i0,j0+1], look_lon[i0+1,j0+1])
        
    lat_q = [g[1] for g in gcps_ll]
    lon_q = [g[0] for g in gcps_ll]
    i_to, j_to, OK = latlon_array_to_ij(lat_q, lon_q, helpers)

    j_fr = [g[3] for g in gcps_ll]; j_fr=np.array(j_fr)
    i_fr = [g[4] for g in gcps_ll]; i_fr=np.array(i_fr)
    
    # j_fr
    # j_to
    # i_fr
    # i_to

    src = np.array(list(zip(i_fr, j_fr)))
    dst = np.array(list(zip(i_to, j_to)))
    
    A, b = affine_from_points(src, dst)
    return A, b
    
def bluebon_ij_to_latlon(look_lat, look_lon, gcps_ll, ij_list):
        
    A, b = form_affine(look_lat, look_lon, gcps_ll)
    mapped_ij_list = apply_affine(A, b, ij_list)
    # print("Mapped:", mapped[0])

    lat_interp, lon_interp = make_latlon_interpolators(look_lat, look_lon)
    lat = lat_interp([mapped_ij_list])[0]
    lon = lon_interp([mapped_ij_list])[0]
    return lat, lon
    
if __name__=='__main__':
    from setting_2508xx_SoffSydney import yr, mo, dd, hr, mn, se, phi0_deg, lam0_deg, \
        ascending, alt_bb, inc_bb, roll_bb, yaw_deg, roll_width, roll_step_deg, minutes, step_s
    
    t0_utc=datetime(yr,mo,dd,hr,mn,se,tzinfo=timezone.utc)
    look_lat, look_lon =  wrapper_look_latlon_sim(t0_utc, phi0_deg, lam0_deg, ascending, alt_bb, inc_bb,yaw_deg, roll_bb, roll_width, roll_step_deg, minutes, step_s)
   
    # #--[optional]
    # from simulation_lonlat import lonlat_to_geojson
    # ofgjson = "look_points.geojson"
    # lonlat_to_geojson(look_lon, look_lat, ofgjson)
    
    
    # gcps_ll = [
    #     # [127.05305907,37.70527911, 0, 117.6,3955.7],
    #     # [127.01118086,37.52975063, 0, 247.2,8147.9],
    #     [126.9570986, 37.2294121,  0, 784.9,15256.2],
    #     # [127.02162837,37.20857353, 0, 2023.3,15553.4],
    #     # [127.074859,  37.214396,   0, 2926.4,15265.4], 
    #     # [127.2157175, 37.5534093,  0, 3712.5,7007.9],
    #     # [127.30803021,37.82867332, 0, 3965.6,367.9],
    #     [127.21252026,37.82574644, 0, 2308.5,712.0]
    # ]
    _gcps_ll = [
        [-34.1023407,151.0979848, 0, 468.2,100.0],
        [-34.1119556,151.1392172, 0, 1256.9,228.0],
        [-34.1595661,151.0730588, 0, 273.3,1501.3 ]
        
        # [-34.1090867,151.0869532, 0, 299.5,284.3],
        # [-34.1023773,151.0979594, 0, 468.6,101.0],
        # [-34.1163177,151.1357457, 0, 1212.8,340.0],
        # [-34.1227377,151.1166167, 0, 938.4,589.3],
        # [-34.1119497,151.0861516, 0, 298.0,354.3],
        # [-34.1265318,151.0712040, 0, 91.5,732.0],
        # [-34.1302758,151.0810829, 0, 287.5,796.3],
        # [-34.1413365,151.1175404, 0, 998.7,969.5],
        # [-34.1517982,151.0906414, 0, 559.1,1278.6],
        # [-34.1595705,151.0730547, 0, 272.3,1502.3],
        # [-34.1720582,151.0631424, 0, 159.1,1848.2]
    ]
    gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll]

    ij_list= [[16000.,0]] #[[i0,j0],[i1,j1],...]
    lats, lons= bluebon_ij_to_latlon(look_lat, look_lon, gcps_ll, ij_list)
    
    

