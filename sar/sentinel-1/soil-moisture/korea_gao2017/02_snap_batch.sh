#!/bin/bash
# 다운로드된 GRD 전부를 SNAP 그래프로 처리 (Gao 2017 전처리: 궤도·열잡음·σ0 보정·SRTM 30m 지형보정, 스페클필터 없음, 10 m), 인자 r=역순
cd ${WORK_ROOT}/data
ls ${1:+-r} s1_grd/*.zip | xargs -P 4 -I{} sh -c 'b=$(basename {} .zip); o=s1_proc/${b}_sigma0.tif; [ -s $o ] && exit 0; unzip -tq {} >/dev/null 2>&1 || { echo "BADZIP $b"; exit 0; }; ~/esa-snap/bin/gpt ../code/s1_gao2017.xml -q 4 -c 6G -Pinput={} -Poutput=$o >/dev/null 2>&1 && echo "ok $b" || echo "FAIL $b"'
echo BATCHDONE
