"""DEM 접근 — Copernicus GLO-30 (EPSG:4326, 1", EGM2008 정표고, Point 등록).

제공:
  * height_ortho(lat, lon)   정표고 bilinear
  * geoid_N(lat, lon)        EGM2008 지오이드고 (pyproj 네트워크로 성긴 격자 계산 후 보간; 실패 시 상수)
  * height_ellip(lat, lon)   타원체고 = 정표고 + N   ← 엄밀모델에 들어가는 높이
  * block(lat0, lat1, lon0, lon1, oversample)  시뮬레이션용 격자: lat/lon 메쉬, 타원체고, ECEF 법선, 면적
"""
import numpy as np
import rasterio
from scipy.ndimage import map_coordinates

GEOID_FALLBACK_M = 26.0     # EGM2008 @제주 (pyproj 확인값)


class DEM:
    def __init__(self, path):
        with rasterio.open(path) as ds:
            self.z = ds.read(1).astype(np.float32)
            self.left, self.top = ds.bounds.left, ds.bounds.top
            self.res = ds.res[0]
            self.nrow, self.ncol = self.z.shape
            nd = ds.nodata
        if nd is not None:
            self.z[self.z == nd] = np.nan
        self._geoid = None

    # ------------------------------------------------------------ 좌표 -> 화소
    def _rc(self, lat, lon):
        col = (np.asarray(lon, float) - self.left) / self.res - 0.5      # 화소중심 기준
        row = (self.top - np.asarray(lat, float)) / self.res - 0.5
        return row, col

    def height_ortho(self, lat, lon):
        row, col = self._rc(lat, lon)
        return map_coordinates(self.z, [row, col], order=1, mode="nearest")

    # ------------------------------------------------------------ 지오이드
    def prepare_geoid(self, lat0, lat1, lon0, lon1, step=0.02):
        """AOI 위에 step 간격 격자로 EGM2008 N 을 계산해 저장 (pyproj 네트워크 필요)."""
        lats = np.arange(lat0 - step, lat1 + 2 * step, step)
        lons = np.arange(lon0 - step, lon1 + 2 * step, step)
        LON, LAT = np.meshgrid(lons, lats)
        N = None
        try:
            import pyproj
            from pyproj import Transformer
            try:
                pyproj.network.set_network_enabled(True)
            except Exception:
                pass
            tr = Transformer.from_crs("EPSG:9518", "EPSG:4979", always_xy=True)
            _, _, h = tr.transform(LON.ravel(), LAT.ravel(), np.zeros(LON.size))
            h = np.asarray(h, float).reshape(LON.shape)
            if np.all(np.isfinite(h)) and np.abs(h).max() > 0.01:
                N = h
        except Exception:
            pass
        if N is None:
            print(f"  [경고] EGM2008 격자 계산 실패 -> 상수 {GEOID_FALLBACK_M:+.1f} m")
            N = np.full(LON.shape, GEOID_FALLBACK_M)
        self._geoid = (lats, lons, N)
        return N

    def geoid_N(self, lat, lon):
        if self._geoid is None:
            return np.full(np.broadcast(np.asarray(lat), np.asarray(lon)).shape, GEOID_FALLBACK_M)
        lats, lons, N = self._geoid
        r = (np.asarray(lat, float) - lats[0]) / (lats[1] - lats[0])
        c = (np.asarray(lon, float) - lons[0]) / (lons[1] - lons[0])
        return map_coordinates(N, [r, c], order=1, mode="nearest")

    def height_ellip(self, lat, lon):
        return self.height_ortho(lat, lon) + self.geoid_N(lat, lon)

    # ------------------------------------------------------------ 시뮬레이션 격자
    def block(self, lat0, lat1, lon0, lon1, oversample=2):
        """AOI 를 oversample 배 촘촘한 격자로. 반환 dict:
           lat, lon (2D), h_ell, n_ecef (…,3 단위법선), area (m^2), slope_deg"""
        step = self.res / oversample
        lats = np.arange(lat1, lat0, -step)          # 북 -> 남 (영상 행과 무관, 편의)
        lons = np.arange(lon0, lon1, step)
        LON, LAT = np.meshgrid(lons, lats)
        h_o = self.height_ortho(LAT, LON)
        h = h_o + self.geoid_N(LAT, LON)
        # 미터 단위 격자 간격
        dy = step * 110574.0
        dx = step * 111320.0 * np.cos(np.radians(LAT))
        # np.gradient: axis0 = 남쪽(+row) 방향, axis1 = 동쪽
        dz_drow, dz_dcol = np.gradient(h_o)
        dz_dn = -dz_drow / dy            # 북쪽으로의 기울기
        dz_de = dz_dcol / dx             # 동쪽으로의 기울기
        # ENU 법선 (-dz/de, -dz/dn, 1) 정규화
        n_e, n_n, n_u = -dz_de, -dz_dn, np.ones_like(h_o)
        norm = np.sqrt(n_e ** 2 + n_n ** 2 + 1.0)
        n_e, n_n, n_u = n_e / norm, n_n / norm, n_u / norm
        slope = np.degrees(np.arccos(n_u))
        area = dx * dy * norm            # 경사면 실제 면적
        # ENU -> ECEF
        la, lo = np.radians(LAT), np.radians(LON)
        e = np.stack([-np.sin(lo), np.cos(lo), np.zeros_like(lo)], -1)
        n = np.stack([-np.sin(la) * np.cos(lo), -np.sin(la) * np.sin(lo), np.cos(la)], -1)
        u = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)
        n_ecef = n_e[..., None] * e + n_n[..., None] * n + n_u[..., None] * u
        return dict(lat=LAT, lon=LON, h_ell=h, h_ortho=h_o, n_ecef=n_ecef, area=area, slope_deg=slope)
