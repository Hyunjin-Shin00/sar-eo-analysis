#!/bin/bash

find /mnt/e/bkchoi/prep/data -maxdepth 1 -type f -name "*zip" -o -name "*.tar.xz" | while read zipfile
do
	dirname=`echo $zipfile | sed 's/.zip$//g' | sed 's/.tar.xz//g'`
	echo $dirname $zipfile
	if [ ! -d $dirname/radiometric ]
	then
		echo Run: $zipfile
		/mnt/e/bkchoi/prep/src/run_band.sh ${zipfile} 16000
	else
		echo Skip: $zipfile
	fi
done

/mnt/e/bkchoi/prep/src/upload.sh
/mnt/e/bkchoi/prep/src/upload4GDrive.sh

#cd /mnt/e/bkchoi/prep/data/fee_cee_temp
#./process-from-drive.sh