#!/bin/bash
# Usage: merge_bands.sh <radiometric_dir>
# MS1,MS2,MS3_DN_dark_rc_p.tiff 를 3밴드 MS123_DN_dark_rc_p.tiff 로 병합

dir=${1:-.}
out=$dir/MS123_DN_dark_rc_p.tiff
vrt=$dir/MS123_DN_dark_rc_p.vrt

for b in 1 2 3
do
	if [ ! -f $dir/MS${b}_DN_dark_rc_p.tiff ]
	then
		echo Missing: $dir/MS${b}_DN_dark_rc_p.tiff
		exit 1
	fi
done

if [ ! -f $out ]
then
	echo Run: $out
	gdalbuildvrt -separate $vrt $dir/MS1_DN_dark_rc_p.tiff $dir/MS2_DN_dark_rc_p.tiff $dir/MS3_DN_dark_rc_p.tiff
	gdal_translate -co COMPRESS=DEFLATE -co BIGTIFF=IF_SAFER $vrt $out
	rm -f $vrt
else
	echo Skip: $out
fi
