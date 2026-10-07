#!/usr/bin/env bash
# Parallel, resumable-by-restart ASF Sentinel-1 SLC downloader with size verification.
# Robust against ASF quirks: probe uses --http1.1 + retries; downloads are FRESH each
# attempt (no -C -, which caused 200-on-resume append-bloat); verification uses a small
# tolerance; if the size probe fails, only a plausible SLC size (3-5GB) is accepted so
# corrupt/doubled files are never mistaken for complete.
# Usage: download_track.sh <urls.txt> <dest_dir> <parallel_jobs>
set -u

URLS="$1"
DEST="$2"
JOBS="${3:-6}"
LOG="$DEST/download.log"
TOL=5242880          # 5 MB tolerance for probe imprecision
MINSLC=3000000000    # plausible SLC lower bound (no-probe fallback)
MAXSLC=5000000000    # plausible SLC upper bound (no-probe fallback)

mkdir -p "$DEST"
cd "$DEST"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
echo "[$(ts)] START track download: $(wc -l < "$URLS") urls, dest=$DEST, jobs=$JOBS" >> "$LOG"

fetch_one() {
  url="$1"
  fname=$(basename "${url%%\?*}")
  jar=$(mktemp /tmp/asf_jar.XXXXXX)

  # --- probe remote total size (http1.1 + up to 3 tries) ---
  rsize=""
  for pa in 1 2 3; do
    rsize=$(curl -s --http1.1 -r 0-0 --netrc -c "$jar" -b "$jar" -L --location-trusted -D - -o /dev/null "$url" 2>/dev/null \
              | tr -d '\r' | awk -F'/' 'tolower($0) ~ /content-range/ {print $2}' | tail -1)
    case "$rsize" in ''|*[!0-9]*) rsize="";; *) break;; esac
    sleep 5
  done

  # --- skip if already present at correct size (within tolerance) ---
  if [ -f "$fname" ] && [ -n "$rsize" ]; then
    lsize=$(stat -c %s "$fname" 2>/dev/null || echo 0)
    d=$((lsize - rsize)); ad=${d#-}
    if [ "$ad" -le "$TOL" ]; then
      echo "[$(date '+%F %T')] SKIP complete: $fname ($lsize)" >> download.log
      rm -f "$jar"; return 0
    fi
  fi

  # --- fresh download (NO -C -), up to 5 attempts ---
  for attempt in 1 2 3 4 5; do
    rm -f "$fname"                     # always start clean -> no append-bloat ever
    curl -sS --http1.1 --netrc -c "$jar" -b "$jar" -L --location-trusted \
         --retry 3 --retry-delay 10 -o "$fname" "$url" >> download.log 2>&1
    lsize=$(stat -c %s "$fname" 2>/dev/null || echo 0)
    if [ -n "$rsize" ]; then
      d=$((lsize - rsize)); ad=${d#-}
      if [ "$ad" -le "$TOL" ]; then
        echo "[$(date '+%F %T')] OK $fname ($lsize) attempt=$attempt" >> download.log
        rm -f "$jar"; return 0
      fi
    else
      if [ "$lsize" -ge "$MINSLC" ] && [ "$lsize" -le "$MAXSLC" ]; then
        echo "[$(date '+%F %T')] OK(no-probe) $fname ($lsize) attempt=$attempt" >> download.log
        rm -f "$jar"; return 0
      fi
    fi
    echo "[$(date '+%F %T')] RETRY $fname attempt=$attempt local=$lsize remote=${rsize:-?}" >> download.log
    sleep 10
  done
  echo "[$(date '+%F %T')] FAIL $fname (local=$lsize remote=${rsize:-?})" >> download.log
  rm -f "$jar"; return 1
}
export -f fetch_one
export TOL MINSLC MAXSLC

cat "$URLS" | xargs -P "$JOBS" -I {} bash -c 'fetch_one "$@"' _ {}

echo "[$(ts)] DONE track download: $DEST" >> "$LOG"
have=$(find "$DEST" -maxdepth 1 -name '*.zip' | wc -l)
want=$(wc -l < "$URLS")
echo "[$(ts)] SUMMARY $DEST : $have/$want zip files present" >> "$LOG"
