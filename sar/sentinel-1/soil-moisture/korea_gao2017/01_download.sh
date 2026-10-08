#!/bin/bash
# ASF에서 Sentinel-1 GRD 다운로드 (~/.netrc Earthdata 인증), 4개 병렬
cd ${WORK_ROOT}/data/s1_grd
CK=$(mktemp)
xargs -P 4 -I{} sh -c 'f=$(basename {}); [ -s "$f" ] && unzip -tq "$f" >/dev/null 2>&1 && exit 0; curl -sL -n -c '$CK' -b '$CK' --retry 5 -o "$f" {} && echo "done $f"' < urls.txt
echo ALLDONE
