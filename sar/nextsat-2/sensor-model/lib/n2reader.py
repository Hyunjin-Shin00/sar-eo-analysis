"""Step 0-1. NEXTSat-2 LV1A SSC(HDF5) 읽기 + 영상 격자 <-> (방위시각 t, 슬랜트거리 R) 정의.

이 모듈은 엄밀센서모델의 '뼈대'만 담당한다.
  * 헤더에서 필요한 값만 꺼내 SI 단위로 정리한다 (시각: UNIX 초, 거리: m).
  * line -> t,  sample -> R  (그리고 그 역) 을 제공한다.
  * SLC 복소자료를 올바른 레이아웃으로 읽는다.

LV1A 배포본의 알려진 결함 두 가지를 여기서 흡수한다.
  1) S01/SBI 가 (2*L, C) int16 으로 잘못 선언되어 있다. 실제 레이아웃은 참 라인 m 의
     복소표본 전체가 선언행 2m, 2m+1 을 이어붙인 평탄버퍼에 I,Q 교대로 들어있다.
       flat = SBI[2m:2m+2].reshape(-1);  z[k] = flat[2k] + 1j*flat[2k+1]
  2) 파일은 촬영 스트립의 방위 앞 절반(라인 0 .. NR//2-1)만 담고 있다.
     헤더 Line Samples / Zero Doppler Azimuth First~Last Time 은 전체 스트립 기준이므로
     격자(t0, dt)는 헤더대로 세우고, '데이터가 존재하는 라인' 만 n_avail 로 따로 관리한다.
"""
import numpy as np
import h5py

C_LIGHT = 299792458.0          # m/s


def _s(v):
    """h5 속성의 bytes/str 을 str 로."""
    if isinstance(v, (bytes, np.bytes_)):
        return v.decode()
    return str(v)


class N2Scene:
    def __init__(self, path):
        self.path = path
        with h5py.File(path, "r") as f:
            a, s1, sb = f.attrs, f["S01"].attrs, f["S01/SBI"].attrs

            # ---- 식별 -------------------------------------------------------
            self.mission    = _s(a["Mission ID"])
            self.orbit_num  = int(a["Orbit Number"])
            self.orbit_dir  = _s(a["Orbit Direction"]).upper()        # ASCENDING / DESCENDING
            self.look_side  = _s(a["Look Side"]).upper()              # LEFT / RIGHT
            self.side_sign  = +1 if self.look_side.startswith("R") else -1   # +1 우측룩, -1 좌측룩
            self.look_angle = float(s1["Look Angle"])                 # 부호 = 룩사이드 (음수 우측)
            self.polar      = _s(s1["Polarization"]) if "Polarization" in s1 else "VV"
            self.freq_hz    = float(a["Radar Frequency"])
            self.wavelength = C_LIGHT / self.freq_hz
            self.f_dc_hz    = float(a["Doppler Centroid"])            # 참고용. 제로도플러 격자라 모델엔 0 사용
            assert _s(a["Columns Order"]).upper() == "NEAR-FAR"
            assert _s(a["Lines Order"]).upper() == "EARLY-LATE"

            # ---- 영상 격자 (헤더 = 전체 스트립 기준) --------------------------
            self.nlines_hdr = int(sb["Line Samples"])
            self.ncols      = int(sb["Column Samples"])
            self.t0         = float(sb["Zero Doppler Azimuth First Time"])   # UNIX 초, line 0
            self.t_last     = float(sb["Zero Doppler Azimuth Last Time"])
            self.dt         = float(sb["Line Time Interval"])                # 초 (= 1/PRF)
            tau0            = float(sb["Zero Doppler Range First Time"])     # 왕복 초, sample 0
            dtau            = float(sb["Column Time Interval"])              # 왕복 초
            self.r0         = C_LIGHT * tau0 / 2.0                           # m
            self.dr         = C_LIGHT * dtau / 2.0                           # m  (~0.9993)
            self.prf        = float(s1["PRF"])
            self.line_spacing_hdr = float(sb["Line Spacing"])                # 참고 (지상 방위 간격)

            # ---- 궤도 -----------------------------------------------------
            self.sv_t   = np.asarray(a["State Vectors Times"], float)        # (N,) UNIX 초
            self.sv_pos = np.asarray(a["ECEF Satellite Position"], float)    # (N,3) m
            self.sv_vel = np.asarray(a["ECEF Satellite Velocity"], float)    # (N,3) m/s

            # ---- 데이터 실체 -------------------------------------------------
            d = f["S01/SBI"]
            self.sbi_shape = tuple(d.shape)
            if d.ndim == 2:                        # LV1A 결함 레이아웃
                self.layout  = "flat2d"
                self.n_avail = d.shape[0] // 2
                assert d.shape[1] == self.ncols
            else:                                  # 정상 (L, C, 2)
                self.layout  = "iq3d"
                self.n_avail = d.shape[0]
            self.qlk_shape = tuple(f["S01/QLK"].shape)

        self.t_mid = 0.5 * (self.t0 + self.t_last)

    # ------------------------------------------------------------------ 격자
    def t_of_line(self, line):
        return self.t0 + np.asarray(line, float) * self.dt

    def line_of_t(self, t):
        return (np.asarray(t, float) - self.t0) / self.dt

    def r_of_sample(self, sample):
        return self.r0 + np.asarray(sample, float) * self.dr

    def sample_of_r(self, r):
        return (np.asarray(r, float) - self.r0) / self.dr

    # ------------------------------------------------------------------ 자료
    def read_slc(self, l0, l1, c0=0, c1=None):
        """참 라인 [l0:l1), 거리열 [c0:c1) 의 복소 SLC (complex64).
        존재하지 않는 라인(>= n_avail)은 잘라낸다. 반환: (array, (l0,l1,c0,c1))"""
        c1 = self.ncols if c1 is None else c1
        l0 = int(max(0, l0)); l1 = int(min(self.n_avail, l1))
        c0 = int(max(0, c0)); c1 = int(min(self.ncols, c1))
        n = max(0, l1 - l0)
        if n == 0 or c1 <= c0:
            return np.zeros((n, max(0, c1 - c0)), np.complex64), (l0, l1, c0, c1)
        with h5py.File(self.path, "r") as f:
            d = f["S01/SBI"]
            if self.layout == "flat2d":
                raw = d[2 * l0:2 * l1].reshape(n, self.ncols, 2)[:, c0:c1, :]
            else:
                raw = d[l0:l1, c0:c1, :]
        z = raw[..., 0].astype(np.float32) + 1j * raw[..., 1].astype(np.float32)
        return z, (l0, l1, c0, c1)

    def read_qlk(self):
        with h5py.File(self.path, "r") as f:
            return f["S01/QLK"][:]

    # ------------------------------------------------------------------ 요약
    def summary(self):
        return {
            "mission": self.mission, "orbit": self.orbit_num,
            "orbit_dir": self.orbit_dir, "look_side": self.look_side, "side_sign": self.side_sign,
            "look_angle_deg": self.look_angle, "wavelength_m": self.wavelength,
            "nlines_hdr": self.nlines_hdr, "n_avail": self.n_avail, "ncols": self.ncols,
            "t0_unix": self.t0, "dt_s": self.dt, "prf_hz": self.prf,
            "r0_m": self.r0, "dr_m": self.dr,
            "scene_dur_s": self.t_last - self.t0,
            "avail_dur_s": (self.n_avail - 1) * self.dt,
            "sbi_shape": self.sbi_shape, "layout": self.layout,
        }
