#!/bin/bash

find <WORK_ROOT>/prep/data -maxdepth 1 -type f -name "*zip" -o -name "*.tar.xz" | while read zipfile
do
	dirname=`echo $zipfile | sed 's/.zip$//g' | sed 's/.tar.xz//g'`
	echo $dirname $zipfile
	if [ ! -d $dirname/radiometric ]
	then
		echo Run: $zipfile
		<WORK_ROOT>/prep/src/run_band.sh ${zipfile} 16000
	else
		echo Skip: $zipfile
	fi
done

<WORK_ROOT>/prep/src/upload.sh
<WORK_ROOT>/prep/src/upload4GDrive.sh

#cd <WORK_ROOT>/prep/data/fee_cee_temp
#./process-from-drive.sh