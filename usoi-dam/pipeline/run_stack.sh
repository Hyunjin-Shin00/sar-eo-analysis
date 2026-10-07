#!/usr/bin/env bash
# Execute ISCE2 topsStack run_files in order for one track.
# Each run_file holds N independent commands (one per date/pair); run them with
# modest parallelism (OMP threads pinned to 1) to stay memory-safe on the shared box.
# Resumable: a .done marker is written per run_file.
# usage: run_stack.sh <asc|dsc> [parallel_per_stage]
set -u
TRACK=$1
PAR=${2:-4}
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1

BASE=${DATA_ROOT}
WORK=$BASE/SBAS/${TRACK^^}
RUNDIR=$WORK/run_files
LOGDIR=$WORK/run_logs
mkdir -p "$LOGDIR"
ST=$WORK/stack_status.txt
say(){ echo "[$(date '+%F %T')] [$TRACK] $*" | tee -a "$ST"; }

[ -d "$RUNDIR" ] || { say "ERROR: no run_files ($RUNDIR) - run setup_stack.sh first"; exit 1; }

for RF in $(ls "$RUNDIR"/run_[0-9]* | grep -vE '\.(job|done|log)$' | sort); do
  name=$(basename "$RF")
  [ -f "$RUNDIR/$name.done" ] && { say "SKIP $name (done)"; continue; }
  nlines=$(grep -cve '^\s*$' "$RF")
  say "START $name ($nlines cmds, par=$PAR)"
  # run each non-empty line as its own command, PAR at a time; capture rc.
  # CRITICAL: topsStack run_file lines end in '&' (background). Strip the trailing '&'
  # so each command runs SYNCHRONOUSLY under xargs -> xargs waits for real completion
  # before the run_file is marked done (otherwise stages race and produce no output).
  if ! grep -ve '^\s*$' "$RF" | sed 's/[[:space:]]*&[[:space:]]*$//' \
        | xargs -P "$PAR" -I {} bash -lc 'eval "$@"' _ {} \
        > "$LOGDIR/$name.log" 2>&1; then
    say "FAIL $name  -> see $LOGDIR/$name.log ; tail:"
    tail -20 "$LOGDIR/$name.log" | tee -a "$ST"
    exit 2
  fi
  touch "$RUNDIR/$name.done"
  say "OK $name"
done
say "ALL run_files complete"
