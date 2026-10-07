#!/usr/bin/env bash
# Self-driving DSC pipeline (disk-aware), IW2, reference=20220930, 224 scenes.
# Order: run_01..07 (coreg+merge SLC) -> delete SECONDARY zips (keep ref zip) ->
# run_08..10 (gen igram, merge, filt+coh; need coreg + ref-zip VRTs) ->
# delete coreg_secondarys + ref zip -> run_11 unwrap -> MintPy SBAS -> PROCESS_DONE.
# run_files are de-duplicated (sort -u) and their trailing '&' stripped so each command
# runs synchronously under xargs. Idempotent via per-run_file .done markers.
set -u
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
BASE=${DATA_ROOT}
W=$BASE/SBAS/DSC
BIN=$BASE/SBAS/_bin
RUNDIR=$W/run_files
LOGDIR=$W/run_logs; mkdir -p "$LOGDIR"
LOG=$W/pipeline.log
SLCDIR=$BASE/sentinel1/dsc
REFDATE=20220930
REFZIP=$SLCDIR/S1A_IW_SLC__1SDV_20220930T011438_20220930T011506_045227_0567EA_2046.zip
say(){ echo "[$(date '+%F %T')] [dsc-pipe] $*" | tee -a "$LOG"; }
dfree(){ df -h "${DATA_ROOT}" | awk 'NR==2{print $4" ("$5")"}'; }

sfile(){ ls "$RUNDIR"/run_$1_* 2>/dev/null | grep -vE '\.(done|log|job)$' | head -1; }
run_one(){ local rf="$1" par="$2" name; name=$(basename "$rf")
  [ -f "$rf.done" ] && { say "SKIP $name (done)"; return 0; }
  local nu; nu=$(grep -ve '^\s*$' "$rf" | sed 's/[[:space:]]*&[[:space:]]*$//' | sort -u | wc -l)
  say "START $name ($nu uniq cmds, par=$par)"
  if grep -ve '^\s*$' "$rf" | sed 's/[[:space:]]*&[[:space:]]*$//' | sort -u \
       | xargs -P "$par" -I {} bash -lc 'eval "$@"' _ {} > "$LOGDIR/$name.log" 2>&1; then
    touch "$rf.done"; say "OK $name"; return 0
  else
    say "FAIL $name -> $LOGDIR/$name.log ; tail:"; tail -15 "$LOGDIR/$name.log" | tee -a "$LOG"; return 1
  fi
}

say "START dsc pipeline. ref=$REFDATE df=$(dfree)"

# 1) coregistration + merge SLC (run_01..07)
for s in 01 02 03 04 05 06 07; do
  rf=$(sfile $s); [ -n "$rf" ] || { say "MISSING run_$s"; exit 1; }
  run_one "$rf" 4 || exit 2
done
say "run_01..07 complete. df=$(dfree)"

# 2) drop secondary zips (coreg_secondarys now holds real resampled SLCs); keep ref zip
if [ "$(ls "$SLCDIR"/*.zip 2>/dev/null | wc -l)" -gt 1 ]; then
  say "deleting secondary DSC zips (keeping ref $(basename "$REFZIP"))"
  find "$SLCDIR" -maxdepth 1 -name '*.zip' ! -name "$(basename "$REFZIP")" -delete
  say "kept $(ls "$SLCDIR"/*.zip 2>/dev/null | wc -l) zip. df=$(dfree)"
fi

# 3) interferograms: generate, merge, filter+coherence (run_08..10) — need coreg + ref-zip VRTs
for s in 08 09 10; do
  rf=$(sfile $s); run_one "$rf" 4 || exit 3
done
say "run_08..10 complete. df=$(dfree)"

# 4) coreg + ref zip no longer needed (run_11 + MintPy read merged/ only)
[ -d "$W/coreg_secondarys" ] && { say "rm coreg_secondarys ($(du -sh "$W/coreg_secondarys" 2>/dev/null|awk '{print $1}'))"; rm -rf "$W/coreg_secondarys"; }
rm -f "$REFZIP"
say "freed coreg + ref zip. df=$(dfree)"

# 5) unwrap (run_11)
rf=$(sfile 11); run_one "$rf" 3 || exit 4
nunw=$(find "$W/merged/interferograms" -name 'filt_fine.unw' 2>/dev/null | wc -l)
say "unwrapped interferograms: $nunw"
[ "$nunw" -ge 1 ] || { say "no unwrapped igrams -> abort"; exit 4; }

# 6) MintPy SBAS (template already fixed: subset=auto, unwrapError=no)
say "starting MintPy dsc"
bash "$BIN/run_mintpy.sh" dsc >> "$LOG" 2>&1 || say "run_mintpy.sh returned nonzero"
if [ -f "$W/mintpy/geo/geo_velocity.h5" ]; then
  touch "$W/PROCESS_DONE"; say "DSC PROCESS_DONE — mintpy/geo/geo_velocity.h5 present. df=$(dfree)"
else
  say "MintPy done but geo/geo_velocity.h5 MISSING -> inspect $W/mintpy/mintpy_run.log"; exit 5
fi
