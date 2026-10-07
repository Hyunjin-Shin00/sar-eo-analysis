#!/usr/bin/env python3
"""
update_sheet.py — push FEE/CEM values from process-all.sh output into the
Bluebon mission Google Sheet.

Matching rule:
  - column C (Mission Plan/Target)         == target parsed from archive filename
  - column E (Mission Plan/Capture Start Time) startswith date parsed from archive filename
  - write to column AD (Analytics/FEE/CEM Temp) on that row

Inputs (produced by process-all.sh):
  - archive_capture_map.csv : archive -> date / target / capture
  - fee_cee_summary.csv     : capture -> FEE / CEM

Setup (one-time):
  pip install gspread google-auth

  1) https://console.cloud.google.com/ → create a project
  2) Enable "Google Sheets API"
  3) IAM & Admin → Service Accounts → create one → Keys → Add key (JSON)
  4) Save the JSON as `credentials.json` next to this script
     (or export GSPREAD_CREDENTIALS=/path/to/key.json)
  5) Open the spreadsheet in the browser and share it with the service
     account's client_email (found inside the JSON) as Editor.
"""

import csv
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    sys.exit("Install dependencies first:  pip install gspread google-auth")

SCRIPT_DIR = Path(__file__).resolve().parent

SPREADSHEET_ID = os.environ.get("BLUEBON_SHEET_ID", "")
SHEET_TAB     = "Mission"
TARGET_COL_IX = 3   # C
DATE_COL_IX   = 5   # E
WRITE_COL     = "AD"
WRITE_COL_IX  = 30  # AD

MAPPING_CSV = SCRIPT_DIR / "archive_capture_map.csv"
SUMMARY_CSV = SCRIPT_DIR / "fee_cee_summary.csv"
DEFAULT_CREDENTIALS = SCRIPT_DIR / "ee-hyunjin-f97764a9f222.json"
CREDENTIALS = Path(os.environ.get("GSPREAD_CREDENTIALS", DEFAULT_CREDENTIALS))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def load_csv_dict(path, key_field):
    with path.open(newline="") as f:
        return {row[key_field]: row for row in csv.DictReader(f)}


def normalize_series(s: str) -> str:
    """'23.4, 23.5, 23.6' -> '23.4,23.5,23.6' (matches existing sheet style)."""
    if not s:
        return ""
    return ",".join(p.strip() for p in s.split(","))


def _norm(s: str) -> str:
    """Lowercase, swap underscores for spaces, strip parens/digits noise — for fuzzy compare."""
    s = s.lower()
    s = re.sub(r"[_\s]+", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_row(targets_col, dates_col, target: str, date_iso: str, threshold: float = 0.5):
    """
    Return (1-based row index, list of (score, row, sheet_target) candidates).
    Strategy:
      1) filter sheet rows by date prefix match (column E starts with YYYY-MM-DD)
      2) among those, score similarity of column C vs `target`
      3) pick highest above threshold; warn if runner-up is within 0.1
    """
    candidates = []
    tn = _norm(target)
    for i, (t, d) in enumerate(zip(targets_col, dates_col), start=1):
        if not d.strip().startswith(date_iso):
            continue
        score = SequenceMatcher(None, tn, _norm(t)).ratio()
        candidates.append((score, i, t.strip()))
    candidates.sort(reverse=True)
    if not candidates or candidates[0][0] < threshold:
        return None, candidates
    return candidates[0][1], candidates


def main():
    if not CREDENTIALS.exists():
        sys.exit(f"Service-account JSON not found: {CREDENTIALS}")
    for p in (MAPPING_CSV, SUMMARY_CSV):
        if not p.exists():
            sys.exit(f"Missing {p.name} — run process-all.sh first")

    creds = Credentials.from_service_account_file(str(CREDENTIALS), scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_TAB)

    targets_col = ws.col_values(TARGET_COL_IX)
    dates_col   = ws.col_values(DATE_COL_IX)
    existing_col = ws.col_values(WRITE_COL_IX)  # current AD values — preserve non-empty

    mapping = load_csv_dict(MAPPING_CSV, "capture")
    summary = load_csv_dict(SUMMARY_CSV, "capture")

    updates, misses = [], []
    for capture, m in mapping.items():
        s = summary.get(capture)
        if not s:
            misses.append((capture, "no summary entry"))
            continue
        fee = normalize_series(s.get("FEE", ""))
        cem = normalize_series(s.get("CEM", ""))
        if not fee and not cem:
            misses.append((capture, "FEE/CEM empty"))
            continue

        row, cands = find_row(targets_col, dates_col, m["target"], m["date"])
        if row is None:
            best = f" (best fuzzy candidate: {cands[0][2]} @ {cands[0][0]:.2f})" if cands else ""
            misses.append((capture, f"no row matched (target={m['target']} date={m['date']}){best}"))
            continue

        # Don't overwrite cells that already have content
        existing = existing_col[row - 1].strip() if row - 1 < len(existing_col) else ""
        if existing:
            print(f"  row {row:>3}  {capture}  --  skip (AD already filled)")
            continue

        # Warn if runner-up is close — possibly ambiguous match
        ambig = ""
        if len(cands) > 1 and cands[1][0] >= cands[0][0] - 0.1:
            ambig = f"  [ambiguous: also {cands[1][2]!r}@{cands[1][0]:.2f}]"

        value = f"FEE: {fee}\nCEM: {cem}"
        updates.append({"range": f"{WRITE_COL}{row}", "values": [[value]]})
        matched_target = cands[0][2]
        print(f"  row {row:>3}  {capture}  ->  {matched_target!r}  (score {cands[0][0]:.2f}){ambig}")

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
