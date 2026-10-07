# soil-moisture — Sentinel-1 표층 토양수분 산출·논문 재현·검증

무료 위성자료(Sentinel-1, Sentinel-2, SMAP)와 공개 현장관측으로 표층 토양수분을 산출하고, 공개 논문의 방법을 그대로 적용해 수치를 재현·검증한 코드. 성공(영국)·실패(미국·국내 관측소·PINN·SMAP) 모두 기록용으로 포함한다.

경로 표기: `<WORK_ROOT>` = 작업 루트(원본 폴더 구조: `case_UK_Maslanka2022/`, `case_US_Ma2020/`, `code/`, `data/`, `outputs/`, `satchat/`, `ref_Cho2026_PINN/`). 셸 스크립트는 `${WORK_ROOT}` 환경변수를 사용한다.

## 폴더
| 폴더 | 내용 | 결과 |
|---|---|---|
| `uk_maslanka2022/` | Maslanka et al. 2022 (IEEE TGRS) TU Wien 변화탐지 재현. 영국 COSMOS-UK 3개소(CHIMN·SHEEP·WADDN), S1 VV 2016–2019 410장 | r² 부분 재현(12조합 평균 0.45 vs 논문 0.47), RMSE 재현 실패 |
| `us_ma2020/` | Ma et al. 2020 (Remote Sens.) Oh-2004 + Water Cloud Model, 미국 SCAN 2001 | 재현 실패 (R² 0.08 vs 0.597) |
| `korea_gao2017/` | Gao et al. 2017 (Sensors) S1+S2 변화탐지 방법1·2, 국내 RDA 관측소 2곳(가평·화성) 100 m | 관측소 1점 실패(R −0.13/−0.14), 지역평균–선행강수 R 0.59(가평) |
| `satchat_viz/` | 텔레픽스 SatCHAT 화면 합성(Esri 위성지도 + rSSM 레이어), 위치정합 확인, 발표용 그래프 | 시연용 합성 이미지 |
| `pinn_cho2026_check/` | Cho et al. 2026 (Zenodo, 비심사) PINN-WCM 재구현 시도 | 시간분할·무작위 CV에서 R≈0.0–0.18, 제외 |
| `verify/` | 포트폴리오 정리 시 원본 산출물에서 핵심 수치를 독립 재계산한 스크립트 | 일치 확인(notes 참조) |

## 실행 순서
### 영국 (Python: planetary-computer, rasterio, pandas)
```
python uk_maslanka2022/01_fetch_s1.py      # Planetary Computer sentinel-1-rtc 에서 관측소 주변 3.2 km 창만 원격 읽기 → s1rtc_<SITE>.npz
python uk_maslanka2022/02_incidence.py     # sentinel-1-grd annotation 으로 궤도별 입사각
python uk_maslanka2022/03_rssm_validate.py # β(Ann-Dir) 40° 정규화 → rSSM → COSMOS-UK 비교, 논문 Table IV 대조
```
### 미국
```
python us_ma2020/ma2020_scan.py            # SCAN 2001 시간자료 + S1 RTC + S2 NDWI → Oh/WCM 격자탐색 역산
```
### 국내 (SNAP gpt + Python)
```
korea_gao2017/01_download.sh               # ASF S1 GRD (~/.netrc 의 Earthdata 인증 사용; 자격증명은 코드에 없음)
korea_gao2017/02_snap_batch.sh [r]         # 궤도·열잡음·σ0 보정·SRTM 30 m 지형보정 (graph: s1_gao2017.xml)
SITE=GP python korea_gao2017/03_s2_ndvi.py # Earth Search S2 L2A NDVI, SCL 구름마스크, 100 m
SITE=GP python korea_gao2017/04_gao2017_change_detection.py
SITE=GP python korea_gao2017/05_validate_figs.py
python korea_gao2017/06_region_rain_response.py
```
화성(HS)은 `SITE=HS` 로 같은 스크립트를 사용(원본의 `_HS` 셸 변형은 경로만 다른 사본이라 제외).

### 검증 재계산
```
python verify/r1_uk.py                     # 영국 12조합 지표 + 겨울/여름 지도 통계 재계산
python verify/r2_uk_chimn250.py 250        # CHIMN 250 m 전 과정 독립 재계산 (WorldCover 원격 COG)
python verify/r3_us_kr.py                  # 미국 SCAN R², 국내 관측소·지역평균 R
python verify/r4_loso.py                   # Cho 2026 공개표로 관측소 제외(LOSO) RF vs 상수 기준선
python verify/r5_smap.py <smap_extract_dir> # SMAP L3E 예비 추출분 vs RDA 현장
python verify/fig_us_scan.py <retrievals.csv> <out.png>
```

## 방법 요약 (영국, TU Wien 변화탐지)
1. σ0(dB) = 10·log10(γ0_RTC·cosθ), σ0 > −5 dB 또는 < −22 dB 제외
2. β = (궤도30 평균 σ0 − 궤도132 평균 σ0)/(θ30 − θ132), σ0(40°) = σ0(θ) − β(θ − 40)
3. 선형 평균으로 100/250/500/1000 m 집계
4. σd = P10 − (P90−P10)/8, σw = P90 + (P90−P10)/8, rSSM = (σ−σd)/(σw−σd)·100
5. COSMOS-UK VWC를 min-max 지수화, 양쪽 14회 이동평균 후 r²·RMSE

## 논문과 다르게 처리한 부분
- σ0를 SNAP 처리 대신 Planetary Computer RTC γ0·cosθ로 근사, Refined Lee 미적용, 토지피복 마스크를 ESA WorldCover로 대체
- 논문 미기재 항목(셀 정렬, 선형/dB 평균, 이동평균 창 위치)은 임의 선택

## 주의
- 산출물은 상대값(0–100%)이다. 체적 함수량이 필요하면 현장값으로 별도 보정해야 한다.
- 원본 데이터(npz, GeoTIFF, xlsx)와 논문 PDF는 포함하지 않는다. Cho 2026 Zenodo 자료는 해당 레코드에서 직접 받아야 한다.
- `satchat_viz/make_satchat.py`는 SatCHAT UI 스크린샷(`satchat.png`)과 Esri World Imagery 타일이 필요하다. 결과 이미지는 실제 서비스 화면이 아닌 시연용 합성이다.
