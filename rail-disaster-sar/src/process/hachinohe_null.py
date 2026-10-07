"""八戸線 결맞음 저하의 유의성을 두 갈래로 굳힌다.

(1) 위약(placebo) 검정
    참조구간끼리의 차(구간2 − 구간1)로 똑같은 종단면을 만든다.
    지진이 없었던 기간이므로 같은 위치에 골이 생기면 안 된다.
    생기면 그 골은 지진이 아니라 그 자리의 상시 특성이다.

(2) 무작위 횡단선 널 분포
    피해구간 중심 3 km 안 육지에서 길이 400 m 직선 횡단선을 N 개 무작위로 놓고
    고가교와 똑같은 방식(25 m 간격·반경 30 m 중앙값)으로 Δ 를 잰다.
    대조 고가가 2개뿐이라 창 표본이 사실상 4개밖에 안 되는 약점을 이것으로 메운다.
"""
import os, sys, pathlib
os.environ.pop("PYTHONPATH", None)
import numpy as np, geopandas as gpd, pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
OUTT = ROOT/"outputs"/"tables"
sys.path.insert(0, str(ROOT/"src"/"process"))
from analyze_hachinohe_coh import TRACKS, load                      # noqa: E402
from hachinohe_profile import sample_profile, merge_line, STEP, WIN  # noqa: E402

N_RAND = int(os.environ.get("N_RAND", "2000"))
SEED = 20251208


def line_median(g, arr, prof, lo=None, hi=None):
    d, v, _ = sample_profile(g, arr, prof)
    if lo is not None:
        sel = (d >= lo) & (d <= hi); v = v[sel]
    v = v[np.isfinite(v)]
    return float(np.median(v)) if len(v) >= 8 else np.nan


def run(tr):
    coh, prof, keys = load(tr)
    if coh is None: print(f"[{tr}] 산출물 없음"); return None
    cfg = TRACKS[tr]
    refs = [f"{m}_{s}" for m, s, t in cfg["ivl"] if t == "참조" and f"{m}_{s}" in keys]
    ev   = next((f"{m}_{s}" for m, s, t in cfg["ivl"] if t == "★지진" and f"{m}_{s}" in keys), None)
    if len(refs) < 2 or ev is None: print(f"[{tr}] 참조 2개 + 사건 필요"); return None
    dref = np.nanmean(np.stack([coh[k] for k in refs]), axis=0)
    D_ev = coh[ev] - dref
    D_pl = coh[refs[1]] - coh[refs[0]]          # 위약: 참조끼리의 차

    v = gpd.read_file(ROOT/"config/aoi/hachinohe_viaduct.geojson").to_crs(prof["crs"])
    ln = merge_line(v[v.역할 == "피해구간"].geometry.values)[0]

    # 최저 창 위치(사건 기준)
    d, val, _ = sample_profile(ln, D_ev, prof)
    k = int(WIN//STEP)
    wm = np.array([np.nanmean(val[j:j+k]) for j in range(len(val)-k+1)])
    j = int(np.nanargmin(wm)); lo, hi = float(d[j]), float(d[j+k])
    obs_ev = line_median(ln, D_ev, prof, lo, hi)
    obs_pl = line_median(ln, D_pl, prof, lo, hi)
    print(f"\n════ {tr} ({cfg['pass_']})  최저창 종단 {lo:.0f}~{hi:.0f} m")
    print(f"  (1) 위약 검정 — 같은 구간에서")
    print(f"      사건 Δ(사건−참조평균) = {obs_ev:+.3f}")
    print(f"      위약 Δ(참조2−참조1)   = {obs_pl:+.3f}")
    # 위약 종단면에서 이 구간이 몇 번째로 낮은가
    d2, val2, _ = sample_profile(ln, D_pl, prof)
    wm2 = np.array([np.nanmean(val2[i:i+k]) for i in range(len(val2)-k+1)])
    rank_pl = float((wm2 < np.nanmean(val2[j:j+k])).mean()*100)
    print(f"      위약 종단면에서 이 창의 백분위 {rank_pl:.0f}% (낮을수록 상시 골)")

    # (2) 무작위 횡단선
    rng = np.random.default_rng(SEED)
    c = ln.centroid
    res = {"사건": [], "위약": []}
    tried = 0
    while len(res["사건"]) < N_RAND and tried < N_RAND*8:
        tried += 1
        r = 3000*np.sqrt(rng.random()); th = rng.random()*2*np.pi
        x0, y0 = c.x + r*np.cos(th), c.y + r*np.sin(th)
        a = rng.random()*np.pi
        g = LineString([(x0, y0), (x0 + WIN*np.cos(a), y0 + WIN*np.sin(a))])
        m1 = line_median(g, D_ev, prof)
        if not np.isfinite(m1): continue
        m2 = line_median(g, D_pl, prof)
        res["사건"].append(m1); res["위약"].append(m2 if np.isfinite(m2) else np.nan)
    ne = np.array(res["사건"]); npl = np.array(res["위약"]); npl = npl[np.isfinite(npl)]
    pe = float((ne < obs_ev).mean()*100); ze = float((obs_ev - ne.mean())/(ne.std(ddof=1)+1e-9))
    pp = float((npl < obs_pl).mean()*100) if len(npl) else np.nan
    print(f"\n  (2) 무작위 400 m 횡단선 널 (n={len(ne)}, 반경 3 km)")
    print(f"      사건: 널 평균 {ne.mean():+.3f} (sd {ne.std(ddof=1):.3f})  → 관측 {obs_ev:+.3f} "
          f"= 백분위 {pe:.2f}%, z={ze:+.2f}")
    if len(npl):
        zp = float((obs_pl - npl.mean())/(npl.std(ddof=1)+1e-9))
        print(f"      위약: 널 평균 {npl.mean():+.3f} (sd {npl.std(ddof=1):.3f})  → 관측 {obs_pl:+.3f} "
              f"= 백분위 {pp:.2f}%, z={zp:+.2f}")
    else:
        zp = np.nan
    return dict(track=tr, 최저창_시작_m=lo, 최저창_끝_m=hi,
                사건_delta=round(obs_ev, 3), 위약_delta=round(obs_pl, 3),
                위약_종단백분위=round(rank_pl, 1), n널=len(ne),
                널평균_사건=round(float(ne.mean()), 3), 널sd_사건=round(float(ne.std(ddof=1)), 3),
                백분위_사건=round(pe, 2), z_사건=round(ze, 2),
                백분위_위약=round(pp, 2) if np.isfinite(pp) else None,
                z_위약=round(zp, 2) if np.isfinite(zp) else None)


if __name__ == "__main__":
    r = [x for x in (run(t) for t in (sys.argv[1:] or ["t46", "t141"])) if x]
    if r:
        pd.DataFrame(r).to_csv(OUTT/"phase3_hachinohe_null_test.csv", index=False, encoding="utf-8-sig")
        print(f"\n저장 {OUTT}/phase3_hachinohe_null_test.csv")
