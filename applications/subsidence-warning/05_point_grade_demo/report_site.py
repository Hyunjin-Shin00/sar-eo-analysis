# -*- coding: utf-8 -*-
"""지역(사상구) 기준 지반침하 보고서 + 공사장(50 m 폴리곤) 개별 판정.
usage: report_site.py --addr "부산광역시 사상구 새벽로 87" [--lat .. --lon ..]
                      [--name "○○ 신축공사"] [--side 50] [--out PATH]

무엇이 달라졌나 (report_tokgeon.py 대비)
  ① 판정 규칙을 **종전 최종**(index_leadtime.html 최종 확정본 탭의 '종전 최종' 절)으로 교체했다.
     1차 게이트(주의) · 2차 경보(위험) 모두 out/verify/last_section.json 원문을 쓴다.
     기존 스크립트가 쓰던 t2k_monotone 1단 위험규칙·gate_op 게이트는 계열이 달라 쓰지 않는다.
  ② 보고서 주체를 **지역(사상구)** 으로 두고, 공사장은 그 안의 개별 물건으로 덧붙인다.
  ③ 주소 기준 **한 변 50 m 정사각 폴리곤**을 만들어 shapefile 로 내보낸다.
  ④ 연도별 스냅샷을 만들지 않는다. **최종 관측일 기준 1건**만 낸다.

등급
  주의 = 주의 구역 선별 통과 (지표 백분위 결합 점수 ≥ 임계)
  위험 = 위험 경보 발령 (원값 AND 조건이 K 에폭 연속)
  임계가 다른 두 단계이므로 위험이면 주의는 이미 통과한 상태다.

판정 지점
  규칙이 '반경 400 m 버퍼 최댓값' 위에서 정의돼 있으므로 공사장 판정도 폴리곤 중심에서
  반경 400 m 를 본다. 폴리곤(50 m)은 관심 지역 표시·도면용이며 판정 단위가 아니다.

출력 rule_maps/reports/<이름>_지반침하보고서.html · 같은 이름 .json · site_shp/<이름>.shp
"""
import os as _os
_CR = _os.environ.get("CLAB_ROOT") or _os.path.abspath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "..", ".."))   # 전달본 상대경로

import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json, argparse, datetime, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CR + "/analysis/sinkhole")
import numpy as np
import sweep_config as C
import discrim_eval as E
import swept_loader as SL
import featx_cache as FX
import leadtime_overfit as LO
import leadtime_op as OP
import leadtime_last as LL

DAYS = 365.25
REGION = "Busan_Sasang_Hadan"
REGION_KR = "부산광역시 사상구 일원 (사상~하단)"
COH, TCOH, R, KSET = 0.3, 0.7, 400.0, "SBAS"
LATCH_D = 90.0      # 2차 발화 후 경보 유지 기간(일)
S = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(S, "rule_maps", "reports")
SHPDIR = os.path.join(S, "rule_maps", "site_shp")
LSEC = os.path.join(C.OUT_ROOT, "verify", "last_section.json")
os.makedirs(OUTDIR, exist_ok=True)
os.makedirs(SHPDIR, exist_ok=True)

FKR = {"cum1": "최근 1년 누적침하", "cum1a": "최근 1년 누적침하/지반등급",
       "cum2": "최근 2년 누적침하", "cum2a": "최근 2년 누적침하/지반등급",
       "cumF": "전체기간 누적침하", "cumFa": "전체기간 누적침하/지반등급",
       "vel": "침하속도", "vela": "침하속도/지반등급", "vtr": "최근구간 침하속도",
       "dv": "침하 가속(후반−전반 속도차)", "ivfrac": "역속도 가속점 비율",
       "ivimm": "역속도 임박도"}
SKR = {"_d1": "1스텝 변화량", "_d3": "3스텝 변화량", "_d6": "6스텝 변화량",
       "_z3": "3스텝 표준화점수", "_z6": "6스텝 표준화점수"}


def fkr(n):
    for s, k in SKR.items():
        if n.endswith(s):
            return "%s의 %s" % (FKR.get(n[:-len(s)], n[:-len(s)]), k)
    return FKR.get(n, n)


def y2d(y):
    yy = int(y)
    return (datetime.date(yy, 1, 1) + datetime.timedelta(days=round((y - yy) * DAYS))).isoformat()


def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def geocode_by_road(addr):
    """동일 도로명 사고 실측좌표로 건물번호 선형보간 → (lat, lon, 근거문)"""
    m = re.search(r"([가-힣]+로)\s*([0-9]+)", addr)
    if not m:
        return None
    road, num = m.group(1), int(m.group(2))
    acc = E.load_accidents_full()
    pts = []
    for _, a in acc[acc.addr.astype(str).str.contains(road, na=False)].iterrows():
        mm = re.search(road + r"\s*([0-9]+)", str(a.addr))
        if mm and np.isfinite(a.lat) and np.isfinite(a.lon):
            pts.append((int(mm.group(1)), float(a.lat), float(a.lon)))
    if len(pts) < 2:
        return None
    pts.sort()
    n = np.array([p[0] for p in pts], float)
    la = np.array([p[1] for p in pts], float)
    lo = np.array([p[2] for p in pts], float)
    same = (n % 2) == (num % 2)
    if same.sum() >= 2:
        n, la, lo = n[same], la[same], lo[same]
    lat = float(np.polyval(np.polyfit(n, la, 1), num))
    lon = float(np.polyval(np.polyfit(n, lo, 1), num))
    return lat, lon, ("%s 실측 좌표 %d개 지점(번지 %d~%d)의 선형보간 - "
                      "국토안전관리원 사고기록 좌표 기반. 운영 시 VWorld/Kakao 지오코딩으로 대체."
                      % (road, len(n), int(n.min()), int(n.max())))


def make_site_shp(lat, lon, side, name):
    """한 변 side m 정사각 폴리곤 → shapefile(EPSG:4326). 반환 (경로, 꼭짓점, 면적)"""
    import geopandas as gpd
    from shapely.geometry import Polygon
    xr, yr = SL.loaders._TR_M.transform([lon], [lat])   # 미터 투영
    h = side / 2.0
    xs = [xr[0] - h, xr[0] + h, xr[0] + h, xr[0] - h]
    ys = [yr[0] - h, yr[0] - h, yr[0] + h, yr[0] + h]
    inv = SL.loaders._TR_M     # 정투영 객체 - 역변환은 pyproj Transformer 로 새로 만든다
    from pyproj import Transformer
    back = Transformer.from_crs(inv.target_crs, 4326, always_xy=True)
    lons, lats = back.transform(xs, ys)
    poly = Polygon(list(zip(lons, lats)))
    g = gpd.GeoDataFrame({"name": [name], "side_m": [side], "area_m2": [side * side],
                          "lat": [lat], "lon": [lon], "region": [REGION]},
                         geometry=[poly], crs="EPSG:4326")
    p = os.path.join(SHPDIR, "%s.shp" % name)
    g.to_file(p, encoding="utf-8")
    return p, [(round(a, 6), round(b, 6)) for a, b in zip(lons, lats)], side * side


_GATE = {}


def gate_setup():
    """탐지에 쓴 1차 게이트를 그대로 재현한다.

    leadtime_last.py 는 저장된 th(0.955, 반올림값)를 쓰지 않고 **그 자리에서 Youden 으로 재적합**한다
    (사상 재적합 0.95491 → 사고 14/14 통과 · 저장값이면 13/14 로 한 건이 어긋난다).
    방향 뒤집기(flips)도 prep_pct 가 단일지표 AUC<0.5 기준으로 정하므로 그대로 가져온다.
    """
    if _GATE:
        return _GATE
    g = json.load(open(LSEC))["regions"][REGION]["gate_rule"]
    A_, B_ = OP.get_series(REGION, "t2k")
    Ap, Bp, flips = OP.prep_pct(A_, B_)
    fsi = [LO.FEATS.index(f) for f in g["features"]]

    def _sc(m):
        sub = m[:, fsi]
        with np.errstate(all="ignore"):
            return OP.COMB[g["comb"]](sub, axis=1) if len(fsi) > 1 else sub[:, 0]
    pa = np.array([OP.persist_max(_sc(m), g["K"]) for m in Ap], float)
    pb = np.array([OP.persist_max(_sc(m), g["K"]) for m in Bp], float)
    th1 = float(OP.youden_op(pa, pb)[0])
    srt = [np.sort(np.concatenate([b[1][f][np.isfinite(b[1][f])] for b in B_]))
           for f in range(len(LO.FEATS))]
    _GATE.update(rule=g, th=th1, flips=flips, srt=srt, fsi=fsi,
                 n_acc_pass=int((pa >= th1).sum()), n_acc=len(pa),
                 n_bg_pass=int((pb >= th1).sum()), n_bg=len(pb))
    return _GATE


def region_block():
    """지역 기준 - 종전 최종 규칙 원문과 그 지역 검증 성적."""
    L = json.load(open(LSEC))["regions"][REGION]
    g, b = L["gate_rule"], L["by_floor"]["80"]
    lds = [x["lead_d"] for x in b["leads"] if x.get("lead_d") is not None]
    n = g["n"]
    n1 = int(round(g["det%"] / 100.0 * n))
    return dict(kr=L["kr"], full=L["full"], gate=g, s2=b,
                n_acc=n, n_gate=n1, n_alarm=len(lds),
                det=100.0 * len(lds) / n,
                med=float(np.median(lds)) if lds else None,
                mn=float(min(lds)) if lds else None,
                mx=float(max(lds)) if lds else None,
                le90=sum(1 for x in lds if x <= 90))


def zone_map(A, shp, side, asof=None):
    """주의 구역 선별 통과 영역 + 공사장 폴리곤을 위성영상 위에 그린다 → base64 PNG.

    주의 구역 선별은 최종 관측일의 두 지표(최근 1년 침하량·가속)만 있으면 재현된다.
    시계열 전체를 돌릴 필요가 없어, 전 관측점의 단일 시점 값을 한 번에 구한 뒤
    격자마다 반경 400 m 최댓값을 취해 백분위·결합·임계 비교를 그대로 적용한다.
    """
    import io as _io, base64
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    import contextily as cx
    from pyproj import Transformer
    import indicators as ind
    from scipy.spatial import cKDTree

    for _c in ("Noto Sans CJK JP", "Noto Sans CJK KR", "NanumGothic"):
        if _c in {f.name for f in fm.fontManager.ttflist}:
            plt.rcParams["font.family"] = _c
            break
    plt.rcParams["axes.unicode_minus"] = False

    e, kinds = FX.build_entry(REGION, COH, TCOH, KSET)
    sb = e["kinds"]["SBAS"]
    yrs, disp = sb["years"], sb["disp"]
    if asof is not None:                                   # 기준일 이후 관측은 일절 쓰지 않는다
        m_ = yrs <= asof + 1e-9
        yrs, disp = yrs[m_], disp[:, m_]
    T_END = float(yrs[-1])
    GT = gate_setup()
    g, TH1 = GT["rule"], GT["th"]
    srt = {f: GT["srt"][LO.FEATS.index(f)] for f in g["features"]}

    S_, N_, W_, Eb = e["box"]
    TRm = SL.loaders._TR_M
    xs_, ys_ = TRm.transform([W_, Eb], [S_, N_])
    step = 50.0
    gx = np.arange(xs_[0], xs_[1] + step, step)
    gy = np.arange(ys_[0], ys_[1] + step, step)
    GX, GY = np.meshgrid(gx, gy)
    tree = cKDTree(np.c_[sb["x"], sb["y"]])
    nb = tree.query_ball_point(np.c_[GX.ravel(), GY.ravel()], R)
    # 이웃 목록을 평탄화해 두면 에폭마다 reduceat 한 번으로 버퍼 최댓값을 얻는다
    cnt = np.array([len(i) for i in nb])
    flat = np.concatenate([np.asarray(i, int) for i in nb if len(i)]) if cnt.any() else np.array([], int)
    off = np.r_[0, np.cumsum(cnt[cnt > 0])[:-1]]
    has = cnt > 0

    def bufmax(v):
        o = np.full(len(nb), np.nan)
        if len(flat):
            o[has] = np.maximum.reduceat(np.nan_to_num(v[flat], nan=-1e18), off)
        return np.where(o <= -1e17, np.nan, o)

    def pctile(f, v):
        sf = srt[f]
        o = np.full(v.shape, np.nan)
        fin = np.isfinite(v)
        o[fin] = (np.searchsorted(sf, v[fin], "left")
                  + np.searchsorted(sf, v[fin], "right")) / (2 * len(sf))
        return 1.0 - o if GT["flips"][LO.FEATS.index(f)] else o

    # 지도는 **기준일 시점** 성립 구역이다. 누적(한 번이라도 통과)으로 그리면 8년치가 쌓여
    # 날짜를 바꿔도 그림이 거의 같아진다. 대신 공사장이 구역 밖이어도 과거 진입 이력이
    # 있으면 감시 대상으로 남는다는 점을 보고서 본문에 함께 적는다.
    tj = float(yrs[-1])
    VAL = {"cum1": E.cum_window(disp, yrs, tj, 1.0)}
    if "dv" in g["features"]:
        tg = ind.trend_grade(disp, yrs, tj)
        VAL["dv"] = tg["v_late"] - tg["v_early"]
    for f in g["features"]:
        VAL.setdefault(f, np.full(disp.shape[0], np.nan))
    P = np.column_stack([pctile(f, bufmax(np.asarray(VAL[f], float))) for f in g["features"]])
    with np.errstate(all="ignore"):
        sc = OP.COMB[g["comb"]](P, axis=1) if P.shape[1] > 1 else P[:, 0]
    ok = (np.nan_to_num(sc, nan=-1e18) >= TH1).reshape(GX.shape)
    n_ok = int(ok.sum())

    to3857 = Transformer.from_crs(TRm.target_crs, 3857, always_xy=True)
    X3, Y3 = to3857.transform(GX, GY)
    # vtx 는 (경도, 위도) 순이다 - 뒤집어 쓰면 웹메르카토르 변환이 무한대를 낸다
    lons = [v[0] for v in shp["vtx"]] + [shp["vtx"][0][0]]
    lats = [v[1] for v in shp["vtx"]] + [shp["vtx"][0][1]]
    px, py = Transformer.from_crs(4326, 3857, always_xy=True).transform(lons, lats)
    cx0, cy0 = float(np.mean(px[:-1])), float(np.mean(py[:-1]))
    m = np.ma.masked_where(~ok, ok.astype(float))
    cmap = matplotlib.colors.ListedColormap(["#e03030"])
    # 흰 점선은 **실제로 계산한 격자**의 바깥 테두리다. 격자는 상자 남서 모서리에서
    # 50 m 간격으로 놓여 마지막 한 칸이 상자 밖으로 나간다 - 경위도 상자를 그대로 그리면
    # 칠한 구역이 선 밖으로 한 칸 삐져나와 보인다.
    hs = step / 2.0
    ex_, ey_ = np.r_[gx - hs, gx[-1] + hs], np.r_[gy - hs, gy[-1] + hs]
    bx_m = np.r_[ex_, np.full(len(ey_), ex_[-1]), ex_[::-1], np.full(len(ey_), ex_[0])]
    by_m = np.r_[np.full(len(ex_), ey_[0]), ey_, np.full(len(ex_), ey_[-1]), ey_[::-1]]
    bxx, bxy = to3857.transform(bx_m, by_m)                                  # 분석 영역 경계

    # 좌: 분석 범위 전체 · 우: 공사장 중심 확대 - 50 m 폴리곤은 전체 축척에서 보이지 않는다
    fig, axs = plt.subplots(1, 2, figsize=(11.4, 6.2))
    ZOOM = 500.0                       # 확대 패널 반폭(m) - 좌우 1 km
    PAD = 0.12
    ex0, ex1, ey0, ey1 = X3.min(), X3.max(), Y3.min(), Y3.max()
    # 두 패널을 같은 크기로 맞춘다 - 시야를 정사각으로 잡고 축 상자 비율도 1:1 로 고정한다
    cxa, cya = (ex0 + ex1) / 2.0, (ey0 + ey1) / 2.0
    hf = max(ex1 - ex0, ey1 - ey0) / 2.0 * (1 + PAD)
    views = [((cxa - hf, cxa + hf, cya - hf, cya + hf), 15, "분석 영역 전체"),
             ((cx0 - ZOOM, cx0 + ZOOM, cy0 - ZOOM, cy0 + ZOOM), 18,
              "관심 지역 주변 %.1f km" % (ZOOM * 2 / 1000.0))]
    for ax, ((bx0, bx1, by0, by1), zm, ttl) in zip(axs, views):
        try:
            img, ext = cx.bounds2img(bx0, by0, bx1, by1, zoom=zm,
                                     source=cx.providers.Esri.WorldImagery, ll=False)
            ax.imshow(img, extent=ext, interpolation="bilinear")
        except Exception:
            pass
        ax.pcolormesh(X3, Y3, m, cmap=cmap, alpha=.40, shading="auto", zorder=2)
        ax.plot(bxx, bxy, color="#ffffff", lw=1.6, ls="--", zorder=3)
        ax.plot(px, py, color="#ffe000", lw=2.6, zorder=4)
        ax.set_xlim(bx0, bx1); ax.set_ylim(by0, by1)
        ax.set_box_aspect(1)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(ttl, fontsize=10.5)
        for sp in ax.spines.values():
            sp.set_color("#666")
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    axs[0].legend(handles=[Patch(fc="#e03030", alpha=.5, label="주의 구역 (선별 기준 성립)"),
                           Line2D([], [], color="#ffe000", lw=2.6, label="관심 지역"),
                           Line2D([], [], color="#ffffff", lw=1.6, ls="--", label="분석 영역 경계")],
                  loc="lower left", fontsize=8.5, framealpha=.85)
    fig.tight_layout(pad=0.6)
    b = _io.BytesIO()
    fig.savefig(b, format="png", dpi=105, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    area = n_ok * step * step / 1e6
    return ("data:image/png;base64," + base64.b64encode(b.getvalue()).decode(),
            dict(n_cell=n_ok, area_km2=round(area, 2),
                 pct=round(100.0 * n_ok / ok.size, 1)))


def plain(feat, revisit):
    """지표 코드를 일반 독자용 문장으로. 스텝 수는 재방문 주기를 곱해 '며칠'로 바꾼다."""
    base, suf = feat, ""
    for k in ("_d1", "_d3", "_d6", "_z3", "_z6"):
        if feat.endswith(k):
            base, suf = feat[:-len(k)], k
            break
    B = {"cum1": "최근 1년 침하량", "cum2": "최근 2년 침하량", "cumF": "관측 시작 이후 총 침하량",
         "cum1a": "최근 1년 침하량(연약지반 보정)", "cum2a": "최근 2년 침하량(연약지반 보정)",
         "cumFa": "총 침하량(연약지반 보정)", "vel": "침하 속도", "vela": "침하 속도(연약지반 보정)",
         "vtr": "최근 구간 침하 속도", "dv": "침하 가속",
         "ivfrac": "붕괴 조짐이 보이는 지점의 비율", "ivimm": "붕괴 예상 시점의 임박도"}
    nb = B.get(base, base)
    n = {"_d1": 1, "_d3": 3, "_d6": 6, "_z3": 3, "_z6": 6}.get(suf, 0)
    days = int(round(n * revisit))
    if suf in ("_d1", "_d3", "_d6"):
        return "최근 약 %d일 사이에 늘어난 %s" % (days, nb)
    if suf in ("_z3", "_z6"):
        return "최근 약 %d일 사이의 %s 변화폭 (평소 변동폭의 몇 배인지)" % (days, nb)
    return nb


def lead_stats():
    """이 지역에서 위험 경보 발령 후 실제 사고까지 걸린 기간(과거 사례)."""
    b = json.load(open(LSEC))["regions"][REGION]["by_floor"]["80"]
    v = sorted(x["lead_d"] for x in b["leads"] if x.get("lead_d") is not None)
    if not v:
        return None
    return dict(n=len(v), mn=v[0], med=float(np.median(v)), mx=v[-1],
                le30=sum(1 for x in v if x <= 30), le90=sum(1 for x in v if x <= 90))


def analyze(lat, lon, side=50.0, asof=None):
    """최종 관측일 기준 1건 판정 - 주의 구역 선별·위험 경보 발령."""
    out = {"lat": lat, "lon": lon}
    RB = region_block()
    out["region"] = RB
    e, kinds = FX.build_entry(REGION, COH, TCOH, KSET)
    sb = e["kinds"]["SBAS"]
    yrs_all, tree = sb["years"], sb["tree"]
    yrs = yrs_all if asof is None else yrs_all[yrs_all <= asof + 1e-9]
    if len(yrs) < C.PRE_MIN_EPOCHS:
        out["insufficient"] = "기준일까지 관측 %d회로 판정 불가" % len(yrs)
        return out
    T_END = float(yrs[-1])
    ref = float(asof) if asof is not None else T_END
    out["asof"] = y2d(ref)
    out["obs"] = {"start": y2d(float(yrs[0])), "end": y2d(T_END), "n_epoch": int(len(yrs)),
                  "revisit_d": round(float(np.median(np.diff(yrs)) * DAYS), 1),
                  "n_point": int(len(sb["lon"])),
                  "lag_d": int(round((ref - T_END) * DAYS))}
    out["box"] = [round(float(v), 5) for v in e["box"]]

    ax, ay = SL.loaders._TR_M.transform([lon], [lat])
    idx = np.array(tree.query_ball_point([ax[0], ay[0]], R), int)
    out["n_buf"] = int(len(idx))
    if not len(idx):
        out["insufficient"] = "반경 %dm 내 관측점 없음" % int(R)
        return out
    out["alpha_min"] = round(float(np.nanmin(sb["alpha"][idx])), 2)
    DSP = sb["disp"][:, :len(yrs)]                 # 기준일까지로 자른 변위

    # ── 관심 지역 주변의 실제 변위 시계열
    # 관심 지역 중심 반경 50 m 로 고정한다.
    # 그 반경에 점이 하나도 없을 때만 넓히고, 실제로 쓴 범위와 점 개수를 그대로 적는다.
    cx, cy = float(ax[0]), float(ay[0])
    used, how = np.array([], int), ""
    for rr in (50.0, 100.0, 200.0, 400.0):
        used = np.array(tree.query_ball_point([cx, cy], rr), int)
        how = "관심 지역 중심 반경 %dm" % int(rr)
        if len(used):
            break
    inside = (np.abs(sb["x"] - cx) <= side / 2) & (np.abs(sb["y"] - cy) <= side / 2)
    if len(used):
        d = np.asarray(DSP[used], float)               # 통상 표기: 침하 = 음(−)
        d = d - d[:, [0]]                              # 관측 시작일 기준 0
        med = np.nanmedian(d, axis=0)
        out["site_series"] = {"t": [round(float(x), 4) for x in yrs],
                              "d": [None if not np.isfinite(v) else round(float(v), 2) for v in med],
                              "n_pt": int(len(used)), "how": how,
                              "n_inside": int(inside.sum()),
                              "total": None if not np.isfinite(med[-1]) else round(float(med[-1]), 1)}

    # 12지표 워크포워드 (확정 계열과 동일 코드)
    t, Fm = LO.ff_series(DSP[idx], yrs, sb["alpha"][idx], T_END)
    if not len(t):
        out["insufficient"] = "지표 산출 구간 부족"
        return out
    out["series"] = {"t": [round(float(x), 4) for x in t],
                     "cum1": [None if not np.isfinite(x) else round(float(x), 2)
                              for x in Fm[LO.FEATS.index("cum1")]],
                     "vel": [None if not np.isfinite(x) else round(float(x), 2)
                             for x in Fm[LO.FEATS.index("vel")]]}

    # ── 1차 게이트(주의) - 배경 풀 백분위 결합
    GT = gate_setup()
    srt = GT["srt"]

    def pct(f, v):
        s = srt[f]
        o = np.full(len(v), np.nan)
        fin = np.isfinite(v)
        if len(s):
            o[fin] = (np.searchsorted(s, v[fin], "left") + np.searchsorted(s, v[fin], "right")) / (2 * len(s))
        return o
    g = RB["gate"]
    gf = GT["fsi"]
    P = np.column_stack([pct(f, Fm[f]) for f in gf])
    for i, f in enumerate(gf):                      # 방향 뒤집기는 prep_pct 판정을 그대로 따른다
        if GT["flips"][f]:
            P[:, i] = 1.0 - P[:, i]
    with np.errstate(all="ignore"):
        gs = OP.COMB[g["comb"]](P, axis=1) if len(gf) > 1 else P[:, 0]
    TH1 = GT["th"]
    gok = np.nan_to_num(gs, nan=-1e18) >= TH1
    gj = int(np.argmax(gok)) if gok.any() else -1
    out["gate"] = {"pass": gj >= 0, "first": None if gj < 0 else y2d(float(t[gj])),
                   "score_now": None if not np.isfinite(gs[-1]) else round(float(gs[-1]), 3),
                   "score_max": None if not np.isfinite(np.nanmax(gs)) else round(float(np.nanmax(gs)), 3),
                   "th": round(TH1, 5), "K": int(g["K"]),
                   "gate_acc": "%d/%d" % (GT["n_acc_pass"], GT["n_acc"]),
                   "pass_now": bool(len(gs) and np.isfinite(gs[-1]) and gs[-1] >= TH1),
                   "n_pass_epoch": int(gok.sum()), "n_epoch": int(len(t)),
                   "features": g["features"], "comb": g["comb"],
                   "pct_now": [None if not np.isfinite(P[-1, i]) else round(float(P[-1, i]), 3)
                               for i in range(P.shape[1])]}

    # ── 2차 경보(위험) - 게이트 진입 이후 구간에 원값 AND · K 연속
    s2 = RB["s2"]
    gcol = max(0, gj) if gj >= 0 else 0
    X = LL.derive(Fm[:, gcol:])
    tX = t[gcol:]
    ok = np.ones(X.shape[1], bool)
    for f, th in s2["rule"]:
        ok &= (X[LL.NAMES.index(f)] >= float(th))
    K = int(s2["K"])
    fires, run, first = [], 0, -1
    for i, h in enumerate(ok):
        run = run + 1 if h else 0
        if run >= K:
            fires.append(float(tX[i]))
            if first < 0:
                first = i
    inst = bool(len(ok) >= K and ok[-K:].all())          # 기준일에 K연속 성립
    since = None if not fires else round(float((T_END - fires[-1]) * DAYS), 1)
    # 발화 후 LATCH_D 일간은 경보를 유지한다(지역 검증 리드 ≤90일 구간 근거).
    # 그 이상 지난 과거 이력만으로 '위험'을 유지하면 상태가 아니라 이력을 보고하는 셈이 된다.
    now = bool(inst or (since is not None and since <= LATCH_D))
    out["alarm"] = {"fired": first >= 0, "first": None if first < 0 else y2d(float(tX[first])),
                    "K": K, "n_fire_epoch": len(fires), "n_epoch_watch": int(len(tX)),
                    "last_fire": y2d(fires[-1]) if fires else None,
                    "days_since_fire": since, "latch_d": LATCH_D,
                    "instant": inst, "now": now}
    out["alarm_conds"] = [{"feature": f, "th": float(th),
                           "val": None if X[LL.NAMES.index(f)][-1] <= -1e17
                           else round(float(X[LL.NAMES.index(f)][-1]), 3),
                           "ok": bool(X[LL.NAMES.index(f)][-1] >= float(th))}
                          for f, th in s2["rule"]]
    # 조건이 지금 충족되지 않는데 '위험'으로 표시되면 표와 등급이 어긋나 보인다.
    # 등급은 기준일 시점의 조건 성립 여부만으로 정한다(과거 발령은 이력으로만 적는다).
    out["grade"] = "위험" if out["alarm"]["instant"] else ("주의" if out["gate"]["pass"] else "정상")

    for k in ("vel", "dv", "cum1"):
        col = Fm[LO.FEATS.index(k)]
        fin = col[np.isfinite(col)]
        out[k + "_now"] = None if not len(fin) else round(float(fin[-1]), 1)

    # 인근 사고
    acc = E.load_accidents_full()
    box = acc[acc.lat.notna() & acc.lon.notna()].copy()
    box["d_m"] = hav(lat, lon, box.lat.values, box.lon.values)
    fut = box[box.year.notna() & (box.year > ref) & (box.d_m <= 1000)].sort_values("year")
    out["after"] = [{"date": E._fmt(a.sagoDate), "cause": a.cause, "addr": str(a.addr)[:40],
                     "d_m": int(round(a.d_m)),
                     "days": int(round((float(a.year) - ref) * DAYS)),
                     "vol": None if not np.isfinite(a.vol) else round(float(a.vol), 1)}
                    for _, a in fut.iterrows()]
    box = box[box.year.notna() & (box.year <= ref)]
    near = box[box.d_m <= 1000].sort_values("d_m")
    out["near"] = [{"date": E._fmt(a.sagoDate), "cause": a.cause, "addr": str(a.addr)[:40],
                    "d_m": int(round(a.d_m))} for _, a in near.head(12).iterrows()]
    out["near_cnt"] = {"400m": int((box.d_m <= 400).sum()), "1km": int(len(near))}
    S_, N_, W_, Eb = e["box"]
    inbox = box[box.lat.between(S_, N_) & box.lon.between(W_, Eb)].copy()
    inbox["yr"] = [str(E._fmt(d))[:4] for d in inbox.sagoDate]
    by_year = []
    for y in sorted(inbox.yr.unique()):
        sub = inbox[inbox.yr == y]
        cz = " · ".join("%s %d" % (k, v) for k, v in sub.cause.value_counts().items())
        by_year.append((y, int(len(sub)), cz))
    yy = [y for y, _, _ in by_year]
    def _n(v, f="%.1f"):
        return None if v is None or not np.isfinite(v) else float(f % v)
    lst = []
    for _, a in inbox.sort_values("sagoDate").iterrows():
        lst.append({"date": E._fmt(a.sagoDate), "cause": a.cause, "addr": str(a.addr)[:40],
                    "w": _n(a.sinkWidth), "l": _n(a.sinkExtend), "d": _n(a.sinkDepth),
                    "vol": _n(a.vol, "%.2f"),
                    "d_m": int(round(hav(lat, lon, float(a.lat), float(a.lon))))})
    out["region_hist"] = {"n": int(len(inbox)), "by_year": by_year, "list": lst,
                          "by_cause": [(str(k), int(v)) for k, v in inbox.cause.value_counts().items()],
                          "span": ("%s~%s년 기록" % (yy[0], yy[-1])) if yy else "기록 없음"}
    return out


def svg_series(t, y, ylab, color="#c0392b", w=690, h=200):
    """관측값은 회색 점, 추세는 이동평균 실선."""
    P = [(a, b) for a, b in zip(t, y) if b is not None]
    if len(P) < 2:
        return "<div class=note>표시할 시계열이 없다.</div>"
    tx = np.array([p[0] for p in P], float)
    vy = np.array([p[1] for p in P], float)
    k = max(3, (len(vy) // 22) * 2 + 1)                 # 관측 수에 맞춘 홀수 창
    pad = np.r_[np.full(k // 2, vy[0]), vy, np.full(k // 2, vy[-1])]
    sm = np.convolve(pad, np.ones(k) / k, mode="valid")
    x0, x1 = tx.min(), tx.max()
    y0, y1 = min(vy.min(), sm.min()), max(vy.max(), sm.max())
    if y1 - y0 < 1e-9:
        y1 = y0 + 1
    pd_ = (y1 - y0) * 0.08
    y0, y1 = y0 - pd_, y1 + pd_
    L, Rm, Tp, Bt = 56, 20, 14, 28      # 양끝 눈금 글씨가 잘리지 않도록 여백 확보
    sx = lambda v: L + (v - x0) / (x1 - x0) * (w - L - Rm)
    sy = lambda v: Tp + (y1 - v) / (y1 - y0) * (h - Tp - Bt)
    gy = ""
    for i in range(5):
        v = y0 + (y1 - y0) * i / 4
        gy += ("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#e5e5e5'/>"
               "<text x='%d' y='%.1f' font-size='8.5' fill='#666' text-anchor='end'>%.0f</text>"
               % (L, sy(v), w - Rm, sy(v), L - 4, sy(v) + 3, v))
    if y0 < 0 < y1:
        gy += "<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#999' stroke-dasharray='3 3'/>" % (
            L, sy(0), w - Rm, sy(0))
    gx = ""
    for i in range(5):
        v = x0 + (x1 - x0) * i / 4
        # 첫·끝 눈금은 가운데 정렬하면 그림 밖으로 넘친다 → 안쪽으로 붙인다
        anc = "start" if i == 0 else ("end" if i == 4 else "middle")
        gx += ("<text x='%.1f' y='%d' font-size='8.5' fill='#666' text-anchor='%s'>%s</text>"
               % (sx(v), h - 8, anc, y2d(v)[:7]))
    dots = "".join("<circle cx='%.1f' cy='%.1f' r='1.7' fill='#9a9a9a' fill-opacity='.75'/>"
                   % (sx(a), sy(b)) for a, b in zip(tx, vy))
    pl = " ".join("%.1f,%.1f" % (sx(a), sy(b)) for a, b in zip(tx, sm))
    return ("<svg viewBox='0 0 %d %d' style='width:100%%;height:auto;border:1px solid #ccc;"
            "background:#fff'>%s%s%s<polyline points='%s' fill='none' stroke='%s' "
            "stroke-width='2.1' stroke-linejoin='round'/>"
            "<text x='4' y='10' font-size='8.5' fill='#333'>%s</text></svg>"
            % (w, h, gy, gx, dots, pl, color, ylab))


def pct_band(v):
    """백분위 → 지역 내 순위 문장. 값 구간만 적고 평가어는 붙이지 않는다."""
    if v is None:
        return "-"
    p = (1.0 - v) * 100
    if p < 1:
        return "이 지역 상위 1% 이내"
    return "이 지역 상위 %.0f%%" % max(1, round(p))


def build(A, args, shp, asof=None):
    zone_img_src, zi = zone_map(A, shp, args.side, asof)
    zone_img = ("<img src='%s' style='width:100%%;border:1px solid #999'/>" % zone_img_src)
    RB = A["region"]; ob = A["obs"]; g = A["gate"]; al = A["alarm"]
    grade = A["grade"]
    GC = {"위험": "#c0392b", "주의": "#c98500", "정상": "#1a9850"}[grade]
    s2 = RB["s2"]
    rv = ob["revisit_d"]
    combkr = {"mean": "평균", "min": "가장 낮은 값", "max": "가장 높은 값"}[RB["gate"]["comb"]]
    gate_txt = ("- 성립" if g["pass_now"] else
                "- 미성립이나 %s 진입 이력이 있어 감시 대상이다" % (g["first"] or "-") if g["pass"] else
                "- 미성립이며 진입 이력도 없다")
    alarm_txt = ("" if not al["last_fire"] else
                 ", 최근 <b>%s</b>%s" % (al["last_fire"],
                 "" if al["days_since_fire"] is None else
                 " (기준일까지 %.0f일 경과)" % al["days_since_fire"]))
    watch_txt = ("주의 구역 선별에 이미 진입한 지점이므로 지속 감시가 필요하다" if g["pass"] else
                 "주의 구역 선별에 진입한 이력이 없어 정기 관측만 유지하면 된다")
    # 세 조건이 순간적으로 모두 충족돼도 K회 연속이라야 발령이다 - 표와 등급이 어긋나 보이지 않게 적는다
    conds = A.get("alarm_conds") or []
    consec_note = ("" if not conds or not all(c["ok"] for c in conds) or al["instant"] else
                   "<div class=note>· 세 항목이 모두 충족이나 <b>%d회 관측 연속</b> 조건을 채우지 못해 "
                   "발령하지 않는다 - 일시적인 값 튐을 걸러내기 위한 장치다</div>" % al["K"])
    alp = A.get("alpha_min")
    AGR = {0.6: "연약", 0.8: "주의", 1.0: "양호"}          # config.grade_alpha 와 같은 체계
    alpkr = "-" if alp is None else min(AGR.items(), key=lambda kv: abs(kv[0] - alp))[1]
    vlon = [v[0] for v in shp["vtx"]]                  # vtx 는 (경도, 위도) 순이다
    vlat = [v[1] for v in shp["vtx"]]
    gate_feat = "".join("<li>%s</li>" % plain(f, rv) for f in RB["gate"]["features"])
    s2_feat = "".join("<li>%s</li>" % plain(f, rv) for f, _ in s2["rule"])
    cond_rows = "".join(
        "<tr><td class=l>%s</td><td>%s 이상</td><td><b>%s</b></td><td>%s</td></tr>"
        % (plain(c["feature"], rv), ("%.1f mm" % c["th"]) if not c["feature"].endswith(("_z3", "_z6"))
           else ("평소의 %.1f배" % c["th"]),
           "-" if c["val"] is None else (("%.1f mm" % c["val"])
                                         if not c["feature"].endswith(("_z3", "_z6"))
                                         else "평소의 %.1f배" % c["val"]),
           "<b style='color:#c0392b'>충족</b>" if c["ok"] else "<span style='color:#777'>미충족</span>")
        for c in A["alarm_conds"])
    pct_rows = "".join(
        "<tr><td class=l>%s</td><td><b>%s</b></td><td class=l>%s</td></tr>"
        % (plain(f, rv), "-" if v is None else "%.3f" % v, pct_band(v))
        for f, v in zip(g["features"], g["pct_now"]))
    def _sz(a):
        if a["w"] is None or a["l"] is None or a["d"] is None:
            return "-"
        return "%.1f × %.1f × %.1f" % (a["w"], a["l"], a["d"])
    acc_rows = "".join(
        "<tr><td>%s</td><td class=l>%s</td><td class=l>%s</td><td>%s</td><td>%s</td></tr>"
        % (a["date"], a["cause"], a["addr"], _sz(a),
           "-" if a["vol"] is None else "%.1f" % a["vol"])
        for a in A["region_hist"]["list"]) or "<tr><td colspan=5>기록 없음</td></tr>"
    hist = A["region_hist"]
    # 작성일과 판정 기준일이 같으면 한 줄로 합친다
    date_lab = ("작성일" if A["asof"] == datetime.date.today().isoformat()
                else "판정 기준일 (작성 %s)" % datetime.date.today().isoformat())
    ss = A.get("site_series")
    if ss:
        site_chart = (svg_series(ss["t"], ss["d"],
                                 "변위 (mm) · 음(−)이 침하", "#c0392b")
                      + "<div class=note>· %s 관측점 %d곳의 중앙값이다<br>"
                        "· 관측 시작일을 0 으로 둔 상대 변위이며, 음(−)이 침하다<br>"
                        "· 기준일 시점 누적 변위 <b>%s mm</b></div>"
                      % (ss["how"], ss["n_pt"],
                         "-" if ss["total"] is None else "%.1f" % ss["total"]))
    else:
        site_chart = "<div class=note>· 관심 지역 주변 관측점이 없어 시계열을 산출할 수 없다</div>"

    return f"""<!DOCTYPE html><html lang=ko><head><meta charset="utf-8"/>
<title>지반침하 위험 보고서 - {args.name}</title><style>
@page {{ size: A4; margin: 14mm 12mm; }}
body {{ font-family:'Malgun Gothic','맑은 고딕',AppleGothic,sans-serif; font-size:9.8px;
       color:#111; margin:0 auto; max-width:800px; padding:10px; line-height:1.55 }}
h1 {{ font-size:16px; text-align:center; background:#efefef; border:1px solid #bbb;
     padding:10px; margin:6px 0 14px; letter-spacing:.5px }}
h2 {{ font-size:13.5px; font-weight:800; margin:16px 0 6px; padding:4px 0 3px;
     border-bottom:2px solid #333 }}
h3 {{ font-size:11.5px; font-weight:700; margin:12px 0 5px }}
table {{ width:100%; border-collapse:collapse; margin-bottom:7px; font-size:9.4px }}
th,td {{ border:1px solid #999; padding:4px 6px; text-align:center; vertical-align:middle }}
th {{ background:#f2f2f2; font-weight:700 }}
td.k {{ background:#f2f2f2; font-weight:700; width:112px; text-align:center }}
td.l {{ text-align:left }}
.note {{ font-size:8.8px; color:#555; line-height:1.55; margin:3px 0 9px }}
.box {{ border:2px solid {GC}; padding:9px 11px; margin:8px 0 12px; background:#fcfcfc }}
.big {{ font-size:22px; font-weight:800; letter-spacing:2px; color:{GC} }}
.pb {{ page-break-before:always }}
ul {{ margin:4px 0 4px 16px; padding:0 }}
</style></head><body>

<h1>지반침하 위험 보고서 - {REGION_KR}</h1>
<table>
<tr><td class=k>보고서 대상</td><td class=l>{REGION_KR}</td>
    <td class=k>{date_lab}</td><td class=l><b>{A['asof']}</b></td></tr>
</table>
<div class=note>· 인공위성 레이더로 약 {rv:.0f}일 주기 반복 관측해 지표 변위를 mm 단위로 계측한다<br>
· 지역 전반의 침하 현황과 해당 관심 지역의 개별 판정을 함께 수록한다</div>

<h2>1. 지역 현황 - {RB['full']}</h2>
<table>
<tr><td class=k>관측 기간</td><td class=l>{ob['start']} ~ {ob['end']}</td>
    <td class=k>촬영 횟수</td><td class=l>{ob['n_epoch']}회</td></tr>
<tr><td class=k>촬영 주기</td><td class=l>약 {rv:.0f}일</td>
    <td class=k>분석 영역 범위</td><td class=l colspan=1>
    위도 {A['box'][0]}~{A['box'][1]}<br>경도 {A['box'][2]}~{A['box'][3]}</td></tr>
</table>

<h3>1-1. 이 지역의 지반침하 사고 이력</h3>
<table>
<tr><th style="width:76px">발생일</th><th style="width:70px">원인</th><th>주소</th>
    <th style="width:118px">규모<br>폭 × 연장 × 깊이 (m)</th><th style="width:66px">체적<br>(m³)</th></tr>
{acc_rows}
</table>
<div class=note>· 출처 - 국토안전관리원 지하안전정보시스템 지반침하 사고 신고자료<br>
· 원인·규모는 신고서 기재값을 그대로 명시한다<br>
· 분석 영역 내에서 좌표가 확인된 사고만 집계한다</div>

<h3>1-2. 위험구역 현황</h3>
{zone_img}
<div class=note>· 붉은 영역 - <b>기준일 시점</b> 선별 기준이 성립하는 주의 구역<br>
· 노란 사각형 - 본 관심 지역 · 흰 점선 - 분석 영역 경계<br>
· 주의 면적 <b>{zi['area_km2']:.2f} km²</b> (분석 영역의 {zi['pct']:.1f}%)<br>
· 위성이 보는 것은 지표 변위이며, 지하 공동의 유무를 직접 확인한 것은 아니다</div>

<h3>1-3. 위험 판정 규칙</h3>
<div class=note>· 지역 내 과거 사고 지점과 비사고 지점을 대조해 도출한 2단계 규칙이다<br>
· 선별 기준 통과 시 <b>주의</b>, 경보 조건까지 성립 시 <b>위험</b>으로 분류한다</div>
<table>
<tr><th style="width:56px">단계</th><th style="width:52px">등급</th><th>내용</th></tr>
<tr><td>주의 구역<br>선별</td><td><b style="color:#c98500">주의</b></td><td class=l>
아래 두 가지를 이 지역 다른 지점들과 비교해서 <b>상위 몇 %인지</b>로 바꾼 뒤,
그 {combkr}이 <b>상위 {100 * (1 - RB['gate']['th']):.1f}% 이내</b>이면 통과한다.
<ul>{gate_feat}</ul></td></tr>
<tr><td>위험 경보<br>발령</td><td><b style="color:#c0392b">위험</b></td><td class=l>
주의 구역 선별 통과 이후, 아래 세 항목이 <b>각각 정해진 기준값을 모두 동시에</b> 넘는 상태가
<b>{s2['K']}회 관측 연속</b>(약 {s2['K'] * rv:.0f}일) 이어지면 발령한다.
항목별 기준값과 본 관심 지역 실측값은 <b>규칙별 상세</b> 항목에 있다.
<ul>{s2_feat}</ul></td></tr>
</table>

<h2 class=pb>2. 관심 지역 개별 판정 - {args.name}</h2>
<table>
<tr><td class=k>관심 지역명</td><td class=l>{args.name}</td>
    <td class=k>소재지</td><td class=l>{args.addr}</td></tr>
<tr><td class=k>중심 좌표</td><td class=l>위도 {A['lat']:.6f} · 경도 {A['lon']:.6f}</td>
    <td class=k>관심 지역</td><td class=l>{shp['area']:,.0f} m²<br>
    위도 {min(vlat):.6f}~{max(vlat):.6f}<br>경도 {min(vlon):.6f}~{max(vlon):.6f}</td></tr>
</table>
<div class=note>{A.get('geo_note', '좌표 직접 입력')}</div>

<div class=box>
<div style="text-align:center">
<div style="font-size:10px;color:#555;margin-bottom:3px">{A['asof']} 기준 판정
              <span style="color:#888">(자료는 {ob['end']} 촬영까지)</span></div>
<div class=big>{grade}</div>
<div style="font-size:9.5px;color:#555;margin-top:4px">
주의 구역 선별 {'진입' if g['pass'] else '미진입'}{'' if g['pass_now'] else '(기준일 미성립)'} ·
위험 경보 {'조건 성립' if al['instant'] else ('과거 성립 이력 있음(기준일 미성립)' if al['fired'] else '이력 없음')}</div>
</div></div>
<div class=note>· 등급 체계 - 정상 → 주의 → 위험<br>
· 등급은 <b>기준일 시점에 조건이 성립하는지</b>로 정한다<br>
· 주의 구역 선별은 <b>한 번 통과하면 감시 대상으로 남는</b> 진입 조건이다. 진입 이후에는 위험 경보 조건만 본다<br>
· 기준일 시점 선별 점수 <b>{'-' if g['score_now'] is None else '%.3f' % g['score_now']}</b>
(기준 {g['th']:.4f}) {gate_txt}<br>
· 본 관심 지역 위험 경보 조건 성립 이력 <b>{al['n_fire_epoch']}회</b>{alarm_txt}<br>
· {watch_txt}</div>

<h3>2-1. 판정 근거</h3>
<table>
<tr><td class=k>판정 범위</td><td class=l>중심에서 반경 400 m</td>
    <td class=k>주의 구역 최초 진입일</td><td class=l>{g['first'] or '없음'}</td></tr>
<tr><td class=k>위험 경보 조건 성립 이력</td><td class=l>{al['n_fire_epoch']}회</td>
    <td class=k>최초 성립일</td><td class=l>{al['first'] or '없음'}</td></tr>
<tr><td class=k>최근 성립일</td><td class=l>{al['last_fire'] or '없음'}</td>
    <td class=k>기준일 현재</td>
    <td class=l><b>{'조건 성립' if al['instant'] else '조건 미성립'}</b></td></tr>
<tr><td class=k>현재 침하 속도</td><td class=l>연간 {A.get('vel_now', '-')} mm</td>
    <td class=k>최근 1년 침하량</td><td class=l>{A.get('cum1_now', '-')} mm</td></tr>
<tr><td class=k>지반 등급</td><td class=l>{alpkr}</td>
    <td class=k>침하 가속</td><td class=l>연간 {A.get('dv_now', '-')} mm</td></tr>
</table>
<div class=note>· 지반 등급은 반경 {int(R)} m 안에서 <b>가장 낮은 등급</b>을 적는다<br>
· 등급 체계 - <b>연약 · 주의 · 양호</b> 3단계이며, 등급이 낮을수록 판정 임계값을 그만큼 낮춰 적용한다<br>
· <b>N값</b> - 표준관입시험에서 시료 채취기를 30 cm 관입시키는 데 필요한 해머 타격 횟수이며, 작을수록 무른 지반이다<br>
· 시추공 자료 기준 - 연약층이 있으면 <b>연약</b>, 연약층이 없어도 최저 N값 10 이하이면 <b>주의</b>, 10 초과이면 <b>양호</b>로 매긴다<br>
· 연약층 판정 - 점성토·이탄질은 N값 4 이하이면서 심도 10 m 미만, 사질토는 N값 6 이하이면서 심도 10 m 이상인 층
  <span style="color:#666">(한국도로공사 도로설계요령 2009)</span><br>
· 반경 400 m 안에 시추공이 없으면 수치지질도 암상으로 대신 판정한다 - 충적층·매립지·석회암은 <b>연약</b>,
  풍화대는 <b>주의</b>, 기반암은 <b>양호</b></div>

<h3>2-2. 규칙별 상세</h3>
<div class=note>· <b>주의 구역 선별</b> - 항목별로 분석 영역 내 상위 순위를 매겨 결합한다</div>
<table>
<tr><th>주의 구역 선별 항목</th><th style="width:76px">상위 순위<br>(0~1)</th><th style="width:200px">해석</th></tr>
{pct_rows}
<tr style="background:#f7f7f7"><td class=l><b>결합 점수 ({combkr})</b></td>
    <td><b>{'-' if g['score_now'] is None else '%.3f' % g['score_now']}</b></td>
    <td class=l>기준 {g['th']:.4f} - <b>{'성립' if g['pass_now'] else '미성립'}</b></td></tr>
</table>
<div class=note>· 1 에 근접할수록 분석 영역 내 다른 지점 대비 침하가 심하다<br>
· 0.5 는 중간 순위, 0.9 는 상위 10% 수준에 해당한다</div>
<div class=note style="margin-top:10px">· <b>위험 경보 발령</b> - 아래 조건을 모두 충족한 상태가 이어져야 발령한다</div>
<table>
<tr><th>위험 경보 조건</th><th style="width:96px">기준값</th>
    <th style="width:96px">본 관심 지역 현재값</th><th style="width:66px">충족</th></tr>
{cond_rows}
</table>
{consec_note}

<h3>2-3. 관심 지역 변위 시계열</h3>
{site_chart}

<div class=note style="margin-top:14px;border-top:1px solid #ccc;padding-top:6px">
본 보고서는 인공위성 관측에 근거한 참고자료이며, 최종 판단은 현장 조사와 병행할 것을 권고한다.
</div>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", required=True)
    ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float)
    ap.add_argument("--name", default="공사현장")
    ap.add_argument("--side", type=float, default=50.0)
    ap.add_argument("--asof", help="판정 기준일 YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--out")
    args = ap.parse_args()

    note = "좌표 직접 입력"
    if args.lat is None or args.lon is None:
        gc = geocode_by_road(args.addr)
        if gc is None:
            sys.exit("좌표를 찾지 못했습니다 - --lat/--lon 을 직접 주십시오.")
        args.lat, args.lon, note = gc
        print("  지오코딩 %.6f, %.6f" % (args.lat, args.lon), flush=True)

    p, vtx, area = make_site_shp(args.lat, args.lon, args.side, args.name)
    print("  폴리곤 → %s (한 변 %.0f m · %.0f m²)" % (p, args.side, area), flush=True)

    d0 = datetime.date.fromisoformat(args.asof) if args.asof else datetime.date.today()
    av = d0.year + (d0 - datetime.date(d0.year, 1, 1)).days / DAYS
    A = analyze(args.lat, args.lon, args.side, av)
    A["geo_note"] = note
    if A.get("insufficient"):
        sys.exit("판정 불가 - %s" % A["insufficient"])
    shp = dict(path=p, vtx=vtx, area=area)
    out = args.out or os.path.join(
        OUTDIR, "%s_지반침하보고서_%s.html" % (args.name, d0.isoformat().replace("-", "")))
    open(out, "w", encoding="utf-8").write(build(A, args, shp, av))
    json.dump(A, open(out.replace(".html", ".json"), "w"), ensure_ascii=False, indent=2, default=str)
    h = A["region_hist"]
    print("  지역 사고 이력 %d건 (%s)" % (h["n"], h["span"]), flush=True)
    print("  기준일 %s · 최종 촬영 %s (%d일 이전) · 촬영 %d회"
          % (A["asof"], A["obs"]["end"], A["obs"]["lag_d"], A["obs"]["n_epoch"]), flush=True)
    print("  공사장 판정 <%s> · 선별 %s(%s) · 경보 %s(%s) · 반경400m 관측 %d점"
          % (A["grade"], "통과" if A["gate"]["pass"] else "미통과", A["gate"]["first"] or "-",
             "발령" if A["alarm"]["fired"] else "미발령", A["alarm"]["last_fire"] or "-", A["n_buf"]),
          flush=True)
    if A.get("after"):
        x = A["after"][0]
        print("  기준일 이후 실제 사고 %d건 · 최초 %s (%d일 후 · %dm)"
              % (len(A["after"]), x["date"], x["days"], x["d_m"]), flush=True)
    print("→ %s" % out, flush=True)


if __name__ == "__main__":
    main()
