# report-gen (sitecheck) — 주소 하나로 네 가지 판정 + 보고서 생성

## 무엇인가
지번 주소를 넣으면 위성 정사영상과 공공 대장에서 **건물 폴리곤 · 야적물 · 이격거리 · 건축물대장 대조** 네 결과를 뽑아 하나의 JSON 으로 내고, 물건별 HTML·PDF 보고서를 생성하는 파이프라인. 네 결과 모두 같은 GeoJSON Feature 형식이고 판정은 같은 이름의 key(`level·label·reason·basis`)에 담김.

`code/report-gen/` = 원본 저장소 `bsmi`(sitecheck). 건물 탐지기는 여기 **vendor 로 사본된 dinov3 분할기**(`sitecheck/vendor/dinov3seg/`)를 씀 — 위 `building-seg` 의 **그 전 세대(run4)**다. 개선본(run7 + 꼭짓점 헤드)으로의 교체는 `building-seg` 쪽 지침 참조.

## 입력
- **주소 문자열**(지번). 정사영상 범위 안이어야 함.
- **정사영상(ortho)** — `assets/scenes/`(원본, 번들 제외). 대구·구미·남동(인천) 등.
- **공공 API 두 개**(키는 환경변수/`.env`로 주입, 번들에 값 없음):
  - `VWORLD_KEY` — V-World 지오코딩·연속지적도(PNU·필지 폴리곤). 출처 www.vworld.kr.
  - `DATA_GO_KR_KEY` — 공공데이터포털 건축물대장 표제부(`getBrTitleInfo`). 출처 www.data.go.kr.
- **OpenAI VLM**(`OPENAI_API_KEY`) — 야적물(적재 구역) 판독. 없으면 야적 레이어만 비고 그 사실을 `result.json` note 에 적음(나머지 셋은 그대로 나옴).
- **GIS건물통합정보** `assets/gis/buildings.gpkg`(4.76 GB) — 건물 도형·대장 참조. **번들 제외(대용량)**. 원본 경로만 MANIFEST 에 기록.
- **건물 분할 가중치** `models/building/dinov3_v2_run4_best_ep11.pth`(1.32 GB, Git-LFS) — **번들 제외**. run4 는 현행(그 전 세대) 탐지기임.
- 공개 참조표 `code/report-gen/data/ext/code/` — 기본풍속(건축구조기준 별표5)·ASOS 관측소. 이격 판정의 풍하중 산정에 쓰는 공개 데이터라 포함.

## 단계 (순서 있음; 앞이 실패하면 뒤는 건너뛰되 그 사실을 결과에 적음)
```
0 주소해석  s0_locate   주소 → 좌표·필지(PNU)·건축물대장·영상 선택
1 건물      s1_building 정사영상 → 지붕 폴리곤 → 정합(georef) → 지번 귀속   (모델)
2 야적      s2_yard     필지 − 건물 → 적재 구역                         (VLM)
3 이격      s3_separation 건물마다 둘레 25 m 안의 상대까지 최단거리
4 대장      s4_ledger   건물별 건축면적 대조
```
- 판정 근거 조문·임계치는 `sitecheck/rules.py`(KFPA 판) — 예: 대장 초과 30 ㎡ 또는 10 % 초과 시 증축 의심, 이격 법정선 10 m 등.
- 좌표 정합(`steps/georef.py`·`parcel_fit.py`·`align.py`)과 꼭짓점 시차(`gt_parallax.py`)는 탐지 폴리곤을 실좌표/필지에 맞추는 보정.

## 출력 (주소마다 한 폴더)
```
result.json        넷을 합친 정본(API·웹이 읽음)
buildings.geojson  건물 폴리곤        (score·arch_area_m2·owner=PNU·role·dong …)
ledger.geojson     대장 대조  A3      (pnu·measured_sum_m2·ledger_sum_m2·label …)
separation.geojson 이격 측정선 A1
yard.geojson       야적 구역  A4·A5
summary.md         사람이 읽는 요약
0~3_*.png          항목별 결과 그림   (sitecheck/draw.py)
보고서.html/.pdf   물건별 보고서      (sitecheck/report/single.py)
```
비교분석(`--compare`): `out_cmp/위성_비교분석_<주소>.{html,pdf}` + 날짜분 `t1/ t2/`.

## 실행 (요약; 전문은 `code/report-gen/README.md`)
```
uv venv --python 3.10 && uv pip install -r requirements.txt
# 키 채우기: assets/.env.geodata (VWORLD_KEY·DATA_GO_KR_KEY) · assets/.env.openai (OPENAI_API_KEY)
.venv/bin/python -m sitecheck.tools.check          # 무엇이 있고 없는지 묶음별 점검
.venv/bin/python run.py "경상북도 구미시 공단동 293-15"
.venv/bin/python run.py --file addresses.txt       # 목록 일괄
```
진입점 셋: `run.py`(모델 추론, `out/`) · `demo.py`(GT 기반, `out_gt/`) · `hand_writting.py`(GT+손보정 데모 5건). 명령줄·단계·판정·저장물은 셋이 같고 `sitecheck/analyze.py` 한 길을 지남.

## 보고서 브랜딩 — 공개용 처리
원본 보고서 머리글은 고객사 로고(워드마크 PNG)와 사명을 넣게 돼 있었음. 공개 번들에서:
- 로고 자산 `assets/brand/*.png` **미포함**.
- 보고서 코드(`report/single.py`·`report/refit.py`)의 로고 파일명은 중립 자리표시자 `client_logo.png` 로, 코드·주석의 고객사명은 "고객사" 로 치환. 로고 파일이 없으면 코드가 **머리글을 비워 그림(빈 brand div)** — 정상 동작 유지.

## 정리 시 뺀 것 (최종 결과 경로만 남김)
- `assets/gis/buildings.gpkg`(4.76 GB)·`assets/scenes/`(정사영상)·`assets/gt/`·`assets/brand/`(로고) — 원본 데이터/대용량/브랜드 자산.
- `models/`(LFS 포인터만 존재)·`.git/`·`__pycache__/`.
- `out/`·`out_cmp/` 전량 대신 **대표 2건의 텍스트 결과만** `results/` 로(아래 참조). 보고서 HTML/PDF 와 결과 PNG 는 전부 Git-LFS 포인터(실파일은 LFS)라 제외.
