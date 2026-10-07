#!/bin/bash
set -u
R=<DATA_ROOT>/CSK_PSInSAR
SB=<DATA_ROOT>/S1_PSInSAR/sbas
source "$R/code/psi_env.sh"
cd "$SB/mintpy"
date +'START %F %H:%M:%S'
smallbaselineApp.py "$SB/mintpy/seoul_s1.txt" --work-dir "$SB/mintpy"
echo "EXIT=$?"
date +'END %F %H:%M:%S'
