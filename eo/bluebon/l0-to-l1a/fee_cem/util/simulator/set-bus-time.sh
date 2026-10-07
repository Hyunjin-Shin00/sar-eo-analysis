#!/bin/bash

if [ -z "$1" ]; then
  echo "Invalid: No timestamp argument"
  echo "Usage: . set-bus-time.sh 1727785090000"
  exit 1
fi

timestamp="$1"

# Check if the input timestamp is in seconds (10 digits)
if [[ ${#timestamp} -eq 10 ]]; then
  timestamp="${timestamp}000"
fi

curl -X PUT 127.0.0.1:8080/stub/time -H "Content-Type: application/json" -d "{\"timestamp\":${timestamp}}"

echo ""
. get-bus-time.sh