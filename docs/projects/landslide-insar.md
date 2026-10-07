# landslide-insar

Sentinel-1 버스트 SLC 를 PyGMTSAR 로 SBAS + PS 처리해 산사태 사면의 LOS 변위속도를 산출하는 스크립트와, 산사태 지점 기반 검증 스크립트.

## 파일
| 파일 | 내용 |
|---|---|
| `gyeongju_2022_sbas_ps.py` | 경주(Sentinel-1 상승 IW2 VV, 2022) SBAS+PS 전체 파이프라인. 버스트 다운로드 → 정렬·지오코딩 → PS 함수/육지마스크 → 다중룩 간섭도(60일 이내 쌍) → 결맞음 기반 쌍 선별 → SNAPHU 언랩 → 지형·좌표 추세 회귀 제거 → lstsq 시계열 → 속도·STL 시계열 → 단일룩 PS → SBAS/PS 비교 → GeoTIFF 저장. 단계별 결과 캐시를 재사용(이미 있으면 건너뜀). |
| `karakoram_2023_2025_sbas_ps.py` | 같은 파이프라인, 파키스탄 카라코람 POI(74.70E 36.27N), IW1, 2023–2024, CORRLIMIT 0.35. |
| `validate_landslide_points.py` | 지점 지도 래스터에서 산사태 표시(빨간 점) 좌표를 추출하고, 각 실행의 SBAS/PS 속도를 지점(3×3 평균)과 배경 화소로 나눠 Mann-Whitney U 로 비교. |

## 실행 환경
- conda env(pygmtsar, GMTSAR, SNAPHU, dask, rioxarray). PROJ 데이터는 `$CONDA_PREFIX/share/proj` 를 사용.
- 작업 루트: 환경변수 `WORK_ROOT` (스크립트 내 `<WORK_ROOT>/landslide/<지역>/{data,work,output}`).
- ASF 버스트 다운로드 자격증명: `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` 환경변수 (NASA Earthdata 계정).
- 검증 스크립트: `DATA_ROOT` 환경변수.

## 주의
- 처리 흐름은 PyGMTSAR 공식 예제(Lake Sarez landslide 노트북)를 바탕으로 스크립트화·개작한 것.
- 출력 속도는 LOS(mm/yr). 별도 노트북에서 만든 수직 변환본은 `V_LOS × cosθ` 로 계산되어 있었음 — 수직운동 가정이면 `V_LOS / cosθ` 가 맞음(여기 번들 스크립트에는 수직 변환 없음).
- 숲이 덮인 산지(경주)에서는 C밴드 결맞음 중앙값이 0.16 수준이라 속도장이 잡음 지배였음. 결과 해석 시 SBAS–PS 상호 일치도(r)를 먼저 볼 것.
