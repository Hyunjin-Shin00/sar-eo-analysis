"""
n2insar.py — NEXTSat-2 (X-band) 직접 InSAR 처리 모듈 (ISCE2 스푸핑 미사용)
=====================================================================
NEXTSat-2 SSC(HDF5, S01/SBI) 복소 SLC 두 장으로 반복궤도 간섭(InSAR)을 수행하는
자립형 파이썬 구현. 궤도 상태벡터 + zero-Doppler 기하로 rdr2geo / geo2rdr 를 직접
풀어 (1) 기하 기반 코레지스트레이션과 (2) flat-earth+지형 기준위상 시뮬레이션을 만든다.

복소 레이아웃 (실증 확정, docs/history 참조):
  SBI(int16, shape=(2*L, C)) 에서 짝수행=I, 홀수행=Q →  cx[k] = SBI[2k] + 1j*SBI[2k+1]
  방위 샘플링 = PRF/2 (복소 라인당).  거리 픽셀 = Column Spacing(슬랜트).
"""
import numpy as np
import h5py

C0 = 299792458.0
# WGS84
A_WGS = 6378137.0
F_WGS = 1.0 / 298.257223563
B_WGS = A_WGS * (1.0 - F_WGS)
E2 = F_WGS * (2.0 - F_WGS)


# ----------------------------------------------------------------------------
# 좌표 변환
# ----------------------------------------------------------------------------
def geo2ecef(lat_deg, lon_deg, h):
    lat = np.radians(lat_deg); lon = np.radians(lon_deg)
    N = A_WGS / np.sqrt(1.0 - E2 * np.sin(lat) ** 2)
    x = (N + h) * np.cos(lat) * np.cos(lon)
    y = (N + h) * np.cos(lat) * np.sin(lon)
    z = (N * (1 - E2) + h) * np.sin(lat)
    return np.stack([x, y, z], axis=-1)


def ecef2geo(T):
    x = T[..., 0]; y = T[..., 1]; z = T[..., 2]
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - E2))
    for _ in range(8):
        N = A_WGS / np.sqrt(1 - E2 * np.sin(lat) ** 2)
        h = p / np.cos(lat) - N
        lat = np.arctan2(z, p * (1 - E2 * N / (N + h)))
    N = A_WGS / np.sqrt(1 - E2 * np.sin(lat) ** 2)
    h = p / np.cos(lat) - N
    return np.degrees(lat), np.degrees(lon), h


# ----------------------------------------------------------------------------
# 씬 로더 (메타 + 궤도)
# ----------------------------------------------------------------------------
class Scene:
    def __init__(self, h5path):
        self.path = h5path
        with h5py.File(h5path, "r") as f:
            a = f.attrs
            self.svt = np.array(a["State Vectors Times"], float)
            self.svP = np.array(a["ECEF Satellite Position"], float).reshape(-1, 3)
            self.svV = np.array(a["ECEF Satellite Velocity"], float).reshape(-1, 3)
            self.radar_freq = float(a["Radar Frequency"])
            self.wavelength = C0 / self.radar_freq
            self.look_side = -1 if str(a["Look Side"]).upper().find("RIGHT") >= 0 else 1
            self.orbit_dir = str(a["Orbit Direction"])
            sb = f["S01/SBI"].attrs
            self.azt0 = float(sb["Zero Doppler Azimuth First Time"])
            self.azt1 = float(sb["Zero Doppler Azimuth Last Time"])
            self.rft = float(sb["Zero Doppler Range First Time"])
            self.dr = float(sb["Column Spacing"])            # 슬랜트 거리 픽셀 [m]
            sbi_shape = f["S01/SBI"].shape
            self.sbi_ndim = len(sbi_shape)
            self.ncols = int(sbi_shape[1])
            if self.sbi_ndim == 3:            # 신형: (L, C, 2) — I/Q가 마지막 축
                self.nlines = int(sbi_shape[0])
            else:                              # 구형 LV1A: (2L, C) 짝수행=I/홀수행=Q
                self.nrows_sbi = int(sbi_shape[0])
                self.nlines = self.nrows_sbi // 2
        self.r0 = C0 * self.rft / 2.0
        self.rN = self.r0 + (self.ncols - 1) * self.dr
        self.dt_az = (self.azt1 - self.azt0) / (self.nlines - 1)  # 복소 라인당 시간
        self._side = None   # rdr2geo look-side 부호 (calibrate_side 로 결정)
        # 궤도 다항식 (t 기준 svt[0]) — 5차 다항 피팅 (부드럽고 미분 가능)
        self._t0 = self.svt[0]
        tt = self.svt - self._t0
        self._pP = [np.polyfit(tt, self.svP[:, i], 5) for i in range(3)]
        self._pV = [np.polyfit(tt, self.svV[:, i], 5) for i in range(3)]
        self._pP_d = [np.polyder(p) for p in self._pP]  # dP/dt = V (검증용)
        self._pV_d = [np.polyder(p) for p in self._pV]  # dV/dt = A

    # --- 궤도 상태 (t: 절대 unix, 스칼라/배열) ---
    def orbit(self, t):
        tt = np.asarray(t, float) - self._t0
        P = np.stack([np.polyval(self._pP[i], tt) for i in range(3)], axis=-1)
        V = np.stack([np.polyval(self._pV[i], tt) for i in range(3)], axis=-1)
        return P, V

    def orbit_PVA(self, t):
        tt = np.asarray(t, float) - self._t0
        P = np.stack([np.polyval(self._pP[i], tt) for i in range(3)], axis=-1)
        V = np.stack([np.polyval(self._pV[i], tt) for i in range(3)], axis=-1)
        Aacc = np.stack([np.polyval(self._pV_d[i], tt) for i in range(3)], axis=-1)
        return P, V, Aacc

    # --- 라인/컬럼 <-> 시간/거리 ---
    def line_to_t(self, line):
        return self.azt0 + np.asarray(line, float) * self.dt_az

    def t_to_line(self, t):
        return (np.asarray(t, float) - self.azt0) / self.dt_az

    def col_to_r(self, col):
        return self.r0 + np.asarray(col, float) * self.dr

    def r_to_col(self, R):
        return (np.asarray(R, float) - self.r0) / self.dr

    # --- 복소 SLC 크롭 읽기 ---
    def read_slc(self, l0, l1, c0, c1):
        """복소 라인 [l0:l1], 컬럼 [c0:c1] 을 complex64 로 반환."""
        l0 = int(max(0, l0)); l1 = int(min(self.nlines, l1))
        c0 = int(max(0, c0)); c1 = int(min(self.ncols, c1))
        with h5py.File(self.path, "r") as f:
            if self.sbi_ndim == 3:            # (L, C, 2): [...,0]=I, [...,1]=Q
                blk = f["S01/SBI"][l0:l1, c0:c1, :].astype(np.float32)
                cx = blk[..., 0] + 1j * blk[..., 1]
                return cx.astype(np.complex64), (l0, l1, c0, c1)
            raw = f["S01/SBI"][2 * l0:2 * l1, c0:c1].astype(np.float32)
        I = raw[0::2, :]; Q = raw[1::2, :]
        n = min(I.shape[0], Q.shape[0])
        cx = I[:n] + 1j * Q[:n]
        return cx.astype(np.complex64), (l0, l0 + n, c0, c1)


# ----------------------------------------------------------------------------
# rdr2geo : (방위시간 t, 슬랜트거리 R, 높이 h) -> ECEF 지표점
#   zero-Doppler:  (T-P)·V = 0 ,  |T-P| = R ,  타원체(+h) 위.
#   look-side 근 선택: ψ-매개화 후 부호로 우/좌 look 선택.
# ----------------------------------------------------------------------------
def rdr2geo(scene, t, R, h=0.0, side=None):
    """t,R 스칼라/배열(브로드캐스트). h 스칼라 또는 R 와 같은 shape. ECEF (…,3) 반환.
    side: +1/-1 (없으면 scene._side, 그것도 없으면 -1). look-side 근 선택 부호."""
    t = np.asarray(t, float); R = np.asarray(R, float)
    if side is None:
        side = scene._side if scene._side is not None else -1
    P, V = scene.orbit(t)                       # (...,3)
    vhat = V / np.linalg.norm(V, axis=-1, keepdims=True)
    a_vec = P - np.sum(P * vhat, axis=-1, keepdims=True) * vhat
    a_hat = a_vec / np.linalg.norm(a_vec, axis=-1, keepdims=True)   # 외향 반경성분
    b_hat = np.cross(vhat, a_hat)               # 크로스트랙
    aE = A_WGS + h; bE = B_WGS + h
    aE = np.broadcast_to(aE, R.shape); bE = np.broadcast_to(bE, R.shape)

    def ellip_val(psi):
        u = (-np.cos(psi)[..., None]) * a_hat + (side * np.sin(psi))[..., None] * b_hat
        T = P + R[..., None] * u
        return (T[..., 0] ** 2 + T[..., 1] ** 2) / aE ** 2 + T[..., 2] ** 2 / bE ** 2 - 1.0, T

    lo = np.zeros(R.shape); hi = np.full(R.shape, np.radians(80.0))
    glo, _ = ellip_val(lo); ghi, _ = ellip_val(hi)
    # 이분법 (부호 반전 구간 가정: near-nadir 아래로 교차)
    T = None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        gm, T = ellip_val(mid)
        left = (glo * gm) <= 0
        hi = np.where(left, mid, hi)
        lo = np.where(left, lo, mid)
        glo = np.where(left, glo, gm)
    return T


def calibrate_side(scene, ref_lat, ref_lon):
    """씬 중심 픽셀을 양쪽 look-side 로 풀어 ref 에 가까운 부호를 scene._side 에 저장."""
    i0, j0 = scene.nlines // 2, scene.ncols // 2
    t = scene.line_to_t(i0); R = scene.col_to_r(j0)
    best = None
    for s in (-1, +1):
        T = rdr2geo(scene, t, R, 0.0, side=s)
        lat, lon, _ = ecef2geo(T)
        d = (float(lat) - ref_lat) ** 2 + (float(lon) - ref_lon) ** 2
        if best is None or d < best[0]:
            best = (d, s, float(lat), float(lon))
    scene._side = best[1]
    return best[1], best[2], best[3]


def rdr2geo_dem(scene, t, R, dem_interp, h0=30.0, n_iter=4):
    """DEM 반영 rdr2geo. dem_interp(lat,lon)->height. 반환: (T_ecef, lat, lon, h)."""
    t = np.asarray(t, float); R = np.asarray(R, float)
    h = np.full(np.broadcast(t, R).shape, float(h0))
    lat = lon = None
    for _ in range(n_iter):
        T = rdr2geo(scene, t, R, h)
        lat, lon, _ = ecef2geo(T)
        h = dem_interp(lat, lon)
    T = rdr2geo(scene, t, R, h)
    lat, lon, hh = ecef2geo(T)
    return T, lat, lon, h


# ----------------------------------------------------------------------------
# geo2rdr : ECEF 지표점 T -> (방위시간 t, 슬랜트거리 R)  (Newton, zero-Doppler)
# ----------------------------------------------------------------------------
def geo2rdr(scene, T, t_guess=None, n_iter=12):
    T = np.asarray(T, float)
    shape = T.shape[:-1]
    if t_guess is None:
        t = np.full(shape, 0.5 * (scene.azt0 + scene.azt1))
    else:
        t = np.array(np.broadcast_to(t_guess, shape), float)
    for _ in range(n_iter):
        P, V, Aacc = scene.orbit_PVA(t)
        Rvec = P - T                       # (...,3)
        f = np.sum(Rvec * V, axis=-1)
        fp = np.sum(V * V, axis=-1) + np.sum(Rvec * Aacc, axis=-1)
        t = t - f / fp
    P, V = scene.orbit(t)
    R = np.linalg.norm(P - T, axis=-1)
    return t, R


# ----------------------------------------------------------------------------
# DEM 보간기 (EPSG:4326 규칙격자용 쌍선형)
# ----------------------------------------------------------------------------
class DemInterp:
    def __init__(self, tif_path):
        import rasterio
        ds = rasterio.open(tif_path)
        self.arr = ds.read(1).astype(np.float32)
        self.arr[self.arr < -1000] = np.nan
        tr = ds.transform
        self.lon0 = tr.c; self.dlon = tr.a
        self.lat0 = tr.f; self.dlat = tr.e          # 보통 음수 (북->남)
        self.H, self.W = self.arr.shape
        self.fill = float(np.nanmedian(self.arr))
        ds.close()

    def __call__(self, lat, lon):
        fx = (np.asarray(lon) - self.lon0) / self.dlon
        fy = (np.asarray(lat) - self.lat0) / self.dlat
        x0 = np.floor(fx).astype(int); y0 = np.floor(fy).astype(int)
        wx = fx - x0; wy = fy - y0
        x0 = np.clip(x0, 0, self.W - 2); y0 = np.clip(y0, 0, self.H - 2)
        a = self.arr
        v = (a[y0, x0] * (1 - wx) * (1 - wy) + a[y0, x0 + 1] * wx * (1 - wy)
             + a[y0 + 1, x0] * (1 - wx) * wy + a[y0 + 1, x0 + 1] * wx * wy)
        return np.where(np.isnan(v), self.fill, v)


if __name__ == "__main__":
    import sys
    D = "<DATA_ROOT>/N2_InSAR/N2/LV1A/TAEAN/"
    m = Scene(D + "N2_SAR_20240921_062139_ST_BB_VV_A_R_SSC_B_____.h5")
    s = Scene(D + "N2_SAR_20241026_062238_ST_BB_VV_A_R_SSC_B_____.h5")
    print("MASTER nlines=%d ncols=%d r0=%.1f dr=%.4f dt_az=%.3e lambda=%.5f" %
          (m.nlines, m.ncols, m.r0, m.dr, m.dt_az, m.wavelength))
    print("SLAVE  nlines=%d ncols=%d r0=%.1f dr=%.4f dt_az=%.3e" %
          (s.nlines, s.ncols, s.r0, s.dr, s.dt_az))
    dem = DemInterp("<DATA_ROOT>/N2_InSAR/N2/taean_Insar/work/cop_dem_N36E126.tif")
    print("MASTER side calib:", calibrate_side(m, 36.8728, 126.1615))
    print("SLAVE  side calib:", calibrate_side(s, 36.9169, 126.1562))
    # round-trip 검증: master 중앙 픽셀
    i0, j0 = m.nlines // 2, m.ncols // 2
    t = m.line_to_t(i0); R = m.col_to_r(j0)
    T, lat, lon, h = rdr2geo_dem(m, t, R, dem)
    print("center pixel (%d,%d) -> lat=%.5f lon=%.5f h=%.1f" % (i0, j0, lat, lon, h))
    t2, R2 = geo2rdr(m, T, t_guess=t)
    print("geo2rdr back: dline=%.4f dcol=%.4f (should ~0)" %
          (m.t_to_line(t2) - i0, m.r_to_col(R2) - j0))
    # slave geo2rdr (슬레이브 자체 시간프레임으로 초기화)
    ts, Rs = geo2rdr(s, T, t_guess=s.line_to_t(i0))
    print("slave: line_s=%.2f col_s=%.2f  R_m-R_s=%.3f m  (h_amb=%.2f m)" %
          (s.t_to_line(ts), s.r_to_col(Rs), R - Rs,
           m.wavelength * R * np.sin(np.radians(27.4)) / (2 * 1495)))
