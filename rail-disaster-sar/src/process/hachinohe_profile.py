"""八戸線 고가교 결맞음 변화의 '위치'를 본다.

피해 보고는 「本八戸―小中野 약 1.8 km 중 第2柏崎高架橋 약 400 m」로 구간을 특정한다.
구간 평균만 보면 나머지 1.4 km 가 신호를 희석한다. 그래서
  ① 고가 중심선을 따라 25 m 간격으로 Δ결맞음 종단면을 만들고
  ② 400 m 창을 미끄러뜨려 창 평균 Δ 를 구한 뒤
  ③ 피해구간 창들이 대조 고가 창들 전체 분포에서 몇 번째인지 본다.
창 단위로 비교하면 화소 간 공간상관을 자동으로 흡수한다(창 안이 상관돼 있어도 창끼리는 거의 독립).
"""
import os, sys, pathlib
os.environ.pop("PYTHONPATH", None)
import numpy as np, rasterio, geopandas as gpd, pandas as pd
from rasterio.warp import reproject, Resampling
from shapely.ops import linemerge, unary_union
from shapely.geometry import LineString, Point

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
COH  = ROOT/"data"/"interim"/"coh"
OUTT = ROOT/"outputs"/"tables"; OUTS = ROOT/"outputs"/"samples"/"hachinohe_coh"
OUTT.mkdir(parents=True, exist_ok=True); OUTS.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT/"src"/"process"))
from analyze_hachinohe_coh import TRACKS, coh_band, load          # noqa: E402

STEP = 25.0       # 종단면 표본 간격 (m)
RAD  = 30.0       # 표본 반경 (m) — 고가 높이 8 m 의 지형보정 잔차(~10 m)를 덮는다
WIN  = 400.0      # 보도된 피해 연장 (m)


def sample_profile(line, arr, prof, step=STEP, rad=RAD):
    """선을 따라 step 간격으로 반경 rad 안의 중앙값을 뽑는다."""
    n = max(int(line.length//step), 1)
    T = ~prof["transform"]; H, W = prof["height"], prof["width"]
    rr = int(np.ceil(rad/abs(prof["transform"].a)))
    d, v, xy = [], [], []
    for i in range(n+1):
        s = min(i*step, line.length); p = line.interpolate(s)
        c, r = T*(p.x, p.y); c, r = int(round(c)), int(round(r))
        r0, r1 = max(r-rr, 0), min(r+rr+1, H); c0, c1 = max(c-rr, 0), min(c+rr+1, W)
        if r1 <= r0 or c1 <= c0: d.append(s); v.append(np.nan); xy.append((p.x, p.y)); continue
        w = arr[r0:r1, c0:c1]
        yy, xx = np.mgrid[r0:r1, c0:c1]
        m = ((yy-r)**2 + (xx-c)**2) <= rr**2
        w = w[m & np.isfinite(w)]
        d.append(s); v.append(float(np.median(w)) if w.size else np.nan); xy.append((p.x, p.y))
    return np.array(d), np.array(v), np.array(xy)


def merge_line(geoms):
    m = linemerge(unary_union(list(geoms)))
    if m.geom_type == "LineString": return [m]
    return sorted(list(m.geoms), key=lambda g: -g.length)


def run(tr):
    coh, prof, keys = load(tr)
    if coh is None: print(f"[{tr}] 산출물 없음"); return
    cfg = TRACKS[tr]
    refs = [f"{m}_{s}" for m, s, tag in cfg["ivl"] if tag == "참조" and f"{m}_{s}" in keys]
    ev   = next((f"{m}_{s}" for m, s, tag in cfg["ivl"] if tag == "★지진" and f"{m}_{s}" in keys), None)
    rp   = next((f"{m}_{s}" for m, s, tag in cfg["ivl"] if tag == "★복구" and f"{m}_{s}" in keys), None)
    if not refs or ev is None: print(f"[{tr}] 참조/사건 구간 부족"); return
    dref = np.nanmean(np.stack([coh[k] for k in refs]), axis=0)
    D = {"지진": coh[ev] - dref}
    if rp: D["복구"] = coh[rp] - dref

    v = gpd.read_file(ROOT/"config/aoi/hachinohe_viaduct.geojson").to_crs(prof["crs"])
    segs = []
    for role in ("피해구간", "대조"):
        for ln in merge_line(v[v.역할 == role].geometry.values):
            if ln.length >= WIN: segs.append((role, ln))
    print(f"\n════ {tr} ({cfg['pass_']}) 종단면 — {WIN:.0f} m 창")
    for role, ln in segs:
        print(f"   {role} 연속구간 {ln.length:.0f} m")

    rows, wins = [], []
    for si, (role, ln) in enumerate(segs):
        for tag, arr in D.items():
            d, val, xy = sample_profile(ln, arr, prof)
            for dd, vv, (x, y) in zip(d, val, xy):
                rows.append(dict(track=tr, seg=si, 역할=role, 구간="", 항목=tag,
                                 거리_m=round(float(dd)), delta=round(float(vv), 4) if np.isfinite(vv) else None,
                                 x=round(x), y=round(y)))
            k = max(int(WIN//STEP), 1)
            for j in range(0, len(val)-k+1):
                w = val[j:j+k]; w = w[np.isfinite(w)]
                if len(w) < k*0.6: continue
                wins.append(dict(track=tr, 역할=role, 항목=tag, seg=si,
                                 시작_m=round(float(d[j])), 중앙_m=round(float(d[j]+WIN/2)),
                                 창평균=round(float(w.mean()), 4)))
    pf = pd.DataFrame(rows); wf = pd.DataFrame(wins)
    pf.to_csv(OUTT/f"phase3_hachinohe_profile_{tr}.csv", index=False, encoding="utf-8-sig")
    wf.to_csv(OUTT/f"phase3_hachinohe_windows_{tr}.csv", index=False, encoding="utf-8-sig")

    out = []
    for tag in D:
        w = wf[wf.항목 == tag]
        dmg = w[w.역할 == "피해구간"]; ctl = w[w.역할 == "대조"]
        if dmg.empty or ctl.empty: continue
        best = dmg.loc[dmg.창평균.idxmin()]
        pct = (ctl.창평균 < best.창평균).mean()*100
        z = (best.창평균 - ctl.창평균.mean())/(ctl.창평균.std(ddof=1)+1e-9)
        print(f"\n  [{tag}] 피해구간 창 {len(dmg)}개 (평균 {dmg.창평균.mean():+.3f}) / "
              f"대조 창 {len(ctl)}개 (평균 {ctl.창평균.mean():+.3f}, sd {ctl.창평균.std(ddof=1):.3f})")
        print(f"       최저 피해창: seg{int(best.seg)} 중심 {best.중앙_m:.0f} m, Δ={best.창평균:+.3f}  "
              f"→ 대조 창 중 더 낮은 비율 {pct:.1f}%, z={z:+.2f}")
        out.append(dict(track=tr, 항목=tag, n피해창=len(dmg), n대조창=len(ctl),
                        피해평균=round(float(dmg.창평균.mean()), 3),
                        대조평균=round(float(ctl.창평균.mean()), 3),
                        대조sd=round(float(ctl.창평균.std(ddof=1)), 3),
                        최저피해창=round(float(best.창평균), 3), 백분위=round(float(pct), 1),
                        z=round(float(z), 2)))
        # 종단면 요약: 피해 연속구간의 25 m 표본 중 가장 낮은 연속 400 m
        for si, g in dmg.groupby("seg"):
            gg = g.sort_values("중앙_m")
            print(f"       seg{si} 창 종단: " +
                  " ".join(f"{r.중앙_m:.0f}:{r.창평균:+.2f}" for _, r in gg.iloc[::max(len(gg)//8, 1)].iterrows()))
    if out:
        pd.DataFrame(out).to_csv(OUTT/f"phase3_hachinohe_window_test_{tr}.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장 {OUTT}/phase3_hachinohe_profile_{tr}.csv , _windows_{tr}.csv")


if __name__ == "__main__":
    for t in (sys.argv[1:] or ["t46", "t141"]):
        run(t)
