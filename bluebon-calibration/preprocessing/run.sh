#!/bin/bash

rootdir=/mnt/e/bkchoi/prep
srcdir=${rootdir}/src/03_code

zipfile=$1
line=$2

if [ -z ${zipfile} ] || [ -z ${line} ]
then
	exit
fi

if [ -f ${zipfile} ]
then
	tmp_dir=`dirname ${zipfile}`
	unzip -o ${zipfile} -d ${tmp_dir}
	datdir=`echo ${zipfile} | sed 's/.zip$//g'`
elif [ -d ${zipfile} ]
then
	datdir=${zipfile}
else
	echo ${zipfile} is not file...
	exit
fi

binfile=`ls ${datdir}/*.bin00 | head -1 | sed 's/00$//g'`

cat ${datdir}/*.bin* > ${binfile}

tiffname_head=`basename ${binfile} | cut -d- -f2 | cut -d. -f1`

${srcdir}/make_tiff/bin2png ${binfile} ${datdir}/${tiffname_head} ${line}

python ${srcdir}/01_DN_to_L.py ${datdir}
