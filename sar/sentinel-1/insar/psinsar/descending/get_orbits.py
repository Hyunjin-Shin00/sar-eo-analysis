#!/usr/bin/env python3
"""S1C 정밀궤도(POEORB) 확보.

POEORB 는 관측 다음날 22:59:42 부터 그 다음날 00:59:42 까지를 덮는다. 즉 관측일 D 를
덮는 파일의 유효구간 시작은 D-1 이다. ESA step 미러는 .EOF.zip 으로 서빙하므로
받아서 풀어야 한다. 파일명의 생성시각(OPOD)은 날짜마다 달라 미리 알 수 없으므로
해당 월의 목록을 긁어 유효구간으로 고른다.
"""
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta

import requests

D = '<DATA_ROOT>/S1_DSC'
OUT = f'{D}/orbits'
ESA = 'https://step.esa.int/auxdata/orbits/Sentinel-1/POEORB/S1C'
PAT = re.compile(r'S1C_OPER_AUX_POEORB_OPOD_\d{8}T\d{6}_V(\d{8})T\d{6}_(\d{8})T\d{6}\.EOF')

os.makedirs(OUT, exist_ok=True)
man = json.load(open(f'{D}/aux/manifest.json'))
dates = sorted({s['date'] for s in man['scenes']})
have = {m.group(0) for f in os.listdir(OUT) if (m := PAT.match(f))}

listing = {}


def month_list(y, m):
    key = (y, m)
    if key not in listing:
        r = requests.get(f'{ESA}/{y:04d}/{m:02d}/', timeout=120)
        listing[key] = re.findall(r'S1C_OPER_AUX_POEORB_OPOD_\d{8}T\d{6}'
                                  r'_V\d{8}T\d{6}_\d{8}T\d{6}\.EOF\.zip', r.text) if r.ok else []
    return listing[key]


def pick(day):
    """관측일을 유효구간이 덮는 EOF 하나."""
    d = datetime.strptime(day, '%Y%m%d')
    cands = []
    for off in (0, -1, 1):        # 월말/월초 대비로 인접 월도 훑는다
        dd = d + timedelta(days=30 * off)
        cands += month_list(dd.year, dd.month)
    for z in sorted(set(cands)):
        m = PAT.match(z[:-4])
        if not m:
            continue
        v0 = datetime.strptime(m.group(1), '%Y%m%d')
        v1 = datetime.strptime(m.group(2), '%Y%m%d')
        if v0 <= d < v1:
            return z
    return None


ok = miss = skip = 0
for day in dates:
    z = pick(day)
    if z is None:
        print(f'  {day}: 궤도 없음'); miss += 1; continue
    eof = z[:-4]
    if os.path.exists(f'{OUT}/{eof}'):
        print(f'  {day}: SKIP {eof[:60]}'); skip += 1; continue
    dt = datetime.strptime(day, '%Y%m%d')
    url = None
    for off in (0, -1, 1):
        dd = dt + timedelta(days=30 * off)
        if z in month_list(dd.year, dd.month):
            url = f'{ESA}/{dd.year:04d}/{dd.month:02d}/{z}'
            break
    r = requests.get(url, timeout=300)
    if not r.ok:
        print(f'  {day}: 내려받기 실패 {r.status_code}'); miss += 1; continue
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        name = [n for n in zf.namelist() if n.endswith('.EOF')][0]
        with open(f'{OUT}/{eof}', 'wb') as f:
            f.write(zf.read(name))
    print(f'  {day}: OK  {eof[:60]}  {len(r.content)/1e6:.1f} MB')
    ok += 1

print(f'\n받음 {ok}, 기존 {skip}, 실패 {miss} / 총 {len(dates)}일')
sys.exit(1 if miss else 0)
