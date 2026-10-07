# -*- coding: utf-8 -*-
"""(5) 백테스팅 — 사고 리스트 = 정답. 사고 이전 시점(asof)으로 알람 클러스터가 사고좌표
버퍼 내 '시간 선행'했는지 판정. 판정단위=DBSCAN 클러스터. KPI: 정탐수·평균리드타임·오탐수.
⚠️ 임계치 잠정 — recall 우선. 후보 임계치 비교는 CONFIG 조정으로 수행(최종 선택=사용자)."""
import os; os.environ.pop("PYTHONPATH", None)
import datetime as dt
import numpy as np, pandas as pd
import pyproj
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir(); os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]

from pcfg import PATHS, EVENTS, ALARM
from aoi import load_aoi
import fuse_cluster as fc

_TRM = pyproj.Transformer.from_crs(4326, 32652, always_xy=True)
_LV = {"관심": 0, "주의": 1, "경보": 2}
SCAN_OFFSETS = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0]   # asof = event - off(년). 최초 선행 탐색(≈6개월 해상)


def _md(df):
    """tabulate 비의존 마크다운 테이블."""
    cols = list(df.columns)
    rows = ["| " + " | ".join(map(str, cols)) + " |",
            "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        rows.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(rows)


def _year(datestr):
    d = dt.date.fromisoformat(datestr); return d.year + (d - dt.date(d.year, 1, 1)).days / 365.25


def detect(region, asof_year, sink_lon, sink_lat, buffer_m):
    """asof 시점 알람 클러스터 중 사고좌표 buffer_m 내 멤버가 있으면 탐지. 반환 dict|None."""
    cl, elev = fc.cluster_alarms_cached(region, asof_year)
    if elev is None or len(elev) == 0 or sink_lon is None:
        return {"detected": False, "n_alarm_clusters": (0 if cl is None else len(cl))}
    sx, sy = _TRM.transform(sink_lon, sink_lat)
    dist = np.hypot(elev["x_m"].to_numpy() - sx, elev["y_m"].to_numpy() - sy)
    near = elev[dist <= buffer_m]
    res = {"detected": len(near) > 0, "n_alarm_clusters": len(cl),
           "nearest_alarm_m": round(float(dist.min()), 1)}
    if len(near):
        lvl = ALARM["level_by_score"][min(int(near["score"].max()), 2)]
        cids = set(near["cluster"].unique())
        leads = cl[cl["cluster"].isin(cids)]["min_lead_days"].dropna()
        res.update({"alarm": lvl, "invvel_accel": bool(near["invvel_accel"].any()),
                    "tf_min_lead_days": (float(leads.min()) if len(leads) else np.nan),
                    "top_basis": near["basis"].mode().iat[0]})
    return res


def backtest_event(region, info):
    """양성: 사고 선행탐지 + 리드타임 스캔. 음성: 알람클러스터수(FP)."""
    ev = EVENTS.get(region, {})
    sink_lon, sink_lat = info.get("sink_lon"), info.get("sink_lat")
    buf = info.get("buffer_m", 200)
    typ = info.get("type", "unknown")
    row = {"region": region, "aoi": info["aoi_name"], "type": typ,
           "event_date": info.get("event_date"), "sink_lon": sink_lon, "sink_lat": sink_lat,
           "buffer_m": buf}

    if typ == "negative" or not info.get("event_date") or sink_lon is None:
        # 음성/발생점없음: 기간말 시점 알람 클러스터 수 = FP 지표
        asof = info["period"][1] if info.get("period") else None
        d = detect(region, asof, sink_lon, sink_lat, buf)
        row.update({"detected": "", "alarm": "", "lead_days": "",
                    "n_alarm_clusters": d.get("n_alarm_clusters", 0),
                    "note": "음성=FP기준선(발생점 없음)" if typ == "negative" else "발생점/일자 미상"})
        return row

    ev_year = _year(info["event_date"])
    # 사고 시점 탐지
    base = detect(region, ev_year, sink_lon, sink_lat, buf)
    # 리드타임: 과거로 스캔하며 최초 선행 탐지 offset 탐색
    earliest_off = 0.0
    scan_log = []
    for off in SCAN_OFFSETS:
        d = detect(region, ev_year - off, sink_lon, sink_lat, buf)
        scan_log.append((off, d["detected"]))
        if d["detected"]:
            earliest_off = off
        else:
            if off > 0:      # 더 과거는 데이터부족/신호없음 → 중단
                break
    lead = round(earliest_off * 365.25) if base["detected"] else 0
    row.update({
        "detected": base["detected"],
        "alarm": base.get("alarm", ""),
        "lead_days": lead,
        "nearest_alarm_m": base.get("nearest_alarm_m", np.nan),
        "n_alarm_clusters": base.get("n_alarm_clusters", 0),
        "invvel_accel": base.get("invvel_accel", False),
        "tf_min_lead_days": base.get("tf_min_lead_days", np.nan),
        "top_basis": base.get("top_basis", "-"),
        "note": "TP" if base["detected"] else "미탐(FN)",
    })
    return row


def subsidence_in_aoi(aoi):
    """지오코딩 사고리스트 중 각 AOI bbox·기간 내 정밀좌표 사고 → 선행탐지(보강 라벨)."""
    df = pd.read_csv(PATHS["subsidence"], encoding="utf-8-sig")
    df = df[df["lat"].notna() & df["geocodeType"].isin(["parcel", "road", "kakao_addr", "kakao_keyword"])].copy()
    df["y"] = pd.to_datetime(df["sagoDate"], format="%Y%m%d", errors="coerce").dt.year \
        + (pd.to_datetime(df["sagoDate"], format="%Y%m%d", errors="coerce").dt.dayofyear) / 365.25
    rows = []
    for region, info in aoi.items():
        b = info["bbox"]; per = info.get("period")
        m = ((df["lat"] >= b["S"]) & (df["lat"] <= b["N"]) &
             (df["lon"] >= b["W"]) & (df["lon"] <= b["E"]))
        sub = df[m]
        for _, a in sub.iterrows():
            ay = a["y"]
            if per and not (per[0] <= ay <= per[1] + 0.3):
                continue
            d = detect(region, ay, a["lon"], a["lat"], info.get("buffer_m", 200))
            rows.append({"region": region, "sagoNo": a["sagoNo"], "sagoDate": a["sagoDate"],
                         "lon": round(a["lon"], 5), "lat": round(a["lat"], 5),
                         "detected": d["detected"], "alarm": d.get("alarm", ""),
                         "nearest_alarm_m": d.get("nearest_alarm_m", np.nan)})
    return pd.DataFrame(rows)


def main():
    aoi = load_aoi()
    print("[백테스트] 7개 AOI 사고 케이스 스터디 …")
    case_rows = [backtest_event(r, info) for r, info in aoi.items()]
    cases = pd.DataFrame(case_rows)
    cases.to_csv(os.path.join(PATHS["backtest"], "case_study_table.csv"),
                 index=False, encoding="utf-8-sig")

    print("[백테스트] AOI 내 지오코딩 사고리스트 선행탐지 …")
    try:
        sub = subsidence_in_aoi(aoi)
        sub.to_csv(os.path.join(PATHS["backtest"], "subsidence_in_aoi_backtest.csv"),
                   index=False, encoding="utf-8-sig")
    except Exception as e:
        sub = pd.DataFrame(); print("  (사고리스트 백테스트 skip:", e, ")")

    pos = cases[cases["type"] == "positive"]
    neg = cases[cases["type"] == "negative"]
    tp = int((pos["detected"] == True).sum()); npos = len(pos)
    leads = pos.loc[pos["detected"] == True, "lead_days"].astype(float)
    fp_neg = int(neg["n_alarm_clusters"].sum())

    lines = []
    lines.append("# KPI 요약 — 싱크홀 사전 알람 백테스트\n")
    lines.append(f"- **정탐(TP): {tp}/{npos} 양성 사례** (사고좌표 {int(pos['buffer_m'].iloc[0]) if npos else 200}m 버퍼 내 알람 클러스터 선행)")
    lines.append(f"- **평균 리드타임: {leads.mean():.0f}일** (최소 {leads.min():.0f} / 최대 {leads.max():.0f}), 스캔해상 ≈6개월" if len(leads) else "- 평균 리드타임: (정탐 없음)")
    lines.append(f"- **오탐(FP) 지표: 음성 AOI 알람 클러스터 총 {fp_neg}개** (송도·만덕, 발생 없음). 침하≠붕괴 baseline.")
    lines.append(f"- 양성 AOI 알람 클러스터 총 {int(pos['n_alarm_clusters'].sum())}개 (사고점 외 지역 포함 — FP 상한 참고).")
    if len(sub):
        sd = int((sub["detected"] == True).sum())
        lines.append(f"- AOI 내 지오코딩 사고리스트 {len(sub)}건 중 선행탐지 {sd}건({100*sd/max(1,len(sub)):.0f}%).")
    lines.append("\n## 케이스 스터디 테이블\n")
    show = cases[["aoi", "type", "event_date", "detected", "alarm", "lead_days",
                  "n_alarm_clusters", "note"]]
    lines.append(_md(show))
    lines.append("\n## 주의 (잠정)")
    lines.append("- 임계치·α·버퍼·DBSCAN(eps/min_samples)·역속도 R²는 모두 **백테스팅 확정 전 잠정값**(pcfg/CONFIG).")
    lines.append("- 리드타임은 6개월 해상 역스캔의 하한(더 세밀히 하면 증가 가능).")
    lines.append("- FP(경보 다수)는 임계치 상향·클러스터 규모게이팅으로 조정 대상 — 후보값은 CONFIG에서 스윕.")
    lines.append("- (B)지하수 방아쇠 미반영 시 순수 InSAR+지반 결과. GIMS 연동 시 동행성으로 FP 저감 기대.")
    with open(os.path.join(PATHS["backtest"], "kpi_summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n" + "\n".join(lines[:6]))
    print("\n저장: backtest/case_study_table.csv, kpi_summary.md",
          ", subsidence_in_aoi_backtest.csv" if len(sub) else "")


if __name__ == "__main__":
    main()
