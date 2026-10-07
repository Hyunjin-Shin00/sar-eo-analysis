#!/usr/bin/env python
"""
Query the Copernicus Data Space Ecosystem (CDSE) OData catalogue for REAL
Sentinel-1 acquisitions over each railway disaster AOI.

No authentication is required for catalogue *search* (only for download).
We never invent acquisitions: every row written comes back from the catalogue.

Output: data/sar_acquisitions_sentinel1.csv  (raw, one row per catalogue item)
"""
import csv
import json
import os
import sys
import time
import datetime as dt
from urllib.parse import quote

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ODATA = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
JST = dt.timezone(dt.timedelta(hours=9))
UTC = dt.timezone.utc

# Product types we keep. GRD = amplitude/flood mapping, SLC = InSAR/coherence.
KEEP_TYPES = ("IW_GRDH", "IW_SLC", "EW_GRDH", "EW_SLC", "SM_GRDH", "SM_SLC")


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build_filter(lon, lat, t0, t1, collection="SENTINEL-1"):
    pt = f"geography'SRID=4326;POINT({lon} {lat})'"
    return (
        f"Collection/Name eq '{collection}' "
        f"and OData.CSC.Intersects(area={pt}) "
        f"and ContentDate/Start gt {iso(t0)} "
        f"and ContentDate/Start lt {iso(t1)}"
    )


def fetch_all(flt, expand_attrs=True, page=1000, max_pages=20):
    """Page through the OData result set."""
    out = []
    url = (
        f"{ODATA}?$filter={quote(flt, safe='')}"
        f"&$orderby={quote('ContentDate/Start asc')}"
        f"&$top={page}"
    )
    if expand_attrs:
        url += "&$expand=Attributes"
    for _ in range(max_pages):
        for attempt in range(4):
            try:
                r = requests.get(url, timeout=180)
                if r.status_code == 200:
                    break
                time.sleep(4 * (attempt + 1))
            except requests.RequestException:
                time.sleep(4 * (attempt + 1))
        else:
            raise RuntimeError(f"CDSE query failed: {url[:180]}")
        js = r.json()
        out.extend(js.get("value", []))
        nxt = js.get("@odata.nextLink")
        if not nxt:
            break
        url = nxt
    return out


def attr_map(item):
    d = {}
    for a in item.get("Attributes") or []:
        d[a.get("Name")] = a.get("Value")
    return d


def parse_item(item, event):
    name = item.get("Name", "")
    ptype = None
    for k in KEEP_TYPES:
        if k in name:
            ptype = k
            break
    if ptype is None:
        return None

    a = attr_map(item)
    start = item["ContentDate"]["Start"]
    # CDSE returns e.g. 2024-07-25T20:51:04.296000Z
    t_utc = dt.datetime.strptime(start[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    t_jst = t_utc.astimezone(JST)
    ev = event["dt_utc"]
    delta_h = (t_utc - ev).total_seconds() / 3600.0

    sat = name[:3]  # S1A / S1B / S1C / S1D
    mode = name[4:6] if len(name) > 6 else a.get("operationalMode", "")
    pol = name[14:18] if len(name) > 18 else ""

    return {
        "event_id": event["event_id"],
        "provider": "ESA / Copernicus (CDSE)",
        "platform": "Sentinel-1",
        "satellite": {"S1A": "Sentinel-1A", "S1B": "Sentinel-1B",
                      "S1C": "Sentinel-1C", "S1D": "Sentinel-1D"}.get(sat, sat),
        "sensor": "C-SAR",
        "band": "C",
        "acquisition_datetime_utc": t_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "acquisition_datetime_jst": t_jst.strftime("%Y-%m-%d %H:%M:%S"),
        "delta_from_event_hours": round(delta_h, 2),
        "pre_or_post": "post" if delta_h >= 0 else "pre",
        "acquisition_mode": ptype,
        "polarization": a.get("polarisationChannels", pol).replace("&", "+"),
        "orbit_direction": a.get("orbitDirection", ""),
        "relative_orbit": a.get("relativeOrbitNumber", ""),
        "absolute_orbit": a.get("orbitNumber", ""),
        "catalog_item_id": item.get("Id", ""),
        "catalog_name": name,
        "footprint_wkt": (item.get("Footprint") or "").replace("\n", " "),
        "online": item.get("Online", ""),
    }


def main():
    with open(os.path.join(ROOT, "data", "events_query.json")) as f:
        events = json.load(f)

    rows = []
    for e in events:
        e["dt_utc"] = dt.datetime.strptime(
            e["event_datetime_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        # Sentinel-1 only exists from 2014-10 onward
        if e["dt_utc"].year < 2014:
            print(f"[skip S1] {e['event_id']} pre-dates Sentinel-1", file=sys.stderr)
            continue
        win = e.get("window_days", 90)
        t0 = e["dt_utc"] - dt.timedelta(days=win)
        t1 = e["dt_utc"] + dt.timedelta(days=win)
        flt = build_filter(e["lon"], e["lat"], t0, t1)
        items = fetch_all(flt)
        n = 0
        for it in items:
            p = parse_item(it, e)
            if p:
                rows.append(p)
                n += 1
        print(f"[S1] {e['event_id']:22s} {n:4d} GRD/SLC products "
              f"(+-{win}d @ {e['lat']:.4f},{e['lon']:.4f})", file=sys.stderr)
        time.sleep(1)

    out = os.path.join(ROOT, "data", "sar_acquisitions_sentinel1.csv")
    cols = list(rows[0].keys())
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
