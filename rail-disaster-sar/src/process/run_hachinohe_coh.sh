#!/usr/bin/env bash
# 八戸線 本八戸~小中野 고가교 — 2025-12-08 青森県東方沖 지진(Mj7.5, 八戸 진도 6강).
#  약 20개소 손상, 第2柏崎高架橋 약 400 m 기둥 曲げ破壊, 12/30 전선 재개.
# 도시 고가교이므로 추정창을 좁히고(2/8) 2룩·10 m 격자로 해상도를 지킨다.
R=${WORK_ROOT:?set WORK_ROOT}
T=${T:-t46}
case "$T" in
  t46)  SRC=$R/data/raw/burst_hachinohe_t46;  SW=IW1
        P="1127:1209 1115:1127 1209:1221 1103:1115 1221:0102" ;;
  t141) SRC=$R/data/raw/burst_hachinohe_t141; SW=IW3
        P="1128:1210 1116:1128 1210:1222 1104:1116 1222:0103" ;;
  *) echo "T=t46|t141"; exit 1 ;;
esac
exec "$R/src/process/run_coh_pairs.sh" "$SRC" "hachinohe_${T}" "$SW" \
  "POLYGON((141.38 40.44,141.60 40.44,141.60 40.62,141.38 40.62,141.38 40.44))" \
  2 8 2 10.0 ${@:-$P}
