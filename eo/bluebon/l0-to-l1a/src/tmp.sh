#!/bin/bash

for i in `cat dirlist`
do
	input=<WORK_ROOT>/gdrive/LEOP/${i}/level-1B
	python merge_bands.py $input
done
