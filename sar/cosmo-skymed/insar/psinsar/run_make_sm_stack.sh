#!/bin/bash
set -u
R=<DATA_ROOT>/CSK_PSInSAR
source "$R/code/psi_env.sh"
cd "$R/seoul/psi"
date +'START %F %H:%M:%S'
tcsh -f "$ISCE2PSI/make_single_reference_stack_isce"
echo "EXIT=$?"
date +'END %F %H:%M:%S'
