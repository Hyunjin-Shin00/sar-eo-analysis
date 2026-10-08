# eo/bluebon/l0-to-l1a/src/sharepoint

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `sp_auth.sh` | sp_auth.sh — SatRev SharePoint(teams/external) 를 rclone 원격 'satrev:' 로 등록함. 실행하면 로그인 URL 이 출력됨. 윈도우 브라우저에서 열 | — | — |
| `sp_download_unprocessed.py` | SharePoint 에서 미처리 원시 파일 내려받기 (시트 목록 대조) | JSON · ZIP | 텍스트/로그 |

## 주요 인자

- `sp_download_unprocessed.py` — `--dry-run` `--limit` `--list` `--since`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 환경변수

| 이름 | 설명 |
|---|---|
| `BLUEBON_SHEET_ID` | 미션 시트 ID |

### 진입점

```bash
python sp_download_unprocessed.py 
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--list` |  |  |  |
| `--dry-run` |  |  |  |
| `--limit` |  | `0` |  |
| `--since` |  |  |  |
