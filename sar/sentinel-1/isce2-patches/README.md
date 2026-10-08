# sar/sentinel-1/isce2-patches

ISCE2가 지원하지 않는 Sentinel-1D 를 쓰기 위한 패치.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `apply_s1d_patch.py` | ISCE2 2.6.x 의 TOPS Sentinel1 리더에 Sentinel-1D 미션 ID 를 추가함. | — | — |
| `verify_offset.py` | S1D 절대궤도→상대궤도 offset 을 관측값으로 역산·검증함. | — | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `apply_s1d_patch.py`
