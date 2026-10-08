"""Step 1~2 실행: 한 씬을 읽어 격자와 궤도를 세우고 체크포인트를 출력한다.

    python step01_grid_orbit.py [h5 경로]

기본 씬: 한라산 20250611 (A/R, 입사각 32.6°, 백록담 100% 포함)
"""
import sys
import numpy as np
from n2reader import N2Scene
from orbit import Orbit

DEFAULT = ("<DATA_ROOT>/N2_InSAR/N2/LV1A/HALA/"
           "N2_SAR_20250611_063619_ST_BB_VV_A_R_SSC_B_NP01.h5")
R_EARTH_KM = 6371.0


def main(path):
    sc = N2Scene(path)
    s = sc.summary()

    print("=" * 70)
    print("Step 1  영상 격자 <-> (t, R)")
    print("=" * 70)
    print(f"  파일            : {path.split('/')[-1]}")
    print(f"  위성/궤도       : {s['mission']}  #{s['orbit']}  {s['orbit_dir']}  {s['look_side']}-look"
          f"  (side_sign={s['side_sign']:+d}, Look Angle {s['look_angle_deg']:+.2f}°)")
    print(f"  SBI 선언 shape  : {s['sbi_shape']}  layout={s['layout']}")
    print(f"  격자(헤더)      : {s['nlines_hdr']} lines x {s['ncols']} samples")
    print(f"  데이터 존재 라인: 0 .. {s['n_avail']-1}   ({s['n_avail']/s['nlines_hdr']*100:.1f} %)")
    print(f"  t0 (UNIX)       : {s['t0_unix']:.6f}")
    print(f"  dt              : {s['dt_s']*1e6:.3f} us   (1/PRF = {1e6/s['prf_hz']:.3f} us)")
    print(f"  씬 길이 / 보유  : {s['scene_dur_s']:.3f} s / {s['avail_dur_s']:.3f} s")
    print(f"  R0              : {s['r0_m']:.1f} m")
    print(f"  dR              : {s['dr_m']:.4f} m")
    print(f"  파장            : {s['wavelength_m']*100:.3f} cm")

    # 격자 왕복 (사소하지만 부호/단위 실수 방지)
    l = np.array([0, 1000, s['n_avail'] - 1]); c = np.array([0, 2596, s['ncols'] - 1])
    assert np.allclose(sc.line_of_t(sc.t_of_line(l)), l)
    assert np.allclose(sc.sample_of_r(sc.r_of_sample(c)), c)
    print("  격자 왕복       : OK")

    print()
    print("=" * 70)
    print("Step 2  궤도 보간")
    print("=" * 70)
    t, P, V = sc.sv_t, sc.sv_pos, sc.sv_vel
    print(f"  상태벡터        : {len(t)} 점, 간격 {np.unique(np.round(np.diff(t),3))} s")
    print(f"  시간 범위       : 씬 시작 {t[0]-sc.t0:+.1f} s  ~  씬 끝 {t[-1]-sc.t_last:+.1f} s")
    rad = np.linalg.norm(P, axis=1) / 1e3
    print(f"  |S| - 6371 km   : {rad.min()-R_EARTH_KM:.1f} ~ {rad.max()-R_EARTH_KM:.1f} km   (정상 480~550)")
    print(f"  |V|             : {np.linalg.norm(V,axis=1).mean()/1e3:.3f} km/s        (정상 7.6~7.7)")
    dPdt = np.gradient(P, t, axis=0)
    print(f"  dP/dt vs V (유한차분) rms : {np.sqrt(((dPdt-V)**2).sum(1).mean()):.2f} m/s   (ECI 였다면 ~500)")

    # 차수 비교
    print()
    print(f"  {'차수':>4} {'적합잔차 m':>11} {'LOO max m':>10} {'LOO rms m':>10} {'속도잔차 m/s':>13}")
    best = None
    for deg in (4, 5, 6, 7, 8, 9):
        ob = Orbit(t, P, V, t_ref=sc.t_mid, deg=deg)
        lmax, lrms = ob.loo_error()
        vr = ob.vel_residual()
        print(f"  {deg:>4} {ob.fit_residual():>11.4f} {lmax:>10.4f} {lrms:>10.4f} {vr:>13.4f}")
        if best is None or lmax < best[0]:
            best = (lmax, deg)
    deg = best[1]
    ob = Orbit(t, P, V, t_ref=sc.t_mid, deg=deg)
    print(f"  -> 채택 차수 {deg}  (LOO max {best[0]:.4f} m)")

    # 씬 구간 안에서 S, V 평가
    for name, tt in (("씬 시작", sc.t0), ("씬 중앙", sc.t_mid), ("보유 끝", sc.t_of_line(sc.n_avail - 1))):
        S = ob.position(tt); Vv = ob.velocity(tt)
        print(f"  {name}: |S|-R = {np.linalg.norm(S)/1e3-R_EARTH_KM:7.1f} km  |V| = {np.linalg.norm(Vv)/1e3:.3f} km/s"
              f"  S·V/|S||V| = {np.dot(S,Vv)/np.linalg.norm(S)/np.linalg.norm(Vv):+.5f}")

    # 기하 sanity: R0 vs 고도/룩각
    S0 = ob.position(sc.t0)
    h_sat = np.linalg.norm(S0) - 6371e3          # 대략 (구 지구)
    R_expect = h_sat / np.cos(np.radians(abs(sc.look_angle)))
    print()
    print(f"  R0 vs H/cos(look)  : {sc.r0/1e3:.1f} km vs {R_expect/1e3:.1f} km  (구지구 근사, 수 km 차는 정상)")

    print()
    print("=" * 70)
    print("Step 1-3  SLC 읽기 검증 (반쪽 규칙)")
    print("=" * 70)
    l0 = sc.n_avail // 2
    z, box = sc.read_slc(l0, l0 + 512, 2000, 2512)
    amp = np.abs(z)
    cv = amp.std() / amp.mean()
    print(f"  블록 {box}: shape={z.shape}  진폭 CV={cv:.3f}  (1룩 레일리 이론값 0.523; I/Q 섞였으면 0.76)")
    print(f"  I 평균 {z.real.mean():+.1f}  Q 평균 {z.imag.mean():+.1f}  (둘 다 ~0 이어야 함)")
    z_out, box_out = sc.read_slc(sc.n_avail - 4, sc.n_avail + 100)
    print(f"  경계 읽기 {sc.n_avail-4}~{sc.n_avail+100} -> 실제 {box_out[0]}~{box_out[1]} ({z_out.shape[0]} 라인)  OK")
    print(f"  QLK shape       : {sc.qlk_shape}")

    return sc, ob


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
