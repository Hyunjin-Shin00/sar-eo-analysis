#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Apr  3 15:08:18 2026
spectra pairs -> haze spectrum 
multiple haze spectra -> linear haze model
@author: yp
"""
import sys
sys.path.append('../../tools')
import ncutils
import matplotlib.pyplot as plt
def plot_haze_specs(fnc, reps, models):
    waves = ncutils.readheader(fnc)['waves']
    colors = plt.cm.viridis(np.linspace(0, 1, len(reps)))
    
    plt.figure()
    for i, (ydata, color) in enumerate(zip(reps, colors)):
        plt.plot(waves, ydata, color=color, label=f'Sample {i+1}')
    for i, (ydata, color) in enumerate(zip(models, colors)):
        plt.plot(waves, ydata, color=color, linestyle='--',label=f'Model {i+1}')
    plt.xticks(waves, rotation=45, ha='right')
    plt.legend()
    plt.show()

import numpy as np

def haze_model(R_in):
    """
    R_in: (N, B)

    return:
        R_model: (N, B)  # 모델 구조로 재구성된 spectra
        a, b: (B,)       # 내부적으로 추정된 계수
    """
    R_in = np.asarray(R_in)
    x = R_in[:, 0]  # (N,)
    xmin, xmax=min(x), max(x)
    N, B = R_in.shape

    a = np.zeros(B)
    b = np.zeros(B)
    

    for i in range(B):
        # R_in[:, i] ≈ a_i * x + b_i
        X = np.vstack([x, np.ones(N)]).T
        y = R_in[:, i]

        coeff, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        a[i], b[i] = coeff

    # R_model = np.zeros_like(R_in)
    # for i in range(B):
    #     R_model[:, i] = a[i] * x + b[i]

    return a, b, xmin, xmax#, R_model



if __name__ == "__main__":    
    #hi/lo pairs
    rho_pairs =[
            [
                [0.12550165, 0.08993524, 0.078261614, 0.0728871, 0.078244925, 0.07347744, 0.075752944, 0.057884622], #(center: 1195.5, 5742.0)
                [0.11375808, 0.076329105, 0.06473778, 0.054609265, 0.058367144, 0.055513706, 0.05442754, 0.03445834] #(center: 1191.5, 5759.5)
             ],
            [
                [0.20363243, 0.18061647, 0.18790342, 0.19887617, 0.23928969, 0.25592738, 0.27516216, 0.2436103], #(center: 1123.5, 5931.0)
                [0.11527473, 0.07712538, 0.065517746, 0.0559306, 0.058076736, 0.053993598, 0.054770917, 0.038161915] #(center: 1102.0, 5966.0)
            ],
            [
                [0.17783186, 0.15164417, 0.14807518, 0.1600069, 0.18195662, 0.1963017, 0.2161874, 0.1898423], #(center: 1120.0, 5911.5)
                [0.11527473, 0.07712538, 0.065517746, 0.0559306, 0.058076736, 0.053993598, 0.054770917, 0.038161915]
            ],
            [
                [0.15950255, 0.12994821, 0.12203123, 0.12858215, 0.14156678, 0.15238945, 0.16035867, 0.14058378], #(center: 1151.0, 5897.5)
                [0.11527473, 0.07712538, 0.065517746, 0.0559306, 0.058076736, 0.053993598, 0.054770917, 0.038161915]
            ],
            [
                [0.1735439, 0.14486457, 0.1434165, 0.15384147, 0.17709468, 0.20009613, 0.20746167, 0.19384907], #(center: 2383.0, 11050.25)
                [0.12736236, 0.09189921, 0.08278489, 0.077063926, 0.08549747, 0.0888486, 0.08999419, 0.06671714] #(center: 2389.5, 11022.5)
            ]
           ]
    
    rho_haze = [ [a-b for a,b in zip(r[0],r[1])] for r in rho_pairs ]
    a,b,xmin, xmax = haze_model(rho_haze)
    rho_haze=np.array(rho_haze)
    rho_haze_fit = [[ai*x+bi for ai, bi  in zip(a,b)]  for x in rho_haze[:,0]]
    fnc='/home/yp/Downloads/bluebon/260209_Suwon/myout/260209_025928_stacked_rhot.nc'
    plot_haze_specs(fnc, rho_haze, rho_haze_fit)




