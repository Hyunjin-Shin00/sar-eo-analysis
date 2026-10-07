#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Aug 28 18:17:53 2025

@author: yp
"""

import numpy as np
from datetime import datetime, timedelta, timezone

# ---- Earth constants ----
mu = 3.986004418e14     # m^3/s^2
Re = 6378137.0          # m (WGS84 equatorial)
R_mean = 6371008.8      # m (mean Earth radius, for great-circle distance)

def deg2rad(x): return np.deg2rad(x)
def rad2deg(x): return np.rad2deg(x)

# GMST (good enough for visualization / short propagation)
def gmst_angle(dt_utc: datetime) -> float:
    Y, M = dt_utc.year, dt_utc.month
    D = dt_utc.day + (dt_utc.hour + (dt_utc.minute + dt_utc.second/60)/60)/24
    if M <= 2: Y -= 1; M += 12
    A = int(Y/100); B = 2 - A + int(A/4)
    JD = int(365.25*(Y+4716)) + int(30.6001*(M+1)) + D + B - 1524.5
    T = (JD - 2451545.0)/36525.0
    gmst = 280.46061837 + 360.98564736629*(JD-2451545.0) + 0.000387933*T*T - T*T*T/38710000.0
    return np.mod(deg2rad(gmst), 2*np.pi)

def rot_z(th):
    c,s = np.cos(th), np.sin(th)
    return np.array([[ c,-s,0],[ s, c,0],[0,0,1]])

def rot_x(th):
    c,s = np.cos(th), np.sin(th)
    return np.array([[1,0,0],[0, c,-s],[0, s, c]])

def eci_from_elements(a_m, inc_rad, raan_rad, u_rad):
    r_pf = a_m * np.array([np.cos(u_rad), np.sin(u_rad), 0.0])   # circular orbit
    R = rot_z(raan_rad) @ rot_x(inc_rad)                         # PQW -> ECI
    return R @ r_pf

def vel_eci_from_elements(a_m, inc_rad, raan_rad, u_rad):
    v_mag = np.sqrt(mu / a_m)
    v_pf = v_mag * np.array([-np.sin(u_rad), np.cos(u_rad), 0.0]) # circular
    R = rot_z(raan_rad) @ rot_x(inc_rad)
    return R @ v_pf

def ecef_from_eci(r_eci, dt):
    return rot_z(-gmst_angle(dt)) @ r_eci

def geodetic_from_ecef(r):
    x,y,z = r
    lon = np.arctan2(y, x)
    rho = np.hypot(x,y)
    lat = np.arctan2(z, rho)   # spherical approx
    return lat, lon

def solve_u0_from_lat(phi0, inc_rad, ascending=True):
    s = np.sin(phi0)/np.sin(inc_rad)
    s = np.clip(s, -1.0, 1.0)
    u1 = np.arcsin(s)
    u2 = np.pi - u1
    return u1 if ascending else u2

# def solve_raan(phi0, lam0, t0, a_m, inc_rad, u0):
#     def lon_from_raan(raan):
#         r_eci = eci_from_elements(a_m, inc_rad, raan, u0)
#         r_ecef = ecef_from_eci(r_eci, t0)
#         _, lon = geodetic_from_ecef(r_ecef)
#         return lon
#     # coarse search over [0, 2π)
#     N = 720
#     rads = np.linspace(0, 2*np.pi, N, endpoint=False)
#     lons = np.unwrap([lon_from_raan(r) for r in rads])
#     idx = np.argmin(np.abs((lons - lam0 + np.pi) % (2*np.pi) - np.pi))
#     return rads[idx]

from scipy.optimize import brentq

def angdiff(a, b):
    """Smallest signed angular difference a - b, in radians, in (-pi, pi]."""
    return np.arctan2(np.sin(a - b), np.cos(a - b))

def solve_raan(phi0, lam0, t0, a_m, inc_rad, u0):
    """
    Solve RAAN (Ω) so that the sub-satellite longitude at time t0 equals lam0,
    given circular orbit with (a, i) and argument of latitude u0 chosen to hit phi0.
    Returns Ω in [0, 2π).
    """
    # lon_from_raan: ECI->ECEF->geodetic for the given epoch t0
    def lon_from_raan(raan):
        r_eci = eci_from_elements(a_m, inc_rad, raan, u0)
        r_ecef = ecef_from_eci(r_eci, t0)
        _, lon = geodetic_from_ecef(r_ecef)
        return lon  # radians, wrapped by atan2 to (-pi, pi]

    # Continuous error function (no wrap jumps)
    def g(raan):
        return angdiff(lon_from_raan(raan), lam0)

    # ---- 1) coarse search for a good initial guess
    N = 2048  # denser than before to be safe
    rads = np.linspace(0.0, 2*np.pi, N, endpoint=False)
    errs = np.array([g(r) for r in rads])
    k0 = np.argmin(np.abs(errs))
    guess = rads[k0]

    # ---- 2) bracket a root around the guess
    # expand symmetrically until sign change or up to pi span
    # step ~ 2π/N initially; expand geometrically
    step = 2*np.pi / N
    left = guess - step
    right = guess + step

    gl = g(left)
    gr = g(right)

    # Try to find a sign change; expand up to π on each side
    max_expand = np.pi
    expand = 1.5
    span = step
    ok = (gl * gr <= 0)

    while not ok and span < max_expand:
        span *= expand
        left = guess - span
        right = guess + span
        gl = g(left)
        gr = g(right)
        ok = (gl * gr <= 0)

    if not ok:
        # As a fallback, try a full-circle scan to find any sign change
        for j in range(N):
            a = rads[j]
            b = rads[(j+1) % N]
            ga, gb = errs[j], errs[(j+1) % N]
            if ga * gb <= 0:
                left, right = a, b
                gl, gr = ga, gb
                ok = True
                break

    if not ok:
        # Last resort: just return the best guess (should be extremely close)
        Omega = guess % (2*np.pi)
        return Omega

    # ---- 3) refine with Brent's method on the continuous error g
    # brentq requires f(left)*f(right) <= 0
    Omega = brentq(g, left, right, xtol=1e-12, rtol=1e-10, maxiter=100)
    return Omega % (2*np.pi)

def lvlh_look_vector(rolls_rad, pitch_rad, yaw_rad):
    """
    rolls_rad: array shape (R,)
    pitch_rad, yaw_rad: scalars (constant for the sweep)
    Returns l_LVLH with shape (3, R)
    Rotations: yaw about +R, pitch about +W, roll about +S (from nadir).
    """
    cρ = np.cos(rolls_rad); sρ = np.sin(rolls_rad)
    cθ = np.cos(pitch_rad); sθ = np.sin(pitch_rad)   # θ = pitch
    cψ = np.cos(yaw_rad);   sψ = np.sin(yaw_rad)     # ψ = yaw

    # Start from nadir v0 = [-1, 0, 0]
    # After roll about +S:
    #   v1 = [-cosρ, 0, -sinρ]
    x1 = -cρ
    y1 =  np.zeros_like(cρ)
    z1 = -sρ

    # After pitch about +W (rotate in R–S plane):
    #   [x2, y2, z2] = [ cθ*x1 - sθ*y1 , sθ*x1 + cθ*y1 , z1 ]  BUT pitch is about +W,
    #   i.e. rotation around z-axis in LVLH -> affects x/y and leaves z same:
    x2 =  cθ * x1 - sθ * y1
    y2 =  sθ * x1 + cθ * y1
    z2 =  z1

    # After yaw about +R (rotate around x-axis in LVLH -> affects y/z, leaves x same):
    x3 =  x2
    y3 =  cψ * y2 - sψ * z2
    z3 =  sψ * y2 + cψ * z2

    return np.vstack((x3, y3, z3))   # (3, R)

def ground_intercepts_sweep(
    alt_km, inc_deg, phi0_deg, lam0_deg, t0_utc,
    roll_min_deg=-30.0, roll_max_deg=30.0, roll_step_deg=1.0,
    yaw_deg=0.0, pitch_deg=0.0,   # <-- NEW: constant yaw
    ascending=True, minutes=60, step_s=5, start_offset_s=0
):
    """
    Sweep roll angle and time to compute ground intercept points.
    Returns:
      times (N,), rolls_deg (R,),
      nadir_lat (N,), nadir_lon (N,),
      look_lat (N,R), look_lon (N,R), offset_m (N,R)
    """

    # Orbit geometry
    a = Re + alt_km*1000.0
    n = np.sqrt(mu / a**3)
    inc = deg2rad(inc_deg)
    phi0 = deg2rad(phi0_deg)
    lam0 = deg2rad(lam0_deg)

    # Resolve initial argument of latitude & RAAN
    u0 = solve_u0_from_lat(phi0, inc, ascending=ascending)
    raan = solve_raan(phi0, lam0, t0_utc, a, inc, u0)

    # Time grid
    N = int((minutes*60)//step_s) + 1
    times = np.array([t0_utc + timedelta(seconds=start_offset_s + k*step_s)
                      for k in range(N)], dtype=object)

    # Roll grid
    rolls_deg = np.arange(roll_min_deg, roll_max_deg + 1e-9, roll_step_deg)
    rolls_rad = deg2rad(rolls_deg)
    pitch_rad = deg2rad(pitch_deg)               # NEW
    yaw_rad   = deg2rad(yaw_deg)                 # NEW
    Rn = rolls_rad.size

    # --- NEW: compute Earth rotation once and advance linearly
    omega_E = 7.2921150e-5                       # rad/s (sidereal)
    theta0  = gmst_angle(t0_utc)                 # GMST at t0 (one call)

    # Outputs
    nadir_lat = np.empty(N)
    nadir_lon = np.empty(N)
    look_lat  = np.full((N, Rn), np.nan)
    look_lon  = np.full((N, Rn), np.nan)
    offset_m  = np.full((N, Rn), np.nan)

    for k, t in enumerate(times):
        # argument of latitude at absolute time t:
        dt_sec = (t - t0_utc).total_seconds()
        u = u0 + n*dt_sec

        # Satellite state (ECI)
        r_eci = eci_from_elements(a, inc, raan, u)
        v_eci = vel_eci_from_elements(a, inc, raan, u)

        # --- NEW: Earth rotation angle at time t via linear advance
        theta = theta0 + omega_E * dt_sec
        Rz = rot_z(-theta)

        # Nadir ground point
        r_ecef = Rz @ r_eci
        lat0, lon0 = geodetic_from_ecef(r_ecef)
        nadir_lat[k] = rad2deg(lat0)
        nadir_lon[k] = ((rad2deg(lon0)+540)%360)-180   # (keep wrap if you want display-ready)

        # LVLH/RSW basis in ECI
        Rhat = r_eci / np.linalg.norm(r_eci)
        Shat = v_eci / np.linalg.norm(v_eci)
        What = np.cross(Rhat, Shat); What /= np.linalg.norm(What)
        B = np.column_stack((Rhat, Shat, What))  # LVLH->ECI matrix

        # Look vectors for all rolls with pitch & yaw applied (NEW)
        l_LVLH = lvlh_look_vector(rolls_rad, pitch_rad, yaw_rad)  # (3, R)

        # Map to ECI (3,R)
        l_eci = B @ l_LVLH

        # Ray-sphere intersection for each roll
        rdotl = r_eci @ l_eci         # (R,)
        r2 = np.dot(r_eci, r_eci)
        cquad = r2 - Re**2
        bquad = 2.0 * rdotl
        disc = bquad*bquad - 4.0*cquad

        valid = disc >= 0.0
        if not np.any(valid):
            continue

        sqrt_disc = np.sqrt(disc[valid])
        t_near = (-bquad[valid] - sqrt_disc) / 2.0
        t_far  = (-bquad[valid] + sqrt_disc) / 2.0
        t_int = np.where(t_near > 0, t_near, t_far)  # prefer near positive
        t_int[t_int <= 0] = np.nan

        # Intercepts in ECI for valid rolls
        p_eci = r_eci[:, None] + l_eci[:, valid] * t_int  # (3, nvalid)

        # --- NEW: use same linear-advanced Earth rotation for look points
        p_ecef = Rz @ p_eci
        latv = np.arctan2(p_ecef[2], np.hypot(p_ecef[0], p_ecef[1]))
        lonv = np.arctan2(p_ecef[1], p_ecef[0])

        # Write back
        idx = np.where(valid)[0]
        look_lat[k, idx] = rad2deg(latv)
        look_lon[k, idx] = ((rad2deg(lonv)+540)%360)-180

        # Great-circle offset between nadir and look (per roll)
        phi1 = np.deg2rad(nadir_lat[k]); lam1 = np.deg2rad(nadir_lon[k])
        phi2 = np.deg2rad(look_lat[k, idx]); lam2 = np.deg2rad(look_lon[k, idx])
        dlam = (lam2 - lam1 + np.pi) % (2*np.pi) - np.pi
        a_gc = np.sin((phi2-phi1)/2.0)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlam/2.0)**2
        c_gc = 2.0*np.arctan2(np.sqrt(a_gc), np.sqrt(1.0 - a_gc))
        offset_m[k, idx] = R_mean * c_gc

    return times, rolls_deg, nadir_lat, nadir_lon, look_lat, look_lon, offset_m


import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

def lonlat_to_geojson(look_lon, look_lat, ofgjson):
    # Flatten arrays
    lat = look_lat.ravel()
    lon = look_lon.ravel()
    
    # Filter NaNs (misses beyond horizon)
    mask = ~np.isnan(lat) & ~np.isnan(lon)
    
    gdf = gpd.GeoDataFrame({
        "lat": lat[mask],
        "lon": lon[mask]
    }, geometry=[Point(xy) for xy in zip(lon[mask], lat[mask])],
       crs="EPSG:4326")   # WGS84
    
    gdf.to_file(ofgjson, driver="GeoJSON")
    
from datetime import datetime

if __name__=="__main__":
    # #--[time of origin: can be arbitrary for this simulation]
    # yr=2025; mo=7; dd=12; hr=2; mn=46; se=25

    # #--[satellite latitude and longitue]
    # phi0_deg,lam0_deg =37.4918,127.2223

    # ascending=False    
    # alt_bb = 494. #Perigee: 499.9km, Apogee:500.4km
    # inc_bb = 97.4+0.4
    # #https://celestrak.org/satcat/search.php -> bluebon -> click graph

    # #--[roll]
    # roll_bb = -1.6705+0.4;     
    # yaw_deg=0.8+0.8
    
    # #--[grid intervals]
    # roll_width=3. #in degree
    # roll_step_deg=0.02
    # minutes=0.4; step_s=0.05
    from setting_250821_Busan import yr, mo, dd, hr, mn, se, phi0_deg, lam0_deg, \
        ascending, alt_bb, inc_bb, roll_bb, yaw_deg, roll_width, roll_step_deg, minutes, step_s
    
    
    roll_c = -roll_bb #(opposite in LVLH where +z = earth-to-spacecraft direction)
    roll_min_deg=roll_c-roll_width/2.; roll_max_deg=roll_c+roll_width/2.; 
    t0_utc=datetime(yr,mo,dd,hr,mn,se,tzinfo=timezone.utc)
    
    
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

    # Example: first time step, all rolls
    # print("t0:", times[0])
    # print("rolls (deg):", rolls_deg)
    # print("look lat @ t0:", np.round(look_lat[0], 4))
    # print("look lon @ t0:", np.round(look_lon[0], 4))
    # print("offset (km) @ t0:", np.round(offset_m[0] / 1000, 3))

    look_lat=look_lat[:,::-1]
    look_lon=look_lon[:,::-1]
    ofgjson = "look_points.geojson"
    lonlat_to_geojson(look_lon, look_lat, ofgjson)

# import numpy as np
# import matplotlib.pyplot as plt

# # unwrap longitudes
# lon = np.rad2deg(np.unwrap(np.deg2rad(look_lon[:,0])))
# # t = (np.array(times) - times[0]).astype('timedelta64[s]').astype(float)
# t = (np.array(times) - times[0]).astype("timedelta64[ms]").astype(float)

# # linear fit
# m, b = np.polyfit(t, lon, 1)
# trend = m*t + b
# resid = lon - trend

# plt.figure()
# plt.plot(t/60, lon, label="Longitude")
# plt.plot(t/60, trend, "--", label="Linear trend")
# plt.xlabel("Minutes from start"); plt.ylabel("Longitude (deg)")
# plt.legend(); plt.show()

# plt.figure()
# # plt.plot(t/60, resid*111, label="Residual (km)")  # convert deg to km approx
# # plt.xlabel("Minutes"); plt.ylabel("Residual (km)")
# # plt.show()

# plt.figure()
# plt.plot(times,nadir_lon[:])
# plt.plot(times,nadir_lon[:])