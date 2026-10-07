#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Mar  9 10:55:18 2026
Bluebon calibration to MSI needs Bluebon DN - msi20m pixel pairing, which involves
two transforms - per-band (j,i) to (lon,lat) transform and (lon, lat) to msi pixel xy conversion
The former transform is equivalent to per-band geocorrection.
The geocorrection is a combination of two steps, band registration and geocorrection.
in this work, both steps utilize skimage 'Affine' transformation, of which inverse is obvious.
Pan band is not considered because of failure in registration of the band.

First, required is step by step verification bluebon per-band pixel to (lon,lat) transformation. 
Example: band i (x,y) in rawDN -> (x1,y1) in stacked -> (lon, lat) -> msi (x2, y2) -> msi-based radiance

Then, for each band and each column, bluebon DN - msi radiance radiance compared. 
Slope and intercept are derived. Visual check with scatter plot 
** previous DN-radiance conversion, compute_coef_rad2DN_coefs.py assume that inter-band register is only shift. 
@author: yp
"""

# %% [markdown]
# ##import modules
%matplotlib inline

import numpy as np
from skimage import transform
import rasterio
import sys
sys.path.append('../src')
import rsr_f0_bluebon
sys.path.append('../../tools')
import ncutils, tiffutils
from scipy.interpolate import interp1d
sys.path.append('../../polygonTools/src_pt')
import tiffcoordconv

import matplotlib.pyplot as plt
# spatial bilinear interpolation
from scipy.ndimage import map_coordinates
import pandas as pd

# %% [markdown]
# # Step 1: bandReg(Band registration) model Import
# loading affine model from a npz file and copy to a dictionary and close the loader

fnpz='/home/yp/Downloads/bluebon/260220_Suwon/myout/260220_025632_affineMtx_bandRegister.npz'
_loader=np.load(fnpz)
bandReg_mtx = {key.replace('arr_','MS'): _loader[key] for key in _loader.files}
_loader.close()

print(len(bandReg_mtx), bandReg_mtx.keys()) #8bands

# Check the loaded model params printing the trans matrix.
for key in bandReg_mtx.keys():
    print(key)
    print(bandReg_mtx[key])

# %% [markdown]
# Quick check bandRegistration
if 0:
    key='MS1'
    tform0 = transform.AffineTransform(matrix=bandReg_mtx[key])
    print('band registration (0,0)=',tform0([0.,0.]))
    print('band registration inv=',tform0.inverse(tform0([0.,0.])[0]))

    print('band registration inv=',tform0.inverse([0,0]))

# %% [markdown]
# # Step2 : Geocorrection Affine model
# Reference_band (bandno=4) to lonlat conversion model based on **gcps_ll**
# which is prepared here by visual idenfication of feature points with zview and Qgis software  
indir='/home/yp/Downloads/bluebon/260220_Suwon/myout'; keystr='260220_025632'
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
gcps_ll = [[r[1],r[0]]+r[2:] for r in _gcps_ll] #lat, lon -> lon, lat
gcps_ll = np.array(gcps_ll)
dst = gcps_ll[:,:2]
src = gcps_ll[:,3:]
geoTrans=transform.estimate_transform('affine',src,dst)
print("Geocorr Matrix:\n", geoTrans.params)

# Check the geocorr model **residuals**
residuals = geoTrans.residuals(src, dst)
print("Mean Residual Error:", np.mean(residuals)) #0.0002856171431174981

#%% [markdown]
def read_raster_tif(ftif):
    with rasterio.open(ftif) as src:
        data = src.read()  # shape: (bands, rows, cols)
        profile = src.profile  # metadata like crs, transform, dtype
    return data, profile


def xyArr2lonlatArr(ib, xyarr, bandReg_mtx, geoTrans):
    #ib [0,1,..7] for [Pan, MS1, .., Ms7]
    key = list(bandReg_mtx.keys())[ib]
    print(bandReg_mtx[key])
    tform0 = transform.AffineTransform(matrix=bandReg_mtx[key])
    _M = geoTrans.params@bandReg_mtx[key]
    tform = transform.AffineTransform(matrix=_M)
    lonlatarr = tform(xyarr)
    
    return lonlatarr

# %% [markdown]
# ## Define ODR-Ordinary Distance Regression fit
from scipy.optimize import curve_fit
from scipy import odr

def get_tame_fit(x_input, y_input, is_quadratic=False, a_limit=1e-10):
    """
    Tame Fit Function.
    - Performs Orthogonal Distance Regression (Unbiased Linear Regression).
    - is_quadratic=True: Uses curve_fit with bounds to keep 'a' small.
    - a_limit: The maximum allowed absolute value for the quadratic term 'a'.
    - quadratic coeff limit produces visually better fit 
    """
    # 1. Clean Data
    x_arr = np.asarray(x_input).flatten()
    y_arr = np.asarray(y_input).flatten()
    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_c, y_c = x_arr[mask], y_arr[mask]

    if len(x_c) < (3 if is_quadratic else 2): return None

    if is_quadratic:
        def model(x, a, b, c): return a*x**2 + b*x + c
        
        lower_bounds = [-a_limit, -np.inf, -np.inf]
        upper_bounds = [ a_limit,  np.inf,  np.inf]
        
        # 1. Get the standard guess
        p0 = list(np.polyfit(x_c, y_c, 2))
        
        # 2. "CLIP" the guess so it is inside the bounds
        # This prevents the "Initial guess is outside of bounds" error
        p0[0] = np.clip(p0[0], -a_limit, a_limit)
        
        try:
            popt, _ = curve_fit(model, x_c, y_c, p0=p0, bounds=(lower_bounds, upper_bounds))
            return popt
        except Exception as e:
            print(f"Fit failed: {e}")
            return None
    else:
        # Fallback to standard ODR for Linear
        def lin_func(p, x): return p[0] * x + p[1]
        model = odr.Model(lin_func)
        data = odr.Data(x_c, y_c)
        my_odr = odr.ODR(data, model, beta0=np.polyfit(x_c, y_c, 1))
        return my_odr.run().beta # [m, b]
    

# %%
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

# %% [markdown]
# #==== MSI_sim data
# read bluebon waves
f0_bb, waves_bb = rsr_f0_bluebon.compute_F0() #order MS1 MS2 ...MS7 PAN
waves_bb=np.roll(waves_bb,1) #reorder Pan, MS1, MS2, .., MS7

# read msi data and waves
fmsi='/home/yp/Downloads/bluebon/260220_msi_T52SCG_dehazingtest/myout/MSI_res20m_merged_rad.tif'
data_msi=tiffutils.getraster(fmsi,None)
waves_msi=tiffutils.get_waves_tif(fmsi)

# generate simulated rad data using wavelength_interpolation to bluebon  

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
# %% [markdown]
# # Combined transformation, Scan-to-lonlat
# _M = geoTrans.params@bandReg_mtx[key], key in ['MS0','MS1',...'MS7'],  MS0 ≡ Pan
print('bandReq_mtx keys=',bandReg_mtx.keys())

VISUALIZE=True 
IN_LOOP=False

ib = 6
key=f'MS{ib}'
tform0 = transform.AffineTransform(matrix=bandReg_mtx[key])
print(f'{key} (0,0) registered to:',tform0([0.,0.]))

_mtx = geoTrans.params@bandReg_mtx[key] #combine
tform = transform.AffineTransform(matrix=_mtx)
print(f'{key} lonlat (0,0) => ',tform([0.,0.]))
# print('band registration (4094,15998)=',tform0([0,0]))
# print('lonlat (0,0) => ',tform([0,0]))


#%% [markdown]
# ##read bluebon rawDN data for a band f'MS{ib}'
#%%
# ##read bluebon band dn data
indir='/home/yp/Downloads/bluebon/260220_Suwon/rawDN'
keystr='260220_025632'
#Pan,MS1...
ftif = indir+f'/{keystr}_{ib}_gray.tiff'
_dn, _profile = read_raster_tif(ftif)
dn_data = np.squeeze(_dn)[:,::-1] #left <-> right: convert to image coordinates compatible bandregister and geoCorr 
nrows, ncols =dn_data.shape #bluebon image shape
print(f'bluebon band {ib} dn_data.shape={dn_data.shape}')

# %%
# ##Need iteration for icol

icol = ncols-1

# %%[markdown]
# ###compute lons, lats for bluebon ib band and icol
col_xyarr = np.array( [[icol, irow] for irow in range(nrows)] )
col_lonlatarr = xyArr2lonlatArr(ib, col_xyarr, bandReg_mtx, geoTrans)
print(col_lonlatarr[:10])

lons=col_lonlatarr[:,0]
lats=col_lonlatarr[:,1]
#%%
if 0: #lat, lon vs row number
    fig, ax1 = plt.subplots()
    ax1.plot(lats)
    ax2=ax1.twinx()
    ax2.plot(lons, color='tab:red')
    plt.show()

#%%
xs, ys=tiffcoordconv.geotiff_xy2lonlat(fmsi, lons, lats, inverse=True)
# jarr=np.round(xs).astype(np.int32)
# iarr=np.round(ys).astype(np.int32)

coords = np.vstack((ys.ravel(), xs.ravel())) #xs, ys float
_rad = map_coordinates(data_msi_sim[ib,:,:], coords, order=1, mode='nearest')
# print(_rad)

# ##pick icol data
_dn = dn_data[:,icol]
# print(_dn)
# %%
if 0:
    m, b = np.polyfit(_dn, _rad, 1)
    plt.scatter(_dn, _rad, marker='+', color='gray', alpha=0.5, label='Data Points')
    plt.plot(_dn, m*np.array(_dn) + b, color='red', label='Linear Fit')
    equation_text = f'y = {m:.2f}x + {b:.2f}'
    plt.text(0.05, 0.95, equation_text, transform=plt.gca().transAxes, 
            fontsize=12, verticalalignment='top', color='red', weight='bold')
    plt.xlabel('DN Value')
    plt.ylabel('Radiation')
    plt.legend()
    plt.show()
#

# %% [markdown]
# ##Checking consitency in spatial variation between Blue
if VISUALIZE and not IN_LOOP:
    fig, ax1 = plt.subplots()
    _dn_avg = pd.Series(_dn).rolling(window=50, center=True).mean()
    lns1=ax1.plot(_dn_avg, linewidth=1, label='DN box mean')
    ax1.set_ylabel('Bluebon DN')
    ax2=ax1.twinx()
    _rad_avg = pd.Series(_rad).rolling(window=50, center=True).mean()
    lns2=ax2.plot(_rad_avg, linewidth=1, color='tab:red', alpha=0.5, label='radiance box mean')
    ax2.set_ylabel('MSI radiance')
    ax1.set_xlabel('row number')
    lns=lns1 + lns2
    labs=[l.get_label() for l in lns]
    ax1.legend(lns, labs)
    plt.title(f"band:{ib} icol:{icol}")
    plt.show()

#%% [markdown]
# ##define x, y for regression
xraw=_dn_avg
yraw=_rad_avg
mask = np.isfinite(xraw) & np.isfinite(yraw)
x = xraw[mask]
y = yraw[mask]

#%% [markdown]
# ### Running the Tame Quadratic Fit
# Constraining 'a' to be very close to zero.

# Example: force 'a' to be extremely small
params = get_tame_fit(x, y, is_quadratic=True, a_limit=3e-5)

if params is None:
    print('Fitting failed')
else:
    if VISUALIZE and not IN_LOOP:
        # 1. Create a smooth x-axis for the curve
        x_fit = np.linspace(min(x), max(x), 500)
        # 2. Calculate y values for the curve

        a, b, c = params
        y_fit = a * x_fit**2 + b * x_fit + c
        label = f'y = ({a:.2e})$x^2$ + ({b:.2f})x + ({c:.2f})'
        equation_str, root1, root2 = get_factored_string(a, b, c)
        print(f"Factored Form: {equation_str}")
        label = f'{equation_str}'
        
        # 3. Plotting
        plt.scatter(x, y, marker='+', alpha=0.3, label='Data')
        plt.plot(x_fit, y_fit, color='orange', linewidth=2, label='ODR quadratic fit')
        
        # Format the equation for the plot
        plt.title(f"Fit Result band:{ib} col:{icol}\n{label}")
        plt.xlabel('DN Value')
        plt.ylabel('radiance-MSI unit')
        plt.legend()
        plt.show()

#%% [markdown]
# ### Running the odr linear fit
params = get_tame_fit(x, y, is_quadratic=False, a_limit=1e-5)

if params is None:
    print('Fitting failed')
else:
    if VISUALIZE and not IN_LOOP:
        # 1. Create a smooth x-axis for the curve
        x_fit = np.linspace(min(x), max(x), 500)
        # 2. Calculate y values for the curve

        b, c = params
        y_fit = b * x_fit + c
        label = f'y = ({b:.2f})x + ({c:.2f})'
        equation_str, root1 = get_factored_string_linear(b, c)
        print(f"Factored Form: {equation_str}")
        label = f'{equation_str}'
        
        # 3. Plotting
        plt.scatter(x, y, marker='+', alpha=0.3, label='Data')
        plt.plot(x_fit, y_fit, color='orange', linewidth=2, label='ODR linear fit')
        
        # Format the equation for the plot
        plt.title(f"Fit Result band:{ib} col:{icol}\n{label}")
        plt.xlabel('DN Value')
        plt.ylabel('radiance-MSI unit')
        plt.legend()
        plt.show()

# %%
