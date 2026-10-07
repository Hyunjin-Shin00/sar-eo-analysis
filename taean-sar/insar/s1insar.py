"""
s1insar.py — Sentinel-1 IW(TOPS) InSAR 리더/기하 (n2insar 흐름 재사용).
=====================================================================
n2insar.py 를 그대로 이어받아(동일 rdr2geo/geo2rdr/DemInterp/ecef2geo/geo2ecef),
Sentinel-1 만의 차이점만 구현:
  - 궤도/타이밍/버스트/FM rate/Doppler centroid 를 annotation XML 에서 파싱
  - 버스트 SLC 를 measurement TIFF(CInt16)에서 윈도우 읽기 (zip 내부 /vsizip/)
  - TOPS 방위 디램프(quadratic) — 스펙트럼으로 부호 검증
S1Scene 은 n2insar.Scene 과 동일한 인터페이스(orbit, line_to_t, col_to_r, read_slc, _side …)를
제공하므로, N.rdr2geo / N.geo2rdr / N.calibrate_side 를 수정 없이 그대로 쓴다.
"""
import numpy as np, zipfile, os
import xml.etree.ElementTree as ET
from datetime import datetime
import rasterio
from rasterio.windows import Window
import n2insar as N

C0 = 299792458.0
_EPOCH = datetime(2026, 1, 1)
def _t2s(s):
    return (datetime.strptime(s[:26], "%Y-%m-%dT%H:%M:%S.%f") - _EPOCH).total_seconds()
def _poly(txt):
    return np.array([float(x) for x in txt.split()], float)


class S1Scene:
    """Sentinel-1 IW 단일 버스트 씬 (n2insar.Scene 인터페이스 호환)."""
    def __init__(self, zip_path, swath="iw1", pol="vv", burst=0):
        self.zip_path = zip_path; self.swath = swath; self.burst = burst
        zf = zipfile.ZipFile(zip_path)
        names = zf.namelist()
        annname = [n for n in names if f"/annotation/" in n and n.endswith(".xml")
                   and f"-{swath}-" in n and f"-{pol}-" in n
                   and all(x not in n for x in ("calibration", "noise", "rfi"))][0]
        self.tiff_internal = [n for n in names if "/measurement/" in n and n.endswith(".tiff")
                              and f"-{swath}-" in n and f"-{pol}-" in n][0]
        r = ET.fromstring(zf.read(annname)); zf.close()
        ii = r.find(".//imageInformation")
        self.radar_freq = float(r.find(".//radarFrequency").text)
        self.wavelength = C0 / self.radar_freq
        self.rsr = float(r.find(".//rangeSamplingRate").text)
        self.slantRangeTime = float(ii.find("slantRangeTime").text)
        self.dt_az = float(ii.find("azimuthTimeInterval").text)
        self.dr = float(ii.find("rangePixelSpacing").text)
        self.steerRate = np.radians(float(r.find(".//azimuthSteeringRate").text))
        self.lpb = int(r.find(".//linesPerBurst").text)
        self.spb = int(r.find(".//samplesPerBurst").text)
        self.ncols = self.spb; self.nlines = self.lpb
        self.r0 = C0 * self.slantRangeTime / 2.0
        self.rN = self.r0 + (self.ncols - 1) * self.dr
        # 궤도 상태벡터
        t = []; P = []; V = []
        for o in r.findall(".//orbit"):
            t.append(_t2s(o.find("time").text))
            P.append([float(o.find("position/x").text), float(o.find("position/y").text), float(o.find("position/z").text)])
            V.append([float(o.find("velocity/x").text), float(o.find("velocity/y").text), float(o.find("velocity/z").text)])
        self.svt = np.array(t); self.svP = np.array(P); self.svV = np.array(V)
        self._t0 = self.svt[0]; tt = self.svt - self._t0
        self._pP = [np.polyfit(tt, self.svP[:, i], 5) for i in range(3)]
        self._pV = [np.polyfit(tt, self.svV[:, i], 5) for i in range(3)]
        self._pV_d = [np.polyder(p) for p in self._pV]
        # 버스트
        bl = r.findall(".//burst")
        self.n_burst = len(bl)
        self.burst_azt = [_t2s(b.find("azimuthTime").text) for b in bl]
        self.azt0 = self.burst_azt[burst]           # 버스트 첫 라인 방위시각
        self.azt1 = self.azt0 + (self.lpb - 1) * self.dt_az
        # FM rate / Doppler centroid (버스트 azimuthTime 에 가장 가까운 것 선택)
        fms = r.findall(".//azimuthFmRate"); dcs = r.findall(".//dcEstimate")
        def pick(lst):
            at = np.array([_t2s(e.find("azimuthTime").text) for e in lst])
            return lst[int(np.argmin(np.abs(at - self.azt0)))]
        fm = pick(fms); dc = pick(dcs)
        self.fm_t0 = float(fm.find("t0").text); self.fm_c = _poly(fm.find("azimuthFmRatePolynomial").text)
        self.dc_t0 = float(dc.find("t0").text); self.dc_c = _poly(dc.find("dataDcPolynomial").text)
        self._side = None; self.look_side = -1; self.sbi_ndim = None
        self._deramp_sign = -1.0

    # --- n2insar.Scene 호환 메서드 ---
    def orbit(self, t):
        tt = np.asarray(t, float) - self._t0
        P = np.stack([np.polyval(self._pP[i], tt) for i in range(3)], axis=-1)
        V = np.stack([np.polyval(self._pV[i], tt) for i in range(3)], axis=-1)
        return P, V
    def orbit_PVA(self, t):
        tt = np.asarray(t, float) - self._t0
        P = np.stack([np.polyval(self._pP[i], tt) for i in range(3)], axis=-1)
        V = np.stack([np.polyval(self._pV[i], tt) for i in range(3)], axis=-1)
        A = np.stack([np.polyval(self._pV_d[i], tt) for i in range(3)], axis=-1)
        return P, V, A
    def line_to_t(self, line): return self.azt0 + np.asarray(line, float) * self.dt_az
    def t_to_line(self, t): return (np.asarray(t, float) - self.azt0) / self.dt_az
    def col_to_r(self, col): return self.r0 + np.asarray(col, float) * self.dr
    def r_to_col(self, R): return (np.asarray(R, float) - self.r0) / self.dr

    def burst_of_time(self, t):
        """azimuth time t 가 속한 버스트 index."""
        best = 0; bestd = 1e18
        for b, a in enumerate(self.burst_azt):
            c = a + (self.lpb / 2) * self.dt_az
            if abs(t - c) < bestd: bestd = abs(t - c); best = b
        return best

    # --- 버스트 SLC 읽기 (measurement TIFF, CInt16) ---
    def read_slc(self, l0, l1, c0, c1):
        l0 = int(max(0, l0)); l1 = int(min(self.lpb, l1))
        c0 = int(max(0, c0)); c1 = int(min(self.ncols, c1))
        vsi = f"/vsizip/{os.path.abspath(self.zip_path)}/{self.tiff_internal}"
        with rasterio.open(vsi) as ds:
            row0 = self.burst * self.lpb + l0
            arr = ds.read(1, window=Window(c0, row0, c1 - c0, l1 - l0))
        cx = np.asarray(arr).astype(np.complex64)   # CInt16 -> complex
        return cx, (l0, l1, c0, c1)

    # --- TOPS 방위 디램프 (quadratic) ---
    def deramp_phase(self, l0, l1, c0, c1):
        cols = np.arange(c0, c1); lines = np.arange(l0, l1)
        tau = self.slantRangeTime + cols / self.rsr                    # 2-way range time
        ka = np.polyval(self.fm_c[::-1], tau - self.fm_t0)             # Hz/s
        fdc = np.polyval(self.dc_c[::-1], tau - self.dc_t0)            # Hz
        Pc, Vc = self.orbit(self.azt0 + (self.lpb / 2) * self.dt_az)
        Vs = np.linalg.norm(Vc)
        ks = 2 * Vs * self.steerRate / self.wavelength                 # Hz/s
        kt = ka * ks / (ka - ks)                                       # Hz/s
        eta = (lines - (self.lpb - 1) / 2.0) * self.dt_az              # s, 버스트 중심 기준
        eta_ref = -fdc / ka                                            # s (per range)
        ETA = eta[:, None]; ER = eta_ref[None, :]; KT = kt[None, :]
        return np.pi * KT * (ETA - ER) ** 2                            # rad (부호는 밖에서)

    def read_deramped(self, l0, l1, c0, c1):
        cx, ret = self.read_slc(l0, l1, c0, c1)
        ph = self.deramp_phase(ret[0], ret[1], ret[2], ret[3]).astype(np.float32)
        cx *= np.exp(1j * self._deramp_sign * ph).astype(np.complex64)
        return cx, ret, ph

    def deramp_phase_at(self, lines, cols):
        """임의(분수 가능) 버스트내 라인/컬럼 배열에서 TOPS 디램프 위상 평가."""
        lines = np.asarray(lines, float); cols = np.asarray(cols, float)
        tau = self.slantRangeTime + cols / self.rsr
        ka = np.polyval(self.fm_c[::-1], tau - self.fm_t0)
        fdc = np.polyval(self.dc_c[::-1], tau - self.dc_t0)
        Pc, Vc = self.orbit(self.azt0 + (self.lpb / 2) * self.dt_az)
        Vs = np.linalg.norm(Vc)
        ks = 2 * Vs * self.steerRate / self.wavelength
        kt = ka * ks / (ka - ks)
        eta = (lines - (self.lpb - 1) / 2.0) * self.dt_az
        eta_ref = -fdc / ka
        return np.pi * kt * (eta - eta_ref) ** 2
