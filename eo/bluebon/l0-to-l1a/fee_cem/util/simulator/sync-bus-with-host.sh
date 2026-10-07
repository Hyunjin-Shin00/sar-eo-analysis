#!/bin/bash

bus_ip=127.0.0.1

while true; do
    current_system_time=$(date +%s%3N)
    curl -X PUT "$bus_ip":8080/stub/time -H "Content-Type: application/json" -d "{\"timestamp\":${current_system_time}}" > /dev/null 2>&1
    sleep 0.1
done
