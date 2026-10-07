#!/usr/bin/env python3
"""
process_empty_rows.py — drive the FEE/CEM pipeline from the spreadsheet side.

For every row in the Mission tab where column AD is empty:
  1) parse the capture datetime from column E
  2) find the closest YYMMDD_HHMMSS folder on gdrive:LEOP/ (same date)
  3) if Drive folder is already complete (result.txt + telemetry/ present),
     just pull result.txt and parse FEE/CEM
     else: download raw/*.tlm.tpx*, run imaging-test.sh locally,
     upload telemetry/ + result.txt back to Drive, then parse FEE/CEM
  4) write FEE: ... \\n CEM: ... into that exact AD cell
     (re-checked just before write — won't overwrite a row that was filled
     during processing)

Usage:
  python3 process_empty_rows.py                  # all empty AD rows
  python3 process_empty_rows.py 654 685          # only these (1-based) sheet rows
  python3 process_empty_rows.py --date 2026-04-29  # only rows whose E date matches
  python3 process_empty_rows.py --dry-run        # plan only, no downloads/writes
  python3 process_empty_rows.py --limit 5        # process at most 5 rows

Pre-conditions:
  - gspread + google-auth installed
  - service account JSON next to this script (or GSPREAD_CREDENTIALS env)
  - service account shared as Editor on the sheet
  - rclone configured with `gdrive:` remote at the LEOP folder root
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    sys.exit("Install:  pip install gspread google-auth")

SCRIPT_DIR  = Path(__file__).resolve().parent
DOWNLINK    = SCRIPT_DIR / "downlink"
RESULT_BASE = SCRIPT_DIR / "result"

SPREADSHEET_ID = os.environ.get("BLUEBON_SHEET_ID", "")
SHEET_TAB     = "Mission"
DATE_COL_IX   = 5    # E
WRITE_COL     = "AD"
WRITE_COL_IX  = 30
DRIVE_BASE    = "gdrive:LEOP"

# Maximum allowed time difference between sheet datetime and folder datetime.
# Pairs further apart than this are treated as "no match".
MAX_DELTA_SECONDS = 20

CREDENTIALS = Path(os.environ.get(
    "GSPREAD_CREDENTIALS",
    SCRIPT_DIR / "ee-hyunjin-f97764a9f222.json",
))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_DT_RE     = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)")
_FOLDER_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$")


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------
def parse_sheet_dt(s):
    if not s:
        return None
    m = _DT_RE.match(s.strip())
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1))
    except ValueError:
        return None


def parse_folder_dt(name):
    m = _FOLDER_RE.match(name)
    if not m:
        return None
    yy, mo, dd, hh, mi, ss = m.groups()
    try:
        return datetime(2000 + int(yy), int(mo), int(dd), int(hh), int(mi), int(ss))
    except ValueError:
        return None


def normalize_series(s):
    return ",".join(p.strip() for p in (s or "").split(","))


# --------------------------------------------------------------------------
# rclone / imaging-test wrappers
# --------------------------------------------------------------------------
def rclone_lsf(path, args=None):
    r = subprocess.run(
        ["rclone", "lsf"] + (args or []) + [path],
        capture_output=True, text=True, check=False,
    )
    return r.stdout.splitlines() if r.returncode == 0 else []


def drive_state(folder):
    """Return tuple (has_result_txt, has_telemetry, has_raw_tlm)."""
    top = rclone_lsf(f"{DRIVE_BASE}/{folder}/")
    has_result    = "result.txt"  in top
    has_telemetry = "telemetry/"  in top
    raw_listing = rclone_lsf(f"{DRIVE_BASE}/{folder}/raw/")
    has_raw = any(".tlm.tpx" in f for f in raw_listing)
    return has_result, has_telemetry, has_raw


def rclone_copy(src, dst, include=None):
    cmd = ["rclone", "copy"]
    if include:
        cmd += ["--include", include]
    cmd += [src, dst]
    return subprocess.run(cmd, check=False).returncode == 0


def cleanup_downlink_leftovers():
    for pat in ("_capture-*.tlm.tpx*", "_capture-*.bin*",
                "imaging-capture.tlm.tpx*", "capture.bin*"):
        for f in DOWNLINK.glob(pat):
            try:
                f.unlink()
            except OSError:
                pass


def run_imaging_test(prefix):
    r = subprocess.run(
        ["bash", "imaging-test.sh", prefix],
        cwd=str(SCRIPT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return r.returncode == 0


def parse_fee_cem(result_txt):
    fee, cem = "", ""
    if not result_txt.is_file():
        return fee, cem
    for line in result_txt.read_text(errors="replace").splitlines():
        if not fee and line.startswith("FEE:"):
            fee = line[4:].strip()
        elif not cem and line.startswith("CEM:"):
            cem = line[4:].strip()
    return fee, cem


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("rows", nargs="*", type=int,
                   help="optional: only process these (1-based) sheet rows")
    p.add_argument("--date", type=str, default="",
                   help="only consider rows whose E datetime is on this date (YYYY-MM-DD)")
    p.add_argument("--dry-run", action="store_true",
                   help="plan only — print the row→folder matches and stop")
    p.add_argument("--limit", type=int, default=0,
                   help="cap the number of rows processed (after planning)")
    args = p.parse_args()

    date_filter = None
    if args.date:
        try:
            date_filter = datetime.fromisoformat(args.date).date()
        except ValueError:
            sys.exit(f"--date expects YYYY-MM-DD, got: {args.date}")

    if not CREDENTIALS.exists():
        sys.exit(f"Service-account JSON not found: {CREDENTIALS}")
    DOWNLINK.mkdir(exist_ok=True)
    cleanup_downlink_leftovers()

    # 1. Read sheet, find empty AD rows
    print(f"[1/5] Reading '{SHEET_TAB}' …")
    creds = Credentials.from_service_account_file(str(CREDENTIALS), scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_TAB)
    dates_col = ws.col_values(DATE_COL_IX)
    ad_col    = ws.col_values(WRITE_COL_IX)

    candidates = []  # (row, sheet_datetime)
    for i, d in enumerate(dates_col, start=1):
        dt = parse_sheet_dt(d)
        if dt is None:
            continue
        ad = ad_col[i - 1].strip() if i - 1 < len(ad_col) else ""
        if ad:
            continue
        if args.rows and i not in args.rows:
            continue
        if date_filter and dt.date() != date_filter:
            continue
        candidates.append((i, dt))
    print(f"  {len(candidates)} row(s) with empty AD + valid E datetime")
    if not candidates:
        return

    # 2. List Drive folders
    print(f"[2/5] Listing folders on {DRIVE_BASE}/ …")
    folders = []
    for entry in rclone_lsf(f"{DRIVE_BASE}/", ["--dirs-only"]):
        name = entry.rstrip("/")
        fdt = parse_folder_dt(name)
        if fdt is not None:
            folders.append((name, fdt))
    print(f"  {len(folders)} YYMMDD_HHMMSS folders found")

    # 3. Match rows to Drive folders.
    # Build every (row, folder) pair on the same date, sort by Δ ascending,
    # then greedily assign 1-to-1 — the smallest Δ wins, so a folder always
    # ends up on its closest row (not just on whatever row was iterated first).
    pairs = []
    for row, target in candidates:
        for name, fdt in folders:
            if fdt.date() != target.date():
                continue
            delta = abs((fdt - target).total_seconds())
            if delta > MAX_DELTA_SECONDS:
                continue
            pairs.append((delta, row, target, name, fdt))
    pairs.sort(key=lambda p: p[0])

    plan = []
    matched_rows = set()
    matched_folders = set()
    for delta, row, target, name, fdt in pairs:
        if row in matched_rows or name in matched_folders:
            continue
        plan.append((row, target, name, fdt, delta))
        matched_rows.add(row)
        matched_folders.add(name)

    no_match = [(row, target) for row, target in candidates if row not in matched_rows]

    print(f"[3/5] Matched {len(plan)} row(s) to Drive folders")
    for row, sdt, folder, fdt, delta in plan:
        print(f"  row {row:>3}  sheet={sdt.isoformat()}  ->  {folder}  Δ={int(delta)}s")
    for row, target in no_match:
        print(f"  row {row:>3}  sheet={target.isoformat()}  ! no folder on {target.date()}")

    if args.dry_run:
        print("(dry-run) stopping before download / imaging / write")
        return
    if args.limit > 0:
        plan = plan[: args.limit]
        print(f"  (--limit {args.limit}) processing first {len(plan)} only")

    # 4. Process each matched folder
    print("[4/5] Processing each match")
    updates = []
    for row, sdt, folder, fdt, delta in plan:
        prefix    = f"capture-{folder}"
        local_dir = RESULT_BASE / folder
        local_txt = local_dir / "result.txt"

        has_result, has_telemetry, has_raw = drive_state(folder)
        print(f"  - {folder}  (drive: result={has_result} telemetry={has_telemetry} raw={has_raw})")

        if has_result and has_telemetry:
            if not local_txt.is_file():
                local_dir.mkdir(parents=True, exist_ok=True)
                rclone_copy(f"{DRIVE_BASE}/{folder}/result.txt", str(local_dir))
            print(f"      use existing result.txt")
        elif local_txt.is_file():
            print(f"      local result.txt exists, uploading to Drive")
            if (local_dir / "telemetry").is_dir() and not has_telemetry:
                rclone_copy(str(local_dir / "telemetry"),
                            f"{DRIVE_BASE}/{folder}/telemetry")
            if not has_result:
                rclone_copy(str(local_txt), f"{DRIVE_BASE}/{folder}/")
        else:
            if not has_raw:
                print(f"      ! no raw/*.tlm.tpx* on Drive — skip")
                continue
            print(f"      download raw → imaging-test → upload")
            if not rclone_copy(f"{DRIVE_BASE}/{folder}/raw/", str(DOWNLINK),
                               include="*.tlm.tpx*"):
                print("        ! raw download failed")
                continue
            if not run_imaging_test(prefix):
                print("        ! imaging-test.sh failed")
                continue
            if (local_dir / "telemetry").is_dir() and not has_telemetry:
                rclone_copy(str(local_dir / "telemetry"),
                            f"{DRIVE_BASE}/{folder}/telemetry")
            if local_txt.is_file() and not has_result:
                rclone_copy(str(local_txt), f"{DRIVE_BASE}/{folder}/")

        fee, cem = parse_fee_cem(local_txt)
        fee, cem = normalize_series(fee), normalize_series(cem)
        if not fee and not cem:
            print("      ! FEE/CEM empty in result.txt, skip")
            continue
        updates.append((row, folder, f"FEE: {fee}\nCEM: {cem}"))

    # 5. Re-check AD just before writing (defense against races) and batch update
    print(f"[5/5] Writing {len(updates)} cell(s) to column {WRITE_COL}")
    if not updates:
        print("  nothing to write.")
        return

    latest_ad = ws.col_values(WRITE_COL_IX)
    batch = []
    for row, folder, value in updates:
        cur = latest_ad[row - 1].strip() if row - 1 < len(latest_ad) else ""
        if cur:
            print(f"  row {row:>3}  {folder}  --  skip (AD now filled)")
            continue
        batch.append({"range": f"{WRITE_COL}{row}", "values": [[value]]})
        print(f"  row {row:>3}  {folder}  ->  written")
    if batch:
        ws.batch_update(batch, value_input_option="RAW")
    print("Done.")


if __name__ == "__main__":
    main()
