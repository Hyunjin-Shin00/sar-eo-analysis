"""지바 케이스의 모든 면적·거리를 원격자(10 m)에서 잰다 — 보고 수치의 단일 출처.

왜 다시 재는가
  · 그동안 면적을 **표시용 격자(약 18 m)로 최대값 재추출한 뒤** 세고 있었다.
    10 m 원자료를 18 m 로 줄일 때 Resampling.max 가 가느다란 물줄기를 한 칸씩 부풀려,
    면적이 31~94 % 과대평가됐다.
  · 표시용 PNG 는 눈으로 보기 위한 것이므로 그대로 두고, **표에 싣는 수치는 이 스크립트 값만 쓴다.**

기준 영역
  · 임계 결정 영역 — SAR 을 처리한 장면 범위 2,710 km² (임계는 이 분포의 하위 1 백분위)
  · 판정·보고 영역 — 지도에 표시하는 범위 (140.100~140.500 E, 35.470~35.720 N)
    화면에서 확인할 수 없는 곳의 값을 표에 싣지 않기 위함.
"""
import os, sys, json, pathlib
os.environ.pop("PYTHONPATH", None)
import numpy as np, rasterio, pyproj
from rasterio.windows import from_bounds
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds as tfb
from rasterio.features import shapes
from shapely.geometry import LineString, shape, box
from shapely.ops import unary_union, transform
from scipy import ndimage

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
OUTS = ROOT/"outputs"/"samples"; OUTT = ROOT/"outputs"/"tables"; LAY = ROOT/"outputs"/"web"/"layers"
RAIL = ROOT/"data"/"raw"/"osm"/"chiba_rail.json"
VIEW = (140.100, 35.470, 140.500, 35.720)
MIN_PX = 50                    # 약 0.5 ha (10 m 격자 50 화소)
LINES = {"JR東金線": "도가네선", "JR外房線": "소토보선", "総武本線": "소부본선",
         "成田線": "나리타선", "JR内房線": "우치보선", "JR久留里線": "구루리선",
         "JR京葉線": "게이요선"}


def main():
    tf = pyproj.Transformer.from_crs(4326, 32654, always_xy=True)
    x0, y0 = tf.transform(VIEW[0], VIEW[1]); x1, y1 = tf.transform(VIEW[2], VIEW[3])
    bb = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    sp = rasterio.open(OUTS/"chiba_v2_water_pre.tif")
    sq = rasterio.open(OUTS/"chiba_v2_water_post.tif")
    px = abs(sp.transform.a*sp.transform.e)/1e6
    full_km2 = sp.width*sp.height*px
    w = from_bounds(*bb, transform=sp.transform).round_offsets().round_lengths()
    tr = sp.window_transform(w)
    view_km2 = w.width*w.height*px
    pre = sp.read(1, window=w).astype(bool)
    post = sq.read(1, window=w).astype(bool)

    # 광학 상시 수체 — 표시 격자(18 m)에서 만든 것을 10 m 로 올린다(최근접이라 면적 보존)
    def to10(npy):
        a = np.load(LAY/npy)
        o = np.zeros(pre.shape, np.uint8)
        reproject(a.astype(np.uint8), o,
                  src_transform=tfb(*VIEW, a.shape[1], a.shape[0]),
                  src_crs=rasterio.crs.CRS.from_epsg(4326),
                  dst_transform=tr, dst_crs=sp.crs,
                  resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
        return o.astype(bool)
    ow_pre, ow_post = to10("_chiba_optwater_pre.npy"), to10("_chiba_optwater_post.npy")

    new = post & ~(pre | ow_pre)
    lab, n = ndimage.label(new, np.ones((3, 3)))
    if n:
        c = np.bincount(lab.ravel()); c[0] = 0
        k = np.zeros(c.size, bool); k[c >= MIN_PX] = True; new = k[lab]

    # 마스크가 서로 얼마나 겹치는지 — 임계가 시기별로 달라 두 수체가 포함관계가 아니다
    inter = float((pre & post).sum()*px)
    A0 = dict(
        sar_overlap_km2=round(inter, 2),
        pre_still_water_pct=round(inter/max(float(pre.sum()*px), 1e-9)*100, 1),
        opt_perm_in_post_km2=round(float((post & ow_pre).sum()*px), 2))
    A = dict(
        threshold_domain_km2=round(full_km2, 0), report_area_km2=round(view_km2, 0),
        sar_water_pre_km2=round(float(pre.sum()*px), 2),
        sar_water_post_km2=round(float(post.sum()*px), 2),
        opt_water_pre_km2=round(float(ow_pre.sum()*px), 2),
        opt_water_post_km2=round(float(ow_post.sum()*px), 2),
        flood_km2=round(float(new.sum()*px), 2),
        flood_polygons=int(ndimage.label(new, np.ones((3, 3)))[1]),
        # 보고하는 침수 면적 — 사건 당일 수체 면적에서 사건 전 수체 면적을 뺀 값
        flood_diff_km2=round(float((post.sum()-pre.sum())*px), 2), **A0)
    print("── 판정·보고 영역 %,.0f km² (임계 결정 영역 %,.0f km²)".replace(",", "")
          % (A["report_area_km2"], A["threshold_domain_km2"]))
    print(f"  SAR  수체 사건 전  {A['sar_water_pre_km2']:6.2f} km²")
    print(f"  SAR  수체 사건 당일 {A['sar_water_post_km2']:6.2f} km²")
    print(f"  광학 수체 사건 전  {A['opt_water_pre_km2']:6.2f} km²")
    print(f"  광학 수체 사건 당일 {A['opt_water_post_km2']:6.2f} km²")
    print(f"  ★ 최종 침수 영역   {A['flood_diff_km2']:6.2f} km²  "
          f"(= {A['sar_water_post_km2']:.2f} − {A['sar_water_pre_km2']:.2f}, 면적 차)")
    print(f"    참고: 화소 단위 차집합은 {A['flood_km2']:.2f} km² ({A['flood_polygons']}개 폴리곤)")
    print(f"  두 시기 SAR 수체가 겹치는 면적 {A['sar_overlap_km2']:.2f} km² "
          f"= 사건 전 수체의 {A['pre_still_water_pct']:.1f} %")
    print(f"  사건 당일 수체 중 광학 상시수체와 겹치는 면적 {A['opt_perm_in_post_km2']:.2f} km²")

    # 노선 거리 — 같은 10 m 판정 결과로
    fu = unary_union([shape(g) for g, v in shapes(new.astype(np.uint8), mask=new, transform=tr) if v])
    d = json.loads(RAIL.read_text())
    segs = {}
    for e in d["elements"]:
        if e["type"] != "way" or e.get("tags", {}).get("railway") != "rail": continue
        nm = e["tags"].get("name", "")
        if nm not in LINES: continue
        p = [(g["lon"], g["lat"]) for g in e.get("geometry", [])]
        if len(p) > 1: segs.setdefault(nm, []).append(LineString(p))
    # ★노선은 판정 영역으로 잘라서 잰다. 자르지 않으면 「영역 밖이라 보지 않은 것」과
    #   「보았는데 침수가 없던 것」이 구분되지 않는다(구루리선은 영역 안 연장이 0 km 다).
    win = box(*bb)
    rows = []
    print("\n── 노선별 (판정 영역으로 자른 뒤 측정)")
    for nm, ko in LINES.items():
        if nm not in segs: continue
        full = transform(tf.transform, unary_union(segs[nm]))
        line = full.intersection(win)
        L_in = line.length/1000
        near = line.intersection(fu.buffer(100)).length/1000 if not line.is_empty else 0.0
        r = dict(노선=ko, 원명=nm,
                 전체연장_km=round(full.length/1000, 2), 영역내연장_km=round(L_in, 2),
                 포함률_pct=round(L_in/(full.length/1000)*100, 1),
                 최단거리_m=(None if line.is_empty else round(line.distance(fu), 0)),
                 within100_km=round(near, 3))
        rows.append(r)
        dm = "판정 불가" if r["최단거리_m"] is None else f"{r['최단거리_m']:7.0f} m"
        print(f"  {ko:6s} 영역내 {L_in:6.2f} km ({r['포함률_pct']:5.1f} %) · 최단 {dm} · 100 m 이내 {near:6.3f} km")
    rows.sort(key=lambda r: (r["최단거리_m"] is None, r["최단거리_m"] or 0))
    out = dict(area=A, lines=rows)
    (OUTT/"phase3_chiba_measure.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n저장 {OUTT}/phase3_chiba_measure.json")


if __name__ == "__main__":
    main()
