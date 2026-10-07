#!/bin/bash
set -u
R=<DATA_ROOT>/CSK_PSInSAR
source "$R/code/psi_env.sh"
cd "$R/seoul/psi/INSAR_20260420"
DA=${DA:-0.4}; RG=${RG:-5}; AZ=${AZ:-4}
date +'START %F %H:%M:%S'
echo "mt_prep_isce $DA $RG $AZ 50 50   (격자 13881az x 20001rg)"
mt_prep_isce "$DA" "$RG" "$AZ" 50 50
echo "EXIT=$?"
date +'END %F %H:%M:%S'
