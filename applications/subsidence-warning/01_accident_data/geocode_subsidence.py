#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subsidence_accidents.csv 의 주소를 VWorld 지오코더로 위경도(EPSG:4326) 변환.

전략(주소당 순차 시도, 첫 성공 채택):
  1) parcel(지번)  : "시도 시군구 동 <지번>"   (addr 괄호 앞 숫자부, 서술어 tail 제거)
  2) road(도로명)  : "시도 시군구 <괄호 안 도로명+건물번호>"
  3) road(본문)    : addr 본문이 로/길로 시작하면 도로명으로 재시도
  4) dong(동 중심) : 위 실패 시 행정동 검색(search/district) 중심점으로 근사
  → 모두 실패면 matchType=none, 좌표 공백.

출력: subsidence_accidents_geocoded.csv (원본 전 컬럼 + lat, lon, geocodeType, geocodeAddr)
"""

import argparse
import csv
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

import requests

GETCOORD_URL = "https://api.vworld.kr/req/address"
SEARCH_URL = "https://api.vworld.kr/req/search"

TIMEOUT = 10
MAX_RETRIES = 4
DEFAULT_WORKERS = 6    # 지속 부하 시 VWorld 502 유발 → 보수적으로
DEFAULT_TPS = 8        # 전역 초당 요청 상한
RETRY_ROUNDS = 3       # 네트워크 오류(error) 행 재시도 라운드 수

# addr 본문에서 좌표와 무관한 서술어가 시작되면 그 앞까지만 사용
TAIL_RE = re.compile(
    r"(앞쪽|맞은편|앞|옆|뒤편|뒤|부근|인근|일원|일대|근처|지점|방향|입구|부지|"
    r"교차로|사거리|삼거리|네거리|오거리|나들목|분기점|IC|JC|톨게이트|"
    r"\d+\s*차로|\d+\s*차선|하부|상부|하단|상단|아래|위)"
)

log = logging.getLogger("geocode")


class RateLimiter:
    def __init__(self, rate: float):
        self.min_interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.min_interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)


class FatalGeocodeError(RuntimeError):
    """키/쿼터 등 전체 실행을 중단해야 하는 오류."""


# 전체 중단을 유발하는 VWorld 오류 코드/문구
FATAL_MARKERS = ("INCORRECT_KEY", "NOT_CERTIFIED_KEY", "OVER_", "LIMIT",
                 "인증", "등록되지", "일일", "허용")


def _get(session, url, params, limiter):
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if limiter:
                limiter.wait()
            resp = session.get(url + "?" + urlencode(params), timeout=TIMEOUT)
            if resp.status_code >= 500 or resp.status_code == 429:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as e:
            last = e
            if attempt < MAX_RETRIES:
                time.sleep(0.8 * (2 ** (attempt - 1)))  # 0.8, 1.6, 3.2
    raise requests.ConnectionError(f"요청 {MAX_RETRIES}회 실패: {last}")


def _check_fatal(resp_obj):
    err = (resp_obj or {}).get("error") or {}
    text = f"{err.get('code','')} {err.get('text','')} {(resp_obj or {}).get('status','')}"
    up = text.upper()
    if any(m.upper() in up for m in FATAL_MARKERS):
        raise FatalGeocodeError(f"VWorld 인증/쿼터 오류로 판단 → 중단: {text.strip()}")


def vworld_getcoord(session, key, addr, addr_type, limiter):
    """(lon, lat, refined_text) 또는 None. 인증/쿼터 오류는 FatalGeocodeError."""
    params = {
        "service": "address", "request": "getcoord", "version": "2.0",
        "crs": "epsg:4326", "type": addr_type, "address": addr,
        "format": "json", "key": key,
    }
    data = _get(session, GETCOORD_URL, params, limiter)
    r = (data or {}).get("response") or {}
    status = r.get("status")
    if status == "OK":
        pt = (r.get("result") or {}).get("point") or {}
        if pt.get("x") and pt.get("y"):
            refined = ((r.get("refined") or {}).get("text")) or ""
            return float(pt["x"]), float(pt["y"]), refined
        return None
    if status == "NOT_FOUND":
        return None
    _check_fatal(r)  # ERROR → 치명 여부 판정
    return None


def vworld_district(session, key, query, limiter):
    """행정동 검색 중심점 (lon, lat, title) 또는 None."""
    params = {
        "service": "search", "request": "search", "version": "2.0",
        "crs": "EPSG:4326", "size": "1", "page": "1", "query": query,
        "type": "district", "category": "L4", "format": "json", "key": key,
    }
    data = _get(session, SEARCH_URL, params, limiter)
    r = (data or {}).get("response") or {}
    if r.get("status") == "OK":
        items = (r.get("result") or {}).get("items") or []
        if items:
            pt = items[0].get("point") or {}
            if pt.get("x") and pt.get("y"):
                return float(pt["x"]), float(pt["y"]), items[0].get("title", "")
        return None
    if r.get("status") == "ERROR":
        _check_fatal(r)
    return None


def build_queries(row):
    """(type, query) 후보 리스트 + 행정동 문자열 반환."""
    sido = (row.get("siDo") or "").strip()
    sigungu = (row.get("siGunGu") or "").strip()
    dong = (row.get("dong") or "").strip()
    addr = (row.get("addr") or "").strip()

    admin3 = " ".join(x for x in (sido, sigungu, dong) if x)
    admin2 = " ".join(x for x in (sido, sigungu) if x)

    m = re.search(r"\(([^)]*)\)", addr)
    paren = m.group(1).strip() if m else ""
    main = re.sub(r"\([^)]*\)", "", addr).strip()
    main_cut = TAIL_RE.split(main)[0].strip()
    main_cut = main_cut.replace("번지", "").strip(" ,")

    out = []

    def add(t, *parts):
        s = " ".join(p for p in parts if p).strip()
        if s and (t, s) not in out:
            out.append((t, s))

    has_num = bool(re.search(r"\d", main_cut))
    if has_num:
        add("parcel", admin3 or admin2, main_cut)
    if paren:
        add("road", admin2, paren)
    if main_cut and re.search(r"(로|길)", main_cut) and not re.match(r"^\d", main_cut):
        add("road", admin2, main_cut)
    return out, admin3, dong


def geocode_row(session, key, row, limiter):
    """(lat, lon, matchType, matchedAddr). matchType: parcel/road/dong/none/error.
    네트워크 오류로 판정 불가하면 'error'(재시도 대상), 정상 무매칭이면 'none'."""
    queries, admin3, dong = build_queries(row)
    neterr = False
    for addr_type, q in queries:
        try:
            res = vworld_getcoord(session, key, q, addr_type, limiter)
        except FatalGeocodeError:
            raise
        except requests.RequestException:
            neterr = True
            continue
        if res:
            lon, lat, refined = res
            return lat, lon, addr_type, (refined or q)
    # 동 중심점 폴백
    if admin3:
        try:
            res = vworld_district(session, key, admin3, limiter)
        except FatalGeocodeError:
            raise
        except requests.RequestException:
            neterr = True
            res = None
        if res:
            lon, lat, title = res
            return lat, lon, "dong", (title or admin3)
    return None, None, ("error" if neterr else "none"), ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="지반침하사고 주소 → VWorld 지오코딩")
    ap.add_argument("--in", dest="inp", default="./subsidence_accidents.csv")
    ap.add_argument("--out", default="./subsidence_accidents_geocoded.csv")
    ap.add_argument("--key", default=os.environ.get("VWORLD_KEY"), help="VWorld apiKey (또는 VWORLD_KEY 환경변수)")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--tps", type=float, default=DEFAULT_TPS)
    ap.add_argument("--limit", type=int, default=0, help="상위 N건만 처리(테스트용, 0=전체)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    if not args.key:
        log.error("VWorld apiKey가 필요합니다. --key 또는 VWORLD_KEY 환경변수로 지정하세요.")
        return 2

    with open(args.inp, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[:args.limit]
    fieldnames = list(rows[0].keys()) + ["lat", "lon", "geocodeType", "geocodeAddr"]

    workers = max(1, args.workers)
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers)
    session.mount("https://", adapter)
    limiter = RateLimiter(args.tps)

    # 키 사전 검증 (실패 시 즉시 중단)
    log.info("VWorld 키 검증 중...")
    try:
        test = vworld_getcoord(session, args.key, "서울특별시 강남구 삼성동 147-2", "parcel", limiter)
    except FatalGeocodeError as e:
        log.error(str(e)); return 3
    if not test:
        log.warning("검증 주소가 NOT_FOUND. 키는 유효할 수 있으나 결과 확인 필요.")
    else:
        log.info("키 정상 (테스트 좌표 lon=%.6f lat=%.6f)", test[0], test[1])

    total = len(rows)
    outcome = [None] * total   # (lat, lon, mtype, maddr)
    lock = threading.Lock()
    fatal = {"err": None}
    counter = {"done": 0}

    def work(i):
        if fatal["err"]:
            return i, None
        try:
            return i, geocode_row(session, args.key, rows[i], limiter)
        except FatalGeocodeError as e:
            fatal["err"] = e
            return i, None
        except Exception:  # 예기치 못한 오류도 재시도 대상(error)으로 격리
            return i, (None, None, "error", "")

    def run_pass(indices, label):
        counter["done"] = 0
        n = len(indices)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, i) for i in indices]
            for fut in as_completed(futs):
                i, res = fut.result()
                if res is not None:
                    outcome[i] = res
                with lock:
                    counter["done"] += 1
                    if counter["done"] % 100 == 0 or counter["done"] == n:
                        log.info("  %s [%d/%d]", label, counter["done"], n)

    log.info("지오코딩 시작: %d건, 워커 %d, 상한 %.0f TPS", total, workers, args.tps)
    run_pass(list(range(total)), "pass1")

    # 네트워크 오류(error) 행만 재시도 (정상 무매칭 'none'은 재시도해도 동일)
    rnd = 0
    while not fatal["err"] and rnd < RETRY_ROUNDS:
        retry_idx = [i for i in range(total) if outcome[i] and outcome[i][2] == "error"]
        if not retry_idx:
            break
        rnd += 1
        log.info("재시도 라운드 %d: error %d건 (서버 회복 대기 후)", rnd, len(retry_idx))
        time.sleep(2.0)
        run_pass(retry_idx, f"retry{rnd}")

    if fatal["err"]:
        log.error("실행 중단됨: %s", fatal["err"])

    # 집계 및 저장
    stats = {"parcel": 0, "road": 0, "dong": 0, "none": 0, "error": 0}
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for i, row in enumerate(rows):
            lat, lon, mtype, maddr = outcome[i] if outcome[i] else (None, None, "error", "")
            stats[mtype] = stats.get(mtype, 0) + 1
            merged = dict(row)
            merged.update({"lat": lat if lat is not None else "",
                           "lon": lon if lon is not None else "",
                           "geocodeType": mtype, "geocodeAddr": maddr})
            w.writerow(merged)

    matched = stats["parcel"] + stats["road"] + stats["dong"]
    log.info("=" * 60)
    log.info("완료 → %s", args.out)
    log.info("정밀매칭 parcel=%d road=%d | 동근사 dong=%d | 무매칭 none=%d | 오류 error=%d",
             stats["parcel"], stats["road"], stats["dong"], stats["none"], stats["error"])
    log.info("좌표 확보 %d/%d (%.1f%%), 정밀(parcel+road) %d (%.1f%%)",
             matched, total, 100 * matched / total,
             stats["parcel"] + stats["road"], 100 * (stats["parcel"] + stats["road"]) / total)
    return 3 if fatal["err"] else (1 if stats["error"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
