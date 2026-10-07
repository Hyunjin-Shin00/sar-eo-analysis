#!/bin/bash
# Usage:
# . upload.sh mission-250908051916.tpx mission.tpx true
# $1 : source file path to
# $2 : destination file name in simulator uplink directory.
# $2 : if true, remove all contents of simulator uplink directory.

if [ "$2" = "true" ]; then
    sudo docker exec bus-file-server sh -c "rm -rf /payload/uplink/*"
fi

sudo docker cp "$1" bus-file-server:/payload/uplink/"$2"
