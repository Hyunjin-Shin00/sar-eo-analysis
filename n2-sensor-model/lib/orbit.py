"""Step 2. 궤도 보간 — 상태벡터(1 s 간격, 60점)를 연속함수 S(t), V(t), A(t) 로.

방법: 씬 중앙시각을 원점으로 시간을 옮긴 뒤(수치 안정), 위치 xyz 각 성분을
다항식(Polynomial.fit, 도메인 스케일링 포함)으로 적합. 속도·가속도는 그 도함수.

검증 두 가지를 제공한다.
  * loo_error(): leave-one-out — 한 점을 빼고 적합해 그 점을 예측한 오차. 보간 정확도.
  * vel_residual(): 위치다항식 도함수 vs 헤더 속도. ECEF 일관성 (ECI 였다면 ~500 m/s 차이).
"""
import numpy as np
from numpy.polynomial import Polynomial


class Orbit:
    def __init__(self, t, pos, vel, t_ref, deg=7, window_s=None):
        """
        t      : (N,) UNIX 초
        pos    : (N,3) m ECEF
        vel    : (N,3) m/s ECEF
        t_ref  : 시간 원점 (보통 씬 중앙시각)
        deg    : 다항식 차수
        window_s: t_ref ± window_s 안의 점만 사용 (None = 전부)
        """
        t = np.asarray(t, float); pos = np.asarray(pos, float); vel = np.asarray(vel, float)
        if window_s is not None:
            m = np.abs(t - t_ref) <= window_s
            t, pos, vel = t[m], pos[m], vel[m]
        self.t_ref = float(t_ref)
        self.t, self.pos, self.vel = t, pos, vel
        self.deg = deg
        self._fit(t, pos)

    def _fit(self, t, pos):
        x = t - self.t_ref
        self.px = [Polynomial.fit(x, pos[:, k], self.deg) for k in range(3)]
        self.pv = [p.deriv(1) for p in self.px]
        self.pa = [p.deriv(2) for p in self.px]

    # ---------------------------------------------------------------- 평가
    def position(self, t):
        x = np.asarray(t, float) - self.t_ref
        return np.stack([p(x) for p in self.px], axis=-1)

    def velocity(self, t):
        x = np.asarray(t, float) - self.t_ref
        return np.stack([p(x) for p in self.pv], axis=-1)

    def acceleration(self, t):
        x = np.asarray(t, float) - self.t_ref
        return np.stack([p(x) for p in self.pa], axis=-1)

    # ---------------------------------------------------------------- 검증
    def loo_error(self):
        """각 점을 빼고 적합 → 그 점 예측오차 [m]. (max, rms) 반환"""
        errs = []
        for i in range(len(self.t)):
            m = np.ones(len(self.t), bool); m[i] = False
            x = self.t[m] - self.t_ref
            pred = [Polynomial.fit(x, self.pos[m, k], self.deg)(self.t[i] - self.t_ref) for k in range(3)]
            errs.append(np.linalg.norm(np.array(pred) - self.pos[i]))
        errs = np.array(errs)
        return float(errs.max()), float(np.sqrt((errs ** 2).mean()))

    def fit_residual(self):
        """적합점에서의 위치 잔차 [m] rms"""
        r = self.position(self.t) - self.pos
        return float(np.sqrt((r ** 2).sum(1).mean()))

    def vel_residual(self):
        """위치다항식 도함수 vs 헤더 속도 [m/s] rms"""
        r = self.velocity(self.t) - self.vel
        return float(np.sqrt((r ** 2).sum(1).mean()))
