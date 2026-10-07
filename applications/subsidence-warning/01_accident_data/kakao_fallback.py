#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VWorld 무매칭(none) 행을 Kakao 지오코더로 2차 폴백.

Kakao 주소검색(지번/도로명) → 실패 시 키워드(장소명) 검색 순으로 시도.
subsidence_accidents_geocoded.csv 를 제자리 갱신(백업 생성). 새 geocodeType:
  kakao_addr(주소검색) / kakao_keyword(장소검색). 좌표계 WGS84(EPSG:4326).
"""
import argparse
import csv
import os
import re
import shutil
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "subsidence_accidents_geocoded.csv")
ADDR_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KW_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
TIMEOUT = 10
MAX_RETRIES = 3

# addr 본문에서 좌표와 무관한 서술어(그 앞까지만 주소로 사용)
TAIL_RE = re.compile(
    r"(앞쪽|맞은편|앞|옆|뒤편|뒤|부근|인근|일원|일대|근처|진입로|교차점|교차로|출입구|출구|입구|"
    r"차도|보도|인도|노상|하부|상부|하단|상단|지점|방향|부지|E/V|엘리베이터|승강기)"
)
JIBUN_RE = re.compile(r"^\s*(산\s*)?\d+(-\d+)?")


def kakao_get(session, url, key, query):
    headers = {"Authorization": f"KakaoAK {key}"}
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=headers, params={"query": query, "size": 5}, timeout=TIMEOUT)
            if r.status_code in (401, 403):
                raise SystemExit(
                    f"Kakao 인증/권한 실패({r.status_code}): {r.text[:200]}\n"
                    "→ 403 'disabled OPEN_MAP_AND_LOCAL'이면 developers.kakao.com에서 "
                    "해당 앱의 '카카오맵' 서비스를 활성화하세요. (키 자체는 정상)")
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json().get("documents", [])
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            last = e
            if attempt < MAX_RETRIES:
                time.sleep(0.5 * (2 ** (attempt - 1)))
    raise requests.ConnectionError(f"Kakao 요청 실패: {last}")


def in_korea(lon, lat):
    return 124 < lon < 132 and 33 < lat < 39


def build_candidates(row):
    """(addr_queries, keyword_queries) 반환."""
    sido = (row.get("siDo") or "").strip()
    sigungu = (row.get("siGunGu") or "").strip()
    dong = (row.get("dong") or "").strip()
    addr = (row.get("addr") or "").strip()
    admin3 = " ".join(x for x in (sido, sigungu, dong) if x)
    admin2 = " ".join(x for x in (sido, sigungu) if x)

    m = re.search(r"\(([^)]*)\)", addr)
    paren = m.group(1).strip() if m else ""
    main = re.sub(r"\([^)]*\)", "", addr).strip()
    main_cut = TAIL_RE.split(main)[0].strip().replace("번지", "").strip(" ,")

    addr_q, kw_q = [], []

    def add(lst, *parts):
        s = " ".join(p for p in parts if p).strip()
        if s and s not in lst:
            lst.append(s)

    # 주소검색: 지번(선두 번지 토큰) / 도로명
    jm = JIBUN_RE.match(main)
    if jm:
        jibun = re.sub(r"\s+", "", jm.group(0))  # "산 7-4" → "산7-4"
        add(addr_q, admin3 or admin2, jibun)
    if re.search(r"(로|길)\s*\d", main_cut):
        add(addr_q, admin2, main_cut)
    if paren and re.search(r"(로|길)", paren):
        add(addr_q, admin2, paren)

    # 키워드(장소명): 전체 본문, 그리고 선두 지번·후미 서술어 제거한 랜드마크
    add(kw_q, admin3 or admin2, main)
    landmark = TAIL_RE.split(JIBUN_RE.sub("", main).strip())[0].strip(" ,")
    if landmark and re.search(r"[가-힣A-Za-z]", landmark):
        add(kw_q, admin2, landmark)
    if paren and re.search(r"[가-힣]", paren):
        add(kw_q, admin2, paren)
    return addr_q, kw_q, sigungu, dong


def geocode_kakao(session, key, row):
    """(lat, lon, mtype, maddr) 또는 (None,None,'none','')."""
    addr_q, kw_q, sigungu, dong = build_candidates(row)

    for q in addr_q:
        docs = kakao_get(session, ADDR_URL, key, q)
        if docs:
            d = docs[0]
            lon, lat = float(d["x"]), float(d["y"])
            if in_korea(lon, lat):
                name = (d.get("road_address") or {}).get("address_name") \
                    or (d.get("address") or {}).get("address_name") or d.get("address_name", "")
                return lat, lon, "kakao_addr", name

    for q in kw_q:
        docs = kakao_get(session, KW_URL, key, q)
        for d in docs:
            lon, lat = float(d["x"]), float(d["y"])
            if not in_korea(lon, lat):
                continue
            aname = d.get("address_name", "")
            # 오탐 방지: 입력 동(법정동)이 결과 주소에 있어야 채택(같은 동=공간적 근접 보장).
            # 동 정보가 없으면 키워드 결과는 채택하지 않음(타지역 오매칭 차단).
            if not dong or dong not in aname:
                continue
            place = d.get("place_name", "")
            return lat, lon, "kakao_keyword", (f"{place} ({aname})" if place else aname)
    return None, None, "none", ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="VWorld 무매칭 행 Kakao 2차 폴백")
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--key", default=os.environ.get("KAKAO_KEY"), help="Kakao REST API 키 (또는 KAKAO_KEY 환경변수)")
    ap.add_argument("--types", default="none", help="재지오코딩 대상 geocodeType (콤마구분, 기본 none)")
    ap.add_argument("--sleep", type=float, default=0.05)
    args = ap.parse_args(argv)
    if not args.key:
        print("Kakao REST API 키 필요: --key 또는 KAKAO_KEY 환경변수", file=sys.stderr)
        return 2

    targets = set(t.strip() for t in args.types.split(","))
    with open(args.csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = rows[0].keys()

    todo = [i for i, r in enumerate(rows) if r["geocodeType"] in targets]
    print(f"대상 {len(todo)}건 (type in {sorted(targets)}) / 전체 {len(rows)}")

    session = requests.Session()
    filled = 0
    stats = {"kakao_addr": 0, "kakao_keyword": 0, "none": 0}
    for n, i in enumerate(todo, 1):
        row = rows[i]
        if not (row.get("addr") or "").strip():
            stats["none"] += 1
            continue
        time.sleep(args.sleep)
        lat, lon, mtype, maddr = geocode_kakao(session, args.key, row)
        stats[mtype] = stats.get(mtype, 0) + 1
        if lat is not None:
            row.update({"lat": lat, "lon": lon, "geocodeType": mtype, "geocodeAddr": maddr})
            filled += 1
        if n % 20 == 0 or n == len(todo):
            print(f"  [{n}/{len(todo)}] filled={filled} (addr={stats['kakao_addr']}, kw={stats['kakao_keyword']})")

    shutil.copy2(args.csv, args.csv + ".bak")
    with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields))
        w.writeheader()
        w.writerows(rows)

    print("=" * 56)
    print(f"백업: {args.csv}.bak")
    print(f"Kakao 신규 채움 {filled}건 (주소 {stats['kakao_addr']} + 키워드 {stats['kakao_keyword']}), 여전히 무매칭 {stats['none']}")
    # 전체 현황 재집계
    from collections import Counter
    print("갱신 후 geocodeType 분포:", dict(Counter(r["geocodeType"] for r in rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
