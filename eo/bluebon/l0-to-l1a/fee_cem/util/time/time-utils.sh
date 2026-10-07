#!/bin/bash

sec_to_ms() {
  local seconds=$1
  local epoch_ms=$((seconds * 1000))
  echo "$epoch_ms"
}

min_to_ms() {
  local minutes=$1
  local epoch_ms=$((minutes * 60 * 1000))
  echo "$epoch_ms"
}

hour_to_ms() {
  local hours=$1
  local epoch_ms=$((hours * 3600 * 1000))
  echo "$epoch_ms"
}

microseconds_to_ms() {
  local microseconds=$1
  local epoch_ms=$((microseconds / 1000))
  echo "$epoch_ms"
}

convert_to_iso8601() {
  epoch_sec=$(($1 / 1000))
  epoch_ms=$(($1 % 1000))

  iso8601_time=$(date -u -d "@$epoch_sec" +"%Y-%m-%dT%H:%M:%S")
  iso8601_with_epoch_ms=$(printf "%s.%03d\n" "$iso8601_time" "$epoch_ms")
  echo "$iso8601_with_epoch_ms"
}
