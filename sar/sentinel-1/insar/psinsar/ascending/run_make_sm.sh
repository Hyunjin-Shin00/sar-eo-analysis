#!/bin/bash
set -u
R=<DATA_ROOT>/CSK_PSInSAR
S1=<DATA_ROOT>/S1_PSInSAR
source "$R/code/psi_env.sh"
cd "$S1"
date +'START %F %H:%M:%S'
tcsh -f "$ISCE2PSI/make_single_reference_stack_isce"
echo "EXIT=$?"
date +'END %F %H:%M:%S'
