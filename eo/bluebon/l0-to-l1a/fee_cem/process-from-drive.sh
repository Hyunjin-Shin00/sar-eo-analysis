#!/bin/bash
#
# process-from-drive.sh — sheet-driven FEE/CEM pipeline.
#
# Finds Mission rows whose AD column is empty, matches each to a Drive
# capture folder (gdrive:LEOP/<YYMMDD_HHMMSS>/), runs the local
# imaging-test.sh pipeline if needed, uploads result.txt + telemetry/ back
# to Drive, and writes FEE/CEM into the matching sheet row.
#
# Usage:
#   ./process-from-drive.sh                  # all empty AD rows
#   ./process-from-drive.sh 654 685          # only these sheet row numbers
#   ./process-from-drive.sh --dry-run        # plan only — no downloads/writes
#   ./process-from-drive.sh --limit 5        # cap processed rows after planning

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$SCRIPT_DIR/bin:$PATH"   # make our `rename` shim visible

exec python3 "$SCRIPT_DIR/process_empty_rows.py" "$@"
