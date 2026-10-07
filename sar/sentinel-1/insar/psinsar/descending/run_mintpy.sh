#!/bin/bash
set -u
source <DATA_ROOT>/CSK_PSInSAR/code/psi_env.sh
W="$1"; T="$2"
cd "$W"; date +'START %F %H:%M:%S'
smallbaselineApp.py "$T" --work-dir "$W"; echo "EXIT=$?"
date +'END %F %H:%M:%S'
