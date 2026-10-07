#!/usr/bin/env python3
"""특수건물(특건) 공백 산출 — 성서산단 공장 중 연면적 3,000㎡ 미만 비율.

화재보험법(「화재로 인한 재해보상과 보험가입에 관한 법률」) 시행령 제2조: 공장은 연면적 합계
3,000㎡ 이상이어야 특수건물(특약부화재보험 의무·안전점검 대상). 그 아래 SME 공장은
인수심사 참고자료(안전점검 보고서)가 없는 '공백' 구간이다.

입력: GIS건물통합정보 일반건축물 shapefile (AL_D162_27_*.shp, 대구, EPSG:5186, CP949).
필드명이 A0~A39로 익명이라 실측 역판별한 매핑을 쓴다:
  A1=PNU(19자리) · A3=법정동 주소 · A24=연면적(㎡) · A29=주용도코드('17000'=공장) · A39=시군구코드

사용:
  python special_bld_gap.py <DATA_ROOT>/ledger/daegu_27/AL_D162_27_20260115.shp [--fig out_dir]
"""
import argparse
import os
from collections import defaultdict

from osgeo import gdal, ogr

gdal.SetConfigOption("SHAPE_ENCODING", "CP949")
ogr.UseExceptions()

SEONGSEO_DONGS = ["갈산동", "월암동", "대천동", "장동", "호산동", "파호동", "신당동", "호림동", "이곡동"]
DALSEO = "27290"
FACTORY = "17000"
THRESH = 3000.0


def load(path, with_geom=False):
    ds = ogr.Open(path)
    lyr = ds.GetLayer(0)
    lyr.SetAttributeFilter(f"A29='{FACTORY}' AND A39='{DALSEO}'")
    rows = []
    for f in lyr:
        dong = (f.GetField("A3") or "").split()[-1]
        if dong not in SEONGSEO_DONGS:
            continue
        pnu = f.GetField("A1")
        if not (pnu and len(pnu) == 19 and pnu.isdigit()):   # 스키마 방어: A1이 PNU가 아니면 중단
            raise ValueError(f"A1 is not a 19-digit PNU: {pnu!r}")
        g = f.GetGeometryRef()
        rows.append(dict(dong=dong, pnu=pnu, gfa=f.GetField("A24") or 0.0,
                         wkb=bytes(g.ExportToWkb()) if (with_geom and g) else None))
    return rows


def summarize(rows):
    parcel = defaultdict(float)
    for r in rows:
        parcel[r["pnu"]] += r["gfa"]
    n_b = len(rows)
    n_b_small = sum(r["gfa"] < THRESH for r in rows)
    n_p = len(parcel)
    n_p_small = sum(v < THRESH for v in parcel.values())
    print(f"건물(동) 단위 : {n_b_small:,} / {n_b:,} = {n_b_small / n_b:.1%}  (연면적 < 3,000㎡)")
    print(f"필지(PNU) 단위: {n_p_small:,} / {n_p:,} = {n_p_small / n_p:.1%}")
    by_dong = defaultdict(lambda: [0, 0])
    seen = set()
    for r in rows:
        if r["pnu"] in seen:
            continue
        seen.add(r["pnu"])
        by_dong[r["dong"]][0] += 1
        by_dong[r["dong"]][1] += parcel[r["pnu"]] < THRESH
    for d in SEONGSEO_DONGS:
        t, s = by_dong[d]
        print(f"  {d:<5} 필지 {t:4d}  3,000㎡ 미만 {s:4d} ({s / t:.0%})")
    return parcel, by_dong


def figures(rows, parcel, by_dong, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Polygon

    from matplotlib import font_manager
    cjk = os.environ.get("CJK_FONT", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if os.path.exists(cjk):
        font_manager.fontManager.addfont(cjk)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=cjk).get_name()
    BLUE, GRAY, INK, MUTED = "#2a78d6", "#b4b2aa", "#0b0b0b", "#52514e"
    os.makedirs(out, exist_ok=True)

    # 1) 지도: 공장 건물 footprint, 소속 필지 연면적 합으로 색 구분
    small, large = [], []
    for r in rows:
        g = ogr.CreateGeometryFromWkb(r["wkb"])
        polys = [g] if g.GetGeometryName() == "POLYGON" else [g.GetGeometryRef(i) for i in range(g.GetGeometryCount())]
        for p in polys:
            ring = np.array(p.GetGeometryRef(0).GetPoints())[:, :2]
            (small if parcel[r["pnu"]] < THRESH else large).append(Polygon(ring, closed=True))
    fig, ax = plt.subplots(figsize=(10, 10), dpi=160)
    ax.add_collection(PatchCollection(large, facecolor=GRAY, edgecolor="none"))
    ax.add_collection(PatchCollection(small, facecolor=BLUE, edgecolor="none"))
    ax.autoscale_view(); ax.set_aspect("equal"); ax.axis("off")
    n_p = len(parcel); n_s = sum(v < THRESH for v in parcel.values())
    ax.set_title(f"성서산단 공장 필지 {n_p:,}곳 중 {n_s:,}곳({n_s / n_p:.1%})이 특수건물 기준(연면적 3,000㎡) 미만",
                 fontsize=14, color=INK, loc="left")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=BLUE, label=f"필지 연면적 < 3,000㎡ (안전점검 자료 없음) · {n_s:,}곳"),
                       Patch(color=GRAY, label=f"필지 연면적 ≥ 3,000㎡ (특수건물) · {n_p - n_s:,}곳")],
              loc="lower left", frameon=False, fontsize=11)
    ax.text(1, 0, "자료: GIS건물통합정보(2026-01) 주용도=공장 · EPSG:5186", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=9, color=MUTED)
    fig.savefig(os.path.join(out, "map_special_gap.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # 2) 분포: 필지 연면적 합 히스토그램 (로그축) + 3,000㎡ 기준선
    v = np.array(list(parcel.values()))
    v = v[v > 0]
    bins = np.logspace(np.log10(v.min()), np.log10(v.max()), 45)
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=160)
    ax.hist(v[v < THRESH], bins=bins, color=BLUE, rwidth=0.85, label="3,000㎡ 미만")
    ax.hist(v[v >= THRESH], bins=bins, color=GRAY, rwidth=0.85, label="3,000㎡ 이상")
    ax.axvline(THRESH, color=INK, lw=1)
    ax.text(THRESH * 1.05, ax.get_ylim()[1] * 0.92, "특수건물 기준 3,000㎡", fontsize=10, color=INK)
    ax.set_xscale("log"); ax.set_xlabel("필지별 공장 연면적 합 (㎡, 로그축)"); ax.set_ylabel("필지 수")
    ax.set_title(f"필지별 공장 연면적 분포 · 중앙값 {np.median(list(parcel.values())):,.0f}㎡", loc="left", fontsize=13)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#e6e5e0", lw=0.6); ax.set_axisbelow(True)
    ax.legend(frameon=False)
    fig.savefig(os.path.join(out, "hist_parcel_gfa.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # 3) 법정동별 막대 (가로 누적)
    d = sorted(SEONGSEO_DONGS, key=lambda k: by_dong[k][0])
    tot = np.array([by_dong[k][0] for k in d]); sm = np.array([by_dong[k][1] for k in d])
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=160)
    ax.barh(d, sm, color=BLUE, height=0.6, label="3,000㎡ 미만")
    ax.barh(d, tot - sm, left=sm + 2, color=GRAY, height=0.6, label="3,000㎡ 이상")
    for i, (t, s) in enumerate(zip(tot, sm)):
        ax.text(t + 6, i, f"{s}/{t} ({s / t:.0%})", va="center", fontsize=9.5, color=MUTED)
    ax.set_xlabel("공장 필지 수"); ax.set_title("법정동별 특수건물 기준 미만 공장 필지", loc="left", fontsize=13)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, loc="lower right")
    ax.set_xlim(0, tot.max() * 1.25)
    fig.savefig(os.path.join(out, "bar_by_dong.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("shp")
    ap.add_argument("--fig", default=None, help="그림 출력 폴더 (생략 시 수치만)")
    a = ap.parse_args()
    rows = load(a.shp, with_geom=bool(a.fig))
    parcel, by_dong = summarize(rows)
    if a.fig:
        figures(rows, parcel, by_dong, a.fig)
