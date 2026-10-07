# -*- coding: utf-8 -*-
"""확장 피처 캐시 구축. usage: featx_cache.py [REGION ...]
버퍼 집계 확장(max·p90·top3·med·초과비율) × 베이스 12종(+공간통계·역속도·밀도) = 64피처.
kinds: SBAS · PS_SBAS (전지역), 송도는 +SBAS_AD · PS_SBAS_AD(ASC+DSC 결합).
(region, coh, tcoh, kinds)별 npz 저장: R별 P[n,F]·N[500,F]·causes. 존재 파일 스킵(재개 가능)."""
import os as _os
_CR = _os.environ.get("CLAB_ROOT") or _os.path.abspath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "..", ".."))   # 전달본 상대경로

import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CR + "/analysis/sinkhole")
import numpy as np
from scipy.spatial import cKDTree
import indicators as ind
import make_unified_map as mum
import sweep_config as C
import swept_loader as SL
import discrim_eval as E
import subsidence_list_analysis as M

OUT = os.path.join(C.OUT_ROOT, "featx")
os.makedirs(OUT, exist_ok=True)
REGS = ["Busan_Sasang_Hadan", "Yangyang", "Seoul_Gangdong", "Gyeonggi_Gwangmyeong",
        "Incheon_Songdo_DSC", "Seoul_Seodaemun", "Busan_Mandeok_Centum"]

# ---- 피처 정의 ----
BASES = ["c1", "c1a", "c2", "c2a", "cf", "cfa", "v", "va", "vt", "vta", "dv", "rough"]
AGGS = ["max", "p90", "t3", "med", "xf"]
XF_TH = {"c1": 10, "c1a": 10, "c2": 20, "c2a": 20, "cf": 30, "cfa": 30,
         "v": 5, "va": 5, "vt": 5, "vta": 5, "dv": 5}          # rough는 xf 없음
SCALARS = ["ivfrac", "nbuf", "vsd", "viqr", "amin"]
NAMES = [f"{b}_{a}" for b in BASES for a in AGGS if not (b == "rough" and a == "xf")] + SCALARS
F = len(NAMES)


def agg_all(vals):
    """vals: base -> 1D array. → 피처 벡터 dict."""
    out = {}
    for b in BASES:
        x = np.asarray(vals[b], float); x = x[np.isfinite(x)]
        if len(x):
            out[f"{b}_max"] = float(np.max(x))
            out[f"{b}_p90"] = float(np.percentile(x, 90))
            out[f"{b}_t3"] = float(np.mean(np.sort(x)[-3:]))
            out[f"{b}_med"] = float(np.median(x))
            if b in XF_TH:
                out[f"{b}_xf"] = float(np.mean(x >= XF_TH[b]))
        else:
            for a in AGGS:
                if not (b == "rough" and a == "xf"):
                    out[f"{b}_{a}"] = np.nan
    return out


def feat_ext(e, lat, lon, asof, R, kinds):
    ax, ay = SL.loaders._TR_M.transform([lon], [lat]); p = np.array([ax[0], ay[0]])
    vals = {b: [] for b in BASES}
    ivac = 0; ivn = 0; al = []
    for kind in kinds:
        k = e["kinds"].get(kind)
        t_ = k["tree"] if k else None
        if t_ is None:
            continue
        idx = np.array(t_.query_ball_point(p, R), int)
        if not len(idx):
            continue
        yrs = k["years"]; m = ind.asof_mask(yrs, asof)
        if m.sum() < C.PRE_MIN_EPOCHS:
            continue
        disp = k["disp"][idx]; a = np.asarray(k["alpha"][idx], float)
        a = np.where(np.isfinite(a) & (a > 0), a, 1.0)
        t = yrs[m]; s = -disp[:, m].astype(float)          # 침하 양수
        v = ind._seg_slope(t, s)
        mm = t >= (t[-1] - 1.0)
        vt = ind._seg_slope(t[mm], s[:, mm]) if mm.sum() >= 4 else np.full(len(idx), np.nan)
        c1 = E.cum_window(disp, yrs, asof, 1.0); c2 = E.cum_window(disp, yrs, asof, 2.0)
        cf = E.cum_window(disp, yrs, asof, None)
        tr = ind.trend_grade(disp, yrs, asof); dv = tr["v_late"] - tr["v_early"]
        # 선형적합 잔차 표준편차(시계열 거칠기)
        b0 = np.nanmean(s, axis=1) - v * t.mean()
        rough = np.nanstd(s - (v[:, None] * t[None, :] + b0[:, None]), axis=1)
        iv = mum.inverse_velocity(disp, yrs, asof)
        ivac += int(np.sum(iv["accel"])); ivn += len(idx)
        al += list(a)
        for b, x in (("c1", c1), ("c1a", c1 / a), ("c2", c2), ("c2a", c2 / a),
                     ("cf", cf), ("cfa", cf / a), ("v", v), ("va", v / a),
                     ("vt", vt), ("vta", vt / a), ("dv", dv), ("rough", rough)):
            vals[b] += list(x)
    if not vals["v"]:
        return None
    out = agg_all(vals)
    vv = np.asarray(vals["v"], float); vv = vv[np.isfinite(vv)]
    out["ivfrac"] = float(ivac / max(1, ivn))
    out["nbuf"] = float(len(vals["v"]))
    out["vsd"] = float(np.std(vv)) if len(vv) > 1 else np.nan
    out["viqr"] = float(np.percentile(vv, 90) - np.percentile(vv, 10)) if len(vv) > 1 else np.nan
    out["amin"] = float(np.min(al)) if al else np.nan
    return np.array([out[n] for n in NAMES], float)


def build_entry(region, coh, tcoh, kindset):
    """kindset: SBAS | PS_SBAS | SBAS_AD | PS_SBAS_AD (AD=송도 ASC 추가)."""
    csv = os.path.join(C.sweep_dir(region, coh, tcoh), f"{region}_sbas_ps_v.csv")
    if not os.path.exists(csv):
        return None, None
    use_ps = kindset.startswith("PS")
    e = SL.build_bank_entry(region, csv, use_ps=use_ps)
    kinds = ["PS", "SBAS"] if use_ps else ["SBAS"]
    if kindset.endswith("_AD"):
        acsv = os.path.join(C.sweep_dir("Incheon_Songdo", coh, tcoh), "Incheon_Songdo_sbas_ps_v.csv")
        sb2 = SL.load_sbas_from_csv(acsv, "Incheon_Songdo")
        gi = SL._geo_integrated("Incheon_Songdo")
        g = gi[gi["kind"] == "SBAS"] if len(gi) else gi
        alpha = M._join_alpha(sb2, g)
        S, N, W, E_ = e["box"]
        mbx = (sb2["lat"] >= S) & (sb2["lat"] <= N) & (sb2["lon"] >= W) & (sb2["lon"] <= E_)
        e["kinds"]["SBAS_A"] = {"lon": sb2["lon"][mbx], "lat": sb2["lat"][mbx],
                                "x": sb2["x"][mbx], "y": sb2["y"][mbx], "vel": sb2["vel"][mbx],
                                "disp": sb2["disp"][mbx], "years": sb2["years"], "alpha": alpha[mbx],
                                "tree": cKDTree(np.c_[sb2["x"][mbx], sb2["y"][mbx]]) if mbx.sum() else None}
        kinds.append("SBAS_A")
        e["y0"] = min(e["y0"], float(sb2["years"].min())); e["y1"] = max(e["y1"], float(sb2["years"].max()))
    return e, tuple(kinds)


def collect_x(region, coh, tcoh, kindset):
    e, kinds = build_entry(region, coh, tcoh, kindset)
    if e is None:
        return None
    RNG = np.random.RandomState(11)
    S, N, W, E_ = e["box"]
    acc = E.load_accidents_full()
    inbox = acc[acc.lat.between(S, N) & acc.lon.between(W, E_) & acc.year.notna()].copy()
    axr, ayr = SL.loaders._TR_M.transform(acc.lon.values, acc.lat.values)
    atree = cKDTree(np.c_[axr, ayr])
    out = {}
    for R in C.BUFFERS:
        P, cz, meta = [], [], []
        for _, a in inbox.iterrows():
            if a.year < e["y0"]:
                continue
            f = feat_ext(e, a.lat, a.lon, min(a.year, e["y1"]), R, kinds)
            if f is not None:
                P.append(f); cz.append(a.cause); meta.append(str(a.get("sagoNo")))
        sb = e["kinds"]["SBAS"]; Np = len(sb["lon"])
        yrs_pool = inbox.year.dropna().values
        Ng = []
        got = tries = 0
        while got < min(C.N_NEG, Np) and tries < C.N_NEG * 40 and len(yrs_pool):
            tries += 1; j = RNG.randint(Np)
            if atree.query([sb["x"][j], sb["y"][j]])[0] < R:
                continue
            f = feat_ext(e, sb["lat"][j], sb["lon"][j], yrs_pool[RNG.randint(len(yrs_pool))], R, kinds)
            if f is None:
                continue
            Ng.append(f); got += 1
        out[int(R)] = (np.array(P, float) if P else np.zeros((0, F)),
                       np.array(Ng, float) if Ng else np.zeros((0, F)),
                       np.array(cz, object), np.array(meta, object))
    return out


def main():
    regs = [a for a in sys.argv[1:] if a in REGS] or REGS
    todo = []
    for region in regs:
        ksets = ["SBAS", "PS_SBAS"] + (["SBAS_AD", "PS_SBAS_AD"] if region == "Incheon_Songdo_DSC" else [])
        for coh, tcoh in C.GRID:
            for ks in ksets:
                todo.append((region, coh, tcoh, ks))
    print(f"총 {len(todo)}건", flush=True)
    for i, (region, coh, tcoh, ks) in enumerate(todo):
        fp = os.path.join(OUT, f"{region}__{coh}_{tcoh}__{ks}.npz")
        if os.path.exists(fp):
            continue
        try:
            d = collect_x(region, coh, tcoh, ks)
        except Exception as ex:
            print(f"[ERR] {region} {coh}/{tcoh} {ks}: {type(ex).__name__} {str(ex)[:80]}", flush=True)
            continue
        if d is None:
            continue
        sv = {"names": np.array(NAMES, object)}
        for R, (P, Ng, cz, meta) in d.items():
            sv[f"P{R}"] = P; sv[f"N{R}"] = Ng; sv[f"cz{R}"] = cz; sv[f"id{R}"] = meta
        np.savez_compressed(fp, **sv)
        print(f"[{i+1}/{len(todo)}] {region} coh{coh}/tcoh{tcoh} {ks} n={d[200][0].shape[0]}", flush=True)
    print("완료")


if __name__ == "__main__":
    main()
