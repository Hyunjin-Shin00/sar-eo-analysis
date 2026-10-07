#!/usr/bin/env bash
# DSC SBAS 실행 (지역별 순차). usage: run_sbas_dsc.sh <t061|t134>
# 하강궤도는 geom 이 full-res(1x1) 이므로 run_sbas_autoscale.py(배율 자동감지판) 필수.
# 옵션 미지정 = 기본값 rgl 9 / azl 3 / coh_min 0.30 / tcoh_min 0.70 = T2k 조건 (기존 분석과 동일)
set -u
R=${WORK_ROOT}/CLAB_DSC
PY=${CONDA_PREFIX}/bin/python
BIN=${DATA_ROOT}/CLAB/analysis/insar_bin
export PYTHONPATH=""
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PROJ_DATA=$($PY -c "import pyproj;print(pyproj.datadir.get_data_dir())" 2>/dev/null)
export PROJ_LIB=$PROJ_DATA

TAG=${1:?사용법: run_sbas_dsc.sh <t061|t134>}
case "$TAG" in
  t061) MERGED=$R/proc_t061_busan/stack/merged
        REGIONS=("Busan_Mandeok_Centum_DSC|35.1644 35.2508 129.0092 129.1379"
                 "Busan_Sasang_Hadan_DSC|35.1294 35.1664 128.9677 129.0049") ;;
  t134) MERGED=$R/proc_t134_capital/stack/merged
        REGIONS=("Seoul_Gangdong_DSC|37.5097 37.5840 127.1033 127.1994"
                 "Seoul_Seodaemun_DSC|37.5407 37.5977 126.8844 126.9636"
                 "Gyeonggi_Gwangmyeong_DSC|37.3812 37.4442 126.8410 126.9181") ;;
  *) echo "TAG 는 t061 또는 t134"; exit 1 ;;
esac
ST=$R/sbas/sbas_status_$TAG.txt
mkdir -p "$R/sbas"
say() { echo "[$(date '+%F %T')] $*" | tee -a "$ST"; }

[ -d "$MERGED" ] || { say "SBAS FAILED: merged 없음 $MERGED"; exit 1; }
say "===== SBAS 시작 $TAG · merged SLC $(ls $MERGED/SLC 2>/dev/null | wc -l)개 · 지역 ${#REGIONS[@]}개 ====="
ok=0; fail=0
for ent in "${REGIONS[@]}"; do
  REG=${ent%%|*}; BBOX=${ent#*|}
  OUT=$R/sbas/$REG
  if [ -f "$OUT/${REG}_sbas_ps_v.csv" ]; then say "skip $REG (이미 완료)"; ok=$((ok+1)); continue; fi
  mkdir -p "$OUT"
  say "실행 $REG  bbox '$BBOX'"
  t0=$(date +%s)
  if "$PY" "$BIN/run_sbas_autoscale.py" --merged "$MERGED" --bbox $BBOX \
       --out "$OUT" --region "$REG" > "$OUT/sbas.log" 2>&1; then
    n=$(wc -l < "$OUT/${REG}_sbas_ps_v.csv" 2>/dev/null || echo 0)
    say "완료 $REG ($(( $(date +%s)-t0 ))s) · 관측점 $((n-1))개"
    ok=$((ok+1))
  else
    say "★실패 $REG ($(( $(date +%s)-t0 ))s) — 로그 $OUT/sbas.log"
    tail -5 "$OUT/sbas.log" | sed 's/^/      /' | tee -a "$ST"
    fail=$((fail+1))
  fi
done
say "===== SBAS 종료 $TAG · 성공 $ok · 실패 $fail ====="
[ "$fail" -eq 0 ] && touch "$R/sbas/SBAS_DONE_$TAG"
