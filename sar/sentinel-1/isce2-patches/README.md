# sar/sentinel-1/isce2-patches

ISCE2가 지원하지 않는 Sentinel-1D 를 쓰기 위한 패치.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `apply_s1d_patch.py` | ISCE2 2.6.x 의 TOPS Sentinel1 리더에 Sentinel-1D 미션 ID 를 추가한다. | — | — |
| `verify_offset.py` | S1D 절대궤도→상대궤도 offset 을 관측값으로 역산·검증한다. | — | — |
