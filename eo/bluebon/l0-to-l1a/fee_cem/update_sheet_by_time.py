#!/usr/bin/env python3
"""
update_sheet_by_time.py — push FEE/CEM into the Bluebon Mission sheet,
matching each captured folder to the row whose Capture Start Time (column E)
is closest to the folder's datetime (parsed from YYMMDD_HHMMSS folder name).

Inputs (produced by process-from-drive.sh):
  - datetime_capture_map.csv  : folder,datetime,capture
  - fee_cee_summary.csv       : capture,FEE,CEM

Matching:
  1. parse folder datetime (YYYY-MM-DDTHH:MM:SS)
  2. consider only sheet rows whose date (Y-M-D part of column E) matches
  3. pick the row with the smallest |E_time - folder_time|
  4. skip the row if column AD already has a value
"""

import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    sys.exit("Install dependencies first:  pip install gspread google-auth")

SCRIPT_DIR = Path(__file__).resolve().parent

SPREADSHEET_ID = os.environ.get("BLUEBON_SHEET_ID", "")
SHEET_TAB     = "Mission"
DATE_COL_IX   = 5    # E
WRITE_COL     = "AD"
WRITE_COL_IX  = 30

DATETIME_CSV = SCRIPT_DIR / "datetime_capture_map.csv"
SUMMARY_CSV  = SCRIPT_DIR / "fee_cee_summary.csv"
CREDENTIALS  = Path(os.environ.get(
    "GSPREAD_CREDENTIALS",
    SCRIPT_DIR / "ee-hyunjin-f97764a9f222.json",
))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


_DT_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)")


def parse_sheet_dt(s: str):
    """Parse '2026-04-29T04:09:31.923(1777435771923)' or similar → datetime."""
    if not s:
        return None
    m = _DT_RE.match(s.strip())
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1))
    except ValueError:
        return None


def find_closest_row(dates_col, target_dt):
    """
    Return (1-based row, |delta seconds|, sheet timestamp string)
    for the row on the same date with the smallest time difference.
    Returns (None, None, None) if no row on that date.
    """
    best = None
    for i, d in enumerate(dates_col, start=1):
        dt = parse_sheet_dt(d)
        if dt is None or dt.date() != target_dt.date():
            continue
        delta = abs((dt - target_dt).total_seconds())
        if best is None or delta < best[1]:
            best = (i, delta, d.strip())
    return best if best else (None, None, None)


def normalize_series(s: str) -> str:
    if not s:
        return ""
    return ",".join(p.strip() for p in s.split(","))


def main():
    if not CREDENTIALS.exists():
        sys.exit(f"Service-account JSON not found: {CREDENTIALS}")
    for p in (DATETIME_CSV, SUMMARY_CSV):
        if not p.exists():
            sys.exit(f"Missing {p.name} — run process-from-drive.sh first")

    creds = Credentials.from_service_account_file(str(CREDENTIALS), scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_TAB)

    dates_col   = ws.col_values(DATE_COL_IX)
    existing_col = ws.col_values(WRITE_COL_IX)

    with DATETIME_CSV.open(newline="") as f:
        mapping = list(csv.DictReader(f))
    with SUMMARY_CSV.open(newline="") as f:
        summary = {r["capture"]: r for r in csv.DictReader(f)}

    updates, misses = [], []
    for m in mapping:
        capture = m["capture"]
        s = summary.get(capture)
        if not s:
            continue  # this folder wasn't (re)processed in this run
        fee = normalize_series(s.get("FEE", ""))
        cem = normalize_series(s.get("CEM", ""))
        if not fee and not cem:
            misses.append((capture, "FEE/CEM empty"))
            continue

        try:
            target_dt = datetime.fromisoformat(m["datetime"])
        except ValueError:
            misses.append((capture, f"bad datetime: {m['datetime']}"))
            continue

        row, delta, matched = find_closest_row(dates_col, target_dt)
        if row is None:
            misses.append((capture, f"no row on date {target_dt.date()} (datetime={m['datetime']})"))
            continue

        existing = existing_col[row - 1].strip() if row - 1 < len(existing_col) else ""
        if existing:
            print(f"  row {row:>3}  {capture}  --  skip (AD already filled)")
            continue

        value = f"FEE: {fee}\nCEM: {cem}"
        updates.append({"range": f"{WRITE_COL}{row}", "values": [[value]]})
        print(f"  row {row:>3}  {capture}  ->  sheet={matched}  (Δ={int(delta)}s)")

    if updates:
        ws.batch_update(updates, value_input_option="RAW")
        print(f"\nUpdated {len(updates)} row(s) in '{SHEET_TAB}'.")
    else:
        print("\nNothing to update.")

    if misses:
        print("\nUnmatched:")
        for capture, reason in misses:
            print(f"  - {capture}: {reason}")
        sys.exit(2)


if __name__ == "__main__":
    main()
