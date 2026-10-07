# -*- coding: utf-8 -*-
"""
STEP 1 — 지반등급 판정 (정적 지반조건)  [6·22 자료 p.5]
판정 단위: 지층(layer)별 연약 판정 → 시추공 단위 집계.

연약층 조건(한국도로공사 도로설계요령 2009 표1.6-1):
  · 점성토·이탄질: 대표N<=4 AND 대표심도<10m
  · 사질토:        대표N<=6 AND 대표심도>=10m
  · 암반/풍화계열(WR·RS·SR·MR·HR, 연암·경암·보통암층)은 판정 제외
  · 대표N = 지층 내 SPT N의 최솟값(보수적)

시추공 3등급 → α:
  연약(연약층>=1)=0.6 / 주의(연약층0 & 최저N<=10)=0.8 / 양호(최저N>10)=1.0

출력: out/step1_borehole_grade.csv
  (공번, lon, lat, x_m, y_m, 등급, alpha, 연약층수, 연약누적두께_m, 최저N, 프로젝트명)
⚠️ 임계치·α는 잠정값(config.py 참조).
"""
import os
os.environ.pop("PYTHONPATH", None)   # env_pyproj_broken.md 우회
import numpy as np
import pandas as pd
import pyproj
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir()
os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]
from pyproj import Transformer

from config import CONFIG


def _uscs_prefix(s):
    """USCS 코드 정규화: 'SM:실트질 모래' -> 'SM', 공백/소문자 처리."""
    if not isinstance(s, str):
        return ""
    t = s.strip().upper().replace("：", ":")
    t = t.split(":")[0].split()[0] if t else ""
    return t


def compute_spt_N(blow, pen):
    """관입깊이 30cm 기준 정규화 N. 관입불능(pen<30)=고타격→N↑(경질). 무효는 NaN."""
    c = CONFIG["spt"]
    blow = np.asarray(blow, float)
    pen = np.asarray(pen, float)
    N = np.full(blow.shape, np.nan)
    valid = (pen >= c["pen_min_cm"]) & (blow >= c["blow_min"]) & (blow <= c["blow_max"])
    # 정규화: N = blow * 30/pen  (pen=30이면 N=blow; refusal pen<30이면 N 증가)
    with np.errstate(divide="ignore", invalid="ignore"):
        Nn = blow * c["pen_full_cm"] / pen
    N[valid] = np.clip(Nn[valid], 0.0, c["N_cap"])
    return N


def classify_soil(uscs, civil):
    """지층 토질분류: 'cohesive' | 'sandy' | 'rock' | 'other'."""
    s = CONFIG["soft"]
    p = _uscs_prefix(uscs)
    if p in s["rock_exclude_uscs"] or (isinstance(civil, str) and civil.strip() in s["rock_exclude_civil"]):
        return "rock"
    if p in s["cohesive"]:
        return "cohesive"
    if p in s["sandy"]:
        return "sandy"
    return "other"


def judge_layer(soil, repN, depth, thick):
    """지층 연약 여부. (soil, 대표N, 대표심도, 두께) -> bool."""
    s = CONFIG["soft"]
    if soil == "rock" or soil == "other":
        return False
    if not np.isfinite(repN):
        return False
    if soil == "cohesive":
        return (repN <= s["cohesive_N"]) and (depth < s["cohesive_depth_max_m"])
    if soil == "sandy":
        return (repN <= s["sandy_N"]) and (depth >= s["sandy_depth_min_m"])
    return False


def run_step1(save=True):
    p = CONFIG["paths"]
    usecols = ["시추공코드", "프로젝트명", "X좌표", "Y좌표",
               "관입깊이", "타격회수", "지층시작심도", "지층종료심도", "지층두께",
               "토목용지층명", "학술용지층명USCS", "지층코드"]
    df = pd.read_csv(p["ground_csv"], usecols=usecols, encoding="utf-8-sig",
                     dtype={"시추공코드": str, "프로젝트명": str, "토목용지층명": str,
                            "학술용지층명USCS": str, "지층코드": str})
    n0 = len(df)

    # --- SPT N 산정 (행=SPT 단위) ---
    df["N"] = compute_spt_N(df["타격회수"].values, df["관입깊이"].values)

    # --- 지층 단위로 집계 (벡터화: C레벨 agg) ---
    # 지층 식별: (시추공코드, 지층코드). 지층코드 결측 시 (시작,종료)심도로 대체키
    df["_lyr"] = df["지층코드"].fillna(
        df["시추공코드"].astype(str) + "_" +
        df["지층시작심도"].round(2).astype(str) + "_" + df["지층종료심도"].round(2).astype(str))

    rep_agg = "min" if CONFIG["soft"]["rep_N_mode"] == "min" else "median"
    lyr = df.groupby("_lyr", sort=False).agg(
        시추공코드=("시추공코드", "first"), 프로젝트명=("프로젝트명", "first"),
        X좌표=("X좌표", "first"), Y좌표=("Y좌표", "first"),
        top=("지층시작심도", "min"), bot=("지층종료심도", "max"),
        thick_col=("지층두께", "first"),
        uscs=("학술용지층명USCS", "first"), civil=("토목용지층명", "first"),
        repN=("N", rep_agg),
    ).reset_index(drop=True)

    # 대표심도
    if CONFIG["soft"]["layer_depth_mode"] == "top":
        lyr["depth"] = lyr["top"]
    else:
        lyr["depth"] = (lyr["top"] + lyr["bot"]) / 2.0
    # 두께: 컬럼값 이상 시 (종료-시작) 대체
    cthick = lyr["bot"] - lyr["top"]
    bad = ~np.isfinite(lyr["thick_col"]) | (lyr["thick_col"] <= 0) | (lyr["thick_col"] > 200)
    lyr["thick"] = np.where(bad, np.where(np.isfinite(cthick) & (cthick > 0), cthick, np.nan),
                            lyr["thick_col"])
    # 토질분류(벡터화)
    s = CONFIG["soft"]
    pref = lyr["uscs"].map(_uscs_prefix)
    civ = lyr["civil"].fillna("").str.strip()
    lyr["soil"] = np.select(
        [pref.isin(s["rock_exclude_uscs"]) | civ.isin(s["rock_exclude_civil"]),
         pref.isin(s["cohesive"]), pref.isin(s["sandy"])],
        ["rock", "cohesive", "sandy"], default="other")
    # 연약 판정(벡터화)
    finN = np.isfinite(lyr["repN"])
    soft_c = (lyr["soil"] == "cohesive") & finN & (lyr["repN"] <= s["cohesive_N"]) & (lyr["depth"] < s["cohesive_depth_max_m"])
    soft_s = (lyr["soil"] == "sandy") & finN & (lyr["repN"] <= s["sandy_N"]) & (lyr["depth"] >= s["sandy_depth_min_m"])
    lyr["is_soft"] = soft_c | soft_s

    # --- 시추공 단위 집계 (벡터화) ---
    lyr["thick_soft"] = np.where(lyr["is_soft"], lyr["thick"], 0.0)
    lyr["is_soil"] = lyr["soil"].isin(["cohesive", "sandy"])
    lyr["repN_soil"] = np.where(lyr["is_soil"], lyr["repN"], np.nan)
    bore = lyr.groupby("시추공코드", sort=False).agg(
        프로젝트명=("프로젝트명", "first"), X좌표=("X좌표", "first"), Y좌표=("Y좌표", "first"),
        연약층수=("is_soft", "sum"),
        연약누적두께_m=("thick_soft", "sum"),
        최저N=("repN_soil", "min"),
    ).reset_index()
    bore["연약층수"] = bore["연약층수"].astype(int)

    # --- 등급 & α ---
    ga = CONFIG["grade_alpha"]; wN = CONFIG["grade_watch_N"]

    def _grade(row):
        if row["연약층수"] >= 1:
            return "연약"
        # 연약층 없음: 최저N 기준. 최저N 결측(토질층 없음=전부 암반) → 양호
        if np.isfinite(row["최저N"]) and row["최저N"] <= wN:
            return "주의"
        return "양호"

    bore["등급"] = bore.apply(_grade, axis=1)
    bore["alpha"] = bore["등급"].map(ga)

    # --- 좌표 변환 5186 -> WGS84 & UTM52N ---
    tr_wgs = Transformer.from_crs(CONFIG["crs_ground"], CONFIG["crs_wgs"], always_xy=True)
    tr_m = Transformer.from_crs(CONFIG["crs_ground"], CONFIG["crs_metric"], always_xy=True)
    lon, lat = tr_wgs.transform(bore["X좌표"].values, bore["Y좌표"].values)
    xm, ym = tr_m.transform(bore["X좌표"].values, bore["Y좌표"].values)
    bore["lon"], bore["lat"], bore["x_m"], bore["y_m"] = lon, lat, xm, ym

    # garbage 좌표 제거 (한국 육지 범위)
    kb = CONFIG["korea_bounds"]
    inkorea = (bore["lon"].between(*kb["lon"]) & bore["lat"].between(*kb["lat"]))
    n_bad = int((~inkorea).sum())
    bore = bore[inkorea].copy()

    out = bore[["시추공코드", "lon", "lat", "x_m", "y_m", "등급", "alpha",
                "연약층수", "연약누적두께_m", "최저N", "프로젝트명"]].rename(columns={"시추공코드": "공번"})

    if save:
        os.makedirs(p["out_dir"], exist_ok=True)
        fp = os.path.join(p["out_dir"], "step1_borehole_grade.csv")
        out.to_csv(fp, index=False, encoding="utf-8-sig")

    # --- 콘솔 요약 ---
    print("=" * 70)
    print("STEP 1 — 지반등급 판정 요약  (⚠️ 임계치·α 잠정값)")
    print("=" * 70)
    print(f"입력 SPT행: {n0:,}  →  지층: {len(lyr):,}  →  시추공: {len(bore):,}  (garbage좌표 제거 {n_bad})")
    print("\n[지층 토질분류 분포]")
    print(lyr["soil"].value_counts().to_dict())
    print(f"연약 지층 수: {int(lyr['is_soft'].sum()):,}  "
          f"(점성토연약 {int(lyr[(lyr.soil=='cohesive')&lyr.is_soft].shape[0]):,} / "
          f"사질토연약 {int(lyr[(lyr.soil=='sandy')&lyr.is_soft].shape[0]):,})")
    print("\n[시추공 등급 분포]")
    vc = out["등급"].value_counts()
    for g in ["연약", "주의", "양호"]:
        print(f"  {g}: {int(vc.get(g,0)):,}  (α={ga[g]})  {vc.get(g,0)/len(out)*100:.1f}%")
    print(f"\n연약등급 시추공 연약누적두께(m) 통계: "
          f"중앙={out[out.등급=='연약']['연약누적두께_m'].median():.1f} "
          f"95%={out[out.등급=='연약']['연약누적두께_m'].quantile(.95):.1f}")
    if save:
        print(f"\n저장: {fp}  ({len(out):,}행)")
    return out


if __name__ == "__main__":
    run_step1(save=True)
