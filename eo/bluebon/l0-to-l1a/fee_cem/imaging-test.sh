#!/bin/bash

# Usage:
# . imaging-test.sh capture-250629_023708 capture-
#
# Input
# $1 : image and telemetry file prefix. (e.g., imaging-250401_123456)
# $2 : result directory prefix to remove (default: capture-)

if [ $# -lt 1 ]; then
  echo "Usage: . imaging-test.sh <file_prefix> [prefix_to_remove for result directory]" >&2
  echo "Example: . imaging-test.sh capture-250629_023708 capture-" >&2
  return 1
fi

prefix="$1"
result_dir_remove_prefix=${2:-capture-}
result_dir=${prefix//$result_dir_remove_prefix/}
telemetry_dir=result/"$result_dir"/telemetry
image_dir=result/"$result_dir"/level-1A

# Prepare result directory
chmod 777 downlink 2>/dev/null || true
rm -rf result/"$result_dir"
mkdir -p result/"$result_dir"/raw
files=(downlink/"$1".tlm*)
cp "${files[@]}" result/"$result_dir"/raw
mkdir -p "$telemetry_dir"
mkdir -p "$image_dir"

# Rename the image and telemetry files to the structured names used within the script
find ./downlink -type f -name "$prefix.bin??" -exec bash -c 'for f; do cp "$f" "$(dirname "$f")/_$(basename "$f")"; done' _ {} +
find ./downlink -type f -name "$prefix.tlm.tpx??" -exec bash -c 'for f; do cp "$f" "$(dirname "$f")/_$(basename "$f")"; done' _ {} +
find ./downlink -type f -name "$prefix.bin??" -exec rename "s/$prefix/capture/" {} +
find ./downlink -type f -name "$prefix.tlm.tpx??" -exec rename "s/$prefix/imaging-capture/" {} +

# Redirect output to a file
output_temp=result.txt
mkdir -p "$(dirname "$output_temp")"
exec > >(tee "$output_temp") 2>&1

. check-tlm.sh "$result_dir"

#echo "# 4. Image"
#. bin-to-png.sh "$result_dir" capture
#. bin-to-png.sh "$result_dir" pattern
#. bin-to-png.sh "$result_dir" test
#. bin-to-png.sh "$result_dir" readout
#
#. cmp-pattern-image.sh "$result_dir" "fm1" "current-time"
#. cmp-test-image.sh "$result_dir"
#
#echo "# 5. Image Ancillary"
#. check-bin.sh "$result_dir"
#echo

echo "# 6. Thermal"
. see-thermal.sh "$telemetry_dir"/imaging-capture.tlm

# Restore output to the terminal
exec > /dev/tty 2>&1

# Save the output to a target result file
output_file="./result/$result_dir/result.txt"
cp "$output_temp" "$output_file"
rm "$output_temp"

# Clean up
if [ -f tlm.txt ]; then
  rm tlm.txt
fi

#rm result/"$result_dir"/raw/capture.bin
find ./downlink -type f -name "_$prefix.bin??" -exec rename "s/_$prefix/$prefix/" {} +
find ./downlink -type f -name "_$prefix.tlm.tpx??" -exec rename "s/_$prefix/$prefix/" {} +
find ./downlink -type f -name "capture.bin??" -exec rm -f {} +
find ./downlink -type f -name "imaging-capture.tlm.tpx??" -exec rm -f {} +