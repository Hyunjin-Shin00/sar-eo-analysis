#!/bin/bash
# DSC 병합 스택을 서울 창으로 잘라낸다. ASC 와 같은 crop_s1.py 를 환경변수로 가리켜 재사용.
set -u
D=<DATA_ROOT>/S1_DSC
source <DATA_ROOT>/CSK_PSInSAR/code/psi_env.sh
export S1_SRC_STACK="$D/stack/merged"
export S1_ROOT="$D"
date +'CROP START %F %H:%M:%S'
python -u <DATA_ROOT>/S1_PSInSAR/code/crop_s1.py all
echo "EXIT=$?"
date +'CROP END %F %H:%M:%S'
du -sh "$D/SLC" "$D/geom_reference"
