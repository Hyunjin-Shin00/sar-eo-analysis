"""사건 후 첫 SAR 취득까지 걸리는 시간의 분포 — 「지바의 +10.2 h 를 일반화할 수 있는가」에 답한다.

방법
  · ASF 에서 대상 AOI 의 Sentinel-1 취득 이력을 최근 1년치 전부 받는다.
  · 사건이 언제 터질지 모르므로, **1시간 간격의 가상 사건 시각**을 1년에 걸쳐 놓고
    각 시각에서 다음 취득까지의 대기시간을 잰다. 그 분포가 곧 기대 리드타임이다.
  · 궤도(track)별로도 나눠, 몇 개 궤도가 실제로 이 지점을 덮는지 본다.
"""
import os, sys, json, pathlib, datetime as dt
os.environ.pop("PYTHONPATH", None)
import numpy as np, requests

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
OUT = ROOT/"outputs"/"market"
API = "https://api.daac.asf.alaska.edu/services/search/param"
AOI = dict(chiba=(140.100, 35.470, 140.500, 35.720))
START, END = "2025-09-01", "2026-09-18"


def fetch(bbox):
    wkt = ("POLYGON(({0} {1},{2} {1},{2} {3},{0} {3},{0} {1}))"
           .format(bbox[0], bbox[1], bbox[2], bbox[3]))
    r = requests.get(API, params=dict(
        intersectsWith=wkt, platform="Sentinel-1", processingLevel="GRD_HD",
        beamMode="IW", start=START, end=END, output="jsonlite"), timeout=180)
    r.raise_for_status()
    return r.json()["results"]


def main():
    for key, bbox in AOI.items():
        res = fetch(bbox)
        # 한 번의 통과가 여러 프레임으로 쪼개져 오므로, 5분 안의 것은 같은 통과로 묶는다.
        # 묶지 않으면 취득 기회가 실제보다 2~3배로 부풀려진다.
        seen, rows = [], []
        for x in sorted(res, key=lambda z: z["startTime"]):
            t = dt.datetime.fromisoformat(x["startTime"].replace("Z", "+00:00"))
            if seen and (t - seen[-1]).total_seconds() < 300: continue
            seen.append(t)
            rows.append((t, int(x.get("path") or 0), x.get("flightDirection", "")[:4],
                         x["granuleName"][:3]))
        ts = np.array([r[0].timestamp() for r in rows])
        print(f"── {key}  {START} ~ {END}  ·  통과 {len(rows)}회 (프레임 {len(res)}건을 통과 단위로 묶음)")
        import collections
        bytrack = collections.Counter((r[1], r[2]) for r in rows)
        print("   궤도별:", ", ".join(f"t{p}{d} {n}건" for (p, d), n in sorted(bytrack.items())))
        print("   위성별:", dict(collections.Counter(r[3] for r in rows)))

        # 1시간 간격 가상 사건 → 다음 취득까지 대기시간
        t0, t1 = ts.min(), ts.max()
        probe = np.arange(t0, t1 - 86400*14, 3600.0)
        idx = np.searchsorted(ts, probe, side="right")
        wait = (ts[np.clip(idx, 0, len(ts)-1)] - probe)/3600.0
        wait = wait[idx < len(ts)]
        q = np.percentile(wait, [50, 75, 90, 95, 100])
        print(f"   사건 후 첫 취득까지 대기시간 — 중앙 {q[0]:.1f} h · "
              f"75 % {q[1]:.1f} h · 90 % {q[2]:.1f} h · 95 % {q[3]:.1f} h · 최악 {q[4]:.1f} h")
        for h in (6, 12, 24, 48, 72):
            print(f"      {h:3d} 시간 안에 취득할 확률 {100*(wait <= h).mean():5.1f} %")
        gaps = np.diff(ts)/3600.0
        print(f"   연속 취득 간격 — 중앙 {np.median(gaps):.1f} h · 최대 {gaps.max():.1f} h")
        (OUT/f"revisit_{key}.json").write_text(json.dumps(dict(
            window=[START, END], n=len(rows),
            tracks={f"t{p}{d}": n for (p, d), n in sorted(bytrack.items())},
            wait_median_h=round(float(q[0]), 1), wait_p90_h=round(float(q[2]), 1),
            wait_max_h=round(float(q[4]), 1),
            within={f"{h}h": round(float(100*(wait <= h).mean()), 1) for h in (6, 12, 24, 48, 72)},
            gap_median_h=round(float(np.median(gaps)), 1)), ensure_ascii=False, indent=1))
        print(f"\n저장 {OUT}/revisit_{key}.json")


if __name__ == "__main__":
    main()
