#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug 23 22:54:23 2025
test for blubon linear noise
@author: yp
"""
import numpy as np
import sys
sys.path.append('./../../tools')
import ncutils
from genrgb import gen_rgb
fnc = '<WORK_ROOT>/Downloads/bluebon/250716_Bahrain/myout/250716_074255_stacked_rhot.nc'
indata = ncutils.getimage(fnc, bip=False, noScale=False)
ibd=6
data_b6 = indata[ibd,:,:]
ibd=3
data = indata[ibd,:,:]
data.shape

aves = np.mean(data, axis=0)
stds = np.std(data, axis=0)


cols = np.arange(data.shape[1])

import matplotlib.pyplot as plt

def moving_average(x, w=10):
    """Box (moving) average with window size w."""
    return np.convolve(x, np.ones(w)/w, mode='same')

box_mean = moving_average(aves, w=21)

# Plot mean
plt.figure()
plt.plot(cols, aves, label="Mean", linewidth=1.5)
plt.plot(cols, box_mean, label="Box-averaged mean (w=10)", color="red", linewidth=1)
plt.xlabel("Column index")
plt.ylabel("Mean value")
plt.title("Column-wise Mean")
plt.legend()
plt.grid(True)
plt.show()

plt.figure()
plt.plot(cols, aves-box_mean, '-x',label="diff", linewidth=1.5)
plt.xlabel("Column index")
plt.ylabel("difference")
plt.title("Column-wise Diff")
plt.legend()
plt.grid(True)
plt.show()

# Plot std
plt.figure()
plt.plot(cols, stds, label="Std Dev", color="orange", linewidth=1.5)
plt.xlabel("Column index")
plt.ylabel("Standard deviation")
plt.title("Column-wise Std Dev")
plt.legend()
plt.grid(True)
plt.show()

box_mean = moving_average(aves, w=25)
mean_diff = aves-box_mean
data_c = data - mean_diff[None,:]
gen_rgb(data, ofilepath='original_data')
gen_rgb(data_c, ofilepath='correcte_data')

aves_v = np.mean(data, axis=1)
box_mean = moving_average(aves_v, w=15)
mean_diff = aves_v-box_mean
data_cc = data_c - mean_diff[:,None]
gen_rgb(data_cc, ofilepath='correcte_data2')


import scipy.ndimage as nd
def fill_nan_nearest(img, mask):
    # mask = np.isnan(img)
    # Get indices of valid pixels
    idx = nd.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return img[tuple(idx)]

mask = data_b6 > 0.03 #land or cloud

data_w = fill_nan_nearest(data, mask)
# data_w=np.copy(data)
# data_w[mask]=0.

from scipy.ndimage import uniform_filter1d
# from scipy.ndimage import median_filter

w = 21  # box size
# edge handling: 'nearest' ~ like extending edge pixels; use 'constant' to mimic zero-padding
box_mean = uniform_filter1d(data_w, size=w, axis=1, mode='nearest')
# box_mean = median_filter(data, size=(1,w))# slightly slow, nogood for linear noise
diff_data = data_w - box_mean
diff_data[mask]=np.nan
mean_diff = np.nanmean(diff_data, axis=0)
data_c = data - mean_diff[None,:]
# data_c[mask]=data[mask]
gen_rgb(data_c, ofilepath='corrected_data_w')

data_w = fill_nan_nearest(data_c, mask)
# data_w=np.copy(data_c)
# data_w[mask]=0.

box_mean = uniform_filter1d(data_w, size=w, axis=0, mode='nearest')
diff_data = data_w - box_mean
diff_data[mask]=np.nan
mean_diff = np.nanmean(diff_data, axis=1)
data_cc = data_c - mean_diff[:,None]
# data_cc[mask]=data[mask]
gen_rgb(data_cc, ofilepath='corrected_data_wh')
    
# plt.figure()
# plt.plot(data, diff_data, '+')
# plt.xlabel("data")
# plt.ylabel("correction")
# plt.show()