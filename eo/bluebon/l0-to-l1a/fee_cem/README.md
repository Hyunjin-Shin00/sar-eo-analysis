# eo/bluebon/l0-to-l1a/fee_cem

FEE/CEM 보드 텔레메트리 확인과 촬영 시험 — 지상 검증 장비 쪽.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`util/`](util/) |  |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `check-tlm.sh` | FEE/CEM 텔레메트리 점검 — 온도·전압 이상 확인 | — | — |
| `imaging-test.sh` | Usage: . imaging-test.sh capture-250629_023708 capture- Input $1 : image and telemetry file prefix. (e.g., ima | TXT | — |
| `process-all.sh` | Usage: ./process-all.sh [input_dir] input_dir : .tar.xz archives are searched here (default: parent dir of thi | CSV · JSON · TXT | — |
| `process-from-drive.sh` | process-from-drive.sh — sheet-driven FEE/CEM pipeline. Finds Mission rows whose AD column is empty, matches ea | — | — |
| `process_empty_rows.py` | process_empty_rows.py — drive the FEE/CEM pipeline from the spreadsheet side. | JSON · TXT | — |
| `see-thermal.sh` | $1 : telemetry file path | — | — |
| `update_sheet.py` | update_sheet.py — push FEE/CEM values from process-all.sh output into the | CSV · JSON | — |
| `update_sheet_by_time.py` | update_sheet_by_time.py — push FEE/CEM into the Bluebon Mission sheet, | CSV · JSON | — |

## 주요 인자

- `process_empty_rows.py` — `--date` `--dry-run` `--limit`

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
| `GSPREAD_CREDENTIALS` | 구글 서비스계정 자격증명 파일 |

### 진입점

```bash
python process_empty_rows.py 
```
process_empty_rows.py — drive the FEE/CEM pipeline from the spreadsheet side. For every row in the Mission tab where column AD is empty: 1) parse the 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `rows` |  |  | optional: only process these (1-based) sheet rows |
| `--date` |  |  | only consider rows whose E datetime is on this date (YYYY-MM-DD) |
| `--dry-run` |  |  | plan only — print the row→folder matches and stop |
| `--limit` |  | `0` | cap the number of rows processed (after planning) |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `update_sheet.py` | `DATE_COL_IX` | `5` |
| `update_sheet_by_time.py` | `DATE_COL_IX` | `5` |
