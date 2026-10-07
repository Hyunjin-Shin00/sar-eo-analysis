"""결정적 검증 — 장면 안 모든 철도 회랑에 같은 400 m 창 탐색을 돌린다.

기존 대조군은 같은 노선 고가 2구간(독립 창 약 4개)뿐이었다. 그것으로는
「第2柏崎 400 m 가 정말 특별한가」를 답할 수 없다.
여기서는 八戸線 22 km + 東北新幹線 60 km + 青い森鉄道 65 km, 총 148 km 의 철도 회랑을
똑같이 25 m 간격·반경 30 m 중앙값으로 훑고 400 m 창 평균을 구해 전부 줄세운다.

판정 기준을 미리 적어둔다(결과를 보고 고치지 않기 위해):
  - 피해 구간 창이 전체 철도 창 중 **상위 1 % 안**이면 「특이하다」고 말할 수 있다.
  - **상위 5 % 밖**이면 이 케이스는 성공 사례에서 내린다.
  - 그 사이면 「경계선」으로 기록하고 단정하지 않는다.
"""
import os, sys, pathlib
os.environ.pop("PYTHONPATH", None)
import numpy as np, geopandas as gpd, pandas as pd
from shapely.ops import linemerge, unary_union

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
OUTT = ROOT/"outputs"/"tables"
sys.path.insert(0, str(ROOT/"src"/"process"))
from analyze_hachinohe_coh import TRACKS, load                       # noqa: E402
from hachinohe_profile import sample_profile, merge_line, STEP, WIN   # noqa: E402


def windows(line, arr, prof, k):
    d, v, _ = sample_profile(line, arr, prof)
    out = []
    for j in range(0, len(v)-k+1):
        w = v[j:j+k]; w = w[np.isfinite(w)]
        if len(w) < k*0.7: continue
        out.append((float(d[j]), float(w.mean())))
    return out


def run(tr):
    coh, prof, keys = load(tr)
    if coh is None: print(f"[{tr}] 산출물 없음"); return None
    cfg = TRACKS[tr]
    refs = [f"{m}_{s}" for m, s, t in cfg["ivl"] if t == "참조" and f"{m}_{s}" in keys]
    ev = next((f"{m}_{s}" for m, s, t in cfg["ivl"] if t == "★지진" and f"{m}_{s}" in keys), None)
    dref = np.nanmean(np.stack([coh[k] for k in refs]), axis=0)
    D = coh[ev] - dref
    k = int(WIN//STEP)

    rail = gpd.read_file(ROOT/"data/raw/osm/hachinohe_allrail.geojson").to_crs(prof["crs"])
    v = gpd.read_file(ROOT/"config/aoi/hachinohe_viaduct.geojson").to_crs(prof["crs"])
    dmg = merge_line(v[v.역할 == "피해구간"].geometry.values)[0]
    dmg_buf = dmg.buffer(250)

    rows = []
    for nm, g in rail.groupby(rail.name.fillna("(무명)")):
        u = unary_union(g.geometry.values)
        try:
            merged = linemerge(u)
        except Exception:
            merged = u
        segs = [merged] if merged.geom_type == "LineString" else list(getattr(merged, "geoms", [merged]))
        segs = [x for x in segs if x.geom_type == "LineString"]
        for si, ln in enumerate(segs):
            if ln.length < WIN: continue
            for d0, m in windows(ln, D, prof, k):
                p = ln.interpolate(d0+WIN/2)
                rows.append(dict(line=nm, seg=si, d0=d0, val=m,
                                 target=bool(dmg_buf.contains(p)),
                                 x=p.x, y=p.y))
    t = pd.DataFrame(rows)
    if t.empty: print(f"[{tr}] 창 없음"); return None
    t = t.sort_values("val").reset_index(drop=True)
    t["rank"] = np.arange(1, len(t)+1)
    t["pct"] = (t["rank"]/len(t)*100).round(2)

    # 피해 구간 창 중 최저
    tg = t[t.target]
    print(f"\n════ {tr} ({cfg['pass_']})")
    print(f"  전체 철도 창 {len(t)}개 (25 m 간격 겹침) · 노선별 "
          + ", ".join(f"{n} {len(g)}" for n, g in t.groupby('line')))
    print(f"  Δcoherence 분포: 중앙 {t.val.median():+.3f}  5퍼센타일 {t.val.quantile(.05):+.3f}  "
          f"1퍼센타일 {t.val.quantile(.01):+.3f}  최저 {t.val.min():+.3f}")
    if tg.empty:
        print("  ★ 피해 구간 창이 하나도 잡히지 않았다"); return None
    best = tg.iloc[0]
    print(f"  ★ 피해 구간 최저 창: Δ={best.val:+.3f} → 전체 {len(t)}개 중 "
          f"{int(best['rank'])}위 = 상위 {best.pct:.2f} %")
    # 겹치지 않는 창만으로 다시
    ind = t[t.d0 % WIN < STEP/2]
    if len(ind) > 20:
        r2 = int((ind.val < best.val).sum())+1
        print(f"  ★ 겹치지 않는 창만({len(ind)}개): {r2}위 = 상위 {r2/len(ind)*100:.2f} %")
    print("  가장 많이 떨어진 창 10개:")
    for _, r in t.head(10).iterrows():
        print(f"     {r.val:+.3f}  {r.line[:18]:18s} {'★피해구간' if r.target else ''}")
    t.to_csv(OUTT/f"phase3_hachinohe_railnull_{tr}.csv", index=False, encoding="utf-8-sig")
    return dict(track=tr, n창=len(t), 피해최저=round(float(best.val), 3),
                순위=int(best["rank"]), 상위pct=float(best.pct),
                널중앙=round(float(t.val.median()), 3),
                널1pct=round(float(t.val.quantile(.01)), 3),
                널5pct=round(float(t.val.quantile(.05)), 3))


if __name__ == "__main__":
    res = [r for r in (run(t) for t in (sys.argv[1:] or ["t46", "t141"])) if r]
    if res:
        pd.DataFrame(res).to_csv(OUTT/"phase3_hachinohe_railnull.csv", index=False, encoding="utf-8-sig")
        print(f"\n저장 {OUTT}/phase3_hachinohe_railnull.csv")
