"""지바 최종 침수 영역 — 변화 기반 판정으로 재생산한다.

왜 방법을 바꾸는가
  · 앞선 방식은 시기마다 「하위 1 백분위」로 임계를 정했다. 그러면 판정 면적이 두 시기 모두
    정확히 1 % 로 고정되어, 홍수의 본질인 「물이 늘었다」를 원리상 표현하지 못한다.
  · 문헌의 표준 처방은 절대값 하나로 가르는 대신 **두 시기의 변화를 본다**.
      Matgen, Hostache, Schumann et al. (2011) Phys. Chem. Earth
      Giustarini, Hostache, Matgen et al. (2013) IEEE TGRS 51(4)
  · Otsu·Kittler–Illingworth·분할기반 자동임계는 이 장면에서 평탄지의 47~98 % 를 물로
    판정해 물리적으로 쓸 수 없었다(threshold_compare.py 실측).

분석 영역
  지도에 표시하는 범위와 정확히 같은 영역(140.100~140.500 E, 35.470~35.720 N)에서만 판정한다.
  판정 영역이 표시 영역보다 넓으면 화면 밖에서 나온 값이 표에 섞여 서로 맞지 않게 된다.

판정 규칙 — 두 조건을 동시에 만족하는 화소만 침수로 본다
  ① 후방산란이 사건 전보다 3 dB 이상 떨어졌을 것   (변화 조건)
  ② 사건 당일 절대값도 물 수준일 것 — 그날 평탄지 분포의 하위 1 백분위 미만 (절대 조건)
  ③ 평탄지(경사 5° 이하)이고, 평소에도 물인 곳(광학 상시 수체)이 아닐 것
  ④ 0.5 ha 미만의 조각은 버린다

①만 쓰면 젖은 농지·수확 직후 논이 섞이고, ②만 쓰면 면적이 고정된다. 둘을 겹쳐야 한다.
"""
import os, sys, json, pathlib
os.environ.pop("PYTHONPATH", None)
import numpy as np, rasterio, pandas as pd
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds as tfb
from scipy import ndimage

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
sys.path.insert(0, str(ROOT/"src"/"process"))
import threshold_compare as TC                                      # noqa: E402
LAY = ROOT/"outputs"/"web"/"layers"; OUTS = ROOT/"outputs"/"samples"
OUTT = ROOT/"outputs"/"tables"

BBOX = (139.95, 35.35, 140.55, 35.80)         # 분석 영역 = 표시 영역
D_MIN = 3.0        # 변화 조건 — 사건 전 대비 하락폭(dB)
P_ABS = 1.0        # 절대 조건 — 사건 당일 평탄지 분포의 백분위(%)
SLOPE_MAX = 5.0
MIN_PX = 50        # 약 0.5 ha


def grid():
    """표시 범위를 UTM 54N 10 m 격자로 만든다."""
    import pyproj
    tf = pyproj.Transformer.from_crs(4326, 32654, always_xy=True)
    x0, y0 = tf.transform(BBOX[0], BBOX[1]); x1, y1 = tf.transform(BBOX[2], BBOX[3])
    x0, x1 = min(x0, x1), max(x0, x1); y0, y1 = min(y0, y1), max(y0, y1)
    w = int((x1-x0)//10); h = int((y1-y0)//10)
    return dict(height=h, width=w, crs=rasterio.crs.CRS.from_epsg(32654),
                transform=tfb(x0, y0, x1, y1, w, h))


def main():
    prof = grid()
    px = abs(prof["transform"].a*prof["transform"].e)/1e6
    elev = TC.elevation_grid(prof); slope = TC.slope_deg(prof, elev)
    land = np.isfinite(elev) & (elev > 0.5)

    ow = np.load(LAY/"_chiba_optwater_pre.npy")
    lon0, lat0, lon1, lat1 = BBOX
    h, w = ow.shape            # 광학 격자 크기는 파일에서 읽는다. 상수로 두면 어긋난다
    s2 = np.zeros((prof["height"], prof["width"]), np.uint8)
    reproject(ow.astype(np.uint8), s2, src_transform=tfb(lon0, lat0, lon1, lat1, w, h),
              src_crs=rasterio.crs.CRS.from_epsg(4326),
              dst_transform=prof["transform"], dst_crs=prof["crs"],
              resampling=Resampling.max, src_nodata=0, dst_nodata=0)
    s2 = s2.astype(bool)

    V, F = {}, {}
    for tag, files in TC.IMGS.items():
        v = TC.db(TC.load(files, 2, prof)); inc = TC.load(files, 3, prof)
        ok = np.isfinite(v) & land & np.isfinite(inc) & (inc > 15) & (inc < 75)
        V[tag] = v; F[tag] = ok & np.isfinite(slope) & (slope <= SLOPE_MAX)
    both = F["pre"] & F["post"]

    def clean(m):
        lab, n = ndimage.label(m, np.ones((3, 3)))
        if not n: return m
        c = np.bincount(lab.ravel()); c[0] = 0
        k = np.zeros(c.size, bool); k[c >= MIN_PX] = True
        return k[lab]

    t = {g: float(np.percentile(V[g][F[g]], P_ABS)) for g in ("pre", "post")}
    water = {g: clean(F[g] & (V[g] < t[g])) for g in ("pre", "post")}
    print(f"분석 영역 {both.sum()*px:.0f} km² (평탄지) · 전체 {prof['width']*prof['height']*px:.0f} km²")
    print(f"SAR 수체 — 사건 전 {water['pre'].sum()*px:.2f} km² (임계 {t['pre']:+.2f} dB) · "
          f"사건 당일 {water['post'].sum()*px:.2f} km² (임계 {t['post']:+.2f} dB)")
    t_abs = t["post"]
    dd = V["post"] - V["pre"]
    flood = clean(both & (dd <= -D_MIN) & (V["post"] < t_abs) & ~s2)
    area = float(flood.sum()*px)
    print(f"변화 조건 Δσ⁰ ≤ {-D_MIN:.0f} dB · 절대 조건 사건 당일 < {t_abs:+.2f} dB "
          f"(평탄지 하위 {P_ABS:.0f} 백분위)")
    print(f"★ 최종 침수 영역 {area:.2f} km²")
    print(f"   변화 조건만  {clean(both & (dd <= -D_MIN) & ~s2).sum()*px:7.2f} km²  ← 젖은 농지가 섞인다")
    print(f"   절대 조건만  {clean(F['post'] & (V['post'] < t_abs) & ~s2).sum()*px:7.2f} km²  ← 사건 전에도 어둡던 곳이 섞인다")

    # 강건성 — 두 자유모수를 흔들어 결과가 얼마나 움직이는지 본다
    rob = []
    print("\n── 강건성")
    for d in (2.0, 3.0, 4.0, 5.0):
        line = []
        for pq in (0.5, 1.0, 2.0):
            tq = float(np.percentile(V["post"][F["post"]], pq))
            a = float(clean(both & (dd <= -d) & (V["post"] < tq) & ~s2).sum()*px)
            line.append(a); rob.append(dict(하락폭_dB=d, 백분위_pct=pq, 침수_km2=round(a, 2)))
        print(f"   Δ≤{-d:+.0f} dB  p=0.5 % {line[0]:5.2f} · p=1 % {line[1]:5.2f} · p=2 % {line[2]:5.2f} km²")
    v = [r["침수_km2"] for r in rob]
    print(f"   전체 범위 {min(v):.2f} ~ {max(v):.2f} km² (중앙값 {np.median(v):.2f})")
    v1 = [r["침수_km2"] for r in rob if r["백분위_pct"] == 1.0]
    print(f"   p=1 % 고정, 하락폭만 변화 → {min(v1):.2f} ~ {max(v1):.2f} km² "
          f"(폭 {(max(v1)-min(v1))/np.mean(v1)*100:.0f} %)")
    pd.DataFrame(rob).to_csv(OUTT/"phase3_chiba_robustness.csv", index=False, encoding="utf-8-sig")

    pr = dict(driver="GTiff", height=prof["height"], width=prof["width"], count=1,
              dtype="uint8", crs=prof["crs"], transform=prof["transform"],
              compress="deflate", nodata=0)
    for nm, arr in (("chiba_flood_change", flood),
                    ("chiba_w_pre", water["pre"]), ("chiba_w_post", water["post"])):
        with rasterio.open(OUTS/f"{nm}.tif", "w", **pr) as o:
            o.write(arr.astype(np.uint8), 1)
    (OUTT/"phase3_chiba_change_summary.json").write_text(json.dumps(dict(
        method="변화 기반 판정 (Matgen 2011 / Giustarini 2013 계열)",
        d_min_db=D_MIN, p_abs_pct=P_ABS, t_abs_db=round(t_abs, 2),
        slope_max_deg=SLOPE_MAX, min_area_ha=MIN_PX*px*100,
        flood_km2=round(area, 2),
        t_pre_db=round(t["pre"], 2), t_post_db=round(t["post"], 2),
        water_pre_km2=round(float(water["pre"].sum()*px), 2),
        water_post_km2=round(float(water["post"].sum()*px), 2),
        area_km2=round(float(prof["width"]*prof["height"]*px), 0),
        change_only_km2=round(float(clean(both & (dd <= -D_MIN) & ~s2).sum()*px), 2),
        abs_only_km2=round(float(clean(F["post"] & (V["post"] < t_abs) & ~s2).sum()*px), 2),
        robust_min_km2=round(min(v1), 2), robust_max_km2=round(max(v1), 2),
        flat_km2=round(float(both.sum()*px), 1)), ensure_ascii=False, indent=1))
    print(f"\n저장 {OUTS}/chiba_flood_change.tif · {OUTT}/phase3_chiba_change_summary.json")


if __name__ == "__main__":
    main()
