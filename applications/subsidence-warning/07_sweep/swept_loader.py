# -*- coding: utf-8 -*-
"""스윕 산출 SBAS csv를 평가용 bank 구조로 로드. loaders 내부(파싱·_deunwrap) 재사용, loaders 미편집.
주의: loaders 의 npz 캐시(out/_cache/sbas_<region>.npz)는 base SBAS 전용 → 절대 건드리지 않는다."""
import os as _os
_CR = _os.environ.get("CLAB_ROOT") or _os.path.abspath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "..", ".."))   # 전달본 상대경로

import os
os.environ.pop("PYTHONPATH", None)
import sys
SINK = _CR + "/analysis/sinkhole"
for p in (SINK, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
import loaders
import subsidence_list_analysis as M     # _join_alpha 재사용
from make_unified_map import AOI_SNWE

CLAB = _CR + ""


def load_sbas_from_csv(csv_path, region):
    """loaders.load_sbas(159-181)의 파싱부 복제(npz 캐시 미사용) + _postload(_deunwrap)."""
    df = pd.read_csv(csv_path)
    dcols = loaders._dcol_names(df.columns)
    lon = df["Longitude"].to_numpy(float); lat = df["Latitude"].to_numpy(float)
    vel = df["velocity"].to_numpy(float)
    tcoh = df["tcoh"].to_numpy(float) if "tcoh" in df else np.full(len(df), np.nan)
    disp = df[dcols].to_numpy(np.float32)
    x, y = loaders._TR_M.transform(lon, lat)
    out = {"lon": lon, "lat": lat, "x": np.array(x), "y": np.array(y),
           "vel": vel, "tcoh": tcoh, "disp": disp,
           "years": loaders.dcols_to_years(dcols), "dates": dcols}
    return loaders._postload(out, region, "sbas")   # 언랩억제(_deunwrap); CMC는 7지역 미대상 no-op


def _geo_integrated(region):
    f = f"{CLAB}/analysis/sinkhole/out/geo_integrated_{region}.csv"
    if os.path.exists(f):
        return pd.read_csv(f, encoding="utf-8-sig")
    return pd.DataFrame(columns=["kind", "lon", "lat", "final_alpha"])   # 송도DSC 등 → α=1.0


def build_bank_entry(region, sbas_csv, use_ps=True):
    """PS(base 고정) + swept SBAS 를 AOI 박스로 클립해 bank entry 구성(load_region_bank 미러)."""
    ps = loaders.load_ps(region) if use_ps else None
    sb = load_sbas_from_csv(sbas_csv, region)
    gi = _geo_integrated(region)
    box = AOI_SNWE.get(region) or AOI_SNWE["Incheon_Songdo"]   # DSC 등 별칭 → 동일 AOI 박스
    entry = {"kinds": {}, "box": box}
    kinds = (("PS", ps), ("SBAS", sb)) if use_ps else (("SBAS", sb),)
    yrs_all = []
    for kind, dat in kinds:
        if dat is None:
            continue
        g = gi[gi["kind"] == kind] if len(gi) else gi
        alpha = M._join_alpha(dat, g)
        lon, lat, x, y = dat["lon"], dat["lat"], dat["x"], dat["y"]
        vel, disp = dat["vel"], dat["disp"]
        S, N, W, E = box
        m = (lat >= S) & (lat <= N) & (lon >= W) & (lon <= E)
        lon, lat, x, y, vel, disp, alpha = lon[m], lat[m], x[m], y[m], vel[m], disp[m], alpha[m]
        entry["kinds"][kind] = {"lon": lon, "lat": lat, "x": x, "y": y, "vel": vel, "disp": disp,
                                "years": dat["years"], "alpha": alpha,
                                "tree": cKDTree(np.c_[x, y]) if len(x) else None}
        yrs_all.append(dat["years"])
    if not use_ps:   # PS 없이 SBAS만: 빈 PS 자리 채움(feat 호환)
        entry["kinds"].setdefault("PS", {"lon": np.array([]), "lat": np.array([]), "x": np.array([]),
                                         "y": np.array([]), "vel": np.array([]),
                                         "disp": np.zeros((0, len(sb["years"])), np.float32),
                                         "years": sb["years"], "alpha": np.array([]), "tree": None})
    ys = np.concatenate(yrs_all)
    entry["y0"], entry["y1"] = float(ys.min()), float(ys.max())
    return entry
