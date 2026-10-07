"""
OSI-SAF OSI-405-d Sea Ice Drift
북동항로(NSR) 구간 화살표(Quiver) 지도 이미지 출력

- 입력: *_nh_*_epsg3995.tif (변환 완료된 2-band GeoTIFF)
- 출력: *_quiver_NSR.png (NSR 구간 화살표 지도)
- NSR 범위: 경도 20°E ~ 190°E(=170°W), 위도 68°N ~ 82°N

필요 패키지:
    conda activate GFW
    pip install rasterio pyproj numpy matplotlib cartopy
"""

import numpy as np
from pathlib import Path
import rasterio
from rasterio.warp import transform as rio_transform
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from pyproj import Transformer

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
INPUT_DIR  = Path(r"<DATA_ROOT>/14_NSR/OSI_SAF/sea ice drift")
OUTPUT_DIR = INPUT_DIR

# NSR 표시 범위 (지리 좌표)
NSR_LON_MIN =  20.0    # 20°E  (카라 해협 서쪽)
NSR_LON_MAX = 190.0    # 190°E = 170°W (베링 해협 동쪽)
NSR_LAT_MIN =  68.0    # 68°N
NSR_LAT_MAX =  82.0    # 82°N

# 화살표 밀도 조절 (1=전체, 2=1/2, 3=1/3 ...)
# drift는 62.5km 격자라 기본적으로 많지 않음 → 1 권장
QUIVER_STEP = 1

# 화살표 스케일 (작을수록 화살표 길게)
QUIVER_SCALE = 150

# 화살표 색상 기준: 'speed'(속도) 또는 'direction'(방향)
COLOR_BY = "speed"

# ─────────────────────────────────────────────
# TIF → 격자 좌표(lon/lat) + dX/dY 배열 추출
# ─────────────────────────────────────────────
def load_drift_tif(tif_path: Path):
    with rasterio.open(tif_path) as src:
        dx_data = src.read(1).astype(np.float32)   # Band 1: dX (km)
        dy_data = src.read(2).astype(np.float32)   # Band 2: dY (km)
        transform = src.transform
        crs = src.crs
        height, width = dx_data.shape

    # 각 픽셀 중심의 투영 좌표 생성
    cols, rows = np.meshgrid(np.arange(width), np.arange(height))
    xs, ys = rasterio.transform.xy(transform, rows, cols)
    xs = np.array(xs, dtype=np.float64)
    ys = np.array(ys, dtype=np.float64)

    # 투영 좌표 → 경위도 변환
    transformer = Transformer.from_crs(crs.to_epsg(), 4326, always_xy=True)
    lons, lats = transformer.transform(xs.ravel(), ys.ravel())
    lons = lons.reshape(height, width)
    lats = lats.reshape(height, width)

    return lons, lats, dx_data, dy_data


# ─────────────────────────────────────────────
# NSR 범위 마스킹
# ─────────────────────────────────────────────
def mask_to_nsr(lons, lats, dx, dy):
    # 경도를 0~360 범위로 통일해서 NSR 범위 적용
    lons_360 = lons % 360

    mask = (
        (lons_360 >= NSR_LON_MIN) &
        (lons_360 <= NSR_LON_MAX) &
        (lats >= NSR_LAT_MIN) &
        (lats <= NSR_LAT_MAX) &
        np.isfinite(dx) &
        np.isfinite(dy)
    )
    return mask


# ─────────────────────────────────────────────
# Quiver 지도 그리기
# ─────────────────────────────────────────────
def plot_quiver(tif_path: Path):
    out_path = OUTPUT_DIR / (tif_path.stem.replace("_epsg3995", "") + "_quiver_NSR.png")
    print(f"\n{'='*60}")
    print(f"입력: {tif_path.name}")
    print(f"출력: {out_path.name}")

    # ── 데이터 로드 ──
    lons, lats, dx, dy = load_drift_tif(tif_path)
    mask = mask_to_nsr(lons, lats, dx, dy)

    if mask.sum() == 0:
        print("  [경고] NSR 범위 내 유효 데이터 없음. 범위를 확인하세요.")
        return

    # 서브샘플링
    s = QUIVER_STEP
    mask_sub = mask[::s, ::s]
    lons_sub = lons[::s, ::s][mask_sub]
    lats_sub = lats[::s, ::s][mask_sub]
    dx_sub   = dx[::s, ::s][mask_sub]
    dy_sub   = dy[::s, ::s][mask_sub]

    # 속도(크기) 계산
    speed = np.sqrt(dx_sub**2 + dy_sub**2)
    print(f"  유효 벡터 수: {len(lons_sub)}개")
    print(f"  속도 범위: {speed.min():.2f} ~ {speed.max():.2f} km/2days")

    # ── 지도 투영 설정 (PlateCarree로 NSR 구간 표시) ──
    proj = ccrs.LambertConformal(
        central_longitude=100,    # NSR 중앙 경도 (~100°E)
        central_latitude=75,
        standard_parallels=(70, 80),
    )

    fig, ax = plt.subplots(
        figsize=(14, 7),
        subplot_kw={"projection": proj}
    )

    # 지도 범위 설정
    ax.set_extent([20, 195, 65, 83], crs=ccrs.PlateCarree())

    # 배경 지형 피처
    ax.add_feature(cfeature.OCEAN,      facecolor="#d0e8f5", zorder=0)
    ax.add_feature(cfeature.LAND,       facecolor="#e8e0d0", zorder=1)
    ax.add_feature(cfeature.COASTLINE,  linewidth=0.6, edgecolor="gray", zorder=2)
    ax.add_feature(cfeature.BORDERS,    linewidth=0.4, edgecolor="gray",
                   linestyle="--", zorder=2)

    # 격자선
    gl = ax.gridlines(
        crs=ccrs.PlateCarree(),
        draw_labels=True,
        linewidth=0.5,
        color="gray",
        alpha=0.5,
        linestyle="--",
    )
    gl.xlocator = mticker.FixedLocator(range(20, 200, 20))
    gl.ylocator = mticker.FixedLocator(range(65, 85, 5))
    gl.top_labels    = False
    gl.right_labels  = False
    gl.xlabel_style  = {"size": 8}
    gl.ylabel_style  = {"size": 8}

    # ── 화살표 색상 설정 ──
    if COLOR_BY == "speed":
        colors = speed
        cmap   = "plasma"
        clabel = "Drift Speed (km/2days)"
    else:
        direction = np.degrees(np.arctan2(dy_sub, dx_sub)) % 360
        colors = direction
        cmap   = "hsv"
        clabel = "Drift Direction (°)"

    # ── dX/dY → 지도 투영 벡터 변환 ──
    # EPSG:3995 기준 dX=동쪽, dY=북쪽이므로
    # PlateCarree 기준 u(동서), v(남북)로 변환
    # 단순히 PlateCarree에서 quiver로 표시
    q = ax.quiver(
        lons_sub, lats_sub,
        dx_sub,   dy_sub,
        colors,
        cmap      = cmap,
        transform = ccrs.PlateCarree(),
        scale     = QUIVER_SCALE,
        width     = 0.003,
        headwidth = 4,
        headlength= 4,
        alpha     = 0.9,
        zorder    = 3,
    )

    # 컬러바
    cbar = plt.colorbar(q, ax=ax, orientation="vertical",
                        pad=0.02, shrink=0.7, aspect=25)
    cbar.set_label(clabel, fontsize=9)
    cbar.ax.tick_params(labelsize=8)

    # 화살표 범례 (scale key)
    ax.quiverkey(
        q, X=0.88, Y=0.06,
        U=20,
        label="20 km/2days",
        labelpos="E",
        fontproperties={"size": 8},
        coordinates="axes",
    )

    # ── 날짜 추출 (파일명에서) ──
    fname = tif_path.stem
    # 예: ice_drift_nh_polstere-625_multi_202603011200_202603031200
    date_str = ""
    parts = fname.split("_")
    for p in parts:
        if len(p) >= 8 and p[:4].isdigit():
            date_str = p[:8]
            break

    title = f"OSI-SAF Sea Ice Drift — NSR Region"
    if date_str:
        title += f"\n{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    ax.set_title(title, fontsize=12, fontweight="bold", pad=10)

    # 데이터 출처 표기
    ax.text(
        0.01, 0.01,
        "Source: EUMETSAT OSI SAF, OSI-405-d",
        transform=ax.transAxes,
        fontsize=7, color="gray", va="bottom",
    )

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor="white")
    plt.close()
    print(f"  저장 완료: {out_path}")
    return out_path


# ─────────────────────────────────────────────
# 일괄 처리
# ─────────────────────────────────────────────
def main():
    tif_files = sorted(INPUT_DIR.glob("*_nh_*_epsg3995.tif"))

    if not tif_files:
        print(f"[오류] 변환된 TIF 파일 없음: {INPUT_DIR}")
        print("  → osisaf_drift_nc2tif.py 를 먼저 실행하세요.")
        return

    print(f"총 {len(tif_files)}개 TIF 파일 발견")
    success, failed = [], []

    for tif_path in tif_files:
        try:
            plot_quiver(tif_path)
            success.append(tif_path.name)
        except Exception as e:
            import traceback
            print(f"  [실패] {tif_path.name}: {e}")
            traceback.print_exc()
            failed.append(tif_path.name)

    print(f"\n{'='*60}")
    print(f"완료: {len(success)}개 성공 / {len(failed)}개 실패")

if __name__ == "__main__":
    main()
