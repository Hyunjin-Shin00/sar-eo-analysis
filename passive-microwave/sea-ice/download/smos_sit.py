#!/usr/bin/env python3
"""
SMOS L3C Sea Ice Thickness (SIT) 자동 다운로드 스크립트
============================================================
- 서버: smos-diss.eo.esa.int (FTPS - Implicit TLS, 포트 990)
- 경로: /SMOS/L3_SIT/L3C/north/YYYY/MM/
- 기간: 2012년 1월 ~ 2026년 4월, 매달 15일
- 대상: Northern Hemisphere

[ 파일명 ]
  v3.3: SMOS_Icethickness_v3.3_north_YYYYMMDD.nc
  이전 버전: 파일명이 다를 수 있음 → 디렉토리 스캔으로 자동 선택

[ 겨울 시즌만 ]
  북반구 SIT 데이터는 10~4월만 존재 (5~9월 자동 건너뜀)

[ 사용법 ]
  python download_smos_sit.py
"""

import os
import ssl
import socket
import time
import logging
from ftplib import FTP_TLS, error_perm
from datetime import date

# ============================================================
# 설정
# ============================================================
FTPS_HOST = "smos-diss.eo.esa.int"
FTPS_PORT = 990
USERNAME = os.environ.get("SMOS_USER", "")   # 자료 제공처 계정 이메일
PASSWORD = os.environ.get("SMOS_PASS", "")

# 확인된 FTP 경로: /SMOS/L3_SIT/L3C/north/YYYY/MM/
FTP_BASE_DIR = "/SMOS/L3_SIT/L3C/north"

LOCAL_DOWNLOAD_DIR = r"<DATA_ROOT>\14_NSR\SMOS\Thickness"

START_YEAR = 2012
START_MONTH = 1
END_YEAR = 2026
END_MONTH = 4
DAY = 15

NH_WINTER_MONTHS = {10, 11, 12, 1, 2, 3, 4}

MAX_RETRIES = 3
RETRY_DELAY = 5
DOWNLOAD_DELAY = 1

# ============================================================
# 로깅
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("download_smos_log.txt", encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)


# ============================================================
# Implicit FTPS 클래스 (Python FTP_TLS 버그 수정)
# - 데이터 채널 SSL 연결 시 server_hostname이 빈 문자열로
#   들어가는 문제를 수정합니다.
# ============================================================
class ImplicitFTPS(FTP_TLS):
    """Implicit FTPS: 포트 990, 연결 시점부터 SSL
    
    Python FTP_TLS의 두 가지 버그를 수정:
    1. 데이터 채널 SSL 연결 시 server_hostname이 빈 문자열인 문제
    2. 이미 SSL인 소켓을 이중 래핑하는 문제
    """

    def __init__(self, host='', port=990, context=None):
        self._host = host
        super().__init__(context=context)
        self.host = host
        self.port = port

    def ntransfercmd(self, cmd, rest=None):
        """데이터 채널 연결 — SSL 이중 래핑 방지 + hostname 수정"""
        conn, size = FTP_TLS.ntransfercmd(self, cmd, rest)
        if self._prot_p and not isinstance(conn, ssl.SSLSocket):
            conn = self.context.wrap_socket(
                conn, server_hostname=self._host
            )
        return conn, size


# ============================================================
# FTPS 연결
# ============================================================
class FTPSManager:
    def __init__(self):
        self.ftp = None

    def connect(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except:
                pass

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # Implicit FTPS (포트 990) - SSL 소켓으로 직접 연결
        log.info(f"FTPS Implicit 연결 시도: {FTPS_HOST}:990")
        sock = socket.create_connection((FTPS_HOST, 990), timeout=60)
        ssl_sock = ctx.wrap_socket(sock, server_hostname=FTPS_HOST)

        self.ftp = ImplicitFTPS(host=FTPS_HOST, context=ctx)
        self.ftp.sock = ssl_sock
        self.ftp.af = ssl_sock.family
        self.ftp.file = self.ftp.sock.makefile('r', encoding=self.ftp.encoding)
        self.ftp.welcome = self.ftp.getresp()
        log.info(f"  서버 응답: {self.ftp.welcome}")

        self.ftp.login(USERNAME, PASSWORD)
        self.ftp.prot_p()
        log.info("FTPS 연결 및 인증 성공")
        return self.ftp

    def ensure_connected(self):
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
# 디렉토리 캐시 & 스캔
# ============================================================
dir_cache = {}


def list_ftp_dir(mgr: FTPSManager, remote_dir: str) -> list:
    if remote_dir in dir_cache:
        return dir_cache[remote_dir]

    ftp = mgr.ensure_connected()
    try:
        files = ftp.nlst(remote_dir)
        files = [os.path.basename(f) for f in files]
        dir_cache[remote_dir] = files
        log.info(f"  디렉토리 스캔: {remote_dir} ({len(files)}개)")
        return files
    except error_perm:
        dir_cache[remote_dir] = []
        return []
    except Exception as e:
        log.warning(f"  스캔 오류: {e}")
        try:
            mgr.connect()
        except:
            pass
        return []


# ============================================================
# 파일 선택
# ============================================================
def find_best_file(file_list: list, target_date: date) -> str | None:
    """
    해당 날짜의 NH SIT 파일을 자동 선택합니다.

    우선순위: 최신 버전 우선 (v3.6 > v3.3 > v3.2 > v3 > 기타)
    제외: south, .nc 아닌 것
    """
    datestr = target_date.strftime("%Y%m%d")

    candidates = []
    for fname in file_list:
        fl = fname.lower()
        if not fl.endswith(".nc"):
            continue
        if datestr not in fname:
            continue
        if "south" in fl:
            continue
        candidates.append(fname)

    if not candidates:
        return None

    def version_score(fname):
        fl = fname.lower()
        if "v3.6" in fl or "v36" in fl:
            return 0
        if "v3.3" in fl or "v33" in fl:
            return 1
        if "v3.2" in fl or "v32" in fl:
            return 2
        if "v3.1" in fl:
            return 3
        if "v3" in fl:
            return 4
        if "v2" in fl:
            return 5
        return 9

    candidates.sort(key=version_score)
    return candidates[0]


# ============================================================
# 다운로드
# ============================================================
def download_file(mgr: FTPSManager, remote_path: str, local_path: str) -> bool:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            ftp = mgr.ensure_connected()
            remote_size = ftp.size(remote_path)

            if os.path.exists(local_path):
                if os.path.getsize(local_path) == remote_size:
                    log.info(f"  ✓ 이미 완료: {os.path.basename(local_path)}")
                    return True

            log.info(f"  ↓ 다운로드: {os.path.basename(remote_path)} ({remote_size:,} bytes)")
            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR {remote_path}", f.write)

            if os.path.getsize(local_path) == remote_size:
                log.info(f"  ✓ 완료")
                return True
            else:
                os.remove(local_path)

        except Exception as e:
            log.warning(f"  시도 {attempt}/{MAX_RETRIES} 실패: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                try:
                    mgr.connect()
                except:
                    pass
    return False


# ============================================================
# 날짜 생성
# ============================================================
def generate_target_dates():
    dates = []
    y, m = START_YEAR, START_MONTH
    while (y, m) <= (END_YEAR, END_MONTH):
        if m in NH_WINTER_MONTHS:
            dates.append(date(y, m, DAY))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return dates


# ============================================================
# 메인
# ============================================================
def main():
    os.makedirs(LOCAL_DOWNLOAD_DIR, exist_ok=True)

    target_dates = generate_target_dates()
    total = len(target_dates)

    log.info("=" * 60)
    log.info("SMOS L3C Sea Ice Thickness (NH) 다운로드")
    log.info(f"  FTP 경로: {FTP_BASE_DIR}/YYYY/MM/")
    log.info(f"  기간: {START_YEAR}.{START_MONTH:02d} ~ {END_YEAR}.{END_MONTH:02d}")
    log.info(f"  겨울 시즌(10~4월) {total}개 날짜")
    log.info(f"  저장: {os.path.abspath(LOCAL_DOWNLOAD_DIR)}")
    log.info("=" * 60)

    mgr = FTPSManager()
    mgr.connect()

    results = {"success": [], "not_found": [], "error": []}

    for idx, target in enumerate(target_dates, 1):
        log.info(f"\n[{idx}/{total}] {target}")

        # 경로: /SMOS/L3_SIT/L3C/north/YYYY/MM
        remote_dir = f"{FTP_BASE_DIR}/{target.strftime('%Y')}/{target.strftime('%m')}"

        file_list = list_ftp_dir(mgr, remote_dir)
        if not file_list:
            log.warning(f"  ⚠ 폴더 없음 또는 비어있음: {remote_dir}")
            results["not_found"].append(str(target))
            continue

        best = find_best_file(file_list, target)
        if not best:
            log.warning(f"  ⚠ 해당 날짜 파일 없음")
            results["not_found"].append(str(target))
            continue

        log.info(f"  선택: {best}")

        remote_path = f"{remote_dir}/{best}"
        local_path = os.path.join(LOCAL_DOWNLOAD_DIR, best)

        if download_file(mgr, remote_path, local_path):
            results["success"].append(f"{target} → {best}")
        else:
            results["error"].append(f"{target} → {best}")

        time.sleep(DOWNLOAD_DELAY)

    mgr.close()

    # 요약
    print("\n" + "=" * 60)
    log.info("다운로드 완료")
    log.info(f"  ✓ 성공: {len(results['success'])}건")
    log.info(f"  ⚠ 없음: {len(results['not_found'])}건")
    log.info(f"  ✗ 오류: {len(results['error'])}건")

    if results["not_found"]:
        log.info("\n  [ 파일 없는 날짜 ]")
        for d in results["not_found"]:
            log.info(f"    - {d}")

    if results["error"]:
        log.info("\n  [ 실패 ]")
        for e in results["error"]:
            log.info(f"    - {e}")

    # 요약 파일 저장
    summary = os.path.join(LOCAL_DOWNLOAD_DIR, "_download_summary.txt")
    with open(summary, "w", encoding="utf-8") as f:
        f.write("=== SMOS L3C SIT NH Download Summary ===\n\n")
        f.write(f"[성공] {len(results['success'])}건\n")
        for item in results["success"]:
            f.write(f"  {item}\n")
        f.write(f"\n[파일 없음] {len(results['not_found'])}건\n")
        for item in results["not_found"]:
            f.write(f"  {item}\n")
        f.write(f"\n[오류] {len(results['error'])}건\n")
        for item in results["error"]:
            f.write(f"  {item}\n")

    log.info(f"  결과 저장: {os.path.abspath(summary)}")


if __name__ == "__main__":
    main()