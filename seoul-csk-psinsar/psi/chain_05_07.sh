#!/bin/bash
# run_05 -> run_06 -> run_07 back to back, each skipping work already done.
set -u
R=<DATA_ROOT>/CSK_PSInSAR
R5="$R/stack/run_files/run_05_invertMisreg"
R6="$R/stack/run_files/run_06_fineResamp"
R7="$R/stack/run_files/run_07_grid_baseline"

echo "CHAIN START $(date +%H:%M:%S)"

# --- run_05: 미등록 오정합 네트워크 역산 (1작업) ---
"$R/code/run_step.sh" "$R5" 1 32G || { echo "CHAIN ABORT: run_05 실패"; exit 1; }

# --- run_06: fineResamp, 미완료분만 ---
T6="$R/stack/run_files/run06_todo"; : > "$T6"
while read -r l; do [ -z "$l" ] && continue
  d=$(grep -oE '[0-9]{8}' <<< "$l" | tail -1)
  [ -s "$R/stack/coregSLC/Coarse/../Fine/$d/$d.slc" ] || echo "$l" >> "$T6"
done < "$R6"
echo "run_06 대상 $(grep -cve '^\s*$' "$T6")개"
"$R/code/run_step.sh" "$T6" 6 56G || { echo "CHAIN ABORT: run_06 실패"; exit 1; }

# --- run_07: baseline grid ---
"$R/code/run_step.sh" "$R7" 8 48G || { echo "CHAIN ABORT: run_07 실패"; exit 1; }

echo "CHAIN DONE $(date +%H:%M:%S)"
