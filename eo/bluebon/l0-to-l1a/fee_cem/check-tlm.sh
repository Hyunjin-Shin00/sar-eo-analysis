#!/bin/bash

if [ -z "$1" ] ; then
  echo "Invalid argument"
  echo "Usage: . check-tlm.sh fm1-1"
  echo "1st argument : result directory name"
  return
fi

chmod 777 downlink 2>/dev/null || true
chmod 777 bin 2>/dev/null || true
chmod 777 bin/bin2png 2>/dev/null || true
chmod 777 bin/tlm-checker 2>/dev/null || true
chmod 777 bin/tlm-checker-full 2>/dev/null || true

unpack_if_exists() {
    local source_file=$1
    local target_file=$2

    if [[ -n "$(compgen -G "$source_file")" ]]; then
        . ./util/mission/unpack-tpx.sh "$source_file" "$target_file"
    fi
}

# Unpack telemetry files
unpack_if_exists "downlink/recovery.tlm.tpx*" "result/$1/telemetry/recovery.tlm"
unpack_if_exists "downlink/gpu.tlm.tpx*" "result/$1/telemetry/gpu.tlm"
unpack_if_exists "downlink/sw-update.tlm.tpx*" "result/$1/telemetry/sw-update.tlm"
unpack_if_exists "downlink/sw-check.tlm.tpx*" "result/$1/telemetry/sw-check.tlm"
unpack_if_exists "downlink/imager-maintenance.tlm.tpx*" "result/$1/telemetry/imager-maintenance.tlm"
unpack_if_exists "downlink/test.tlm.tpx*" "result/$1/telemetry/test.tlm"
unpack_if_exists "downlink/imaging-pattern.tlm.tpx*" "result/$1/telemetry/imaging-pattern.tlm"
unpack_if_exists "downlink/imaging-capture.tlm.tpx*" "result/$1/telemetry/imaging-capture.tlm"
unpack_if_exists "downlink/imaging-readout.tlm.tpx*" "result/$1/telemetry/imaging-readout.tlm"
unpack_if_exists "downlink/thermal-control.tlm.tpx*" "result/$1/telemetry/thermal-control.tlm"

output_mission_result() {
    local result_file=$1
    if [ -e "$result_file" ]; then
        grep "info,0,0,0" "$result_file" | awk -F',' '{print $(NF-1) " : " $NF}'
    fi
}

echo "# 1. Mission Result"
# Output mission result
output_mission_result result/"$1"/telemetry/recovery.tlm
output_mission_result result/"$1"/telemetry/gpu.tlm
output_mission_result result/"$1"/telemetry/sw-update.tlm
output_mission_result result/"$1"/telemetry/sw-check.tlm
output_mission_result result/"$1"/telemetry/imager-maintenance.tlm
output_mission_result result/"$1"/telemetry/test.tlm
output_mission_result result/"$1"/telemetry/imaging-pattern.tlm
output_mission_result result/"$1"/telemetry/imaging-capture.tlm
output_mission_result result/"$1"/telemetry/imaging-readout.tlm
output_mission_result result/"$1"/telemetry/thermal-control.tlm
echo ""


echo "# 2. Network Status (BUS-Payload)"
output_network_status() {
    local result_file=$1
    local mode=$2
    if [ -e "$result_file" ]; then
        printf "%s" "$mode : "
        if grep -qE "eth0: Link is Up|eth0: Link is Down" "$result_file"; then
          echo "PASS"
        else
          echo "FAIL"
        fi
    fi
}

output_network_status result/"$1"/telemetry/gpu.tlm "GPU"
output_network_status result/"$1"/telemetry/sw-update.tlm "Maintenance(sw-update)"
output_network_status result/"$1"/telemetry/sw-check.tlm "Maintenance(sw-check)"
output_network_status result/"$1"/telemetry/imager-maintenance.tlm "Imager maintenance"
output_network_status result/"$1"/telemetry/test.tlm "Test channel"
output_network_status result/"$1"/telemetry/imaging-pattern.tlm "Imaging(pattern)"
output_network_status result/"$1"/telemetry/imaging-capture.tlm "Imaging(capture)"
output_network_status result/"$1"/telemetry/imaging-readout.tlm "Imaging(readout)"
output_network_status result/"$1"/telemetry/thermal-control.tlm "Thermal control"
echo ""

echo "# 3. Telemetry"
if [ -e "result/$1/telemetry/recovery.tlm" ]; then
  echo "# Check recovery mode result..."
  cat result/"$1"/telemetry/recovery.tlm
  echo ""
fi

if [ -e "result/$1/telemetry/gpu.tlm" ]; then
  echo "# Check gpu mode result..."
  grep "6,0,0,1" result/"$1"/telemetry/gpu.tlm
  echo ""
fi

if [ -e "result/$1/telemetry/sw-update.tlm" ]; then
  echo "# Check sw-update mode result..."
  grep -E "main hash|backup hash|startup hash|.bashrc hash|interfaces hash" result/"$1"/telemetry/sw-update.tlm
  echo ""

  echo "# Check reference sw package..."
  printf "main hash : "
  sha256sum "../develop/build/apb-main" | cut -d ' ' -f 1 | tr -d '\n'
  echo
  printf "startup hash : "
  sha256sum "../develop/startup.sh" | cut -d ' ' -f 1 | tr -d '\n'
  echo
  printf ".bashrc hash : "
  sha256sum "../develop/bashrc" | cut -d ' ' -f 1 | tr -d '\n'
  echo
  printf "/etc/network/interface hash : "
  sha256sum "../develop/network-interfaces" | cut -d ' ' -f 1 | tr -d '\n'
  echo
  echo ""
fi

if [ -e "result/$1/telemetry/imaging-capture.tlm" ]; then
  ./bin/tlm-checker result/"$1"/telemetry/imaging-capture.tlm
fi
if [ -e "result/$1/telemetry/imaging-pattern.tlm" ]; then
  ./bin/tlm-checker result/"$1"/telemetry/imaging-pattern.tlm
fi
if [ -e "result/$1/telemetry/imaging-readout.tlm" ]; then
  ./bin/tlm-checker result/"$1"/telemetry/telemetry/imaging-readout.tlm
fi
echo ""
