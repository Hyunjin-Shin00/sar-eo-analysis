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
