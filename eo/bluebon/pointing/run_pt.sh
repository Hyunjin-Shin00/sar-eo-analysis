#!/bin/bash

input_file=$1
output_file=./output.txt

sdir=<WORK_ROOT>/pointing

sed -i 's/\t/ /g' ${input_file}
sed -i 's/([0-9]*)//g' ${input_file}

rm -rf ${output_file}
cat ${input_file} | while read t t_lat t_lon c_lat c_lon
do
	python ${sdir}/pointing_across_along_cal.py ${t} ${t_lat} ${t_lon} ${c_lat} ${c_lon} >> ${output_file}

done
