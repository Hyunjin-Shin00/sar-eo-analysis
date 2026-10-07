# -*- coding: utf-8 -*-
"""과제②: 정제 지반침하 사고 리스트 전체에 '기존 위험판정 기준'을 동일 적용
        → (STEP1) 사고별 위험등급  (STEP2) 리드타임  (STEP3) 탐지정확도  (STEP4) 변위양상 패턴.

원칙(사용자 지시):
 - 위험등급·급변점 로직은 기존 검증자산 그대로 재사용(indicators·loaders·config·make_unified_map).
   새 위험기준을 만들지 않는다. 함수가 이미 지원하는 asof_year만 채워 '사고일 이전' 판정.
 - 사고 좌표=주소 지오코딩 근사 → 한 점이 아니라 R_search 버퍼 내 포인트 종합.
 - '변위 없음'으로 사고를 추가 제외하지 않는다(FN을 데이터에서 지우는 순환논리 금지).
 - 관측범위 밖은 '데이터 없음'으로 별도 집계(제외 아님).
 - 리드타임 = 사고 직전(가)·최초 전조(나) 급변점, 사고일 '이전'만 유효.
 - 패턴은 있으면 제시·없으면 없다고 정직 보고. 표본 적음 → 케이스검증·분포 중심.

확정 파라미터(2026-07-15, 사용자): R_search=300m(스윕 6종) · vjump_min=8.0(기존) · 규모=W×L×D · asof=사고일 이전.
부호규약: LOS 침하=음(-). risk_vel=-vel(양수=침하). 거리/버퍼=UTM52N 미터.
"""
import os; os.environ.pop("PYTHONPATH", None)
import sys, csv, warnings
sys.path.insert(0, "<DATA_ROOT>/analysis/sinkhole")
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore", message="Mean of empty slice")
warnings.filterwarnings("ignore", message="invalid value encountered")
warnings.filterwarnings("ignore", message="Degrees of freedom")

from config import CONFIG
import loaders
import indicators as ind
import make_unified_map as mum   # detect_inflection·smooth_series·inverse_velocity·_year_of·_yr_to_date 재사용

# ------------------------------------------------------------------ 설정
ORDER = {"정상": 0, "주의": 1, "위험": 2}
ACFG = {
    "csv":  "<DATA_ROOT>/auxiliary/subsidence_list/subsidence_accidents_geocoded_update.csv",
    "regions": ["Seoul_Gangdong", "Seoul_Seodaemun", "Gyeonggi_Gwangmyeong",
                "Incheon_Songdo", "Busan_Mandeok_Centum", "Busan_Sasang_Hadan", "Yangyang"],
    "R_search_m": 300.0,
    "R_sweep_m": [150, 200, 300, 500, 750, 1000],
    "coverage_max_m": 2000.0,          # 이 초과면 '관측범위 밖(데이터 없음)'
    "vjump_min_mmyr": 8.0,             # 급변점 임계(기존 map_viz 재사용)
    "min_series_lead": 8,              # 급변점 탐지 최소 관측
    "pre_min_epochs": 6,              # asof 판정 최소 사고전 관측
    "out": "<DATA_ROOT>/analysis/sinkhole/out/acclist",
    # AOI 케이스 라벨(확정 사고이력 기준; 리스트 사고는 전부 실제 발생임에 유의)
    "neg_regions": ["Incheon_Songdo", "Busan_Mandeok_Centum"],   # 미발생(비붕괴) 기준선 AOI
}
VIZ = dict(CONFIG.get("map_viz", {}))       # 급변점/평활 파라미터(기존)
VIZ["infl_vjump_min_mmyr"] = ACFG["vjump_min_mmyr"]


# ------------------------------------------------------------------ 입력
def load_accidents():
    """정제 CSV → 사고 dict 리스트(좌표 유효만). 규모=W×L×D(가능시)."""
    rows = list(csv.DictReader(open(ACFG["csv"], encoding="utf-8-sig")))
    out = []
    for r in rows:
        try:
            la, lo = float(r["lat"]), float(r["lon"])
        except (TypeError, ValueError):
            continue
        if not (33 < la < 39.5 and 124 < lo < 132):
            continue
        def _f(k):
            try: return float(r.get(k))
            except (TypeError, ValueError): return np.nan
        w, l, d = _f("sinkWidth"), _f("sinkExtend"), _f("sinkDepth")
        vol = w * l * d if np.all(np.isfinite([w, l, d])) else np.nan
        out.append({"no": r["sagoNo"], "date": str(r["sagoDate"]).strip(),
                    "year": mum._year_of(_fmt(r["sagoDate"])), "lat": la, "lon": lo,
                    "sigungu": r.get("siGunGu", ""), "dong": r.get("dong", ""), "addr": r.get("addr", ""),
                    "w": w, "l": l, "d": d, "vol": vol, "grd": r.get("grdKind", ""),
                    "death": r.get("deathCnt", "0"), "injury": r.get("injuryCnt", "0")})
    return out


def _fmt(x):
    x = str(x).strip()
    return f"{x[0:4]}-{x[4:6]}-{x[6:8]}" if len(x) == 8 and x.isdigit() else x


def load_region_bank():
    """지역별 PS/SBAS 로드 + α(geo_integrated) 결합 + KDTree(UTM52N). 관측기간 포함."""
    bank = {}
    for reg in ACFG["regions"]:
        ps, sb = loaders.load_ps(reg), loaders.load_sbas(reg)
        gi = pd.read_csv(f"<DATA_ROOT>/analysis/sinkhole/out/geo_integrated_{reg}.csv", encoding="utf-8-sig")
        box = mum.AOI_SNWE.get(reg) if ACFG.get("clip_bbox") else None
        entry = {"kinds": {}, "box": box}
        for kind, dat in (("PS", ps), ("SBAS", sb)):
            g = gi[gi["kind"] == kind]
            alpha = _join_alpha(dat, g)
            lon, lat, x, y, vel, disp = dat["lon"], dat["lat"], dat["x"], dat["y"], dat["vel"], dat["disp"]
            if box is not None:                       # AOI.xlsx SNWE 박스로 클립
                S, N, W, E = box
                m = (lat >= S) & (lat <= N) & (lon >= W) & (lon <= E)
                lon, lat, x, y, vel, disp, alpha = lon[m], lat[m], x[m], y[m], vel[m], disp[m], alpha[m]
            entry["kinds"][kind] = {
                "lon": lon, "lat": lat, "x": x, "y": y, "vel": vel, "disp": disp, "years": dat["years"],
                "alpha": alpha, "tree": cKDTree(np.c_[x, y]) if len(x) else None}
        yrs = np.concatenate([ps["years"], sb["years"]])
        entry["y0"], entry["y1"] = float(yrs.min()), float(yrs.max())
        bank[reg] = entry
    return bank


def _join_alpha(dat, g):
    """geo_integrated α를 좌표 최근접으로 결합(동일 포인트집합 → dist≈0). 실패시 1.0."""
    if len(g) == 0:
        return np.ones(len(dat["lon"]))
    gx, gy = loaders._TR_M.transform(g["lon"].values, g["lat"].values)
    tree = cKDTree(np.c_[gx, gy])
    dist, idx = tree.query(np.c_[dat["x"], dat["y"]])
    a = g["final_alpha"].values[idx]
    a[dist > 5.0] = 1.0                 # 매칭 실패(>5m)면 중립 α=1.0
    return np.asarray(a, float)


# ------------------------------------------------------------------ 판정 코어(기존 재사용, asof 채움)
def judge_points(disp, years, vel, alpha, asof_year):
    """기존 step2_fusion 순서 그대로 + asof 적용. 반환 dict(grade,gv,gc,gt,rv,rc,vel_asof,ind)."""
    m = ind.asof_mask(years, asof_year)
    if m.sum() < ACFG["pre_min_epochs"]:
        return None
    vel_asof = ind._seg_slope(years[m], disp[:, m].astype(float))   # dLOS/dt (음=침하)
    rv = ind.risk_velocity(vel_asof)
    rc = ind.risk_cumulative(disp, years, asof_year)
    tr = ind.trend_grade(disp, years, asof_year)
    gv = ind.subsidence_gate(ind.grade_velocity(rv, alpha), vel_asof)
    gc = ind.subsidence_gate(ind.grade_cumulative(rc, alpha), vel_asof)
    gt = ind.subsidence_gate(tr["grade"], vel_asof)
    grade = ind.combine_max(gv, gc, gt)
    lab = ind.which_indicator(gv, gc, gt)
    return {"grade": grade, "gv": gv, "gc": gc, "gt": gt, "rv": rv, "rc": rc,
            "vel_asof": vel_asof, "ind": lab, "v_late": tr["v_late"]}


# ------------------------------------------------------------------ 사고→버퍼 배정
def assign_buffer(acc, bank, R):
    """사고 근접 지역·버퍼 내 포인트 인덱스. 반환 (region, {PS:idx[],SBAS:idx[]}, nearest_m) 또는 (None,..)."""
    best_reg, best_d = None, np.inf
    ax, ay = loaders._TR_M.transform([acc["lon"]], [acc["lat"]])
    p = np.array([ax[0], ay[0]])
    for reg, e in bank.items():
        for kind in ("PS", "SBAS"):
            t = e["kinds"][kind]["tree"]
            if t is None: continue
            d, _ = t.query(p)
            if d < best_d:
                best_d, best_reg = d, reg
    if best_reg is None:
        return None, None, best_d
    sel = {}
    e = bank[best_reg]
    for kind in ("PS", "SBAS"):
        t = e["kinds"][kind]["tree"]
        sel[kind] = np.array(t.query_ball_point(p, R), int) if t is not None else np.array([], int)
    return best_reg, sel, float(best_d)


# ------------------------------------------------------------------ STEP1: 사고별 위험판정
def step1_judge_accident(acc, bank, reg, sel):
    """버퍼 내 포인트 판정 → 대표(최고위험) + 버퍼분포. asof=사고일 이전(관측종료 이후면 종료시점)."""
    e = bank[reg]
    asof = min(acc["year"], e["y1"]) if acc["year"] else e["y1"]
    post_obs = bool(acc["year"] and acc["year"] > e["y1"] + 1e-6)
    pre_obs = bool(acc["year"] and acc["year"] < e["y0"] - 1e-6)
    recs = []
    for kind in ("PS", "SBAS"):
        idx = sel[kind]
        if not len(idx): continue
        k = e["kinds"][kind]
        J = judge_points(k["disp"][idx], k["years"], k["vel"][idx], k["alpha"][idx], asof)
        if J is None: continue
        for j, gi in enumerate(idx):
            recs.append({"kind": kind, "gidx": int(gi), "grade": J["grade"][j],
                         "gorder": ORDER[J["grade"][j]], "rv": float(J["rv"][j]), "rc": float(J["rc"][j]),
                         "vel_asof": float(J["vel_asof"][j]), "v_late": float(J["v_late"][j]),
                         "ind": J["ind"][j], "alpha": float(k["alpha"][gi])})
    if not recs:
        return None, dict(asof=asof, post_obs=post_obs, pre_obs=pre_obs, n_buf=0)
    # 대표 = 최고등급 → 최대 누적침하 → 최대 침하속도
    rep = max(recs, key=lambda r: (r["gorder"], r["rc"], r["rv"]))
    grds = [r["grade"] for r in recs]
    dist = {g: grds.count(g) for g in ("정상", "주의", "위험")}
    n_ps = sum(1 for r in recs if r["kind"] == "PS")
    summ = dict(asof=asof, post_obs=post_obs, pre_obs=pre_obs, n_buf=len(recs),
                n_ps=n_ps, n_sb=len(recs) - n_ps, dist=dist,
                max_grade=max(grds, key=lambda g: ORDER[g]),
                n_elev=dist["주의"] + dist["위험"], sbas_only=(n_ps == 0))
    return rep, summ


# ------------------------------------------------------------------ STEP2: 리드타임(급변점)
def step2_leadtime(acc, bank, reg, rep):
    """대표포인트 시계열(사고일 이전)에서 급변점 → (가)직전·(나)최초. 사고일 이전만 유효."""
    e = bank[reg]; k = e["kinds"][rep["kind"]]
    disp = k["disp"][rep["gidx"]]; years = k["years"]
    asof = min(acc["year"], e["y1"]) if acc["year"] else e["y1"]
    m = years <= asof
    if m.sum() < ACFG["min_series_lead"]:
        return dict(detected=False, reason="관측부족", n_infl=0)
    dsub = disp[m]; ysub = years[m]
    viz = dict(VIZ); viz["infl_top_n"] = 99      # 모든 임계이상 후보 확보(직전/최초 선택용)
    cands = mum.detect_inflection(dsub, ysub, viz)
    if not cands:
        return dict(detected=False, reason="급변점없음", n_infl=0)
    cyears = sorted([(ysub[c["idx"]], c) for c in cands], key=lambda x: x[0])
    ev = acc["year"]
    before = [(cy, c) for cy, c in cyears if ev is None or cy <= ev]
    if not before:
        return dict(detected=False, reason="급변점_사고이후만", n_infl=len(cands))
    first_y, first_c = before[0]           # 최초 전조(나)
    last_y, last_c = before[-1]            # 직전 급변점(가)
    lead_main = (ev - last_y) * 365.25 if ev else np.nan
    lead_first = (ev - first_y) * 365.25 if ev else np.nan
    return dict(detected=True, n_infl=len(before),
                onset_main=mum._yr_to_date(last_y), lead_main_days=lead_main, vjump_main=last_c["delta_v"],
                onset_first=mum._yr_to_date(first_y), lead_first_days=lead_first, vjump_first=first_c["delta_v"])


# ------------------------------------------------------------------ STEP4: feature set(대표포인트, 사고일 이전)
def feature_set(acc, bank, reg, rep, sel):
    """변위 양상 특징값(패턴분석 공유). asof=사고일 이전. 결측은 NaN(억지보간 금지)."""
    e = bank[reg]; k = e["kinds"][rep["kind"]]
    disp = k["disp"][rep["gidx"]]; years = k["years"]
    asof = min(acc["year"], e["y1"]) if acc["year"] else e["y1"]
    m = years <= asof
    F = {"total_cum_mm": np.nan, "vmax_mmyr": np.nan, "vmean_mmyr": np.nan,
         "n_infl": 0, "max_vjump": np.nan, "iv_r2": np.nan, "iv_accel": 0,
         "duration_days": np.nan, "stable_to_sub": 0, "n_sub_buf": 0}
    if m.sum() < ACFG["min_series_lead"]:
        return F
    y = years[m]; s = -disp[m].astype(float)                 # 침하 양수
    ok = np.isfinite(s)
    if ok.sum() >= 2:
        s = np.interp(np.arange(len(s)), np.where(ok)[0], s[ok])
    sm = mum.smooth_series(s, VIZ.get("smooth_method"), VIZ.get("smooth_window"))
    F["total_cum_mm"] = float(sm[-1] - sm[0])
    # 롤링 국소속도(6점창)
    w = 6; slopes = [ind._seg_slope(y[i:i+w], (sm[i:i+w])[None, :])[0] for i in range(max(1, len(y)-w+1))]
    slopes = np.array(slopes) if slopes else np.array([np.nan])
    F["vmax_mmyr"] = float(np.nanmax(slopes)); F["vmean_mmyr"] = float(np.nanmean(slopes))
    viz = dict(VIZ); viz["infl_top_n"] = 99
    cands = mum.detect_inflection(disp[m], y, viz)
    F["n_infl"] = len(cands)
    F["stable_to_sub"] = int(len(cands) > 0)
    if cands:
        F["max_vjump"] = float(max(c["delta_v"] for c in cands))
        F["duration_days"] = float((y[-1] - y[cands[0]["idx"]]) * 365.25) if cands else np.nan
    iv = mum.inverse_velocity(disp[None, :], years, asof)     # Fukuzono 말기가속(1/v R²)
    F["iv_r2"] = float(iv["r2"][0]); F["iv_accel"] = int(bool(iv["accel"][0]))
    # 공간: 버퍼 내 '침하'(vel_asof<0) 포인트 수 (각 kind 자기 시간축으로)
    n_sub = 0
    for kind in ("PS", "SBAS"):
        idx = sel[kind]
        if not len(idx): continue
        kk = e["kinds"][kind]; mk = kk["years"] <= asof
        if mk.sum() < 3: continue
        va = ind._seg_slope(kk["years"][mk], kk["disp"][idx][:, mk].astype(float))
        n_sub += int(np.sum(va < 0))
    F["n_sub_buf"] = n_sub
    return F


def shape_class(F):
    """침하 진행형태 정성분류: 급가속(Fukuzono) / 계단·가속 / 선형점진 / 미약."""
    if not np.isfinite(F.get("total_cum_mm", np.nan)) or F["total_cum_mm"] < 5:
        return "미약/무침하"
    if F.get("iv_accel", 0) == 1 and F.get("iv_r2", 0) >= CONFIG["invvel"]["r2_min"]:
        return "말기급가속(Fukuzono형)"
    if F.get("n_infl", 0) >= 1 and np.isfinite(F.get("max_vjump", np.nan)) and F["max_vjump"] >= ACFG["vjump_min_mmyr"]:
        return "가속전환형"
    return "선형점진형"


# ------------------------------------------------------------------ 메인 오케스트레이션
def main():
    # 인자로 지역 지정 시 그 지역만 분석(배경·대조군·출력 모두 해당 지역으로 스코프)
    if "--aoibox" in sys.argv:                # AOI.xlsx SNWE 박스로 포인트 클립
        ACFG["clip_bbox"] = True
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    if argv:
        sel_regions = [r for r in argv if r in ACFG["regions"]]
        if not sel_regions:
            print(f"[경고] 인식된 지역 없음({argv}); 전체 실행. 가능: {ACFG['regions']}")
        else:
            ACFG["regions"] = sel_regions
            ACFG["neg_regions"] = sel_regions          # 배경도 동일 지역
            ACFG["out"] = ACFG["out"] + "_" + "_".join(sel_regions) + ("_aoibox" if ACFG.get("clip_bbox") else "")
            print(f"■ 단일/부분 지역 분석: {sel_regions}"
                  + ("  [AOI.xlsx 박스 클립]" if ACFG.get("clip_bbox") else "")
                  + f"  → 출력 {ACFG['out']}")
    os.makedirs(ACFG["out"], exist_ok=True)
    print("■ 사고 리스트 로드"); acc = load_accidents(); print(f"  좌표유효 {len(acc)}건")
    print("■ 지역 PS/SBAS+α 로드"); bank = load_region_bank()

    # ---- STEP1+2+feature: R_search 확정값으로 본분석 ----
    R = ACFG["R_search_m"]
    rows = []
    for a in acc:
        reg, sel, nd = assign_buffer(a, bank, R)
        base = {"no": a["no"], "date": _fmt(a["date"]), "year": a["year"], "region": reg,
                "sigungu": a["sigungu"], "dong": a["dong"], "nearest_m": round(nd, 1),
                "w": a["w"], "l": a["l"], "d": a["d"], "vol": a["vol"], "grd": a["grd"]}
        if reg is None or nd > ACFG["coverage_max_m"]:
            base["cover"] = "관측범위밖"; rows.append(base); continue
        n_buf = sum(len(sel[k]) for k in sel)
        if n_buf == 0:
            base["cover"] = "AOI인근_버퍼공백"; rows.append(base); continue
        base["cover"] = "분석가능"
        rep, summ = step1_judge_accident(a, bank, reg, sel)
        base.update({"asof": round(summ["asof"], 2), "post_obs": summ["post_obs"], "pre_obs": summ["pre_obs"],
                     "n_buf": summ["n_buf"]})
        if rep is None:
            base["cover"] = "판정불가_사고전관측부족"; rows.append(base); continue
        base.update({"rep_kind": rep["kind"], "rep_gidx": rep["gidx"], "rep_grade": rep["grade"], "max_grade": summ["max_grade"],
                     "n_주의": summ["dist"]["주의"], "n_위험": summ["dist"]["위험"], "n_elev": summ["n_elev"],
                     "sbas_only": summ["sbas_only"], "rep_ind": rep["ind"],
                     "rep_rv": round(rep["rv"], 2), "rep_rc": round(rep["rc"], 2), "rep_alpha": rep["alpha"]})
        lt = step2_leadtime(a, bank, reg, rep)
        base.update({"lt_detected": lt["detected"], "lt_reason": lt.get("reason", ""),
                     "onset_main": lt.get("onset_main"), "lead_main_days": lt.get("lead_main_days"),
                     "onset_first": lt.get("onset_first"), "lead_first_days": lt.get("lead_first_days"),
                     "n_infl": lt.get("n_infl", 0)})
        F = feature_set(a, bank, reg, rep, sel)
        base.update({f"F_{k}": v for k, v in F.items()}); base["shape"] = shape_class(F)
        rows.append(base)
    df = pd.DataFrame(rows)
    df["verdict"] = [classify_verdict(r) for r in rows]     # 전 행(관측범위밖 포함) 분류
    df.to_csv(f"{ACFG['out']}/accident_judgment.csv", index=False, encoding="utf-8-sig")
    print(f"  → accident_judgment.csv ({len(df)}건)")

    step3_accuracy(df, acc, bank)
    ctrl = step3_control(acc, bank)
    discriminator(df, ctrl)
    step3_sensitivity(acc, bank)
    step4_patterns(df, bank)
    print("\n■ 완료. 산출물:", ACFG["out"])


def classify_verdict(b):
    """TP / 사전탐지실패 / ③분면(InSAR한계) / 데이터없음 분류."""
    cov = b.get("cover")
    if cov in ("관측범위밖",):
        return "데이터없음"
    if cov in ("AOI인근_버퍼공백", "판정불가_사고전관측부족", "pre_obs"):
        return "데이터없음"
    if b.get("pre_obs"):
        return "데이터없음"
    elev = (ORDER.get(b.get("max_grade", "정상"), 0) >= 1)
    detected = bool(b.get("lt_detected"))
    if elev and detected:
        return "TP"
    if b.get("post_obs"):
        return "③분면_관측종료(직전탐지불가)"
    # 상위등급인데 급변점(선행)이 없으면: 등속 침하 or 급변 미검출
    if elev and not detected:
        return "사전탐지실패_급변점없음"
    return "사전탐지실패_등급미달"


# ------------------------------------------------------------------ STEP3: 정확도
def step3_accuracy(df, acc, bank):
    print("\n■ STEP3 탐지 정확도")
    print("  [커버리지 분류(전 사고)]")
    for k, v in df["cover"].value_counts().items():
        print(f"    {k:28s} {v:5d}")
    ana = df[df["cover"] == "분석가능"].copy()
    vc = df["verdict"].value_counts().to_dict() if "verdict" in df else {}
    print("  [판정 분류]")
    for k in ["TP", "사전탐지실패_등급미달", "사전탐지실패_급변점없음",
              "③분면_관측종료(직전탐지불가)", "데이터없음"]:
        print(f"    {k:28s} {vc.get(k,0):5d}")
    n_ana = len(ana)
    tp = int((ana["verdict"] == "TP").sum()) if "verdict" in ana else 0
    print(f"  분석가능 {n_ana}건 중 TP {tp} (탐지율 {100*tp/max(1,n_ana):.1f}%)")
    lead = ana[ana["verdict"] == "TP"]["lead_main_days"].dropna()
    if len(lead):
        print(f"  주 리드타임(가): 평균 {lead.mean():.0f}일 · 중앙 {lead.median():.0f}일 · 범위 {lead.min():.0f}~{lead.max():.0f}")
    leadf = ana[ana["verdict"] == "TP"]["lead_first_days"].dropna()
    if len(leadf):
        print(f"  참고 리드타임(나·최초전조): 평균 {leadf.mean():.0f}일 · 중앙 {leadf.median():.0f}일")
    ana.to_csv(f"{ACFG['out']}/step3_case_table.csv", index=False, encoding="utf-8-sig")
    pd.Series(vc).to_csv(f"{ACFG['out']}/step3_verdict_summary.csv", encoding="utf-8-sig")
    # 소수 지역(포커스 분석)이면 사고별 케이스 표 출력
    if 0 < n_ana <= 40:
        print("\n  [사고별 케이스 표]")
        hdr = f"    {'사고번호':>10} {'사고일':>10} {'동':>8} {'대표':>5} {'최고등급':>6} {'근거':>8} {'직전급변':>10} {'리드(가)':>7} {'형태':>16} {'판정':>10}"
        print(hdr)
        for _, r in ana.sort_values("date").iterrows():
            lm = r.get("lead_main_days"); lm = f"{lm:.0f}일" if pd.notna(lm) else "-"
            print(f"    {str(r['no']):>10} {str(r['date']):>10} {str(r.get('dong',''))[:6]:>8} "
                  f"{str(r.get('rep_kind','')):>5} {str(r.get('max_grade','')):>6} {str(r.get('rep_ind','')):>8} "
                  f"{str(r.get('onset_main') or '-'):>10} {lm:>7} {str(r.get('shape',''))[:14]:>16} {str(r.get('verdict','')):>10}")


def step3_control(acc, bank, n_ctrl=400, seed=42):
    """★오탐 기준선: 실제 사고와 무관한 랜덤 지점에 동일 파이프라인(버퍼-최고위험+급변점) 적용.
    대조군 탐지율이 실제와 비슷하면 '위치 판별력 없음'(버퍼-max 팽창). 정직 검증용."""
    print("\n■ STEP3 대조군(랜덤 비사고 지점) — 버퍼-max 탐지율 기준선")
    rs = np.random.RandomState(seed)
    R = ACFG["R_search_m"]
    # 실제 분석가능 사고의 (지역, 사고연도) 분포를 대조군에 부여(공정 비교)
    real = []
    for a in acc:
        reg, sel, nd = assign_buffer(a, bank, R)
        if reg and nd <= ACFG["coverage_max_m"] and sum(len(sel[k]) for k in sel) > 0 and a["year"]:
            real.append((reg, a["year"]))
    if not real:
        print("    실제 분석가능 사고 없음 → 대조군 생략"); return
    # 사고좌표 KDTree(대조군이 실제 사고와 겹치지 않게)
    axr, ayr = loaders._TR_M.transform([a["lon"] for a in acc], [a["lat"] for a in acc])
    acc_tree = cKDTree(np.c_[axr, ayr])
    n_ana = n_elev = n_det = 0; leads = []; ctrl_rc = []; ctrl_rv = []
    tries = 0
    while n_ana < n_ctrl and tries < n_ctrl * 20:
        tries += 1
        reg, yr = real[rs.randint(len(real))]
        e = bank[reg]; kind = "PS" if len(e["kinds"]["PS"]["lon"]) else "SBAS"
        K = e["kinds"][kind]; N = len(K["lon"])
        j = rs.randint(N)
        px, py = K["x"][j], K["y"][j]
        # 실제 사고와 R_search*2 이내면 제외(비사고 보장)
        if acc_tree.query([px, py])[0] < R * 2:
            continue
        p = np.array([px, py])
        sel = {}
        for kd in ("PS", "SBAS"):
            t = e["kinds"][kd]["tree"]
            sel[kd] = np.array(t.query_ball_point(p, R), int) if t is not None else np.array([], int)
        if sum(len(sel[k]) for k in sel) == 0:
            continue
        pseudo = {"year": yr, "no": f"CTRL{tries}"}
        rep, summ = step1_judge_accident(pseudo, bank, reg, sel)
        if rep is None:
            continue
        n_ana += 1
        ctrl_rc.append(rep["rc"]); ctrl_rv.append(rep["rv"])
        elev = summ["n_elev"] > 0
        if elev: n_elev += 1
        lt = step2_leadtime(pseudo, bank, reg, rep)
        if elev and lt["detected"]:
            n_det += 1
            if np.isfinite(lt.get("lead_main_days", np.nan)): leads.append(lt["lead_main_days"])
    md = np.median(leads) if leads else np.nan
    step3_control._reps = {"rc": np.array(ctrl_rc), "rv": np.array(ctrl_rv)}   # 판별비교용 저장
    print(f"    대조군 {n_ana}지점: 상위등급 {n_elev} · '탐지' {n_det} → 기준선 탐지율 {100*n_det/max(1,n_ana):.1f}%"
          f" (중앙리드 {md:.0f}일)" if leads else f"    대조군 {n_ana}지점: 상위등급 {n_elev} · '탐지' {n_det} → 기준선 탐지율 {100*n_det/max(1,n_ana):.1f}%")
    pd.DataFrame([{"n_control": n_ana, "n_elevated": n_elev, "n_detected": n_det,
                   "control_detect_rate_%": round(100*n_det/max(1, n_ana), 1),
                   "median_lead_days": round(md, 0) if leads else None}]).to_csv(
        f"{ACFG['out']}/step3_control_baseline.csv", index=False, encoding="utf-8-sig")
    print("    ⚠ 이 기준선이 실제 탐지율과 비슷하면 '위치 판별력'이 아니라 '구역이 침하 중'을 반영(버퍼-max 팽창).")
    return {"rc": np.array(ctrl_rc), "rv": np.array(ctrl_rv),
            "detect_rate": 100*n_det/max(1, n_ana), "n": n_ana}


def discriminator(df, ctrl):
    """★공정 판별 검정: 사고 버퍼-대표 vs 대조군 버퍼-대표(둘 다 buffer-max)의 누적침하 분포 비교.
    균등배경(4-2)은 안정지역에 희석돼 불공정 → 이 비교가 '위치 판별력'의 진짜 잣대."""
    print("\n■ 판별력 검정 — 사고 대표 vs 대조군 대표 (둘 다 buffer-max, 공정 비교)")
    a_rc = pd.to_numeric(df[df["cover"] == "분석가능"]["rep_rc"], errors="coerce").dropna()
    c_rc = pd.Series(ctrl["rc"]).dropna()
    print(f"    누적침하 rep_rc(mm) 중앙값 — 사고 {a_rc.median():.1f} (n={len(a_rc)})  vs  대조군 {c_rc.median():.1f} (n={len(c_rc)})")
    print(f"    상위 25% 임계(대조군 75퍼센타일)={c_rc.quantile(.75):.1f}mm 초과 비율 — "
          f"사고 {100*(a_rc>c_rc.quantile(.75)).mean():.0f}% vs 대조군 25%")
    pd.DataFrame({"group": ["accident", "control"],
                  "rep_rc_median": [round(a_rc.median(), 1), round(c_rc.median(), 1)],
                  "rep_rc_p75": [round(a_rc.quantile(.75), 1), round(c_rc.quantile(.75), 1)],
                  "n": [len(a_rc), len(c_rc)]}).to_csv(
        f"{ACFG['out']}/step3_discriminator.csv", index=False, encoding="utf-8-sig")


def step3_sensitivity(acc, bank):
    print("\n■ STEP3 민감도(R_search 스윕) — 분석가능/탐지 건수")
    out = []
    for R in ACFG["R_sweep_m"]:
        n_ana = n_tp = n_elev = 0
        leads = []
        for a in acc:
            reg, sel, nd = assign_buffer(a, bank, R)
            if reg is None or nd > ACFG["coverage_max_m"]: continue
            if sum(len(sel[k]) for k in sel) == 0: continue
            rep, summ = step1_judge_accident(a, bank, reg, sel)
            if rep is None: continue
            n_ana += 1
            elev = summ["n_elev"] > 0
            if elev: n_elev += 1
            lt = step2_leadtime(a, bank, reg, rep)
            if elev and lt["detected"]:
                n_tp += 1
                if np.isfinite(lt.get("lead_main_days", np.nan)): leads.append(lt["lead_main_days"])
        md = np.median(leads) if leads else np.nan
        out.append({"R_m": R, "n_analyzable": n_ana, "n_elevated": n_elev, "n_TP": n_tp,
                    "detect_rate_%": round(100*n_tp/max(1, n_ana), 1), "median_lead_days": round(md, 0) if leads else None})
        print(f"    R={R:4d}m  분석가능 {n_ana:3d}  상위등급 {n_elev:3d}  TP {n_tp:3d}  탐지율 {out[-1]['detect_rate_%']:5.1f}%  중앙리드 {out[-1]['median_lead_days']}")
    pd.DataFrame(out).to_csv(f"{ACFG['out']}/step3_sensitivity_R.csv", index=False, encoding="utf-8-sig")


# ------------------------------------------------------------------ STEP4: 패턴
def step4_patterns(df, bank):
    print("\n■ STEP4 변위 양상 패턴(탐색적)")
    ana = df[(df["cover"] == "분석가능") & df["shape"].notna()].copy()
    feats = ["F_total_cum_mm", "F_vmax_mmyr", "F_vmean_mmyr", "F_n_infl", "F_max_vjump",
             "F_iv_r2", "F_iv_accel", "F_duration_days", "F_n_sub_buf"]
    # 4-1 규모(W×L×D)별
    print("  [4-1] 침하 규모(W×L×D)별 — 대/중/소 3분위")
    a1 = ana[ana["vol"].notna()].copy()
    if len(a1) >= 6:
        try:
            a1["mag"] = pd.qcut(a1["vol"], 3, labels=["소", "중", "대"])
        except ValueError:                       # 동일값 많아 3분위 불가 → 순위 3등분
            a1["mag"] = pd.qcut(a1["vol"].rank(method="first"), 3, labels=["소", "중", "대"])
        g = a1.groupby("mag", observed=True)[feats + ["vol"]].median(numeric_only=True)
        g["n"] = a1.groupby("mag", observed=True).size()
        g.to_csv(f"{ACFG['out']}/step4_1_by_magnitude.csv", encoding="utf-8-sig")
        print(g.round(2).to_string())
        sc = a1.groupby(["mag", "shape"], observed=True).size().unstack(fill_value=0)
        print("    형태분포:\n" + sc.to_string())
    else:
        print(f"    규모·좌표 모두 있는 사고 {len(a1)}건 — 통계 불충분, 케이스 나열만.")

    # 4-2 발생 vs 미발생(배경) — 배경=음성 AOI 포인트 표본
    print("\n  [4-2] 발생(사고 대표) vs 미발생(음성 AOI 배경) 분포")
    occ = ana[feats].apply(pd.to_numeric, errors="coerce")
    bg = background_sample(bank, ACFG["neg_regions"], n=1500)
    _compare_groups(occ, bg, feats, "step4_2_occ_vs_background")

    # 4-3 발생지끼리 — feature 유사성 + 사고일정렬 중첩
    print("\n  [4-3] 발생지끼리 공통 양상")
    tp = ana[ana["verdict"] == "TP"]
    print(f"    TP {len(tp)}건 형태분포: {tp['shape'].value_counts().to_dict()}")
    print(f"    전체 분석가능 형태분포: {ana['shape'].value_counts().to_dict()}")
    ana.groupby("shape", observed=True)[feats].median(numeric_only=True).to_csv(
        f"{ACFG['out']}/step4_3_by_shape.csv", encoding="utf-8-sig")
    _plot_aligned(df, bank)


def background_sample(bank, regions, n=1500):
    """음성 AOI 포인트에서 배경 feature 표본(간이): total_cum·vmax·iv_r2 등. asof=관측전체."""
    recs = []
    for reg in regions:
        e = bank[reg]
        for kind in ("PS", "SBAS"):
            k = e["kinds"][kind]; N = len(k["lon"])
            if N == 0: continue
            take = np.linspace(0, N-1, min(n//2, N)).astype(int)
            years = k["years"]; disp = k["disp"][take]
            s = -disp.astype(float)
            for i in range(s.shape[0]):
                row = s[i]; ok = np.isfinite(row)
                if ok.sum() < 8: continue
                r = np.interp(np.arange(len(row)), np.where(ok)[0], row[ok])
                sm = mum.smooth_series(r, VIZ.get("smooth_method"), VIZ.get("smooth_window"))
                w = 6; sl = [ind._seg_slope(years[j:j+w], (sm[j:j+w])[None, :])[0] for j in range(max(1, len(years)-w+1))]
                sl = np.array(sl)
                iv = mum.inverse_velocity(disp[i][None, :], years, None)
                cands = mum.detect_inflection(disp[i], years, {**VIZ, "infl_top_n": 99})
                recs.append({"F_total_cum_mm": sm[-1]-sm[0], "F_vmax_mmyr": np.nanmax(sl),
                             "F_vmean_mmyr": np.nanmean(sl), "F_n_infl": len(cands),
                             "F_max_vjump": max([c["delta_v"] for c in cands], default=np.nan),
                             "F_iv_r2": iv["r2"][0], "F_iv_accel": int(bool(iv["accel"][0])),
                             "F_duration_days": np.nan, "F_n_sub_buf": np.nan})
    return pd.DataFrame(recs)


def _compare_groups(occ, bg, feats, tag):
    rows = []
    for f in feats:
        o = pd.to_numeric(occ[f], errors="coerce").dropna()
        b = pd.to_numeric(bg[f], errors="coerce").dropna() if f in bg else pd.Series(dtype=float)
        rows.append({"feature": f, "occ_median": round(o.median(), 2) if len(o) else None,
                     "occ_n": len(o), "bg_median": round(b.median(), 2) if len(b) else None, "bg_n": len(b)})
    cmp = pd.DataFrame(rows); cmp.to_csv(f"{ACFG['out']}/{tag}.csv", index=False, encoding="utf-8-sig")
    print(cmp.to_string(index=False))
    # 분포 플롯(주요 3특징)
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.4))
    for ax, f in zip(axes, ["F_total_cum_mm", "F_vmax_mmyr", "F_iv_r2"]):
        o = pd.to_numeric(occ[f], errors="coerce").dropna()
        b = pd.to_numeric(bg[f], errors="coerce").dropna() if f in bg else pd.Series(dtype=float)
        if len(o): ax.hist(o, bins=25, density=True, alpha=0.6, label=f"occur n={len(o)}", color="#c0392b")
        if len(b): ax.hist(b, bins=25, density=True, alpha=0.5, label=f"background n={len(b)}", color="#2166ac")
        ax.set_title(f); ax.legend(fontsize=8)
    plt.tight_layout(); plt.savefig(f"{ACFG['out']}/{tag}.png", dpi=110); plt.close()


def _plot_aligned(df, bank):
    """발생 TP 사고의 대표포인트 누적침하를 사고일(t0) 기준 정렬 중첩(사고전 구간)."""
    ana = df[(df["cover"] == "분석가능") & (df["verdict"] == "TP") & df["rep_gidx"].notna()]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    n = 0
    for _, b in ana.iterrows():
        e = bank.get(b["region"])
        if e is None or b["rep_kind"] not in ("PS", "SBAS"): continue
        k = e["kinds"][b["rep_kind"]]; gidx = int(b["rep_gidx"])
        years = k["years"]; ev = b["year"]
        asof = min(ev, e["y1"]) if ev else e["y1"]; m = years <= asof
        if m.sum() < 8 or not ev: continue
        s = -k["disp"][gidx][m].astype(float); ok = np.isfinite(s)
        if ok.sum() < 8: continue
        s = np.interp(np.arange(len(s)), np.where(ok)[0], s[ok])
        sm = mum.smooth_series(s, VIZ.get("smooth_method"), VIZ.get("smooth_window"))
        rel = (years[m] - ev) * 365.25              # 사고일까지 잔여(음수=이전)
        base = sm - sm[0]
        norm = base / (np.max(np.abs(base)) + 1e-9)
        ax.plot(rel, norm, lw=1.0, alpha=0.6)
        n += 1
    ax.axvline(0, color="#c0392b", ls="--", lw=1.2, label="accident t0")
    ax.set_title(f"Accident-aligned cumulative subsidence (rep points, normalized) n={n}")
    ax.set_xlabel("days to accident (negative=before)"); ax.set_ylabel("normalized cumulative subsidence")
    ax.legend(fontsize=8)
    plt.tight_layout(); plt.savefig(f"{ACFG['out']}/step4_3_aligned.png", dpi=110); plt.close()
    print(f"    사고일 정렬 중첩도: {n}건 → step4_3_aligned.png")


if __name__ == "__main__":
    main()
