# eo/bluebon/geometric/Code/web_app/backend/services

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `__init__.py` | 서비스 패키지 초기화 | — | — |
| `pipeline_service.py` | Run the geometric correction pipeline with real-time log capture. | — | — |
| `sheet_service.py` | Sheet loading, TIFF scanning, row editing. | CSV | CSV · 텍스트/로그 |
| `upload_service.py` | Google Drive 업로드 서비스. | JSON · TIF · TIFF | 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함
