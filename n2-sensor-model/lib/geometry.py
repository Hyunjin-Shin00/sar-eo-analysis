"""Step 3~5. 거리-도플러 엄밀센서모델 — geo2rdr / rdr2geo / 룩사이드.

모델 (제로도플러 격자):
    ① |P − S(t)| = R
    ② (P − S(t)) · V(t) = 0
    ③ P 가 WGS84 타원체 위 높이 h (또는 DEM)

편향 모수는 격자 원점 두 개만 건드린다 (Step 8 에서 채움):
    t_eff(line)   = t0 + dt_bias + line * dt
    R_eff(sample) = r0 + dr_bias + sample * dr
"""
import numpy as np

# WGS84
A_WGS = 6378137.0
F_WGS = 1.0 / 298.257223563
B_WGS = A_WGS * (1.0 - F_WGS)
E2_WGS = 1.0 - (B_WGS / A_WGS) ** 2


# --------------------------------------------------------------------------- 좌표 변환
def geodetic_to_ecef(lat_deg, lon_deg, h):
    lat = np.radians(np.asarray(lat_deg, float)); lon = np.radians(np.asarray(lon_deg, float))
    h = np.asarray(h, float)
    N = A_WGS / np.sqrt(1.0 - E2_WGS * np.sin(lat) ** 2)
    x = (N + h) * np.cos(lat) * np.cos(lon)
    y = (N + h) * np.cos(lat) * np.sin(lon)
    z = (N * (1.0 - E2_WGS) + h) * np.sin(lat)
    return np.stack([x, y, z], axis=-1)


def ecef_to_geodetic(P):
    """(…,3) ECEF -> lat[deg], lon[deg], h[m]. 반복법, 1e-12 rad 수렴."""
    P = np.asarray(P, float)
    x, y, z = P[..., 0], P[..., 1], P[..., 2]
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1.0 - E2_WGS))
    for _ in range(10):
        N = A_WGS / np.sqrt(1.0 - E2_WGS * np.sin(lat) ** 2)
        h = p / np.cos(lat) - N
        lat_new = np.arctan2(z, p * (1.0 - E2_WGS * N / (N + h)))
        if np.all(np.abs(lat_new - lat) < 1e-12):
            lat = lat_new; break
        lat = lat_new
    N = A_WGS / np.sqrt(1.0 - E2_WGS * np.sin(lat) ** 2)
    h = p / np.cos(lat) - N
    return np.degrees(lat), np.degrees(lon), h


def ellipsoid_normal(P):
    """타원체 표면 법선(지오데틱 수직) 단위벡터."""
    lat, lon, _ = ecef_to_geodetic(P)
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def _unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


# --------------------------------------------------------------------------- 모델
class RangeDoppler:
    def __init__(self, scene, orbit, dt_bias=0.0, dr_bias=0.0, tropo=False):
        self.sc = scene
        self.orb = orbit
        self.dt_bias = float(dt_bias)     # 초   (방위 시각 편향)
        self.dr_bias = float(dr_bias)     # m    (슬랜트거리 편향)
        self.tropo = bool(tropo)          # 대류권 지연 포함 여부 (R_measured = R_geom + delay)

    # ---- 대류권 -----------------------------------------------------------
    def _delay(self, P, t):
        """지상점 P 에 대한 슬랜트 대류권 지연 [m]. tropo=False 면 0."""
        if not self.tropo:
            return 0.0
        from tropo import slant_delay
        lat, _, h = ecef_to_geodetic(P)
        return slant_delay(h, lat, self.incidence_deg(P, t))

    def add_image_offset(self, dl_px, ds_px):
        """정합에서 얻은 오프셋을 편향에 반영.
        규약: 모델이 (l, s) 에 예측한 지형이 실제 영상에서는 (l+dl, s+ds) 에 있다."""
        self.dt_bias -= float(dl_px) * self.sc.dt
        self.dr_bias -= float(ds_px) * self.sc.dr

    # ---- 격자 (편향 포함) ---------------------------------------------------
    def t_of_line(self, line):
        return self.sc.t0 + self.dt_bias + np.asarray(line, float) * self.sc.dt

    def line_of_t(self, t):
        return (np.asarray(t, float) - self.sc.t0 - self.dt_bias) / self.sc.dt

    def r_of_sample(self, sample):
        return self.sc.r0 + self.dr_bias + np.asarray(sample, float) * self.sc.dr

    def sample_of_r(self, r):
        return (np.asarray(r, float) - self.sc.r0 - self.dr_bias) / self.sc.dr

    # ---- 위성 좌표계 -------------------------------------------------------
    def _frame(self, t):
        """t 에서 v̂(진행), n̂(아래, ⊥v), ĉ_right(오른쪽) 반환. 각 (…,3)"""
        S = self.orb.position(t); V = self.orb.velocity(t)
        vhat = _unit(V)
        down = -S
        nhat = _unit(down - np.sum(down * vhat, axis=-1, keepdims=True) * vhat)
        c_right = np.cross(nhat, vhat)          # 진행방향 기준 오른쪽
        return S, V, vhat, nhat, c_right

    # ---- Step 3: geo2rdr ----------------------------------------------------
    def geo2rdr(self, P, t_guess=None, tol=1e-9, max_iter=20):
        """지상점 P(…,3 ECEF) -> (t, R, line, sample). 제로도플러 뉴턴."""
        P = np.asarray(P, float)
        shp = P.shape[:-1]
        t = np.full(shp, self.sc.t_mid if t_guess is None else t_guess, float)
        for _ in range(max_iter):
            S = self.orb.position(t); V = self.orb.velocity(t); A = self.orb.acceleration(t)
            D = P - S
            g = np.sum(D * V, axis=-1)
            dg = -np.sum(V * V, axis=-1) + np.sum(D * A, axis=-1)
            step = g / dg
            t = t - step
            if np.all(np.abs(step) < tol):
                break
        S = self.orb.position(t)
        R = np.linalg.norm(P - S, axis=-1) + self._delay(P, t)      # 측정 거리 = 기하 + 대류권
        return t, R, self.line_of_t(t), self.sample_of_r(R)

    # ---- Step 4: rdr2geo (타원체 + h) ----------------------------------------
    def rdr2geo(self, line, sample, h=0.0, side_sign=None, tol=1e-12, max_iter=30):
        """(line, sample, h) -> P(…,3 ECEF). 룩각 θ 1변수 뉴턴."""
        line = np.asarray(line, float); sample = np.asarray(sample, float)
        line, sample = np.broadcast_arrays(line, sample)
        h = np.broadcast_to(np.asarray(h, float), line.shape)
        s = self.sc.side_sign if side_sign is None else side_sign
        t = self.t_of_line(line); R = self.r_of_sample(sample)
        if self.tropo:
            # 측정 거리에서 대류권 지연을 빼야 기하 거리. 지연은 P 에 약하게 의존 -> 1회 선행 풀이
            P0 = self._solve_theta(t, R, np.broadcast_to(np.asarray(h, float), line.shape), s, tol, max_iter)
            R = R - self._delay(P0, t)
        return self._solve_theta(t, R, h, s, tol, max_iter)

    def _solve_theta(self, t, R, h, s, tol=1e-12, max_iter=30):
        """①②③ 를 룰각 θ 로 푸는 내부 루틴 (R 은 기하 거리)."""
        S, V, vhat, nhat, c_right = self._frame(t)
        line = np.asarray(t, float)   # shape 참조용
        a2 = (A_WGS + h) ** 2; b2 = (B_WGS + h) ** 2
        theta = np.full(line.shape, np.radians(abs(self.sc.look_angle)), float)
        R_ = R[..., None]
        for _ in range(max_iter):
            u = np.cos(theta)[..., None] * nhat + s * np.sin(theta)[..., None] * c_right
            P = S + R_ * u
            f = (P[..., 0] ** 2 + P[..., 1] ** 2) / a2 + P[..., 2] ** 2 / b2 - 1.0
            dPdth = R_ * (-np.sin(theta)[..., None] * nhat + s * np.cos(theta)[..., None] * c_right)
            grad = np.stack([2 * P[..., 0] / a2, 2 * P[..., 1] / a2, 2 * P[..., 2] / b2], axis=-1)
            df = np.sum(grad * dPdth, axis=-1)
            step = f / df
            theta = theta - step
            if np.all(np.abs(step) < tol):
                break
        u = np.cos(theta)[..., None] * nhat + s * np.sin(theta)[..., None] * c_right
        return S + R_ * u

    def rdr2geo_dem(self, line, sample, dem_h_func, h0=0.0, max_iter=15, tol=0.01):
        """DEM 위의 점. dem_h_func(lat_deg, lon_deg) -> 타원체고[m]. h 반복 갱신."""
        line = np.asarray(line, float)
        h = np.broadcast_to(np.asarray(h0, float), np.broadcast(line, np.asarray(sample, float)).shape).copy()
        for _ in range(max_iter):
            P = self.rdr2geo(line, sample, h)
            lat, lon, _ = ecef_to_geodetic(P)
            h_new = np.asarray(dem_h_func(lat, lon), float)
            done = np.all(np.abs(h_new - h) < tol)
            h = h_new
            if done:
                break
        return self.rdr2geo(line, sample, h), h

    # ---- Step 5: 룩사이드 / 기하량 ------------------------------------------
    def side_of(self, P, t):
        """P 가 위성 진행방향 기준 오른쪽(+1)/왼쪽(-1)."""
        S, V, vhat, nhat, c_right = self._frame(t)
        return np.sign(np.sum((np.asarray(P) - S) * c_right, axis=-1))

    def incidence_deg(self, P, t):
        """타원체 법선 기준 입사각 [deg] (국지 지형 미반영)."""
        S = self.orb.position(t)
        los = _unit(S - np.asarray(P))                # 지표 -> 위성
        n = ellipsoid_normal(P)
        return np.degrees(np.arccos(np.clip(np.sum(los * n, axis=-1), -1, 1)))

    def look_deg(self, P, t):
        """위성에서 본 룩각 [deg] (나디르 기준)."""
        S = self.orb.position(t)
        d = _unit(np.asarray(P) - S); nadir = _unit(-S)
        return np.degrees(np.arccos(np.clip(np.sum(d * nadir, axis=-1), -1, 1)))
