#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Mar  9 10:55:18 2026 @author: yp

Pan band is not considered because of failure in registration of the band.

First, required is step by step verification bluebon per-band pixel to (lon,lat) transformation. 
Example: band i (x,y) in rawDN -> (x1,y1) in stacked -> (lon, lat) -> msi (x2, y2) -> msi-based radiance

Then, for each band and each column, bluebon DN - msi radiance radiance compared. 
Slope and intercept are derived. Visual check with scatter plot 

"""

# %% [markdown]
# # MSI-to-Bluebon Radiometric Calibration Pipeline
# This notebook performs cross-calibration between MSI (Reference) and Bluebon (Target) sensors.
# 
# **Process Flow:**
# 1. **Spatial Alignment:** Band registration and Geocorrection via Affine transforms.
#    - Previous DN-radiance conversion, compute_coef_rad2DN_coefs.py assume that inter-band register is only shift. 
# 2. **Spectral Resampling:** Interpolating MSI radiance to Bluebon band centers.
# 3. **Regression:** Using "Tame ODR" (Sigma-clipped regression) to calculate DN-to-Radiance coefficients.

# Prepared:
# Reference_band (bandno=4) to lonlat conversion model based on **gcps_ll**
# which is prepared here by visual idenfication of feature points with zview and Qgis software 

# Calcoefs for Pan band will not be reliable because of failure in registration of the band.

# %% [markdown]
# ## 1. Environment Setup & Dependencies

import numpy as np
from skimage import transform
# Suppressing rasterio georeferencing warnings as raw calibration frames lack CRS metadata.
import warnings
from rasterio.errors import NotGeoreferencedWarning
warnings.filterwarnings('ignore', category=NotGeoreferencedWarning)
import rasterio
import sys

sys.path.append('../src')
import rsr_f0_bluebon
sys.path.append('../../tools')
import ncutils, tiffutils, uniquify
from scipy.interpolate import interp1d
sys.path.append('../../polygonTools/src_pt')
import tiffcoordconv

import matplotlib.pyplot as plt
# spatial bilinear interpolation
from scipy.ndimage import map_coordinates
import pandas as pd

# %% [markdown]
# ## 2. Geometric & Spatial Helpers
# Functions to handle coordinate transformations between sensor bands and global lon/lat.
# load band registration matrix 
def load_bandRegistration(fnpz):
    """
    Loads inter-band registration matrices.
    Maps PAN-MS7 pixel coordinates to the Reference(MS4, check fnpz) frame.
    set bandReg_mtx=bb_bandnames
    """
    _loader=np.load(fnpz)
    bandReg_mtx = {bb_bandnames[i]: _loader[key] for i, key in enumerate(_loader.files)}
    _loader.close()

    # print(len(bandReg_mtx), bandReg_mtx.keys()) #8bands

    if VERBOSE:# Check the loaded model params printing the trans matrix.
        for key in bandReg_mtx.keys():
            print(key)
            print(bandReg_mtx[key])

    # Quick check bandRegistration
    if 0:
        key='MS1'
        tform0 = transform.AffineTransform(matrix=bandReg_mtx[key])
        print('band registration (0,0)=',tform0([0.,0.]))
        print('band registration inv=',tform0.inverse(tform0([0.,0.])[0]))
        print('band registration inv=',tform0.inverse([0,0]))

    return bandReg_mtx

# to compute geoTrans matrix
def load_geoTrans(gcps_ll):
    """
    Estimates Affine Transform from Ground Control Points (GCPs).
    Maps Pan-band pixel coordinates to Lon/Lat.
    """
    dst = gcps_ll[:,:2]
    src = gcps_ll[:,3:]
    geoTrans=transform.estimate_transform('affine',src,dst)
    # print("Geocorr Matrix:\n", geoTrans.params)

    # Check the geocorr model **residuals**
    # residuals = geoTrans.residuals(src, dst)
    # print("Mean Residual Error:", np.mean(residuals)) #0.0002856171431174981
    return geoTrans


# ## read_raster_tif
def read_raster_tif(ftif):
    with rasterio.open(ftif) as src:
        data = src.read()  # shape: (bands, rows, cols)
        profile = src.profile  # metadata like crs, transform, dtype
    return data, profile

# ## xyArr2lonlatArr
def xyArr2lonlatArr(ib, xyarr, bandReg_mtx, geoTrans):
    #ib [0,1,..7] for [Pan, MS1, .., Ms7]
    key = list(bandReg_mtx.keys())[ib]
    # print(bandReg_mtx[key])
    tform0 = transform.AffineTransform(matrix=bandReg_mtx[key])
    _M = geoTrans.params@bandReg_mtx[key]
    tform = transform.AffineTransform(matrix=_M)
    lonlatarr = tform(xyarr)
    
    return lonlatarr


# ## Define ODR-Ordinary Distance Regression fit
from scipy.optimize import curve_fit
from scipy import odr

import numpy as np
from scipy.optimize import curve_fit
from scipy import odr
# %% [markdown]
# ## 3. Radiometric & Regression Engines
# Core logic for calculating the DN-to-Radiance mapping.
# - **Tame Fit:** Prevents extreme curvature in quadratic fits by bounding the 'a' coefficient.
# - **Sigma Clip:** Automatically removes pixel noise/outliers before fitting.
def get_tame_fit(x_input, y_input, is_quadratic=False, a_limit=1e-10, sigma_clip=3.0):
    """
    Tame Fit Function with Outlier Removal.
    - sigma_clip: Removes points further than X standard deviations from a preliminary fit.
    """
    # 1. Basic Cleaning (NaN/Inf)
    x_arr = np.asarray(x_input).flatten()
    y_arr = np.asarray(y_input).flatten()
    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_c, y_c = x_arr[mask], y_arr[mask]

    if len(x_c) < (3 if is_quadratic else 2): return None

    # 2. Outlier Removal (Sigma Clipping)
    # We do a quick initial fit to find the "center" of the data
    p_prelim = np.polyfit(x_c, y_c, 2 if is_quadratic else 1)
    y_pred = np.polyval(p_prelim, x_c)
    residuals = y_c - y_pred
    std_dev = np.std(residuals)
    
    # Keep only points within the 'sigma_clip' range
    outlier_mask = np.abs(residuals) < (sigma_clip * std_dev)
    x_final = x_c[outlier_mask]
    y_final = y_c[outlier_mask]
    
    # Check if we still have enough data after clipping
    if len(x_final) < (3 if is_quadratic else 2):
        x_final, y_final = x_c, y_c # Fallback to original if we clipped too much

    # 3. Final Fitting
    if is_quadratic:
        def model(x, a, b, c): return a*x**2 + b*x + c
        lower_bounds = [-a_limit, -np.inf, -np.inf]
        upper_bounds = [ a_limit,  np.inf,  np.inf]
        
        p0 = list(np.polyfit(x_final, y_final, 2))
        p0[0] = np.clip(p0[0], -a_limit, a_limit)
        
        try:
            popt, _ = curve_fit(model, x_final, y_final, p0=p0, bounds=(lower_bounds, upper_bounds))
            return popt
        except Exception as e:
            print(f"Fit failed: {e}")
            return None
    else:
        def lin_func(p, x): return p[0] * x + p[1]
        model = odr.Model(lin_func)
        data = odr.Data(x_final, y_final)
        my_odr = odr.ODR(data, model, beta0=np.polyfit(x_final, y_final, 1))
        return my_odr.run().beta
    

# %% [markdown]
# ## 4. Other diagnostic fuctions
# - **get_factored_string**
# - **get_factored_string_linear**
# - **show_regression_graph**
# - **plot_diagnostic_fit**
# - **show_variation_over_rows**
# - **plot_diagnostic_spatial**
# - **plot_calibration_results(fnpz, imageOrder=True)**

import cmath # Using cmath in case the roots are complex/imaginary

def get_factored_string(a, b, c):
    # 1. Calculate the discriminant
    d = (b**2) - (4*a*c)
    
    # 2. Find the two roots
    sol1 = (-b - cmath.sqrt(d)) / (2*a)
    sol2 = (-b + cmath.sqrt(d)) / (2*a)
    
    # 3. Format the string for your plot or Markdown
    # We take the .real part if you only care about the physical x-intercepts
    raw_r1, raw_r2 = sol1.real, sol2.real
    r1 = max(raw_r1, raw_r2)
    r2 = min(raw_r1, raw_r2)
    
    # Note: we use (x - r1) so if r1 is negative, it becomes (x + absolute_r1)
    factored_eq = f"y = {a:.2e}(x - {r1:.2f})(x - {r2:.2f})"
    factored_eq = f"y = {a:.2e}(X - {r1-r2:.2f})X, X=x-{r2:.2f}"
    return factored_eq, r1, r2

def get_factored_string_linear(b, c):
    
    r1 = -c / b
    # Note: we use (x - r1) so if r1 is negative, it becomes (x + absolute_r1)
    factored_eq = f"y = {b:.2e}X , X=x-{r1:.2f}"
    return factored_eq, r1

def show_regression_graph(ib, icol, params, is_quadratic, x, y):    
    # 1. Create a smooth x-axis for the curve
    x_fit = np.linspace(min(x), max(x), 500)
    # 2. Calculate y values for the curve

    if is_quadratic:
        a, b, c = params
        y_fit = a * x_fit**2 + b * x_fit + c
        label = f'y = ({a:.2e})$x^2$ + ({b:.2f})x + ({c:.2f})'
        equation_str, root1, root2 = get_factored_string(a, b, c)
    else:
        b, c = params
        y_fit = b * x_fit + c
        label = f'y = ({b:.2f})x + ({c:.2f})'
        equation_str, root1 = get_factored_string_linear(b, c)
    print(f"Factored Form: {equation_str}")
    label = f'{equation_str}'
    
    # 3. Plotting
    plt.figure()
    plt.scatter(x, y, marker='+', alpha=0.3, label='Data')
    plt.plot(x_fit, y_fit, color='orange', linewidth=2, label='ODR fit')
    
    # Format the equation for the plot
    plt.title(f"Fit Result band:{ib} col:{icol}\n{label}")
    plt.xlabel('DN Value')
    plt.ylabel('radiance-MSI unit')
    plt.legend()
    plt.show()

def plot_diagnostic_fit(debug_info, is_quadratic, use_avg=False, a_limit=3e-5):
    """Visualizes the Tame Fit against the smoothed data."""
    if not use_avg:
        x = debug_info['dn_raw']
        y = debug_info['rad_raw']
    else:
        x = debug_info['dn_avg']
        y = debug_info['rad_avg']
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    
    params = get_tame_fit(x, y, is_quadratic=is_quadratic, a_limit=a_limit)
    show_regression_graph(debug_info['ib'], debug_info['icol'], params, is_quadratic, x, y)

def show_variation_over_rows(ib, icol, _dn_avg, _rad_avg):
    fig, ax1 = plt.subplots()
    lns1=ax1.plot(_dn_avg, linewidth=1, label='DN')
    ax1.set_ylabel('Bluebon DN')
    ax2=ax1.twinx()
    
    lns2=ax2.plot(_rad_avg, linewidth=1, color='tab:red', alpha=0.5, label='radiance')
    ax2.set_ylabel('MSI radiance')
    ax1.set_xlabel('row number')
    lns=lns1 + lns2
    labs=[l.get_label() for l in lns]
    ax1.legend(lns, labs)
    plt.title(f"band:{ib} icol:{icol}")
    plt.show()

def plot_diagnostic_spatial(debug_info, use_avg=False):
    if not use_avg:
        x = debug_info['dn_raw']
        y = debug_info['rad_raw']
    else:
        x = debug_info['dn_avg']
        y = debug_info['rad_avg']
    # mask = np.isfinite(x) & np.isfinite(y)
    # x = x[mask]
    # y = y[mask]
    show_variation_over_rows(debug_info['ib'], debug_info['icol'], x, y)

def plot_diagnostic_lonlat(debug_info):
    """Checks if the lon/lat path for a column looks correct."""
    plt.figure(figsize=(8, 4))
    plt.plot(debug_info['lats'], label='Latitude', color='blue')
    plt.ylabel('Lat')
    ax2 = plt.gca().twinx()
    ax2.plot(debug_info['lons'], label='Longitude', color='red')
    ax2.set_ylabel('Lon')
    plt.title(f"Spatial Path: Band {debug_info['ib']}, Col {debug_info['icol']}")
    plt.show()

def plot_calibration_results(fnpz_coeffs, imageOrder=True):
    with np.load(fnpz_coeffs, allow_pickle=True) as z:
        coeff = np.array(z['coeffs'])
        # .item() is often needed to get the dictionary back from the array wrapper
        metadata = z['meta_data'].item()
    print(metadata)
    print(coeff.shape)

    nbds = coeff.shape[0]
    ncols = coeff.shape[1]
    nparams = coeff.shape[2] # 2 for linear, 3 for quadratic

    # Create two vertical panels
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    for ibd in range(nbds):
        # Determine which index is slope and which is offset
        # For Quadratic (a, b, c): Slope is index 1, Offset is index 2
        # For Linear (m, b): Slope is index 0, Offset is index 1
        s_idx, o_idx = (1, 2) if nparams == 3 else (0, 1)

        slope = coeff[ibd, :, s_idx]
        offset = coeff[ibd, :, o_idx]
        if imageOrder:
            slope=slope[::-1]
            offset=offset[::-1]
        
        # Plot Slope (Gain)
        ax1.plot(slope, label=f'Band {ibd}', alpha=0.8)
        # Plot Offset (Dark)
        ax2.plot(offset, alpha=0.8)

    # Formatting Top Panel
    ax1.set_ylabel('Slope (Gain)')
    ax1.set_title(f"Calibration Coefficients per Column\nSource: {fnpz_coeffs}")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper right', bbox_to_anchor=(1.15, 1))

    # Formatting Bottom Panel
    ax2.set_ylabel('Offset (Dark Signal)')
    ax2.set_xlabel('Sensor Column Index')
    ax2.axhline(0, color='black', linestyle='--', linewidth=1) # Reference line
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()

# %% [markdown]
# ## 5. Function to collect match data for multi calpar
# - **build geoTrans affine** matrix with _gcps_ll
# - ** Geocorrection Affine model**:
# - msi data interpolated to bb waveband

# function to load calibration parameters for single file
def load_filepair(calpar):
    fnpz = calpar['fnpz']
    _gcps_ll = calpar['_gcps_ll']
    fmsi = calpar['fmsi']

    #load_bandregistration
    bandReg_mtx = load_bandRegistration(fnpz)

    #load geoTrans
    gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll ] #lat, lon -> lon, lat
    gcps_ll = np.array(gcps_ll)

    geoTrans = load_geoTrans(gcps_ll)

    # #==== generate MSI_sim data
    # read msi data and waves
    data_msi=tiffutils.getraster(fmsi,None)
    waves_msi=tiffutils.get_waves_tif(fmsi)

    # MSI radiance data interpolated to bluebon wavelengths  
    f = interp1d(
        waves_msi,            # length Nwave
        data_msi,             # shape (Nwave, nrows_msi, ncols_msi)
        kind='linear',
        axis=0,            # interpolate along the wave axis
        bounds_error=False,
        fill_value='extrapolate'
    )
    data_msi_sim = f(waves_bb)   # shape (len(waves1), nrows_msi, ncols_msi)
    print(f'data_msi_sim.shape={data_msi_sim.shape}')

    return bandReg_mtx, geoTrans, data_msi_sim, fmsi

# function collect matching dn-rad data over multi file pairs (calpar_arr)
#nb and bb_bandnames should be assigned before
def collect_column_xy_data(calpar_arr, interval, use_avg):
    # Initialize: A list of bands, where each band is a list of columns
    # total_x[band_idx][column_idx] will hold a list of arrays from different files
    # total_x[ib] -> {icol: [array1, array2, ...]}
    total_x = [{} for _ in range(nb)]
    total_y = [{} for _ in range(nb)]
    for f_idx, calpar in enumerate(calpar_arr):
        # Major Progress
        print(f"\n[File {f_idx+1}/{len(calpar_arr)}] Loading: {calpar['keystr']}...")

        bandReg_mtx, geoTrans, data_msi_sim, fmsi = load_filepair(calpar)
        indir = calpar['indir']
        keystr = calpar['keystr']
        for ib in range(nb):
            # Mid-level Progress
            print(f"  > Processing Band {ib} ({bb_bandnames[ib]})...", end="")

            # Load Bluebon DN data
            ftif = f"{indir}/{keystr}_{ib}_gray.tiff"
            _dn, _ = read_raster_tif(ftif)
            # Flip for image coordinate compatibility
            dn_data = np.squeeze(_dn)[:, ::-1] 
            nrows, ncols = dn_data.shape

            key = bb_bandnames[ib]
            _mtx = geoTrans.params @ bandReg_mtx[key]

            for icol in range(ncols):
                # Minor Progress (Overwrites the same line)
                if icol % 100 == 0: # Update every 100 columns to save CPU
                    sys.stdout.write(f"\r  > Processing Band {ib}: Column {icol}/{ncols}")
                    sys.stdout.flush()
                dn_x, rad_y = get_xydata_sub(icol, _mtx, fmsi, data_msi_sim[ib], dn_data, use_avg=use_avg, interval=interval)
                # If this is the first time we see this column, initialize its list
                if icol not in total_x[ib]:
                    total_x[ib][icol] = []
                    total_y[ib][icol] = []
                total_x[ib][icol].append(dn_x)
                total_y[ib][icol].append(rad_y)
            # Print a newline once the band is finished
            print(f" - Done! Total Cols: {len(total_x[ib])}")
        del data_msi_sim #save RAM

    # Final Step: Concatenate into single arrays
    for ib in range(nb):
        for icol in total_x[ib].keys():
            total_x[ib][icol] = np.concatenate(total_x[ib][icol])
            total_y[ib][icol] = np.concatenate(total_y[ib][icol])

    return total_x, total_y

# get_xydata_sub
def get_xydata_sub(icol, _mtx, fmsi, msidata_sim, dn_data, use_avg=False, interval=1):
    nrows = dn_data.shape[0]

    col_xyarr = np.array([[icol, irow] for irow in range(nrows)])
    tform = transform.AffineTransform(matrix=_mtx)
    col_lonlatarr = tform(col_xyarr)
    
    lons, lats = col_lonlatarr[:, 0], col_lonlatarr[:, 1]

    # 2. MSI Reference Sampling (Lon/Lat -> MSI Pixels -> Radiance)
    xs, ys = tiffcoordconv.geotiff_xy2lonlat(fmsi, lons, lats, inverse=True)
    coords = np.vstack((ys.ravel(), xs.ravel()))
    _rad = map_coordinates(msidata_sim, coords, order=1, mode='nearest')
    
    _dn = dn_data[:, icol]

    # 3. Smoothing & Cleaning
    if use_avg: 
        _dn = pd.Series(_dn).rolling(window=50, center=True).mean().values
        _rad = pd.Series(_rad).rolling(window=50, center=True).mean().values
    if interval>1:
        _dn=_dn[::interval]
        _rad=_rad[::interval]
    
    mask = np.isfinite(_dn) & np.isfinite(_rad)
    _dn, _rad = _dn[mask], _rad[mask]

    return _dn, _rad

#  - extract_column_debug_data (for visual checking only)
def extract_column_debug_data(calpar_list, ib, icol, interval=5):
    """
    Extracts raw and smoothed data for a single column for independent debugging.
    """
    tot_rad=[]; tot_dn=[]
    tot_rad_avg=[]; tot_dn_avg=[]
    tot_lons=[]; tot_lats=[]; tot_xs=[]; tot_ys=[]
    for calpar in calpar_list:
        bandReg_mtx, geoTrans, data_msi_sim, fmsi = load_filepair(calpar)
        indir = calpar['indir']
        keystr = calpar['keystr']
        # Load and prepare Bluebon DN data
        ftif = f"{indir}/{keystr}_{ib}_gray.tiff"
        _dn, _ = read_raster_tif(ftif)
        # Flip for image coordinate compatibility
        dn_data = np.squeeze(_dn)[:, ::-1] 

        nrows, _ = dn_data.shape
        key = bb_bandnames[ib]
        _mtx = geoTrans.params @ bandReg_mtx[key]

        
        # 1. Spatial extraction
        col_xyarr = np.array([[icol, irow] for irow in range(nrows)])
        tform = transform.AffineTransform(matrix=_mtx)
        col_lonlatarr = tform(col_xyarr)
        
        lons, lats = col_lonlatarr[:, 0], col_lonlatarr[:, 1]
        xs, ys = tiffcoordconv.geotiff_xy2lonlat(fmsi, lons, lats, inverse=True)
        coords = np.vstack((ys.ravel(), xs.ravel()))
        
        # 2. Radiance sampling
        _rad = map_coordinates(data_msi_sim[ib, :, :], coords, order=1, mode='nearest')
        _dn = dn_data[:, icol]
        
        # 3. Smoothing (Matches the main loop)
        _dn_avg = pd.Series(_dn).rolling(window=50, center=True).mean().values
        _rad_avg = pd.Series(_rad).rolling(window=50, center=True).mean().values
    
        tot_lons=np.concatenate([tot_lons, lons])
        tot_lats=np.concatenate([tot_lats, lats])
        tot_xs=np.concatenate([tot_xs, xs])
        tot_ys=np.concatenate([tot_ys, ys])
        tot_rad=np.concatenate([tot_rad, _rad])
        tot_dn=np.concatenate([tot_dn, _dn])
        tot_rad_avg=np.concatenate([tot_rad_avg, _rad_avg])
        tot_dn_avg=np.concatenate([tot_dn_avg, _dn_avg])
        
    
    if interval>1:
        tot_dn = tot_dn[::interval]
        tot_rad= tot_rad[::interval]
        tot_dn_avg = tot_dn_avg[::interval]
        tot_rad_avg= tot_rad_avg[::interval]
        tot_lons = tot_lons[::interval]
        tot_lats = tot_lats[::interval]
        tot_xs = tot_xs[::interval]
        tot_ys = tot_ys[::interval]
    return {
        'ib': ib, 'icol': icol,
        'dn_raw': tot_dn, 'rad_raw': tot_rad,
        'dn_avg': tot_dn_avg, 'rad_avg': tot_rad_avg,
        'lons': tot_lons, 'lats': tot_lats,
        'coords_msi': (tot_xs, tot_ys)
    }
#%% 
# ## 6. Function to regress rad vs DN (calib coeffs) and store as npz
# 
def compute_calcoeffs_save(total_x, total_y, fnpz_out):
    # compute calibration coeffs
    all_band_coeffs = []
    for ib in range(len(total_x)): #len(total_x)=nb
        band_results = []
        # Sort keys to ensure column 0 comes before column 1 in your final array
        sorted_cols = sorted(total_x[ib].keys())
        
        for icol in sorted_cols:
            x = total_x[ib][icol]
            y = total_y[ib][icol]
            
            # Run fit
            coeffs = get_tame_fit(x, y, is_quadratic=False)
            band_results.append(coeffs)
        band_results.reverse()    # back to scan(sensor pixel) order
        all_band_coeffs.append(band_results)
    #Save dn2rad_coeffs to npz
    meta_data={'band_order':'PAN,MS1,..MS7','column_order':'sensor pixel order'}
    np.savez(fnpz_out, coeffs=all_band_coeffs, meta_data=meta_data)
# %% 6. Main process
# - 1) setup calpar
calpar_list=[]
# first calpar
calpar = {'fnpz':None, 'indir':None , '_gcps_ll':None ,  'fmsi':None   }
fnpz='/home/yp/Downloads/bluebon/260220_Suwon/myout/260220_025632_affineMtx_bandRegister.npz'
indir='/home/yp/Downloads/bluebon/260220_Suwon/rawDN'; keystr='260220_025632'
calpar['fnpz'] = fnpz
calpar['indir'] = indir
calpar['keystr'] = keystr
#
_gcps_ll = [
    [37.51771592,126.95896201, 0 , 124.2,  278.0], 
    [37.51809633,126.97242457, 0 , 361.0,  219.2],
    [37.49568720,127.16220045, 0, 3804.3,   39.1],
    [37.49379069,127.16153289, 0, 3801.8,   85.6],
    [37.17253197,127.08238835, 0, 3984.4, 7698.8],
    [37.17473687,127.06067079, 0, 3594.0, 7727.9],
    [37.19886709,126.88774930, 0,  426.8, 7810.0],
    [37.19929736,126.88501533, 0,  375.2, 7810.1],
    [36.88787414,126.82832587, 0,  897.2,15125.2],
    [36.8844458,126.7856303,   0,  151.5,15360.0],
    [36.83202674,126.97085791, 0, 3693.9,15879.2],
    [36.87920411,126.97835809, 0, 3592.5,14774.2]
]
calpar['_gcps_ll'] =_gcps_ll 
fmsi='/home/yp/Downloads/bluebon/260220_msi_T52SCG_dehazingtest/myout/MSI_res20m_merged_rad.tif'
calpar['fmsi']=fmsi
calpar_list.append(calpar)
# setup second calpar
calpar = {}
fnpz='/home/yp/Downloads/bluebon/250926_Khuvsgul/myout/250926_045459_affineMtx_bandRegister.npz'
indir='/home/yp/Downloads/bluebon/250926_Khuvsgul/rawDN'; keystr='250926_045459'
calpar['fnpz'] = fnpz
calpar['indir'] = indir
calpar['keystr'] = keystr
_gcps_ll = [
    [50.96998344,100.52621050, 0, 2486.5,10550.5],
    [50.9783405,100.4809444, 0, 1846.0,10526.2],
    [51.3764714,100.8047033, 0 , 3787.0,338.5],
    [51.30510752,100.78940838, 0, 3994.2,2008.2],
    [50.8917195,100.5794015, 0, 3626.0,12128.0],
    [50.80433038,100.53623967, 0, 3561.0,14262.0],
    [50.7554938,100.5131371, 0, 3538.8,15451.2]
]
calpar['_gcps_ll'] =_gcps_ll 
fmsi='/home/yp/Downloads/bluebon/250926_Khuvsgul_msi_T47UNS/myout/MSI_res20m_merged_rad.tif'
calpar['fmsi']=fmsi
calpar_list.append(calpar)
# add to calpar_list 
# read bluebon waves
f0_bb, waves_bb = rsr_f0_bluebon.compute_F0() #order MS1 MS2 ...MS7 PAN
waves_bb=np.roll(waves_bb,1) #reordering Pan, MS1, MS2, .., MS7

bb_bandnames=['PAN']+[f'MS{i+1}' for i in range(7)]
nb = len(waves_bb)


# %% [markdown]
# -2) Pre-checking for selected colpar, band, icol
# Showed similar spatial variabity but 'poor' linearity => not solved quadratic fitting
is_quadratic=True
VISUALIZE=True #True for debugging
VERBOSE=False
target_ib = 6
target_col = 2000

# 1. Extract the data
debug_data = extract_column_debug_data(calpar_list, target_ib, target_col, interval=5)
%matplotlib qt
plot_diagnostic_spatial(debug_data, use_avg=True)
plot_diagnostic_fit(debug_data, is_quadratic, use_avg=True, a_limit=5e-5)
plot_diagnostic_lonlat(debug_data)

#%%
# -3) extract all matching pairs DN and rad

interval=5 #sample every interval pixels
use_avg=False
total_x, total_y = collect_column_xy_data(calpar_list, interval, use_avg)

#%%
# -4) Save the results, dn2rad_coeffs
fnpz_out=f'dn2rad_coeffs_calpar.npz'
fnpz_out=uniquify.uniquify(fnpz_out)
compute_calcoeffs_save(total_x, total_y, fnpz_out)

#%%
# [Note] Checking slope and offset from saved npz file
Check_npz=True #Need switch
%matplotlib qt 
plot_calibration_results(fnpz_out, imageOrder=True)

# %% [markdown]
# ## 7.Main Calibration Loop (Band & Column Iteration)
# For each band and each sensor column:
# 1. Transform pixels to Lon/Lat.
# 2. Sample reference MSI radiance at those coordinates.
# 3. Perform Regression to find Slope/Offset.
# - Matching the MSI reference spectral bands to the Bluebon sensor response.
# # Execution: Main Calibration Loop
# #Storing coefficients in NPZ format and visualizing the distribution of gains/offsets across the focal plane.

##old stuff
# VISUALIZE=False
# dn2rad_coeffs = []
# for ib in range(len(waves_bb)):
#     # Load and prepare Bluebon DN data
#     ftif = f"{indir}/{keystr}_{ib}_gray.tiff"
#     _dn, _ = read_raster_tif(ftif)
#     # Flip for image coordinate compatibility
#     dn_data = np.squeeze(_dn)[:, ::-1] 
    
#     print(f"Processing Band {bb_bandnames[ib]} ({dn_data.shape[1]} columns)...")
    
#     # Call our new encapsulated helper
#     _table = calibrate_band_columns(ib, dn_data, data_msi_sim, bandReg_mtx, geoTrans, fmsi, is_quadratic=is_quadratic)
    
#     # Reorder back to scan column order and store
#     _table.reverse() 
#     dn2rad_coeffs.append(_table)

# # Save results
# fnpz_out=f'dn2rad_coeffs_{keystr}.npz'
# #Save dn2rad_coeffs to npz
# meta_data={'band_order':'PAN,MS1,..MS7','column_order':'sensor pixel order'}
# np.savez(fnpz_out, coeffs=dn2rad_coeffs, meta_data=meta_data)

# # [Note] Checking slope and offset from saved npz file
# Check_npz=True #Need switch
# %matplotlib qt 
# plot_calibration_results(fnpz, imageOrder=True)

# #  - calibrate_band_columns
# def calibrate_band_columns(ib, dn_data, data_msi_sim, bandReg_mtx, geoTrans, fmsi, is_quadratic=False, a_limit=3e-5):
#     """
#     Processes all columns for a single band to find DN-to-Radiance coefficients.
#     """
#     nrows, ncols = dn_data.shape
#     band_coeffs = []
    
#     # Pre-calculate band-specific transforms
#     key = bb_bandnames[ib]
#     _mtx = geoTrans.params @ bandReg_mtx[key]
    
#     for icol in range(ncols):
#         # 1. Coordinate Transformation (Bluebon -> Lon/Lat)
#         col_xyarr = np.array([[icol, irow] for irow in range(nrows)])
#         tform = transform.AffineTransform(matrix=_mtx)
#         col_lonlatarr = tform(col_xyarr)
        
#         lons, lats = col_lonlatarr[:, 0], col_lonlatarr[:, 1]

#         # 2. MSI Reference Sampling (Lon/Lat -> MSI Pixels -> Radiance)
#         xs, ys = tiffcoordconv.geotiff_xy2lonlat(fmsi, lons, lats, inverse=True)
#         coords = np.vstack((ys.ravel(), xs.ravel()))
#         _rad = map_coordinates(data_msi_sim[ib, :, :], coords, order=1, mode='nearest')
        
#         # 3. Smoothing & Cleaning
#         _dn = dn_data[:, icol]
#         _dn_avg = pd.Series(_dn).rolling(window=50, center=True).mean()
#         _rad_avg = pd.Series(_rad).rolling(window=50, center=True).mean()
        
#         mask = np.isfinite(_dn_avg) & np.isfinite(_rad_avg)
#         x, y = _dn_avg[mask], _rad_avg[mask]

#         # 4. Regression
#         params = get_tame_fit(x, y, is_quadratic=is_quadratic, a_limit=a_limit)
        
#         if params is not None:
#             band_coeffs.append(list(params))
#         else:
#             # Fallback if fit fails (e.g., all zeros)
#             band_coeffs.append([0, 0, 0] if is_quadratic else [0, 0])
            
#     return band_coeffs
