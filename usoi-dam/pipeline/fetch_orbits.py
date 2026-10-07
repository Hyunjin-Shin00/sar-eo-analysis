#!/usr/bin/env python3
# Generalized Sentinel-1 POEORB precise-orbit fetcher (ESA mirror, no auth).
# usage: fetch_orbits.py --urls URLS.txt --out ORBIT_DIR
import os, sys, re, io, zipfile, argparse
from datetime import datetime, timedelta
from pathlib import Path
import requests

MIRROR = "https://step.esa.int/auxdata/orbits/Sentinel-1/POEORB"
_dir_cache = {}

def get_slc_info(urls_file):
    slcs, seen = [], set()
    for line in open(urls_file):
        m = re.search(r"(S1[AB])_IW_SLC__1SDV_(\d{8}T\d{6})", line)
        if m:
            sat = m.group(1); t = datetime.strptime(m.group(2), "%Y%m%dT%H%M%S")
            if (sat, t) not in seen:
                seen.add((sat, t)); slcs.append((sat, t, m.group(0)))
    return slcs

def list_month(session, sat, year, month):
    key = (sat, year, month)
    if key in _dir_cache: return _dir_cache[key]
    url = f"{MIRROR}/{sat}/{year:04d}/{month:02d}/"
    entries = []
    try:
        r = session.get(url, timeout=60)
        if r.status_code == 200:
            pat = r'(S1[AB]_OPER_AUX_POEORB_OPOD_\d{8}T\d{6}_V(\d{8}T\d{6})_(\d{8}T\d{6})\.EOF\.zip)'
            for m in re.finditer(pat, r.text):
                entries.append((m.group(1),
                                datetime.strptime(m.group(2), "%Y%m%dT%H%M%S"),
                                datetime.strptime(m.group(3), "%Y%m%dT%H%M%S")))
    except Exception as e:
        print(f"  [list error] {url}: {e}")
    _dir_cache[key] = entries
    return entries

def find_orbit(session, sat, acq):
    cands = []
    for d in (acq, acq - timedelta(days=2)):
        cands += list_month(session, sat, d.year, d.month)
    for fname, v0, v1 in cands:
        if v0 <= acq <= v1:
            return fname
    return None

def download_eof(session, fname, out_dir):
    eof_name = fname[:-4]
    out = Path(out_dir) / eof_name
    if out.exists() and out.stat().st_size > 0:
        return True
    m = re.search(r"_V(\d{8})", fname); d = datetime.strptime(m.group(1), "%Y%m%d")
    sat = fname[:3]
    url = f"{MIRROR}/{sat}/{d.year:04d}/{d.month:02d}/{fname}"
    try:
        r = session.get(url, timeout=180); r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            inner = [n for n in z.namelist() if n.endswith('.EOF')]
            data = z.read(inner[0]) if inner else z.read(z.namelist()[0])
        with open(out, 'wb') as f: f.write(data)
        return True
    except Exception as e:
        print(f"  [error] {fname}: {e}")
        if out.exists(): out.unlink()
        return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--urls', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    s = requests.Session()
    slcs = get_slc_info(a.urls)
    print(f"unique acquisitions: {len(slcs)}", flush=True)
    ok, fail = 0, []
    for sat, acq, name in slcs:
        fn = find_orbit(s, sat, acq)
        if not fn: fail.append(name); continue
        if download_eof(s, fn, a.out): ok += 1
        else: fail.append(name)
    print(f"DONE orbits: {ok} ok / {len(fail)} fail -> {a.out}", flush=True)
    for f in fail: print("  MISSING:", f)

if __name__ == "__main__":
    main()
