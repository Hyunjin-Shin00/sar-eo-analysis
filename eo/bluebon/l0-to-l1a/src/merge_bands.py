#!/usr/bin/env python3
"""
단일밴드 TIFF 파일을 하나의 멀티밴드 TIFF로 합치는 스크립트

8밴드 구성 (MS0~MS7 모두 있는 경우):
  0: PAN (MS0)
  1: Blue (MS1)
  2: Green (MS2)
  3: Red (MS3)
  4: RedEdge1 (MS4)
  5: RedEdge2 (MS5)
  6: RedEdge3 (MS6)
  7: NIR (MS7)

4밴드 구성 (MS1, MS2, MS3, MS7만 있는 경우):
  0: Blue (MS1)
  1: Green (MS2)
  2: Red (MS3)
  3: NIR (MS7)

사용법:
  conda activate prep
  python merge_bands.py <input_directory>

예시:
  python merge_bands.py /mnt/e/bkchoi/prep/data/upload/complete/GDrive/260116_021517/level-1B
  -> bb_l1b_20260116_021517_8band.tiff (level-1B, 8밴드)
  -> bb_l1b_20260116_021517_4band.tiff (level-1B, 4밴드)

  python merge_bands.py /mnt/e/bkchoi/prep/data/upload/complete/GDrive/260116_021517/level-1A
  -> bb_l1a_20260116_021517_8band.tiff (level-1A, 8밴드)
"""

import rasterio
import os
import re
import argparse


# 8밴드 설정
BANDS_8 = {
    'indices': [0, 1, 2, 3, 4, 5, 6, 7],
    'names': ['PAN', 'Blue', 'Green', 'Red', 'RedEdge1', 'RedEdge2', 'RedEdge3', 'NIR'],
    'files': [f"MS{i}_DN_dark_rc_p.tiff" for i in range(8)],
}

# 4밴드 설정 (Blue, Green, Red, NIR)
BANDS_4 = {
    'indices': [1, 2, 3, 7],
    'names': ['Blue', 'Green', 'Red', 'NIR'],
    'files': [f"MS{i}_DN_dark_rc_p.tiff" for i in [1, 2, 3, 7]],
}

# 2밴드 설정 (Blue, Green, Red, NIR)
BANDS_3 = {
    'indices': [1, 2, 3],
    'names': ['Blue', 'Green', 'Red'],
    'files': [f"MS{i}_DN_dark_rc_p.tiff" for i in [1, 2, 3]],
}

def extract_datetime_from_path(input_dir: str) -> tuple[str, str]:
    """
    경로에서 yymmdd_HHMMSS 패턴을 추출하여 yyyymmdd, HHMMSS 반환
    """
    pattern = r'(\d{6})_(\d{6})'
    match = re.search(pattern, input_dir)

    if not match:
        raise ValueError(f"경로에서 yymmdd_HHMMSS 패턴을 찾을 수 없습니다: {input_dir}")

    yymmdd = match.group(1)
    hhmmss = match.group(2)

    # yy를 yyyy로 변환 (20xx 또는 19xx 판단)
    yy = int(yymmdd[:2])
    if yy >= 50:
        yyyy = f"19{yymmdd[:2]}"
    else:
        yyyy = f"20{yymmdd[:2]}"

    yyyymmdd = yyyy + yymmdd[2:]

    return yyyymmdd, hhmmss


def detect_band_config(input_dir: str) -> dict:
    """
    디렉토리에 있는 파일을 확인하여 8밴드인지 4밴드인지 판단
    """
    # 8밴드 파일 모두 존재하는지 확인
    all_8_exist = all(
        os.path.exists(os.path.join(input_dir, f))
        for f in BANDS_8['files']
    )

    if all_8_exist:
        return BANDS_8

    # 4밴드 파일 모두 존재하는지 확인
    all_4_exist = all(
        os.path.exists(os.path.join(input_dir, f))
        for f in BANDS_4['files']
    )

    if all_4_exist:
        return BANDS_4

    # 3밴드 파일 모두 존재하는지 확인
    all_3_exist = all(
        os.path.exists(os.path.join(input_dir, f))
        for f in BANDS_3['files']
    )

    if all_3_exist:
        return BANDS_3

    # 어떤 파일이 있는지 확인
    existing = [f for f in BANDS_8['files'] if os.path.exists(os.path.join(input_dir, f))]
    raise ValueError(
        f"필요한 TIFF 파일이 없습니다.\n"
        f"8밴드: MS0~MS7 필요\n"
        f"4밴드: MS1, MS2, MS3, MS7 필요\n"
        f"3밴드: MS1, MS2, MS3 필요\n"
        f"존재하는 파일: {existing}"
    )


def merge_bands(input_dir: str):
    """
    입력 디렉토리의 TIFF 파일을 하나의 멀티밴드 TIFF로 합침
    """
    input_dir = os.path.abspath(input_dir)

    # 밴드 설정 자동 감지
    band_config = detect_band_config(input_dir)
    num_bands = len(band_config['indices'])

    # 날짜/시간 추출
    yyyymmdd, hhmmss = extract_datetime_from_path(input_dir)

    # 출력 파일명 생성
    output_filename = f"bb_l1a_{yyyymmdd}_{hhmmss}_{num_bands}band.tiff"
    output_path = os.path.join(input_dir, output_filename)

    band_names = band_config['names']
    files = band_config['files']

    # 첫 번째 파일로 메타데이터 확인
    with rasterio.open(os.path.join(input_dir, files[0])) as src:
        print(f"입력 디렉토리: {input_dir}")
        print(f"감지된 밴드 수: {num_bands}")
        print(f"원본 파일 정보:")
        print(f"  크기: {src.width} x {src.height}")
        print(f"  데이터 타입: {src.dtypes[0]}")
        print(f"  CRS: {src.crs}")

        meta = src.meta.copy()
        meta.update(count=num_bands)

        print(f"\n밴드 합치는 중...")
        with rasterio.open(output_path, 'w', **meta) as dst:
            for i, (fname, bname) in enumerate(zip(files, band_names)):
                fpath = os.path.join(input_dir, fname)
                print(f"  밴드 {i}: {bname} <- {fname}")
                with rasterio.open(fpath) as band_src:
                    data = band_src.read(1)
                    dst.write(data, i + 1)  # rasterio는 1-based index

            # 밴드 설명 추가
            dst.descriptions = tuple(band_names)

    print(f"\n완료!")
    print(f"출력 파일: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='단일밴드 TIFF 파일을 멀티밴드 TIFF로 합침 (8밴드 또는 4밴드 자동 감지)'
    )
    parser.add_argument(
        'input_dir',
        help='TIFF 파일이 있는 디렉토리 (경로에 yymmdd_HHMMSS 패턴 포함 필요)'
    )

    args = parser.parse_args()
    merge_bands(args.input_dir)


if __name__ == "__main__":
    main()
