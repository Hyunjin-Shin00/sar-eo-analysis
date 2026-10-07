"""八戸線 고가교 결맞음 변화 증거도.

(a) 지도 — 지진 구간 Δ결맞음, 고가 중심선·피해/대조 구간·최저 400 m 창
(b) 종단면 — 고가 중심선을 따라간 Δ (사건 / 위약), 평행선 대조
(c) 구간 시계열 — 피해구간·대조·시가지 널의 결맞음 5구간 추이
"""
import os, sys, pathlib
os.environ.pop("PYTHONPATH", None)
import numpy as np, geopandas as gpd, pandas as pd, rasterio
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from shapely.geometry import Point

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
OUTF = ROOT/"outputs"/"figures"; OUTF.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT/"src"/"process")); sys.path.insert(0, str(ROOT/"src"/"figures"))
import style                                                        # noqa: E402
from analyze_hachinohe_coh import TRACKS, load                      # noqa: E402
from hachinohe_profile import sample_profile, merge_line, STEP, WIN  # noqa: E402

STA = {"本八戸": (141.4888217, 40.5162548), "小中野": (141.5102394, 40.5187266),
       "陸奥湊": (141.5273194, 40.5230771)}
KZ = {"柏崎四丁目": (141.49996, 40.51521), "柏崎五丁目": (141.50362, 40.51694)}
LBLT = {"t46": "하강 t46 · S1A", "t141": "상승 t141 · S1C"}


def panel(tr, fig, gs, row):
    coh, prof, keys = load(tr)
    if coh is None: return False
    cfg = TRACKS[tr]
    refs = [f"{m}_{s}" for m, s, t in cfg["ivl"] if t == "참조" and f"{m}_{s}" in keys]
    ev = next((f"{m}_{s}" for m, s, t in cfg["ivl"] if t == "★지진" and f"{m}_{s}" in keys), None)
    rp = next((f"{m}_{s}" for m, s, t in cfg["ivl"] if t == "★복구" and f"{m}_{s}" in keys), None)
    dref = np.nanmean(np.stack([coh[k] for k in refs]), axis=0)
    D_ev = coh[ev] - dref
    D_pl = coh[refs[1]] - coh[refs[0]] if len(refs) > 1 else None

    v = gpd.read_file(ROOT/"config/aoi/hachinohe_viaduct.geojson").to_crs(prof["crs"])
    ln = merge_line(v[v.역할 == "피해구간"].geometry.values)[0]
    d, val, _ = sample_profile(ln, D_ev, prof)
    k = int(WIN//STEP)
    wm = np.array([np.nanmean(val[j:j+k]) for j in range(len(val)-k+1)])
    j = int(np.nanargmin(wm)); lo, hi = float(d[j]), float(d[j+k])

    # ── (a) 지도
    ax = fig.add_subplot(gs[2*row, 0])
    T = prof["transform"]
    minx, miny, maxx, maxy = ln.bounds
    pad = 300
    c0 = int((minx-pad - T.c)/T.a); c1 = int((maxx+pad - T.c)/T.a)
    r0 = int((maxy+pad - T.f)/T.e); r1 = int((miny-pad - T.f)/T.e)
    c0, c1 = max(c0, 0), min(c1, prof["width"]); r0, r1 = max(r0, 0), min(r1, prof["height"])
    sub = D_ev[r0:r1, c0:c1]
    ext = [T.c + c0*T.a, T.c + c1*T.a, T.f + r1*T.e, T.f + r0*T.e]
    im = ax.imshow(sub, extent=ext, origin="upper", cmap="RdYlBu", vmin=-0.30, vmax=0.10,
                   interpolation="nearest")
    for role, col, lw in (("대조", style.FREE, 2.0), ("피해구간", style.FG, 2.4)):
        for g in v[v.역할 == role].geometry:
            x, y = g.xy; ax.plot(x, y, color=col, lw=lw, zorder=3)
    sl = [ln.interpolate(s) for s in np.linspace(lo, hi, 60)]
    ax.plot([p.x for p in sl], [p.y for p in sl], color=style.ACCENT, lw=4.5, zorder=4,
            solid_capstyle="butt")
    for nm, c in STA.items():
        p = gpd.GeoSeries([Point(*c)], crs=4326).to_crs(prof["crs"]).iloc[0]
        if not (ext[0] < p.x < ext[1] and ext[2] < p.y < ext[3]): continue
        ax.plot(p.x, p.y, "o", ms=5, mfc=style.BG, mec=style.FG, mew=1.4, zorder=5)
        ax.annotate(nm, (p.x, p.y), xytext=(4, 5), textcoords="offset points",
                    fontsize=8, color=style.FG, zorder=6)
    for nm, c in KZ.items():
        q = gpd.GeoSeries([Point(*c)], crs=4326).to_crs(prof["crs"]).iloc[0]
        if not (ext[0] < q.x < ext[1] and ext[2] < q.y < ext[3]): continue
        ax.plot(q.x, q.y, "s", ms=4, mfc="none", mec=style.PAID, mew=1.2, zorder=5)
        ax.annotate(nm, (q.x, q.y), xytext=(4, -10), textcoords="offset points",
                    fontsize=7.5, color=style.PAID, zorder=6)
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"({'ab'[row]}1) {LBLT[tr]} — 지진 구간 Δ결맞음", fontsize=11, color=style.FG, loc="left")
    cb = fig.colorbar(im, ax=ax, fraction=0.055, pad=0.04, orientation="horizontal",
                      location="bottom", aspect=60)
    cb.set_label("Δγ  (사건 구간 − 참조 평균)", fontsize=8, color=style.MUTED)
    cb.ax.tick_params(labelsize=7, colors=style.MUTED)
    ax.legend(handles=[Line2D([], [], color=style.FG, lw=2.4, label="피해 보고구간 本八戸~小中野"),
                       Line2D([], [], color=style.FREE, lw=2.0, label="대조 고가(같은 노선)"),
                       Line2D([], [], color=style.ACCENT, lw=4, label=f"최저 {WIN:.0f} m 창")],
              loc="upper center", bbox_to_anchor=(0.5, -0.30), ncol=3, fontsize=8.5,
              framealpha=0.0, labelcolor=style.FG, handlelength=2.4)

    # ── (b) 종단면
    ax2 = fig.add_subplot(gs[2*row+1, 0])
    ax2.axhline(0, color=style.MUTED, lw=0.7)
    def rmean(a):
        o = np.full(len(a), np.nan)
        for i in range(len(a)):
            lo_, hi_ = max(i-k//2, 0), min(i+k//2+1, len(a))
            w = a[lo_:hi_]; w = w[np.isfinite(w)]
            if len(w) >= k*0.6: o[i] = w.mean()
        return o
    ax2.plot(d, val, color=style.ACCENT, lw=0.8, alpha=0.30)
    ax2.plot(d, rmean(val), color=style.ACCENT, lw=2.6, label=f"사건 구간(지진 포함) · {WIN:.0f} m 이동평균")
    if D_pl is not None:
        _, vpl, _ = sample_profile(ln, D_pl, prof)
        ax2.plot(d, rmean(vpl), color=style.MUTED, lw=1.8, ls="--", label="위약 (참조2 − 참조1)")
    if rp:
        _, vrp, _ = sample_profile(ln, coh[rp]-dref, prof)
        ax2.plot(d, rmean(vrp), color=style.PAID, lw=1.8, label="복구 구간")
    try:
        w = pd.read_csv(ROOT/"outputs/tables"/f"phase3_hachinohe_windows_{tr}.csv")
        cw = w[(w.역할 == "대조") & (w.항목 == "지진")].창평균
        if len(cw):
            ax2.axhspan(cw.mean()-cw.std(ddof=1), cw.mean()+cw.std(ddof=1),
                        color=style.FREE, alpha=0.16, zorder=0)
            ax2.axhline(cw.mean(), color=style.FREE, lw=1.1, ls=":",
                        label=f"대조 고가 {WIN:.0f} m 창 ±1sd")
    except Exception:
        pass
    ax2.axvspan(lo, hi, color=style.ACCENT, alpha=0.13, zorder=0)
    ax2.annotate(f"최저 {WIN:.0f} m 창\nΔ={wm[j]:+.3f}", ((lo+hi)/2, min(np.nanmin(val), -0.25)),
                 ha="center", va="bottom", fontsize=8, color=style.ACCENT)
    for nm, c in (("小中野", STA["小中野"]), ("本八戸", STA["本八戸"])):
        p = gpd.GeoSeries([Point(*c)], crs=4326).to_crs(prof["crs"]).iloc[0]
        s = ln.project(p)
        ax2.axvline(s, color=style.FG, lw=0.7, alpha=0.5)
        ax2.annotate(nm, (s, 0.06), fontsize=7.5, color=style.FG, ha="center")
    ax2.set_xlabel("고가 중심선 종단거리 (m, 0 = 小中野 쪽)", fontsize=9)
    ax2.set_ylabel("Δ결맞음", fontsize=9)
    ax2.set_title(f"({'ab'[row]}2) {LBLT[tr]} — 고가 종단면", fontsize=11, color=style.FG, loc="left")
    ax2.grid(alpha=0.25); ax2.legend(fontsize=7.5, framealpha=0.2, labelcolor=style.FG)
    ax2.set_ylim(-0.30, 0.10)
    return True


def main():
    style.setup()
    trs = [t for t in (sys.argv[1:] or ["t46", "t141"])
           if (ROOT/"data/interim/coh"/f"hachinohe_{t}_"
               f"{TRACKS[t]['ivl'][2][0]}_{TRACKS[t]['ivl'][2][1]}_{TRACKS[t]['sw']}_coh.tif").exists()]
    fig = plt.figure(figsize=(13, 7.4*len(trs)))
    gs = fig.add_gridspec(2*len(trs), 1, height_ratios=[1.35, 1.0]*len(trs), hspace=0.42)
    n = 0
    for i, t in enumerate(trs):
        if panel(t, fig, gs, i): n += 1
    fig.suptitle("八戸線 本八戸~小中野 고가교 — 2025-12-08 青森県東方沖 지진(Mj7.5, 八戸 진도 6강)\n"
                 "Sentinel-1 결맞음 변화 · 보도: 약 20개소 손상, 第2柏崎高架橋 약 400 m 기둥 曲げ破壊",
                 fontsize=13, color=style.FG, y=0.985)
    out = OUTF/"phase3_hachinohe_evidence.png"
    fig.savefig(out); print(f"저장 {out}  (패널 {n}개)")


if __name__ == "__main__":
    main()
