import numpy as np
import pandas as pd
def read_bb_srf():
    fcsv_srf = '/home/yp/myPy/bluebon/calib/Spectral Response Function.csv'
    df = pd.read_csv(fcsv_srf) #this fast
    column_names=df.columns.tolist()
    # print('\n')
    # print('srf colnames:',column_names)
    waves=df['wavelength(nm)'].to_numpy()
    srf_data=df.iloc[:,1:].to_numpy().transpose()
    return waves, srf_data, column_names

# def define_rsr_bb(waves):
#     wave0 = 400. + np.arange(501) #400-900
#     rsr=[]
#     for ib in range(len(waves)):
#         _rsr = np.zeros(len(wave0))
#         _rsr[np.logical_and((waves[ib]-10 < wave0), ( wave0 <waves[ib]+10.)) ]=1
#         rsr.append(_rsr)
#     return wave0, np.array(rsr)

import sys
sys.path.append(r'../../g2l1bpy/LUT')
import read_Thuillier
def compute_F0():
    # wave0, rsr = define_rsr_bb(waves_bb)
    wave0, rsr, col_names = read_bb_srf()
    wave_ave = np.sum(wave0*rsr, axis=1)/np.sum(rsr,axis=1)
    
    (_wave, _f0) = read_Thuillier.read_Thuillier_F0()
    f0 = np.interp(wave0, _wave, _f0)
    f0_ave = np.sum(f0*rsr, axis=1)/np.sum(rsr,axis=1)
    return f0_ave, wave_ave