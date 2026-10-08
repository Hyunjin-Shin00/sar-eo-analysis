#!/bin/bash

ddir=<WORK_ROOT>/prep/data
cdir=${ddir}/upload
gdir=<WORK_ROOT>/gdrive/LEOP

find ${cdir} -maxdepth 1 -type d -name "??????_??????" | while read dir
do
	tdate=`basename $dir`
	tdir=${cdir}/GDrive/${tdate}
	echo ${tdate}
	if [ ! -d ${gdir}/${tdate} ]
	then
		cnt=`ls ${dir}/DN_dark_rc_*pc_v.png | wc -l`
		cnt2=`find ${ddir} -type f -name "${tdate}*tiff" | wc -l`
		if [ $cnt -ge 0 ] && [ $cnt2 -ge 2 ]
		then
			mkdir -p ${tdir}/level-1A
			mkdir -p ${tdir}/level-0
			mkdir -p ${tdir}/raw

			rm -rf ${tdir}/level-1A/*
			rm -rf ${tdir}/level-0/*
			rm -rf ${tdir}/raw/*

			find ${ddir} -maxdepth 2 -type f -name "capture-${tdate}*" -exec cp {} ${tdir}/raw/. \;
			find ${ddir} -maxdepth 2 -type f -name "${tdate}*tiff" -exec cp {} ${tdir}/level-0/. \;
			find ${ddir} -maxdepth 2 -type f -name "${tdate}*png" -exec cp {} ${tdir}/level-0/. \;
			python merge_bands.py ${dir}
			l1a_png=`basename ${dir}/bb_*tiff | tail -1 | sed 's/_l1a_/_l1a-rgb_/g' | cut -d_ -f1-4`
			cp ${dir}/DN_dark*png ${tdir}/level-1A/${l1a_png}.png
			mv ${dir}/bb_*tiff ${tdir}/level-1A/.
			#rclone copy ${tdir} gdrive:LEOP/${tdate} && rm -rf ${tdir}
			echo "GoogleDrive upload prog: ${tdir}" 
		else
			echo "Check Files: "
			ls ${dir}/DN_dark_rc_*pc_v.png
			find ${ddir} -type f -name "${tdate}*tiff"
		fi
	else
		echo "Exsit Dir: ${gdir}/${tdate}"
	fi

done