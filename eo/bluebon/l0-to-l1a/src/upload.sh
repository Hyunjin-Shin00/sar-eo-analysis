#!/bin/bash


datdir=<WORK_ROOT>/prep/data
outdir=${datdir}/upload

find ${datdir} -maxdepth 2 -type d -name "radiometric" | while read dir
do
	udir=`echo $dir |sed 's/\/radiometric//g'`
	tdate=`ls ${udir}/capture-* | head -1 | xargs basename | cut -d- -f2 | cut -d. -f1`
	tdir=${outdir}/${tdate}
	echo ${tdir}
	if [ ! -d ${tdir} ]
	then
		cnt=`ls ${dir}/DN_dark_rc_*pc_v.png | wc -l`
		if [ $cnt -ge 1 ]
		then
			mkdir -p ${tdir}
			cp ${dir}/MS*dark_rc_p.tiff ${tdir}/.
			cp ${dir}/DN_dark_rc_*pc_v.png ${tdir}/.
			echo "Make: ${tdir}"
		fi
	else
		echo "Exsit Dir: ${tdir}"
	fi
done
