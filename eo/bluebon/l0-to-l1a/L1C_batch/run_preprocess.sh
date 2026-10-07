#!/bin/bash

hdir=/mnt/e/bkchoi/working
sdir=${hdir}/preprocess_script
rdir=${hdir}/radiometric_correction/src
gdir=${hdir}/BlueBON_Geometric_Correction_V3/Code

ddir=/mnt/e/bkchoi/data

cat ${sdir}/BlueBON_reprocess_matched_latlon2.txt | while read name otime dtime lat lon
do
    tdir=${ddir}/${dtime}
    n=`ls ${tdir}/*tiff 2>/dev/null | wc -l`

    if [ $n -eq 8 ]
    then
        l1a_file=${tdir}/radiometric_v5/bb_l1a_20${dtime}_8band.tiff

        if [ -f ${l1a_file} ]
        then
            #echo "Run | ${dtime} | `date  "+%Y-%M-%d %H:%M:%S KST"` | Radiometric correction"

            #conda run -n prep python ${rdir}/pipeline.py ${tdir}

            l1c_file=${tdir}/radiometric_v5/level-1C/bb_l1c_20${dtime}_8band.tiff

            if [ ! -f ${l1c_file} ]
            then
                echo "Finish | ${dtime} | `date  "+%Y-%M-%d %H:%M:%S KST"` | Radiometric correction"
                echo "Run | ${dtime} | `date  "+%Y-%M-%d %H:%M:%S KST"` | Geometric correction"
                conda run -n geo_correctionv2 python ${gdir}/Full_processing_v2.py --input ${l1a_file} \
                                                                    --lat ${lat} --lon ${lon}

                echo "Finish | ${dtime} | `date  "+%Y-%M-%d %H:%M:%S KST"` | Geometric correction"
            else
                #echo "Error | ${dtime} | `date  "+%Y-%M-%d %H:%M:%S KST"` | Radiometric correction"
                echo "skip | ${dtime} | `date  "+%Y-%M-%d %H:%M:%S KST"` | Geometric correction"
                
                continue
            fi
        # else
        #     echo "Skip | ${dtime} | `date  "+%Y-%M-%d %H:%M:%S KST"` | Radiometric correction file exist"
        fi
    else
        echo Skip ${tdir}: Raw Tiff: $n files
    fi

done