import pandas as pd
import subprocess
import os
import io
import requests
import re
from datetime import datetime

# --- 설정 ---
SHEET_ID = os.environ.get("BLUEBON_SHEET_ID", "")
REMOTE_NAME = "LEOP"
BASE_SUB_PATH = "LEOP/"  # 아까 lsf 결과에서 확인한 하위 폴더
BANDS = ["8band", "4band", "3band"]
TIME_WINDOW = 600
# -----------

def _http_get_with_retry(url: str, timeout_sec: int = 60, max_attempts: int = 6) -> requests.Response:
    """
    Google Sheets export가 간헐적으로 429/5xx를 내거나 느릴 때를 대비한 재시도.
    """
    import time
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.get(url, timeout=timeout_sec)
            # 429/5xx는 백오프 후 재시도
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            sleep_sec = min(60, 2 ** (attempt - 1))
            print(f"⚠️ 시트 다운로드 재시도 {attempt}/{max_attempts} (대기 {sleep_sec}s): {e}")
            time.sleep(sleep_sec)
    raise RuntimeError(f"시트 다운로드 실패: {last_exc}")


def _rclone_run(cmd: list, max_attempts: int = 6):
    """
    rclone이 rate limit(429) 또는 네트워크 오류로 백오프가 길어질 때를 대비해
    - timeout / retries 옵션을 기본으로 붙이고
    - 실패 시 지수 백오프로 재시도
    """
    import time
    base_cmd = [
        "rclone",
        "--retries", "10",
        "--low-level-retries", "20",
        "--contimeout", "30s",
        "--timeout", "10m",
        "--tpslimit", "4",
        "--tpslimit-burst", "4",
    ]
    last = None
    for attempt in range(1, max_attempts + 1):
        try:
            return subprocess.run(base_cmd + cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            last = e
            err = (e.stderr or "")[-400:]
            sleep_sec = min(120, 2 ** (attempt - 1))
            print(f"⚠️ rclone 재시도 {attempt}/{max_attempts} (대기 {sleep_sec}s): {err}")
            time.sleep(sleep_sec)
    raise RuntimeError(f"rclone 실패: {last.stderr if last else ''}")


def parse_dt(text):
    """시트 형식(2026-03-25T...)과 파일명 형식(260325_094532) 모두 대응"""
    text = str(text).strip()
    
    # 1. 시트 형식 대응: 2026-03-25T09:45:32
    iso_match = re.search(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})', text)
    if iso_match:
        try:
            # 2026-03-25T09:45:32 형태를 datetime 객체로 변환
            return datetime.strptime(iso_match.group(0), "%Y-%m-%dT%H:%M:%S")
        except: pass

    # 2. 파일명/폴더명 형식 대응: 260325_094532
    underscore_match = re.search(r'(\d{6})_(\d{6})', text)
    if underscore_match:
        try:
            return datetime.strptime(underscore_match.group(0), "%y%m%d_%H%M%S")
        except: pass
        
    return None

def _download_one(raw_time: str, all_folders: list, save_dir: str):
    """단일 타겟 다운로드 (병렬 호출용)."""
    sheet_dt = parse_dt(raw_time)
    if not sheet_dt:
        print(f"❌ 시간 해석 실패: {raw_time} (건너뜁니다)")
        return

    print(f"\n🎯 타겟: {sheet_dt.strftime('%Y-%m-%d %H:%M:%S')} -> 검색 시작")

    best_folder = None
    min_diff = TIME_WINDOW + 1
    for folder_name in all_folders:
        folder_dt = parse_dt(folder_name)
        if folder_dt:
            diff = abs((sheet_dt - folder_dt).total_seconds())
            if diff <= TIME_WINDOW and diff < min_diff:
                min_diff = diff
                best_folder = folder_name

    if not best_folder:
        print(f"   ❌ {TIME_WINDOW}초 이내 폴더 없음")
        return

    print(f"   📂 폴더 매칭: {best_folder} (차이: {int(min_diff)}초)")

    search_path = f"{REMOTE_NAME}:{BASE_SUB_PATH}{best_folder}/level-1A/"
    ls_files = _rclone_run(["lsf", search_path])
    all_files = ls_files.stdout.splitlines()

    best_file = None
    file_min_diff = TIME_WINDOW + 1
    for band in BANDS:
        for file_name in all_files:
            if band in file_name:
                file_dt = parse_dt(file_name)
                if file_dt:
                    diff = abs((sheet_dt - file_dt).total_seconds())
                    if diff <= TIME_WINDOW and diff < file_min_diff:
                        file_min_diff = diff
                        best_file = file_name

    if best_file:
        print(f"   🎯 파일 매칭: {best_file} (차이: {int(file_min_diff)}초)")
        _rclone_run(["copy", f"{search_path}{best_file}", save_dir, "-P", "--ignore-existing"])
        print(f"   ✅ 다운로드 완료: {best_file}")
    else:
        print(f"   ❌ 일치하는 8/4/3band 파일 없음")


def _download_targets(capture_times: list, save_dir: str, max_workers: int = 3):
    """
    capture_times: list of capture time strings (from state.rows)
    구글 드라이브에서 해당 시간대 TIFF를 병렬로 다운로드.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    os.makedirs(save_dir, exist_ok=True)

    # 폴더 목록은 1회만 조회 (공유 read-only)
    print(f">>> Google Drive {REMOTE_NAME}:{BASE_SUB_PATH} 폴더 스캔 중...")
    ls_folders = _rclone_run(["lsf", f"{REMOTE_NAME}:{BASE_SUB_PATH}", "--dirs-only"])
    all_folders = [f.strip('/') for f in ls_folders.stdout.splitlines()]
    print(f"   드라이브 폴더 {len(all_folders)}개 발견, 타겟 {len(capture_times)}개 병렬 다운로드 시작 (workers={max_workers})")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_download_one, t, all_folders, save_dir): t
            for t in capture_times
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"   ❌ 다운로드 오류: {e}")


def run_for_targets(capture_times: list, save_dir: str = "/mnt/hdd/BB", max_workers: int = 3):
    """웹 앱에서 호출: state.rows의 perform=True 행 capture_time 리스트를 받아 병렬 다운로드."""
    if not capture_times:
        print("⚠️ 다운로드할 항목이 없습니다 (Perform 체크된 행 없음)")
        return
    print(f">>> 다운로드 대상: {len(capture_times)}개")
    _download_targets(capture_times, save_dir, max_workers=max_workers)


def run(save_dir: str = "/mnt/hdd/BB"):
    print(">>> [1단계] 구글 시트 데이터 읽기...")
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
    
    try:
        response = _http_get_with_retry(url, timeout_sec=60, max_attempts=6)
        # 헤더 자동 찾기 (Perform 컬럼 기준)
        temp_df = pd.read_csv(io.StringIO(response.text), header=None)
        header_row = -1
        for i, row in temp_df.iterrows():
            if "Perform" in row.values:
                header_row = i
                break
        if header_row == -1:
            print("❌ 시트에서 'Perform' 컬럼을 찾을 수 없습니다."); return
            
        df = pd.read_csv(io.StringIO(response.text), skiprows=header_row)
        df.columns = df.columns.str.strip()
    except Exception as e:
        print(f"❌ 시트 읽기 실패: {e}"); return

    # csv 저장
    os.makedirs(save_dir, exist_ok=True)
    csv_path = os.path.join(save_dir, "BlueBON_Geometric_Correction.csv")
    df.to_csv(csv_path, index=False)
    print(f"✅ CSV 저장 완료: {csv_path}")


    # 드라이브 폴더 스캔
    print(f">>> {REMOTE_NAME}:{BASE_SUB_PATH} 안에서 날짜 폴더 스캔 중...")
    ls_folders = _rclone_run(["lsf", f"{REMOTE_NAME}:{BASE_SUB_PATH}", "--dirs-only"])
    all_folders = [f.strip('/') for f in ls_folders.stdout.splitlines()]
    
    # 'Perform' 열에 'o' 표시된 행만 필터링
    targets = df[df['Perform'].astype(str).str.strip().str.lower() == 'o']
    
    if targets.empty:
        print("⚠️ 'o'로 표시된 항목이 없습니다."); return

    for _, row in targets.iterrows():
        raw_time = row['Capture Start Time']
        sheet_dt = parse_dt(raw_time)
        
        if not sheet_dt:
            print(f"❌ 시간 해석 실패: {raw_time} (이 데이터는 건너뜁니다)")
            continue

        print(f"\n🎯 시트 타겟: {sheet_dt.strftime('%Y-%m-%d %H:%M:%S')} -> 검색 시작")

        # 1. 가장 가까운 폴더 찾기
        best_folder = None
        min_diff = TIME_WINDOW + 1
        
        for folder_name in all_folders:
            folder_dt = parse_dt(folder_name)
            if folder_dt:
                diff = abs((sheet_dt - folder_dt).total_seconds())
                if diff <= TIME_WINDOW and diff < min_diff:
                    min_diff = diff
                    best_folder = folder_name

        if not best_folder:
            print(f"   ❌ {TIME_WINDOW}초 이내 폴더 없음")
            continue

        print(f"   📂 폴더 매칭: {best_folder} (차이: {int(min_diff)}초)")

        # 2. 파일 찾기
        search_path = f"{REMOTE_NAME}:{BASE_SUB_PATH}{best_folder}/level-1A/"
        ls_files = _rclone_run(["lsf", search_path])
        all_files = ls_files.stdout.splitlines()

        best_file = None
        file_min_diff = TIME_WINDOW + 1
        
        for band in BANDS:
            for file_name in all_files:
                if band in file_name:
                    file_dt = parse_dt(file_name)
                    if file_dt:
                        diff = abs((sheet_dt - file_dt).total_seconds())
                        if diff <= TIME_WINDOW and diff < file_min_diff:
                            file_min_diff = diff
                            best_file = file_name

        if best_file:
            print(f"   🎯 파일 매칭: {best_file} (차이: {int(file_min_diff)}초)")
            # 이미 같은 파일이 있으면 다시 받지 않도록 --ignore-existing
            _rclone_run(["copy", f"{search_path}{best_file}", save_dir, "-P", "--ignore-existing"])
        else:
            print(f"   ❌ 일치하는 8/4/3band 파일 없음")

if __name__ == "__main__":
    run()