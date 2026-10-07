# umbra-sar — 초고해상도 상용 SAR

Umbra(25 cm급) SAR 데이터를 직접 읽고 σ⁰를 산출한다.

## 파일

| 파일 | 역할 |
|---|---|
| `view_umbra_sicd.py` | SICD(NITF) 복소 SAR 데이터 직접 파싱·표시 |
| `sigma0/calc.py` | 복소 진폭 → σ⁰ 변환 계산 |
| `sigma0/file_io.py` | SICD / GEC 입출력 |
| `sigma0/main.py` | 실행 진입점 |

## SICD vs GEC

| 산출물 | 성격 | 용도 |
|---|---|---|
| **SICD** (NITF) | 복소수, 슬랜트 레인지 | 간섭 처리, 위상 활용 |
| **GEC** (GeoTIFF) | 진폭, 타원체 지오코딩 | 육안 판독, GIS 중첩 |

## 적용

인도네시아 디엥(Dieng) 화산, 남극 에레부스(Erebus) 화산.

## 관찰

25 cm에서는 개별 차량과 구조물까지 식별된다 — Sentinel-1(10 m)과는 다른 용도다.
다만 **해상도가 높다고 간섭 처리가 쉬워지지는 않는다.**
InSAR에는 짧은 재방문 주기와 궤도 정밀도가 해상도보다 중요하다.
