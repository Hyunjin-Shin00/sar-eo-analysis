# passive-microwave/sea-ice/download

원자료 자동 수집.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `osisaf_sic.py` | OSISAF 해빙 농도(Sea Ice Concentration) 자동 다운로드 스크립트 v2 | NC · TXT | 텍스트/로그 |
| `smos_sit.py` | SMOS L3C Sea Ice Thickness (SIT) 자동 다운로드 스크립트 | NC · TXT | 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `osisaf_sic.py` | `FTP_BASE_DIR` | `/archive/ice/conc` |
|  | `LOCAL_DOWNLOAD_DIR` | `<DATA_ROOT>_NSR\OSI_SAF\conc` |
| `smos_sit.py` | `FTP_BASE_DIR` | `/SMOS/L3_SIT/L3C/north` |
|  | `LOCAL_DOWNLOAD_DIR` | `<DATA_ROOT>\14_NSR\SMOS\Thickness` |
