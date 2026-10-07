#!/usr/bin/env bash
# t134 코레지 워치독 - 완주까지 자동 재시작, 이후 SBAS·통합맵까지 자동 연결.
#
# 왜 별도 unit 인가
#   systemd-oomd 는 cgroup 안의 프로세스를 통째로 죽인다(t134e 에서 5개 동시 사망).
#   따라서 재시도 루프를 코레지와 같은 unit 에 두면 루프까지 함께 죽는다.
#   이 워치독은 sleep 과 파일 존재 확인만 하므로 메모리 압박이 없어 oomd 표적이 되지 않는다.
#
# OOM 5회에서 배운 것
#   - MemoryHigh 는 상시 회수를 강제해 PSI 를 올려 oomd 를 부른다 (3번째 OOM 원인).
#   - MemoryMax 도 상한 도달 시 같은 회수를 유발한다. 시스템 여유가 101 GB 인데도
#     24 G 상한 cgroup 만 죽은 것이 t134e (5번째). ⇒ 메모리 상한을 아예 걸지 않는다.
#   - 진짜 원인은 gdal.Translate 의 무제한 블록 캐시 → env 에서 GDAL_CACHEMAX=512 로 묶었다.
#   - NP=1 로 merge 를 한 번에 하나만 돌린다 (139개 중 108개는 이미 완료돼 빠르게 통과).
set -u
R=${WORK_ROOT}/CLAB_DSC
PROC=$R/proc_t134_capital
LOG=$R/logs/watchdog_t134.log
PY=${CONDA_PREFIX}/bin/python
UNIT=clab-coreg-t134w
mkdir -p "$R/logs"
say() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

say "===== 워치독 시작 (PID $$) ====="

# ---------- 1) 코레지 완주까지 감시 ----------
tries=0
while [ ! -f "$PROC/COREG_DONE" ]; do
  if systemctl --user is-active --quiet "$UNIT"; then
    sleep 180; continue
  fi
  # 죽어 있음 → 재시작
  st=$(systemctl --user show "$UNIT" -p Result --value 2>/dev/null)
  [ -n "$st" ] && say "코레지 정지 감지 (Result=$st) · merged $(ls $PROC/stack/merged/SLC 2>/dev/null | wc -l)/139"
  systemctl --user reset-failed "$UNIT" 2>/dev/null
  tries=$((tries+1))
  if [ "$tries" -gt 40 ]; then say "★재시작 40회 초과 - 워치독 중단"; exit 1; fi
  # 메모리 상한 없음(위 주석 참조) · NP=1 · oomd 회피 선호
  systemd-run --user --unit="$UNIT" --service-type=exec \
    -p ManagedOOMPreference=avoid -p ManagedOOMMemoryPressure=auto \
    -p ManagedOOMSwap=auto -p CPUQuota=300% \
    -p WorkingDirectory=$R \
    -p StandardOutput=append:$R/logs/svc_t134w.out \
    -p StandardError=append:$R/logs/svc_t134w.out \
    /bin/bash $R/run_coreg_dsc.sh t134 1 >> "$LOG" 2>&1
  say "재시작 #$tries 완료 (unit $UNIT)"
  sleep 60
done
say "▶ 코레지 완료 (COREG_DONE) · merged $(ls $PROC/stack/merged/SLC 2>/dev/null | wc -l)개"

# ---------- 2) 수도권 3지역 SBAS ----------
if [ ! -f "$R/sbas/SBAS_DONE_t134" ]; then
  systemctl --user reset-failed clab-sbas-t134 2>/dev/null
  say "SBAS 시작 (강동·서대문·광명)"
  systemd-run --user --unit=clab-sbas-t134 --service-type=exec --wait \
    -p ManagedOOMPreference=avoid -p CPUQuota=400% \
    -p WorkingDirectory=$R \
    -p StandardOutput=append:$R/logs/svc_sbas_t134.out \
    -p StandardError=append:$R/logs/svc_sbas_t134.out \
    /bin/bash $R/run_sbas_dsc.sh t134 >> "$LOG" 2>&1
  say "SBAS 종료 · DONE=$([ -f $R/sbas/SBAS_DONE_t134 ] && echo Y || echo N)"
fi

# ---------- 3) 통합맵 (지역별 공통성분 자체 판정) ----------
if [ -f "$R/sbas/SBAS_DONE_t134" ]; then
  say "통합맵 생성"
  cd "$R" && PYTHONPATH="" "$PY" make_dsc_map.py >> "$LOG" 2>&1
  say "통합맵 완료 · $(ls $R/통합맵/*.html 2>/dev/null | wc -l)개 html"
fi
say "===== 워치독 종료 ====="
