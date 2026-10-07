#!/bin/bash
# ASF SLC 내려받기.
# wget 은 datapool -> CloudFront 리다이렉트에서 자격증명을 넘기지 못해 403 이 난다.
# curl 로 쿠키자를 유지하면서 리다이렉트를 따라가야 한다.
set -u
D=<DATA_ROOT>/S1_DSC
CJ="$D/aux/cookies.txt"
cd "$D/SLC"
date +'START %F %H:%M:%S'
n=0; ok=0; fail=0
while read -r url; do
  f=$(basename "$url"); n=$((n+1))
  if [ -s "$f" ] && unzip -t "$f" >/dev/null 2>&1; then
    echo "SKIP [$n] $f"; ok=$((ok+1)); continue
  fi
  echo "GET  [$n] $f"
  # -C - 로 이어받기. 실패하면 한 번 더.
  for try in 1 2 3; do
    code=$(curl -sL --netrc -c "$CJ" -b "$CJ" -C - --retry 3 --retry-delay 10 \
                --max-time 7200 -o "$f" -w '%{http_code}' "$url")
    if unzip -t "$f" >/dev/null 2>&1; then break; fi
    echo "  재시도 $try (http=$code)"; sleep 20
  done
  if unzip -t "$f" >/dev/null 2>&1; then
    echo "OK   [$n] $f  $(du -h "$f"|cut -f1)"; ok=$((ok+1))
  else
    echo "FAIL [$n] $f (http=$code)"; fail=$((fail+1))
  fi
done < "$D/aux/urls.txt"
echo "done ok=$ok fail=$fail / $n"
du -sh "$D/SLC"
date +'END %F %H:%M:%S'
