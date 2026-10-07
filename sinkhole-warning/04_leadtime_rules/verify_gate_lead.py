# -*- coding: utf-8 -*-
"""[검증 전용·읽기 전용] 2단 파이프라인 탐지율 주장 6개 검증. usage: verify_gate_lead.py
파이프라인 산출물을 수정하지 않는다. 출력은 out/verify/ 아래에만 쓴다.
검증 방식 2중화
  (A) 리포트 파싱: rule_maps/index_leadtime.html의 「상시 운영 AUC」표·14절 표에서 숫자 추출
  (B) 원천 재계산: out/leadtime/op_series/*__t2k.npz + op_rule.json(규칙 정의)으로 직접 재계산
      · 1단 = 백분위 결합점수 persist_max(K) ≥ Youden 임계 (임계는 저장 반올림값 대신 재계산)
      · 게이트 진입일 = as-of 워크포워드에서 K연속 최초 성립 에폭
      · 2단 = 게이트 진입 이후 구간에서 raw 지표 AND × K연속 최초 발화
      · 주장3 검증용으로 '사고 후 에폭까지 포함한 전기간 최대' 변형도 별도 계산해 비교
출력: out/verify/verify_gate_lead.csv, out/verify/verify_report.json"""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "<DATA_ROOT>/analysis/sinkhole")
import numpy as np
import sweep_config as C
import discrim_eval as E
import swept_loader as SL
import leadtime_backtest as LB
import leadtime_op as OP
import leadtime_op2 as O2
import leadtime_overfit as LO
import leadtime_region_rule as RRU

DAYS = 365.25
TAG = "t2k"
COH, TCOH, R = 0.3, 0.7, 400.0
HTML = "<DATA_ROOT>/analysis/sbas_sweep/rule_maps/index_leadtime.html"
OUT = os.path.join(C.OUT_ROOT, "verify")
FEATS = RRU.FEATS
ORDER = ["Yangyang", "Incheon_Songdo_DSC", "Busan_Sasang_Hadan", "Seoul_Seodaemun",
         "Gyeonggi_Gwangmyeong", "Seoul_Gangdong", "Busan_Mandeok_Centum"]
# 사용자 주장표
CLAIM = {  # 지역: (사고수, 1단통과, 2단성공, 최종, 중앙리드, 배경발화)
    "Yangyang": (4, 4, 4, 4, 98, 3.3),
    "Incheon_Songdo_DSC": (2, 2, 2, 2, 180, 36.7),
    "Busan_Sasang_Hadan": (14, 14, 12, 12, 140, 10.0),
    "Seoul_Seodaemun": (14, 13, 11, 11, 540, 46.7),
    "Gyeonggi_Gwangmyeong": (3, 2, 2, 2, 584, 0.0),
    "Seoul_Gangdong": (9, 7, 6, 6, 374, 10.0),
    "Busan_Mandeok_Centum": (25, 17, 16, 16, 816, 26.7),
}


def y2d(y):
    yy = int(y)
    return (datetime.date(yy, 1, 1) + datetime.timedelta(days=round((y - yy) * DAYS))).isoformat()


# ---------------- (A) 리포트 파싱 ----------------
def parse_html():
    """운영 AUC 표(탐지·배경발화·사고수) + 14절 ≥80% 행(중앙리드) 추출."""
    if not os.path.exists(HTML):
        return None
    h = open(HTML, encoding="utf-8").read()
    res = {"op_table": {}, "sec14": {}}
    # 운영 AUC 표
    i = h.find("T2k 운영 규칙(지표")
    if i > 0:
        seg = h[i:i + 9000]
        rows = re.findall(r"<tr><td>(사상|양양|송도|광명|서대문|강동|만덕)</td>(.*?)</tr>", seg, re.S)
        for kr, body in rows:
            nums = re.findall(r">([\d.]+)%", body)
            nb = re.search(r"<b>(\d+)</b>건", body)
            aucm = re.search(r"font-weight:700'>([\d.]+)<", body)
            res["op_table"][kr] = {"det%": float(nums[0]) if nums else None,
                                   "bg%": float(nums[1]) if len(nums) > 1 else None,
                                   "n_acc": int(nb.group(1)) if nb else None,
                                   "opAUC": float(aucm.group(1)) if aucm else None}
    # 14절 표: 지역별 ≥80% 행의 중앙 리드
    j = h.find("14. [추가·요청 설계]")
    if j > 0:
        seg = h[j:j + 40000]
        for kr in ("사상", "양양", "강동", "광명", "송도", "서대문", "만덕"):
            m = re.search(r">([^<]*" + kr + r"[^<]*)</td>(.*?)(?=<tr><td>(?:[^<]*(?:사상|양양|강동|광명|송도|서대문|만덕))|$)",
                          seg, re.S)
            if m:
                gm = re.search(r"(\d+)\s*/\s*(\d+)", m.group(2))
                res["sec14"][kr] = {"gate": (int(gm.group(1)), int(gm.group(2))) if gm else None}
    return res


# ---------------- (B) 원천 재계산 ----------------
def pct_of(pool_sorted, vals):
    o = np.full(len(vals), np.nan)
    fin = np.isfinite(vals)
    s = pool_sorted
    if len(s):
        o[fin] = (np.searchsorted(s, vals[fin], "left") + np.searchsorted(s, vals[fin], "right")) / (2 * len(s))
    return o


def full_period_series(region):
    """주장3 검증용: 사고 지점의 '전기간(사고 후 포함)' 12지표 시계열."""
    csv = os.path.join(C.sweep_dir(region, COH, TCOH), f"{region}_sbas_ps_v.csv")
    e = SL.build_bank_entry(region, csv, use_ps=False)
    sb = e["kinds"]["SBAS"]; yrs = sb["years"]; tree = sb["tree"]
    S, N, W, Eb = e["box"]
    acc = E.load_accidents_full()
    box = acc[acc.lat.between(S, N) & acc.lon.between(W, Eb) & acc.year.notna()]
    box = box[(box.year >= e["y0"]) & (box.year <= e["y1"])]
    out = {}
    for _, a in box.iterrows():
        ax, ay = SL.loaders._TR_M.transform([a.lon], [a.lat])
        idx = np.array(tree.query_ball_point([ax[0], ay[0]], R), int)
        if not len(idx) or (yrs <= float(a.year)).sum() < LB.MIN_EP:
            continue
        t, Fm = LO.ff_series(sb["disp"][idx], yrs, sb["alpha"][idx], float(yrs[-1]))
        if len(t):
            out[str(a.get("sagoNo"))] = (t, Fm, float(a.year))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    rep = parse_html()
    OPJ = json.load(open(os.path.join(C.OUT_ROOT, "leadtime", "op_rule.json")))["per_region"]
    GOJ = json.load(open(os.path.join(C.OUT_ROOT, "leadtime", "gate_op.json")))["regions"]
    MONO = json.load(open(os.path.join(C.OUT_ROOT, "t2k_monotone.json")))["regions"]
    rows, per = [], {}
    for region in ORDER:
        kr = LB.KR[region]
        g = OPJ[region]["cfgs"]["t2k"]
        A, B = OP.get_series(region, TAG)
        Ap, Bp, flips = OP.prep_pct(A, B)
        fs = [FEATS.index(f) for f in g["features"]]
        K, comb = g["K"], g["comb"]

        def score(m):
            sub = m[:, fs]
            with np.errstate(all="ignore"):
                return OP.COMB[comb](sub, axis=1) if len(fs) > 1 else sub[:, 0]
        pa = np.array([OP.persist_max(score(m), K) for m in Ap], float)
        pb = np.array([OP.persist_max(score(m), K) for m in Bp], float)
        th, det_re, bg_re = OP.youden_op(pa, pb)

        # 게이트 진입 에폭 + as-of 검증
        UA, UB = O2.make_units(A, B)
        ja, entry, post = [], [], 0
        for u, m in zip(UA, Ap):
            s = score(m)
            ok = np.nan_to_num(s, nan=-1e18) >= th
            j = O2.bool_first_fire(ok, K)
            ja.append(j)
            if j >= 0:
                te = float(u["t"][j])
                entry.append(te)
                if te > u["t_acc"]:
                    post += 1
            else:
                entry.append(None)
        # 사고 시계열이 실제로 사고일 이전까지만인지 검증
        tmax_over = sum(1 for u in UA if len(u["t"]) and float(u["t"][-1]) > u["t_acc"])

        # 2단(≥80% 운용점) 재계산
        c80 = GOJ[[k for k in GOJ if GOJ[k]["kr"] == kr][0]]["by_floor"].get("80")
        s2rule = [(FEATS.index(f), float(t)) for f, t in c80["rule"]] if c80 else []
        K2 = int(c80["K"]) if c80 else 1
        s2lead, s2first = [], []
        for u, j in zip(UA, ja):
            if j < 0:
                s2lead.append(None); s2first.append(None); continue
            F = u["F"][:, j:]; t = u["t"][j:]
            ok = np.ones(F.shape[1], bool)
            for f, thv in s2rule:
                ok &= (F[f] >= thv)
            i2 = O2.bool_first_fire(ok, K2)
            if i2 < 0:
                s2lead.append(None); s2first.append(None)
            else:
                s2lead.append(round(float((u["t_acc"] - t[i2]) * DAYS), 1))
                s2first.append(float(t[i2]))
        n_acc = len(UA)
        n_g1 = sum(1 for j in ja if j >= 0)
        n_g2 = sum(1 for x in s2lead if x is not None)
        d = [x for x in s2lead if x is not None]
        med = round(float(np.median(d)), 1) if d else None
        bg_pass = sum(1 for m in Bp if np.isfinite(OP.persist_max(score(m), K))
                      and OP.persist_max(score(m), K) >= th)
        neg = sum(1 for x in d if x <= 0)
        viol = sum(1 for u, x in zip(UA, s2lead)
                   if x is not None and u["gap"] is not None and x < u["gap"] - 0.01)
        per[region] = {"kr": kr, "n_acc": n_acc, "n_gate1": n_g1, "n_stage2": n_g2,
                       "det1%": round(100 * n_g1 / n_acc, 1), "det2%_of_gate": round(100 * n_g2 / max(1, n_g1), 1),
                       "final%": round(100 * n_g2 / n_acc, 1), "med_lead_d": med,
                       "bg_fire%": round(100 * bg_pass / len(Bp), 1), "bg_pass": bg_pass, "n_bg": len(Bp),
                       "th_recalc": round(th, 5), "th_json": g["th"], "det_json": g["det%"], "bg_json": g["bg_fire%"],
                       "det_recalc": det_re, "bg_recalc": bg_re,
                       "n_discrim_mono": MONO.get(region, {}).get("n"),
                       "entry_after_accident": post, "series_extends_past_accident": tmax_over,
                       "lead_le0": neg, "gap_violations": viol,
                       "s2_rule": c80["rule"] if c80 else None, "s2_K": K2}
        for u, j, te, sf, sl in zip(UA, ja, entry, s2first, s2lead):
            rows.append({"지역": kr, "사고일": u["date"], "원인": u["cause"], "gap": u["gap"],
                         "게이트_진입일": y2d(te) if te else "",
                         "게이트_통과여부": "통과" if j >= 0 else "미통과",
                         "진입리드(사고일-진입일)": round((u["t_acc"] - te) * DAYS, 1) if te else "",
                         "2단_최초발화일": y2d(sf) if sf else "",
                         "2단_리드": sl if sl is not None else "",
                         "최종탐지여부": "탐지" if sl is not None else "미탐"})
        print(f"[{kr}] 사고 {n_acc} · 1단 {n_g1}({per[region]['det1%']}%) · 2단 {n_g2} · "
              f"중앙리드 {med}d · 배경 {bg_pass}/{len(Bp)}({per[region]['bg_fire%']}%) · "
              f"진입>사고 {post}건 · 시계열초과 {tmax_over}건 · 리드≤0 {neg} · gap위반 {viol}", flush=True)

    # ---- 주장3: 사고 후 에폭 포함 변형 ----
    print("\n[주장3] 사고 후 에폭 포함 시 1단 통과율 변화 계산 중...", flush=True)
    inflate = {}
    for region in ORDER:
        kr = LB.KR[region]
        g = OPJ[region]["cfgs"]["t2k"]
        A, B = OP.get_series(region, TAG)
        Ap, Bp, flips = OP.prep_pct(A, B)
        fs = [FEATS.index(f) for f in g["features"]]
        K, comb = g["K"], g["comb"]
        pool = [np.concatenate([b[1][f][np.isfinite(b[1][f])] for b in B]) for f in range(len(FEATS))]
        srt = [np.sort(x) for x in pool]

        def sc_raw(Fm):
            P = np.column_stack([pct_of(srt[f], Fm[f]) for f in range(len(FEATS))])
            P[:, flips] = 1 - P[:, flips]
            sub = P[:, fs]
            with np.errstate(all="ignore"):
                return OP.COMB[comb](sub, axis=1) if len(fs) > 1 else sub[:, 0]
        pa = np.array([OP.persist_max(sc_raw(a["F"]), K) for a in A], float)
        pb = np.array([OP.persist_max(sc_raw(b[1]), K) for b in B], float)
        th, _, _ = OP.youden_op(pa, pb)
        FP = full_period_series(region)
        n_asof = n_full = n_tot = 0
        gained = []
        for a in A:
            n_tot += 1
            s_asof = OP.persist_max(sc_raw(a["F"]), K)
            ok_asof = np.isfinite(s_asof) and s_asof >= th
            n_asof += ok_asof
            got = FP.get(str(a["no"]))
            if got is None:
                n_full += ok_asof
                continue
            t2, F2, tacc = got
            s_full = OP.persist_max(sc_raw(np.where(np.isfinite(F2), F2, np.nan)), K)
            ok_full = np.isfinite(s_full) and s_full >= th
            n_full += ok_full
            if ok_full and not ok_asof:
                gained.append({"date": a["date"], "s_asof": None if not np.isfinite(s_asof) else round(float(s_asof), 4),
                               "s_full": round(float(s_full), 4), "th": round(float(th), 4)})
        inflate[region] = {"kr": kr, "n": n_tot, "asof_pass": int(n_asof), "fullperiod_pass": int(n_full),
                           "delta": int(n_full - n_asof), "gained": gained,
                           "asof%": round(100 * n_asof / max(1, n_tot), 1),
                           "full%": round(100 * n_full / max(1, n_tot), 1)}
        print(f"  {kr}: as-of {n_asof}/{n_tot}({inflate[region]['asof%']}%) vs "
              f"전기간 {n_full}/{n_tot}({inflate[region]['full%']}%) → 차이 {n_full-n_asof}건", flush=True)

    # ---- 저장 ----
    import csv as _csv
    p = os.path.join(OUT, "verify_gate_lead.csv")
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    json.dump({"per_region": per, "html_parsed": rep, "claim3_inflation": inflate,
               "claim_table": {LB.KR[k]: v for k, v in CLAIM.items()}},
              open(os.path.join(OUT, "verify_report.json"), "w"), ensure_ascii=False, indent=2, default=str)
    print(f"\n→ {p}\n→ {os.path.join(OUT, 'verify_report.json')}")


if __name__ == "__main__":
    main()
