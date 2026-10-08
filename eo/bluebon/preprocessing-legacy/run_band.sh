#!/bin/bash

rootdir=<WORK_ROOT>/prep
srcdir=${rootdir}/src/03_code

zipfile=$1
line=$2

if [ -z ${zipfile} ] || [ -z ${line} ]
then
	exit
fi

if [[ "$zipfile" == *.zip ]]
then
	#tmp_dir=`dirname ${zipfile}`
	datdir=`echo ${zipfile} | sed 's/.zip$//g'`
	#unzip -o "${zipfile}" -d "${tmp_dir}"
	mkdir -p ${datdir}
	bsdtar --strip-components=1 -xf ${zipfile} -C "${datdir}"
elif [[ "$zipfile" == *.tar.xz ]]
then
	datdir=`echo ${zipfile} | sed 's/.tar.xz$//g'`
	mkdir -p ${datdir}
	tar -xJf ${zipfile} -C "${datdir}" --strip-components=3
elif [ -d ${zipfile} ]
then
	datdir=${zipfile}
else
	echo "${zipfile} is not file or directory"
	exit
fi

binfile=`ls ${datdir}/*.bin00 | head -1 | sed 's/00$//g'`

cat ${datdir}/*.bin* > ${binfile}

tiffname_head=`basename ${binfile} | cut -d- -f2 | cut -d. -f1`

${srcdir}/make_tiff/bin2png ${binfile} ${datdir}/${tiffname_head} ${line}

cnt=`ls ${datdir}/*tiff | wc -l`

if [ $cnt -eq 8 ] || [ $cnt -eq 4 ]
then
	python ${srcdir}/01_DN_to_L_band.py ${datdir} ${cnt}
else
	echo "Band check: $cnt"
fi