#!/usr/bin/env bash
set -euo pipefail

# 배치 실행 스크립트: geometric_correction.py의 CURRENT_SET 값을 순회하며 전체 셋 실행
# 실행 전 요구사항:
#  - Python 환경 활성화 (필요 시)
#  - 데이터셋 경로 유효성 확인

REPO_ROOT="/media/<USER>/X10 Pro/04.Code/03.geometric_correction/03.geometric_correction"
PY_FILE="$REPO_ROOT/geometric_correction.py"

# 순회할 실험 셋 (파일 내 EXPERIMENT_SETS 키와 동일해야 함)
# Thailand_18과 Thailand_22의 top/center/bottom 6개 셋만 실행
SETS=(
  "Thailand_18_top" "Thailand_18_center" "Thailand_18_bottom"
  "Thailand_22_top" "Thailand_22_center" "Thailand_22_bottom"
)

# 백업 생성 (원복용)
TMP_BACKUP="$(mktemp)"
cp "$PY_FILE" "$TMP_BACKUP"

cleanup() {
  echo "Restoring original geometric_correction.py ..."
  cp "$TMP_BACKUP" "$PY_FILE"
  rm -f "$TMP_BACKUP"
}
trap cleanup EXIT

echo "Batch run started at: $(date '+%Y-%m-%d %H:%M:%S')"

for SET in "${SETS[@]}"; do
  echo "============================================================"
  echo "Running set: $SET"
  echo "============================================================"

  # CURRENT_SET 값을 해당 셋으로 변경
  # 참고: 라인 내 공백/주석이 조금 달라도 작동하도록 넉넉한 정규식 사용
  sed -i -E "s/^(\s*)CURRENT_SET\s*=\s*\".*\"/\1CURRENT_SET = \"${SET}\"/" "$PY_FILE"

  # 실행 (출력되는 OUTPUT_DIR는 각 셋의 정의에 따름)
  # 개별 셋의 로그는 해당 OUTPUT_DIR 내부의 pipeline_output.log에도 남지만,
  # 여기에서도 별도로 한 벌 저장
  LOG_DIR="$REPO_ROOT/batch_logs"
  mkdir -p "$LOG_DIR"
  LOG_FILE="$LOG_DIR/${SET}_$(date '+%Y%m%d_%H%M%S').log"

  # -u (unbuffered)로 실시간 로그
  python -u "$PY_FILE" | tee "$LOG_FILE"

done

echo "Batch run finished at: $(date '+%Y-%m-%d %H:%M:%S')"


