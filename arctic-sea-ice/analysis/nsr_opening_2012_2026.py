"""
NSR 개방 시기 시계열 분석 — 통합 스크립트 (분석 + 시각화 v2)
단독 실행 가능. CSV 캐시가 있으면 재사용, 없으면 래스터 추출부터 수행.

데이터:
  SIC  : OSI_SAF/conc/ice_conc_nh_polstere-100_multi_YYYYMMDD1200_epsg3995.tif
  SIT  : SMOS/Thickness/SMOS_Icethickness_v*_north_YYYYMMDD_sea_ice_thickness_epsg3995.tif
  GFW  : GFW/2012_2026/monthly/arctic/presence_arctic_YYYY-MM/.../public-global-presence-v4.0.tif
  AOI  : AOI/arctic_route_aoi_epsg3995.shp  (EPSG:3995)
"""

import os
import glob
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.mask import mask as rio_mask
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
from matplotlib.cm import ScalarMappable
from scipy import stats
import pymannkendall as mk

matplotlib.rc("font", family="Malgun Gothic")
matplotlib.rcParams["axes.unicode_minus"] = False

# ==============================================================
# 경로 및 임계값
# ==============================================================
BASE_DIR        = r"<DATA_ROOT>\14_NSR"
SIC_DIR         = os.path.join(BASE_DIR, "OSI_SAF", "conc")
SIT_DIR         = os.path.join(BASE_DIR, "SMOS", "Thickness")
GFW_MONTHLY_DIR = os.path.join(BASE_DIR, "GFW", "2012_2026", "monthly", "arctic")
AOI_PATH        = os.path.join(BASE_DIR, "AOI", "arctic_route_aoi_epsg3995_2.shp")
OUT_DIR         = os.path.join(BASE_DIR, "analysis_results_2")
MONTHLY_CSV     = os.path.join(OUT_DIR, "monthly_stats_2.csv")
YEARLY_CSV      = os.path.join(OUT_DIR, "yearly_opening_2.csv")
TREND_CSV       = os.path.join(OUT_DIR, "trend_analysis_2.csv")
OUT_PNG         = os.path.join(OUT_DIR, "nsr_opening_analysis_2.png")

SIC_THRESHOLD = 0.3
SIT_THRESHOLD = 0.15
START_YEAR    = 2012
END_YEAR      = 2026
END_MONTH     = 4   # 2026년은 4월까지만

os.makedirs(OUT_DIR, exist_ok=True)

MONTH_LABELS = ["1월","2월","3월","4월","5월","6월",
                "7월","8월","9월","10월","11월","12월"]


# ==============================================================
# Step 1: 래스터 → AOI 통계 추출
# ==============================================================

def _read_masked(fpath, shapes, nodata_vals=None):
    """AOI clip 후 float32 배열 반환. int32 래스터(GFW)도 안전하게 처리."""
    with rasterio.open(fpath) as src:
        file_nodata = src.nodata
        out_img, _ = rio_mask(src, shapes, crop=True, filled=False)
    data = np.ma.filled(out_img[0].astype(np.float32), fill_value=np.nan)
    if file_nodata is not None:
        data[data == float(file_nodata)] = np.nan
    if nodata_vals:
        for v in nodata_vals:
            data[data == float(v)] = np.nan
    data[data < 0] = np.nan
    return data


def _shapes(gdf):
    return [g.__geo_interface__ for g in gdf.geometry]


def extract_sic(year, month, aoi):
    fname = f"ice_conc_nh_polstere-100_multi_{year}{month:02d}151200_epsg3995.tif"
    fpath = os.path.join(SIC_DIR, fname)
    if not os.path.isfile(fpath):
        warnings.warn(f"[SIC 없음] {fpath}")
        return np.nan
    try:
        return float(np.nanmean(_read_masked(fpath, _shapes(aoi))))
    except Exception as e:
        warnings.warn(f"[SIC 오류] {year}-{month:02d}: {e}")
        return np.nan


def extract_sit(year, month, aoi):
    """SMOS 10~4월만 제공. 파일 없는 달(여름 포함)은 모두 NaN 반환."""
    pattern = os.path.join(
        SIT_DIR,
        f"SMOS_Icethickness_v*_north_{year}{month:02d}15_sea_ice_thickness_epsg3995.tif",
    )
    matches = glob.glob(pattern)
    if not matches:
        return np.nan
    try:
        return float(np.nanmean(_read_masked(matches[0], _shapes(aoi))))
    except Exception as e:
        warnings.warn(f"[SIT 오류] {year}-{month:02d}: {e}")
        return np.nan


def extract_gfw(year, month, aoi_4326):
    """GFW는 EPSG:4326 → AOI를 4326으로 변환 후 사용."""
    fpath = os.path.join(
        GFW_MONTHLY_DIR,
        f"presence_arctic_{year}-{month:02d}",
        "layer-activity-data-0",
        "public-global-presence-v4.0.tif",
    )
    if not os.path.isfile(fpath):
        warnings.warn(f"[GFW 없음] {fpath}")
        return np.nan
    try:
        data = _read_masked(fpath, _shapes(aoi_4326), nodata_vals=[999999.0])
        return float(np.nansum(data > 0))
    except Exception as e:
        warnings.warn(f"[GFW 오류] {year}-{month:02d}: {e}")
        return np.nan


def build_monthly_stats():
    print("=== Step 1: 월별 통계 추출 ===")
    aoi      = gpd.read_file(AOI_PATH)
    aoi_4326 = aoi.to_crs("EPSG:4326")
    records  = []
    for year in range(START_YEAR, END_YEAR + 1):
        max_month = END_MONTH if year == END_YEAR else 12
        for month in range(1, max_month + 1):
            sic = extract_sic(year, month, aoi)
            sit = extract_sit(year, month, aoi)
            gfw = extract_gfw(year, month, aoi_4326)
            records.append({"year": year, "month": month,
                            "sic_mean": sic, "sit_mean": sit, "gfw_sum": gfw})
            print(f"  {year}-{month:02d}  SIC={sic:.3f}  SIT={sit if np.isnan(sit) else f'{sit:.3f}'}  GFW={gfw:.0f}")
    df = pd.DataFrame(records)
    df.to_csv(MONTHLY_CSV, index=False, encoding="utf-8-sig")
    print(f"[저장] {MONTHLY_CSV}\n")
    return df


# ==============================================================
# Step 2: 개방 판정
# ==============================================================

def add_open_flag(df):
    """NaN SIT(데이터 없는 달)는 0으로 간주하여 조건 판정."""
    sit_filled = df["sit_mean"].fillna(0.0)
    df["is_open"] = (df["sic_mean"] < SIC_THRESHOLD) & (sit_filled < SIT_THRESHOLD)
    return df


# ==============================================================
# Step 3: 연도별 지표
# ==============================================================

def calc_yearly_opening(df):
    print("=== Step 3: 연도별 지표 산출 ===")
    records = []
    for year, grp in df.groupby("year"):
        open_rows = grp[grp["is_open"]]
        months    = open_rows["month"].tolist()
        if months:
            start, end, dur = int(min(months)), int(max(months)), len(months)
            gfw_sum = float(open_rows["gfw_sum"].sum())
        else:
            start = end = dur = gfw_sum = np.nan
        records.append({"year": year, "open_start": start, "open_end": end,
                        "open_duration": dur, "gfw_total": gfw_sum})
        print(f"  {year}: 시작={start}  종료={end}  기간={dur}개월  GFW={gfw_sum:.0f}" if months
              else f"  {year}: 개방 없음")
    df_y = pd.DataFrame(records)
    df_y.to_csv(YEARLY_CSV, index=False, encoding="utf-8-sig")
    print(f"[저장] {YEARLY_CSV}\n")
    return df_y


# ==============================================================
# Step 4: 추세 분석
# ==============================================================

def analyze_trends(df_y):
    print("=== Step 4: 추세 분석 ===")
    rows = []
    for col, label in [("open_start","개방 시작월"), ("open_end","개방 종료월"),
                       ("open_duration","개방 기간(개월)")]:
        valid = df_y[["year", col]].dropna()
        if len(valid) < 3:
            print(f"  [{label}] 데이터 부족")
            continue
        x, y = valid["year"].values, valid[col].values
        slope, intercept, r, p, _ = stats.linregress(x, y)
        mk_res = mk.original_test(y)
        print(f"\n  [{label}]")
        print(f"    선형회귀: 기울기 {slope:+.4f}/년  R²={r**2:.3f}  p={p:.4f}")
        print(f"    Mann-Kendall: trend={mk_res.trend}  Tau={mk_res.Tau:.3f}  p={mk_res.p:.4f}")
        rows.append({"variable": label, "slope": slope, "intercept": intercept,
                     "r2": r**2, "p_linreg": p,
                     "mk_trend": mk_res.trend, "mk_tau": mk_res.Tau, "mk_p": mk_res.p})
    df_t = pd.DataFrame(rows)
    df_t.to_csv(TREND_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[저장] {TREND_CSV}\n")
    return df_t


# ==============================================================
# 데이터 로드 (캐시 우선)
# ==============================================================

def load_data():
    if os.path.isfile(MONTHLY_CSV) and os.path.isfile(YEARLY_CSV):
        print(f"[캐시 로드] {MONTHLY_CSV}")
        df_m = pd.read_csv(MONTHLY_CSV)
        df_y = pd.read_csv(YEARLY_CSV)
    else:
        df_m = build_monthly_stats()
        df_m = add_open_flag(df_m)
        df_y = calc_yearly_opening(df_m)
        analyze_trends(df_y)
        return df_m, df_y

    # 캐시 로드 후 처리
    df_m = add_open_flag(df_m)
    df_y = calc_yearly_opening(df_m)   # 임계값 변경 시 재계산
    return df_m, df_y


# ==============================================================
# 공통 헬퍼 (시각화)
# ==============================================================

def _text_color(rgba):
    lum = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
    return "black" if lum > 0.45 else "white"


def _heatmap_base(ax, matrix, open_matrix, cmap, vmin, vmax, years, cbar_label):
    n_years, n_months = len(years), 12
    cmap_obj = plt.get_cmap(cmap).copy()
    cmap_obj.set_bad(color="lightgray")
    norm   = mcolors.Normalize(vmin=vmin, vmax=vmax)
    masked = np.ma.array(matrix, mask=np.isnan(matrix))

    im = ax.pcolormesh(np.arange(n_months + 1), np.arange(n_years + 1),
                       masked, cmap=cmap_obj, norm=norm)
    plt.colorbar(im, ax=ax, label=cbar_label, shrink=0.85, pad=0.02)

    for yi in range(n_years):
        for mi in range(n_months):
            val = matrix[yi, mi]
            if not np.isnan(val):
                tc = _text_color(cmap_obj(norm(val)))
                ax.text(mi + 0.5, yi + 0.5, f"{val:.2f}",
                        ha="center", va="center", fontsize=7, color=tc)

    for yi in range(n_years):
        for mi in range(n_months):
            if open_matrix[yi, mi]:
                ax.add_patch(mpatches.Rectangle(
                    (mi, yi), 1, 1, linewidth=2, edgecolor="white", facecolor="none"))

    ax.set_xticks(np.arange(n_months) + 0.5)
    ax.set_xticklabels(MONTH_LABELS, fontsize=8)
    ax.set_yticks(np.arange(n_years) + 0.5)
    ax.set_yticklabels(years, fontsize=8)
    ax.set_xlabel("월")
    ax.set_ylabel("연도")


def _year_colorbar(ax, years, cmap_name):
    norm = mcolors.Normalize(vmin=years[0], vmax=years[-1])
    sm   = ScalarMappable(cmap=plt.get_cmap(cmap_name), norm=norm)
    sm.set_array([])
    cb = plt.colorbar(sm, ax=ax, shrink=0.85, pad=0.02)
    cb.set_label("연도")
    cb.set_ticks(range(years[0], years[-1] + 1, 2))
    return plt.get_cmap(cmap_name), norm


def _pivot(df, col, years, months=range(1, 13)):
    return df.pivot(index="year", columns="month", values=col)\
             .reindex(index=years, columns=list(months)).values


# ==============================================================
# (0,0) SIC 히트맵
# ==============================================================

def plot_sic_heatmap(ax, df_m):
    years    = sorted(df_m["year"].unique())
    sic_mat  = _pivot(df_m, "sic_mean", years)
    open_mat = _pivot(df_m, "is_open", years)
    open_mat = np.where(np.isnan(open_mat.astype(float)), False, open_mat).astype(bool)

    _heatmap_base(ax, sic_mat, open_mat, "RdYlBu_r", 0, 1, years, "SIC (0~1)")
    ax.set_title(f"SIC 월별 히트맵  (흰 테두리: 개방,  기준 SIC<{SIC_THRESHOLD*100:.0f}%·SIT<{SIT_THRESHOLD}m)")


# ==============================================================
# (0,1) SIT 히트맵
# ==============================================================

def plot_sit_heatmap(ax, df_m):
    years    = sorted(df_m["year"].unique())
    sit_mat  = _pivot(df_m, "sit_mean", years)   # 5~9월은 NaN → 회색
    open_mat = _pivot(df_m, "is_open", years)
    open_mat = np.where(np.isnan(open_mat.astype(float)), False, open_mat).astype(bool)

    _heatmap_base(ax, sit_mat, open_mat, "YlOrRd", 0, 1.0, years, "SIT (m)")
    ax.set_title("SIT 월별 히트맵  (흰 테두리: 개방,  회색=데이터 없음)")


# ==============================================================
# (1,0) SIC 월별 변화 라인
# ==============================================================

def plot_sic_lines(ax, df_m):
    years = sorted(df_m["year"].unique())
    cmap, norm = _year_colorbar(ax, years, "plasma")

    for yr in years:
        d = df_m[df_m["year"] == yr].sort_values("month")
        ax.plot(d["month"], d["sic_mean"], color=cmap(norm(yr)), alpha=0.85, linewidth=1.5)

    ax.axhline(SIC_THRESHOLD, color="red", ls="--", lw=1.8,
               label=f"SIC {SIC_THRESHOLD*100:.0f}% 기준선")
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(MONTH_LABELS, fontsize=8)
    ax.set_xlim(1, 12)
    ax.set_ylabel("SIC (0~1)")
    ax.set_xlabel("월")
    ax.set_title("연도별 SIC 월간 변화")
    ax.legend(fontsize=8, loc="upper right")


# ==============================================================
# (1,1) SIT 월별 변화 라인
# ==============================================================

def plot_sit_lines(ax, df_m):
    years = sorted(df_m["year"].unique())
    cmap, norm = _year_colorbar(ax, years, "plasma")

    for yr in years:
        d = df_m[df_m["year"] == yr].sort_values("month")
        # NaN(5~9월 포함 데이터 없는 달)은 라인 자동 끊김
        ax.plot(d["month"], d["sit_mean"], color=cmap(norm(yr)), alpha=0.85, linewidth=1.5)

    ax.axhline(SIT_THRESHOLD, color="red", ls="--", lw=1.8,
               label=f"SIT {SIT_THRESHOLD}m 기준선")
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(MONTH_LABELS, fontsize=8)
    ax.set_xlim(1, 12)
    ax.set_ylabel("SIT (m)")
    ax.set_xlabel("월")
    ax.set_title("연도별 SIT 월간 변화  (데이터 없는 달은 라인 끊김)")
    ax.legend(fontsize=8, loc="upper right")


# ==============================================================
# (2,0) 월별 SIC-GFW 오버레이
# ==============================================================

def plot_sic_gfw_monthly_overlay(ax, df_m):
    """월별 전연도 평균 SIC(라인) + 평균 GFW(바) 오버레이. 이중 Y축."""
    months = list(range(1, 13))

    # 전연도 평균
    sic_avg = df_m.groupby("month")["sic_mean"].mean().reindex(months)
    gfw_avg = df_m.groupby("month")["gfw_sum"].mean().reindex(months)

    ax2 = ax.twinx()

    # ── GFW 바 (뒤, zorder=1) ──────────────────────────────────
    ax2.bar(months, gfw_avg.values, width=0.6,
            color="#ff7f0e", alpha=0.6, zorder=1, label="GFW 평균 (전연도)")
    ax2.set_ylabel("GFW 통항량 (평균)", color="#ff7f0e")
    ax2.tick_params(axis="y", labelcolor="#ff7f0e")

    # ── 개별 연도 SIC 라인 (회색, 배경) ───────────────────────
    years = sorted(df_m["year"].unique())
    for yr in years:
        d = df_m[df_m["year"] == yr].sort_values("month")
        ax.plot(d["month"], d["sic_mean"],
                color="gray", alpha=0.25, linewidth=0.8, zorder=2)
    # 범례용 더미 핸들
    gray_line = matplotlib.lines.Line2D([], [], color="gray", alpha=0.5,
                                        linewidth=0.8, label="개별 연도 SIC")

    # ── SIC 개방 구간 음영 ─────────────────────────────────────
    open_months = [m for m in months
                   if pd.notna(sic_avg[m]) and sic_avg[m] < SIC_THRESHOLD]
    if open_months:
        # 연속 구간 묶기
        groups, cur = [], [open_months[0]]
        for m in open_months[1:]:
            if m == cur[-1] + 1:
                cur.append(m)
            else:
                groups.append(cur); cur = [m]
        groups.append(cur)
        for g in groups:
            ax.axvspan(g[0] - 0.5, g[-1] + 0.5, alpha=0.1, color="skyblue", zorder=0)
        # 음영 구간 중앙에 텍스트
        mid = open_months[len(open_months) // 2]
        ax.text(mid, SIC_THRESHOLD * 0.5, "개방 구간",
                ha="center", va="center", fontsize=8, color="steelblue", alpha=0.8)

    # ── 평균 SIC 라인 (앞, zorder=3) ─────────────────────────
    sic_line, = ax.plot(months, sic_avg.values,
                        color="#1f77b4", linewidth=2.5,
                        marker="o", markersize=6, zorder=3, label="SIC 평균 (전연도)")
    ax.axhline(SIC_THRESHOLD, color="red", ls="--", lw=1.5, zorder=3,
               label=f"SIC {SIC_THRESHOLD*100:.0f}% 기준")
    ax.set_ylabel("SIC (0~1)", color="#1f77b4")
    ax.tick_params(axis="y", labelcolor="#1f77b4")

    ax.set_xticks(months)
    ax.set_xticklabels(MONTH_LABELS, fontsize=8)
    ax.set_xlim(0.5, 12.5)
    ax.set_xlabel("월")
    ax.set_title("월별 해빙 조건(SIC)과 선박 통항량(GFW) 비교")

    # ── 범례 통합 ─────────────────────────────────────────────
    gfw_patch = mpatches.Patch(color="#ff7f0e", alpha=0.6, label="GFW 평균 (전연도)")
    handles = [sic_line,
               matplotlib.lines.Line2D([], [], color="red", ls="--", lw=1.5,
                                       label=f"SIC {SIC_THRESHOLD*100:.0f}% 기준"),
               gfw_patch, gray_line]
    ax.legend(handles=handles, fontsize=8, loc="upper left")


# ==============================================================
# (2,1) GFW 월별 통항량 히트맵
# ==============================================================

def plot_gfw_heatmap(ax, df_m):
    """SIC/SIT 히트맵과 동일 형식으로 GFW 월별 통항량을 표시."""
    years   = sorted(df_m["year"].unique())
    gfw_mat = _pivot(df_m, "gfw_sum", years)

    n_years, n_months = len(years), 12
    cmap_obj = plt.get_cmap("YlOrBr").copy()
    cmap_obj.set_bad(color="lightgray")

    vmax = float(np.nanmax(gfw_mat)) if not np.all(np.isnan(gfw_mat)) else 1.0
    norm = mcolors.Normalize(vmin=0, vmax=vmax)
    masked = np.ma.array(gfw_mat, mask=np.isnan(gfw_mat))

    im = ax.pcolormesh(np.arange(n_months + 1), np.arange(n_years + 1),
                       masked, cmap=cmap_obj, norm=norm)
    plt.colorbar(im, ax=ax, label="GFW 통항량", shrink=0.85, pad=0.02)

    for yi in range(n_years):
        for mi in range(n_months):
            val = gfw_mat[yi, mi]
            if not np.isnan(val) and val > 0:
                tc = _text_color(cmap_obj(norm(val)))
                ax.text(mi + 0.5, yi + 0.5, str(int(val)),
                        ha="center", va="center", fontsize=7, color=tc)

    ax.set_xticks(np.arange(n_months) + 0.5)
    ax.set_xticklabels(MONTH_LABELS, fontsize=8)
    ax.set_yticks(np.arange(n_years) + 0.5)
    ax.set_yticklabels(years, fontsize=8)
    ax.set_xlabel("월")
    ax.set_ylabel("연도")
    ax.set_title("GFW 월별 선박 통항량 히트맵")


# ==============================================================
# Figure 조립 및 저장
# ==============================================================

def make_figure_v3(df_m, df_y):
    print("=== 시각화 v3 생성 ===")
    fig, axes = plt.subplots(3, 2, figsize=(20, 24))
    fig.suptitle(
        f"북극항로(NSR) 개방 시기 시계열 분석 ({START_YEAR}~{END_YEAR})\n"
        f"개방 기준: SIC < {SIC_THRESHOLD*100:.0f}%  &  SIT < {SIT_THRESHOLD} m",
        fontsize=15, fontweight="bold",
    )
    plot_sic_heatmap(axes[0, 0], df_m)
    plot_sit_heatmap(axes[0, 1], df_m)
    plot_sic_lines(axes[1, 0], df_m)
    plot_sit_lines(axes[1, 1], df_m)
    plot_sic_gfw_monthly_overlay(axes[2, 0], df_m)
    plot_gfw_heatmap(axes[2, 1], df_m)

    plt.tight_layout(rect=[0, 0, 1, 0.95], h_pad=4.0, w_pad=3.0)
    plt.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    print(f"[저장] {OUT_PNG}")
    plt.show()


# ==============================================================
# 메인
# ==============================================================

if __name__ == "__main__":
    df_monthly, df_yearly = load_data()
    analyze_trends(df_yearly)
    make_figure_v3(df_monthly, df_yearly)
