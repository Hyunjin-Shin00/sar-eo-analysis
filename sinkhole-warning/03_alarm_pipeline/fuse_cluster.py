# -*- coding: utf-8 -*-
"""(4) 융합 스코어링 & DBSCAN 클러스터 알람.
지점 = PS+SBAS. 각 점: InSAR 3지표 위험등급(α 반영) + 역속도 가속(A') [+ 지하수 방아쇠(B)].
상위등급(주의+)·침하 점을 DBSCAN(UTM52N)으로 '현장 단위' 클러스터화 → 관심/주의/경보 알람.
asof_year로 시점 고정(백테스팅 시 사고 이전 상태 재현). ⚠️ 임계치 잠정(pcfg)."""
import os; os.environ.pop("PYTHONPATH", None)
import numpy as np, pandas as pd
import pyproj
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir(); os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]
from scipy.spatial import cKDTree
from sklearn.cluster import DBSCAN

from pcfg import PATHS, RISK, ALARM, CONFIG
import loaders, indicators as ind
from invvel import inverse_velocity

_TR_M = pyproj.Transformer.from_crs(4326, CONFIG["crs_metric"], always_xy=True)
_SCORE = RISK["grade_score"]
_geo_cache = {}


def _alpha_for(region, lon, lat):
    """geo_integrated_{region}.csv 최근접점 final_alpha(지반 취약계수). 없으면 1.0(양호)."""
    if region not in _geo_cache:
        fp = os.path.join(PATHS["geo_integrated_dir"], f"geo_integrated_{region}.csv")
        g = pd.read_csv(fp, encoding="utf-8-sig")
        a = pd.to_numeric(g["final_alpha"], errors="coerce").to_numpy()
        _geo_cache[region] = (cKDTree(np.column_stack([g["lon"].to_numpy(), g["lat"].to_numpy()])), a)
    tree, a = _geo_cache[region]
    _, idx = tree.query(np.column_stack([lon, lat]), k=1)
    al = a[idx]
    al[~np.isfinite(al)] = 1.0
    return al


def _point_grades(d, alpha, asof_year):
    """한 데이터셋(PS 또는 SBAS)의 점별 최종 위험등급 + 근거."""
    rv = ind.risk_velocity(d["vel"])
    rc = ind.risk_cumulative(d["disp"], d["years"], asof_year)
    tr = ind.trend_grade(d["disp"], d["years"], asof_year)
    gv = ind.grade_velocity(rv, alpha); gc = ind.grade_cumulative(rc, alpha); gt = tr["grade"]
    grade = ind.combine_max(gv, gc, gt)
    grade = ind.subsidence_gate(grade, d["vel"])     # 침하(vel<0)만 상위등급 유지
    basis = ind.which_indicator(gv, gc, gt)
    return grade, rv, rc, basis


def build_points(region, asof_year=None):
    """PS+SBAS 통합 점 테이블(위험등급·점수·역속도) 반환."""
    frames = []
    for kind, load in (("PS", loaders.load_ps), ("SBAS", loaders.load_sbas)):
        d = load(region)
        n = len(d["vel"])
        if n == 0:
            continue
        alpha = _alpha_for(region, d["lon"], d["lat"])
        grade, rv, rc, basis = _point_grades(d, alpha, asof_year)
        iv = inverse_velocity(d["disp"], d["years"], asof_year)
        score = np.array([_SCORE.get(g, 0) for g in grade], int)
        score = np.clip(score + RISK["invvel_boost"] * iv["accel"].astype(int), 0, 2)
        x, y = _TR_M.transform(d["lon"], d["lat"])
        frames.append(pd.DataFrame({
            "region": region, "kind": kind, "lon": d["lon"], "lat": d["lat"],
            "x_m": x, "y_m": y, "vel": d["vel"], "alpha": np.round(alpha, 2),
            "risk_vel": np.round(rv, 2), "risk_cum": np.round(rc, 2),
            "grade": grade, "basis": basis, "score": score,
            "invvel_accel": iv["accel"], "tf_year": np.round(iv["tf_year"], 3),
            "lead_days": np.round(iv["lead_days"], 0),
        }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def cluster_alarms(region, asof_year=None, pts=None):
    """상위등급·침하 점을 DBSCAN 클러스터 → 클러스터별 알람 레코드 DataFrame."""
    if pts is None:
        pts = build_points(region, asof_year)
    if pts.empty:
        return pts, pd.DataFrame(), pd.DataFrame()
    elev = pts[(pts["score"] >= 1) & (pts["vel"] < 0)].copy()   # 주의+ 이면서 침하
    if len(elev) < ALARM["min_samples"]:
        return pts, pd.DataFrame(), elev
    xy = elev[["x_m", "y_m"]].to_numpy()
    lab = DBSCAN(eps=ALARM["eps_m"], min_samples=ALARM["min_samples"]).fit_predict(xy)
    elev["cluster"] = lab
    recs = []
    for cid, grp in elev.groupby("cluster"):
        if cid < 0:                                   # 노이즈(미클러스터)
            continue
        n_elev = len(grp)
        if n_elev < ALARM["min_cluster_elevated"]:
            continue
        maxscore = int(grp["score"].max())
        level = ALARM["level_by_score"][min(maxscore, 2)]
        has_iv = bool(grp["invvel_accel"].any())
        lead = grp.loc[grp["invvel_accel"], "lead_days"]
        recs.append({
            "region": region, "cluster": int(cid), "alarm": level,
            "n_points": n_elev, "n_danger": int((grp["score"] >= 2).sum()),
            "cx_lon": round(float(grp["lon"].mean()), 6), "cy_lat": round(float(grp["lat"].mean()), 6),
            "max_subsid_vel_mmyr": round(float(-grp["vel"].min()), 1),   # 최대 침하속도
            "invvel_accel": has_iv, "min_lead_days": (float(lead.min()) if len(lead) else np.nan),
            "kinds": "+".join(sorted(grp["kind"].unique())),
            "top_basis": grp["basis"].mode().iat[0] if not grp["basis"].mode().empty else "-",
        })
    clusters = pd.DataFrame(recs).sort_values(["alarm", "n_points"], ascending=[True, False]) \
        if recs else pd.DataFrame()
    # 백테스트용: min_cluster_elevated 통과한 클러스터 멤버만 라벨과 함께 반환
    keep = set(c["cluster"] for c in recs)
    elev_kept = elev[elev["cluster"].isin(keep)].copy() if keep else elev.iloc[0:0].copy()
    return pts, clusters, elev_kept


_ALARM_CACHE = {}


def cluster_alarms_cached(region, asof_year=None):
    """(clusters, elev)만 반환하는 캐시 버전(백테스트 반복 asof 가속). asof는 0.1년으로 양자화."""
    key = (region, round(asof_year, 1) if asof_year is not None else None)
    if key not in _ALARM_CACHE:
        _, cl, elev = cluster_alarms(region, key[1])
        _ALARM_CACHE[key] = (cl, elev)
    return _ALARM_CACHE[key]


if __name__ == "__main__":
    import sys
    reg = sys.argv[1] if len(sys.argv) > 1 else "Seoul_Gangdong"
    pts, cl, _ = cluster_alarms(reg, asof_year=None)
    print(f"=== {reg} === 점 {len(pts)} | 상위등급 {(pts['score']>=1).sum()} | 클러스터 알람 {len(cl)}")
    print("등급분포:", pts["grade"].value_counts().to_dict())
    if len(cl):
        print(cl.to_string(index=False))
