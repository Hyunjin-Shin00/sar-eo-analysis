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
