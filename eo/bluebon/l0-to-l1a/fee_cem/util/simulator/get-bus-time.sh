#!/bin/bash

# Fetch the JSON data
json_data=$(curl -s http://127.0.0.1:8080/time)

# Extract the timestamp using jq
timestamp=$(echo "$json_data" | jq -r '.timestamp')

# Convert the timestamp from milliseconds to seconds
timestamp_seconds=$((timestamp / 1000))

# Format the timestamp into a human-readable format
formatted_time=$(date -u -d @"$timestamp_seconds" +"%Y-%m-%dT%H:%M:%S.%3N")

# Output the formatted time
echo "$formatted_time"
