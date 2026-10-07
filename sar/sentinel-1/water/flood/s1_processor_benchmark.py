#!/usr/bin/env python
# -*- coding: utf-8 -*-


    # 실행코드

    # python <DATA_ROOT>\etc\code\s1_processor8_hjh.py ^
    # --input_tifs "<DATA_ROOT>\07_disaster\flood\Sen1Flood11_hjh\s1\*.tif" ^
    # --output_dir "<DATA_ROOT>\07_disaster\flood\Sen1Flood11_hjh\watermask" ^
    # --polarization VH ^
    # --initial_db_threshold -30 ^
    # --edge_buffer 5

    # python <DATA_ROOT>\etc\code\s1_processor8_hjh.py ^
    # --input_tifs "<DATA_ROOT>\07_disaster\flood\Sen1Flood11_hjh\s1\*.tif" ^
    # --output_dir "<DATA_ROOT>\07_disaster\flood\Sen1Flood11_hjh\watermask" ^
    # --polarization VV ^
    # --initial_db_threshold -20 ^
    # --edge_buffer 5



import argparse
from glob import glob
from pathlib import Path

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import reproject, Resampling as WarpResampling
from scipy.ndimage import binary_dilation, binary_erosion
from skimage.filters import threshold_otsu


def edge_otsu_thresholding(image_data: np.ndarray,
                           initial_threshold: float,
                           edge_buffer: int):
    """
    Edge-Otsu 알고리즘 구현.
    - image_data: float32 dB 배열 (NaN은 무시)
    - initial_threshold: 초기 물 임계값(dB)
    - edge_buffer: 경계 주변 dilation 횟수
    """
    valid = ~np.isnan(image_data)
    if not np.any(valid):
        # 유효 픽셀이 전혀 없으면 전부 비물
        return np.zeros_like(image_data, dtype=bool), initial_threshold

    # 1) 초기 임계값 이진화 (물=True)
    water0 = np.zeros_like(image_data, dtype=bool)
    water0[valid] = image_data[valid] < initial_threshold

    # 2) 모폴로지 경계 (morphological gradient)
    erode = binary_erosion(water0, iterations=1, border_value=0)
    dilate = binary_dilation(water0, iterations=1, border_value=0)
    edges = np.logical_and(dilate, ~erode)

    # 3) 경계 버퍼
    iters = max(1, int(edge_buffer))
    buffered_edges = binary_dilation(edges, iterations=iters, border_value=0)

    # 4) 버퍼 영역(유효값만)에서 Otsu
    samples_mask = np.logical_and(buffered_edges, valid)
    if np.count_nonzero(samples_mask) == 0:
        # 경계 샘플이 없다면 전체 유효 픽셀에서 Otsu
        final_thr = threshold_otsu(image_data[valid].astype(np.float32))
    else:
        final_thr = threshold_otsu(image_data[samples_mask].astype(np.float32))

    # 최종 마스크
    final_mask = np.zeros_like(water0, dtype=bool)
    final_mask[valid] = image_data[valid] < final_thr
    return final_mask, float(final_thr)


def detect_water_single_tif(
    tif_path: Path,
    output_dir: Path,
    polarization: str,
    initial_db_threshold: float,
    edge_buffer: int,
):
    """
    하나의 dB GeoTIFF에서 수체 마스크 생성.

    polarization:
      - 'VV' -> band_index = 1
      - 'VH' -> band_index = 2  (Sen1Floods11 S1 기준)
    """
    tif_path = Path(tif_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if polarization.upper() == "VV":
        band_index = 1
    else:  # "VH"
        band_index = 2

    out_path = output_dir / f"{tif_path.stem}_watermask.tif"
    if out_path.exists():
        print(f"[SKIP] 이미 존재: {out_path}")
        return str(out_path)

    print(f"\n[수체 탐지] 입력: {tif_path}  (band_index={band_index})")

    with rasterio.open(tif_path) as src:
        db_data = src.read(band_index).astype(np.float32)
        meta = src.meta.copy()

    # 기본적인 NaN 처리 / 이상치 제거 (필요시 값 조정 가능)
    nodata = meta.get("nodata", None)
    if nodata is not None:
        db_data[db_data == nodata] = np.nan
    db_data[db_data == 0] = np.nan       # 0 dB는 nodata처럼 취급 (환경에 따라 조정 가능)
    db_data[~np.isfinite(db_data)] = np.nan
    db_data[db_data <= -9999.0] = np.nan
    db_data[(~np.isnan(db_data)) & (db_data < -80.0)] = np.nan

    # Edge-Otsu 수행
    water_mask, final_thr = edge_otsu_thresholding(
        db_data,
        initial_threshold=initial_db_threshold,
        edge_buffer=edge_buffer,
    )
    print(f"   - Edge-Otsu 최종 임계값: {final_thr:.4f} dB")

    # 0/1 마스크로 저장
    meta.update(
        {
            "driver": "GTiff",
            "count": 1,
            "dtype": "uint8",
            "nodata": 0,
        }
    )
    with rasterio.open(out_path, "w", **meta) as dst:
        dst.write(water_mask.astype(np.uint8), 1)

    print(f"   - 저장 완료: {out_path}")
    return str(out_path)


def expand_input_patterns(patterns):
    """
    --input_tifs 에 들어온 문자열 리스트(와일드카드 포함)를
    실제 파일 경로 리스트로 확장.
    """
    all_files = []

    for pat in patterns:
        # Path 객체로 한 번 정리
        p = Path(pat)

        # 디렉터리 + 패턴으로 분리
        # 예: D:\...\Sen1Flood11_hjh\*.tif
        if any(ch in p.name for ch in ["*", "?"]):
            directory = p.parent if p.parent != Path("") else Path.cwd()
            pattern = p.name

            # 디렉터리가 실제 존재하면 그 안에서 직접 glob
            if directory.exists():
                matches = sorted(directory.glob(pattern))
            else:
                matches = []

            if matches:
                all_files.extend(str(m) for m in matches)
            else:
                print(f"[경고] 패턴에서 파일을 찾지 못했습니다: {pat}")
        else:
            # 와일드카드가 없으면 그냥 파일 존재 여부 확인
            if p.exists():
                all_files.append(str(p))
            else:
                print(f"[경고] 파일을 찾지 못했습니다: {pat}")

    # 중복 제거 + Path로 변환
    unique_files = sorted({str(Path(f)) for f in all_files})
    print(f"[디버그] 확장된 입력 파일 수: {len(unique_files)}")
    for f in unique_files:
        print(f"         - {f}")
    return [Path(f) for f in unique_files]



def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description="Edge-Otsu 기반 수체 탐지 (이미 dB로 전처리된 Sentinel-1 GeoTIFF용)",
    )
    parser.add_argument(
        "--input_tifs",
        required=True,
        nargs="+",
        help="입력 dB GeoTIFF 경로 (와일드카드 지원, 예: 'D:\\data\\*.tif')",
    )
    parser.add_argument(
        "--output_dir",
        required=True,
        help="수체 마스크 GeoTIFF를 저장할 폴더",
    )
    parser.add_argument(
        "--polarization",
        default="VH",
        choices=["VV", "VH"],
        help="사용할 편파 (기본: VH, Sen1Floods11 S1 기준 band2)",
    )
    parser.add_argument(
        "--initial_db_threshold",
        type=float,
        default=-20.0,
        help="Edge-Otsu 초기 임계값 (dB)",
    )
    parser.add_argument(
        "--edge_buffer",
        type=int,
        default=5,
        help="경계 dilation 버퍼링 횟수",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_files = expand_input_patterns(args.input_tifs)
    if not input_files:
        print("오류: 입력 GeoTIFF를 찾을 수 없습니다. --input_tifs 패턴을 확인하세요.")
        return

    print(f"\n--- Edge-Otsu 수체 탐지 시작: 총 {len(input_files)}개 파일 ---")
    out_dir = Path(args.output_dir)

    for f in input_files:
        detect_water_single_tif(
            tif_path=f,
            output_dir=out_dir,
            polarization=args.polarization,
            initial_db_threshold=args.initial_db_threshold,
            edge_buffer=args.edge_buffer,
        )

    print("\n✅ 모든 작업 완료.")


if __name__ == "__main__":
    main()
