# sar/cosmo-skymed/insar

CSK 간섭처리 — ISCE2 기반.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`psinsar/`](psinsar/) | X-band PS-InSAR 체인. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `doppler_xml.py` | CSK XML 메타데이터에서 도플러 중심주파수 계수 추출 | XML | — |
| `read_h5_meta.py` | 입력 CSK HDF5 파일 | HDF5 | — |
| `run_csk_unwrap_all.sh` | CSK 간섭쌍 전체를 순차 언래핑 (snaphu) | GeoTIFF · 파일 묶음 | GeoTIFF · PNG 그림 · 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함
