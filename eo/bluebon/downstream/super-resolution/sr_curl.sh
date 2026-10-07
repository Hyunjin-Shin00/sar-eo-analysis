path=`pwd`

head=`echo $1 | cut -d. -f 1`

curl -X POST "http://<INTERNAL_HOST>:8000/predict" \
     -H "accept: image/png" \
     -F "file=@$1" \
     --output ${head}_sr.png
