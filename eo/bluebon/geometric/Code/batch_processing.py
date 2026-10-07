#!/usr/bin/env python3
"""
BlueBON 배치 기하보정 처리 스크립트
=====================================

All_data 폴더의 TIFF 영상들을 Excel 좌표와 매칭하여 배치 단위로 기하보정 처리

사용법:
    python batch_processing.py --batch-count 3
    python batch_processing.py --dry-run  # 매칭 결과만 확인
"""

import os
import sys
import re
import argparse
import glob
from concurrent.futures import as_completed
from dataclasses import dataclass
from typing import Optional, List, Tuple

import openpyxl
import rasterio
from datetime import datetime, timedelta

# Full_processing_v2.py에서 필요한 모듈 임포트
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from pipeline_config import PipelineConfig
# Full_processing_v2 / Download_BlueBON은 실제 사용 시점에 lazy import
# (웹 서버 import 시 무거운 의존성이 즉시 로딩되는 것을 방지)

@dataclass
class MatchedData:
    """매칭된 데이터 정보"""
    excel_row: int
    capture_time: str
    target_lat: float
    target_lon: float
    tiff_path: str
    tiff_filename: str
    match_key: str  # yyyymmdd_HHMM


def parse_excel_datetime(capture_time: str) -> Optional[str]:
    """
    Excel의 Capture Start Time에서 매칭 키 추출
    
    입력: "2026-01-12T04:01:55.591(1768190515591)"
    출력: "20260112_0401"
    """
    if not capture_time:
        return None
    
    # 정규식으로 날짜/시간 추출: YYYY-MM-DDTHH:MM:SS
    pattern = r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):\d{2}'
    match = re.match(pattern, str(capture_time))
    
    if match:
        year, month, day, hour, minute = match.groups()
        return f"{year}{month}{day}_{hour}{minute}"
    
    return None


def parse_excel_datetime_dt(capture_time: str) -> Optional[datetime]:
    """
    Capture Start Time을 datetime으로 변환 (초 단위까지).
    예: "2026-01-12T04:01:55.591(1768190515591)" → 2026-01-12 04:01:55
    """
    if not capture_time:
        return None
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})', str(capture_time))
    if not m:
        return None
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
        )
    except Exception:
        return None


def parse_tiff_filename(filename: str) -> Optional[str]:
    """
    TIFF 파일명에서 매칭 키 추출
    
    입력: "bb_l1a_20260112_040151_4band.tiff"
    출력: "20260112_0401"
    """
    basename = os.path.basename(filename)
    
    # 패턴: bb_l1a_yyyymmdd_HHMMSS_Nband.tiff
    pattern = r'bb_l1a_(\d{8})_(\d{2})(\d{2})\d{2}_\d+band\.tiff?$'
    match = re.match(pattern, basename, re.IGNORECASE)
    
    if match:
        date_str = match.group(1)  # yyyymmdd
        hour = match.group(2)       # HH
        minute = match.group(3)     # MM
        return f"{date_str}_{hour}{minute}"
    
    return None


def parse_tiff_datetime_dt(filename: str) -> Optional[datetime]:
    """
    TIFF 파일명에서 촬영 시간을 datetime으로 변환 (초 단위까지).
    입력: "bb_l1a_20260112_040151_4band.tiff"
    """
    basename = os.path.basename(filename)
    m = re.match(r'bb_l1a_(\d{8})_(\d{6})_\d+band\.tiff?$', basename, re.IGNORECASE)
    if not m:
        return None
    date_str, time_str = m.group(1), m.group(2)
    try:
        return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
    except Exception:
        return None


def get_band_count_from_filename(filename: str) -> int:
    """파일명에서 밴드 수 추출"""
    basename = os.path.basename(filename)
    match = re.search(r'(\d+)band', basename, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0


def parse_tiff_metadata(filename: str) -> dict:
    """TIFF 파일명에서 메타데이터 추출"""
    basename = os.path.basename(filename)
    pattern = r'bb_([a-zA-Z0-9]+)_(\d{8})_(\d{6})_(\d+)band\.tiff?$'
    match = re.match(pattern, basename, re.IGNORECASE)
    
    if match:
        return {
            'level': match.group(1),
            'date': match.group(2),
            'time': match.group(3),
            'band_count': int(match.group(4))
        }
    return None


def _normalize_perform(value) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def load_sheet_data(sheet_path: str, only_perform_o: bool = True) -> List[dict]:
    """
    좌표/시간 시트 데이터 로드

    지원:
    - xlsx: 기존 openpyxl 방식 (A: Capture Start Time, B: Target Latitude, C: Target Longitude, (옵션) Perform)
    - csv : Download_BlueBON.py가 저장하는 Dataset/BlueBON_Geometric_Correction.csv (헤더 기반)
    """
    sheet_path = os.path.abspath(sheet_path)
    if not os.path.exists(sheet_path):
        raise FileNotFoundError(f"시트 파일을 찾을 수 없습니다: {sheet_path}")

    ext = os.path.splitext(sheet_path)[1].lower()
    data: List[dict] = []

    if ext in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
        wb = openpyxl.load_workbook(sheet_path)
        ws = wb.active
        # 헤더 탐색 (가능하면 Perform 컬럼도 찾음)
        header = [c.value for c in ws[1]]
        perform_col = None
        for idx, name in enumerate(header, start=1):
            if name and str(name).strip().lower() == "perform":
                perform_col = idx
                break

        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
            capture_time = row[0].value  # A: Capture Start Time
            target_lat = row[1].value    # B: Target Latitude
            target_lon = row[2].value    # C: Target Longitude
            perform_val = None
            if perform_col is not None and perform_col - 1 < len(row):
                perform_val = row[perform_col - 1].value

            if only_perform_o and perform_col is not None:
                if _normalize_perform(perform_val) != "o":
                    continue

            if capture_time and target_lat is not None and target_lon is not None:
                data.append({
                    "row": row_idx,
                    "capture_time": str(capture_time),
                    "target_lat": float(target_lat),
                    "target_lon": float(target_lon),
                    "perform": perform_col is None or _normalize_perform(perform_val) == "o",
                })
        wb.close()
        return data

    if ext == ".csv":
        # pandas 의존성 없이 csv 읽기
        import csv
        with open(sheet_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # DictReader가 헤더를 못 읽는 경우 방어
            if not reader.fieldnames:
                raise ValueError(f"CSV 헤더를 읽을 수 없습니다: {sheet_path}")

            for i, row in enumerate(reader, start=2):  # 헤더 다음 줄을 2로 취급
                if only_perform_o:
                    if _normalize_perform(row.get("Perform")) != "o":
                        continue

                capture_time = row.get("Capture Start Time") or row.get("CaptureStartTime") or row.get("capture_time")
                target_lat = row.get("Target Latitude") or row.get("TargetLatitude") or row.get("target_lat")
                target_lon = row.get("Target Longitude") or row.get("TargetLongitude") or row.get("target_lon")

                if capture_time and target_lat is not None and target_lon is not None:
                    try:
                        data.append({
                            "row": i,
                            "capture_time": str(capture_time),
                            "target_lat": float(target_lat),
                            "target_lon": float(target_lon),
                            "perform": _normalize_perform(row.get("Perform", "o")) == "o",
                        })
                    except ValueError:
                        # 숫자 변환 실패 행은 스킵
                        continue
        return data

    raise ValueError(f"지원하지 않는 시트 확장자입니다: {ext} (지원: .csv, .xlsx)")


def scan_tiff_files(tiff_dir: str) -> dict:
    """TIFF 폴더 스캔하여 매칭 키별로 인덱싱"""
    tiff_index = {}

    patterns = [
        os.path.join(tiff_dir, "bb_l1a_*.tif"),
        os.path.join(tiff_dir, "bb_l1a_*.tiff"),
        os.path.join(tiff_dir, "bb_l1a_*.TIF"),
        os.path.join(tiff_dir, "bb_l1a_*.TIFF"),
    ]
    for pat in patterns:
        for tiff_path in glob.glob(pat):
            match_key = parse_tiff_filename(tiff_path)
            if match_key:
                # 동일 키가 여러 개면 최신 파일 우선(파일명 기준)
                if match_key not in tiff_index or os.path.basename(tiff_path) > os.path.basename(tiff_index[match_key]):
                    tiff_index[match_key] = tiff_path
    
    return tiff_index


def match_excel_tiff(excel_data: List[dict], tiff_index: dict, tolerance_sec: int = 600) -> List[MatchedData]:
    """
    시트 데이터와 TIFF 파일 매칭

    - 1차: 분 단위 키(yyyymmdd_HHMM)로 정확 매칭
    - 2차: 허용 오차(tolerance_sec) 내에서 가장 가까운 TIFF 선택
    """
    matched = []

    # 2차 매칭용: TIFF datetime 리스트 구성
    tiff_dt_list: List[Tuple[datetime, str]] = []
    for _, path in tiff_index.items():
        dt = parse_tiff_datetime_dt(path)
        if dt:
            tiff_dt_list.append((dt, path))
    tiff_dt_list.sort(key=lambda x: x[0])
    
    for item in excel_data:
        match_key = parse_excel_datetime(item['capture_time'])

        tiff_path = None
        if match_key and match_key in tiff_index:
            tiff_path = tiff_index[match_key]
        else:
            # 2차: tolerance 내 최인접 선택
            sheet_dt = parse_excel_datetime_dt(item.get("capture_time"))
            if sheet_dt and tiff_dt_list:
                tol = timedelta(seconds=int(tolerance_sec))
                best_path = None
                best_diff = None
                for dt, path in tiff_dt_list:
                    diff = abs(dt - sheet_dt)
                    if diff <= tol and (best_diff is None or diff < best_diff):
                        best_diff = diff
                        best_path = path
                tiff_path = best_path

        if tiff_path:
            used_key = parse_tiff_filename(tiff_path) or (match_key or "unknown")
            matched.append(MatchedData(
                excel_row=item['row'],
                capture_time=item['capture_time'],
                target_lat=item['target_lat'],
                target_lon=item['target_lon'],
                tiff_path=tiff_path,
                tiff_filename=os.path.basename(tiff_path),
                match_key=used_key
            ))
    
    return matched


def create_pipeline_config(matched: MatchedData) -> PipelineConfig:
    """매칭된 데이터로 PipelineConfig 생성"""
    metadata = parse_tiff_metadata(matched.tiff_path)
    
    if not metadata:
        # 파일에서 밴드 수 직접 확인
        band_count = get_band_count_from_filename(matched.tiff_path)
        if band_count == 0:
            with rasterio.open(matched.tiff_path) as src:
                band_count = src.count
        metadata = {
            'level': 'l1a',
            'date': matched.match_key.split('_')[0],
            'time': matched.match_key.split('_')[1] + '00',
            'band_count': band_count
        }
    
    return PipelineConfig(
        input_path=matched.tiff_path,
        level=metadata['level'],
        date=metadata['date'],
        time=metadata['time'],
        band_count=metadata['band_count'],
        center_lat=matched.target_lat,
        center_lon=matched.target_lon,
        num_segments=3,  # 영상 분할 3개로 고정
        save_intermediate=True  # 중간 결과물 저장
    )


def process_single_image(matched: MatchedData, output_base_dir: str) -> Tuple[int, Optional[Tuple[float, float]]]:
    """
    단일 영상 처리
    
    Returns:
        (excel_row, (actual_lat, actual_lon)) or (excel_row, None) if failed
    """
    try:
        print(f"\n{'='*60}")
        print(f"Processing: {matched.tiff_filename}")
        print(f"  Target coords: ({matched.target_lat}, {matched.target_lon})")
        print(f"{'='*60}")
        
        config = create_pipeline_config(matched)
        
        # 출력 디렉토리 설정 (output 폴더 아래)
        metadata = parse_tiff_metadata(matched.tiff_path)
        if metadata:
            output_folder = f"bb_{metadata['level']}_{metadata['date']}_{metadata['time']}_{metadata['band_count']}band"
        else:
            output_folder = os.path.splitext(matched.tiff_filename)[0]
        
        # 출력 경로를 output_base_dir로 변경하기 위해 input_path의 디렉토리를 임시 변경
        # Full_processing_v2.py는 input_path 기준으로 출력 폴더를 만드므로,
        # 별도의 방식으로 처리해야 함
        
        # 파이프라인 실행
        from Full_processing_v2 import main as run_pipeline
        run_pipeline(config)
        
        # 모자이킹 결과물에서 중심 좌표 읽기
        input_dir = os.path.dirname(matched.tiff_path)
        result_dir = os.path.join(input_dir, output_folder)

        # bb_l1c_*_*band.tiff 형식의 모자이킹 결과 찾기
        mosaic_files = glob.glob(os.path.join(result_dir, "bb_l1c_*.tiff"))
        if mosaic_files:
            mosaic_path = mosaic_files[0]
            # 중심 좌표 추출 (CRS → EPSG:4326 변환)
            from rasterio.warp import transform as warp_transform_xy
            with rasterio.open(mosaic_path) as src:
                width = src.width
                height = src.height
                center_col = width / 2.0
                center_row = height / 2.0
                center_x, center_y = src.transform * (center_col, center_row)
                lons, lats = warp_transform_xy(src.crs, "EPSG:4326", [center_x], [center_y])
                center_lat, center_lon = round(lats[0], 8), round(lons[0], 8)

            print(f"  ✅ 완료: 중심 좌표 ({center_lat:.6f}, {center_lon:.6f})")
            return (matched.excel_row, (center_lat, center_lon))
        
        print(f"  ⚠️ 모자이킹 결과물을 찾을 수 없습니다")
        return (matched.excel_row, None)
        
    except Exception as e:
        print(f"  ❌ 처리 실패: {e}")
        import traceback
        traceback.print_exc()
        return (matched.excel_row, None)


def update_excel_with_results(excel_path: str, results: List[Tuple[int, Optional[Tuple[float, float]]]]):
    """xlsx 파일에 actual latitude/longitude 업데이트"""
    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active

    existing_cols = [cell.value for cell in ws[1]]
    lat_col = lon_col = None
    for idx, col_name in enumerate(existing_cols, start=1):
        n = str(col_name or '').lower()
        if 'actual' in n and 'lat' in n:
            lat_col = idx
        if 'actual' in n and 'lon' in n:
            lon_col = idx

    if lat_col is None:
        lat_col = len(existing_cols) + 1
        ws.cell(row=1, column=lat_col, value="Actual\nLatitude")
    if lon_col is None:
        lon_col = len(existing_cols) + 2 if lat_col == len(existing_cols) + 1 else len(existing_cols) + 1
        ws.cell(row=1, column=lon_col, value="Actual\nLongitude")

    updated_count = 0
    for excel_row, coords in results:
        if coords:
            actual_lat, actual_lon = coords
            ws.cell(row=excel_row, column=lat_col, value=actual_lat)
            ws.cell(row=excel_row, column=lon_col, value=actual_lon)
            updated_count += 1

    wb.save(excel_path)
    wb.close()
    print(f"\n✅ Excel 업데이트 완료: {updated_count}개 행")


def update_csv_with_results(csv_path: str, results: List[Tuple[int, Optional[Tuple[float, float]]]]):
    """CSV 파일에 actual latitude/longitude 업데이트"""
    import csv as _csv

    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        rows = list(_csv.reader(f))
    if not rows:
        return

    header = rows[0]
    lat_col = lon_col = None
    for i, name in enumerate(header):
        n = str(name or '').strip().lower().replace('\n', ' ')
        if 'actual' in n and 'lat' in n:
            lat_col = i
        if 'actual' in n and 'lon' in n:
            lon_col = i

    if lat_col is None:
        lat_col = len(header)
        header.append("Actual\nLatitude")
        rows[0] = header
    if lon_col is None:
        lon_col = len(header)
        header.append("Actual\nLongitude")
        rows[0] = header

    updated_count = 0
    for excel_row, coords in results:
        if coords and 0 < excel_row - 1 < len(rows):
            actual_lat, actual_lon = coords
            row = rows[excel_row - 1]
            while len(row) <= max(lat_col, lon_col):
                row.append('')
            row[lat_col] = str(actual_lat)
            row[lon_col] = str(actual_lon)
            rows[excel_row - 1] = row
            updated_count += 1

    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        _csv.writer(f).writerows(rows)
    print(f"\n✅ CSV 업데이트 완료: {updated_count}개 행")


def main():
    parser = argparse.ArgumentParser(description='BlueBON 배치 기하보정 처리')
    parser.add_argument('--batch-count', type=int, default=1,
                        help='동시에 처리할 배치 개수 (기본값: 1)')
    parser.add_argument('--dry-run', action='store_true',
                        help='매칭 결과만 출력하고 실제 처리는 하지 않음')
    parser.add_argument('--sheet', type=str,
                        #default=os.path.join(SCRIPT_DIR, "..", "Dataset", "BlueBON_Geometric_Correction.csv"),
                        default='/mnt/hdd/BB/BlueBON_Geometric_Correction.csv',
                        help='좌표/시간 시트 파일 경로 (.csv 또는 .xlsx). 기본: /mnt/hdd/BB/BlueBON_Geometric_Correction.csv')
    parser.add_argument('--no-download', action='store_true',
                        help='시트/영상 자동 다운로드를 건너뜀 (Dataset에 이미 파일이 있을 때)')
    parser.add_argument('--only-perform-o', action='store_true',
                        help="시트의 Perform 컬럼이 'o'인 행만 처리 (기본: CSV는 자동으로 적용, XLSX는 Perform 컬럼이 있을 때만 적용)")
    parser.add_argument('--tiff-dir', type=str,
                        default='/mnt/hdd/BB',
                        help='TIFF 파일 폴더 경로')
    parser.add_argument('--match-window-sec', type=int, default=600,
                        help='시트 시간과 파일명 시간 매칭 허용 오차(초). 기본: 600(±10분)')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='출력 폴더 경로 (기본값: TIFF 폴더와 동일)')
    
    args = parser.parse_args()
    
    # 경로 정규화
    sheet_path = os.path.abspath(args.sheet)
    tiff_dir = os.path.abspath(args.tiff_dir)
    output_dir = os.path.abspath(args.output_dir) if args.output_dir else tiff_dir
    
    print("=" * 60)
    print("🛰️ BlueBON 배치 기하보정 처리")
    print("=" * 60)
    # print(f"  Excel 파일: {excel_path}")
    print(f"  TIFF 폴더: {tiff_dir}")
    print(f"  시트 파일: {sheet_path}")
    print(f"  배치 개수: {args.batch_count}")
    print(f"  Dry-run: {args.dry_run}")
    print()
    if not args.no_download:
        from Download_BlueBON import run as download_bluebon
        download_bluebon(save_dir=tiff_dir)
    
    # 파일 확인
    if not os.path.exists(sheet_path):
        print(f"❌ 시트 파일을 찾을 수 없습니다: {sheet_path}")
        sys.exit(1)
    if not os.path.isdir(tiff_dir):
        print(f"❌ TIFF 폴더를 찾을 수 없습니다: {tiff_dir}")
        sys.exit(1)
    
    # 데이터 로드
    print("📊 시트 데이터 로드 중...")
    only_perform_o = args.only_perform_o
    # CSV는 Download_BlueBON에서 Perform='o'만 처리하도록 설계되어 있어 기본적으로 필터링되는 것이 안전
    if os.path.splitext(sheet_path)[1].lower() == ".csv" and not args.only_perform_o:
        only_perform_o = True
    sheet_data = load_sheet_data(sheet_path, only_perform_o=only_perform_o)
    print(f"  ✓ {len(sheet_data)}개 행 로드")
    
    print("📁 TIFF 파일 스캔 중...")
    tiff_index = scan_tiff_files(tiff_dir)
    print(f"  ✓ {len(tiff_index)}개 파일 발견")
    
    # 매칭
    print("🔗 Excel-TIFF 매칭 중...")
    matched_list = match_excel_tiff(sheet_data, tiff_index, tolerance_sec=args.match_window_sec)
    print(f"  ✓ {len(matched_list)}개 매칭 성공")
    print(f"  ✗ {len(sheet_data) - len(matched_list)}개 매칭 실패 (스킵)")
    
    if args.dry_run:
        print("\n📋 매칭 결과:")
        print("-" * 80)
        for m in matched_list[:20]:  # 처음 20개만 출력
            print(f"  [{m.match_key}] {m.tiff_filename}")
            print(f"    └─ 좌표: ({m.target_lat}, {m.target_lon})")
        if len(matched_list) > 20:
            print(f"  ... 외 {len(matched_list) - 20}개")
        return
    
    if not matched_list:
        print("\n⚠️ 처리할 데이터가 없습니다.")
        return
    
    # 병렬 배치 처리
    print(f"\n🚀 배치 처리 시작 (동시 {args.batch_count}개)")
    print("-" * 60)
    
    results = []
    
    # ThreadPoolExecutor로 병렬 처리
    # (ProcessPoolExecutor는 Earth Engine 세션 공유 문제로 사용 불가)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    with ThreadPoolExecutor(max_workers=args.batch_count) as executor:
        # 모든 작업 제출
        future_to_matched = {
            executor.submit(process_single_image, matched, output_dir): matched 
            for matched in matched_list
        }
        
        completed_count = 0
        for future in as_completed(future_to_matched):
            matched = future_to_matched[future]
            completed_count += 1
            
            try:
                result = future.result()
                results.append(result)
                print(f"\n[{completed_count}/{len(matched_list)}] 완료: {matched.tiff_filename}")
            except Exception as e:
                print(f"\n[{completed_count}/{len(matched_list)}] ❌ 실패: {matched.tiff_filename} - {e}")
                results.append((matched.excel_row, None))
            
            # 매 배치마다 시트 업데이트 (중간 저장)
            if completed_count % args.batch_count == 0 or completed_count == len(matched_list):
                print(f"\n📝 시트 중간 저장 ({completed_count}/{len(matched_list)})...")
                if os.path.splitext(sheet_path)[1].lower() == ".csv":
                    update_csv_with_results(sheet_path, results)
                else:
                    update_excel_with_results(sheet_path, results)
    
    # 최종 결과 요약
    success_count = sum(1 for _, coords in results if coords is not None)
    print("\n" + "=" * 60)
    print("✅ 배치 처리 완료")
    print("=" * 60)
    print(f"  전체: {len(matched_list)}개")
    print(f"  성공: {success_count}개")
    print(f"  실패: {len(matched_list) - success_count}개")


if __name__ == "__main__":
    main()
