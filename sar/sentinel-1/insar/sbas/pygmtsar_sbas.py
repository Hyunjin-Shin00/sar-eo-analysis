#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import warnings
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
from shapely.geometry import Point

import matplotlib
matplotlib.use("Agg")  # 터미널에서 PNG 저장용
import matplotlib.pyplot as plt

from pyproj import CRS, datadir

import dask
from dask.distributed import Client

from pygmtsar import S1, Stack, ASF, Tiles, utils

# -----------------------------------------------------------------------------
# 기본 설정
# -----------------------------------------------------------------------------
warnings.filterwarnings("ignore")

# PROJ 설정 (conda 환경 기준으로 자동 설정)
CONDA_PREFIX = Path(os.environ.get("CONDA_PREFIX", ""))
proj_dir = CONDA_PREFIX / "share" / "proj"

os.environ["PROJ_LIB"] = str(proj_dir)
os.environ["PROJ_DATA"] = str(proj_dir)
datadir.set_data_dir(str(proj_dir))

print("PROJ_LIB =", os.environ.get("PROJ_LIB"))
print("pyproj data dir =", datadir.get_data_dir())
print("CRS 3857 =", CRS.from_epsg(3857))

plt.rcParams['figure.figsize'] = [12, 4]
plt.rcParams['figure.dpi'] = 150
plt.rcParams['figure.titlesize'] = 18
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['xtick.labelsize'] = 11
plt.rcParams['ytick.labelsize'] = 11


@contextmanager
def mpl_settings(settings):
    original_settings = {k: plt.rcParams[k] for k in settings}
    plt.rcParams.update(settings)
    try:
        yield
    finally:
        plt.rcParams.update(original_settings)


# -----------------------------------------------------------------------------
# 경로 설정
#   - Windows:  <DATA_ROOT>\07_disaster\landslide\pakistan2
#   - WSL   :  <DATA_ROOT>/07_disaster/landslide/pakistan2
# -----------------------------------------------------------------------------
BASE_DIR = Path("<DATA_ROOT>/07_disaster/landslide/pakistan2")

# 만약 이 스크립트를 WSL 안으로 복사해서 사용할 거면, 아래처럼 바꿔도 됨:
# BASE_DIR = Path(__file__).resolve().parent

WORKDIR = BASE_DIR / "work"
DATADIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

WORKDIR.mkdir(parents=True, exist_ok=True)
DATADIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEM = DATADIR / "dem.nc"


def save_fig(name: str):
    """현재 figure를 OUTPUT_DIR/name.png 로 저장"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{name}.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved figure: {out_path}")


# -----------------------------------------------------------------------------
# Sentinel-1 세팅
# -----------------------------------------------------------------------------
ORBIT = "A"
SUBSWATH = 1
REFERENCE = "2023-11-25"  # 필요하면 다른 날짜로 변경

BURSTS_STR = """
S1_056059_IW1_20241225T125751_VV_B697-BURST
S1_056059_IW1_20241213T125752_VV_E894-BURST
S1_056059_IW1_20241119T125754_VV_F13D-BURST
S1_056059_IW1_20241107T125754_VV_3B7D-BURST
S1_056059_IW1_20241026T125754_VV_7246-BURST
S1_056059_IW1_20241014T125755_VV_806E-BURST
S1_056059_IW1_20241002T125754_VV_8DD1-BURST
S1_056059_IW1_20240920T125754_VV_003E-BURST
S1_056059_IW1_20240908T125754_VV_0797-BURST
S1_056059_IW1_20240827T125754_VV_9704-BURST
S1_056059_IW1_20240815T125753_VV_CBAD-BURST
S1_056059_IW1_20240803T125753_VV_69D0-BURST
S1_056059_IW1_20240722T125753_VV_C34D-BURST
S1_056059_IW1_20240710T125754_VV_B455-BURST
S1_056059_IW1_20240616T125755_VV_97E5-BURST
S1_056059_IW1_20240604T125755_VV_A707-BURST
S1_056059_IW1_20240523T125755_VV_F7BD-BURST
S1_056059_IW1_20240511T125756_VV_9D2B-BURST
S1_056059_IW1_20240429T125756_VV_761F-BURST
S1_056059_IW1_20240417T125755_VV_97E3-BURST
S1_056059_IW1_20240405T125755_VV_1B3E-BURST
S1_056059_IW1_20240324T125755_VV_6574-BURST
S1_056059_IW1_20240312T125754_VV_F4BA-BURST
S1_056059_IW1_20240229T125754_VV_7F4A-BURST
S1_056059_IW1_20240217T125754_VV_9D08-BURST
S1_056059_IW1_20240205T125754_VV_A7FF-BURST
S1_056059_IW1_20240124T125755_VV_1035-BURST
S1_056059_IW1_20240112T125755_VV_42DF-BURST
S1_056059_IW1_20231231T125756_VV_F82C-BURST
S1_056059_IW1_20231219T125756_VV_9F68-BURST
S1_056059_IW1_20231207T125757_VV_2733-BURST
S1_056059_IW1_20231125T125757_VV_F503-BURST
S1_056059_IW1_20231113T125758_VV_2161-BURST
S1_056059_IW1_20231101T125758_VV_30B8-BURST
S1_056059_IW1_20231020T125759_VV_AFC8-BURST
S1_056059_IW1_20231008T125758_VV_68E7-BURST
S1_056059_IW1_20230926T125758_VV_C922-BURST
S1_056059_IW1_20230914T125758_VV_756D-BURST
S1_056059_IW1_20230902T125758_VV_EAA9-BURST
S1_056059_IW1_20230821T125757_VV_A07B-BURST
S1_056059_IW1_20230809T125756_VV_27C3-BURST
S1_056059_IW1_20230728T125756_VV_F143-BURST
S1_056059_IW1_20230716T125755_VV_DF91-BURST
S1_056059_IW1_20230704T125754_VV_8E61-BURST
S1_056059_IW1_20230622T125753_VV_90EF-BURST
S1_056059_IW1_20230610T125753_VV_0EE8-BURST
S1_056059_IW1_20230529T125752_VV_9B31-BURST
S1_056059_IW1_20230517T125752_VV_2180-BURST
S1_056059_IW1_20230505T125751_VV_A857-BURST
S1_056059_IW1_20230423T125750_VV_C287-BURST
S1_056059_IW1_20230411T125750_VV_E8A7-BURST
S1_056059_IW1_20230330T125749_VV_E87F-BURST
S1_056059_IW1_20230318T125749_VV_31FB-BURST
S1_056059_IW1_20230306T125749_VV_865F-BURST
S1_056059_IW1_20230222T125749_VV_9D10-BURST
S1_056059_IW1_20230210T125749_VV_4959-BURST
S1_056059_IW1_20230129T125750_VV_321E-BURST
S1_056059_IW1_20230117T125750_VV_EA61-BURST
S1_056059_IW1_20230105T125751_VV_7071-BURST
"""
BURSTS = list(filter(None, BURSTS_STR.split("\n")))
print(f"Bursts defined: {len(BURSTS)}")


# -----------------------------------------------------------------------------
# 여러 POI + 첫 번째 포인트 기준 AOI 생성
# -----------------------------------------------------------------------------
POI_COORDS = [
    (74.699861, 36.274522),    # POI 1 (AOI 중심)
    (74.7181389, 36.2629722),  # POI 2 (예시)
    # 계속 (lon, lat) 추가 가능
]

POI = gpd.GeoDataFrame(
    geometry=[Point(lon, lat) for lon, lat in POI_COORDS],
    crs="EPSG:4326"
)

BUFFER_DEG = 0.08  # degree 단위 버퍼 (AOI 크기)
center_point = POI.geometry.iloc[0]
AOI = gpd.GeoDataFrame(
    geometry=[center_point.buffer(BUFFER_DEG)],
    crs=POI.crs
)

# -----------------------------------------------------------------------------
# ASF 다운로드
# -----------------------------------------------------------------------------
# ※ 실제 실행 시에는 본인 계정/비밀번호 맞는지 확인 필요
asf_username = os.environ.get("EARTHDATA_USER", "")
asf_password = os.environ.get("EARTHDATA_PASS", "")

asf = ASF(asf_username, asf_password)
print("ASF Downloading Sentinel-1 SLC Bursts...")
print(asf.download(DATADIR, BURSTS))

# 오빗 파일 다운로드
S1.download_orbits(DATADIR, S1.scan_slc(DATADIR))

# -----------------------------------------------------------------------------
# DEM 다운로드
# -----------------------------------------------------------------------------
dem_tiles = Tiles().download_dem(AOI, filename=str(DEM))
dem_tiles.plot.imshow(cmap="cividis")
plt.title("DEM Tiles")
save_fig("00_dem_tiles")

# -----------------------------------------------------------------------------
# Dask 클라이언트 (쓰레드 기반, nanny 문제 방지)
# -----------------------------------------------------------------------------
try:
    client.close()
except Exception:
    pass

dask.config.set(scheduler="threads")
client = Client(processes=False, threads_per_worker=4)
print(client)

# -----------------------------------------------------------------------------
# SBAS 스택 구축
# -----------------------------------------------------------------------------
scenes = S1.scan_slc(DATADIR)
print("Scenes:")
print(scenes)

sbas = (
    Stack(str(WORKDIR), drop_if_exists=True)
    .set_scenes(scenes)
    .set_reference(REFERENCE)
)
df_scenes = sbas.to_dataframe()
print(df_scenes)

# plot_scenes는 에러가 자주 나서 try/except로 감쌈
try:
    sbas.plot_scenes(AOI=AOI)
    save_fig("01_scenes")
except Exception as e:
    print("WARNING: sbas.plot_scenes(AOI=AOI) failed, skip plot. Error:", repr(e))
    plt.close("all")

# AOI 기준 리프레임
sbas.compute_reframe(AOI)

try:
    sbas.plot_scenes(AOI=AOI)
    save_fig("02_scenes_reframed")
except Exception as e:
    print("WARNING: sbas.plot_scenes(AOI=AOI) after reframe failed, skip plot. Error:", repr(e))
    plt.close("all")

# DEM 로드
sbas.load_dem(str(DEM), AOI)

try:
    sbas.plot_scenes(AOI=AOI)
    save_fig("03_scenes_with_dem")
except Exception as e:
    print("WARNING: sbas.plot_scenes(AOI=AOI) with DEM failed, skip plot. Error:", repr(e))
    plt.close("all")

# 정렬
sbas.compute_align()

# 지오코딩 (원래 해상도 1 pixel spacing)
sbas.compute_geocode(1)

sbas.plot_topo(quantile=[0.01, 0.99])
save_fig("04_topography")

# -----------------------------------------------------------------------------
# PS 함수 계산 및 Landmask 생성
# -----------------------------------------------------------------------------
sbas.compute_ps()

sbas.plot_psfunction(quantile=[0.01, 0.90])
save_fig("05_ps_function")

psfunc = sbas.psfunction()
psmask_sbas = sbas.multilooking(psfunc, coarsen=(1, 4), wavelength=100) > 0.45
topo_sbas = sbas.get_topo().interp_like(psmask_sbas, method="nearest")

landmask_sbas = psmask_sbas & (np.isfinite(topo_sbas))
landmask_sbas = utils.binary_opening(landmask_sbas, structure=np.ones((20, 20)))
landmask_sbas = np.isfinite(sbas.conncomp_main(landmask_sbas))
landmask_sbas = utils.binary_closing(landmask_sbas, structure=np.ones((20, 20)))
landmask_sbas = np.isfinite(psmask_sbas.where(landmask_sbas))

sbas.plot_landmask(landmask_sbas)
save_fig("06_landmask")

# -----------------------------------------------------------------------------
# SBAS 인터페로그램 생성
# -----------------------------------------------------------------------------
baseline_pairs = sbas.sbas_pairs(days=60)
print(baseline_pairs)

with mpl_settings({'figure.dpi': 300}):
    sbas.plot_baseline(baseline_pairs)
    save_fig("07_baseline_all")

# 멀티룩 인터페로그램
sbas.compute_interferogram_multilook(
    baseline_pairs,
    "intf_mlook",
    wavelength=200,
    psize=32,
    weight=psfunc,
)

ds_sbas = sbas.open_stack("intf_mlook")
ds_sbas = ds_sbas.where(landmask_sbas)

intf_sbas = ds_sbas.phase
corr_sbas = ds_sbas.correlation
print(corr_sbas)

sbas.plot_interferograms(intf_sbas[:8], caption="SBAS Phase, [rad]")
save_fig("08_intf_sbas_phase_first8")

sbas.plot_correlations(corr_sbas[:8], caption="SBAS Correlation")
save_fig("09_intf_sbas_corr_first8")

baseline_pairs["corr"] = corr_sbas.mean(["y", "x"])
print(len(baseline_pairs), baseline_pairs)

pairs_best = sbas.sbas_pairs_covering_correlation(baseline_pairs, 2)
print(len(pairs_best), pairs_best)

with mpl_settings({'figure.dpi': 300}):
    sbas.plot_baseline(pairs_best)
    save_fig("10_baseline_best_pairs")

sbas.plot_baseline_correlation(baseline_pairs, pairs_best)
save_fig("11_baseline_corr")

sbas.plot_baseline_duration(baseline_pairs, column="corr", ascending=False)
save_fig("12_baseline_duration_all")

sbas.plot_baseline_duration(pairs_best, column="corr", ascending=False)
save_fig("13_baseline_duration_best")

intf_sbas = intf_sbas.sel(pair=pairs_best.pair.values)
corr_sbas = corr_sbas.sel(pair=pairs_best.pair.values)

sbas.plot_interferograms(intf_sbas[:8], caption="SBAS Phase (best), [rad]")
save_fig("14_intf_sbas_phase_best_first8")

sbas.plot_correlations(corr_sbas[:8], caption="SBAS Correlation (best)")
save_fig("15_intf_sbas_corr_best_first8")

# 스택 코히런스
corr_sbas_stack = corr_sbas.mean("pair")
corr_sbas_stack = sbas.sync_cube(corr_sbas_stack, "corr_sbas_stack")

CORRLIMIT = 0.35
sbas.plot_correlation_stack(corr_sbas_stack, CORRLIMIT, caption="SBAS Stack Correlation")
save_fig("16_corr_stack")

sbas.plot_interferograms(
    intf_sbas[:8].where(corr_sbas_stack > CORRLIMIT),
    caption="SBAS Phase (stack mask), [rad]",
)
save_fig("17_intf_sbas_phase_masked_first8")

# -----------------------------------------------------------------------------
# 언래핑 (2D) - SNAPHU
#   ※ 여기서 snaphu 실행 파일이 PATH에 있어야 함 (which snaphu 로 확인 가능)
# -----------------------------------------------------------------------------
unwrap_sbas = sbas.unwrap_snaphu(
    intf_sbas.where(corr_sbas_stack > CORRLIMIT),
    corr_sbas,
    conncomp=True,
)
unwrap_sbas = sbas.sync_cube(unwrap_sbas, "unwrap_sbas")

sbas.plot_phases(
    (unwrap_sbas.phase - unwrap_sbas.phase.mean(["y", "x"]))[:8],
    caption="SBAS Phase Unwrapped, [rad]",
)
save_fig("18_unwrap_sbas_first8")

# 메인 컴포넌트 선택
unwrap_sbas = sbas.conncomp_main(unwrap_sbas, 1)

sbas.plot_phases(
    (unwrap_sbas.phase - unwrap_sbas.phase.mean(["y", "x"]))[:8],
    caption="SBAS Phase Unwrapped (main comp), [rad]",
)
save_fig("19_unwrap_sbas_main_first8")

# -----------------------------------------------------------------------------
# 트렌드 제거 및 변위 계산
# -----------------------------------------------------------------------------
decimator_sbas = sbas.decimator(resolution=15, grid=(1, 1))
topo = decimator_sbas(sbas.get_topo())
yy, xx = xr.broadcast(topo.y, topo.x)

trend_sbas = sbas.regression(
    unwrap_sbas.phase,
    [
        topo,
        topo * yy,
        topo * xx,
        topo * yy * xx,
        topo ** 2,
        topo ** 2 * yy,
        topo ** 2 * xx,
        topo ** 2 * yy * xx,
        yy,
        xx,
        yy * xx,
    ],
    corr_sbas,
)
trend_sbas = sbas.sync_cube(trend_sbas, "trend_sbas")

sbas.plot_phases(
    trend_sbas[:8],
    caption="SBAS Trend Phase, [rad]",
    quantile=[0.01, 0.99],
)
save_fig("20_trend_sbas_first8")

sbas.plot_phases(
    (unwrap_sbas.phase - trend_sbas)[:8],
    caption="SBAS Phase - Trend, [rad]",
    vmin=-np.pi,
    vmax=np.pi,
)
save_fig("21_sbas_phase_minus_trend_first8")

disp_sbas = sbas.los_displacement_mm(
    sbas.lstsq(unwrap_sbas.phase - trend_sbas, corr_sbas)
)
disp_sbas = sbas.sync_cube(disp_sbas, "disp_sbas")

sbas.plot_displacements(
    disp_sbas[::3],
    caption="SBAS Cumulative LOS Displacement, [mm]",
    quantile=[0.01, 0.99],
    symmetrical=True,
)
save_fig("22_disp_sbas")

velocity_sbas = sbas.velocity(disp_sbas)
velocity_sbas = sbas.sync_cube(velocity_sbas, "velocity_sbas")

# 속도 맵 플롯 (AOI, POI 오버레이)
with mpl_settings({'figure.dpi': 300}):
    fig = plt.figure(figsize=(12, 4))
    zmin, zmax = np.nanquantile(velocity_sbas, [0.01, 0.99])
    zminmax = max(abs(zmin), zmax)

    ax = fig.add_subplot(1, 2, 1)
    velocity_sbas.plot.imshow(cmap="turbo", vmin=-zminmax, vmax=zminmax, ax=ax)
    sbas.geocode(AOI.boundary).plot(ax=ax)
    sbas.geocode(POI).plot(ax=ax, marker="x", c="r", markersize=50, label="POI")
    ax.set_aspect("auto")
    ax.set_title("SBAS Velocity, mm/year")

    ax = fig.add_subplot(1, 2, 2)
    sbas.as_geo(sbas.ra2ll(velocity_sbas)).rio.clip(AOI.geometry) \
        .plot.imshow(cmap="turbo", vmin=-zminmax, vmax=zminmax, ax=ax)
    AOI.boundary.plot(ax=ax)
    POI.plot(ax=ax, marker="x", c="r", markersize=50, label="POI")
    ax.legend(loc="upper left")
    ax.set_title("SBAS Velocity (clipped), mm/year")

    plt.suptitle("SBAS LOS Velocity", fontsize=18)
    plt.tight_layout()
    save_fig("23_velocity_sbas")

# -----------------------------------------------------------------------------
# SBAS 시계열 (여러 POI)
# -----------------------------------------------------------------------------
for i, geom in enumerate(sbas.geocode(POI).geometry):
    x, y = geom.x, geom.y
    disp_pixel = disp_sbas.sel(y=y, x=x, method="nearest")
    stl_pixel = sbas.stl(
        disp_sbas.sel(y=[y], x=[x], method="nearest")
    ).isel(x=0, y=0)

    plt.figure(figsize=(12, 4), dpi=300)
    plt.plot(disp_pixel.date, disp_pixel, c="r", lw=2, label=f"Displacement POI {i+1}")
    plt.plot(stl_pixel.date, stl_pixel.trend, c="r", ls="--", lw=2, label="Trend")
    plt.plot(stl_pixel.date, stl_pixel.seasonal, c="r", lw=1, label="Seasonal")
    plt.legend(loc="upper left")
    plt.title(f"SBAS LOS Displacement STL (POI {i+1})", fontsize=16)
    plt.ylabel("Displacement, mm", fontsize=14)
    save_fig(f"24_disp_sbas_stl_poi{i+1}")

# -----------------------------------------------------------------------------
# PS 기반 처리
# -----------------------------------------------------------------------------
stability = sbas.psfunction()
landmask_ps = landmask_sbas.astype(int).interp_like(
    stability, method="nearest"
).astype(bool)

sbas.compute_interferogram_singlelook(
    pairs_best,
    "intf_slook",
    wavelength=60,
    weight=stability.where(landmask_ps),
    phase=trend_sbas,
)

ds_ps = sbas.open_stack("intf_slook")
intf_ps = ds_ps.phase
corr_ps = ds_ps.correlation

sbas.plot_interferograms(intf_ps[:8], caption="PS Phase, [rad]")
save_fig("25_intf_ps_phase_first8")

sbas.plot_correlations(corr_ps[:8], caption="PS Correlation")
save_fig("26_intf_ps_corr_first8")

disp_ps_pairs = sbas.los_displacement_mm(sbas.unwrap1d(intf_ps))
disp_ps_pairs = sbas.sync_cube(disp_ps_pairs, "disp_ps_pairs")

disp_ps = sbas.lstsq(disp_ps_pairs, corr_ps)
disp_ps = sbas.sync_cube(disp_ps, "disp_ps")

sbas.plot_displacements(
    disp_ps[::3],
    caption="PS Cumulative LOS Displacement, [mm]",
    quantile=[0.01, 0.99],
    symmetrical=True,
)
save_fig("27_disp_ps")

velocity_ps = sbas.velocity(disp_ps)
velocity_ps = sbas.sync_cube(velocity_ps, "velocity_ps")

with mpl_settings({'figure.dpi': 300}):
    fig = plt.figure(figsize=(12, 4))
    zmin, zmax = np.nanquantile(velocity_ps, [0.01, 0.99])
    zminmax = max(abs(zmin), zmax)

    ax = fig.add_subplot(1, 2, 1)
    velocity_ps.plot.imshow(cmap="turbo", vmin=-zminmax, vmax=zminmax, ax=ax)
    sbas.geocode(AOI.boundary).plot(ax=ax)
    sbas.geocode(POI).plot(ax=ax, marker="x", c="r", markersize=50, label="POI")
    ax.set_aspect("auto")
    ax.set_title("PS Velocity, mm/year")

    ax = fig.add_subplot(1, 2, 2)
    sbas.as_geo(sbas.ra2ll(velocity_ps)).rio.clip(AOI.geometry) \
        .plot.imshow(cmap="turbo", vmin=-zminmax, vmax=zminmax, ax=ax)
    AOI.boundary.plot(ax=ax)
    POI.plot(ax=ax, marker="x", c="r", markersize=50, label="POI")
    ax.legend(loc="upper left")
    ax.set_title("PS Velocity (clipped), mm/year")

    plt.suptitle("PS LOS Velocity", fontsize=18)
    plt.tight_layout()
    save_fig("28_velocity_ps")

# PS 시계열 (여러 POI)
for i, geom in enumerate(sbas.geocode(POI).geometry):
    x, y = geom.x, geom.y
    disp_pixel = disp_ps.sel(y=y, x=x, method="nearest")
    stl_pixel = sbas.stl(
        disp_ps.sel(y=[y], x=[x], method="nearest")
    ).isel(x=0, y=0)

    plt.figure(figsize=(12, 4), dpi=300)
    plt.plot(disp_pixel.date, disp_pixel, c="r", lw=2, label=f"Displacement POI {i+1}")
    plt.plot(stl_pixel.date, stl_pixel.trend, c="r", ls="--", lw=2, label="Trend")
    plt.plot(stl_pixel.date, stl_pixel.seasonal, c="r", lw=1, label="Seasonal")
    plt.legend(loc="upper left")
    plt.title(f"PS LOS Displacement STL (POI {i+1})", fontsize=16)
    plt.ylabel("Displacement, mm", fontsize=14)
    save_fig(f"29_disp_ps_stl_poi{i+1}")

# baseline-displacement plot (여러 POI)
for i, geom in enumerate(sbas.geocode(POI).geometry):
    x, y = geom.x, geom.y
    disp_norm = disp_ps_pairs.sel(y=y, x=x, method="nearest") / sbas.los_displacement_mm(1)
    corr_norm = corr_ps.sel(y=y, x=x, method="nearest")

    sbas.plot_baseline_displacement_los_mm(
        disp_norm,
        corr_norm,
        caption=f"POI {i+1}",
        stl=True,
    )
    save_fig(f"30_baseline_disp_ps_poi{i+1}")

# -----------------------------------------------------------------------------
# RMSE 및 비교
# -----------------------------------------------------------------------------
rmse_ps = sbas.rmse(disp_ps_pairs, disp_ps, corr_ps)
rmse_ps = sbas.sync_cube(rmse_ps, "rmse_ps")

sbas.plot_rmse(rmse_ps, caption="RMSE Correlation Aware, [mm]")
save_fig("31_rmse_ps")

# SBAS vs PS 속도 산점도 (AOI 클립)
points_sbas = sbas.as_geo(sbas.ra2ll(velocity_sbas)).rio.clip(AOI.geometry)
points_ps = sbas.as_geo(sbas.ra2ll(velocity_ps)).rio.clip(AOI.geometry)
points_ps_interp = points_ps.interp_like(points_sbas, method="nearest").values.ravel()
points_sbas_vals = points_sbas.values.ravel()
nanmask = np.isnan(points_sbas_vals) | np.isnan(points_ps_interp)

points_sbas_vals = points_sbas_vals[~nanmask]
points_ps_interp = points_ps_interp[~nanmask]

plt.figure(figsize=(12, 4), dpi=300)
plt.scatter(points_sbas_vals, points_ps_interp, c="silver", alpha=1, s=1)
plt.scatter(points_sbas_vals, points_ps_interp, c="b", alpha=0.1, s=1)
plt.scatter(points_sbas_vals, points_ps_interp, c="g", alpha=0.1, s=0.1)
plt.scatter(points_sbas_vals, points_ps_interp, c="y", alpha=0.1, s=0.01)

max_value = max(np.nanmax(points_sbas_vals), np.nanmax(points_ps_interp))
min_value = min(np.nanmin(points_sbas_vals), np.nanmin(points_ps_interp))
plt.plot([min_value, max_value], [min_value, max_value], "k--")

plt.xlabel("Velocity SBAS, mm/year", fontsize=16)
plt.ylabel("Velocity PS, mm/year", fontsize=16)
plt.title("Cross-Comparison between SBAS and PS Velocity", fontsize=18)
plt.grid(True)
save_fig("32_sbas_vs_ps_scatter")

# -----------------------------------------------------------------------------
# GeoTIFF 저장 (SBAS/PS Velocity, RMSE)
# -----------------------------------------------------------------------------
vel_sbas_ll = sbas.ra2ll(velocity_sbas)
vel_sbas_ll = sbas.as_geo(vel_sbas_ll).rio.clip(AOI.geometry)
sbas_tif = OUTPUT_DIR / "velocity_sbas_los_mm_per_year.tif"
vel_sbas_ll.rio.to_raster(sbas_tif)
print("Saved SBAS velocity:", sbas_tif)

vel_ps_ll = sbas.ra2ll(velocity_ps)
vel_ps_ll = sbas.as_geo(vel_ps_ll).rio.clip(AOI.geometry)
ps_tif = OUTPUT_DIR / "velocity_ps_los_mm_per_year.tif"
vel_ps_ll.rio.to_raster(ps_tif)
print("Saved PS velocity:", ps_tif)

rmse_ll = sbas.ra2ll(rmse_ps)
rmse_ll = sbas.as_geo(rmse_ll).rio.clip(AOI.geometry)
rmse_tif = OUTPUT_DIR / "rmse_ps_los_mm.tif"
rmse_ll.rio.to_raster(rmse_tif)
print("Saved PS RMSE:", rmse_tif)

print("DONE.")
