"""BlueBON AOD v8 + post-smoothing end-to-end pipeline.

현재까지 가장 좋은 설정으로 판단된 v8 retrieval(`bb_aod_calval.retrieve_aod`)에
Gaussian 후처리 스무딩(`smooth_v8.py` 등가)을 결합해 한 번의 호출로 산출한다.

Usage
-----
단일 파일 + MAIAC 자동 다운로드(권장):
    python bb_aod_pipeline.py --input bb_l1c_20260220_025632_8band.tiff --auto-maiac
        → bb_aod_20260220_025632_sm.tif (자동 명명)
        → 같은 날짜 MAIAC MCD19A2 다운로드 후 scene mean 으로 background fill 보정

수동 MAIAC 지정:
    python bb_aod_pipeline.py --input ... --maiac-aod-mean 0.3393

여러 파일 / glob:
    python bb_aod_pipeline.py --input 'bb_l1c_*_8band.tiff' --auto-maiac

주요 옵션:
    --auto-maiac             입력 tiff 의 센싱 날짜/bbox 에 맞춰 MAIAC 자동 다운로드 + mean 주입
    --maiac-cache DIR        MAIAC HDF 캐시 디렉토리 (default: ./maiac_cache)
    --maiac-date-window N    ±N 일 범위 검색 (default: 0 = 동일 날짜만)
    --earthdata-user / --earthdata-pass  NASA Earthdata 계정 (없으면 .netrc/env 사용)
    --out-dir DIR            출력 디렉토리 (default: 입력과 동일)
    --out NAME               단일 입력일 때만 유효한 명시적 출력 경로
    --save-raw               스무딩 전 v8 결과도 `_v8.tif` 로 저장
    --save-qa                QA 레이어 `_qa.tif` 로 저장
    --post-sigma-px VAL      후처리 Gaussian sigma (출력 격자 픽셀 단위)
    --radiance-scale VAL     DN→radiance 계수 (default: V8 값 0.3183)

기타 retrieval 파라미터는 argparse passthrough 로 제공한다.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import traceback
from datetime import timedelta
from typing import List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from scipy.ndimage import gaussian_filter

from bb_aod_calval import (
    RetrievalConfig,
    parse_sensing_time,
    retrieve_aod,
    write_geotiff,
)


# ---------------------------------------------------------------------------
# v8 기준 기본 설정  (bb_aod_v8_sm.tif 재현용)
# ---------------------------------------------------------------------------
# v8 생성 당시(jsonl line 1737) 인자:
#   --radiance-scale 0.3183  --surf-blue-red-ratio 0.575
#   --smooth-sigma-px 480    --maiac-aod-mean 0.3393 (scene-specific)
# v8 당시 RetrievalConfig 기본:
#   ndvi_dependent_ratio=True (현재 기본 False 와 반대 — v9 회귀 방지로 바뀜)
#   forest branch 없음 (ratio = surf_blue_red_ratio × (0.6 + 0.4 × frac))
# 현재 코드는 ndvi_high = forest_ndvi_thresh + forest branch 가 추가되었으므로
# forest_ndvi_thresh = 0.60, surf_blue_red_ratio_forest = surf_blue_red_ratio 로
# 세팅해 forest branch 영향을 제거하고 v8 공식과 등가로 만든다.
#
# 최종 smooth_v8.py 호출(jsonl line 2290): sigma-px=30
V8_DEFAULTS = dict(
    ndvi_min=0.25,
    red_dark_max=0.15,
    ddv_nir_min=0.20,
    surf_blue_red_ratio=0.575,
    surf_blue_red_ratio_forest=0.575,   # = main ratio → forest 분기 무효화
    forest_ndvi_thresh=0.60,            # v8-era ndvi_high
    ndvi_dependent_ratio=True,          # v8 당시 기본 True
    cloud_tests_enabled=False,
    use_block_trimmed_mean=False,
    min_valid_ddv_fraction=0.0005,
    fill_sigma_px=300.0,
    smooth_sigma_px=480.0,              # v8 CLI 값
    out_res_m=20,
    use_py6s=True,
    aerosol_profile="continental",
    atmosphere_profile="auto",
    target_alt_km=0.0,
)

DEFAULT_POST_SIGMA_PX = 30.0      # bb_aod_v8_sm.tif 는 sigma=30 으로 생성됨
DEFAULT_RADIANCE_SCALE = 0.3183   # v8 CLI 값


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def derive_stem(input_path: str) -> str:
    """`bb_l1c_20260220_025632_8band.tiff` → `bb_aod_20260220_025632`.

    파일명 패턴이 인식되지 않으면 기본 stem 을 사용한다.
    """
    base = os.path.basename(input_path)
    stem, _ = os.path.splitext(base)
    m = re.match(r"bb_l1c_(\d{8})_(\d{6})", stem)
    if m:
        return f"bb_aod_{m.group(1)}_{m.group(2)}"
    # Fallback: 입력 stem 뒤에 _aod 붙임
    return f"{stem}_aod"


def expand_inputs(patterns: List[str]) -> List[str]:
    """Literal 경로 + glob 패턴을 모두 수용."""
    out: List[str] = []
    seen = set()
    for p in patterns:
        matches = sorted(glob.glob(p)) if any(ch in p for ch in "*?[") else [p]
        if not matches:
            print(f"  [warn] no match for {p!r}", file=sys.stderr)
            continue
        for m in matches:
            if m not in seen and os.path.exists(m):
                seen.add(m)
                out.append(m)
            elif m not in seen:
                print(f"  [warn] missing file: {m}", file=sys.stderr)
    return out


def scene_bbox_wgs84(tiff_path: str) -> Tuple[float, float, float, float]:
    """BlueBON tiff 의 scene bbox 를 WGS84 (lon_min, lat_min, lon_max, lat_max) 로 반환."""
    with rasterio.open(tiff_path) as s:
        if s.crs is None:
            raise RuntimeError(f"{tiff_path}: CRS 정보 없음 → bbox 계산 불가")
        if s.crs.is_geographic:
            lon_min, lat_min, lon_max, lat_max = s.bounds
        else:
            lon_min, lat_min, lon_max, lat_max = transform_bounds(
                s.crs, "EPSG:4326", *s.bounds, densify_pts=21,
            )
    return float(lon_min), float(lat_min), float(lon_max), float(lat_max)


def auto_maiac_mean(tiff_path: str,
                    cache_dir: str,
                    date_window_days: int = 0,
                    username: Optional[str] = None,
                    password: Optional[str] = None,
                    bbox_pad_deg: float = 0.10) -> Optional[float]:
    """입력 BlueBON tiff 의 센싱 날짜/bbox 에 맞춰 MAIAC 을 자동 다운로드하고
    scene mean AOD(550) 를 반환한다.

    실패(네트워크, 자격증명, granule 없음 등) 시 None 반환 → 파이프라인은
    DDV median 으로 자동 fallback 한다.

    Parameters
    ----------
    tiff_path : BlueBON L1C tiff
    cache_dir : MAIAC HDF 캐시 디렉토리
    date_window_days : ±N 일 범위 (0 = 동일 날짜만)
    bbox_pad_deg : bbox 경계 여유 (기본 0.10° ≈ 10 km)
    """
    # validate_bb_aod 에서 재사용 (MODIS 다운로드 + HDF 읽기)
    try:
        from validate_bb_aod import download_maiac_range, read_maiac_aod
    except ImportError as e:
        print(f"  [auto-maiac] validate_bb_aod import 실패: {e}", file=sys.stderr)
        return None

    sensing_time = parse_sensing_time(tiff_path)
    date_str = sensing_time.strftime("%Y-%m-%d")
    try:
        lon_min, lat_min, lon_max, lat_max = scene_bbox_wgs84(tiff_path)
    except Exception as e:
        print(f"  [auto-maiac] bbox 추출 실패: {e}", file=sys.stderr)
        return None

    bbox = (lon_min - bbox_pad_deg, lat_min - bbox_pad_deg,
            lon_max + bbox_pad_deg, lat_max + bbox_pad_deg)
    print(f"  [auto-maiac] {date_str}  bbox=({bbox[0]:.3f},{bbox[1]:.3f},"
          f"{bbox[2]:.3f},{bbox[3]:.3f})  window=±{date_window_days}d")

    if date_window_days > 0:
        d0 = (sensing_time - timedelta(days=date_window_days)).strftime("%Y-%m-%d")
        d1 = (sensing_time + timedelta(days=date_window_days)).strftime("%Y-%m-%d")
    else:
        d0 = d1 = date_str

    os.makedirs(cache_dir, exist_ok=True)
    try:
        files = download_maiac_range(d0, d1, bbox, cache_dir, username, password)
    except Exception as e:
        print(f"  [auto-maiac] 다운로드 실패 → DDV median fallback: {e}", file=sys.stderr)
        return None
    if not files:
        print("  [auto-maiac] 다운로드된 granule 없음 → DDV median fallback")
        return None

    # 센싱 날짜와 동일한 granule 우선, 없으면 범위 내 전체 사용
    doy_tag = f"A{sensing_time.strftime('%Y%j')}"
    same_date = [f for f in files if doy_tag in os.path.basename(f)]
    target_files = same_date if same_date else files
    if not same_date and date_window_days > 0:
        print(f"  [auto-maiac] 동일 날짜({date_str}) granule 없음 → window 내 전체({len(files)}) 사용")

    all_aod: List[np.ndarray] = []
    for hdf in target_files:
        try:
            _, _, aod = read_maiac_aod(hdf, bbox)
            if aod.size > 0:
                all_aod.append(aod)
        except Exception as e:
            print(f"    read_maiac_aod 실패 {os.path.basename(hdf)}: {e}", file=sys.stderr)

    if not all_aod:
        print("  [auto-maiac] bbox 내 유효 MAIAC 픽셀 없음 → DDV median fallback")
        return None

    concat = np.concatenate(all_aod)
    mean = float(np.nanmean(concat))
    print(f"  [auto-maiac] MAIAC AOD mean = {mean:.4f}  "
          f"(n={concat.size:,}, granules={len(target_files)})")
    return mean


def post_smooth(arr: np.ndarray, sigma_px: float) -> np.ndarray:
    """NaN-aware Gaussian 스무딩 (smooth_v8.py 동일 로직)."""
    valid = np.isfinite(arr)
    a0 = np.where(valid, arr, 0.0).astype(np.float32)
    w0 = valid.astype(np.float32)
    num = gaussian_filter(a0, sigma=sigma_px)
    den = gaussian_filter(w0, sigma=sigma_px)
    sm = num / np.maximum(den, 1e-9)
    return np.where(valid, sm, np.nan).astype(np.float32)


def build_config(args: argparse.Namespace) -> RetrievalConfig:
    """V8 기본값 + CLI override 로 RetrievalConfig 생성."""
    params = dict(V8_DEFAULTS)
    for key in (
        "ndvi_min",
        "red_dark_max",
        "ddv_nir_min",
        "surf_blue_red_ratio",
        "min_valid_ddv_fraction",
        "fill_sigma_px",
        "smooth_sigma_px",
        "out_res_m",
        "aerosol_profile",
        "atmosphere_profile",
        "target_alt_km",
    ):
        val = getattr(args, key, None)
        if val is not None:
            params[key] = val
    if args.no_py6s:
        params["use_py6s"] = False
    if args.no_ndvi_dependent_ratio:
        params["ndvi_dependent_ratio"] = False
    return RetrievalConfig(**params)


# ---------------------------------------------------------------------------
# Per-scene processing
# ---------------------------------------------------------------------------

def process_one(input_path: str, cfg: RetrievalConfig,
                out_dir: Optional[str], explicit_out: Optional[str],
                save_raw: bool, save_qa: bool,
                post_sigma_px: float,
                radiance_scale: float,
                solar_z_override: Optional[float],
                view_z_deg: float, rel_az_deg: float,
                maiac_aod_mean: Optional[float]) -> Tuple[str, str]:
    """단일 BlueBON tiff 처리. (out_sm_path, out_raw_path or '') 반환."""
    stem = derive_stem(input_path)
    base_dir = out_dir if out_dir else os.path.dirname(os.path.abspath(input_path))
    os.makedirs(base_dir, exist_ok=True)

    sm_path = explicit_out if explicit_out else os.path.join(base_dir, f"{stem}_sm.tif")
    raw_path = os.path.join(base_dir, f"{stem}_v8.tif") if save_raw else ""
    qa_path = os.path.join(base_dir, f"{stem}_qa.tif") if save_qa else ""

    print(f"\n==== {os.path.basename(input_path)} → {os.path.basename(sm_path)} ====")
    aod, transform, crs, debug = retrieve_aod(
        input_path, cfg,
        radiance_scale=radiance_scale,
        solar_z_override=solar_z_override,
        view_z_deg=view_z_deg,
        rel_az_deg=rel_az_deg,
        maiac_aod_mean=maiac_aod_mean,
    )

    if raw_path:
        write_geotiff(raw_path, aod, transform, crs)
        print(f"Wrote v8 AOD      : {raw_path}")

    aod_sm = post_smooth(aod, sigma_px=post_sigma_px)
    write_geotiff(sm_path, aod_sm, transform, crs)
    print(f"Wrote smoothed AOD: {sm_path}  (sigma_px={post_sigma_px})")

    if qa_path and "qa" in debug:
        write_geotiff(qa_path, debug["qa"].astype(np.float32), transform, crs)
        print(f"Wrote QA          : {qa_path}")

    finite = np.isfinite(aod_sm)
    if finite.any():
        print(f"AOD stats (sm)    : n={finite.sum():,}  "
              f"mean={np.nanmean(aod_sm):.3f}  median={np.nanmedian(aod_sm):.3f}  "
              f"min={np.nanmin(aod_sm):.3f}  max={np.nanmax(aod_sm):.3f}")
    else:
        print("  WARNING: no valid AOD pixels.")
    return sm_path, raw_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="BlueBON AOD v8+smoothing pipeline for arbitrary L1C 8-band TIFFs",
    )
    p.add_argument("--input", action="append", required=True,
                   help="입력 BlueBON L1C tiff 경로 또는 glob 패턴. 반복 가능.")
    p.add_argument("--out", default=None,
                   help="단일 입력일 때의 최종 smoothed AOD 출력 경로. "
                        "다중 입력/glob 에서는 무시(자동 명명).")
    p.add_argument("--out-dir", default=None,
                   help="출력 디렉토리 (default: 각 입력 파일과 동일 위치)")
    p.add_argument("--save-raw", action="store_true",
                   help="스무딩 전 v8 결과도 `_v8.tif` 로 저장")
    p.add_argument("--save-qa",  action="store_true",
                   help="QA 레이어 `_qa.tif` 로 저장")
    p.add_argument("--post-sigma-px", type=float, default=DEFAULT_POST_SIGMA_PX,
                   help=f"후처리 Gaussian sigma (출력 격자 픽셀; default={DEFAULT_POST_SIGMA_PX})")

    # Calibration / geometry
    p.add_argument("--radiance-scale", type=float, default=DEFAULT_RADIANCE_SCALE)
    p.add_argument("--solar-z-deg", type=float, default=None)
    p.add_argument("--view-z-deg",  type=float, default=0.0)
    p.add_argument("--rel-az-deg",  type=float, default=0.0)
    p.add_argument("--maiac-aod-mean", type=float, default=None,
                   help="수동 MAIAC scene mean AOD. 지정 시 --auto-maiac 무시.")
    p.add_argument("--auto-maiac", action="store_true",
                   help="입력 tiff 의 날짜/bbox 로 MAIAC 자동 다운로드 후 mean 주입")
    p.add_argument("--maiac-cache", default="./maiac_cache",
                   help="MAIAC HDF 캐시 디렉토리 (default: ./maiac_cache)")
    p.add_argument("--maiac-date-window", type=int, default=0,
                   help="MAIAC 검색 ±N 일 (default: 0 = 동일 날짜만)")
    p.add_argument("--earthdata-user", default=None,
                   help="NASA Earthdata username (없으면 .netrc/env 사용)")
    p.add_argument("--earthdata-pass", default=None,
                   help="NASA Earthdata password")

    # Retrieval overrides (v8 기본값에서 벗어나고 싶을 때만)
    p.add_argument("--ndvi-min", type=float, default=None)
    p.add_argument("--red-dark-max", type=float, default=None)
    p.add_argument("--ddv-nir-min", type=float, default=None)
    p.add_argument("--surf-blue-red-ratio", type=float, default=None)
    p.add_argument("--min-valid-ddv-fraction", dest="min_valid_ddv_fraction",
                   type=float, default=None)
    p.add_argument("--fill-sigma-px",   type=float, default=None)
    p.add_argument("--smooth-sigma-px", type=float, default=None)
    p.add_argument("--out-res",         dest="out_res_m", type=int, default=None)
    p.add_argument("--aerosol-profile", default=None,
                   choices=["continental", "maritime", "urban", "desert"])
    p.add_argument("--atmosphere-profile", default=None,
                   choices=["auto", "midlatitude_summer", "midlatitude_winter",
                            "tropical", "subarctic_summer", "subarctic_winter"])
    p.add_argument("--target-alt-km", type=float, default=None)
    p.add_argument("--no-py6s", action="store_true")
    p.add_argument("--no-ndvi-dependent-ratio", action="store_true",
                   help="NDVI-dependent ratio 비활성화 (v8 기본은 활성)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    inputs = expand_inputs(args.input)
    if not inputs:
        print("No input files.", file=sys.stderr)
        return 2
    if args.out and len(inputs) > 1:
        print("  [warn] --out is ignored when multiple inputs are given.",
              file=sys.stderr)
        explicit_out = None
    else:
        explicit_out = args.out

    cfg = build_config(args)
    print(f"Processing {len(inputs)} scene(s) with v8 defaults + post-smooth σ={args.post_sigma_px}px")

    ok, fail = 0, 0
    for path in inputs:
        try:
            # Per-scene MAIAC 참조값 결정: 수동값 우선 → --auto-maiac → None(DDV median)
            if args.maiac_aod_mean is not None:
                scene_maiac = args.maiac_aod_mean
                if args.auto_maiac:
                    print(f"  [auto-maiac] --maiac-aod-mean={scene_maiac} 지정됨, 자동 다운로드 skip")
            elif args.auto_maiac:
                scene_maiac = auto_maiac_mean(
                    path,
                    cache_dir=args.maiac_cache,
                    date_window_days=args.maiac_date_window,
                    username=args.earthdata_user,
                    password=args.earthdata_pass,
                )
            else:
                scene_maiac = None

            process_one(
                path, cfg,
                out_dir=args.out_dir,
                explicit_out=explicit_out,
                save_raw=args.save_raw,
                save_qa=args.save_qa,
                post_sigma_px=args.post_sigma_px,
                radiance_scale=args.radiance_scale,
                solar_z_override=args.solar_z_deg,
                view_z_deg=args.view_z_deg,
                rel_az_deg=args.rel_az_deg,
                maiac_aod_mean=scene_maiac,
            )
            ok += 1
        except Exception as exc:
            fail += 1
            print(f"  [ERROR] {path}: {exc}", file=sys.stderr)
            traceback.print_exc()

    print(f"\nDone. success={ok}  failed={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
