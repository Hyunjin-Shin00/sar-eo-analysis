#!/bin/bash

rootdir=<WORK_ROOT>/prep
srcdir=${rootdir}/src/03_code

datdir=$1
line=$2

if [ -z ${datdir} ] || [ -z ${line} ]
then
	exit
fi

binfile=`ls ${datdir}/*.bin00 | head -1 | sed 's/00$//g'`

cat ${datdir}/*.bin* > ${binfile}

tiffname_head=`basename ${binfile} | cut -d- -f2 | cut -d. -f1`

${srcdir}/make_tiff/bin2png ${binfile} ${datdir}/${tiffname_head} ${line}

cnt=`ls ${datdir}/*tiff | wc -l`

if [ $cnt == 8 ] || [ $cnt == 4 ]
then
	python ${srcdir}/01_DN_to_L_band.py ${datdir} ${cnt}
elif
	echo "Band check: $cnt"
fi