# -*- coding: utf-8 -*-
"""
STEP 2 — 변위 3지표 × α 융합 → 최종 위험등급
결합구조: [1단 SBAS 광역 스크리닝(hotspot)] → [2단 PS 정밀 확인]
  · 판정 중심점 = 각 SBAS 점. 반경 R(30m) 내 PS>=K(1)면 PS신호로 확정, 아니면 SBAS단독(PS공백).
  · 두 기법 불일치 시 보수적으로 상위등급 채택.
  · 근거 3분류: ① PS+SBAS 합치 / ② SBAS 단독(PS공백) / ③ PS-SBAS 불일치(보수적 상위)
  · α = 판정점에서 가장 가까운 시추공 등급의 α (nearest-join, 결합거리 기록)

출력:
  out/step2_sbas_judgment_ALL.csv   — SBAS 판정점별 최종등급(포인트별 최종등급표)
  out/step2_ps_elevated_ALL.csv     — PS 점 중 주의/위험 등급(정밀, 구조물 단위)
⚠️ 임계치·α·R·K 잠정값(config.py).
"""
import os
os.environ.pop("PYTHONPATH", None)
import numpy as np, pandas as pd
from scipy.spatial import cKDTree

from config import CONFIG, REGIONS
import loaders, indicators as ind

_ORD = {"정상": 0, "주의": 1, "위험": 2}
_INV = {0: "정상", 1: "주의", 2: "위험"}


def _bore_tree():
    """STEP1 시추공 등급표 → KDTree(UTM52N) + alpha 배열."""
    fp = os.path.join(CONFIG["paths"]["out_dir"], "step1_borehole_grade.csv")
    b = pd.read_csv(fp, encoding="utf-8-sig")
    tree = cKDTree(np.column_stack([b["x_m"].values, b["y_m"].values]))
    return tree, b["alpha"].values, b["등급"].values, b


def _nearest_alpha(tree, alpha, grade, xy):
    d, i = tree.query(xy, k=1)
    return alpha[i], grade[i], d


def process_region(region, bore, thr=None):
    """한 지역 처리 → (sbas_df, ps_elev_df, stats)."""
    thr = thr or CONFIG["thr_base"]
    btree, balpha, bgrade, _ = bore
    R = CONFIG["R_m"]; K = CONFIG["K_ps"]
    sc = CONFIG["sbas"]

    ps = loaders.load_ps(region); sb = loaders.load_sbas(region)
    ps_xy = np.column_stack([ps["x"], ps["y"]]); sb_xy = np.column_stack([sb["x"], sb["y"]])

    # ---- α nearest-join ----
    ps_alpha, _, ps_bd = _nearest_alpha(btree, balpha, bgrade, ps_xy)
    sb_alpha, _, sb_bd = _nearest_alpha(btree, balpha, bgrade, sb_xy)

    # ---- 지표 & 지표별 등급 ----
    ps_rv = ind.risk_velocity(ps["vel"]); ps_rc = ind.risk_cumulative(ps["disp"], ps["years"])
    ps_tr = ind.trend_grade(ps["disp"], ps["years"])
    ps_gv = ind.grade_velocity(ps_rv, ps_alpha, thr); ps_gc = ind.grade_cumulative(ps_rc, ps_alpha, thr)
    # 침하만: 융기(vel>0) 점 지표 등급을 정상으로 게이트
    ps_gv = ind.subsidence_gate(ps_gv, ps["vel"]); ps_gc = ind.subsidence_gate(ps_gc, ps["vel"])
    ps_gt = ind.subsidence_gate(ps_tr["grade"], ps["vel"])
    ps_grade = ind.combine_max(ps_gv, ps_gc, ps_gt)
    ps_gint = np.array([_ORD[g] for g in ps_grade])

    sb_rv = ind.risk_velocity(sb["vel"]); sb_rc = ind.risk_cumulative(sb["disp"], sb["years"])
    sb_tr = ind.trend_grade(sb["disp"], sb["years"])
    sb_gv = ind.grade_velocity(sb_rv, sb_alpha, thr); sb_gc = ind.grade_cumulative(sb_rc, sb_alpha, thr)
    sb_gv = ind.subsidence_gate(sb_gv, sb["vel"]); sb_gc = ind.subsidence_gate(sb_gc, sb["vel"])
    sb_gt = ind.subsidence_gate(sb_tr["grade"], sb["vel"])
    sb_grade = ind.combine_max(sb_gv, sb_gc, sb_gt)
    sb_ind = ind.which_indicator(sb_gv, sb_gc, sb_gt)
    low_tcoh = sb["tcoh"] < sc["tcoh_min"]

    # ---- SBAS hotspot (공간 연속 침하) ----
    subs = sb_rv >= sc["screen_vel_mmyr"]
    tree_all = cKDTree(sb_xy)
    tot = tree_all.query_ball_point(sb_xy, sc["neighbor_R_m"], return_length=True)
    hotspot = np.zeros(len(sb_rv), bool)
    if subs.any():
        tree_sub = cKDTree(sb_xy[subs])
        subc = tree_sub.query_ball_point(sb_xy, sc["neighbor_R_m"], return_length=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            frac = np.where(tot > 0, subc / tot, 0.0)
        hotspot = subs & (subc >= sc["neighbor_min_cnt"]) & (frac >= sc["neighbor_min_frac"])

    # ---- PS-within-R join (판정점=SBAS점) ----
    tree_ps = cKDTree(ps_xy)
    nbr = tree_ps.query_ball_point(sb_xy, R)               # 반경 내 PS 인덱스 리스트
    n_ps = np.array([len(x) for x in nbr])
    ps_rep_int = np.zeros(len(sb_rv), int)                 # 반경 내 PS 최고위험(보수적)
    for i, lst in enumerate(nbr):
        if lst:
            ps_rep_int[i] = ps_gint[lst].max()
    ps_void = n_ps < K
    ps_rep_grade = np.where(ps_void, "", np.array([_INV[v] for v in ps_rep_int], dtype=object))
    # 최근접 PS(참고)
    dnear, inear = tree_ps.query(sb_xy, k=1)
    ps_near_rv = ps_rv[inear]

    # ---- 결합 → 최종등급 + 근거 3분류 ----
    # 2단 구조: SBAS 기여는 hotspot(공간연속 침하)으로 게이팅 → 고립 노이즈점 스크리닝 제외.
    sb_int = np.array([_ORD[g] for g in sb_grade])
    # 고신뢰 단독 구제: hotspot 미형성이라도 고품질(tcoh≥)·강신호(위험 AND 가속확정 or 누적≥danger)
    #  SBAS 단독점은 2단 확인 없이 자체등급 유지(조기경보 recall 우선, 사용자 확정 2026-07-09).
    gt_int = np.array([_ORD[g] for g in sb_gt])
    rescue = np.zeros(len(sb_int), bool)
    if sc.get("rescue_enable", False):
        strong = (sb_int == 2) & ((gt_int == 2) | (sb_rc >= thr["cum_danger"]))
        rescue = strong & (np.nan_to_num(sb["tcoh"], nan=0.0) >= sc.get("rescue_tcoh", 0.7))
    eff_sb = np.where(hotspot | rescue, sb_int, 0)           # 스크리닝 통과(또는 구제) SBAS 등급
    final_int = np.where(ps_void, eff_sb, np.maximum(eff_sb, ps_rep_int))
    # 침하만: 최종등급은 '표시 SBAS점 자체가 침하(vel<0)'일 때만 유지(인접 PS 흡수분 포함).
    #  · vel>=0(융기·정지) 점은 정상 강제(사용자 지시: 최종 변위속도 −만 주의/위험).
    if CONFIG.get("subsidence_only", False):
        final_int = np.where(np.asarray(sb["vel"], float) < 0, final_int, 0)
    final_grade = np.array([_INV[v] for v in final_int], dtype=object)
    # 근거 3분류(경보점만 라벨; 정상은 '-')
    basis = np.full(len(sb_int), "-", dtype=object)
    alarm = final_int >= 1
    b_void = alarm & ps_void
    b_agree = alarm & (~ps_void) & (eff_sb == ps_rep_int)
    b_dis = alarm & (~ps_void) & (eff_sb != ps_rep_int)
    basis[b_void] = "②SBAS단독(PS공백)"
    basis[b_agree] = "①PS+SBAS합치"
    basis[b_dis] = "③불일치(보수상위)"
    disagree = b_dis

    sb_df = pd.DataFrame({
        "region": region, "quad": REGIONS.get(region, {}).get("quad", ""),
        "lon": sb["lon"], "lat": sb["lat"],
        "sbas_rv_mmyr": np.round(sb_rv, 2), "sbas_cum_mm": np.round(sb_rc, 1),
        "sbas_v_late": np.round(sb_tr["v_late"], 2),
        "sbas_gv": sb_gv, "sbas_gc": sb_gc, "sbas_gt": sb_gt, "sbas_grade": sb_grade,
        "sbas_screen_grade": np.array([_INV[v] for v in eff_sb], dtype=object),
        "tcoh": np.round(sb["tcoh"], 2), "low_tcoh": low_tcoh, "hotspot": hotspot,
        "n_ps_R": n_ps, "ps_rep_grade": ps_rep_grade, "rescue": rescue,
        "ps_near_rv_mmyr": np.round(ps_near_rv, 2), "ps_near_dist_m": np.round(dnear, 1),
        "final_grade": final_grade, "basis": basis,
        "indicator": sb_ind, "alpha": np.round(sb_alpha, 2),
        "bore_dist_m": np.round(sb_bd, 1), "far_join": sb_bd > CONFIG["join_far_flag_m"],
        "ps_void": ps_void, "disagree": disagree,
    })

    # ---- PS 상위등급 점 (정밀) ----
    pe = ps_gint >= 1
    ps_elev = pd.DataFrame({
        "region": region, "quad": REGIONS.get(region, {}).get("quad", ""),
        "lon": ps["lon"][pe], "lat": ps["lat"][pe],
        "ps_rv_mmyr": np.round(ps_rv[pe], 2), "ps_cum_mm": np.round(ps_rc[pe], 1),
        "ps_v_late": np.round(ps_tr["v_late"][pe], 2),
        "ps_gv": ps_gv[pe], "ps_gc": ps_gc[pe], "ps_gt": ps_gt[pe], "ps_grade": ps_grade[pe],
        "alpha": np.round(ps_alpha[pe], 2), "bore_dist_m": np.round(ps_bd[pe], 1),
    })

    stats = {
        "region": region, "quad": REGIONS.get(region, {}).get("quad", ""),
        "n_sbas": len(sb_rv), "n_ps": len(ps_rv),
        "sbas_hotspot": int(hotspot.sum()),
        "sbas_주의+": int((sb_int >= 1).sum()), "sbas_위험": int((sb_int == 2).sum()),
        "ps_주의+": int((ps_gint >= 1).sum()), "ps_위험": int((ps_gint == 2).sum()),
        "final_주의": int((final_int == 1).sum()), "final_위험": int((final_int == 2).sum()),
        # 근거 3분류는 '경보점'만 집계 (정상점 제외)
        "①합치": int((basis == "①PS+SBAS합치").sum()),
        "②SBAS단독": int((basis == "②SBAS단독(PS공백)").sum()),
        "③불일치": int((basis == "③불일치(보수상위)").sum()),
        "ps_void_frac": round(ps_void.mean(), 3),
    }
    return sb_df, ps_elev, stats


def run_step2(regions=None, save=True):
    regions = regions or list(REGIONS.keys())
    bore = _bore_tree()
    sb_all, pe_all, stats = [], [], []
    for R in regions:
        try:
            s, p, st = process_region(R, bore)
        except FileNotFoundError as e:
            print("  skip(파일없음):", R, e); continue
        sb_all.append(s); pe_all.append(p); stats.append(st)
        print(f"  {R:<22} SBAS {st['n_sbas']:>6} (hotspot {st['sbas_hotspot']:>5}, "
              f"주의+ {st['sbas_주의+']:>5}) | PS {st['n_ps']:>6} (주의+ {st['ps_주의+']:>5}) | "
              f"최종 주의 {st['final_주의']:>5}/위험 {st['final_위험']:>5} | "
              f"①{st['①합치']} ②{st['②SBAS단독']} ③{st['③불일치']} PS공백{st['ps_void_frac']*100:.0f}%")
    sb_all = pd.concat(sb_all, ignore_index=True); pe_all = pd.concat(pe_all, ignore_index=True)
    stdf = pd.DataFrame(stats)
    if save:
        od = CONFIG["paths"]["out_dir"]
        sb_all.to_csv(os.path.join(od, "step2_sbas_judgment_ALL.csv"), index=False, encoding="utf-8-sig")
        pe_all.to_csv(os.path.join(od, "step2_ps_elevated_ALL.csv"), index=False, encoding="utf-8-sig")
        stdf.to_csv(os.path.join(od, "step2_region_stats.csv"), index=False, encoding="utf-8-sig")
    print("\n" + "=" * 70)
    print("STEP 2 요약  (⚠️ 임계치 base=6·22값, α·R=30m·K=1 잠정)")
    print("=" * 70)
    print(stdf.to_string(index=False))
    return sb_all, pe_all, stdf


if __name__ == "__main__":
    run_step2(save=True)
