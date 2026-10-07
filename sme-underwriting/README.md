# sme-underwriting — 중소 공장(SME) 물건 인수심사용 공간정보 분석

국내 대형 손해보험사 대상 PoC(위성·공간정보 기반 인수심사)에서 **본인이 작성한 부분**만 담았다.
건물 탐지 모델(DINOv3+Mask2Former)·이격거리·적재물·대장 대조 판정 파이프라인은 동료 개발자 저장소이므로 포함하지 않는다.

## 파일
| 파일 | 역할 |
|---|---|
| `special_bld_gap.py` | GIS건물통합정보에서 성서산단 9개 법정동 공장(A29='17000')을 PNU별로 묶어 연면적 3,000㎡(특수건물 기준) 미만 비율 산출 + 지도·분포·법정동 막대 그림 |
| `ksic_link.py` | 지번 → 공장등록현황 업종명 → KSIC 11차 대·중분류 연결. 단일 지번 조회와 단지 전체 매칭률(`--coverage`) |
| `fig_ksic_mix.py` | 성서산단 등록 공장의 KSIC 중분류 구성 막대 그림 |
| `profile_phase0.py` | 공장등록현황 CSV 프로파일링(컬럼 검증·단지명·업종 빈도·결측률·지번 표기 패턴·주소 중복도) |
| `profile_dbf.py` | 익명 필드(A0~A39) shapefile 속성 값 분포 프로파일 — 필드 의미 역판별용 |
| `verify_field_mapping.py` | 역판별 매핑 검증: ID 유일성, 건폐율=A23/A22, 용적률=A24/A22, 주차면적=A36×11.5 |
| `factory_by_sgg.py` | 시군구별 공장 건물 수, 달서구 공장 상위 법정동 |
| `fig_workflow.py`, `fig_source_coverage.py` | 개요도·정보원 커버리지 그림 |

## 입력 데이터 (번들에 없음)
- GIS건물통합정보 일반건축물 `AL_D162_27_20260115.shp` (국가공간정보포털, EPSG:5186, CP949)
- `대구광역시_제조업체(공장등록업체)현황_20250707.csv` (data.go.kr 15069132, cp949, 11,744행)
- KSIC 11차 연계표 정제본 CSV (국세청 홈택스 게시 업종코드-KSIC 연계표에서 정제)

## 실행
```bash
python special_bld_gap.py <DATA_ROOT>/ledger/daegu_27/AL_D162_27_20260115.shp --fig out/
python ksic_link.py <DATA_ROOT>/factory/factory.csv <DATA_ROOT>/ksic/KSIC_11.csv "대구 달서구 호산동 702-5" --coverage 성서
python profile_phase0.py <DATA_ROOT>/factory/factory.csv
python verify_field_mapping.py <DATA_ROOT>/ledger/daegu_27/AL_D162_27_20260115.dbf
```
의존성: GDAL(osgeo), pandas, numpy, matplotlib. 한글 그림은 `CJK_FONT`(기본 NotoSansCJK-Regular.ttc).

## 필드 매핑 (실측 역판별, 공식 레이아웃 문서 대조 아님)
A1=PNU(19자리) · A3=법정동 주소 · A6=지번 · A22=대지면적 · A23=건축면적 · A24=연면적 · A25=용적률 · A26=건폐율 ·
A29/A30=주용도 코드/명(17000=공장) · A32/A33=지상/지하 층수 · A35=사용승인일 · A39=시군구코드.

## 함정
- 공단처럼 필지가 작고 빽빽한 곳에서 필지 폴리곤 **겹침**으로 건물을 고르면 이웃 건물이 딸려 와 면적이 3~8배로 부풀었다 → 반드시 A1(PNU)로 고른다.
- 공장등록현황 지번에 `번지`·단지/블록 꼬리표가 붙어 정확일치는 0건 → 본번-부번까지만 정규화.
- 업종명 끝 `외 N 종`(복수업종), 공백 차이(`자동측정`/`자동 측정`) 정규화 필요.
- 특건 판정은 법령상 '공장 연면적 합계' 기준인데 여기서는 **필지(PNU) 단위 합**으로 근사했다(한 사업장이 여러 필지에 걸친 경우 과소평가 가능).
