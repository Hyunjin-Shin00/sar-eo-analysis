#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""리스트 API(getSubsidenceList01)에서 사고원인(sagoReason)만 전수 수집."""
import csv
import sys

import requests

sys.path.insert(0, "<DATA_ROOT>/auxiliary/subsidence_list")
from collect_subsidence import (DECODING_KEY, LIST_OP, RateLimiter, call_api,
                               extract_items, get_int, result_code)

OUT = "<WORK_ROOT>/subsidence_reasons.csv"
ROWS = 100

s = requests.Session()
s.headers.update({"Accept": "application/json"})
lim = RateLimiter(20)
base = {"sagoDateFrom": "20000101", "sagoDateTo": "20260730", "numOfRows": ROWS}

first = call_api(s, LIST_OP, DECODING_KEY, {**base, "pageNo": 1}, lim)
total = get_int(first, "totalCount")
last = (total + ROWS - 1) // ROWS
print("total", total, "pages", last, result_code(first))

seen, out = set(), []
def absorb(resp):
    for it in extract_items(resp):
        no = it.get("sagoNo")
        if no and no not in seen:
            seen.add(no)
            out.append({k: (it.get(k) or "").strip() for k in
                        ("sagoNo", "sagoDate", "sido", "sigungu", "sagoReason")})

absorb(first)
for p in range(2, last + 1):
    r = call_api(s, LIST_OP, DECODING_KEY, {**base, "pageNo": p}, lim)
    code, msg = result_code(r)
    if code not in ("0", "00"):
        print("page", p, "fail", code, msg)
        continue
    absorb(r)

with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["sagoNo", "sagoDate", "sido", "sigungu", "sagoReason"])
    w.writeheader()
    w.writerows(out)
print("saved", len(out), "->", OUT)
