"""八戸線 本八戸~小中野 고가교 — 2025-12-08 青森県東方沖 지진 결맞음 변화 검정.

사건
  2025-12-08 23:15 JST Mj7.5 / 八戸市 최대진도 6강.
  本八戸―小中野 간 고가교 약 20개소 손상(콘크리트 박락·철근 노출).
  그 중 第2柏崎高架橋(1977년 준공, 연장 1.8 km 중 약 400 m) 기둥 다수 曲げ破壊.
  12/9 八戸~久慈 전 열차 운휴 → 12/22 鮫~久慈 재개 → 12/30 09시 전선 재개.

설계
  같은 궤도·같은 시간기선(12일) 연속 구간을 늘어놓고, 피해구간에서만
  ① 사건 구간에 결맞음이 떨어지고 ② 복구 구간에도 떨어져 있다가 ③ 사후에 회복하는지 본다.
  ①만 있으면 지진동, ①+②는 손상+복구공사, 아무것도 없으면 미탐지다.

대조군 2종
  (a) 같은 八戸線·같은 시가지의 피해구간 밖 고가 5개(합 1,951 m) — 피해구간 1,967 m 와 총연장이 같다.
  (b) 주변 시가지 화소(철도 200 m 버퍼 제외) — 널 분포.

주의: DInSAR 변위는 같은 페어에서 언랩 실패로 폐기했다(phase3_aomori_findings.md).
      결맞음 변화는 언랩이 필요 없으므로 그 실패와 무관하다.
"""
import os, sys, pathlib
os.environ.pop("PYTHONPATH", None)
import numpy as np, rasterio, geopandas as gpd, pandas as pd
from rasterio.warp import reproject, Resampling
from rasterio.features import rasterize
from shapely.ops import unary_union

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
COH  = ROOT/"data"/"interim"/"coh"
OUTT = ROOT/"outputs"/"tables"; OUTS = ROOT/"outputs"/"samples"/"hachinohe_coh"
OUTT.mkdir(parents=True, exist_ok=True); OUTS.mkdir(parents=True, exist_ok=True)

TRACKS = {
 "t46": dict(sw="IW1", pass_="DESC S1A",
             ivl=[("1103", "1115", "참조"), ("1115", "1127", "참조"),
                  ("1127", "1209", "★지진"), ("1209", "1221", "★복구"),
                  ("1221", "0102", "사후")],
             lab={"1103": "11-03", "1115": "11-15", "1127": "11-27",
                  "1209": "12-09", "1221": "12-21", "0102": "01-02"}),
 "t141": dict(sw="IW3", pass_="ASC S1C",
             ivl=[("1104", "1116", "참조"), ("1116", "1128", "참조"),
                  ("1128", "1210", "★지진"), ("1210", "1222", "★복구"),
                  ("1222", "0103", "사후")],
             lab={"1104": "11-04", "1116": "11-16", "1128": "11-28",
                  "1210": "12-10", "1222": "12-22", "0103": "01-03"}),
}
RAD = float(os.environ.get("RAD", "30"))   # 고가 중심선 버퍼 (m). 고가 높이 8 m → 지형보정 잔차 ~10 m 고려


def coh_band(p):
    with rasterio.open(p) as d:
        for i, nm in enumerate(d.descriptions, 1):
            if nm and nm.lower().startswith("coh"): return i
    return 1


def load(tr):
    cfg = TRACKS[tr]; sw = cfg["sw"]
    keys, paths = [], {}
    for m, s, _ in cfg["ivl"]:
        p = COH/f"hachinohe_{tr}_{m}_{s}_{sw}_coh.tif"
        if p.exists(): keys.append(f"{m}_{s}"); paths[f"{m}_{s}"] = p
    if not keys: return None, None, None
    ref = paths[keys[0]]
    with rasterio.open(ref) as a:
        prof = a.profile; shp = (a.height, a.width)
    out = {}
    for k in keys:
        with rasterio.open(paths[k]) as b:
            z = np.full(shp, np.nan, np.float32)
            reproject(rasterio.band(b, coh_band(paths[k])), z,
                      src_transform=b.transform, src_crs=b.crs,
                      dst_transform=prof["transform"], dst_crs=prof["crs"],
                      resampling=Resampling.bilinear, src_nodata=0, dst_nodata=np.nan)
        z[z <= 0] = np.nan
        out[k] = z
    return out, prof, keys


def rast(geoms, prof):
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms: return np.zeros((prof["height"], prof["width"]), bool)
    return rasterize([(g, 1) for g in geoms], out_shape=(prof["height"], prof["width"]),
                     transform=prof["transform"], fill=0, dtype="uint8").astype(bool)


def run(tr):
    cfg = TRACKS[tr]
    coh, prof, keys = load(tr)
    if coh is None:
        print(f"[{tr}] 결맞음 산출물 없음"); return None
    valid = np.all([np.isfinite(coh[k]) for k in keys], axis=0)
    px = abs(prof["transform"].a*prof["transform"].e)/1e6
    print(f"\n════ {tr} ({cfg['pass_']}, {cfg['sw']}) 구간 {len(keys)}개  "
          f"격자 {prof['width']}x{prof['height']}  공통유효 {valid.sum()*px:.1f} km²")

    v = gpd.read_file(ROOT/"config/aoi/hachinohe_viaduct.geojson").to_crs(prof["crs"])
    rail = gpd.read_file(ROOT/"data/raw/osm/hachinohe_rail.geojson").to_crs(prof["crs"])
    ru = unary_union(rail.geometry.values)

    # 널 분포: 피해구간 중심 3 km 안의 시가지에서 철도 200 m 버퍼를 뺀 곳
    dmg = unary_union(v[v.역할 == "피해구간"].geometry.values)
    nullm = rast([dmg.centroid.buffer(3000)], prof) & ~rast([ru.buffer(200)], prof) & valid

    rows = []
    for _, b in v.iterrows():
        bm = rast([b.geometry.buffer(RAD)], prof) & valid
        if bm.sum() < 5: continue
        r = dict(id=int(b.id), 역할=b.역할, 구간명=b.구간명, 길이_m=float(b.len_m), n=int(bm.sum()))
        for k in keys: r[k] = round(float(np.nanmedian(coh[k][bm])), 3)
        rows.append(r)
    # 그룹 집계
    for role in ("피해구간", "대조"):
        gm = rast([g.buffer(RAD) for g in v[v.역할 == role].geometry], prof) & valid
        r = dict(id=-1, 역할=f"[{role} 합]", 구간명="", 길이_m=float(v[v.역할 == role].len_m.sum()),
                 n=int(gm.sum()))
        for k in keys: r[k] = round(float(np.nanmedian(coh[k][gm])), 3)
        rows.append(r)
    r = dict(id=0, 역할="[시가지 널]", 구간명="", 길이_m=np.nan, n=int(nullm.sum()))
    for k in keys: r[k] = round(float(np.nanmedian(coh[k][nullm])), 3)
    rows.append(r)

    t = pd.DataFrame(rows)
    refs = [f"{m}_{s}" for m, s, tag in cfg["ivl"] if tag == "참조" and f"{m}_{s}" in keys]
    ev   = next((f"{m}_{s}" for m, s, tag in cfg["ivl"] if tag == "★지진" and f"{m}_{s}" in keys), None)
    rp   = next((f"{m}_{s}" for m, s, tag in cfg["ivl"] if tag == "★복구" and f"{m}_{s}" in keys), None)
    if refs:
        t["참조"] = t[refs].mean(axis=1).round(3)
        if ev: t["Δ지진"] = (t[ev] - t["참조"]).round(3)
        if rp: t["Δ복구"] = (t[rp] - t["참조"]).round(3)
    t.to_csv(OUTT/f"phase3_hachinohe_coh_{tr}.csv", index=False, encoding="utf-8-sig")
    show = ["역할", "구간명", "길이_m", "n"] + keys + [c for c in ("참조", "Δ지진", "Δ복구") if c in t]
    print(t[show].to_string(index=False))

    # 유의성: 피해 way vs 대조 way
    out = dict(track=tr, pass_=cfg["pass_"], 버퍼_m=RAD)
    for col, nm in ((("Δ지진"), "지진"), (("Δ복구"), "복구")):
        if col not in t: continue
        d = t[t.역할 == "피해구간"][col].values
        c = t[t.역할 == "대조"][col].values
        if len(d) < 2 or len(c) < 2: continue
        z = (d.mean() - c.mean())/(c.std(ddof=1)+1e-9)
        print(f"  {nm}: 피해 {len(d)}개 평균 {d.mean():+.3f} | 대조 {len(c)}개 평균 {c.mean():+.3f} "
              f"(sd {c.std(ddof=1):.3f}) → z={z:+.2f}")
        out[f"피해_{nm}"] = round(float(d.mean()), 3); out[f"대조_{nm}"] = round(float(c.mean()), 3)
        out[f"z_{nm}"] = round(float(z), 2)

    # 화소 단위: 피해구간 화소 Δ vs 시가지 널 화소 Δ
    if refs and ev:
        dref = np.nanmean(np.stack([coh[k] for k in refs]), axis=0)
        for tag, k in ((("지진"), ev), (("복구"), rp)):
            if k is None: continue
            dd = coh[k] - dref
            dm = rast([g.buffer(RAD) for g in v[v.역할 == "피해구간"].geometry], prof) & valid
            a = dd[dm]; a = a[np.isfinite(a)]
            b = dd[nullm]; b = b[np.isfinite(b)]
            if len(a) and len(b):
                z = (np.median(a) - np.median(b))/(b.std()+1e-9)
                pct = (b < np.median(a)).mean()*100
                print(f"  {tag}(화소): 피해 Δ중앙 {np.median(a):+.3f} (n={len(a)}) | "
                      f"널 중앙 {np.median(b):+.3f} (n={len(b)}, sd {b.std():.3f}) → z={z:+.2f}, 백분위 {pct:.1f}%")
                out[f"화소z_{tag}"] = round(float(z), 2); out[f"화소백분위_{tag}"] = round(float(pct), 1)
            pr = dict(prof); pr.update(count=1, dtype="float32", nodata=np.nan, compress="deflate")
            with rasterio.open(OUTS/f"dcoh_{tr}_{tag}.tif", "w", **pr) as o:
                o.write(dd.astype(np.float32), 1)
        np.save(OUTS/f"coh_stack_{tr}.npy", np.stack([coh[k] for k in keys]))
        (OUTS/f"keys_{tr}.txt").write_text("\n".join(keys))
    return out


def main():
    trs = sys.argv[1:] or ["t46", "t141"]
    res = [r for r in (run(t) for t in trs) if r]
    if res:
        pd.DataFrame(res).to_csv(OUTT/"phase3_hachinohe_coh_test.csv", index=False, encoding="utf-8-sig")
        print(f"\n저장 {OUTT}/phase3_hachinohe_coh_*.csv , {OUTS}")


if __name__ == "__main__":
    main()
