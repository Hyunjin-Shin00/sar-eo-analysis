#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
국토교통부_지반정보_표준관입시험정보 전량 다운로드 (api.odcloud.kr 자동변환 OpenAPI)
환경변수 DATA_GO_KR_KEY 에서 인증키를 읽어 사용.

사용법:
  Windows : set DATA_GO_KR_KEY=인증키  &&  python download_spt.py
  Linux   : export DATA_GO_KR_KEY=인증키 && python download_spt.py
"""

import os
import sys
import time
import csv

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ── 설정 ─────────────────────────────────────────────────────────────
SERVICE_KEY = os.environ.get("DATA_GO_KR_KEY", "")
if not SERVICE_KEY:
    print("ERROR: 환경변수 DATA_GO_KR_KEY 가 설정되지 않았습니다.")
    print("  Windows : set DATA_GO_KR_KEY=인증키")
    print("  Linux   : export DATA_GO_KR_KEY=인증키")
    sys.exit(1)

DATA_NO  = "15148686"
UDDI     = "uddi:a1ef4cc3-456c-4356-b93a-b932c9adf35f"
BASE_URL = f"https://api.odcloud.kr/api/{DATA_NO}/v1/{UDDI}"

PER_PAGE      = 10000
OUT_DIR       = os.path.dirname(os.path.abspath(__file__))
OUT_KO        = os.path.join(OUT_DIR, "표준관입시험정보_전체.csv")
OUT_EN        = os.path.join(OUT_DIR, "표준관입시험정보_전체_en.csv")
TIMEOUT       = 60
MAX_RETRY     = 3
SLEEP_BETWEEN = 0.3

KO_TO_EN = {
    "프로젝트코드": "PROJECT_CODE",
    "프로젝트명":   "PROJECT_NAME",
    "시험심도":     "DEPTH_SPT",
    "시추공코드":   "HOLE_CODE",
    "관입깊이":     "SPT_DEPTH",
    "타격회수":     "SPT_N",
}
# ─────────────────────────────────────────────────────────────────────

# 인코딩 폴백 플래그: True 이면 키를 URL 에 직접 삽입(추가 인코딩 없음)
_url_direct = False


def _raw_get(page: int, per_page: int) -> "requests.Response":
    if _url_direct:
        url = (f"{BASE_URL}?page={page}&perPage={per_page}"
               f"&returnType=JSON&serviceKey={SERVICE_KEY}")
        return requests.get(url, timeout=TIMEOUT)
    params = {
        "page":       page,
        "perPage":    per_page,
        "returnType": "JSON",
        "serviceKey": SERVICE_KEY,
    }
    return requests.get(BASE_URL, params=params, timeout=TIMEOUT)


def _call(page: int, per_page: int) -> dict:
    global _url_direct

    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = _raw_get(page, per_page)

            try:
                body = r.json()
            except Exception:
                body = {}

            if r.status_code == 401:
                code = body.get("code", "")
                msg  = body.get("msg",  "")

                # 키가 아예 전달되지 않은 경우
                if code == -401 and "필수 항목" in str(msg):
                    print(f"\n[오류] 인증키가 서버에 전달되지 않음: {msg}")
                    print("  DATA_GO_KR_KEY 환경변수 설정을 확인하세요.")
                    sys.exit(2)

                # 키가 전달됐으나 인증 실패 → 인코딩 폴백 1회 시도
                if not _url_direct:
                    print("  [인증 실패] params 방식 401 -> URL 직접 방식으로 폴백...")
                    _url_direct = True
                    continue   # 같은 루프에서 즉시 재시도

                # 폴백도 실패
                print(f"\n[오류] 인증 실패 (HTTP 401)")
                print(f"  code={code}  msg={msg}")
                print("  조치:")
                print("  1. data.go.kr 마이페이지 인증키 값 재확인")
                print("  2. 데이터셋 15148686 활용신청 승인 여부 확인")
                sys.exit(2)

            if r.status_code == 500:
                print(f"\n[오류] API 서버 오류 (HTTP 500). {attempt}/{MAX_RETRY}")
                if attempt == MAX_RETRY:
                    sys.exit(3)
                time.sleep(2 ** attempt)
                continue

            r.raise_for_status()

            if not body:
                raise ValueError("응답 JSON 이 비어 있음")
            return body

        except SystemExit:
            raise
        except requests.exceptions.ConnectionError as e:
            if attempt == MAX_RETRY:
                print("\n[네트워크 오류] api.odcloud.kr 에 연결할 수 없습니다.")
                print("  허용 필요 도메인: api.odcloud.kr (TCP 443)")
                sys.exit(4)
            print(f"  [page {page}] 연결 실패 {attempt}/{MAX_RETRY}, 재시도...")
        except Exception as e:
            print(f"  [page {page}] 시도 {attempt}/{MAX_RETRY} 실패: {e}", file=sys.stderr)
            if attempt == MAX_RETRY:
                raise
        time.sleep(2 ** attempt)


def main():
    # ── 1단계: 검증 호출 ──────────────────────────────────────────────
    print("[1] API 연결 및 인증 확인 (page=1, perPage=1)...")
    probe = _call(1, 1)

    total = probe.get("totalCount")
    if total is None:
        print("[오류] 응답에 totalCount 가 없습니다. 응답:")
        print(str(probe)[:800])
        sys.exit(1)

    print(f"    => 정상 응답. totalCount = {total:,}")

    # ── 2단계: 전량 수집 ──────────────────────────────────────────────
    n_pages = (total + PER_PAGE - 1) // PER_PAGE
    print(f"[2] {n_pages}페이지 수집 시작 (perPage={PER_PAGE})...")

    # 검증 호출은 perPage=1 이었으므로 page=1 을 perPage=10000 으로 다시 수집
    print(f"    페이지    1/{n_pages}  (재수집)...", end="\r")
    first_full = _call(1, PER_PAGE)
    rows = list(first_full.get("data", []))

    for p in range(2, n_pages + 1):
        print(f"    페이지 {p:>4}/{n_pages}  ({len(rows):,}행 수집 중)...", end="\r")
        body = _call(p, PER_PAGE)
        data = body.get("data", [])
        if not data:
            print(f"\n    page {p}: data[] 빈 배열 -> 마지막 페이지 판단, 종료")
            break
        rows.extend(data)
        time.sleep(SLEEP_BETWEEN)

    print(f"\n[3] 수집 완료: {len(rows):,}행")

    if not rows:
        print("[오류] 수집된 데이터가 없습니다.")
        sys.exit(1)

    # ── 3단계: CSV 저장 ────────────────────────────────────────────────
    ko_fields = list(rows[0].keys())
    en_fields = [KO_TO_EN.get(k, k) for k in ko_fields]

    with open(OUT_KO, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=ko_fields)
        w.writeheader()
        w.writerows(rows)
    print(f"[4] 저장: {OUT_KO}")

    with open(OUT_EN, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(en_fields)
        for row in rows:
            w.writerow([row.get(k, "") for k in ko_fields])
    print(f"[4] 저장: {OUT_EN}")

    print(f"    행: {len(rows):,} / 열: {len(ko_fields)}")
    print(f"    컬럼(한글): {ko_fields}")
    print(f"    컬럼(영문): {en_fields}")

    # ── 4단계: 검증 ───────────────────────────────────────────────────
    if len(rows) == total:
        print(f"[OK] 수집행({len(rows):,}) == totalCount({total:,}) 일치")
    else:
        print(f"[경고] 수집행({len(rows):,}) != totalCount({total:,}) -> 재실행/확인 필요",
              file=sys.stderr)

    # HOLE_CODE 고유값
    hole_key = next((k for k in ko_fields if k == "시추공코드"), None)
    if hole_key:
        unique_holes = len({r.get(hole_key, "") for r in rows})
        print(f"[5] 시추공코드(HOLE_CODE) 고유값 수: {unique_holes:,}")

    # 결론
    if total <= 1_048_575:
        print(f"\n[결론] 기존 파일분({1_048_575:,}행)과 동일/이하 - API 전량과 같음")
    else:
        print(f"\n[결론] 기존 CSV 가 잘려 있었고 API 전량({total:,}행)이 더 많음")


if __name__ == "__main__":
    main()
