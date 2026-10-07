#!/usr/bin/env python3
"""Final PS product: SCLA- and SCN-corrected LOS displacement + WLS velocity.

Follows ps_output.py's formulation but streams the big arrays so 6.3M PS x 32
epochs fits comfortably, and writes GeoPackage/Parquet instead of a shapefile
(which caps at 2 GB).
"""
import os
import numpy as np

PROC = '<DATA_ROOT>/S1_PSInSAR/INSAR_20241208'
OUT = '<DATA_ROOT>/S1_PSInSAR/results'
COH_THRESH = float(os.environ.get('COH_THRESH', 0.6))

ps = np.load(f'{PROC}/ps2.npy', allow_pickle=True).item()
parms = np.load(f'{PROC}/parms.npy', allow_pickle=True).item()
lam = float(parms['lambda'])
n_ps, n_ifg = ps['n_ps'], ps['n_ifg']
mix = int(ps['master_ix'])
print(f"  n_ps={n_ps:,}  n_ifg={n_ifg}  lambda={lam:.9f}  master_ix={mix}")

# --- 보정 위상 (블록 처리) ---
ph = np.load(f'{PROC}/phuw2.npy', allow_pickle=True).item()['ph_uw'].astype(np.float32)
for name, key in (('scla2.npy', 'ph_scla'), ('scn2.npy', 'ph_scn_slave')):
    d = np.load(f'{PROC}/{name}', allow_pickle=True).item()
    a = d[key]
    for lo in range(0, n_ps, 500000):
        hi = min(lo + 500000, n_ps)
        ph[lo:hi, :] -= a[lo:hi, :].astype(np.float32)
    del d, a
    print(f"  {key} 차감 완료")

# --- 기준점 차감 ---
from psi_python.ps_setref import ps_setref
os.chdir(PROC)
ref = np.asarray(ps_setref()).ravel()
ref_ts = np.nanmean(ph[ref, :], axis=0).astype(np.float32)
ph -= ref_ts
print(f"  기준 PS {ref.size}개 차감")

# --- 마스크 ---
coh = np.asarray(np.load(f'{PROC}/pm2.npy', allow_pickle=True).item()['coh_ps']).ravel()
keep = (coh > COH_THRESH) & np.isfinite(ph[:, 0])
print(f"  coh>{COH_THRESH} 및 유한값 -> {keep.sum():,} / {n_ps:,} ({100*keep.mean():.1f}%)")

# --- WLS 속도 (간섭도 표준편차 가중) ---
day = np.asarray(ps['day']).ravel()
t = (day - ps['master_day']).astype('timedelta64[D]').astype(float) / 365.25
idx = np.setdiff1d(np.arange(n_ifg), [mix])
G = np.column_stack([np.ones(idx.size), t[idx]])
ifgstd = np.load(f'{PROC}/ifgstd2.npy', allow_pickle=True).item()
var = (np.asarray(ifgstd['ifg_std']).squeeze() * np.pi / 181.0) ** 2
W = np.diag(1.0 / var[idx])
lhs = G.T @ W @ G
pinv = np.linalg.solve(lhs, G.T @ W)          # 2 x n_used

vel = np.empty(n_ps, dtype=np.float32)
for lo in range(0, n_ps, 500000):
    hi = min(lo + 500000, n_ps)
    m = pinv @ ph[lo:hi, idx].T                # 2 x blk
    vel[lo:hi] = (-m[1, :] / (4 * np.pi) * lam * 1000).astype(np.float32)
print("  WLS 속도 산출 완료")

disp_mm = (-ph * lam * 1000.0 / (4 * np.pi)).astype(np.float32)   # 전 기간 변위 시계열
del ph

hgt = np.asarray(np.load(f'{PROC}/hgt2.npy', allow_pickle=True).item()['hgt']).ravel()
inc = np.asarray(np.load(f'{PROC}/inc2.npy', allow_pickle=True).item()['inc']).ravel()

np.savez_compressed(f'{OUT}/seoul_csk_ps.npz',
                    lon=ps['lonlat'][keep, 0].astype(np.float32),
                    lat=ps['lonlat'][keep, 1].astype(np.float32),
                    vel_mm_yr=vel[keep], coh=coh[keep].astype(np.float32),
                    hgt_m=hgt[keep].astype(np.float32), inc_deg=inc[keep].astype(np.float32),
                    disp_mm=disp_mm[keep, :], day=day, master_ix=mix,
                    coh_thresh=COH_THRESH, lam=lam)
print(f"  저장: {OUT}/seoul_csk_ps.npz")

v = vel[keep]
print(f"\n=== LOS 속도 분포 (mm/yr, 음수=위성에서 멀어짐=침하) ===")
for q in (1, 5, 25, 50, 75, 95, 99):
    print(f"   {q:3d}%  {np.nanpercentile(v, q):8.2f}")
print(f"   평균 {np.nanmean(v):.2f}  표준편차 {np.nanstd(v):.2f}")
d_end = disp_mm[keep, -1]
print(f"\n=== 기간말(2026-08-26) 누적 LOS 변위 (mm) ===")
for q in (1, 5, 50, 95, 99):
    print(f"   {q:3d}%  {np.nanpercentile(d_end, q):8.2f}")
