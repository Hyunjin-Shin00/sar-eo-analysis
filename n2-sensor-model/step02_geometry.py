"""Step 3~6 실행: geo2rdr / rdr2geo 를 세우고 자기일관성·룰사이드·풋프린트를 검증한다.

    python step02_geometry.py [h5 경로]

출력: ../Output/step02_footprint_<date>.geojson  (QGIS 에 바로 올려 확인)
"""
import sys, os, json
import numpy as np
from n2reader import N2Scene
from orbit import Orbit
from geometry import RangeDoppler, geodetic_to_ecef, ecef_to_geodetic

DEFAULT = ("/mnt/c/N2_InSAR/N2/LV1A/HALA/"
           "N2_SAR_20250611_063619_ST_BB_VV_A_R_SSC_B_NP01.h5")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Output")

# 검증 지점: 한라산 백록담 (정표고 ~1947 m). 타원체고는 아래에서 geoid 로 보정
BNR_LAT, BNR_LON, BNR_H_ORTHO = 33.3617, 126.5292, 1947.0


GEOID_FALLBACK = 26.0   # EGM2008 @백록담 (pyproj 네트워크 확인값 +26.0 m). 격자 못 받을 때만 사용


def geoid_N(lat, lon):
    """EGM2008 지오이드고 N [m] (타원체고 = 정표고 + N).
    PROJ 격자(us_nga_egm08_25.tif)가 없으면 pyproj 가 조용히 0 을 돌려주므로 0 은 실패로 본다."""
    try:
        import pyproj
        from pyproj import Transformer
        try:
            pyproj.network.set_network_enabled(True)      # 격자 자동 다운로드 시도
        except Exception:
            pass
        tr = Transformer.from_crs("EPSG:9518", "EPSG:4979", always_xy=True)
        _, _, h = tr.transform(lon, lat, 0.0)
        if np.isfinite(h) and abs(h) > 0.01:
            return float(h)
    except Exception:
        pass
    print(f"  [경고] EGM2008 격자 없음 -> 지오이드고 근사값 {GEOID_FALLBACK:+.1f} m 사용")
    return GEOID_FALLBACK


def main(path):
    sc = N2Scene(path)
    ob = Orbit(sc.sv_t, sc.sv_pos, sc.sv_vel, t_ref=sc.t_mid, deg=4)
    rd = RangeDoppler(sc, ob)
    date = os.path.basename(path)[7:15]
    n_av, nc = sc.n_avail, sc.ncols

    print("=" * 70); print("Step 6-1  왕복 정합  rdr2geo -> geo2rdr"); print("=" * 70)
    L, C = np.meshgrid(np.linspace(0, n_av - 1, 9), np.linspace(0, nc - 1, 7), indexing="ij")
    worst = 0.0
    for h in (0.0, 1000.0, 2000.0):
        P = rd.rdr2geo(L, C, h)
        t, R, l2, c2 = rd.geo2rdr(P)
        e = np.hypot(l2 - L, c2 - C)
        worst = max(worst, e.max())
        print(f"  h={h:6.0f} m : 63점  잔차 max {e.max():.2e} px   (기준 < 1e-3)")
    print("  ->", "OK" if worst < 1e-3 else "FAIL")

    print(); print("=" * 70); print("Step 5  룩사이드"); print("=" * 70)
    N = geoid_N(BNR_LAT, BNR_LON)
    P_bnr = geodetic_to_ecef(BNR_LAT, BNR_LON, BNR_H_ORTHO + N)
    t, R, line, samp = rd.geo2rdr(P_bnr)
    side = rd.side_of(P_bnr, t)
    print(f"  백록담 타원체고  : {BNR_H_ORTHO:.0f} + N({N:+.1f}) = {BNR_H_ORTHO+N:.1f} m")
    print(f"  백록담 -> 영상   : line {line:9.1f} / {n_av} 존재 ({line/n_av*100:5.1f} %),  sample {samp:7.1f} / {nc}")
    print(f"  판별식 부호      : {side:+.0f}  (헤더 {sc.look_side} = {sc.side_sign:+d})  ->",
          "일치" if side == sc.side_sign else "불일치!!")
    inside = (0 <= line < n_av) and (0 <= samp < nc)
    print(f"  데이터 안에 있나 : {'예' if inside else '아니오'}")
    print(f"  입사각/룩각      : {rd.incidence_deg(P_bnr, t):.2f}° / {rd.look_deg(P_bnr, t):.2f}°"
          f"   (헤더 Look Angle {abs(sc.look_angle):.2f}°)")

    # 반대 룩사이드로 풀었을 때 어디로 가는지 (실수 감지용)
    Pw = rd.rdr2geo(line, samp, BNR_H_ORTHO + N, side_sign=-sc.side_sign)
    latw, lonw, _ = ecef_to_geodetic(Pw)
    print(f"  반대 룩사이드 해 : {latw:.4f}N {lonw:.4f}E  (백록담 {BNR_LAT}N {BNR_LON}E 에서 "
          f"{np.linalg.norm(Pw-P_bnr)/1e3:.0f} km 떨어짐)")

    print(); print("=" * 70); print("Step 6-2  기하량 sanity"); print("=" * 70)
    lc, cc = n_av // 2, nc // 2
    P0 = rd.rdr2geo(lc, cc, 0.0); P1 = rd.rdr2geo(lc + 1, cc, 0.0); P2 = rd.rdr2geo(lc, cc + 1, 0.0)
    t0 = rd.t_of_line(lc)
    inc = rd.incidence_deg(P0, t0)
    print(f"  보유구간 중앙 입사각          : {inc:.2f}°   (헤더 look {abs(sc.look_angle):.2f}° + 곡률)")
    print(f"  방위 인접라인 지상거리        : {np.linalg.norm(P1-P0):.4f} m   (헤더 Line Spacing {sc.line_spacing_hdr:.4f})")
    print(f"  거리 인접샘플 지상거리        : {np.linalg.norm(P2-P0):.4f} m   (dR/sin(inc) = {sc.dr/np.sin(np.radians(inc)):.4f})")
    Pn = rd.rdr2geo(lc, 0, 0.0); Pf = rd.rdr2geo(lc, nc - 1, 0.0)
    print(f"  근거리/원거리 입사각          : {rd.incidence_deg(Pn,t0):.2f}° / {rd.incidence_deg(Pf,t0):.2f}°")
    print(f"  지상 스와스 폭                : {np.linalg.norm(Pf-Pn)/1e3:.2f} km")

    print(); print("=" * 70); print("Step 6-3  풋프린트 (h=0)"); print("=" * 70)
    def corners(l_end):
        ls = [0, 0, l_end, l_end, 0]; cs = [0, nc - 1, nc - 1, 0, 0]
        P = rd.rdr2geo(np.array(ls, float), np.array(cs, float), 0.0)
        lat, lon, _ = ecef_to_geodetic(P)
        return list(zip(lon.tolist(), lat.tolist()))
    fp_avail = corners(n_av - 1); fp_full = corners(sc.nlines_hdr - 1)
    for nm, fp in (("데이터 보유 구간", fp_avail), ("헤더 전체 스트립", fp_full)):
        lats = [p[1] for p in fp[:4]]; lons = [p[0] for p in fp[:4]]
        print(f"  {nm}: lat {min(lats):.4f}~{max(lats):.4f}  lon {min(lons):.4f}~{max(lons):.4f}")
    os.makedirs(OUT, exist_ok=True)
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "avail_half", "scene": date},
         "geometry": {"type": "Polygon", "coordinates": [fp_avail]}},
        {"type": "Feature", "properties": {"name": "header_full", "scene": date},
         "geometry": {"type": "Polygon", "coordinates": [fp_full]}},
        {"type": "Feature", "properties": {"name": "Baengnokdam", "line": float(line), "sample": float(samp)},
         "geometry": {"type": "Point", "coordinates": [BNR_LON, BNR_LAT]}},
    ]}
    fn = os.path.join(OUT, f"step02_footprint_{date}.geojson")
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False, indent=1)
    print(f"  저장: {os.path.normpath(fn)}  (QGIS: 레이어 > 추가 > 벡터)")
    return rd


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
