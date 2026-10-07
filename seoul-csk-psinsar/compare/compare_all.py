#!/usr/bin/env python3
"""Four-way comparison: CSK PS / CSK SBAS / S1 PS / S1 SBAS.

Everything is brought to the same footing before comparing:
  - same reference point (Ansan granite, 126.9518 / 37.5742)
  - LOS -> vertical using cos(incidence); `inc` is stored in RADIANS
  - the same observation window when comparing displacement
S1's 2.6-year record is the only one that can separate the annual cycle from a
secular trend, so it is used as the reference for quantifying the others' bias.
The common reference is 성북, not the PS products' own 안산 tie point: it is the
only pixel that survives in both SBAS solutions, and a constant offset is all a
change of reference costs.
"""
import json
import numpy as np
from scipy.spatial import cKDTree

CSK = '<DATA_ROOT>/CSK_PSInSAR'
S1 = '<DATA_ROOT>/S1_PSInSAR'
REF_LL = (127.06254, 37.607475)     # 성북 — 4종 전부에서 유효한 유일한 공통점
                                    # (안산은 SBAS 두 종 모두 연결성분 62%로 탈락)
OVERLAP = ('2025-12-05', '2026-04-26')
KX = lambda lo, la: np.column_stack([np.asarray(lo) * 111320 * np.cos(np.radians(37.55)),
                                     np.asarray(la) * 110540])


def load_ps(npz):
    Z = np.load(npz)
    inc = np.asarray(Z['inc_deg'], float)          # 라디안
    return dict(lon=Z['lon'], lat=Z['lat'], disp=Z['disp_mm'], day=Z['day'],
                coh=Z['coh'], hgt=Z['hgt_m'], kv=1.0 / np.cos(inc),
                master_ix=int(Z['master_ix']))


def load_sbas(geodir, tsfile, cohfile, maskfile=None, tc_min=0.5):
    import h5py
    f = h5py.File(f'{geodir}/{tsfile}', 'r')
    ts = f['timeseries'][:] * 1000.0
    A = dict(f.attrs); dates = [d.decode() for d in f['date'][:]]; f.close()
    t = h5py.File(f'{geodir}/{cohfile}', 'r')
    tc = t[list(t.keys())[0]][:]; t.close()
    x0, y0 = float(A['X_FIRST']), float(A['Y_FIRST'])
    dx, dy = float(A['X_STEP']), float(A['Y_STEP'])
    ny, nx = tc.shape
    lon = x0 + np.arange(nx) * dx
    lat = y0 + np.arange(ny) * dy
    LO, LA = np.meshgrid(lon, lat)
    sel = np.isfinite(ts[0]) & (tc >= tc_min)
    day = np.array([np.datetime64(f'{d[:4]}-{d[4:6]}-{d[6:]}') for d in dates])
    return dict(lon=LO[sel], lat=LA[sel], disp=ts[:, sel].T, day=day, coh=tc[sel])


def reref(D, rad=300.0):
    """Shift the whole stack so the Ansan patch reads zero at every epoch."""
    d = np.hypot((D['lat'] - REF_LL[1]) * 110540,
                 (D['lon'] - REF_LL[0]) * 111320 * np.cos(np.radians(REF_LL[1])))
    m = d <= rad
    if m.sum() < 20:
        return False, int(m.sum())
    D['disp'] = D['disp'] - np.nanmean(D['disp'][m, :], axis=0)
    return True, int(m.sum())


def window_delta(D, t0, t1):
    day = D['day'].astype('datetime64[D]')
    i0 = int(np.argmin(np.abs(day - np.datetime64(t0))))
    i1 = int(np.argmin(np.abs(day - np.datetime64(t1))))
    return D['disp'][:, i1] - D['disp'][:, i0], str(day[i0]), str(day[i1])


def fit_secular(D):
    """Linear + annual + semi-annual; returns secular (mm/yr) and annual amp (mm)."""
    day = D['day'].astype('datetime64[D]')
    t = (day - day[0]).astype(int) / 365.25
    A = np.column_stack([t, np.ones_like(t), np.cos(2 * np.pi * t), np.sin(2 * np.pi * t),
                         np.cos(4 * np.pi * t), np.sin(4 * np.pi * t)])
    sol, *_ = np.linalg.lstsq(A, D['disp'].T, rcond=None)
    lin, *_ = np.linalg.lstsq(A[:, :2], D['disp'].T, rcond=None)
    return sol[0], np.hypot(sol[2], sol[3]), lin[0]


def grid_mean(lon, lat, val, cell=0.01, nmin=20):
    import pandas as pd
    k = (np.round(lon / cell).astype(int) * 100000 + np.round(lat / cell).astype(int))
    df = pd.DataFrame({'k': k, 'v': val}).groupby('k')['v'].agg(['mean', 'size'])
    df = df[df['size'] >= nmin]
    return df.index.values, df['mean'].values


def match(src, dst_lon, dst_lat, dst_val, rad=60.0, nmin=3):
    """For each src point, the mean dst value within rad."""
    tree = cKDTree(KX(dst_lon, dst_lat))
    nb = tree.query_ball_point(KX(src['lon'], src['lat']), rad, workers=8)
    return np.array([np.nanmean(dst_val[i]) if len(i) >= nmin else np.nan for i in nb])


def window_rate(D, t0, t1):
    """Linear rate over every epoch inside [t0, t1].

    A two-epoch difference carries the full atmospheric delay of both dates;
    over a five-month window in Seoul that noise is several times the ground
    motion.  Fitting all epochs in the window instead divides it by ~sqrt(N).
    Returns (mm/yr, cumulative mm over the window, n_epochs, first, last).
    """
    day = D['day'].astype('datetime64[D]')
    m = (day >= np.datetime64(t0)) & (day <= np.datetime64(t1))
    t = (day[m] - day[m][0]).astype(int) / 365.25
    A = np.column_stack([t, np.ones_like(t)])
    sol, *_ = np.linalg.lstsq(A, D['disp'][:, m].T, rcond=None)
    return sol[0], sol[0] * t[-1], int(m.sum()), str(day[m][0]), str(day[m][-1])


def full_rate(D):
    """Linear rate over the product's whole record (mm/yr)."""
    day = D['day'].astype('datetime64[D]')
    t = (day - day[0]).astype(int) / 365.25
    A = np.column_stack([t, np.ones_like(t)])
    sol, *_ = np.linalg.lstsq(A, D['disp'].T, rcond=None)
    return sol[0], float(t[-1])
