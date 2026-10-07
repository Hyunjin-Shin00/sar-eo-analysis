"""대류권 전파지연 — 표준대기 기반 간이 모델 (Saastamoinen 건조항 + 습윤항 근사).

레이더 전파는 대기에서 진공보다 느리게 가므로 측정 거리가 실제보다 길어진다.
  R_measured = R_geometric + delay
천정 지연(ZTD) 은 해면에서 ~2.4 m, 지표 고도가 올라가면 위쪽 대기가 줄어 감소한다.
슬랜트 지연 = ZTD / cos(입사각)   (입사각 < 40° 에서 충분)

정확도: 실제 기상 대비 ±0.2 m 수준. 궤도 양자화(0.5 m)가 바닥인 이 데이터에서는 충분하며
ERA5 적분으로 교체하려면 zenith_delay() 만 바꾸면 된다.
"""
import numpy as np

P0_HPA = 1013.25          # 해면 표준기압
ZWD0_M = 0.15             # 해면 습윤 지연 근사 (중위도 연평균; 여름 0.3, 겨울 0.05)
H_WET_M = 2000.0          # 습윤 스케일 고도


def pressure_hpa(h_m):
    """표준대기 기압 프로파일."""
    h = np.clip(np.asarray(h_m, float), -500.0, 11000.0)
    return P0_HPA * (1.0 - 2.2558e-5 * h) ** 5.2559


def zenith_delay(h_m, lat_deg):
    """천정 총지연 [m] = 건조(Saastamoinen) + 습윤(지수 감소 근사)."""
    h = np.asarray(h_m, float)
    phi = np.radians(np.asarray(lat_deg, float))
    f = 1.0 - 0.00266 * np.cos(2.0 * phi) - 0.00028 * (h / 1000.0)
    zhd = 0.0022768 * pressure_hpa(h) / f
    zwd = ZWD0_M * np.exp(-h / H_WET_M)
    return zhd + zwd


def slant_delay(h_m, lat_deg, inc_deg):
    """슬랜트 지연 [m]."""
    return zenith_delay(h_m, lat_deg) / np.cos(np.radians(np.asarray(inc_deg, float)))
