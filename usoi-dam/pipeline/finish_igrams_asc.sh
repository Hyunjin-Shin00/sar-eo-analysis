#!/usr/bin/env bash
# Disk-safe completion of ASC run_08 (generateIgram) + run_09 (mergeBursts) on a
# nearly-full SHARED disk. Key idea: merge each pair, then IMMEDIATELY delete its
# full-resolution burst interferogram dir (~1.23GB each). Complete pairs are drained
# FIRST to free ~596GB up front, then the missing pairs are generated with headroom.
# coreg_secondarys is KEPT (run_10 FilterAndCoherence reads merged/SLC VRTs that point
# into it); it is deleted only after run_10.
# Idempotent / resumable: an already-merged pair just gets its burst dir removed.
set -u
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1

W=${DATA_ROOT}/SBAS/ASC
IG=$W/interferograms
MG=$W/merged/interferograms
CFG=$W/configs
LOG=$W/run_logs
mkdir -p "$MG" "$LOG"
ST=$W/igram_finish.log
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$ST"; }

MINMERGED=41000000   # expected merged fine.int ~41.9MB (2841x1843 cfloat); guard truncation

merged_ok(){ [ -f "$MG/$1/fine.int" ] && [ "$(stat -c %s "$MG/$1/fine.int" 2>/dev/null||echo 0)" -ge "$MINMERGED" ]; }
bursts_ok(){ [ "$(find "$IG/$1/IW2" -maxdepth 1 -name 'fine_0*.int' -size +290M 2>/dev/null|wc -l)" -ge 4 ]; }

do_pair(){
  p="$1"
  if merged_ok "$p"; then rm -rf "$IG/$p"; return 0; fi
  mkdir -p "$MG/$p"
  if ! bursts_ok "$p"; then
    SentinelWrapper.py -c "$CFG/config_generate_igram_$p" >>"$LOG/finish_gen.log" 2>&1
  fi
  if ! bursts_ok "$p"; then echo "[$(date '+%F %T')] GENFAIL $p" >>"$LOG/finish_err.log"; return 1; fi
  SentinelWrapper.py -c "$CFG/config_merge_igram_$p" >>"$LOG/finish_merge.log" 2>&1
  if merged_ok "$p"; then rm -rf "$IG/$p"; return 0; fi
  echo "[$(date '+%F %T')] MERGEFAIL $p" >>"$LOG/finish_err.log"; return 1
}
export -f do_pair merged_ok bursts_ok
export IG MG CFG LOG MINMERGED

# Authoritative 641-pair set from run_08 configs
mapfile -t PAIRS < <(ls "$CFG"/config_generate_igram_* | sed 's#.*config_generate_igram_##' | sort)
say "total pairs: ${#PAIRS[@]}"

# Split: pairs whose bursts already exist (or already merged) -> DRAIN first (frees disk)
COMPLETE=(); INCOMPLETE=()
for p in "${PAIRS[@]}"; do
  if merged_ok "$p" || bursts_ok "$p"; then COMPLETE+=("$p"); else INCOMPLETE+=("$p"); fi
done
say "drain(complete bursts): ${#COMPLETE[@]}  generate(missing): ${#INCOMPLETE[@]}"

if [ "${#COMPLETE[@]}" -gt 0 ]; then
  say "PHASE A: merge+delete ${#COMPLETE[@]} complete pairs (par=4)"
  printf '%s\n' "${COMPLETE[@]}" | xargs -P 4 -I {} bash -c 'do_pair "$@"' _ {}
  say "PHASE A done. df: $(df -h "${DATA_ROOT}" | awk 'NR==2{print $4" ("$5")"}')"
fi

if [ "${#INCOMPLETE[@]}" -gt 0 ]; then
  say "PHASE B: generate+merge+delete ${#INCOMPLETE[@]} missing pairs (par=3)"
  printf '%s\n' "${INCOMPLETE[@]}" | xargs -P 3 -I {} bash -c 'do_pair "$@"' _ {}
  say "PHASE B done. df: $(df -h "${DATA_ROOT}" | awk 'NR==2{print $4" ("$5")"}')"
fi

# Verify every pair merged
missing=0
for p in "${PAIRS[@]}"; do merged_ok "$p" || { missing=$((missing+1)); echo "MISSING $p" >>"$LOG/finish_err.log"; }; done
say "merged present: $(( ${#PAIRS[@]} - missing )) / ${#PAIRS[@]}  (missing=$missing)"

if [ "$missing" -eq 0 ]; then
  touch "$W/run_files/run_08_generate_burst_igram.done" "$W/run_files/run_09_merge_burst_igram.done"
  # bursts fully drained -> remove the (now empty) interferograms tree
  rm -rf "$IG"
  say "ALL MERGED. run_08+run_09 marked done. burst interferograms/ removed."
  say "coreg_secondarys KEPT (needed by run_10). df: $(df -h "${DATA_ROOT}" | awk 'NR==2{print $4" ("$5")"}')"
  echo OK > "$W/IGRAMS_DONE"
else
  say "INCOMPLETE: $missing pairs still missing merged fine.int -> see $LOG/finish_err.log"
  exit 3
fi
