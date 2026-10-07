#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
국토안전관리원 지하안전정보 Open API 지반침하사고 전수 수집기.

1단계: getSubsidenceList01 로 사고 리스트를 전 기간 페이징 수집
       (sagoNo + 리스트에만 있는 사고원인 sagoReason 확보)
2단계: getSubsidenceInfo01 로 각 sagoNo 상세를 조회
→ 하나의 CSV(subsidence_accidents.csv)로 병합 저장.

사용 예:
    python3 collect_subsidence.py
    python3 collect_subsidence.py --date-from 20180101 --date-to 20261231 --rows 100 --out out.csv
"""

import os
import argparse
import csv
import datetime as dt
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urlencode

import requests

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
BASE_URL = "https://apis.data.go.kr/1613000/undergroundsafetyinfo01"
LIST_OP = "getSubsidenceList01"
INFO_OP = "getSubsidenceInfo01"

# data.go.kr Decoding 키(디코딩된 원본). params= 재인코딩 시 이중 인코딩되어 30번
# 에러가 나므로, 아래에서 quote(safe='')로 한 번만 인코딩해 URL에 직접 붙인다.
DECODING_KEY = os.environ.get("DATA_GO_KR_KEY", "")

TIMEOUT = 10          # 요청 타임아웃(초)
MAX_RETRIES = 3       # 실패 시 최대 재시도 횟수
# 실측 왕복 지연이 건당 ~3초라 순차 처리 시 전수(1600여건) 수집에 80분 이상 소요된다.
# 30 TPS 허용치를 활용해 스레드 풀로 병렬 조회하되, 아래 전역 RateLimiter로 시작
# 시점을 강제 분산시켜 초당 요청 수를 하드 캡한다.
DEFAULT_WORKERS = 15  # 상세 조회 동시 스레드 수
DEFAULT_TPS = 20      # 전역 초당 요청 상한 (API 제한 30 TPS 대비 여유)

# 정상/데이터없음 판정용 resultCode 집합 (앞자리 0 유무 모두 허용)
OK_CODES = {"0", "00"}
NODATA_CODES = {"3", "03"}

# 최종 CSV 컬럼(요청 스펙) + 좌표/복구비(부가). 스펙 컬럼명은 그대로 유지하되
# 실제 API 키(sido/sigungu 등)에서 값을 읽는다.
CSV_COLUMNS = [
    "sagoNo", "sagoDate", "siDo", "siGunGu", "dong", "addr",
    "sinkWidth", "sinkExtend", "sinkDepth", "grdKind", "sagoDetail",
    "deathCnt", "injuryCnt", "vehicleCnt",
    "trStatus", "trMethod", "trFnDate", "daStDate",
    # 부가 컬럼 (스펙 외, 좌표 활용 대비)
    "sagoLat", "sagoLon", "trAmt",
    # 사고원인. 상세(INFO_OP)의 sagoDetail은 전 건 서버측 공란이고, 실제 원인값은
    # 리스트(LIST_OP) 응답의 sagoReason에만 있다 → 1단계에서 받아 여기에 채운다.
    "sagoReason",
]

log = logging.getLogger("subsidence")


# ---------------------------------------------------------------------------
# HTTP / 파싱 유틸
# ---------------------------------------------------------------------------
class ApiError(RuntimeError):
    """API가 비정상 resultCode 또는 인증(XML) 에러를 반환."""


class RateLimiter:
    """스레드 여러 개가 공유해도 초당 요청 시작을 rate개로 제한(토큰 간격 방식)."""

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


def build_url(operation: str, service_key: str, params: dict) -> str:
    """serviceKey는 한 번만 인코딩해 URL에 직접 붙이고, 나머지 파라미터를 이어붙인다."""
    query = "serviceKey=" + quote(service_key, safe="")
    if params:
        query += "&" + urlencode(params)
    return f"{BASE_URL}/{operation}?{query}"


def _extract_xml_error(text: str) -> str | None:
    """type=json 요청이라도 인증 에러 등은 XML로 온다. 사람이 읽을 메시지를 추출."""
    lowered = text.lstrip()
    if not lowered.startswith("<"):
        return None
    msg = None
    for tag in ("returnAuthMsg", "errMsg", "returnReasonCode", "resultMsg", "cmmMsgHeader"):
        start = text.find(f"<{tag}>")
        if start != -1:
            end = text.find(f"</{tag}>", start)
            if end != -1:
                frag = text[start + len(tag) + 2:end].strip()
                msg = f"{tag}={frag}" if msg is None else f"{msg}, {tag}={frag}"
    return msg or text[:200].strip()


def call_api(session: requests.Session, operation: str, service_key: str, params: dict,
             limiter: "RateLimiter | None" = None) -> dict:
    """API를 호출해 response 딕셔너리를 반환. 네트워크/5xx 오류는 지수 백오프 재시도."""
    params = {**params, "type": "json"}
    url = build_url(operation, service_key, params)

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if limiter is not None:
                limiter.wait()
            resp = session.get(url, timeout=TIMEOUT)
            # 5xx는 일시 오류로 보고 재시도
            if resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            resp.raise_for_status()

            text = resp.text
            try:
                data = resp.json()
            except ValueError:
                # JSON이 아니면 XML 에러(인증 등)일 가능성이 높음 → 재시도 무의미
                xml_err = _extract_xml_error(text)
                raise ApiError(f"비 JSON 응답 ({operation}): {xml_err or text[:200]}")

            response = data.get("response")
            if not isinstance(response, dict):
                raise ApiError(f"예상치 못한 응답 구조 ({operation}): {str(data)[:200]}")
            return response

        except ApiError:
            raise  # 인증/구조 오류는 재시도하지 않고 즉시 전파
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                backoff = 0.5 * (2 ** (attempt - 1))  # 0.5, 1.0, 2.0 ...
                log.warning("요청 실패(%s) [%d/%d] — %.1fs 후 재시도: %s",
                            operation, attempt, MAX_RETRIES, backoff, exc)
                time.sleep(backoff)
            else:
                log.error("요청 최종 실패(%s): %s", operation, exc)

    raise ApiError(f"{operation} 재시도 {MAX_RETRIES}회 모두 실패: {last_exc}")


def result_code(response: dict) -> tuple[str, str]:
    header = response.get("header") or {}
    return str(header.get("resultCode", "")).strip(), str(header.get("resultMsg", "")).strip()


def get_int(response: dict, key: str) -> int | None:
    """totalCount 등은 response 직속 또는 body 아래 둘 다 올 수 있어 모두 확인."""
    for src in (response, response.get("body") or {}):
        if isinstance(src, dict) and src.get(key) not in (None, ""):
            try:
                return int(src[key])
            except (TypeError, ValueError):
                pass
    return None


def extract_items(response: dict) -> list:
    """body.items 를 list로 정규화. list / {'item': ...} / 단건 dict / 빈값 모두 대응."""
    body = response.get("body") or {}
    items = body.get("items")
    if items in (None, ""):
        return []
    if isinstance(items, list):
        return items
    if isinstance(items, dict):
        if "item" in items:
            it = items["item"]
            if it in (None, ""):
                return []
            return it if isinstance(it, list) else [it]
        return [items]  # 단건이 items 자체로 온 경우
    return []


def g(item: dict, *keys):
    """여러 키 별칭 중 처음으로 값이 있는 것을 반환. 빈 문자열은 None."""
    for k in keys:
        if k in item:
            v = item[k]
            if isinstance(v, str):
                v = v.strip()
            if v not in (None, ""):
                return v
    return None


# ---------------------------------------------------------------------------
# 1단계: 리스트 수집
# ---------------------------------------------------------------------------
def fetch_all_sago(session, service_key, date_from, date_to, rows,
                   limiter=None) -> tuple[list[str], dict[str, str]]:
    """(sagoNo 순서 리스트, {sagoNo: sagoReason}) 반환.

    sagoReason은 리스트 응답에만 있는 필드라 여기서 함께 걷어둔다(상세엔 없음).
    """
    base_params = {"sagoDateFrom": date_from, "sagoDateTo": date_to, "numOfRows": rows}

    first = call_api(session, LIST_OP, service_key, {**base_params, "pageNo": 1}, limiter)
    code, msg = result_code(first)
    if code in NODATA_CODES:
        log.warning("리스트 데이터 없음 (resultCode=%s %s)", code, msg)
        return [], {}
    if code not in OK_CODES:
        raise ApiError(f"리스트 조회 실패 resultCode={code} {msg}")

    total = get_int(first, "totalCount") or 0
    last_page = (total + rows - 1) // rows if total else 1
    log.info("리스트 총 %d건, %d페이지(페이지당 %d건) 수집 시작", total, last_page, rows)

    seen: set[str] = set()
    order: list[str] = []
    reasons: dict[str, str] = {}

    def absorb(resp):
        for it in extract_items(resp):
            no = g(it, "sagoNo")
            if no and no not in seen:
                seen.add(no)
                order.append(no)
                reasons[no] = g(it, "sagoReason") or ""

    absorb(first)

    for page in range(2, last_page + 1):
        resp = call_api(session, LIST_OP, service_key, {**base_params, "pageNo": page}, limiter)
        code, msg = result_code(resp)
        if code in NODATA_CODES:
            break
        if code not in OK_CODES:
            log.warning("리스트 %d페이지 실패 resultCode=%s %s — 건너뜀", page, code, msg)
            continue
        absorb(resp)
        if page % 5 == 0 or page == last_page:
            log.info("  리스트 진행: %d/%d 페이지, 누적 %d건", page, last_page, len(order))

    n_reason = sum(1 for v in reasons.values() if v)
    log.info("리스트 수집 완료: 고유 sagoNo %d건 (사고원인 있음 %d건)", len(order), n_reason)
    return order, reasons


# ---------------------------------------------------------------------------
# 2단계: 상세 조회
# ---------------------------------------------------------------------------
def fetch_info(session, service_key, sago_no, limiter=None) -> tuple[str, dict | None]:
    """(status, row) 반환. status ∈ {'ok','nodata','error'}"""
    try:
        resp = call_api(session, INFO_OP, service_key,
                        {"sagoNo": sago_no, "numOfRows": 10, "pageNo": 1}, limiter)
    except ApiError as exc:
        log.error("  상세 조회 오류 sagoNo=%s: %s", sago_no, exc)
        return "error", None

    code, msg = result_code(resp)
    if code in NODATA_CODES:
        return "nodata", None
    if code not in OK_CODES:
        log.warning("  상세 조회 실패 sagoNo=%s resultCode=%s %s", sago_no, code, msg)
        return "error", None

    items = extract_items(resp)
    if not items:
        return "nodata", None

    it = items[0]
    row = {
        "sagoNo":     g(it, "sagoNo") or sago_no,
        "sagoDate":   g(it, "sagoDate"),
        "siDo":       g(it, "sido", "siDo"),
        "siGunGu":    g(it, "sigungu", "siGunGu"),
        "dong":       g(it, "dong"),
        "addr":       g(it, "addr"),
        "sinkWidth":  g(it, "sinkWidth"),
        "sinkExtend": g(it, "sinkExtend"),
        "sinkDepth":  g(it, "sinkDepth"),
        "grdKind":    g(it, "grdKind"),
        "sagoDetail": g(it, "sagoDetail"),
        "deathCnt":   g(it, "deathCnt"),
        "injuryCnt":  g(it, "injuryCnt"),
        "vehicleCnt": g(it, "vehicleCnt"),
        "trStatus":   g(it, "trStatus"),
        "trMethod":   g(it, "trMethod"),
        "trFnDate":   g(it, "trFnDate"),
        "daStDate":   g(it, "daStDate"),
        "sagoLat":    g(it, "sagoLat"),
        "sagoLon":    g(it, "sagoLon"),
        "trAmt":      g(it, "trAmt"),
    }
    return "ok", row


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    today = dt.date.today().strftime("%Y%m%d")
    p = argparse.ArgumentParser(description="국토안전관리원 지반침하사고 전수 수집")
    p.add_argument("--date-from", default="20000101", help="조회 시작일 YYYYMMDD (기본 20000101)")
    p.add_argument("--date-to", default=today, help=f"조회 종료일 YYYYMMDD (기본 오늘 {today})")
    p.add_argument("--rows", type=int, default=100, help="리스트 페이지당 건수 (기본 100)")
    p.add_argument("--out", default="./subsidence_accidents.csv", help="출력 CSV 경로")
    p.add_argument("--service-key", default=DECODING_KEY, help="data.go.kr Decoding 서비스키")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help=f"상세 조회 동시 스레드 수 (기본 {DEFAULT_WORKERS}, 1이면 순차)")
    p.add_argument("--tps", type=float, default=DEFAULT_TPS,
                   help=f"전역 초당 요청 상한 (기본 {DEFAULT_TPS}, API 제한 30 이하)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)

    workers = max(1, args.workers)
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    # 연결 풀을 워커 수에 맞춰 keep-alive 재사용 (기본 10이면 풀 부족 경고 발생)
    adapter = requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    limiter = RateLimiter(args.tps)

    log.info("기간 %s ~ %s, 페이지당 %d건, 워커 %d, 상한 %.0f TPS",
             args.date_from, args.date_to, args.rows, args.workers, args.tps)

    # 1단계
    sago_list, reasons = fetch_all_sago(session, args.service_key, args.date_from,
                                        args.date_to, args.rows, limiter)
    if not sago_list:
        log.warning("수집할 사고번호가 없습니다. 종료.")
        return 1

    # 2단계 (스레드 풀 병렬 조회, 결과는 리스트 원래 순서로 정렬 보관)
    total = len(sago_list)
    results: list[dict | None] = [None] * total
    n_ok = n_nodata = n_error = 0
    done = 0
    lock = threading.Lock()

    def work(i, sago_no):
        return i, sago_no, fetch_info(session, args.service_key, sago_no, limiter)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(work, i, no) for i, no in enumerate(sago_list)]
        for fut in as_completed(futures):
            i, sago_no, (status, row) = fut.result()
            with lock:
                done += 1
                if status == "ok":
                    results[i] = row
                    n_ok += 1
                elif status == "nodata":
                    n_nodata += 1
                else:
                    n_error += 1
                if done % 50 == 0 or done == total:
                    log.info("[%d/%d] 수집 (ok=%d, nodata=%d, error=%d)",
                             done, total, n_ok, n_nodata, n_error)

    rows = [r for r in results if r is not None]

    # 1단계에서 걷어둔 사고원인을 상세 행에 합친다.
    for r in rows:
        r["sagoReason"] = reasons.get(r["sagoNo"], "")

    # 저장
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    log.info("=" * 60)
    log.info("완료: 저장 %d건 → %s", len(rows), args.out)
    log.info("총 대상 %d건 | 성공 %d | 실패(NODATA %d + 에러 %d = %d)",
             total, n_ok, n_nodata, n_error, n_nodata + n_error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
