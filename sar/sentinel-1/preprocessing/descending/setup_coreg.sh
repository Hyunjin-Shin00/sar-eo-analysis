#!/usr/bin/env bash
# DSC 코레지 SETUP + run_01 topo 조기검증.  usage: setup_coreg_dsc.sh <t061|t134>
# DSC_incheon/setup_coreg.sh 절차를 그대로 따름:
#   1) zip 무결성 검증  2) slc_link 생성  3) master(중앙일자)  4) stackSentinel 셋업
#   5) run_01 topo 실행 → geom_reference 생성 확인(= DEM 커버리지 조기검증)
set -u
source ${WORK_ROOT}/CLAB_DSC/env_isce2_dsc.sh

TAG=${1:?사용법: setup_coreg_dsc.sh <t061|t134>}
case "$TAG" in
  t061) SLCDIR=$DSC_ROOT/t061_f475_busan/slc
        WORK=$DSC_ROOT/proc_t061_busan
        DEM=$DSC_ROOT/dem/demLat_N35_N36_Lon_E128_E130.dem.wgs84
        # 만덕(35.1644 35.2508 129.0092 129.1379) + 사상(35.1294 35.1664 128.9677 129.0049) 합집합 + 여유
        BBOX='35.11 35.27 128.94 129.16'
        NAME='부산 만덕~센텀 · 사상~하단 (path 61 / frame 475)' ;;
  t134) SLCDIR=$DSC_ROOT/t134_f466_capital/slc
        WORK=$DSC_ROOT/proc_t134_capital
        DEM=$DSC_ROOT/dem/GLO30_Seoul.wgs84.dem
        # 기존 ASC 서울 스택과 동일한 검증된 박스. 강동·서대문·광명·송도 4 AOI 전부 포함.
        BBOX='37.35 37.69 126.57 127.22'
        NAME='수도권 강동·서대문·광명·송도 (path 134 / frame 466)' ;;
  *) echo "TAG 는 t061 또는 t134"; exit 1 ;;
esac
STACK=$WORK/stack
ST=$WORK/coreg_status.txt
mkdir -p "$WORK" "$STACK" "$WORK/aux"
say() { echo "[$(date '+%F %T')] $*" | tee -a "$ST"; }
die() { say "SETUP FAILED: $*"; exit 1; }

say "===== SETUP 시작: $NAME ====="
say "  SLC $SLCDIR · DEM $(basename "$DEM") · BBOX '$BBOX'"

# 1) zip 무결성
n=0; bad=0
for f in "$SLCDIR"/*.zip; do
  n=$((n+1)); unzip -l "$f" >/dev/null 2>&1 || { bad=$((bad+1)); say "  BAD zip: $(basename "$f")"; }
done
say "zip 총 ${n}개, 손상 ${bad}개"
[ "$bad" -eq 0 ] || die "손상 zip ${bad}개 — 재다운로드 필요"

# 2) slc_link
rm -rf "$WORK/slc_link"; mkdir -p "$WORK/slc_link"
for f in "$SLCDIR"/*.zip; do ln -sf "$f" "$WORK/slc_link/$(basename "$f")"; done
say "slc_link 생성 ($(ls "$WORK/slc_link" | wc -l)개)"

# 3) master = 중앙 일자
MASTER=$(ls "$SLCDIR"/S1[AB]_IW_SLC*.zip | grep -oE '_[0-9]{8}T' | grep -oE '[0-9]{8}' \
         | sort -u | awk '{a[NR]=$0} END{print a[int((NR+1)/2)]}')
NDATE=$(ls "$SLCDIR"/*.zip | grep -oE '_[0-9]{8}T' | grep -oE '[0-9]{8}' | sort -u | wc -l)
say "master(중앙일자) = $MASTER  (총 $NDATE dates)"
echo "$MASTER" > "$WORK/MASTER.txt"

# 4) 궤도파일 커버 확인
miss=0
for d in $(ls "$SLCDIR"/*.zip | grep -oE '_[0-9]{8}T' | grep -oE '[0-9]{8}' | sort -u); do
  y=${d:0:4}; m=${d:4:2}; dd=${d:6:2}
  prev=$(date -d "$y-$m-$dd -1 day" +%Y%m%d)
  ls "$ORBIT_DIR"/*_V${prev}T*.EOF >/dev/null 2>&1 || { miss=$((miss+1)); say "  궤도없음 $d"; }
done
say "궤도파일 확인: 부족 ${miss}개"
[ "$miss" -eq 0 ] || die "궤도파일 ${miss}개 부족"

# 5) stackSentinel 셋업 (DSC_incheon 과 동일 인자)
say "stackSentinel 셋업 (slc workflow, NESD, -c 1, swaths 1 2 3, -z 1 -r 1)"
cd "$STACK" || die "cd stack"
stackSentinel.py -s "$WORK/slc_link" -o "$ORBIT_DIR" -a "$WORK/aux" -w "$STACK" \
  -d "$DEM" -b "$BBOX" -n '1 2 3' -W slc -p vv -C NESD -c 1 -z 1 -r 1 \
  -m "$MASTER" --num_proc 1 --num_proc4topo 1 > "$WORK/setup.log" 2>&1 \
  || die "stackSentinel 셋업 실패 (setup.log 확인)"
[ -d "$STACK/run_files" ] || die "run_files 미생성"
say "run_files 생성 완료: $(ls "$STACK"/run_files/run_* 2>/dev/null | wc -l)개"

# 6) run_01 topo 조기검증 (DEM 커버리지)
say "run_01 topo 실행 (DEM 커버리지 조기검증)"
RF=$(ls "$STACK"/run_files/run_01_* 2>/dev/null | head -1)
[ -n "$RF" ] || die "run_01 파일 없음"
LOGF="$WORK/log_run_01_unpack_topo_reference.log"; : > "$LOGF"
while IFS= read -r cmd; do
  [ -z "$cmd" ] && continue
  eval "$cmd" >> "$LOGF" 2>&1 || die "run_01 명령 실패 (로그: $LOGF)"
done < "$RF"
NG=$(ls "$STACK"/geom_reference/*/*.rdr* 2>/dev/null | wc -l)
[ "$NG" -gt 0 ] || die "run_01 topo 실패: geom_reference 비어있음 → DEM 커버리지/.vrt 확인 (로그: $LOGF)"
say "geom_reference 산출 ${NG}개 파일"
touch "$WORK/SETUP_DONE"
say "===== SETUP 완료: topo OK, 전체 코레지 진행 가능 ====="
