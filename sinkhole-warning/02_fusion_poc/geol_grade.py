# -*- coding: utf-8 -*-
"""
지질 기반 지반등급 산정 + 시추공 등급과 융합 (시추공 공백 보완).
 STEP1 수치지질도 Litho(암상) 점-in-폴리곤 → 3단계 등급/α, Fault 버퍼→단층인접, 카르스트 플래그
 STEP2 시추공>지질 우선 융합(공백거리 초과만 지질로 채움), source/confidence 태그
 STEP3 통합 α를 변위3지표 파이프라인에 투입 → 공백지 위험판정
⚠️ 임계치·매핑 잠정(config.GEO_CONFIG). 지질 기반은 간접추정(confidence=medium).
"""
import os
os.environ.pop("PYTHONPATH", None)
import numpy as np, pandas as pd, geopandas as gpd
import pyproj
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir(); os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]
from scipy.spatial import cKDTree
from shapely.ops import unary_union

from config import CONFIG, GEO_CONFIG as G
import loaders, indicators as ind

GEO_DIR = G["shp_dir"]
OUTC = CONFIG["paths"]["out_dir"]
# 하이브리드(2026-07-09): 1:5만 도폭 보유 3개 AOI는 5만 유지(고해상), 미보유 4개만 전국 1:25만.
REGION_SHEET = {
    "Yangyang": "HH20", "Seoul_Seodaemun": "FG33", "Incheon_Songdo": "FG22",   # 5만 도폭 보유
    "Seoul_Gangdong": "250K", "Gyeonggi_Gwangmyeong": "250K",                  # 5만 미보유 → 전국 25만
    "Busan_Mandeok_Centum": "250K", "Busan_Sasang_Hadan": "250K",
}
SCALE_LABEL = {"HH20": "1:5만", "FG33": "1:5만", "FG22": "1:5만", "250K": "1:25만"}
_MCRS = CONFIG["crs_metric"]
_O = {"정상": 0, "주의": 1, "위험": 2}
_LITH_CACHE = None   # 전국 Litho 1회 로드 캐시


def _load_nationwide():
    """전국 25만 Litho 1회 로드(UTF-8) → LITHONAME/AGE 정규화·WGS84."""
    global _LITH_CACHE
    if _LITH_CACHE is None:
        g = gpd.read_file(G["nationwide_shp"], encoding="utf-8")
        ren = {}
        if "lithoname" in g.columns: ren["lithoname"] = "LITHONAME"
        if "age" in g.columns: ren["age"] = "AGE"
        g = g.rename(columns=ren)
        if "LITHONAME" not in g.columns:
            raise KeyError("전국 지질도에 lithoname/LITHONAME 컬럼 없음")
        if "AGE" not in g.columns:
            g["AGE"] = ""
        if g.crs is None:
            g.set_crs(epsg=4326, inplace=True)
        g = g.to_crs(epsg=4326)
        _LITH_CACHE = g[["LITHONAME", "AGE", "geometry"]].copy()
    return _LITH_CACHE


def _read_shp(path):
    """수치지질도 SHP 자동 인코딩(UTF-8/CP949) 읽기(5만 도폭용)."""
    for enc in ("utf-8", "cp949"):
        g = gpd.read_file(path, encoding=enc)
        sc = [c for c in ("LITHONAME", "TYPE") if c in g.columns]
        if not sc:
            return g
        v = str(g[sc[0]].dropna().iloc[0]) if g[sc[0]].notna().any() else ""
        if any("가" <= ch <= "힣" for ch in v) or not v:
            return g
    return g


def read_geology(code=None):
    """하이브리드: code=='250K'면 전국 25만, 그 외(도폭코드)는 해당 5만 도폭 Litho. fault 미사용→None."""
    if code is None or code == "250K":
        return _load_nationwide(), None
    lith = _read_shp(f"{GEO_DIR}/{code}/{code}_Geology_50K_Litho.shp")
    if lith.crs is None:
        lith.set_crs(epsg=4326, inplace=True)
    lith = lith.to_crs(epsg=4326)
    return lith, None


def classify_litho(name):
    """암상명 → (등급, 카르스트플래그). soft>watch>good, 없으면 미분류."""
    if not isinstance(name, str) or not name or name == "nan":
        return "미분류", False
    karst = any(k in name for k in G["karst_kw"])
    for kw in G["lith_soft"]:
        if kw in name:
            return "연약", karst
    for kw in G["lith_watch"]:
        if kw in name:
            return "주의", karst
    for kw in G["lith_good"]:
        if kw in name:
            return "양호", karst
    return "미분류", karst


def geology_grade(lon, lat, code=None):
    """점(lon/lat)들에 지질 기반 등급/α/플래그 부여. 반환 DataFrame."""
    lith, fault = read_geology(code)
    # 전국판(대용량)만 판정점 bbox로 클립(sjoin 성능). 5만 도폭(소규모)은 그대로.
    if len(lith) > 500:
        from shapely.geometry import box
        pad = 0.05
        bb = box(float(np.min(lon)) - pad, float(np.min(lat)) - pad,
                 float(np.max(lon)) + pad, float(np.max(lat)) + pad)
        lith = gpd.clip(lith, bb)
    pts = gpd.GeoDataFrame({"i": np.arange(len(lon))},
                           geometry=gpd.points_from_xy(lon, lat), crs="EPSG:4326")
    # 점-in-폴리곤 (LITHONAME)
    j = gpd.sjoin(pts, lith[["LITHONAME", "AGE", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")].sort_index()
    lithoname = j["LITHONAME"].values
    grades = []; karst = []
    for nm in lithoname:
        gr, ka = classify_litho(nm); grades.append(gr); karst.append(ka)
    grades = np.array(grades, dtype=object); karst = np.array(karst)
    # 단층 인접 (미터 거리) — use_fault=True일 때만
    fault_flag = np.zeros(len(lon), bool)
    if G.get("use_fault", False) and fault is not None and len(fault):
        pm = pts.to_crs(epsg=_MCRS)
        fu = unary_union(fault.to_crs(epsg=_MCRS).geometry.values)
        dist = pm.geometry.distance(fu).values
        fault_flag = dist <= G["fault_buffer_m"]
        up = fault_flag & np.isin(grades, ["양호", "주의"])   # 단층 인접 → 연약 상향
        grades = np.where(up, "연약", grades)
    alpha = np.array([G["grade_alpha"].get(g, np.nan) for g in grades])
    return pd.DataFrame({
        "lon": lon, "lat": lat, "LITHONAME": lithoname, "AGE": j["AGE"].values,
        "geo_grade": grades, "geo_alpha": alpha, "karst": karst, "fault_adj": fault_flag,
    })


def run_region(region, save=True):
    if region not in REGION_SHEET:
        print(f"⚠️ {region}: 커버 도폭 없음 — 추가 수치지질도 필요."); return None
    code = REGION_SHEET[region]
    # 판정점 = PS+SBAS
    ps = loaders.load_ps(region); sb = loaders.load_sbas(region)
    lon = np.r_[ps["lon"], sb["lon"]]; lat = np.r_[ps["lat"], sb["lat"]]
    kind = np.r_[np.full(len(ps["lon"]), "PS"), np.full(len(sb["lon"]), "SBAS")]

    # 최근접 시추공 거리(m) → 공백 판정
    b = pd.read_csv(os.path.join(OUTC, "step1_borehole_grade.csv"), encoding="utf-8-sig")
    trm = pyproj.Transformer.from_crs(4326, _MCRS, always_xy=True)
    bx, by = b["x_m"].values, b["y_m"].values
    bt = cKDTree(np.column_stack([bx, by]))
    px, py = trm.transform(lon, lat)
    bdist, bi = bt.query(np.column_stack([px, py]), k=1)
    bore_alpha = b["alpha"].values[bi]; bore_grade = b["등급"].values[bi]
    gap = bdist > G["gap_dist_m"]

    # 지질 기반 등급
    geo = geology_grade(lon, lat, code)

    # 융합: 시추공(≤gap) 우선, 공백만 지질
    src = np.where(gap, "geology", "borehole")
    # 시추공 등급코드(연약/주의/양호) vs 지질 등급코드 — α만 융합에 사용
    final_alpha = np.where(gap, geo["geo_alpha"].values, bore_alpha)
    final_grade_g = np.where(gap, geo["geo_grade"].values, bore_grade)  # 지반등급(연약/주의/양호)
    conf = np.where(gap, G["confidence"]["geology"], G["confidence"]["borehole"])
    # 공백인데 지질도 미분류/무지질이면 채움 실패
    nofill = gap & (~np.isin(geo["geo_grade"].values, ["연약", "주의", "양호"]))
    final_grade_g = np.where(nofill, "미상", final_grade_g)
    conf = np.where(nofill, "none", conf)

    out = pd.DataFrame({
        "region": region, "kind": kind, "lon": np.round(lon, 6), "lat": np.round(lat, 6),
        "bore_dist_m": np.round(bdist, 1), "gap": gap,
        "LITHONAME": geo["LITHONAME"].values, "geo_grade": geo["geo_grade"].values,
        "geo_alpha": geo["geo_alpha"].values, "karst": geo["karst"].values, "fault_adj": geo["fault_adj"].values,
        "bore_grade": bore_grade, "bore_alpha": np.round(bore_alpha, 2),
        "source": src, "final_ground_grade": final_grade_g,
        "final_alpha": np.round(final_alpha.astype(float), 2), "confidence": conf,
    })
    if save:
        fp = os.path.join(OUTC, f"geo_integrated_{region}.csv")
        out.to_csv(fp, index=False, encoding="utf-8-sig")

    # ---- 요약 ----
    n = len(out)
    print("=" * 68); print(f"지질 기반 지반등급 융합 — {region} (도폭 {code})"); print("=" * 68)
    print(f"판정점 {n:,} (PS {int((kind=='PS').sum()):,} + SBAS {int((kind=='SBAS').sum()):,})")
    print(f"\n[공백 판정] gap_dist={G['gap_dist_m']:.0f}m 초과 = 시추공 공백")
    print(f"  시추공 근접(borehole): {int((~gap).sum()):,} ({(~gap).mean()*100:.1f}%)")
    print(f"  시추공 공백(geology):  {int(gap.sum()):,} ({gap.mean()*100:.1f}%)")
    print(f"\n[지질 기반 등급 분포 — 공백점 {int(gap.sum()):,}건]")
    gg = out[out.gap]["final_ground_grade"].value_counts()
    for k in ["연약", "주의", "양호", "미상"]:
        if k in gg: print(f"  {k}: {int(gg[k]):,} ({gg[k]/gap.sum()*100:.1f}%)")
    print(f"  카르스트 플래그: {int(out[out.gap]['karst'].sum()):,} · 단층인접: {int(out[out.gap]['fault_adj'].sum()):,}")
    print(f"\n[암상별 공백점 분포 상위]")
    print(out[out.gap]["LITHONAME"].value_counts().head(8).to_string())
    print(f"\n[융합 커버리지]")
    print(f"  borehole {int((~gap).sum()):,} (high) + geology {int((gap & ~nofill).sum()):,} (medium) "
          f"+ 미상 {int(nofill.sum()):,} (none)")
    filled = (gap & ~nofill).sum()
    print(f"  → 시추공만이면 공백 {int(gap.sum()):,}건 미판정, 지질로 {int(filled):,}건 메움({filled/max(1,gap.sum())*100:.1f}%)")
    if save:
        print(f"\n저장: {fp}")
    return out


if __name__ == "__main__":
    import sys
    reg = sys.argv[1] if len(sys.argv) > 1 else "Yangyang"
    run_region(reg)
