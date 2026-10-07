# -*- coding: utf-8 -*-
"""PS/SBAS 로더 + 캐시. 좌표 WGS84 -> UTM52N(m). 시계열 D컬럼 -> 누적변위 행렬."""
import os
os.environ.pop("PYTHONPATH", None)
import numpy as np
import pandas as pd
import fiona
import pyproj
from scipy.ndimage import median_filter
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir()
os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]
from pyproj import Transformer

from config import CONFIG, region_result_dir
try:
    from config import AOI_REF
except Exception:
    AOI_REF = {}

_TR_M = Transformer.from_crs(CONFIG["crs_wgs"], CONFIG["crs_metric"], always_xy=True)


def _deunwrap(out, kind):
    """언래핑 오류 억제(disp 시계열): 국소 시간중앙값(win) 대비 잔차가 λ/2(27.73mm)의 정수배(±tol)
    이고 국소 강건척도(1.4826·MAD)의 outlier_k배를 초과하는 '진짜 점프'만 정수배만큼 되돌림.
    노이즈 과대검출을 피하려 국소중앙값+MAD 게이트 사용. vel은 유지(StaMPS 강건추정)."""
    u = CONFIG.get("unwrap", {})
    if not u.get("enable", False) or kind not in u.get("apply_to", []):
        return out
    disp = out["disp"].astype(float)
    N, T = disp.shape
    if T < 3 or N == 0:
        return out
    cyc = float(u["cycle_mm"]); tol = float(u["tol_mm"])
    maxn = int(u["max_n"]); win = int(u["win"])
    ok_k = float(u.get("outlier_k", 4.0)); fl = float(u.get("scale_floor_mm", 2.0))
    finite = np.isfinite(disp)
    rowmed = np.nanmedian(np.where(finite, disp, np.nan), axis=1, keepdims=True)
    rowmed = np.where(np.isfinite(rowmed), rowmed, 0.0)
    filled = np.where(finite, disp, rowmed)
    base = median_filter(filled, size=(1, win), mode="nearest")   # 국소 시간중앙값
    resid = disp - base
    absr = np.abs(resid)
    mad = np.nanmedian(np.where(finite, absr, np.nan), axis=1, keepdims=True)
    scale = np.clip(1.4826 * np.where(np.isfinite(mad), mad, fl), fl, None)
    n = np.round(np.where(finite, resid / cyc, 0.0))
    mask = (finite & (n != 0) & (np.abs(n) <= maxn)
            & (np.abs(resid - n * cyc) <= tol) & (absr > ok_k * scale))
    if mask.any():
        disp = np.where(mask, disp - n * cyc, disp)
    out["disp"] = disp.astype(np.float32)
    out["_deunwrap_n"] = int(mask.sum())
    return out


def _cmc_sbas(out, region):
    """공통모드 보정(CMC): 명시 지역만 전점 중앙값 시계열·중앙값 속도를 차감(광역 공통추세 제거)."""
    c = CONFIG.get("cmc", {})
    if not c.get("enable", False) or region not in c.get("sbas_regions", []):
        out["cmc"] = None
        return out
    disp = out["disp"].astype(float)
    cm = np.nanmedian(disp, axis=0)                 # 에폭별 전점 중앙값 = 공통모드 시계열
    if np.isnan(cm).any():
        ok = np.isfinite(cm); idx = np.arange(len(cm))
        cm = np.interp(idx, idx[ok], cm[ok]) if ok.sum() >= 2 else np.nan_to_num(cm)
    out["disp"] = (disp - cm[None, :]).astype(np.float32)
    v_cm = float(np.nanmedian(out["vel"]))
    out["vel"] = out["vel"] - v_cm
    out["cmc"] = {"v_cm": round(v_cm, 3), "cm_last": round(float(cm[-1]), 2),
                  "cm_max": round(float(np.nanmax(cm)), 2)}
    return out


def _postload(out, region, kind):
    """공통 후처리: 언래핑 억제 → (PS)사용자 기준점 재기준화 / (SBAS)공통모드 보정."""
    out = _deunwrap(out, kind)
    if kind == "ps":
        return _reref_ps(out, region)
    return _cmc_sbas(out, region)


def _reref_ps(out, region):
    """PS를 사용자 기준점(AOI_REF)으로 재기준화: 반경 내 PS 평균 시계열·속도를 전체에서 차감.
    output_final(자동ref) − 사용자기준점 = raw − 사용자기준점 (순수차감, 검증됨). SBAS는 미적용."""
    if not CONFIG.get("ps_reref", False) or region not in AOI_REF:
        out["reref"] = None
        return out
    rlat, rlon = AOI_REF[region]
    rx, ry = _TR_M.transform(rlon, rlat)
    d = np.hypot(out["x"] - rx, out["y"] - ry)
    mode = CONFIG.get("ps_reref_mode", "nearest")
    if mode == "nearest":                      # 사용자 선정 최근접 단일 PS
        k = int(np.argmin(d)); n_used = 1
        ref_ts = out["disp"][k].astype(float)
        ref_v = float(out["vel"][k])
    else:                                      # 반경 평균
        R = CONFIG.get("ps_reref_radius_m", 150.0)
        m = d <= R
        if int(m.sum()) == 0:
            m = np.zeros(len(d), bool); m[int(np.argmin(d))] = True
        ref_ts = np.nanmean(out["disp"][m], axis=0); ref_v = float(np.nanmean(out["vel"][m])); n_used = int(m.sum())
    # 단일점 결측 에폭 보간(전체에 NaN 전파 방지)
    if np.isnan(ref_ts).any():
        ok = np.isfinite(ref_ts); idx = np.arange(len(ref_ts))
        ref_ts = np.interp(idx, idx[ok], ref_ts[ok]) if ok.sum() >= 2 else np.nan_to_num(ref_ts)
    out["disp"] = (out["disp"] - ref_ts[None, :]).astype(np.float32)
    out["vel"] = out["vel"] - ref_v
    out["reref"] = {"lat": rlat, "lon": rlon, "mode": mode, "n": n_used,
                    "ref_v": round(ref_v, 3), "dist_nearest_m": round(float(d.min()), 1)}
    return out


def dcols_to_years(dcols):
    """['D20190109',...] -> np.array(decimal years)."""
    ys = []
    for c in dcols:
        s = c[1:]
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
        doy = (pd.Timestamp(y, m, d) - pd.Timestamp(y, 1, 1)).days
        ys.append(y + doy / 365.25)
    return np.array(ys, float)


def _dcol_names(cols):
    return [c for c in cols if c.startswith("D") and c[1:].isdigit() and len(c) == 9]


def load_ps(region, use_cache=True):
    """PS output_final.shp -> dict(lon,lat,x,y,vel,disp[N,T],years[T],dates)."""
    cache = os.path.join(CONFIG["paths"]["cache_dir"], f"ps_{region}.npz")
    if use_cache and os.path.exists(cache):
        z = np.load(cache, allow_pickle=True)
        d = {k: z[k] for k in z.files}
        d["dates"] = list(z["dates"])
        return _postload(d, region, "ps")    # 언래핑 억제 + 사용자 기준점 재기준화(캐시는 원본 유지)
    shp = f"{region_result_dir(region, 'psinsar')}/output_final.shp"
    props = list(fiona.open(shp).schema["properties"].keys())
    dcols = _dcol_names(props)
    lon, lat, vel = [], [], []
    disp = []
    with fiona.open(shp) as src:
        for f in src:
            p = f["properties"]; c = f["geometry"]["coordinates"]
            lon.append(c[0]); lat.append(c[1]); vel.append(p["velocity"])
            disp.append([p[d] for d in dcols])
    lon = np.array(lon); lat = np.array(lat); vel = np.array(vel, float)
    disp = np.array(disp, np.float32)
    x, y = _TR_M.transform(lon, lat)
    out = {"lon": lon, "lat": lat, "x": np.array(x), "y": np.array(y),
           "vel": vel, "disp": disp, "years": dcols_to_years(dcols), "dates": dcols}
    if use_cache:
        os.makedirs(CONFIG["paths"]["cache_dir"], exist_ok=True)
        np.savez(cache, **{k: v for k, v in out.items() if k != "dates"},
                            dates=np.array(dcols))
    return _postload(out, region, "ps")      # 언래핑 억제 + 사용자 기준점 재기준화


def load_sbas(region, use_cache=True):
    """SBAS {R}_sbas_ps_v.csv -> dict(lon,lat,x,y,vel,tcoh,disp[N,T],years,dates)."""
    cache = os.path.join(CONFIG["paths"]["cache_dir"], f"sbas_{region}.npz")
    if use_cache and os.path.exists(cache):
        z = np.load(cache, allow_pickle=True)
        d = {k: z[k] for k in z.files}
        d["dates"] = list(z["dates"])
        return _postload(d, region, "sbas")   # 언래핑 억제 + (해당 지역)공통모드 보정
    csv = f"{region_result_dir(region, 'sbas')}/{region}_sbas_ps_v.csv"
    df = pd.read_csv(csv)
    dcols = _dcol_names(df.columns)
    lon = df["Longitude"].to_numpy(float); lat = df["Latitude"].to_numpy(float)
    vel = df["velocity"].to_numpy(float)
    tcoh = df["tcoh"].to_numpy(float) if "tcoh" in df else np.full(len(df), np.nan)
    disp = df[dcols].to_numpy(np.float32)
    x, y = _TR_M.transform(lon, lat)
    out = {"lon": lon, "lat": lat, "x": np.array(x), "y": np.array(y),
           "vel": vel, "tcoh": tcoh, "disp": disp, "years": dcols_to_years(dcols), "dates": dcols}
    if use_cache:
        os.makedirs(CONFIG["paths"]["cache_dir"], exist_ok=True)
        np.savez(cache, **{k: v for k, v in out.items() if k != "dates"},
                            dates=np.array(dcols))
    return _postload(out, region, "sbas")     # 언래핑 억제 + (해당 지역)공통모드 보정


if __name__ == "__main__":
    # 검증: 한 지역 로드 + 부호규약/NaN 확인
    for R in ["Yangyang", "Seoul_Gangdong"]:
        ps = load_ps(R, use_cache=False); sb = load_sbas(R, use_cache=False)
        print(f"\n=== {R} ===")
        print(f"PS   n={len(ps['vel'])} T={ps['disp'].shape[1]} vel[min,med,max]="
              f"[{np.nanmin(ps['vel']):.1f},{np.nanmedian(ps['vel']):.1f},{np.nanmax(ps['vel']):.1f}] "
              f"NaN%={np.isnan(ps['disp']).mean()*100:.2f} 기간 {ps['years'][0]:.2f}-{ps['years'][-1]:.2f}")
        print(f"     누적변위 마지막열[min,med,max]=[{np.nanmin(ps['disp'][:,-1]):.1f},"
              f"{np.nanmedian(ps['disp'][:,-1]):.1f},{np.nanmax(ps['disp'][:,-1]):.1f}] (음수=침하?)")
        print(f"SBAS n={len(sb['vel'])} T={sb['disp'].shape[1]} vel[min,med,max]="
              f"[{np.nanmin(sb['vel']):.1f},{np.nanmedian(sb['vel']):.1f},{np.nanmax(sb['vel']):.1f}] "
              f"tcoh med={np.nanmedian(sb['tcoh']):.2f} NaN%={np.isnan(sb['disp']).mean()*100:.2f}")
