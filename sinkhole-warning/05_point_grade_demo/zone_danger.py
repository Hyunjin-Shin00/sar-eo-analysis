# -*- coding: utf-8 -*-
"""위험 구역을 폴리곤으로 그린 보고서 지도.

주의 구역(선별)은 지금까지처럼 격자 채색으로 두고, **위험 경보 조건이 성립한 격자**를
하나로 합쳐(shapely unary_union) 그 외곽선을 폴리곤으로 덧그린다.

격자별 경보 판정은 공사장 판정과 같은 방식이다 - 반경 400 m 버퍼 최댓값으로 12지표 중
cum1·cumF 를 만들고, 거기서 규칙이 쓰는 파생값(3스텝 증가량·1스텝 증가량·3스텝 표준화점수)을
뽑아 세 기준값을 동시에 넘는 상태가 K회 연속인지 본다. 선별에 진입한 격자만 대상으로 한다.

usage: zone_danger.py <보고서 html> <기준일 YYYY-MM-DD> <출력 html>
"""
import os, sys, io, re, json, base64, datetime
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(HERE)
LIB = os.path.join(DEMO, "_lib")
os.environ.setdefault("DATA_ROOT", LIB)
SB = os.path.join(LIB, "analysis", "sbas_sweep")
sys.path.insert(0, SB)
sys.path.insert(0, os.path.join(LIB, "analysis", "sinkhole"))
import numpy as np
import report_site as RS
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib import font_manager as fm
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
import contextily as cx
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import box
from shapely.ops import unary_union, transform as shp_transform
import indicators as ind

SRC, ASOF_S, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
d0 = datetime.date.fromisoformat(ASOF_S)
ASOF = d0.year + (d0 - datetime.date(d0.year, 1, 1)).days / RS.DAYS
for _c in ("Noto Sans CJK JP", "Noto Sans CJK KR"):
    if _c in {f.name for f in fm.fontManager.ttflist}:
        plt.rcParams["font.family"] = _c
        break
plt.rcParams["axes.unicode_minus"] = False

J = json.load(open(SRC.replace(".html", ".json")))
xr, yr = RS.SL.loaders._TR_M.transform([J["lon"]], [J["lat"]])
h = 25.0
back = Transformer.from_crs(RS.SL.loaders._TR_M.target_crs, 4326, always_xy=True)
lons, lats = back.transform([xr[0] - h, xr[0] + h, xr[0] + h, xr[0] - h],
                            [yr[0] - h, yr[0] - h, yr[0] + h, yr[0] + h])
shp_vtx = list(zip(lons, lats))

e, kinds = RS.FX.build_entry(RS.REGION, RS.COH, RS.TCOH, RS.KSET)
sb = e["kinds"]["SBAS"]
yrs, disp = sb["years"], sb["disp"]
m_ = yrs <= ASOF + 1e-9
yrs, disp = yrs[m_], disp[:, m_]
GT = RS.gate_setup()
g, TH1 = GT["rule"], GT["th"]
srt = {f: GT["srt"][RS.LO.FEATS.index(f)] for f in g["features"]}
RB = RS.region_block()
S2 = RB["s2"]                                   # 2단(위험 경보) 규칙 - 지역 확정본
S2_RULE, S2_K = S2["rule"], int(S2["K"])
print("경보 규칙 %s · K=%d" % (S2_RULE, S2_K), flush=True)

S_, N_, W_, Eb = e["box"]
TRm = RS.SL.loaders._TR_M
xs_, ys_ = TRm.transform([W_, Eb], [S_, N_])
step = 50.0
gx = np.arange(xs_[0], xs_[1] + step, step)
gy = np.arange(ys_[0], ys_[1] + step, step)
GX, GY = np.meshgrid(gx, gy)
tree = cKDTree(np.c_[sb["x"], sb["y"]])
nb = tree.query_ball_point(np.c_[GX.ravel(), GY.ravel()], RS.R)
cnt = np.array([len(i) for i in nb])
flat = np.concatenate([np.asarray(i, int) for i in nb if len(i)])
off = np.r_[0, np.cumsum(cnt[cnt > 0])[:-1]]
has = cnt > 0
NC = len(nb)


def bufmax(v):
    o = np.full(NC, np.nan)
    o[has] = np.maximum.reduceat(np.nan_to_num(v[flat], nan=-1e18), off)
    return np.where(o <= -1e17, np.nan, o)


def pctile(f, v):
    sf = srt[f]
    o = np.full(v.shape, np.nan)
    fin = np.isfinite(v)
    o[fin] = (np.searchsorted(sf, v[fin], "left") + np.searchsorted(sf, v[fin], "right")) / (2 * len(sf))
    return 1.0 - o if GT["flips"][RS.LO.FEATS.index(f)] else o


CACHE = os.path.join(HERE, "zone_cache", "dz_cache_%s.npz" % ASOF_S)
if os.path.exists(CACHE):                      # 지도만 손볼 때 재계산을 건너뛴다
    _z = np.load(CACHE)
    gate_ever, gate_now = _z["ge"].astype(bool), _z["gn"].astype(bool)
    dang_now, dang_ever = _z["dn"].astype(bool), _z["de"].astype(bool)
    print("격자 판정 캐시 사용 - %s" % CACHE, flush=True)
else:
    # ── 에폭별로 격자 버퍼 최댓값을 쌓는다 (cum1·cumF·게이트 점수)
    T = len(yrs)
    C1 = np.full((NC, T), np.nan)
    CF = np.full((NC, T), np.nan)
    SC = np.full((NC, T), np.nan)
    for j in range(T):
        tj = float(yrs[j])
        c1 = bufmax(np.asarray(RS.E.cum_window(disp, yrs, tj, 1.0), float))
        cf = bufmax(np.asarray(RS.E.cum_window(disp, yrs, tj, None), float))
        C1[:, j], CF[:, j] = c1, cf
        tg = ind.trend_grade(disp, yrs, tj)
        dv = bufmax(np.asarray(tg["v_late"] - tg["v_early"], float))
        P = np.column_stack([pctile(f, {"cum1": c1, "dv": dv}[f]) for f in g["features"]])
        with np.errstate(all="ignore"):
            SC[:, j] = RS.OP.COMB[g["comb"]](P, axis=1) if P.shape[1] > 1 else P[:, 0]
        if (j + 1) % 25 == 0 or j == T - 1:
            print("  %3d/%d 에폭" % (j + 1, T), flush=True)

    # ── 주의 구역(선별) - 최근 1년 창이 확보되는 에폭부터, K에폭 연속을 진입으로 본다
    GK = int(g["K"])
    gate_ever = np.zeros(NC, bool)
    run = np.zeros(NC, int)
    gate_now = np.zeros(NC, bool)
    for j in range(T):
        if yrs[j] - yrs[0] < 1.0:
            continue
        hit = np.nan_to_num(SC[:, j], nan=-1e18) >= TH1
        run = np.where(hit, run + 1, 0)
        gate_ever |= run >= GK
        gate_now = hit

    # ── 위험 경보 - 규칙이 쓰는 파생값을 만들어 세 조건 AND, K회 연속
    BASEV = {"cum1": C1, "cumF": CF}


    def derived(name, j):
        """<지표><_d창|_z창> 값을 에폭 j 에서 계산한다. 창 부족이면 NaN."""
        b, suf = name.split("_")
        F = BASEV[b]
        m = int(suf[1:])
        if j - m < 0:
            return np.full(NC, np.nan)
        if suf[0] == "d":
            return F[:, j] - F[:, j - m]
        w = F[:, j - m:j]
        with np.errstate(all="ignore"):
            mu, sd = np.nanmean(w, axis=1), np.nanstd(w, axis=1)
        sd = np.where(np.isfinite(sd) & (sd > 1e-6), sd, np.nan)
        return (F[:, j] - mu) / sd


    need = max(int(n.split("_")[1][1:]) for n, _ in S2_RULE)
    j0 = (RS.LB.MIN_EP - 1) + need if hasattr(RS, "LB") else 5 + need
    run2 = np.zeros(NC, int)
    dang_ever = np.zeros(NC, bool)
    dang_now = np.zeros(NC, bool)
    for j in range(j0, T):
        ok = np.ones(NC, bool)
        for nm, th in S2_RULE:
            ok &= np.nan_to_num(derived(nm, j), nan=-1e18) >= float(th)
        run2 = np.where(ok, run2 + 1, 0)
        fire = run2 >= S2_K
        dang_ever |= fire
        dang_now = fire
    dang_now &= gate_ever                       # 선별 진입 격자만 경보 대상
    dang_ever &= gate_ever
    print("주의 누적 %d칸 · 위험(기준일) %d칸 · 위험(누적) %d칸"
          % (gate_ever.sum(), dang_now.sum(), dang_ever.sum()), flush=True)

    np.savez_compressed(CACHE, ge=gate_ever, gn=gate_now, dn=dang_now, de=dang_ever)

# ── 위험 격자를 하나로 합쳐 폴리곤으로 만든다
to3857 = Transformer.from_crs(TRm.target_crs, 3857, always_xy=True)
GXf, GYf = GX.ravel(), GY.ravel()
polys = []
if dang_now.any():
    u = unary_union([box(x - step / 2, y - step / 2, x + step / 2, y + step / 2)
                     for x, y in zip(GXf[dang_now], GYf[dang_now])])
    polys = list(u.geoms) if u.geom_type == "MultiPolygon" else [u]
area_d = sum(p.area for p in polys) / 1e6
print("위험 폴리곤 %d개 · 면적 %.2f km²" % (len(polys), area_d), flush=True)
poly3857 = [shp_transform(lambda a, b: to3857.transform(a, b), p) for p in polys]

# ── 구역을 GeoJSON 으로도 저장한다 (지도에 바로 얹을 수 있게)
from shapely.geometry import mapping
to4326 = Transformer.from_crs(TRm.target_crs, 4326, always_xy=True)


def feats(mask, kind, color):
    """격자 마스크 → 폴리곤 병합 → EPSG:4326 Feature 목록."""
    if not mask.any():
        return []
    u = unary_union([box(x - step / 2, y - step / 2, x + step / 2, y + step / 2)
                     for x, y in zip(GXf[mask], GYf[mask])])
    gs = list(u.geoms) if u.geom_type == "MultiPolygon" else [u]
    out = []
    for i, p in enumerate(sorted(gs, key=lambda g: -g.area), 1):
        p4 = shp_transform(lambda a, b: to4326.transform(a, b), p)
        out.append({"type": "Feature",
                    "properties": {"kind": kind, "zone_id": i, "asof": ASOF_S,
                                   "area_m2": int(round(p.area)),
                                   "area_ha": round(p.area / 1e4, 2), "color": color},
                    "geometry": mapping(p4)})
    return out


GJ = OUT.replace(".html", "") + "_zones.geojson"
fc = {"type": "FeatureCollection",
      "note": "주의 = 기준일까지 한 번이라도 선별 기준 성립 · 위험 = 기준일 시점 경보 조건 성립",
      "features": feats(gate_ever, "주의", "#FFBF00") + feats(dang_now, "위험", "#e03030")}
io.open(GJ, "w", encoding="utf-8").write(json.dumps(fc, ensure_ascii=False))
print("GeoJSON 저장 %s · 주의 %d개 · 위험 %d개"
      % (GJ, sum(1 for f in fc["features"] if f["properties"]["kind"] == "주의"),
         sum(1 for f in fc["features"] if f["properties"]["kind"] == "위험")), flush=True)

X3, Y3 = to3857.transform(GX, GY)
lo = [v[0] for v in shp_vtx] + [shp_vtx[0][0]]
la = [v[1] for v in shp_vtx] + [shp_vtx[0][1]]
px, py = Transformer.from_crs(4326, 3857, always_xy=True).transform(lo, la)
cx0, cy0 = float(np.mean(px[:-1])), float(np.mean(py[:-1]))
hs = step / 2.0
ex_, ey_ = np.r_[gx - hs, gx[-1] + hs], np.r_[gy - hs, gy[-1] + hs]
bx_m = np.r_[ex_, np.full(len(ey_), ex_[-1]), ex_[::-1], np.full(len(ey_), ex_[0])]
by_m = np.r_[np.full(len(ex_), ey_[0]), ey_, np.full(len(ex_), ey_[-1]), ey_[::-1]]
bxx, bxy = to3857.transform(bx_m, by_m)

OK_GATE = gate_ever.reshape(GX.shape)
OK_DANG = dang_now.reshape(GX.shape)
m_gate = np.ma.masked_where(~OK_GATE, OK_GATE.astype(float))
m_dang = np.ma.masked_where(~OK_DANG, OK_DANG.astype(float))
cm_gate = matplotlib.colors.ListedColormap(["#FFBF00"])     # 주의 - 주황과 노랑의 중간
cm_dang = matplotlib.colors.ListedColormap(["#e03030"])     # 위험 - 붉은색
area_ever = gate_ever.sum() * step * step / 1e6
area_now = gate_now.sum() * step * step / 1e6

fig, axs = plt.subplots(1, 2, figsize=(11.4, 6.2))
ZOOM, PAD = 500.0, 0.12
ex0, ex1, ey0, ey1 = X3.min(), X3.max(), Y3.min(), Y3.max()
cxa, cya = (ex0 + ex1) / 2.0, (ey0 + ey1) / 2.0
hf = max(ex1 - ex0, ey1 - ey0) / 2.0 * (1 + PAD)
views = [((cxa - hf, cxa + hf, cya - hf, cya + hf), 15, "분석 영역 전체"),
         ((cx0 - ZOOM, cx0 + ZOOM, cy0 - ZOOM, cy0 + ZOOM), 18, "관심 지역 주변 1.0 km")]
for ax, ((bx0, bx1, by0, by1), zm, ttl) in zip(axs, views):
    try:
        img, ext = cx.bounds2img(bx0, by0, bx1, by1, zoom=zm,
                                 source=cx.providers.Esri.WorldImagery, ll=False)
        ax.imshow(img, extent=ext, interpolation="bilinear")
    except Exception:
        pass
    ax.pcolormesh(X3, Y3, m_gate, cmap=cm_gate, alpha=.45, shading="auto", zorder=2)
    ax.pcolormesh(X3, Y3, m_dang, cmap=cm_dang, alpha=.45, shading="auto", zorder=3)
    ax.plot(bxx, bxy, color="#ffffff", lw=1.6, ls="--", zorder=4)
    ax.plot(px, py, color="#ffe000", lw=2.6, zorder=5,
            path_effects=[pe.Stroke(linewidth=4.4, foreground="#202020"), pe.Normal()])
    ax.set_xlim(bx0, bx1); ax.set_ylim(by0, by1)
    ax.set_box_aspect(1)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(ttl, fontsize=10.5)
    for sp in ax.spines.values():
        sp.set_color("#666")
axs[0].legend(handles=[Patch(fc="#FFBF00", alpha=.7, label="주의 구역 - 선별 기준 성립"),
                       Patch(fc="#e03030", alpha=.7, label="위험 구역 - 경보 조건 성립"),
                       Line2D([], [], color="#ffe000", lw=2.6, label="관심 지역"),
                       Line2D([], [], color="#ffffff", lw=1.6, ls="--", label="분석 영역 경계")],
              loc="lower left", fontsize=8.5, framealpha=.85)
fig.tight_layout(pad=0.6)
b = io.BytesIO()
fig.savefig(b, format="png", dpi=105, bbox_inches="tight", pad_inches=0.02)
plt.close(fig)
img64 = "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()

s = io.open(SRC, encoding="utf-8").read()
s = re.sub(r'data:image/png;base64,[A-Za-z0-9+/=]{500,}', lambda _: img64, s, count=1)
s = s.replace("· 붉은 영역 - <b>기준일 시점</b> 선별 기준이 성립하는 주의 구역",
              "· 주황 영역 - 기준일까지 <b>한 번이라도</b> 선별 기준이 성립한 <b>주의 구역</b><br>"
              "· 붉은 영역 - <b>기준일 시점</b> 경보 조건이 성립한 <b>위험 구역</b>")
def fmt_area(km2, n_cell):
    """0.01 km² 미만은 m² 로, 0 이면 '없음' 으로 적는다."""
    if n_cell == 0:
        return "없음"
    if km2 < 0.01:
        return "<b>%s m²</b>" % format(int(round(km2 * 1e6)), ",")
    return "<b>%.2f km²</b>" % km2


s = re.sub(r"· 주의 면적 <b>[\d.]+ km²</b> \(분석 영역의 [\d.]+%\)",
           "· 주의 면적 %s%s · 위험 면적 %s%s"
           % (fmt_area(area_ever, int(gate_ever.sum())),
              "" if not gate_ever.any() else " (분석 영역의 %.1f%%)" % (100 * gate_ever.mean()),
              fmt_area(area_d, int(dang_now.sum())),
              "" if not dang_now.any() else " (분석 영역의 %.1f%%)" % (100.0 * dang_now.sum() / NC)), s)
io.open(OUT, "w", encoding="utf-8").write(s)
print("→", OUT)
