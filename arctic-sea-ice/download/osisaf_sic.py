#!/usr/bin/env python3
"""
OSISAF 해빙 농도(Sea Ice Concentration) 자동 다운로드 스크립트 v2
==============================================================
- 대상: Northern Hemisphere (NH)
- 기간: 2012년 1월 ~ 2026년 4월, 매달 15일
- FTP 서버: osisaf.met.no (익명 접속)
- 경로: /archive/ice/conc/YYYY/MM/

[ 파일명 패턴 정리 ]
같은 폴더 안에 여러 형식의 파일이 혼재합니다:

 1) 구형 (짧은 이름, HDF)
    ice_conc_nh_YYYYMMDD1200.hdf

 2) 구형 품질 파일 (다운로드 대상 아님!)
    ice_conc_nh_qual_YYYYMMDD1200.hdf

 3) 신형 (긴 이름, polstere, NC)
    ice_conc_nh_polstere-100_multi_YYYYMMDD1200.nc

 4) 신형 (긴 이름, polstere, HDF5) - 과도기
    ice_conc_nh_polstere-100_multi_YYYYMMDD1200.hdf5

 5) GRIB 파일 (다운로드 대상 아님)
    ice_conc_nh_YYYYMMDD1200.grb 등

[ 다운로드 우선순위 ]
  polstere NC > polstere HDF5 > 짧은이름 HDF
  (_qual_, _grb 등은 항상 제외)

이 스크립트는 FTP 디렉토리를 실제로 스캔하여 해당 날짜의 NH 파일 중
가장 적합한 것을 자동으로 선택합니다.
"""

import os
import re
import sys
import time
import logging
from ftplib import FTP, error_perm, error_temp
from datetime import date

# ============================================================
# 설정 (필요에 따라 수정하세요)
# ============================================================
FTP_HOST = "osisaf.met.no"
FTP_BASE_DIR = "/archive/ice/conc"
LOCAL_DOWNLOAD_DIR = "<DATA_ROOT>\14_NSR\OSI_SAF\conc"   # ← 원하는 경로로 변경

START_YEAR = 2012
START_MONTH = 1
END_YEAR = 2026
END_MONTH = 4
DAY = 15                                  # 매달 15일

MAX_RETRIES = 3
RETRY_DELAY = 5    # 초
DOWNLOAD_DELAY = 1  # 파일 간 대기 (서버 부하 방지)

# ============================================================
# 로깅 설정
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("download_log.txt", encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)


# ============================================================
# FTP 연결 관리
# ============================================================
class FTPManager:
    """FTP 연결 관리 (자동 재연결 포함)"""

    def __init__(self, host, timeout=60):
        self.host = host
        self.timeout = timeout
        self.ftp = None

    def connect(self):
        """FTP 연결 및 익명 로그인"""
        if self.ftp:
            try:
                self.ftp.quit()
            except:
                pass
        log.info(f"FTP 연결 중: {self.host}")
        self.ftp = FTP(self.host, timeout=self.timeout)
        self.ftp.login()
        log.info("FTP 연결 성공 (익명 로그인)")
        return self.ftp

    def ensure_connected(self):
        """연결 상태 확인, 끊어졌으면 재연결"""
        try:
            self.ftp.voidcmd("NOOP")
        except:
            self.connect()
        return self.ftp

    def close(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except:
                pass


# ============================================================
# 파일 선택 로직
# ============================================================
def find_best_file(file_list: list, target_date: date) -> str | None:
    """
    FTP 디렉토리의 파일 목록에서 해당 날짜의 NH 해빙농도 파일 중
    가장 적합한 것을 선택합니다.

    우선순위:
      1. ice_conc_nh_polstere-100_multi_YYYYMMDD1200.nc
      2. ice_conc_nh_polstere-100_multi_YYYYMMDD1200.hdf5
      3. ice_conc_nh_YYYYMMDD1200.hdf
      4. ice_conc_nh_YYYYMMDD1200.nc  (혹시 존재할 경우)

    제외:
      - _qual_ 포함 (품질 플래그 파일)
      - _grb / .grb (GRIB 파일)
      - _sh_ (남반구)
    """
    datestr = target_date.strftime("%Y%m%d")

    # 제외 키워드
    exclude_patterns = ["_qual_", "_sh_", "_edge_", "_type_", "_emis_"]

    # 해당 날짜 + NH 파일만 필터링
    candidates = []
    for fname in file_list:
        fname_lower = fname.lower()

        # 기본 조건: 날짜 포함, NH 포함
        if datestr not in fname:
            continue
        if "_nh_" not in fname_lower and "_nh_" not in fname:
            continue

        # 제외 패턴
        if any(ex in fname_lower for ex in exclude_patterns):
            continue

        # .grb 제외
        if fname_lower.endswith(".grb") or fname_lower.endswith(".grib"):
            continue

        candidates.append(fname)

    if not candidates:
        return None

    # 우선순위 점수 매기기
    def priority_score(fname):
        fname_lower = fname.lower()
        # polstere + nc = 최우선
        if "polstere" in fname_lower and fname_lower.endswith(".nc"):
            return 0
        # polstere + hdf5 = 2순위
        if "polstere" in fname_lower and fname_lower.endswith(".hdf5"):
            return 1
        # 짧은이름 + nc
        if fname_lower.endswith(".nc"):
            return 2
        # 짧은이름 + hdf
        if fname_lower.endswith(".hdf"):
            return 3
        # hdf5 (polstere 없는 경우)
        if fname_lower.endswith(".hdf5"):
            return 4
        # 기타
        return 99

    candidates.sort(key=priority_score)
    return candidates[0]


# ============================================================
# 디렉토리 목록 캐싱 (같은 월은 한 번만 스캔)
# ============================================================
dir_cache = {}

def list_ftp_dir(ftp_mgr: FTPManager, remote_dir: str) -> list:
    """FTP 디렉토리 파일 목록을 가져오고 캐싱합니다."""
    if remote_dir in dir_cache:
        return dir_cache[remote_dir]

    ftp = ftp_mgr.ensure_connected()
    try:
        files = ftp.nlst(remote_dir)
        # nlst는 전체 경로를 반환할 수 있으므로 파일명만 추출
        files = [os.path.basename(f) for f in files]
        dir_cache[remote_dir] = files
        log.info(f"  디렉토리 스캔 완료: {remote_dir} ({len(files)}개 파일)")
        return files
    except error_perm as e:
        log.warning(f"  디렉토리 접근 실패: {remote_dir} → {e}")
        dir_cache[remote_dir] = []
        return []
    except Exception as e:
        log.warning(f"  디렉토리 스캔 오류: {remote_dir} → {e}")
        ftp_mgr.connect()
        return []


# ============================================================
# 다운로드
# ============================================================
def download_file(ftp_mgr: FTPManager, remote_path: str, local_path: str) -> bool:
    """FTP에서 파일 다운로드 (재시도 포함)"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            ftp = ftp_mgr.ensure_connected()
            remote_size = ftp.size(remote_path)

            # 이미 완료된 파일 스킵
            if os.path.exists(local_path):
                local_size = os.path.getsize(local_path)
                if local_size == remote_size:
                    log.info(f"  ✓ 이미 다운로드 완료: {os.path.basename(local_path)}")
                    return True
                else:
                    log.info(f"  크기 불일치(로컬={local_size}, 원격={remote_size}) → 재다운로드")

            log.info(f"  ↓ 다운로드: {os.path.basename(remote_path)} ({remote_size:,} bytes)")
            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR {remote_path}", f.write)

            # 크기 검증
            actual = os.path.getsize(local_path)
            if actual == remote_size:
                log.info(f"  ✓ 완료: {os.path.basename(local_path)}")
                return True
            else:
                log.warning(f"  ✗ 크기 불일치 (받은={actual}, 원격={remote_size})")
                os.remove(local_path)

        except Exception as e:
            log.warning(f"  시도 {attempt}/{MAX_RETRIES} 실패: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                try:
                    ftp_mgr.connect()
                except:
                    pass

    return False


# ============================================================
# 날짜 생성
# ============================================================
def generate_target_dates():
    dates = []
    year, month = START_YEAR, START_MONTH
    while (year, month) <= (END_YEAR, END_MONTH):
        dates.append(date(year, month, DAY))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return dates


# ============================================================
# 메인
# ============================================================
def main():
    os.makedirs(LOCAL_DOWNLOAD_DIR, exist_ok=True)

    target_dates = generate_target_dates()
    total = len(target_dates)

    log.info("=" * 60)
    log.info("OSISAF NH Sea Ice Concentration 다운로드 시작")
    log.info(f"  기간: {target_dates[0]} ~ {target_dates[-1]} (매달 15일)")
    log.info(f"  총 {total}개 날짜")
    log.info(f"  저장 위치: {os.path.abspath(LOCAL_DOWNLOAD_DIR)}")
    log.info("=" * 60)

    ftp_mgr = FTPManager(FTP_HOST)
    ftp_mgr.connect()

    results = {"success": [], "skip": [], "not_found": [], "error": []}

    for idx, target in enumerate(target_dates, 1):
        year_str = target.strftime("%Y")
        month_str = target.strftime("%m")
        remote_dir = f"{FTP_BASE_DIR}/{year_str}/{month_str}"

        log.info(f"\n[{idx}/{total}] {target} 처리 중...")

        # 1) 디렉토리 스캔
        file_list = list_ftp_dir(ftp_mgr, remote_dir)
        if not file_list:
            log.warning(f"  ⚠ 디렉토리가 비어있거나 접근 불가: {remote_dir}")
            results["not_found"].append(str(target))
            continue

        # 2) 최적 파일 선택
        best_file = find_best_file(file_list, target)
        if not best_file:
            log.warning(f"  ⚠ {target}: 해당 날짜의 NH 파일을 찾을 수 없습니다.")
            log.info(f"    (참고) 디렉토리 내 파일 샘플: {file_list[:5]}")
            results["not_found"].append(str(target))
            continue

        log.info(f"  선택된 파일: {best_file}")

        # 3) 다운로드
        remote_path = f"{remote_dir}/{best_file}"
        local_path = os.path.join(LOCAL_DOWNLOAD_DIR, best_file)

        if download_file(ftp_mgr, remote_path, local_path):
            results["success"].append(f"{target} → {best_file}")
        else:
            log.error(f"  ✗ 다운로드 실패: {best_file}")
            results["error"].append(f"{target} → {best_file}")

        time.sleep(DOWNLOAD_DELAY)

    ftp_mgr.close()

    # ============================================================
    # 결과 요약
    # ============================================================
    print("\n" + "=" * 60)
    log.info("다운로드 완료 요약")
    log.info(f"  ✓ 성공: {len(results['success'])}건")
    log.info(f"  ⚠ 파일 없음: {len(results['not_found'])}건")
    log.info(f"  ✗ 오류: {len(results['error'])}건")

    if results["not_found"]:
        log.info(f"\n  [ 파일 없는 날짜 ]")
        for d in results["not_found"]:
            log.info(f"    - {d}")

    if results["error"]:
        log.info(f"\n  [ 다운로드 실패 ]")
        for e in results["error"]:
            log.info(f"    - {e}")

    # 다운로드된 파일 목록 저장
    summary_path = os.path.join(LOCAL_DOWNLOAD_DIR, "_download_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("=== OSISAF NH SIC Download Summary ===\n")
        f.write(f"기간: {target_dates[0]} ~ {target_dates[-1]}\n")
        f.write(f"총 요청: {total}건\n\n")

        f.write(f"[성공] {len(results['success'])}건\n")
        for item in results["success"]:
            f.write(f"  {item}\n")

        f.write(f"\n[파일 없음] {len(results['not_found'])}건\n")
        for item in results["not_found"]:
            f.write(f"  {item}\n")

        f.write(f"\n[오류] {len(results['error'])}건\n")
        for item in results["error"]:
            f.write(f"  {item}\n")

    log.info(f"\n  상세 결과 저장: {os.path.abspath(summary_path)}")
    log.info(f"  저장 위치: {os.path.abspath(LOCAL_DOWNLOAD_DIR)}")


if __name__ == "__main__":
    main()
