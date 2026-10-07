"""
Gao, Zribi, Escorihuela & Baghdadi (2017) Sensors 17(9):1966, doi:10.3390/s17091966
"Synergetic Use of Sentinel-1 and Sentinel-2 Data for Soil Moisture Mapping at 100 m Resolution"
의 방법 1·2를 그대로 구현해 가평(RDA 가평읍 관측소 주변 약 10×10 km)에 적용.

  입력  S1 VV σ0 (궤도·열잡음·보정·SRTM 30m 지형보정, 필터 없음) → 100 m 평균(선형) → dB
        S2 NDVI (구름마스크) → 100 m → S1 날짜로 시간 선형보간
  마스크 NDVI<0.1(물)·NDVI>0.8(산림) 제외, σ0<−15 dB 제외                      (논문 3.1)

  방법1 (Eq.3–8)
        σdry(i,j,class) = 해당 NDVI 등급(0.1 간격)에서 셀의 최저 σ0
        Δσ = σ0(d) − σdry
        f(NDVI) = a·NDVI + Δσmax_bare : NDVI 값별 Δσ 의 상위 1% 제외 최댓값(=99백분위)에 선형회귀
        Mv = Δσ / f(NDVI) · (Mvmax − Mvmin) + Mvmin,   Mvmax=0.32, Mvmin=0.05 (논문값)
  방법2 (Eq.9–11)
        δσ = σ0(t2) − σ0(t1),  NDVI = 두 날짜 평균
        g(NDVI) = b·NDVI + δσmax_bare : NDVI 값별 |δσ| 의 상위 1% 제외 최댓값에 선형회귀
        Mv(t2) = Mv(t1) + δσ / g(NDVI) · δMvmax,   δMvmax = 0.15, 시작일 = 현장관측값으로 초기화

논문에 명시되지 않은 구현 선택(보고서에 명기):
  - NDVI 시간보간: 픽셀별 선형, S2 관측 사이 간격 45일 초과 구간은 무효
  - '각 NDVI 값별' 상위 1% 처리: NDVI 0.02 폭 구간, 구간당 표본 50개 이상만 회귀에 사용
  - Mv 범위: 방법1은 [Mvmin, Mvmax] 로 자름(논문 그림 범위와 동일), 방법2는 [0.02, 0.50]
  - 방법2에서 마스크된 쌍은 δMv=0 (값 유지)
"""
import glob, json, os, re
import numpy as np, pandas as pd, rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin

import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from site_config import C, SITE
DATA = C["data"]; OUT = C["out"]; os.makedirs(f"{OUT}/maps_method1", exist_ok=True); os.makedirs(f"{OUT}/maps_method2", exist_ok=True)
MVMAX, MVMIN, DMVMAX = 0.32, 0.05, 0.15
LON, LAT = C["lon"], C["lat"]

# ---------------- 격자 ----------------
z = np.load(f"{DATA}/s2_ndvi_100m.npz")
H, W, RES = int(z["height"]), int(z["width"]), float(z["res"])
TR = from_origin(float(z["x0"]), float(z["y1"]), RES, RES); CRS = f"EPSG:{int(z['epsg'])}"
s2_dates = pd.to_datetime(z["dates"]); s2 = z["ndvi"]

# ---------------- S1 VV → 100 m ----------------
files = sorted(glob.glob(f"{DATA}/s1_proc/*_sigma0.tif"))
s1_dates, vv = [], []
for f in files:
    try:
        s = rasterio.open(f)
    except rasterio.errors.RasterioIOError:
        print("skip (미완성 파일)", os.path.basename(f)); continue
    with s:
        a = s.read(2).astype(np.float32)                 # band2 = Sigma0_VV (band1 VH, band3 LIA)
        a[a <= 0] = np.nan
        dst = np.full((H, W), np.nan, np.float32)
        reproject(a, dst, src_transform=s.transform, src_crs=s.crs, src_nodata=np.nan,
                  dst_transform=TR, dst_crs=CRS, dst_nodata=np.nan, resampling=Resampling.average)
    s1_dates.append(pd.Timestamp(re.search(r"1SDV_(\d{8})", f).group(1))); vv.append(10 * np.log10(dst))
order = np.argsort(s1_dates); s1_dates = pd.DatetimeIndex(np.array(s1_dates)[order]); VV = np.stack(vv)[order]
T = len(s1_dates); print("S1 dates", T, s1_dates[0].date(), s1_dates[-1].date())

# ---------------- NDVI → S1 날짜 ----------------
def interp_ndvi(t):
    tt = (s2_dates - t).days.values
    nd = np.full((H, W), np.nan, np.float32)
    before = np.where(tt <= 0)[0]; after = np.where(tt >= 0)[0]
    # 픽셀별: 가장 가까운 앞/뒤 유효 관측
    prev_v = np.full((H, W), np.nan); prev_d = np.full((H, W), np.nan)
    for k in before:                                       # 시간순 → 마지막 유효값이 남음
        m = np.isfinite(s2[k]); prev_v[m] = s2[k][m]; prev_d[m] = -tt[k]
    next_v = np.full((H, W), np.nan); next_d = np.full((H, W), np.nan)
    for k in after[::-1]:
        m = np.isfinite(s2[k]); next_v[m] = s2[k][m]; next_d[m] = tt[k]
    both = np.isfinite(prev_v) & np.isfinite(next_v) & (prev_d + next_d <= 45)
    w = np.where(prev_d + next_d > 0, prev_d / np.maximum(prev_d + next_d, 1e-9), 0)
    nd[both] = (prev_v + w * (next_v - prev_v))[both]
    near = ~both & np.isfinite(prev_v) & (prev_d <= 10); nd[near] = prev_v[near]
    near = ~both & np.isnan(nd) & np.isfinite(next_v) & (next_d <= 10); nd[near] = next_v[near]
    return nd
ND = np.stack([interp_ndvi(t) for t in s1_dates])
valid = np.isfinite(VV) & np.isfinite(ND) & (ND >= 0.1) & (ND <= 0.8) & (VV >= -15)
print("valid fraction per date (median)", np.median(valid.mean((1, 2))).round(3))

def envelope_fit(x, y, label):
    """NDVI 0.02 구간별 상위1% 제외 최댓값(99백분위) → 선형회귀 (논문 Fig.4, Fig.7)"""
    bins = np.arange(0.1, 0.801, 0.02); cx, cy, n = [], [], []
    for lo in bins[:-1]:
        m = (x >= lo) & (x < lo + 0.02)
        if m.sum() >= 50:
            cx.append(lo + 0.01); cy.append(np.percentile(y[m], 99)); n.append(int(m.sum()))
    slope, icpt = np.polyfit(cx, cy, 1)
    print(f"{label}: {slope:.3f}·NDVI + {icpt:.3f}  ({len(cx)} bins)")
    return slope, icpt, dict(ndvi=cx, env=cy, n=n)

# ---------------- 방법 1 ----------------
cls = np.floor(ND * 10).astype(np.int16)                    # 1..7 (0.1 간격 등급), 8 = 0.8 정확히
cls[~valid] = -1
DSIG = np.full_like(VV, np.nan)
NCLS = np.zeros_like(VV, dtype=np.int16)
for k in range(1, 9):
    mk = cls == k
    vk = np.where(mk, VV, np.nan)
    with np.errstate(all="ignore"):
        dry = np.nanmin(vk, 0)
    DSIG[mk] = (VV - dry[None])[mk]
    NCLS[mk] = np.broadcast_to(mk.sum(0)[None], mk.shape)[mk]
a1, b1, env1 = envelope_fit(ND[valid], DSIG[valid], "f(NDVI) Δσmax")
f_nd = a1 * ND + b1
MV1 = np.clip(DSIG / f_nd * (MVMAX - MVMIN) + MVMIN, MVMIN, MVMAX)
MV1[~valid] = np.nan

# ---------------- 방법 2 ----------------
DS = VV[1:] - VV[:-1]; NDm = (ND[1:] + ND[:-1]) / 2
pv = valid[1:] & valid[:-1]
a2, b2, env2 = envelope_fit(NDm[pv], np.abs(DS[pv]), "g(NDVI) δσmax")
g_nd = a2 * NDm + b2

# 관측소 셀
from pyproj import Transformer
xs, ys = Transformer.from_crs(4326, CRS, always_xy=True).transform(LON, LAT)
r0, c0 = rasterio.transform.rowcol(TR, xs, ys)
insitu = pd.read_csv(f"{DATA}/{C['insitu']}", parse_dates=["date"]).set_index("date")
insitu.loc[insitu.sm_vol <= 0, "sm_vol"] = np.nan                  # QC: 음수(센서 오류) 제외

def run_method2(start_idx, init_value):
    mv = np.full((T, H, W), np.nan, np.float32)
    mv[start_idx] = init_value
    for t in range(start_idx, T - 1):
        dmv = np.where(pv[t], DS[t] / g_nd[t] * DMVMAX, 0.0)
        mv[t + 1] = np.clip(mv[t] + dmv, 0.02, 0.50)
    return mv
t0 = 0
MV2 = run_method2(t0, insitu.sm_vol.get(s1_dates[t0]))
MV2_masked = np.where(valid, MV2, np.nan)

# ---------------- 저장 ----------------
prof = dict(driver="GTiff", height=H, width=W, count=1, dtype="float32", crs=CRS, transform=TR, nodata=np.nan, compress="deflate")
for t, d in enumerate(s1_dates):
    for name, arr in (("method1", MV1[t]), ("method2", MV2_masked[t])):
        with rasterio.open(f"{OUT}/maps_{name}/{SITE}_SM_{name}_{d:%Y%m%d}.tif", "w", **prof) as o:
            o.write(arr.astype(np.float32), 1); o.set_band_description(1, f"surface soil moisture m3/m3, Gao2017 {name}")
np.savez_compressed(f"{OUT}/gao2017_stack_100m.npz", dates=s1_dates.strftime("%Y-%m-%d").values, VV=VV, NDVI=ND, valid=valid,
                    MV1=MV1, MV2=MV2_masked, x0=float(z["x0"]), y1=float(z["y1"]), res=RES, epsg=int(z["epsg"]))

ts = pd.DataFrame(dict(date=s1_dates, VV_dB=VV[:, r0, c0], NDVI=ND[:, r0, c0], valid=valid[:, r0, c0],
                       ndvi_class_n_dates=NCLS[:, r0, c0], dsigma=DSIG[:, r0, c0],
                       SM_method1=MV1[:, r0, c0], SM_method2=MV2[:, r0, c0],
                       SM_method1_3x3=np.nanmean(MV1[:, r0 - 1:r0 + 2, c0 - 1:c0 + 2], (1, 2)),
                       map_mean_method1=np.nanmean(MV1, (1, 2)), map_valid_frac=valid.mean((1, 2))))
ts = ts.merge(insitu.reset_index()[["date", "sm_vol", "rain_mm"]], on="date", how="left")
ts.to_csv(f"{OUT}/{SITE}_station_timeseries_gao2017.csv", index=False)
json.dump(dict(f=dict(a=a1, dsig_max_bare=b1, **env1), g=dict(b=a2, dsig_max_bare=b2, **env2),
               station_cell=[int(r0), int(c0)], start_date=str(s1_dates[t0].date()),
               params=dict(Mvmax=MVMAX, Mvmin=MVMIN, dMvmax=DMVMAX)),
          open(f"{OUT}/gao2017_fitted_params.json", "w"), indent=1, default=float)
print(ts.round(3).to_string())
