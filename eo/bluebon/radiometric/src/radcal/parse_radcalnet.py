#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RadCalNet 산출물(.output) 파서.

RadCalNet `.output` (product level v04) = nadir TOA 반사율 스펙트럼.
포맷(La Crau LCFR01 기준, 탭 구분):
  - 헤더: Site/Lat/Lon/Alt, Year/DOY/UTC/Local, P/T/WV/O3/AOD/Ang, Type,
          Zen/Azi/esd (13개 시간열: UTC 09:00~15:00, 30분 간격)
  - TOA 반사율 스펙트럼: 400~2500nm @ 10nm (211행) x 13 시간열
  - 불확도 블록: P/T/WV/O3/AOD/Ang 불확도 헤더 + 동일 스펙트럼 격자의 반사율 1σ (211행)
  - fill 값: 9998(output), 9999(input) = no-data

각 시간열 인덱스(0-based): 09:00=0, 09:30=1, 10:00=2, 10:30=3, 11:00=4, ... 15:00=12
"""
import re
from dataclasses import dataclass, field

import numpy as np

FILL_VALUES = (9998.0, 9999.0)
N_TIMESLOTS = 13
WL_MIN, WL_MAX, WL_STEP = 400, 2500, 10   # 211 파장


@dataclass
class RadCalNetSample:
    """지정 UTC 시간열 하나에 대한 RadCalNet TOA 표본."""
    path: str
    site: str
    lat: float
    lon: float
    alt: float
    year: int
    doy: int
    utc: str                 # 선택된 격자 UTC "HH:MM"
    col_index: int           # 13열 중 0-based 인덱스
    sza: float               # 태양 천정각 [deg]
    saa: float               # 태양 방위각 [deg]
    esd: float               # 지구-태양 거리 [AU]
    atmos: dict              # {'P','T','WV','O3','AOD','Ang'} (선택열 값)
    wavelength: np.ndarray   # [nm], fill 제외 후 유효 파장
    toa_refl: np.ndarray     # TOA 반사율 (유효 파장)
    toa_refl_unc: np.ndarray # TOA 반사율 1σ 불확도 (유효 파장)
    n_fill: int = 0          # 400~2500 중 제외된 fill 개수
    meta: dict = field(default_factory=dict)


def _split(line):
    return line.rstrip("\n").split("\t")


def _find_col_index(utc_row_fields, target_hhmmss):
    """UTC: 헤더 행에서 target 시각에 가장 가까운 30분 격자 열 인덱스(0-based)를 반환."""
    times = utc_row_fields[1:1 + N_TIMESLOTS]

    def to_min(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    parts = target_hhmmss.split(":")
    tgt = int(parts[0]) * 60 + int(parts[1]) + (int(parts[2]) / 60 if len(parts) > 2 else 0)
    grid = np.array([to_min(t) for t in times], dtype=float)
    idx = int(np.argmin(np.abs(grid - tgt)))
    return idx, times[idx], grid


def parse_output(path, utc="11:08:33"):
    """RadCalNet .output 파일을 파싱하여 지정 UTC 시각의 RadCalNetSample을 반환."""
    with open(path, "r") as f:
        lines = f.readlines()

    header = {}
    utc_fields = None
    zen = azi = esd = None
    atmos_rows = {}
    for ln in lines:
        fields = _split(ln)
        if not fields or fields[0] == "":
            continue
        key = fields[0].rstrip(":")
        if key in ("Site", "Lat", "Lon", "Alt"):
            header[key] = fields[1].strip()
        elif key == "Year":
            header["Year"] = fields[1:1 + N_TIMESLOTS]
        elif key == "DOY(U)":
            header["DOY"] = fields[1:1 + N_TIMESLOTS]
        elif key == "UTC":
            utc_fields = fields
        elif key in ("P", "T", "WV", "O3", "AOD", "Ang"):
            # 첫 등장(데이터 블록)만 채택 — 두 번째는 불확도 블록
            if key not in atmos_rows:
                atmos_rows[key] = fields[1:1 + N_TIMESLOTS]
        elif key == "Zen":
            zen = [float(x) for x in fields[1:1 + N_TIMESLOTS]]
        elif key == "Azi":
            azi = [float(x) for x in fields[1:1 + N_TIMESLOTS]]
        elif key == "esd":
            esd = [float(x) for x in fields[1:1 + N_TIMESLOTS]]

    if utc_fields is None:
        raise ValueError(f"UTC 헤더 행을 찾지 못함: {path}")

    col, sel_utc, _grid = _find_col_index(utc_fields, utc)

    # --- 스펙트럼 블록 두 개(데이터, 불확도) 추출 ---
    # 파장 정수(400~2500)로 시작하고 13개 값을 갖는 행을 순서대로 수집.
    wl_re = re.compile(r"^\d+$")
    spectra = []            # list of (wl, [13 values])
    for ln in lines:
        fields = _split(ln)
        if len(fields) < 1 + N_TIMESLOTS:
            continue
        if not wl_re.match(fields[0]):
            continue
        wl = int(fields[0])
        if wl < WL_MIN or wl > WL_MAX:
            continue
        try:
            vals = [float(x) for x in fields[1:1 + N_TIMESLOTS]]
        except ValueError:
            continue
        spectra.append((wl, vals))

    n_wl = (WL_MAX - WL_MIN) // WL_STEP + 1   # 211
    if len(spectra) < 2 * n_wl:
        raise ValueError(
            f"스펙트럼 행 수 부족: {len(spectra)} (기대 {2*n_wl}) — {path}")

    data_block = spectra[:n_wl]
    unc_block = spectra[n_wl:2 * n_wl]

    wl_arr = np.array([w for w, _ in data_block], dtype=float)
    refl = np.array([v[col] for _, v in data_block], dtype=float)
    unc_wl = np.array([w for w, _ in unc_block], dtype=float)
    unc = np.array([abs(v[col]) for _, v in unc_block], dtype=float)
    assert np.array_equal(wl_arr, unc_wl), "데이터/불확도 파장 격자 불일치"

    # fill 제외
    valid = ~np.isin(refl, FILL_VALUES)
    n_fill = int((~valid).sum())

    atmos = {k: float(atmos_rows[k][col]) for k in atmos_rows}

    return RadCalNetSample(
        path=path,
        site=header.get("Site", ""),
        lat=float(header.get("Lat", "nan")),
        lon=float(header.get("Lon", "nan")),
        alt=float(header.get("Alt", "nan")),
        year=int(header["Year"][col]),
        doy=int(header["DOY"][col]),
        utc=sel_utc,
        col_index=col,
        sza=float(zen[col]) if zen else float("nan"),
        saa=float(azi[col]) if azi else float("nan"),
        esd=float(esd[col]) if esd else float("nan"),
        atmos=atmos,
        wavelength=wl_arr[valid],
        toa_refl=refl[valid],
        toa_refl_unc=unc[valid],
        n_fill=n_fill,
        meta={"requested_utc": utc, "n_wavelengths": int(valid.sum())},
    )


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="RadCalNet .output 파서 점검")
    ap.add_argument("path")
    ap.add_argument("--utc", default="11:08:33")
    a = ap.parse_args()
    s = parse_output(a.path, utc=a.utc)
    print(f"site={s.site} lat={s.lat} lon={s.lon} year={s.year} doy={s.doy}")
    print(f"selected UTC={s.utc} (col {s.col_index}) SZA={s.sza:.3f} esd={s.esd:.5f}")
    print(f"atmos={s.atmos}")
    print(f"valid wl: {s.wavelength.min():.0f}~{s.wavelength.max():.0f} nm, "
          f"n={s.wavelength.size}, fill excluded={s.n_fill}")
    # 400~1000 구간 요약
    m = (s.wavelength >= 400) & (s.wavelength <= 1000)
    print(f"VNIR(400~1000) TOA refl: min={s.toa_refl[m].min():.4f} "
          f"max={s.toa_refl[m].max():.4f}, unc mean={s.toa_refl_unc[m].mean():.4f}")
