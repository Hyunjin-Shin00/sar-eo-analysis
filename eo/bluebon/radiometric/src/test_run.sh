#!/bin/bash

rdir=<WORK_ROOT>/data

cat flist.txt | awk '{print $11}' | cut -d/ -f 2 | while read t
do
	dir=${rdir}/${t}
	python pipeline.py ${dir}
done