# -*- coding: utf-8 -*-
"""ASC/DSC 중복기간 수직·동서 분해 → SBAS csv 4종 생성. usage: decomp_build.py [지역...]

왜 csv 로 떨어뜨리나
  기존 분석(dsc_full_analysis.py)은 swept_loader.build_bank_entry(region, csv) 로 읽는다.
  분해 결과를 같은 포맷 csv 로 쓰면 지표 계산·게이트·규칙 탐색을 **완전히 동일한 코드**로 돌릴 수 있다.
  새 경로를 만들면 비교가 오염된다.

절차
 1) ASC/DSC csv 로드 (원본 disp - 언랩억제는 로더가 이미 적용)
 2) AOI 를 55 m 격자로 나눠 셀별 중앙값 → 두 궤도의 **공통 셀**만 남김
 3) 시간축 = 중복기간 안의 DSC 관측일 (에폭이 적은 쪽 기준). ASC 는 그 날짜로 선형보간
    · 보간 신뢰를 위해 앞뒤 ASC 관측이 GAP_MAX 일 안에 있는 날짜만 채택
 4) 각 셀·각 에폭에서 2성분 분해:
      LOS = U·cosθ + E·sinθ·sin(α_gs)     (남북은 |0.17| 로 둔감 → 무시, 통상 관행)
      [asc]   [ca  ea][U]                  ea = sin(α_a)·sinθa ≈ -0.98·sinθa
      [dsc] = [cd  ed][E]                  ed = sin(α_d)·sinθd ≈ +0.98·sinθd
 5) 네 세트를 같은 격자·같은 날짜로 csv 저장
      ASC_LOS(중복기간) · DSC_LOS(중복기간) · UP · EW
    velocity = 시계열 선형회귀 기울기(mm/yr), tcoh = 두 궤도 tcoh 의 최솟값

부호 규약: 파이프라인의 disp 는 침하가 양수(-LOS). 분해는 물리 LOS(위성방향 +)에서 해야 하므로
  내부에서 los = -disp 로 되돌려 계산하고, 저장할 때 다시 부호를 뒤집어 침하 양수로 맞춘다.
  UP 은 "침하 양수"(= -Up), EW 는 "서향 양수"(= -East) 로 저장해 기존 지표 방향과 일치시킨다.
"""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json, re
sys.path.insert(0, "<DATA_ROOT>/CLAB/analysis/sbas_sweep")
sys.path.insert(0, "<DATA_ROOT>/CLAB/analysis/sinkhole")
import numpy as np
import pandas as pd
import swept_loader as SL

CL = "<DATA_ROOT>/CLAB"
D1 = "<WORK_ROOT>/CLAB_DSC"
OUTD = os.path.join(D1, "decomp")
GRID = 0.0005            # 약 55 m
GAP_MAX = 30             # ASC 보간 시 허용하는 앞뒤 관측 간격(일)
MIN_CELL = 200           # 공통 셀이 이보다 적으면 분해 포기
RAD = np.pi / 180
DAYS = 365.25

REG = {
    "만덕": dict(asc_region="Busan_Mandeok_Centum", snwe=(35.1644, 35.2508, 129.0092, 129.1379),
               asc=CL + "/regions/busan/sbas/mandeok_centum/Busan_Mandeok_Centum_sbas_ps_v.csv",
               dsc=D1 + "/sbas/Busan_Mandeok_Centum_DSC/Busan_Mandeok_Centum_DSC_sbas_ps_v.csv"),
    "사상": dict(asc_region="Busan_Sasang_Hadan", snwe=(35.1294, 35.1664, 128.9677, 129.0049),
               asc=CL + "/regions/busan/sbas/sasang_hadan/Busan_Sasang_Hadan_sbas_ps_v.csv",
               dsc=D1 + "/sbas/Busan_Sasang_Hadan_DSC/Busan_Sasang_Hadan_DSC_sbas_ps_v.csv"),
    "강동": dict(asc_region="Seoul_Gangdong", snwe=(37.5097, 37.5840, 127.1033, 127.1994),
               asc=CL + "/regions/seoul/sbas/gangdong/Seoul_Gangdong_sbas_ps_v.csv",
               dsc=D1 + "/sbas/Seoul_Gangdong_DSC/Seoul_Gangdong_DSC_sbas_ps_v.csv"),
    "서대문": dict(asc_region="Seoul_Seodaemun", snwe=(37.5407, 37.5977, 126.8844, 126.9636),
                asc=CL + "/regions/seoul/sbas/seodaemun/Seoul_Seodaemun_sbas_ps_v.csv",
                dsc=D1 + "/sbas/Seoul_Seodaemun_DSC/Seoul_Seodaemun_DSC_sbas_ps_v.csv"),
    "광명": dict(asc_region="Gyeonggi_Gwangmyeong", snwe=(37.3812, 37.4442, 126.8410, 126.9181),
               asc=CL + "/regions/gyeonggi/sbas/Gyeonggi_Gwangmyeong_sbas_ps_v.csv",
               dsc=D1 + "/sbas/Gyeonggi_Gwangmyeong_DSC/Gyeonggi_Gwangmyeong_DSC_sbas_ps_v.csv"),
}


def ymd2yr(s):
    from datetime import date
    y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    return y + (date(y, m, d).timetuple().tm_yday - 1) / (366.0 if y % 4 == 0 else 365.0)


def load(csv, region):
    """swept_loader 와 같은 파싱(언랩억제 포함). disp 는 침하 양수 규약."""
    e = SL.load_sbas_from_csv(csv, region)
    return e


def cellize(lon, lat, snwe):
    S, N, W, E = snwe
    gi = np.floor((lat - S) / GRID).astype(np.int64)
    gj = np.floor((lon - W) / GRID).astype(np.int64)
    return gi * 1000000 + gj


def agg(key, disp, tcoh, lon, lat):
    """셀별 중앙값 집계. 반환: 정렬된 셀키, disp(셀×에폭), tcoh, 대표 lon/lat"""
    o = np.argsort(key, kind="stable")
    k = key[o]; d = disp[o]; tc = tcoh[o]; lo = lon[o]; la = lat[o]
    uk, st = np.unique(k, return_index=True)
    ed = np.r_[st[1:], len(k)]
    D = np.empty((len(uk), d.shape[1]), np.float64)
    T = np.empty(len(uk)); LO = np.empty(len(uk)); LA = np.empty(len(uk))
    for i, (a, b) in enumerate(zip(st, ed)):
        with np.errstate(all="ignore"):
            D[i] = np.nanmedian(d[a:b], axis=0)
        T[i] = np.nanmedian(tc[a:b]); LO[i] = np.nanmedian(lo[a:b]); LA[i] = np.nanmedian(la[a:b])
    return uk, D, T, LO, LA


def interp_asc(Da, ya, yt, gap_max_yr):
    """ASC 시계열을 목표 날짜 yt 로 선형보간. 앞뒤 관측이 멀면 NaN."""
    out = np.full((Da.shape[0], len(yt)), np.nan)
    ok = np.zeros(len(yt), bool)
    for j, t in enumerate(yt):
        i1 = np.searchsorted(ya, t)
        i0 = i1 - 1
        if i1 >= len(ya):
            if abs(ya[-1] - t) <= gap_max_yr:
                out[:, j] = Da[:, -1]; ok[j] = True
            continue
        if i0 < 0:
            if abs(ya[0] - t) <= gap_max_yr:
                out[:, j] = Da[:, 0]; ok[j] = True
            continue
        if (ya[i1] - ya[i0]) > 2 * gap_max_yr:
            continue
        w = (t - ya[i0]) / max(ya[i1] - ya[i0], 1e-9)
        out[:, j] = Da[:, i0] * (1 - w) + Da[:, i1] * w
        ok[j] = True
    return out, ok


def vel_of(D, yrs):
    """시계열 선형회귀 기울기(mm/yr). NaN 은 0 으로 채워 최소제곱."""
    A = np.vstack([yrs, np.ones_like(yrs)]).T
    return np.linalg.lstsq(A, np.nan_to_num(D, nan=0.0).T, rcond=None)[0][0]


def save_csv(path, lon, lat, D, dates, tcoh, inc):
    cols = {"Longitude": lon, "Latitude": lat, "incidence": np.full(len(lon), inc),
            "velocity": vel_of(D, np.array([ymd2yr(s) for s in dates])), "tcoh": tcoh}
    df = pd.DataFrame(cols)
    for j, s in enumerate(dates):
        df["D" + s] = D[:, j]
    df["is_ref"] = 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, float_format="%.4f")
    return len(df)


def run(kr, G):
    R = REG[kr]
    ga, gd = G.get("%s|ASC" % kr), G.get("%s|DSC" % kr)
    if not (ga and gd):
        print("  ★%s 기하 미실측 - 건너뜀" % kr); return None
    ta, td = ga["inc"], gd["inc"]
    aa, ad = ga["azi_g2s"], gd["azi_g2s"]
    ca, cd = np.cos(ta * RAD), np.cos(td * RAD)
    ea = np.sin(aa * RAD) * np.sin(ta * RAD)
    ed = np.sin(ad * RAD) * np.sin(td * RAD)
    det = ca * ed - cd * ea
    print("  기하 ASC θ%.2f° α%.1f° (c=%.3f e=%+.3f) · DSC θ%.2f° α%.1f° (c=%.3f e=%+.3f) · det=%.4f"
          % (ta, aa, ca, ea, td, ad, cd, ed, det))
    if abs(det) < 0.3:
        print("  ★det 이 작아 분해가 불안정 - 건너뜀"); return None

    A = load(R["asc"], R["asc_region"])
    Dc = load(R["dsc"], R["asc_region"])          # α·AOI 메타는 ASC 지역명 기준
    ya, yd = np.asarray(A["years"], float), np.asarray(Dc["years"], float)
    lo0, hi0 = max(ya[0], yd[0]), min(ya[-1], yd[-1])
    selD = (yd >= lo0) & (yd <= hi0)
    if selD.sum() < 10:
        print("  ★중복 에폭 %d 개 - 건너뜀" % selD.sum()); return None

    # 공간 정렬
    S, N, W, E = R["snwe"]
    def clip(e):
        m = (e["lat"] >= S) & (e["lat"] <= N) & (e["lon"] >= W) & (e["lon"] <= E)
        return m
    ma, md = clip(A), clip(Dc)
    ka = cellize(A["lon"][ma], A["lat"][ma], R["snwe"])
    kd = cellize(Dc["lon"][md], Dc["lat"][md], R["snwe"])
    uka, DA, TA, LOA, LAA = agg(ka, A["disp"][ma], A["tcoh"][ma], A["lon"][ma], A["lat"][ma])
    ukd, DD, TD, LOD, LAD = agg(kd, Dc["disp"][md][:, selD], Dc["tcoh"][md], Dc["lon"][md], Dc["lat"][md])
    com, ia, id_ = np.intersect1d(uka, ukd, return_indices=True)
    print("  격자 %.0f m · ASC 셀 %d · DSC 셀 %d · 공통 %d" % (GRID * 111000, len(uka), len(ukd), len(com)))
    if len(com) < MIN_CELL:
        print("  ★공통 셀 부족 - 건너뜀"); return None
    DA, TA = DA[ia], TA[ia]
    DD, TD, LO, LA = DD[id_], TD[id_], LOD[id_], LAD[id_]

    # 시간 정렬 - DSC 관측일에 ASC 보간
    yt = yd[selD]
    dts = [d[1:] if str(d).startswith("D") else str(d) for d in np.asarray(Dc["dates"])[selD]]
    DAi, ok = interp_asc(DA, ya, yt, GAP_MAX / DAYS)
    print("  중복기간 %.3f~%.3f · DSC 에폭 %d · ASC 보간가능 %d (gap≤%d일)"
          % (lo0, hi0, len(yt), ok.sum(), GAP_MAX))
    if ok.sum() < 10:
        print("  ★보간 가능 에폭 부족 - 건너뜀"); return None
    yt, dts = yt[ok], [d for d, o in zip(dts, ok) if o]
    DAi, DD = DAi[:, ok], DD[:, ok]

    # 분해 - 물리 LOS(위성방향 +)로 되돌려 계산
    la_, ld_ = -DAi, -DD
    UP = (la_ * ed - ld_ * ea) / det          # 상향 양수
    EW = (ld_ * ca - la_ * cd) / det          # 동향 양수
    # 저장은 기존 규약(침하 양수)에 맞춰 부호 반전
    UPs, EWs = -UP, -EW
    # 각 셀의 첫 에폭을 0 으로 (기준점이 궤도마다 달라 남는 상수 offset 제거)
    for Z in (UPs, EWs):
        Z -= Z[:, :1]
    tc = np.minimum(TA, TD)

    out = {}
    for nm, Z, inc in (("ASC_LOS", DAi - DAi[:, :1], ta), ("DSC_LOS", DD - DD[:, :1], td),
                       ("UP", UPs, 0.0), ("EW", EWs, 0.0)):
        reg = "%s_%s" % (R["asc_region"], nm)
        p = os.path.join(OUTD, kr, "%s_sbas_ps_v.csv" % reg)
        n = save_csv(p, LO, LA, Z, dts, tc, inc)
        out[nm] = dict(csv=p, region=reg, n=n)
        print("    %-8s → %s (%d 셀 × %d 에폭)" % (nm, os.path.basename(p), n, len(dts)))
    return dict(kr=kr, asc_region=R["asc_region"], snwe=list(R["snwe"]),
                geom=dict(inc_a=ta, inc_d=td, az_a=aa, az_d=ad, ca=ca, cd=cd, ea=ea, ed=ed, det=det),
                overlap=[float(lo0), float(hi0)], n_ep=len(dts), dates=dts,
                n_cell=int(len(com)), sets=out)


def main():
    G = json.load(open(os.path.join(D1, "analysis", "geom_probe.json")))
    want = [a for a in sys.argv[1:] if a in REG] or list(REG)
    res = {}
    for kr in want:
        print("\n■ %s" % kr)
        r = run(kr, G)
        if r:
            res[kr] = r
    p = os.path.join(D1, "analysis", "decomp_build.json")
    json.dump(res, open(p, "w"), ensure_ascii=False, indent=1)
    print("\n→ %s (%d 지역)" % (p, len(res)))


if __name__ == "__main__":
    main()
