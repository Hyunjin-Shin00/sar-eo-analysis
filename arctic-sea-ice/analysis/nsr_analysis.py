"""
북극항로 분석: SIC + SIT + GFW Vessel Presence (2026-03-01 단일 날짜)
=======================================================================
[분석 목적]
  해빙농도(SIC), 해빙두께(SIT), 선박 존재(Vessel Presence) 세 데이터를
  동일 격자에서 비교하여, 해빙 조건과 실제 선박 통항 패턴의 관계를 분석한다.

[입력 데이터]
  - SIC : OSI-SAF 해빙농도, EPSG:3995, 약 10km 해상도, 값 범위 0~1 (→ ×100 변환)
  - SIT : SMOS L3 해빙두께, EPSG:3995, 약 12.5km 해상도, 값 범위 0~약 1.6m
           ※ SMOS는 두께 ~1m 이상에서 신호 포화로 측정 불가 → 두꺼운 빙 구간 NaN 많음
  - GFW : Global Fishing Watch Vessel Presence, EPSG:4326, 0.1° 격자
           값 = 해당 픽셀의 선박 존재 시간(vessel-hours), nodata = 999999
           ※ 선박이 없는 바다 픽셀은 파일에 아예 존재하지 않는 sparse 구조

[처리 흐름]
  1. GFW 여러 지역 tif 파일을 하나로 병합
  2. SIT를 SIC 격자(EPSG:3995)에 맞춰 리샘플링
  3. GFW 유효 픽셀의 위경도 좌표를 EPSG:3995로 변환 후
     SIC 격자 인덱스(row, col)에 직접 매핑 → vp_map 생성
     (vp_map=0: 선박 없음, vp_map>0: 선박 있음)
  4. GFW 커버 위도(15~88°N) 내의 SIC 유효 픽셀을 분석 대상으로 제한

[출력 결과 해석]
  - 콘솔 통계
      · SIC 구간별 전체 픽셀 수, VP>0 픽셀 수, 비율(%)
        → 비율(%) = 해당 SIC 구간에서 선박이 실제로 관측된 픽셀의 비중
        → SIC가 높을수록 비율 감소 = 해빙 조건이 통항 가능성을 제한함을 정량화

  - fig1_sic_histogram.png
      · SIC 구간별 전체 픽셀 수(연한 파랑)와 VP>0 픽셀 수(진한 색) 막대 비교
      · 붉은 꺾은선: SIC 구간별 VP>0 비율(%)
      · 해석: 선박 통항이 어느 SIC 구간에 집중되는지, SIC가 통항을 얼마나 제한하는지 확인

  - fig2_sit_at_sic100.png
      · SIC=100% 픽셀만 대상으로 VP 유무에 따른 SIT 분포 히스토그램
      · 기준선: 0.3m(PC7 하한), 0.7m(PC7 상한=PC6 하한), 1.2m(PC4 하한)
        - PC7(30~70cm): 여름·가을 얇은 1년생 빙 운항 가능한 최저 극지 등급
        - PC6(70~120cm): 여름·가을 중간 두께 1년생 빙
        - PC4(120cm~): 두꺼운 1년생 빙, 연중 운항
      · 해석: SIC=100%에서 SIT가 0.7m 이하면 PC7급 독립 운항 가능성,
               1.2m 이상이면 PC4급 이상(쇄빙선 수준) 필요
      ※ SIC=100%이지만 SIT 데이터 없는 픽셀 = SMOS 포화 구간(두께 >1m 가능성 높음)

  - fig3_sic_sit_scatter.png
      · X축=SIC(%), Y축=SIT(m), 색=픽셀 수(log scale)
      · 왼쪽(VP=0): 선박이 없는 픽셀의 SIC-SIT 분포
      · 오른쪽(VP>0): 선박이 있는 픽셀의 SIC-SIT 분포
      · 해석: 실제 통항이 집중되는 SIC-SIT 조건 공간을 시각화
               두 그래프의 분포 차이 = 해빙 조건이 통항을 차단하는 임계 영역
=======================================================================
"""

import os, glob
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pyproj import Transformer
import rasterio
from rasterio.merge import merge
import warnings
warnings.filterwarnings("ignore")
import matplotlib
matplotlib.rcParams['font.family'] = 'Malgun Gothic'   # Windows 맑은 고딕
matplotlib.rcParams['axes.unicode_minus'] = False       # 마이너스 기호 깨짐 방지

# ──────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────
GFW_ROOT = r"<DATA_ROOT>\14_NSR\GFW\vessel_presence"
SIC_PATH = r"<DATA_ROOT>\14_NSR\OSI_SAF\conc\ice_conc_nh_polstere-100_multi_202603011200_epsg3995.tif"
SIT_PATH = r"<DATA_ROOT>\14_NSR\SMOS\Thickness\SMOS_Icethickness_v3.6_north_20260301_sea_ice_thickness_epsg3995.tif"
OUT_DIR  = r"<DATA_ROOT>\14_NSR\analysis_output"
os.makedirs(OUT_DIR, exist_ok=True)

GFW_NODATA = 999999

# ──────────────────────────────────────────
# 1. SIC / SIT 읽기
# ──────────────────────────────────────────
print("▶ SIC / SIT 읽기...")
with rasterio.open(SIC_PATH) as ds:
    sic = ds.read(1).astype(float)
    sic_trans = ds.transform
    sic_crs   = ds.crs
    sic_h, sic_w = ds.shape

with rasterio.open(SIT_PATH) as ds:
    sit_raw = ds.read(1).astype(float)
    sit_trans = ds.transform
    sit_crs   = ds.crs
    sit_h, sit_w = ds.shape

# SIC: 0~1 → 0~100%, nodata 처리
sic[(sic < 0) | (sic > 1)] = np.nan
sic = sic * 100.0

# SIT: 0 및 비현실값 → NaN
sit_raw[sit_raw <= 0] = np.nan
sit_raw[sit_raw > 10] = np.nan

print(f"  SIC shape: {sic.shape}, 유효: {np.sum(~np.isnan(sic)):,}")
print(f"  SIT shape: {sit_raw.shape}, 유효: {np.sum(~np.isnan(sit_raw)):,}")

# ──────────────────────────────────────────
# 2. SIT → SIC 격자 리샘플링 (rasterio reproject)
# ──────────────────────────────────────────
print("\n▶ SIT → SIC 격자 리샘플링...")
from rasterio.warp import reproject, Resampling
sit = np.full((sic_h, sic_w), np.nan, dtype=np.float32)
with rasterio.open(SIT_PATH) as src:
    reproject(
        source=rasterio.band(src, 1),
        destination=sit,
        src_transform=src.transform,
        src_crs=src.crs,
        dst_transform=sic_trans,
        dst_crs=sic_crs,
        resampling=Resampling.average,
        src_nodata=float('nan'),
        dst_nodata=float('nan'),
    )
sit[sit <= 0] = np.nan
sit[sit > 10] = np.nan
print(f"  SIT 리샘플링 완료, 유효: {np.sum(~np.isnan(sit)):,}")

# ──────────────────────────────────────────
# 3. GFW 병합 및 유효 픽셀 좌표 추출 (EPSG:4326)
# ──────────────────────────────────────────
print("\n▶ GFW 병합 및 유효 좌표 추출...")
gfw_files = glob.glob(os.path.join(GFW_ROOT, "**", "*.tif"), recursive=True)
gfw_datasets = [rasterio.open(f) for f in gfw_files]
gfw_arr, gfw_transform = merge(gfw_datasets, nodata=GFW_NODATA)
gfw_arr = gfw_arr[0]  # (H, W)
for ds in gfw_datasets:
    ds.close()

# GFW 유효 픽셀 위경도 좌표 계산
rows, cols = np.where(gfw_arr != GFW_NODATA)
gfw_vals   = gfw_arr[rows, cols].astype(float)

# 픽셀 중심 좌표 (EPSG:4326)
lon = gfw_transform.c + (cols + 0.5) * gfw_transform.a
lat = gfw_transform.f + (rows + 0.5) * gfw_transform.e

print(f"  GFW 유효 픽셀 수: {len(gfw_vals):,}")
print(f"  위도 범위: {lat.min():.1f}° ~ {lat.max():.1f}°N")
print(f"  경도 범위: {lon.min():.1f}° ~ {lon.max():.1f}°E")

# ──────────────────────────────────────────
# 4. GFW 위경도 → SIC 격자 인덱스로 변환
# ──────────────────────────────────────────
print("\n▶ GFW 좌표 → SIC 격자 인덱스 매핑...")
transformer = Transformer.from_crs("EPSG:4326", str(sic_crs), always_xy=True)
gfw_x, gfw_y = transformer.transform(lon, lat)  # EPSG:3995 좌표

# SIC 격자 인덱스로 변환
col_idx = np.floor((gfw_x - sic_trans.c) / sic_trans.a).astype(int)
row_idx = np.floor((gfw_y - sic_trans.f) / sic_trans.e).astype(int)

# 범위 내 픽셀만 필터링
in_bounds = (row_idx >= 0) & (row_idx < sic_h) & (col_idx >= 0) & (col_idx < sic_w)
row_idx = row_idx[in_bounds]
col_idx = col_idx[in_bounds]
gfw_vals_in = gfw_vals[in_bounds]

print(f"  SIC 격자 내 GFW 픽셀: {len(gfw_vals_in):,} / {len(gfw_vals):,}")

# ──────────────────────────────────────────
# 5. SIC 격자에 GFW 값 합산 맵 생성
# ──────────────────────────────────────────
print("\n▶ SIC 격자에 VP 맵 생성...")
vp_map = np.zeros((sic_h, sic_w), dtype=float)   # 0 = 선박 없음

# 여러 GFW 픽셀이 같은 SIC 셀에 들어올 경우 합산
np.add.at(vp_map, (row_idx, col_idx), gfw_vals_in)

# GFW가 커버하는 영역 마스크 (바다인지 육지인지 구분용)
# GFW는 바다만 커버하므로, GFW 전체 범위(위도 15~88N) 내의 SIC 픽셀을 유효로 봄
# → SIC 픽셀의 위경도를 계산해서 GFW 위도 범위 내인지 확인
rows_sic, cols_sic = np.mgrid[0:sic_h, 0:sic_w]
sic_x_coords = sic_trans.c + (cols_sic + 0.5) * sic_trans.a
sic_y_coords = sic_trans.f + (rows_sic + 0.5) * sic_trans.e

# EPSG:3995 → EPSG:4326
trans_back = Transformer.from_crs(str(sic_crs), "EPSG:4326", always_xy=True)
sic_lon_map, sic_lat_map = trans_back.transform(sic_x_coords, sic_y_coords)

# GFW 커버 영역: 위도 15~88N, 경도 -180~180
gfw_coverage = (sic_lat_map >= 15) & (sic_lat_map <= 88)

# 분석 마스크: SIC 유효 + GFW 커버 범위 내
analysis_mask = ~np.isnan(sic) & gfw_coverage

print(f"  분석 대상 픽셀(SIC유효+GFW범위): {np.sum(analysis_mask):,}")
print(f"  VP > 0 픽셀: {np.sum(analysis_mask & (vp_map > 0)):,}")
print(f"  VP = 0 픽셀: {np.sum(analysis_mask & (vp_map == 0)):,}")
print(f"  SIC=100% & VP>0: {np.sum((sic==100) & (vp_map>0) & analysis_mask):,}")
print(f"  SIC≥80%  & VP>0: {np.sum((sic>=80)  & (vp_map>0) & analysis_mask):,}")

# ──────────────────────────────────────────
# 6. SIC 구간별 집계
# ──────────────────────────────────────────
bins   = [0, 15, 40, 70, 90, 100, 100.01]
labels = ["0–15%", "15–40%", "40–70%", "70–90%", "90–<100%", "100%"]
colors = ["#2196F3","#4CAF50","#FFC107","#FF9800","#F44336","#9C27B0"]

sic_f = sic[analysis_mask].ravel()
vp_f  = vp_map[analysis_mask].ravel()

n_all, n_vp, vp_sum = [], [], []
for i in range(len(labels)):
    lo, hi = bins[i], bins[i+1]
    m = (sic_f >= lo) & (sic_f < hi)
    n_all.append(int(np.sum(m)))
    n_vp.append(int(np.sum(m & (vp_f > 0))))
    vp_sum.append(float(np.nansum(vp_f[m & (vp_f > 0)])))

ratio = [v/a*100 if a > 0 else 0 for v, a in zip(n_vp, n_all)]

print(f"\n── SIC 구간별 통계 ──")
print(f"{'구간':<12} {'전체 픽셀':>10} {'VP>0 픽셀':>10} {'비율(%)':>8} {'VP합계':>12}")
for i, lbl in enumerate(labels):
    print(f"{lbl:<12} {n_all[i]:>10,} {n_vp[i]:>10,} {ratio[i]:>8.2f} {vp_sum[i]:>12.1f}")

# ──────────────────────────────────────────
# 7. 그림 1: SIC 구간별 히스토그램
# ──────────────────────────────────────────
fig, ax1 = plt.subplots(figsize=(10, 5))
x, w = np.arange(len(labels)), 0.4
ax1.bar(x-w/2, n_all, w, label="전체 픽셀",    color="#90CAF9", edgecolor="k", lw=0.5)
ax1.bar(x+w/2, n_vp,  w, label="VP > 0 픽셀", color=colors,   edgecolor="k", lw=0.5)
ax1.set_xlabel("SIC 구간", fontsize=12)
ax1.set_ylabel("픽셀 수", fontsize=12)
ax1.set_xticks(x); ax1.set_xticklabels(labels, fontsize=11)
ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{int(v):,}"))
ax2 = ax1.twinx()
ax2.plot(x, ratio, "D--", color="crimson", lw=1.5, ms=7, label="VP>0 비율(%)")
ax2.set_ylabel("VP > 0 픽셀 비율 (%)", color="crimson", fontsize=12)
ax2.tick_params(axis="y", labelcolor="crimson")
ax2.set_ylim(0, max(ratio)*1.3+0.1)
h1,l1 = ax1.get_legend_handles_labels()
h2,l2 = ax2.get_legend_handles_labels()
ax1.legend(h1+h2, l1+l2, loc="upper right", fontsize=10)
ax1.set_title("SIC 구간별 Vessel Presence 분포 (2026-03-01)", fontsize=13)
plt.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "fig1_sic_histogram.png"), dpi=150)
plt.show()
print("\n  fig1 저장 완료")

# ──────────────────────────────────────────
# 8. 그림 2: SIC=100% 구간 SIT 분포 비교
# ──────────────────────────────────────────
valid3 = analysis_mask & ~np.isnan(sit)
sic_3 = sic[valid3].ravel()
sit_3 = sit[valid3].ravel()
vp_3  = vp_map[valid3].ravel()

m100 = sic_3 == 100
sit_no  = sit_3[m100 & (vp_3 == 0)]
sit_yes = sit_3[m100 & (vp_3  > 0)]

print(f"\n── SIC=100% 픽셀 SIT 통계 ──")
for lbl, arr in [("VP=0", sit_no), ("VP>0", sit_yes)]:
    if len(arr) > 0:
        print(f"  {lbl}: n={len(arr):,}, 평균={np.nanmean(arr):.3f}m, 중앙값={np.nanmedian(arr):.3f}m")
    else:
        print(f"  {lbl}: 픽셀 없음")

fig, ax = plt.subplots(figsize=(8, 5))
sit_bins = np.arange(0, 2.1, 0.1)
if len(sit_no)  > 0: ax.hist(sit_no,  bins=sit_bins, alpha=0.6, color="#2196F3", label="SIC=100%, VP=0")
if len(sit_yes) > 0: ax.hist(sit_yes, bins=sit_bins, alpha=0.7, color="#F44336", label="SIC=100%, VP>0")
ax.axvline(0.3, color="blue",   ls="--", lw=1.2, label="0.3m (PC7 하한)")
ax.axvline(0.7, color="black", ls="--", lw=1.2, label="0.7m (PC7 상한/PC6 하한)")
ax.axvline(1.2, color="red",   ls="--", lw=1.2, label="1.2m (PC4 하한)")
ax.set_xlabel("SIT (m)", fontsize=12); ax.set_ylabel("픽셀 수", fontsize=12)
ax.set_title("SIC=100% 구간: SIT 분포 (VP 유무 비교)", fontsize=13)
ax.legend(fontsize=10)
plt.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "fig2_sit_at_sic100.png"), dpi=150)
plt.show()
print("  fig2 저장 완료")

# ──────────────────────────────────────────
# 9. 그림 3: SIC–SIT 2D 히스토그램
# ──────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(13, 5))
for ax, title, mask_vp, cmap in zip(
    axes,
    ["VP = 0 (선박 없음)", "VP > 0 (선박 있음)"],
    [vp_3 == 0, vp_3 > 0],
    ["Blues", "Reds"]
):
    d_sic = sic_3[mask_vp]
    d_sit = sit_3[mask_vp]
    if len(d_sic) == 0:
        ax.text(0.5, 0.5, "데이터 없음", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontsize=12); continue
    h = ax.hist2d(d_sic, d_sit, bins=[50,50], range=[[0,100],[0,2.0]],
                  cmap=cmap, norm=plt.matplotlib.colors.LogNorm(vmin=1))
    plt.colorbar(h[3], ax=ax, label="픽셀 수 (log)")
    ax.set_xlabel("SIC (%)", fontsize=11); ax.set_ylabel("SIT (m)", fontsize=11)
    ax.set_title(title, fontsize=12)
    ax.axvline(15, color="lime",   ls="--", lw=1, label="SIC 15%")
    ax.axvline(80, color="yellow", ls="--", lw=1, label="SIC 80%")
    ax.legend(fontsize=9)

plt.suptitle("SIC–SIT 2D 분포: 선박 유무 비교 (2026-03-01)", fontsize=13)
plt.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "fig3_sic_sit_scatter.png"), dpi=150)
plt.show()
print("  fig3 저장 완료")

print(f"\n✅ 분석 완료. 결과: {OUT_DIR}")