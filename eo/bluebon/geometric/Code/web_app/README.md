# eo/bluebon/geometric/Code/web_app

처리 상태를 보는 웹 UI (FastAPI + React).

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`backend/`](backend/) |  |

## ⚠ 보안

이 백엔드는 **인증이 없고 CORS 가 `*` 로 열려 있다** (`backend/main.py`).
내부망 전용으로만 띄우고, 외부에 노출하지 말 것.
Earth Engine 인증키는 이미지에 넣지 말고 실행 시 볼륨으로 마운트함
(`docker/run.sh` 의 `--key` 참고).
