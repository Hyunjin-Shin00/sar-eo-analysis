#!/bin/bash

ddir=/mnt/e/bkchoi/prep/data
cdir=${ddir}/upload/complete

find ${cdir} -maxdepth 1 -type d -name "??????_??????" | while read dir
do
	tdate=`basename $dir`
	tdir=${cdir}/GDrive/${tdate}
	echo ${tdate}
	if [ ! -d ${tdir} ]
	then
		cnt=`ls ${dir}/DN_dark_rc_*pc_v.png | wc -l`
		cnt2=`find ${ddir} -type f -name "${tdate}*tiff" | wc -l`
		if [ $cnt -ge 1 ] && [ $cnt2 -ge 4 ]
		then
			mkdir -p ${tdir}
			mv ${dir} ${tdir}/level-1B
			mkdir -p ${tdir}/level-1A
			mkdir -p ${tdir}/raw
			find ${ddir} -maxdepth 2 -type f -name "${tdate}*tiff" -exec mv {} ${tdir}/level-1A/. \;
			find ${ddir} -maxdepth 2 -type f -name "${tdate}*png" -exec mv {} ${tdir}/level-1A/. \;
			find ${ddir} -maxdepth 2 -type f -name "capture-${tdate}*" -exec mv {} ${tdir}/raw/. \;
			echo "GoogleDrive upload prog: ${tdir}"
		fi
	else
		echo "Exsit Dir: ${tdir}"
	fi
done
