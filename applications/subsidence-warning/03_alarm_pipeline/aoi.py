# -*- coding: utf-8 -*-
"""AOI.xlsx → region별 {bbox(S,N,W,E), 사고점, 사고일, 기준점, 기간}. events.py로 사고좌표/일자 보강."""
import os; os.environ.pop("PYTHONPATH", None)
import re
import pandas as pd
from pcfg import PATHS, AOI_TO_REGION, EVENTS


def _f(s):
    return float(str(s).strip())


def _parse_pair(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    m = re.findall(r"-?\d+\.?\d*", str(s))
    return (float(m[0]), float(m[1])) if len(m) >= 2 else None   # (lat, lon)


def _parse_period(s):
    """'2019.01~2026.04' → (2019.083, 2026.292) 소수연."""
    m = re.findall(r"(\d{4})\.(\d{2})", str(s))
    if len(m) < 2:
        return None
    (y0, m0), (y1, m1) = m[0], m[1]
    return (int(y0) + (int(m0) - 1) / 12.0, int(y1) + (int(m1) - 1) / 12.0)


def load_aoi():
    df = pd.read_excel(PATHS["aoi_xlsx"])
    out = {}
    for _, r in df.iterrows():
        name = str(r["AOI"]).strip()
        region = AOI_TO_REGION.get(name)
        if region is None:
            continue
        s, n, w, e = [_f(x) for x in re.findall(r"-?\d+\.?\d*", str(r["SNWE"]))[:4]]
        sink = _parse_pair(r.get("싱크홀 위경도"))          # (lat, lon) or None
        ref = _parse_pair(r.get("기준점 위경도"))
        ev = EVENTS.get(region, {})
        out[region] = {
            "region": region, "aoi_name": name,
            "bbox": {"S": s, "N": n, "W": w, "E": e},   # lat/lon deg
            "sink_lat": sink[0] if sink else ev.get("lat"),
            "sink_lon": sink[1] if sink else ev.get("lon"),
            "event_date": ev.get("event_date"),
            "type": ev.get("type", "unknown"),
            "buffer_m": ev.get("buffer_m", 200),
            "ref_lat": ref[0] if ref else None, "ref_lon": ref[1] if ref else None,
            "period": _parse_period(r.get("기간")),
        }
    return out


if __name__ == "__main__":
    a = load_aoi()
    for reg, d in a.items():
        print(f"{reg:24s} bbox={d['bbox']} type={d['type']} "
              f"sink=({d['sink_lat']},{d['sink_lon']}) date={d['event_date']} period={d['period']}")
