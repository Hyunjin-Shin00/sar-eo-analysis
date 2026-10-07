#!/bin/bash

# $1 : telemetry file path

fee_temps=()
cem_temps=()

while IFS= read -r line; do
  if echo "$line" | grep -q "4,0,9"; then
    temp=$(echo "$line" | awk -F',' '{gsub(/^ +| +$/, "", $NF); print $NF}')
#    timestamp=$(echo "$line" | awk -F',' '{print $1}')
#    echo "($timestamp) FEE: $temp도"
    fee_temps+=("$temp")
  elif echo "$line" | grep -q "4,0,8"; then
    temp=$(echo "$line" | awk -F',' '{gsub(/^ +| +$/, "", $NF); print $NF}')
#    timestamp=$(echo "$line" | awk -F',' '{print $1}')
#    echo "($timestamp) CEM: $temp도"
    cem_temps+=("$temp")
  fi
done < "$1"

# 요약 출력
if [ ${#fee_temps[@]} -gt 0 ]; then
  echo -n "FEE: "
  IFS=', '
  echo "${fee_temps[*]}"
fi

if [ ${#cem_temps[@]} -gt 0 ]; then
  echo -n "CEM: "
  IFS=', '
  echo "${cem_temps[*]}"
fi
