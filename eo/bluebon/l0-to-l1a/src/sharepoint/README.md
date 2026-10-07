# eo/bluebon/l0-to-l1a/src/sharepoint

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `sp_auth.sh` | sp_auth.sh — SatRev SharePoint(teams/external) 를 rclone 원격 'satrev:' 로 등록함. 실행하면 로그인 URL 이 출력됨. 윈도우 브라우저에서 열 | — | — |
| `sp_download_unprocessed.py` | SharePoint 에서 미처리 원시 파일 내려받기 (시트 목록 대조) | JSON · ZIP | 텍스트/로그 |

## 주요 인자

- `sp_download_unprocessed.py` — `--dry-run` `--limit` `--list` `--since`
