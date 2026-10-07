"""
북극항로 월별 지도 생성 (2012–현재)
=====================================
레이아웃: 왼쪽=해빙농도(SIC), 오른쪽=해빙두께(SIT)
표시 범위: 위도 40°N 이상
GFW 자료: arctic / atlantic_ne / atlantic_nw / pacific_ne / pacific_nw 폴더
          각 폴더 내 presence_{region}_YYYY-MM/layer-activity-data-0/public-global-presence-v4.0.tif
출력: <DATA_ROOT>/14_NSR/월간분석_2012_2026/YYYYMM.png
"""

import glob
import warnings
from pathlib import Path

import contextily as ctx
import matplotlib
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from pyproj import Transformer as ProjTransformer
from rasterio.crs import CRS
from rasterio.merge import merge
from rasterio.warp import reproject, Resampling

warnings.filterwarnings("ignore")
matplotlib.rcParams['font.family'] = 'Malgun Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False

# ─────────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────────
GFW_BASE_DIR = Path(r"<DATA_ROOT>\14_NSR\GFW")
GFW_REGIONS  = ["arctic", "atlantic_ne", "atlantic_nw", "pacific_ne", "pacific_nw"]
SMOS_DIR     = Path(r"<DATA_ROOT>\14_NSR\SMOS\Thickness")
SIC_DIR      = Path(r"<DATA_ROOT>\14_NSR\OSI_SAF\conc")
OUT_DIR      = Path(r"<DATA_ROOT>\14_NSR\월간분석_2012_2026")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DISPLAY_CRS = CRS.from_epsg(3995)

SIT_VMIN, SIT_VMAX = 0.0, 2.0
SIC_VMIN, SIC_VMAX = 0.0, 1.0

# ─────────────────────────────────────────────
# 위도 40°N 이상 표시 범위 계산 (EPSG:3995)
# ─────────────────────────────────────────────
_t4326_3995 = ProjTransformer.from_crs("EPSG:4326", "EPSG:3995", always_xy=True)
_lons = np.arange(0, 360, 5)
_xs, _ys = _t4326_3995.transform(_lons, np.full_like(_lons, 40.0))
MAP_RADIUS = float(max(np.max(np.abs(_xs)), np.max(np.abs(_ys)))) * 1.01
MAP_XLIM = (-MAP_RADIUS, MAP_RADIUS)
MAP_YLIM = (-MAP_RADIUS, MAP_RADIUS)
print(f"위도 40°N 표시 반경: {MAP_RADIUS/1e6:.2f} × 10⁶ m")

# ─────────────────────────────────────────────
# 공통 참조 격자 (SMOS TIF 기준)
# ─────────────────────────────────────────────
_ref_files = sorted(SMOS_DIR.glob("*sea_ice_thickness*epsg3995.tif"))
if not _ref_files:
    raise FileNotFoundError(f"SMOS TIF 없음: {SMOS_DIR}")

with rasterio.open(_ref_files[0]) as _ds:
    REF_TRANSFORM = _ds.transform
    REF_H, REF_W  = _ds.height, _ds.width
    REF_BOUNDS    = _ds.bounds

EXTENT_MPL = [REF_BOUNDS.left, REF_BOUNDS.right,
              REF_BOUNDS.bottom, REF_BOUNDS.top]

print(f"참조 격자: {REF_H} x {REF_W}")


# ─────────────────────────────────────────────
# 데이터 로더
# ─────────────────────────────────────────────
def get_gfw_tif_files(year_month: str) -> list:
    """year_month: 'YYYY-MM'. 5개 지역에서 존재하는 TIF 경로 반환."""
    tif_files = []
    for region in GFW_REGIONS:
        tif_path = (GFW_BASE_DIR / region
                    / f"presence_{region}_{year_month}"
                    / "layer-activity-data-0"
                    / "public-global-presence-v4.0.tif")
        if tif_path.exists():
            tif_files.append(tif_path)
    return tif_files


def load_gfw_presence(year_month: str) -> np.ndarray:
    tif_files = get_gfw_tif_files(year_month)
    if not tif_files:
        return None

    datasets = [rasterio.open(f) for f in tif_files]
    src_nodata = datasets[0].nodata  # 파일에 기록된 nodata 값 사용
    gfw_arr, gfw_trans = merge(datasets, nodata=src_nodata)
    gfw_crs = datasets[0].crs
    for ds in datasets:
        ds.close()

    gfw_arr = gfw_arr[0].astype(np.float32)
    if src_nodata is not None:
        gfw_arr[gfw_arr == src_nodata] = np.nan
    gfw_arr[gfw_arr < 0] = np.nan
    presence = np.where(gfw_arr > 0, 1.0, np.nan).astype(np.float32)

    dst = np.full((REF_H, REF_W), np.nan, dtype=np.float32)
    reproject(
        source=presence, destination=dst,
        src_transform=gfw_trans, src_crs=gfw_crs,
        dst_transform=REF_TRANSFORM, dst_crs=DISPLAY_CRS,
        resampling=Resampling.nearest,
        src_nodata=np.nan, dst_nodata=np.nan,
    )
    return dst


def load_sit(date_compact: str):
    """date_compact: 'YYYYMMDD' (매월 15일)"""
    matches = glob.glob(str(SMOS_DIR / f"*{date_compact}*sea_ice_thickness*epsg3995.tif"))
    if not matches:
        return None
    with rasterio.open(matches[0]) as ds:
        arr = ds.read(1).astype(float)
    arr[arr <= 0] = np.nan
    arr[arr > 10] = np.nan
    return arr


def load_sic(date_compact: str):
    """date_compact: 'YYYYMMDD' (매월 15일)"""
    matches = glob.glob(str(SIC_DIR / f"*{date_compact}*epsg3995.tif"))
    if not matches:
        return None
    with rasterio.open(matches[0]) as ds:
        arr = ds.read(1).astype(float)
        src_transform = ds.transform
        src_crs = ds.crs

    dst = np.full((REF_H, REF_W), np.nan, dtype=np.float32)
    reproject(
        source=arr.astype(np.float32), destination=dst,
        src_transform=src_transform, src_crs=src_crs,
        dst_transform=REF_TRANSFORM, dst_crs=DISPLAY_CRS,
        resampling=Resampling.average,
        src_nodata=np.nan, dst_nodata=np.nan,
    )
    dst[(dst < 0) | (dst > 1)] = np.nan
    return dst


# ─────────────────────────────────────────────
# 지도 그리기 헬퍼
# ─────────────────────────────────────────────
WHITE_CMAP = mcolors.ListedColormap(["white"])


def draw_map(ax, data, cmap, vmin, vmax, gfw_presence):
    ax.set_xlim(MAP_XLIM)
    ax.set_ylim(MAP_YLIM)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor("black")

    try:
        ctx.add_basemap(ax, crs=str(DISPLAY_CRS),
                        source=ctx.providers.Esri.WorldImagery,
                        zoom="auto", zorder=1)
    except Exception as e:
        print(f"    배경 로드 실패: {e}")

    im = None
    if data is not None:
        im = ax.imshow(data, cmap=cmap, extent=EXTENT_MPL, origin="upper",
                       vmin=vmin, vmax=vmax, alpha=0.75, zorder=2)

    if gfw_presence is not None:
        ax.imshow(gfw_presence, cmap=WHITE_CMAP, extent=EXTENT_MPL, origin="upper",
                  vmin=0.5, vmax=1.5, alpha=0.9, zorder=3)
    return im


# ─────────────────────────────────────────────
# 처리 대상 월 수집 (GFW 폴더 기준)
# ─────────────────────────────────────────────
all_months = set()
for region in GFW_REGIONS:
    region_dir = GFW_BASE_DIR / region
    if not region_dir.exists():
        continue
    prefix = f"presence_{region}_"
    for d in region_dir.iterdir():
        if d.is_dir() and d.name.startswith(prefix):
            ym = d.name[len(prefix):]
            if len(ym) == 7 and ym[4] == "-":  # YYYY-MM 형식 확인
                all_months.add(ym)

all_months = sorted(all_months)
if not all_months:
    raise RuntimeError("GFW 월 폴더를 찾을 수 없습니다. GFW_BASE_DIR 경로를 확인하세요.")

print(f"\n총 {len(all_months)}개월 처리 예정: {all_months[0]} ~ {all_months[-1]}")


# ─────────────────────────────────────────────
# 월별 PNG 생성
# ─────────────────────────────────────────────
for year_month in all_months:
    print(f"\n{'='*55}")
    print(f"  월: {year_month}")

    date_compact = year_month.replace("-", "") + "15"  # YYYYMM15 (매월 15일 자료)
    out_path = OUT_DIR / f"{year_month.replace('-', '')}.png"

    if out_path.exists():
        print(f"  이미 존재 → 건너뜀")
        continue

    gfw_presence = load_gfw_presence(year_month)
    if gfw_presence is None:
        print("  GFW 없음 → 건너뜀")
        continue

    sit = load_sit(date_compact)
    sic = load_sic(date_compact)

    print(f"  GFW 선박감지: {int(np.nansum(gfw_presence == 1.0)):,}픽셀  "
          f"SIT: {'있음' if sit is not None else '없음'}  "
          f"SIC: {'있음' if sic is not None else '없음'}")

    # ── 레이아웃: 타이틀행 + 지도행 + 컬러바행 ──
    fig = plt.figure(figsize=(22, 13), facecolor="black")
    gs = fig.add_gridspec(
        3, 2,
        height_ratios=[0.7, 20, 1],
        hspace=0.04,
        wspace=0.04,
        left=0.02, right=0.98,
        top=0.96, bottom=0.04,
    )

    ax_title_sic = fig.add_subplot(gs[0, 0])
    ax_title_sit = fig.add_subplot(gs[0, 1])
    ax_sic       = fig.add_subplot(gs[1, 0])
    ax_sit       = fig.add_subplot(gs[1, 1])
    ax_cb_sic    = fig.add_subplot(gs[2, 0])
    ax_cb_sit    = fig.add_subplot(gs[2, 1])

    for ax_t, txt in [(ax_title_sic, "해빙농도 (SIC)"),
                      (ax_title_sit, "해빙두께 (SIT)")]:
        ax_t.axis("off")
        ax_t.set_facecolor("black")
        ax_t.text(0.5, 0.5, txt, color="white", fontsize=14, fontweight="bold",
                  va="center", ha="center", transform=ax_t.transAxes)

    im_sic = draw_map(ax_sic, sic, "turbo",   SIC_VMIN, SIC_VMAX, gfw_presence)
    im_sit = draw_map(ax_sit, sit, "viridis",  SIT_VMIN, SIT_VMAX, gfw_presence)

    fig.text(0.02, 0.975, year_month,
             color="white", fontsize=18, fontweight="bold",
             va="top", ha="left", transform=fig.transFigure)

    if im_sic is not None:
        cb = fig.colorbar(im_sic, cax=ax_cb_sic, orientation="horizontal")
        cb.set_label("해빙농도 (0–1)", color="white", fontsize=10)
        cb.ax.xaxis.set_tick_params(color="white", labelcolor="white", labelsize=8)
        cb.outline.set_edgecolor("white")
    else:
        ax_cb_sic.axis("off")

    if im_sit is not None:
        cb = fig.colorbar(im_sit, cax=ax_cb_sit, orientation="horizontal")
        cb.set_label("해빙두께 (m)", color="white", fontsize=10)
        cb.ax.xaxis.set_tick_params(color="white", labelcolor="white", labelsize=8)
        cb.outline.set_edgecolor("white")
    else:
        ax_cb_sit.axis("off")

    fig.savefig(out_path, dpi=150, bbox_inches=None, facecolor="black")
    plt.close(fig)
    print(f"  저장: {out_path.name}")

print(f"\n완료. 결과 폴더: {OUT_DIR}")
