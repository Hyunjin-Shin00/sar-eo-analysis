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

# -------------------------------------------------------------------------
# 기본 설정
# -------------------------------------------------------------------------
warnings.filterwarnings("ignore")

os.environ["PROJ_LIB"] = os.path.join(os.environ.get("CONDA_PREFIX", ""), "share", "proj")
os.environ["PROJ_DATA"] = os.path.join(os.environ.get("CONDA_PREFIX", ""), "share", "proj")
datadir.set_data_dir(os.path.join(os.environ.get("CONDA_PREFIX", ""), "share", "proj"))

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


# -------------------------------------------------------------------------
# 경로 설정 및 유틸
# -------------------------------------------------------------------------
BASE_DIR   = Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>")) / "landslide/Gyeongju"
WORKDIR    = BASE_DIR / "work"
DATADIR    = BASE_DIR / "data"
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


def fig_exists(name: str) -> bool:
    return (OUTPUT_DIR / f"{name}.png").exists()


def ensure_dataarray(obj: xr.Dataset | xr.DataArray) -> xr.DataArray:
    """open_stack 결과가 Dataset이든 DataArray든 항상 DataArray로 통일"""
    if isinstance(obj, xr.DataArray):
        return obj
    elif isinstance(obj, xr.Dataset):
        if len(obj.data_vars) == 0:
            raise ValueError("Dataset has no data variables.")
        return next(iter(obj.data_vars.values()))
    else:
        raise TypeError(f"Unsupported type: {type(obj)}")


# -------------------------------------------------------------------------
# Sentinel-1 세팅
# -------------------------------------------------------------------------
ORBIT     = "A"
SUBSWATH  = 2
REFERENCE = "2022-07-23" 

BURSTS_STR = """

S1_114049_IW2_20221226T092344_VV_2DB6-BURST
S1_114049_IW2_20221214T092345_VV_47B8-BURST
S1_114049_IW2_20221202T092346_VV_38D4-BURST
S1_114049_IW2_20221120T092346_VV_E3BD-BURST
S1_114049_IW2_20221108T092346_VV_9483-BURST
S1_114049_IW2_20221027T092347_VV_FB5B-BURST
S1_114049_IW2_20221015T092347_VV_4626-BURST
S1_114049_IW2_20221003T092347_VV_5EA0-BURST
S1_114049_IW2_20220921T092345_VV_9162-BURST
S1_114049_IW2_20220909T092346_VV_6724-BURST
S1_114049_IW2_20220828T092345_VV_C566-BURST
S1_114049_IW2_20220816T092345_VV_DA73-BURST
S1_114049_IW2_20220804T092344_VV_7D14-BURST
S1_114049_IW2_20220723T092344_VV_9B8F-BURST
S1_114049_IW2_20220711T092343_VV_9583-BURST
S1_114049_IW2_20220629T092342_VV_13D8-BURST
S1_114049_IW2_20220617T092341_VV_0410-BURST
S1_114049_IW2_20220605T092341_VV_6F3A-BURST
S1_114049_IW2_20220430T092338_VV_C28A-BURST
S1_114049_IW2_20220418T092337_VV_3CC6-BURST
S1_114049_IW2_20220406T092337_VV_7D6A-BURST
S1_114049_IW2_20220325T092337_VV_B877-BURST
S1_114049_IW2_20220313T092337_VV_1F14-BURST
S1_114049_IW2_20220301T092336_VV_E653-BURST
S1_114049_IW2_20220217T092337_VV_DC5C-BURST
S1_114049_IW2_20220205T092337_VV_88FB-BURST
S1_114049_IW2_20220124T092337_VV_9EAB-BURST
S1_114049_IW2_20220112T092338_VV_CAF5-BURST
"""
BURSTS = list(filter(None, BURSTS_STR.split("\n")))
print(f"Bursts defined: {len(BURSTS)}")

# -------------------------------------------------------------------------
# AOI / POI
# -------------------------------------------------------------------------
POI_COORDS = [
    (129.35909,35.83185),
    (129.394270,35.829364)    # POI 1 (AOI 중심)

]

POI = gpd.GeoDataFrame(
    geometry=[Point(lon, lat) for lon, lat in POI_COORDS],
    crs="EPSG:4326"
)

BUFFER_DEG = 0.08
center_point = POI.geometry.iloc[0]
AOI = gpd.GeoDataFrame(geometry=[center_point.buffer(BUFFER_DEG)], crs=POI.crs)

# -------------------------------------------------------------------------
# ASF 다운로드 / DEM 다운로드 (이미 있으면 스킵)
# -------------------------------------------------------------------------
if not DEM.exists():
    print("DEM not found. Downloading ASF data + DEM...")
    asf = ASF(os.environ.get("EARTHDATA_USERNAME", ""), os.environ.get("EARTHDATA_PASSWORD", ""))
    print("ASF Downloading Sentinel-1 SLC Bursts...")
    print(asf.download(DATADIR, BURSTS))

    S1.download_orbits(DATADIR, S1.scan_slc(DATADIR))

    dem_tiles = Tiles().download_dem(AOI, filename=str(DEM))
    if not fig_exists("01_dem_tiles"):
        dem_tiles.plot.imshow(cmap="cividis")
        plt.title("DEM Tiles")
        save_fig("01_dem_tiles")
else:
    print("DEM exists, skip DEM download.")

# -------------------------------------------------------------------------
# Dask 클라이언트
# -------------------------------------------------------------------------
try:
    client.close()
except Exception:
    pass

dask.config.set(scheduler="threads")
client = Client(processes=False, threads_per_worker=4)
print(client)

# -------------------------------------------------------------------------
# SBAS 스택 구축 (기존 work 재사용)
# -------------------------------------------------------------------------
scenes = S1.scan_slc(DATADIR)
print("Scenes:")
print(scenes)

sbas = Stack(str(WORKDIR), drop_if_exists=True).set_scenes(scenes).set_reference(REFERENCE)
df_scenes = sbas.to_dataframe()
print(df_scenes)

# plot_scenes (디버그용) - 그림 있으면 스킵
if not fig_exists("debug_01_scenes"):
    try:
        sbas.plot_scenes(AOI=AOI)
        save_fig("debug_01_scenes")
    except Exception as e:
        print("WARNING: sbas.plot_scenes(AOI=AOI) failed, skip plot. Error:", repr(e))
        plt.close("all")

# -------------------------------------------------------------------------
# AOI 리프레임 / DEM 로드 / 정렬 / 지오코딩
# (이 부분은 비교적 가벼우니 항상 호출, 내부에서 캐시 재사용)
# -------------------------------------------------------------------------
sbas.compute_reframe(AOI)
if not fig_exists("debug_02_scenes_reframed"):
    try:
        sbas.plot_scenes(AOI=AOI)
        save_fig("debug_02_scenes_reframed")
    except Exception as e:
        print("WARNING: sbas.plot_scenes(AOI=AOI) after reframe failed, skip plot. Error:", repr(e))
        plt.close("all")

sbas.load_dem(str(DEM), AOI)
if not fig_exists("debug_03_scenes_with_dem"):
    try:
        sbas.plot_scenes(AOI=AOI)
        save_fig("debug_03_scenes_with_dem")
    except Exception as e:
        print("WARNING: sbas.plot_scenes(AOI=AOI) with DEM failed, skip plot. Error:", repr(e))
        plt.close("all")

sbas.compute_align()
sbas.compute_geocode(1)

if not fig_exists("02_topography"):
    sbas.plot_topo(quantile=[0.01, 0.99])
    save_fig("02_topography")

# -------------------------------------------------------------------------
# PS 함수 / landmask_sbas
# -------------------------------------------------------------------------
try:
    psfunc = sbas.psfunction()
    print("psfunction already exists.")
except Exception:
    print("Computing psfunction...")
    sbas.compute_ps()
    psfunc = sbas.psfunction()

if not fig_exists("03_ps_function"):
    sbas.plot_psfunction(quantile=[0.01, 0.90])
    save_fig("03_ps_function")

psmask_sbas = sbas.multilooking(psfunc, coarsen=(1, 4), wavelength=100) > 0.45
topo_sbas = sbas.get_topo().interp_like(psmask_sbas, method="nearest")

landmask_sbas = psmask_sbas & (np.isfinite(topo_sbas))
landmask_sbas = utils.binary_opening(landmask_sbas, structure=np.ones((20, 20)))
landmask_sbas = np.isfinite(sbas.conncomp_main(landmask_sbas))
landmask_sbas = utils.binary_closing(landmask_sbas, structure=np.ones((20, 20)))
landmask_sbas = np.isfinite(psmask_sbas.where(landmask_sbas))

if not fig_exists("04_landmask"):
    sbas.plot_landmask(landmask_sbas)
    save_fig("04_landmask")

# -------------------------------------------------------------------------
# SBAS 인터페로그램 (intf_mlook)
# -------------------------------------------------------------------------
try:
    ds_sbas = sbas.open_stack("intf_mlook")
    print("intf_mlook already exists, open_stack.")
except Exception:
    baseline_pairs = sbas.sbas_pairs(days=60)
    print(baseline_pairs)

    if not fig_exists("05_baseline_all"):
        with mpl_settings({'figure.dpi': 300}):
            sbas.plot_baseline(baseline_pairs)
            save_fig("05_baseline_all")

    print("Computing intf_mlook...")
    sbas.compute_interferogram_multilook(
        baseline_pairs,
        "intf_mlook",
        wavelength=200,
        psize=32,
        weight=psfunc
    )
    ds_sbas = sbas.open_stack("intf_mlook")

# baseline_pairs는 이후에도 필요하니, 없으면 다시 계산
if 'baseline_pairs' not in locals():
    baseline_pairs = sbas.sbas_pairs(days=60)

ds_sbas = ds_sbas.where(landmask_sbas)
intf_sbas = ds_sbas.phase
corr_sbas = ds_sbas.correlation
print(corr_sbas)

if not fig_exists("06_intf_sbas_phase_first8"):
    sbas.plot_interferograms(intf_sbas[:8], caption="SBAS Phase, [rad]")
    save_fig("06_intf_sbas_phase_first8")

if not fig_exists("07_intf_sbas_corr_first8"):
    sbas.plot_correlations(corr_sbas[:8], caption="SBAS Correlation")
    save_fig("07_intf_sbas_corr_first8")

baseline_pairs["corr"] = corr_sbas.mean(["y", "x"])
print(len(baseline_pairs), baseline_pairs)

pairs_best = sbas.sbas_pairs_covering_correlation(baseline_pairs, 2)
print(len(pairs_best), pairs_best)

if not fig_exists("08_baseline_best_pairs"):
    with mpl_settings({'figure.dpi': 300}):
        sbas.plot_baseline(pairs_best)
        save_fig("08_baseline_best_pairs")

if not fig_exists("09_baseline_corr"):
    sbas.plot_baseline_correlation(baseline_pairs, pairs_best)
    save_fig("09_baseline_corr")

if not fig_exists("10_baseline_duration_all"):
    sbas.plot_baseline_duration(baseline_pairs, column="corr", ascending=False)
    save_fig("10_baseline_duration_all")

if not fig_exists("11_baseline_duration_best"):
    sbas.plot_baseline_duration(pairs_best, column="corr", ascending=False)
    save_fig("11_baseline_duration_best")

intf_sbas = intf_sbas.sel(pair=pairs_best.pair.values)
corr_sbas = corr_sbas.sel(pair=pairs_best.pair.values)

if not fig_exists("12_intf_sbas_phase_best_first8"):
    sbas.plot_interferograms(intf_sbas[:8], caption="SBAS Phase (best), [rad]")
    save_fig("12_intf_sbas_phase_best_first8")

if not fig_exists("13_intf_sbas_corr_best_first8"):
    sbas.plot_correlations(corr_sbas[:8], caption="SBAS Correlation (best)")
    save_fig("13_intf_sbas_corr_best_first8")

# -------------------------------------------------------------------------
# 스택 코히런스 corr_sbas_stack
# -------------------------------------------------------------------------
try:
    corr_sbas_stack = sbas.open_stack("corr_sbas_stack")
    corr_sbas_stack = ensure_dataarray(corr_sbas_stack)
    print("corr_sbas_stack already exists.")
except Exception:
    corr_sbas_stack = corr_sbas.mean("pair")
    corr_sbas_stack = sbas.sync_cube(corr_sbas_stack, "corr_sbas_stack")

CORRLIMIT = 0.15

if not fig_exists("14_corr_stack"):
    sbas.plot_correlation_stack(corr_sbas_stack, CORRLIMIT, caption="SBAS Stack Correlation")
    save_fig("14_corr_stack")

if not fig_exists("15_intf_sbas_phase_masked_first8"):
    sbas.plot_interferograms(
        intf_sbas[:8].where(corr_sbas_stack > CORRLIMIT),
        caption="SBAS Phase (stack mask), [rad]"
    )
    save_fig("15_intf_sbas_phase_masked_first8")

# -------------------------------------------------------------------------
# 언래핑 unwrap_sbas
# -------------------------------------------------------------------------
try:
    unwrap_sbas = sbas.open_stack("unwrap_sbas")
    print("unwrap_sbas already exists.")
except Exception:
    print("Computing unwrap_sbas via snaphu...")
    unwrap_sbas = sbas.unwrap_snaphu(
        intf_sbas.where(corr_sbas_stack > CORRLIMIT),
        corr_sbas,
        conncomp=True
    )
    unwrap_sbas = sbas.sync_cube(unwrap_sbas, "unwrap_sbas")

if not fig_exists("16_unwrap_sbas_first8"):
    sbas.plot_phases(
        (unwrap_sbas.phase - unwrap_sbas.phase.mean(["y", "x"]))[:8],
        caption="SBAS Phase Unwrapped, [rad]"
    )
    save_fig("16_unwrap_sbas_first8")

unwrap_sbas = sbas.conncomp_main(unwrap_sbas, 1)

if not fig_exists("17_unwrap_sbas_main_first8"):
    sbas.plot_phases(
        (unwrap_sbas.phase - unwrap_sbas.phase.mean(["y", "x"]))[:8],
        caption="SBAS Phase Unwrapped (main comp), [rad]"
    )
    save_fig("17_unwrap_sbas_main_first8")

# -------------------------------------------------------------------------
# 트렌드 / disp_sbas / velocity_sbas
# -------------------------------------------------------------------------
try:
    trend_sbas = sbas.open_stack("trend_sbas")
    trend_sbas = ensure_dataarray(trend_sbas)
    print("trend_sbas already exists.")
except Exception:
    decimator_sbas = sbas.decimator(resolution=15, grid=(1, 1))
    topo = decimator_sbas(sbas.get_topo())
    yy, xx = xr.broadcast(topo.y, topo.x)

    trend_sbas = sbas.regression(
        unwrap_sbas.phase,
        [
            topo, topo * yy, topo * xx, topo * yy * xx,
            topo ** 2, topo ** 2 * yy, topo ** 2 * xx, topo ** 2 * yy * xx,
            yy, xx, yy * xx
        ],
        corr_sbas
    )
    trend_sbas = sbas.sync_cube(trend_sbas, "trend_sbas")

if not fig_exists("18_trend_sbas_first8"):
    sbas.plot_phases(trend_sbas[:8], caption="SBAS Trend Phase, [rad]", quantile=[0.01, 0.99])
    save_fig("18_trend_sbas_first8")

if not fig_exists("19_sbas_phase_minus_trend_first8"):
    sbas.plot_phases(
        (unwrap_sbas.phase - trend_sbas)[:8],
        caption="SBAS Phase - Trend, [rad]",
        vmin=-np.pi, vmax=np.pi
    )
    save_fig("19_sbas_phase_minus_trend_first8")

try:
    disp_sbas = sbas.open_stack("disp_sbas")
    disp_sbas = ensure_dataarray(disp_sbas)
    print("disp_sbas already exists.")
except Exception:
    disp_sbas = sbas.los_displacement_mm(
        sbas.lstsq(unwrap_sbas.phase - trend_sbas, corr_sbas)
    )
    disp_sbas = sbas.sync_cube(disp_sbas, "disp_sbas")

if not fig_exists("20_disp_sbas"):
    sbas.plot_displacements(
        disp_sbas[::3],
        caption="SBAS Cumulative LOS Displacement, [mm]",
        quantile=[0.01, 0.99],
        symmetrical=True
    )
    save_fig("20_disp_sbas")

try:
    velocity_sbas = sbas.open_stack("velocity_sbas")
    velocity_sbas = ensure_dataarray(velocity_sbas)
    print("velocity_sbas already exists.")
except Exception:
    velocity_sbas = sbas.velocity(disp_sbas)
    velocity_sbas = sbas.sync_cube(velocity_sbas, "velocity_sbas")

# SBAS 속도 맵
if not fig_exists("21_velocity_sbas"):
    with mpl_settings({'figure.dpi': 300}):
        fig = plt.figure(figsize=(12, 4))
        zmin, zmax = np.nanquantile(velocity_sbas, [0.01, 0.99])
        zminmax = max(abs(zmin), zmax)

        ax = fig.add_subplot(1, 2, 1)
        velocity_sbas.plot.imshow(cmap="turbo", vmin=-zminmax, vmax=zminmax, ax=ax)
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
        save_fig("21_velocity_sbas")

# -------------------------------------------------------------------------
# SBAS 시계열
# -------------------------------------------------------------------------
geo_pois = sbas.geocode(POI).geometry

for i, geom in enumerate(geo_pois):
    fname = f"22_disp_sbas_stl_poi{i+1}"
    if fig_exists(fname):
        continue

    x, y = geom.x, geom.y
    disp_pixel = disp_sbas.sel(y=y, x=x, method="nearest")
    stl_pixel = sbas.stl(disp_sbas.sel(y=[y], x=[x], method="nearest")).isel(x=0, y=0)

    plt.figure(figsize=(12, 4), dpi=300)
    plt.plot(disp_pixel.date, disp_pixel, c="r", lw=2, label=f"Displacement POI {i+1}")
    plt.plot(stl_pixel.date, stl_pixel.trend, c="r", ls="--", lw=2, label="Trend")
    plt.plot(stl_pixel.date, stl_pixel.seasonal, c="r", lw=1, label="Seasonal")
    plt.legend(loc="upper left")
    plt.title(f"SBAS LOS Displacement STL (POI {i+1})", fontsize=16)
    plt.ylabel("Displacement, mm", fontsize=14)
    save_fig(fname)

if len(geo_pois) > 1 and not fig_exists("23_disp_sbas_all_pois"):
    plt.figure(figsize=(12, 4), dpi=300)
    for i, geom in enumerate(geo_pois):
        x, y = geom.x, geom.y
        disp_pixel = disp_sbas.sel(y=y, x=x, method="nearest")
        plt.plot(disp_pixel.date, disp_pixel, lw=2, label=f"POI {i+1}")
    plt.legend(loc="upper left")
    plt.title("SBAS LOS Displacement (All POIs)", fontsize=16)
    plt.ylabel("Displacement, mm", fontsize=14)
    save_fig("23_disp_sbas_all_pois")

# -------------------------------------------------------------------------
# PS 기반 처리: intf_slook, disp_ps_pairs, disp_ps, velocity_ps
# -------------------------------------------------------------------------
stability = sbas.psfunction()
landmask_ps = landmask_sbas.astype(int).interp_like(stability, method="nearest").astype(bool)

try:
    ds_ps = sbas.open_stack("intf_slook")
    print("intf_slook already exists.")
except Exception:
    print("Computing intf_slook...")
    sbas.compute_interferogram_singlelook(
        pairs_best,
        "intf_slook",
        wavelength=60,
        weight=stability.where(landmask_ps),
        phase=trend_sbas
    )
    ds_ps = sbas.open_stack("intf_slook")

intf_ps = ds_ps.phase
corr_ps = ds_ps.correlation

if not fig_exists("24_intf_ps_phase_first8"):
    sbas.plot_interferograms(intf_ps[:8], caption="PS Phase, [rad]")
    save_fig("24_intf_ps_phase_first8")

if not fig_exists("25_intf_ps_corr_first8"):
    sbas.plot_correlations(corr_ps[:8], caption="PS Correlation")
    save_fig("25_intf_ps_corr_first8")

try:
    disp_ps_pairs = sbas.open_stack("disp_ps_pairs")
    disp_ps_pairs = ensure_dataarray(disp_ps_pairs)
    print("disp_ps_pairs already exists.")
except Exception:
    print("Computing disp_ps_pairs...")
    disp_ps_pairs = sbas.los_displacement_mm(sbas.unwrap1d(intf_ps))
    disp_ps_pairs = sbas.sync_cube(disp_ps_pairs, "disp_ps_pairs")

try:
    disp_ps = sbas.open_stack("disp_ps")
    disp_ps = ensure_dataarray(disp_ps)
    print("disp_ps already exists.")
except Exception:
    disp_ps = sbas.lstsq(disp_ps_pairs, corr_ps)
    disp_ps = sbas.sync_cube(disp_ps, "disp_ps")

if not fig_exists("26_disp_ps"):
    sbas.plot_displacements(
        disp_ps[::3],
        caption="PS Cumulative LOS Displacement, [mm]",
        quantile=[0.01, 0.99],
        symmetrical=True
    )
    save_fig("26_disp_ps")

try:
    velocity_ps = sbas.open_stack("velocity_ps")
    velocity_ps = ensure_dataarray(velocity_ps)
    print("velocity_ps already exists.")
except Exception:
    velocity_ps = sbas.velocity(disp_ps)
    velocity_ps = sbas.sync_cube(velocity_ps, "velocity_ps")

if not fig_exists("27_velocity_ps"):
    with mpl_settings({'figure.dpi': 300}):
        fig = plt.figure(figsize=(12, 4))
        zmin, zmax = np.nanquantile(velocity_ps, [0.01, 0.99])
        zminmax = max(abs(zmin), zmax)

        ax = fig.add_subplot(1, 2, 1)
        velocity_ps.plot.imshow(cmap="turbo", vmin=-zminmax, vmax=zminmax, ax=ax)
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
        save_fig("27_velocity_ps")

# PS 시계열
geo_pois = sbas.geocode(POI).geometry

for i, geom in enumerate(geo_pois):
    fname = f"28_disp_ps_stl_poi{i+1}"
    if fig_exists(fname):
        continue

    x, y = geom.x, geom.y
    disp_pixel = disp_ps.sel(y=y, x=x, method="nearest")
    stl_pixel = sbas.stl(disp_ps.sel(y=[y], x=[x], method="nearest")).isel(x=0, y=0)

    plt.figure(figsize=(12, 4), dpi=300)
    plt.plot(disp_pixel.date, disp_pixel, c="r", lw=2, label=f"Displacement POI {i+1}")
    plt.plot(stl_pixel.date, stl_pixel.trend, c="r", ls="--", lw=2, label="Trend")
    plt.plot(stl_pixel.date, stl_pixel.seasonal, c="r", lw=1, label="Seasonal")
    plt.legend(loc="upper left")
    plt.title(f"PS LOS Displacement STL (POI {i+1})", fontsize=16)
    plt.ylabel("Displacement, mm", fontsize=14)
    save_fig(fname)

if len(geo_pois) > 1 and not fig_exists("29_disp_ps_all_pois"):
    plt.figure(figsize=(12, 4), dpi=300)
    for i, geom in enumerate(geo_pois):
        x, y = geom.x, geom.y
        disp_pixel = disp_ps.sel(y=y, x=x, method="nearest")
        plt.plot(disp_pixel.date, disp_pixel, lw=2, label=f"POI {i+1}")
    plt.legend(loc="upper left")
    plt.title("PS LOS Displacement (All POIs)", fontsize=16)
    plt.ylabel("Displacement, mm", fontsize=14)
    save_fig("29_disp_ps_all_pois")

# baseline-displacement plot (여러 POI)
for i, geom in enumerate(sbas.geocode(POI).geometry):
    fname = f"30_baseline_disp_ps_poi{i+1}"
    if fig_exists(fname):
        continue

    x, y = geom.x, geom.y
    disp_norm = disp_ps_pairs.sel(y=y, x=x, method="nearest") / sbas.los_displacement_mm(1)
    corr_norm = corr_ps.sel(y=y, x=x, method="nearest")

    sbas.plot_baseline_displacement_los_mm(
        disp_norm,
        corr_norm,
        caption=f"POI {i+1}",
        stl=True
    )
    save_fig(fname)

# -------------------------------------------------------------------------
# SBAS vs PS 누적 변위 비교 (컬러바 오른쪽 바깥)
# -------------------------------------------------------------------------
if not fig_exists("31_disp_sbas_ps_compare"):
    with mpl_settings({'figure.dpi': 300}):
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))

        disp_sbas_last = disp_sbas.isel(date=-1)
        disp_ps_last   = disp_ps.isel(date=-1)

        all_vals = np.concatenate([
            disp_sbas_last.values.ravel(),
            disp_ps_last.values.ravel()
        ])
        all_vals = all_vals[~np.isnan(all_vals)]

        if all_vals.size > 0:
            qmin, qmax = np.nanquantile(all_vals, [0.01, 0.99])
            zlim = max(abs(qmin), abs(qmax))
        else:
            zlim = 10.0

        vmin, vmax = -zlim, zlim

        im0 = disp_sbas_last.plot.imshow(
            ax=axes[0],
            cmap="turbo",
            vmin=vmin,
            vmax=vmax,
            add_colorbar=False
        )
        axes[0].set_title("SBAS Cumulative LOS Displacement, mm")
        axes[0].set_aspect("auto")

        im1 = disp_ps_last.plot.imshow(
            ax=axes[1],
            cmap="turbo",
            vmin=vmin,
            vmax=vmax,
            add_colorbar=False
        )
        axes[1].set_title("PS Cumulative LOS Displacement, mm")
        axes[1].set_aspect("auto")

        # 컬러바를 오른쪽 바깥에 따로 배치
        fig.subplots_adjust(right=0.85)
        cbar_ax = fig.add_axes([0.88, 0.15, 0.02, 0.7])
        cbar = fig.colorbar(im1, cax=cbar_ax)
        cbar.set_label("Displacement, mm")

        plt.suptitle("SBAS vs PS Cumulative LOS Displacement (common color scale)", fontsize=16)
        plt.tight_layout(rect=[0.0, 0.0, 0.85, 0.95])
        save_fig("31_disp_sbas_ps_compare")

# -------------------------------------------------------------------------
# RMSE (rmse_ps)
# -------------------------------------------------------------------------
try:
    rmse_ps = sbas.open_stack("rmse_ps")
    rmse_ps = ensure_dataarray(rmse_ps)
    print("rmse_ps already exists.")
except Exception:
    print("Computing rmse_ps...")
    rmse_ps = sbas.rmse(disp_ps_pairs, disp_ps, corr_ps)
    rmse_ps = sbas.sync_cube(rmse_ps, "rmse_ps")

if not fig_exists("32_rmse_ps"):
    sbas.plot_rmse(rmse_ps, caption="RMSE Correlation Aware, [mm]")
    save_fig("32_rmse_ps")

# -------------------------------------------------------------------------
# SBAS vs PS 속도 산점도 (RA 좌표계에서 비교: 지오코딩 안 씀)
# -------------------------------------------------------------------------
if not fig_exists("33_sbas_vs_ps_scatter"):
    vel_ps_interp_ra = velocity_ps.interp_like(velocity_sbas, method="nearest")

    points_sbas_vals = velocity_sbas.values.ravel()
    points_ps_interp = vel_ps_interp_ra.values.ravel()

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
    plt.title("Cross-Comparison between SBAS and PS Velocity (RA grid)", fontsize=18)
    plt.grid(True)
    save_fig("33_sbas_vs_ps_scatter")

# -------------------------------------------------------------------------
# GeoTIFF 저장 (SBAS/PS Velocity, RMSE)
# -------------------------------------------------------------------------
vel_sbas_ll = sbas.ra2ll(velocity_sbas)
vel_sbas_ll = sbas.as_geo(vel_sbas_ll).rio.clip(AOI.geometry)
sbas_tif = OUTPUT_DIR / "velocity_sbas_los_mm_per_year.tif"
if not sbas_tif.exists():
    vel_sbas_ll.rio.to_raster(sbas_tif)
    print("Saved SBAS velocity:", sbas_tif)
else:
    print("SBAS velocity GeoTIFF already exists:", sbas_tif)

vel_ps_ll = sbas.ra2ll(velocity_ps)
vel_ps_ll = sbas.as_geo(vel_ps_ll).rio.clip(AOI.geometry)
ps_tif = OUTPUT_DIR / "velocity_ps_los_mm_per_year.tif"
if not ps_tif.exists():
    vel_ps_ll.rio.to_raster(ps_tif)
    print("Saved PS velocity:", ps_tif)
else:
    print("PS velocity GeoTIFF already exists:", ps_tif)

rmse_ll = sbas.ra2ll(rmse_ps)
rmse_ll = sbas.as_geo(rmse_ll).rio.clip(AOI.geometry)
rmse_tif = OUTPUT_DIR / "rmse_ps_los_mm.tif"
if not rmse_tif.exists():
    rmse_ll.rio.to_raster(rmse_tif)
    print("Saved PS RMSE:", rmse_tif)
else:
    print("RMSE GeoTIFF already exists:", rmse_tif)

print("DONE.")
