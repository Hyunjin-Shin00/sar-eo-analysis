#!/bin/bash
# sp_auth.sh — SatRev SharePoint(teams/external) 를 rclone 원격 'satrev:' 로 등록한다.
# 실행하면 로그인 URL 이 출력된다. 윈도우 브라우저에서 열어 Microsoft 계정으로 로그인하면
# 인증이 끝나고 토큰이 자동으로 rclone.conf 에 저장된다.
set -u
RCLONE=~/.local/bin/rclone2
TENANT=1f449af8-8a3f-4c97-a307-f27ed0ab84e4          # satrevolution.onmicrosoft.com
SITE_HOST=satrevolution.sharepoint.com
SITE_PATH=/teams/external
REMOTE=satrev
OUT=$(mktemp)

BLOB=$(echo -n "{\"tenant\":\"$TENANT\",\"drive_type\":\"documentLibrary\"}" | base64 -w0 | tr '+/' '-_' | tr -d '=')
echo "### 아래 URL 을 브라우저에서 열고 로그인하세요 (satrevolution SharePoint 에 접근 가능한 계정)"
$RCLONE authorize onedrive "$BLOB" --auth-no-open-browser 2>&1 | tee "$OUT"

TOKEN=$(sed -n '/^{/,/^}/p' "$OUT" | tr -d '\n')
if [ -z "$TOKEN" ]; then
  TOKEN=$(grep -oE '\{"access_token".*\}' "$OUT" | head -1)
fi
rm -f "$OUT"
if [ -z "$TOKEN" ]; then echo "!! 토큰을 얻지 못했습니다"; exit 1; fi

$RCLONE config create "$REMOTE" onedrive tenant="$TENANT" drive_type=documentLibrary token="$TOKEN" --non-interactive >/dev/null

# site → 문서 라이브러리 drive id 조회
ACCESS=$(echo "$TOKEN" | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
DRIVE_ID=$(curl -s -H "Authorization: Bearer $ACCESS" \
  "https://graph.microsoft.com/v1.0/sites/${SITE_HOST}:${SITE_PATH}:/drive" \
  | python3 -c 'import sys,json; j=json.load(sys.stdin); print(j.get("id","")); print(j.get("error",""), file=sys.stderr)')
if [ -z "$DRIVE_ID" ]; then echo "!! drive id 조회 실패"; exit 1; fi
$RCLONE config update "$REMOTE" drive_id="$DRIVE_ID" --non-interactive >/dev/null

echo "### 등록 완료: ${REMOTE}:  (drive_id=$DRIVE_ID)"
echo "### 확인:"
$RCLONE lsd "${REMOTE}:TelePIX/00_LEOPS/" 2>&1 | head
