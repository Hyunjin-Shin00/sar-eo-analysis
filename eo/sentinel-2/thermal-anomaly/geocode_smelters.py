# -*- coding: utf-8 -*-
"""
Geocode copper smelters and write coordinates back to Excel.

Changes per request:
- Data rows start at Excel row **2** (1-indexed). Row 1 is header.
- Use columns 1~3 (Country, Smelters, Operator/Owner(s)) for geocoding.
- (Optional fallback) if present, also consider column 9 (Short Remarks).
- Write **Latitude** to column **9** and **Longitude** to column **10** (1-indexed).
  Existing columns at/after those positions are shifted to the right to preserve data.

Usage (Windows/macOS/Linux):
    pip install pandas geopy openpyxl
    python geocode_smelters.py --input "path/to/smelters.xlsx" --output "path/to/smelters_with_coords.xlsx" --email "you@example.com"

Notes:
- Uses OpenStreetMap Nominatim via geopy with polite rate-limiting.
- A JSON cache avoids repeated lookups for the same row.
"""

import argparse
import json
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

# ----------------------- Helpers -----------------------

def sanitize_name(name: str) -> str:
    """Normalize a smelter/owner string for search."""
    if not isinstance(name, str):
        return ""
    s = name.strip()
    s = re.sub(r"\(.*?\)", "", s)             # remove parenthesis text
    s = re.sub(r"\bsmelter\b", "", s, flags=re.I)
    s = re.sub(r"\brefiner(y)?\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s)
    return s.strip(",; ").strip()

def build_query_candidates(country: str, smelter: str, owner: str, remarks: Optional[str]) -> List[str]:
    """Compose multiple candidate queries (most specific first)."""
    country_s = sanitize_name(country)
    smelter_s = sanitize_name(smelter)
    owner_s = sanitize_name(owner)
    remarks_s = sanitize_name(remarks) if remarks is not None else ""

    cands: List[str] = []
    if smelter_s and owner_s and country_s:
        cands.append(f"{smelter_s}, {owner_s}, {country_s}")
    if smelter_s and country_s:
        cands.append(f"{smelter_s}, {country_s}")
    if owner_s and country_s:
        cands.append(f"{owner_s}, {country_s}")
    if smelter_s:
        cands.append(smelter_s)
    if owner_s:
        cands.append(owner_s)

    # Fallback to remarks if available
    if remarks_s and country_s:
        cands.append(f"{remarks_s}, {country_s}")
    if remarks_s:
        cands.append(remarks_s)

    # De-duplicate while preserving order
    seen = set()
    uniq = []
    for q in cands:
        key = q.lower()
        if key and key not in seen:
            uniq.append(q)
            seen.add(key)
    return uniq

def load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_cache(path: Path, cache: dict):
    try:
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

# ----------------------- Main -----------------------

def insert_columns_for_lat_lon(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure we can place Latitude at col 9 and Longitude at col 10 (1-indexed).
    If the DataFrame has fewer than 8 columns, pad with blanks, then insert new columns
    at positions 8 and 9 (0-indexed). Existing columns at/after those indices are shifted right.
    """
    while len(df.columns) < 8:
        df[f"__empty_{len(df.columns)+1}"] = ""

    cols = list(df.columns)
    # Insert placeholders at 8 and 9
    cols[8:8] = ["Latitude"]
    cols[9:9] = ["Longitude"]
    # Reindex to new order; new cols will be created as empty
    df = df.reindex(columns=cols)
    return df


def main(input_excel: Path, output_excel: Path, cache_path: Path, email_for_user_agent: str, delay: float):
    # Read input Excel entirely (assume row 1 is headers, data from row 2)
    df = pd.read_excel(input_excel)

    # Prepare output structure (insert Latitude at col9, Longitude at col10)
    df = insert_columns_for_lat_lon(df)

    # Map column names (robust to slight name variations)
    def find_col(name_options: List[str]) -> Optional[str]:
        lower_map = {str(c).strip().lower(): c for c in df.columns}
        for opt in name_options:
            key = opt.lower()
            if key in lower_map:
                return lower_map[key]
        return None

    col_country = find_col(["Country"]) or "Country"
    col_smelter = find_col(["Smelters", "Smelter"]) or "Smelters"
    col_owner = find_col(["Operator/Owner(s)", "Operator/Owner", "Owner", "Operator"]) or "Operator/Owner(s)"
    col_remarks = find_col(["Short Remarks", "Remarks", "Notes"])  # optional

    # Prepare geocoder
    ua = f"smelter-geocoder/1.0 ({email_for_user_agent})" if email_for_user_agent else "smelter-geocoder/1.0"
    geolocator = Nominatim(user_agent=ua, timeout=15)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, max_retries=2, error_wait_seconds=3.0)

    cache = load_cache(cache_path)

    # Initialize columns (ensure they exist for assignment by index)
    if "Latitude" not in df.columns:
        df["Latitude"] = None
    if "Longitude" not in df.columns:
        df["Longitude"] = None

    # Only process data rows starting at Excel row 2 → pandas index 1
    for idx in range(1, len(df)):
        country = df.at[idx, col_country] if col_country in df.columns else ""
        smelter = df.at[idx, col_smelter] if col_smelter in df.columns else ""
        owner = df.at[idx, col_owner] if col_owner in df.columns else ""
        remarks = df.at[idx, col_remarks] if col_remarks and col_remarks in df.columns else ""

        candidates = build_query_candidates(country, smelter, owner, remarks)

        cache_key = json.dumps({
            "country": country if pd.notna(country) else "",
            "smelter": smelter if pd.notna(smelter) else "",
            "owner": owner if pd.notna(owner) else "",
            "remarks": remarks if pd.notna(remarks) else "",
        }, ensure_ascii=False)

        got = cache.get(cache_key)
        if not got:
            got = {"lon": None, "lat": None, "query": candidates[0] if candidates else ""}
            for q in candidates:
                try:
                    loc = geocode(q)
                    if loc:
                        got = {"lon": loc.longitude, "lat": loc.latitude, "query": q, "address": loc.address}
                        break
                except Exception:
                    time.sleep(delay)
            cache[cache_key] = got
            save_cache(cache_path, cache)

        # Write results into designated columns
        df.at[idx, "Latitude"] = got.get("lat")
        df.at[idx, "Longitude"] = got.get("lon")

        time.sleep(delay)

    # Write output Excel
    df.to_excel(output_excel, index=False)

    # Also export unresolved subset for follow-up
    unresolved_mask = df.index >= 1
    unresolved_mask &= (df["Latitude"].isna() | df["Longitude"].isna())
    unresolved = df.loc[unresolved_mask].copy()
    unresolved_path = output_excel.with_name(output_excel.stem + "_UNRESOLVED.xlsx")
    unresolved.to_excel(unresolved_path, index=False)

    print(f"Done.\nOutput: {output_excel}\nUnresolved: {unresolved_path}\nCache: {cache_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="Path to input Excel (e.g., smelters.xlsx)")
    p.add_argument("--output", required=True, help="Path to output Excel")
    p.add_argument("--cache", default="geocode_cache.json", help="Path to cache JSON file")
    p.add_argument("--email", default="", help="(Optional) Contact email for Nominatim user agent")
    p.add_argument("--delay", type=float, default=1.0, help="Extra polite delay seconds between requests (>=1.0 recommended)")
    args = p.parse_args()

    main(
        input_excel=Path(args.input).expanduser(),
        output_excel=Path(args.output).expanduser(),
        cache_path=Path(args.cache).expanduser(),
        email_for_user_agent=args.email,
        delay=max(0.8, float(args.delay)),
    )
