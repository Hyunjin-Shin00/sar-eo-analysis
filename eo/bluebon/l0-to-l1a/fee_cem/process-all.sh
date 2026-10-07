#!/bin/bash
#
# Usage:
#   ./process-all.sh [input_dir]
#
#   input_dir : .tar.xz archives are searched here (default: parent dir of this script)
#
# Flow:
#   1) extract every *.tar.xz under input_dir to a temp folder
#   2) copy *.tlm.tpx* files from each archive into ./downlink/
#   3) run imaging-test.sh for every unique capture-* prefix
#   4) parse FEE / CEM values from result/*/result.txt
#   5) write fee_cee_summary.csv and fee_cee_summary.json

set -u
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT_DIR="${1:-$(dirname "$SCRIPT_DIR")}"

# Prepend bin/ so our minimal `rename` shim is found without system install
export PATH="$SCRIPT_DIR/bin:$PATH"

DOWNLINK="$SCRIPT_DIR/downlink"
RESULT_BASE="$SCRIPT_DIR/result"
TMP_EXTRACT="$SCRIPT_DIR/.extract_tmp"
SUMMARY_CSV="$SCRIPT_DIR/fee_cee_summary.csv"
SUMMARY_JSON="$SCRIPT_DIR/fee_cee_summary.json"
MAPPING_CSV="$SCRIPT_DIR/archive_capture_map.csv"

mkdir -p "$DOWNLINK" "$TMP_EXTRACT"

# Clean up leftovers from a previous interrupted run (imaging-test.sh sets these up
# but only cleans them up if it reaches the end successfully).
rm -f "$DOWNLINK"/_capture-*.tlm.tpx* "$DOWNLINK"/_capture-*.bin* \
      "$DOWNLINK"/imaging-capture.tlm.tpx* "$DOWNLINK"/capture.bin* 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 1 & 2: extract archives, collect .tlm.tpx files
# ---------------------------------------------------------------------------
echo "[1/4] Extracting .tar.xz from: $INPUT_DIR"
archives=("$INPUT_DIR"/*.tar.xz)

# Mapping CSV is accumulated across runs — only init header if missing.
# (Don't truncate, otherwise previously-extracted captures lose their date/target.)
if [ ! -f "$MAPPING_CSV" ]; then
  echo "archive,date,target,capture" > "$MAPPING_CSV"
fi

# Collect prefixes of THIS run's captures only.
# (downlink/ may contain leftovers from previous runs or from process-from-drive.sh
#  — we must NOT process those here. Only handle captures extracted from $INPUT_DIR
#  archives this time.)
prefixes=()

if [ ${#archives[@]} -eq 0 ]; then
  echo "  (no .tar.xz archives found)"
else
  for archive in "${archives[@]}"; do
    name=$(basename "$archive" .tar.xz)
    dest="$TMP_EXTRACT/$name"
    echo "  - $name"
    rm -rf "$dest"
    mkdir -p "$dest"
    tar -xJf "$archive" -C "$dest"

    found=$(find "$dest" -type f -name "*.tlm.tpx*" | wc -l)
    if [ "$found" -eq 0 ]; then
      echo "    ! no .tlm.tpx files inside $name"
      continue
    fi
    find "$dest" -type f -name "*.tlm.tpx*" -exec cp -f {} "$DOWNLINK/" \;
    echo "    copied $found .tlm.tpx file(s) -> downlink/"

    # Collect prefixes for this archive's captures
    while IFS= read -r f; do
      prefix=$(basename "$f" .tlm.tpx00)
      prefixes+=("$prefix")
    done < <(find "$dest" -type f -name "*.tlm.tpx00")

    # Record archive -> capture mapping (date + target parsed from archive filename)
    # Pattern assumed: YYYYMMDD_<target>.tar.xz   (target may contain underscores)
    if [[ "$name" =~ ^([0-9]{8})_(.+)$ ]]; then
      date_raw="${BASH_REMATCH[1]}"
      target="${BASH_REMATCH[2]}"
      date_iso="${date_raw:0:4}-${date_raw:4:2}-${date_raw:6:2}"
      while IFS= read -r f; do
        prefix=$(basename "$f" .tlm.tpx00)
        # skip if this capture already has a mapping entry
        if ! grep -q ",${prefix}\$" "$MAPPING_CSV"; then
          echo "$name,$date_iso,$target,$prefix" >> "$MAPPING_CSV"
        fi
      done < <(find "$dest" -type f -name "*.tlm.tpx00")
    else
      echo "    ! archive name not in 'YYYYMMDD_<target>' form — skipping mapping for $name"
    fi
  done
fi

# ---------------------------------------------------------------------------
# Step 2: report which captures we'll process (this run only)
# ---------------------------------------------------------------------------
echo "[2/4] Captures extracted in this run"
if [ ${#prefixes[@]} -eq 0 ]; then
  echo "  ! no captures extracted — nothing to do"
  exit 0
fi
echo "  ${#prefixes[@]} capture(s): ${prefixes[*]}"

# ---------------------------------------------------------------------------
# Step 4: run imaging-test.sh for each capture (sequentially — rename collision)
# ---------------------------------------------------------------------------
echo "[3/4] Running imaging-test.sh for each capture"
failed=()
for prefix in "${prefixes[@]}"; do
  echo "  - $prefix"
  if ( cd "$SCRIPT_DIR" && bash imaging-test.sh "$prefix" >/dev/null 2>&1 ); then
    echo "    ok"
  else
    echo "    ! imaging-test.sh exited non-zero (check result/${prefix#capture-}/result.txt)"
    failed+=("$prefix")
  fi
done

# ---------------------------------------------------------------------------
# Step 5: parse FEE / CEE values, write CSV + JSON
# ---------------------------------------------------------------------------
echo "[4/4] Aggregating FEE / CEM values"
echo "capture,FEE,CEM" > "$SUMMARY_CSV"
json_tmp="$(mktemp)"
echo "[" > "$json_tmp"

count=0
total=${#prefixes[@]}
for prefix in "${prefixes[@]}"; do
  count=$((count + 1))
  result_dir="${prefix#capture-}"
  result_txt="$RESULT_BASE/$result_dir/result.txt"

  fee=""
  cem=""
  if [ -f "$result_txt" ]; then
    fee=$(grep -m1 '^FEE:' "$result_txt" | sed 's/^FEE:[[:space:]]*//')
    cem=$(grep -m1 '^CEM:' "$result_txt" | sed 's/^CEM:[[:space:]]*//')
  else
    echo "  ! missing $result_txt"
  fi

  # CSV — wrap in quotes since values contain commas; escape internal quotes
  fee_csv=${fee//\"/\"\"}
  cem_csv=${cem//\"/\"\"}
  printf '%s,"%s","%s"\n' "$prefix" "$fee_csv" "$cem_csv" >> "$SUMMARY_CSV"

  # JSON — escape backslash and double-quote
  fee_j=${fee//\\/\\\\}; fee_j=${fee_j//\"/\\\"}
  cem_j=${cem//\\/\\\\}; cem_j=${cem_j//\"/\\\"}
  sep=","
  [ "$count" -eq "$total" ] && sep=""
  printf '  {"capture":"%s","FEE":"%s","CEM":"%s"}%s\n' \
    "$prefix" "$fee_j" "$cem_j" "$sep" >> "$json_tmp"
done

echo "]" >> "$json_tmp"
mv "$json_tmp" "$SUMMARY_JSON"

# ---------------------------------------------------------------------------
# Cleanup of extract temp folder (downlink + result are preserved)
# ---------------------------------------------------------------------------
rm -rf "$TMP_EXTRACT"

echo "Done."
echo "  CSV : $SUMMARY_CSV"
echo "  JSON: $SUMMARY_JSON"
if [ ${#failed[@]} -gt 0 ]; then
  echo "  failed captures: ${failed[*]}"
fi

# ---------------------------------------------------------------------------
# Step 5: upload telemetry/ + result.txt to gdrive:LEOP/<dir>
#   - destination folder must already exist on Drive (we don't create new ones)
#   - skipped if SKIP_DRIVE_UPLOAD=1 or rclone unavailable
# ---------------------------------------------------------------------------
if [ "${SKIP_DRIVE_UPLOAD:-0}" = "1" ]; then
  echo "[5/6] Skipping Drive upload (SKIP_DRIVE_UPLOAD=1)"
elif ! command -v rclone >/dev/null 2>&1; then
  echo "[5/6] Skipping Drive upload (rclone not installed)"
else
  echo "[5/6] Uploading telemetry/ + result.txt to gdrive:LEOP/"
  mapfile -t leop_folders < <(rclone lsf --dirs-only gdrive:LEOP/ 2>/dev/null | sed 's:/$::')
  for prefix in "${prefixes[@]}"; do
    result_dir="${prefix#capture-}"
    src="$RESULT_BASE/$result_dir"
    if ! printf '%s\n' "${leop_folders[@]}" | grep -Fxq "$result_dir"; then
      echo "  ! gdrive:LEOP/$result_dir not found — skipping"
      continue
    fi
    # Snapshot what's already in the destination so we don't re-upload
    existing=$(rclone lsf "gdrive:LEOP/$result_dir/" 2>/dev/null)

    if [ -d "$src/telemetry" ]; then
      if printf '%s\n' "$existing" | grep -Fxq "telemetry/"; then
        echo "  - $result_dir/telemetry   already on Drive, skip"
      else
        rclone copy "$src/telemetry" "gdrive:LEOP/$result_dir/telemetry" \
          && echo "  - $result_dir/telemetry   uploaded"
      fi
    fi

    if [ -f "$src/result.txt" ]; then
      if printf '%s\n' "$existing" | grep -Fxq "result.txt"; then
        echo "  - $result_dir/result.txt  already on Drive, skip"
      else
        rclone copy "$src/result.txt" "gdrive:LEOP/$result_dir/" \
          && echo "  - $result_dir/result.txt  uploaded"
      fi
    fi
  done
fi

# ---------------------------------------------------------------------------
# Step 6 (optional): push FEE/CEM values to the Google Sheet.
# Skipped automatically when:
#   - SKIP_SHEET_UPDATE=1 is set, or
#   - python3 / update_sheet.py / credentials JSON is missing
# ---------------------------------------------------------------------------
SHEET_SCRIPT="$SCRIPT_DIR/update_sheet.py"
SHEET_CREDS="${GSPREAD_CREDENTIALS:-$SCRIPT_DIR/ee-hyunjin-f97764a9f222.json}"

if [ "${SKIP_SHEET_UPDATE:-0}" = "1" ]; then
  echo "[6/6] Skipping Google Sheet update (SKIP_SHEET_UPDATE=1)"
elif [ ! -f "$SHEET_SCRIPT" ]; then
  echo "[6/6] Skipping Google Sheet update (update_sheet.py not found)"
elif [ ! -f "$SHEET_CREDS" ]; then
  echo "[6/6] Skipping Google Sheet update (credentials JSON not found: $SHEET_CREDS)"
elif ! command -v python3 >/dev/null 2>&1; then
  echo "[6/6] Skipping Google Sheet update (python3 not installed)"
else
  echo "[6/6] Updating Google Sheet (Mission tab, AD column)"
  python3 "$SHEET_SCRIPT" || echo "  ! update_sheet.py exited non-zero"
fi

if [ ${#failed[@]} -gt 0 ]; then
  exit 1
fi
