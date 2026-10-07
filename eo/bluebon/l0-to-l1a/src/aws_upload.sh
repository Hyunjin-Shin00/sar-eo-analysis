#!/bin/bash

DNS=https://telepix-fs.satrev.space

input_data=$1
echo $input_data
if [ -d ${input_data} ]
then
	tar -cJf ${input_data}.tar.xz ${input_data}
	input_data=${input_data}.tar.xz
fi

aws s3 cp ${input_data} s3://telepix/processed_images/ --endpoint-url ${DNS}
aws s3api head-object --bucket telepix --key processed_images/${input_data} --endpoint-url ${DNS}
