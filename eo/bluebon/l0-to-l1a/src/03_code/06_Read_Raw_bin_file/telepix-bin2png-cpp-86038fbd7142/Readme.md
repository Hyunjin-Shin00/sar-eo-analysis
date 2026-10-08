# eo/bluebon/l0-to-l1a/src/03_code/06_Read_Raw_bin_file/telepix-bin2png-cpp-86038fbd7142

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `check_tiff.py` | bin2png 산출 TIFF 무결성 점검 | TIFF | — |
| `package.sh` | bin2png 바이너리 패키징 | — | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `check_tiff.py`
