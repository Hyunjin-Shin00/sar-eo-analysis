# RUNBOOK — 새 영상이 들어왔을 때

자료 한 벌이 새로 들어왔을 때 **어느 모듈을 어떤 순서로 돌리면 결과가 나오는지** 적은 문서임.
각 모듈 README 의 「실행」 절에 인자가 코드에서 뽑은 그대로 들어 있고, 여기서는 **순서와 연결**만 다룸.

- 환경 구성·자격증명·외부 도구: [`environment/ENV.md`](environment/ENV.md)
- 처음이면 아래 0절부터

---

## 0. 한 번만 하는 준비

```bash
git clone <this repo> && cd sar-eo-analysis
cp .env.example .env            # 값 채우기 — ENV.md 2절
conda env create -f environment/isce2_snaphu.yml
conda create -n pyps python=3.10 && conda activate pyps && pip install -r requirements.txt

export DATA_ROOT=/mnt/data/eo   # 원본·산출물 루트
export WORK_ROOT=$HOME/work
set -a; source .env; set +a
```

표기 약속 — `<DATA_ROOT>` · `<WORK_ROOT>` 는 위 환경변수로 치환됨.
코드 안의 같은 표기도 전부 이 둘을 가리킴.

---

## 1. Sentinel-1 홍수 탐지 — 원본 ZIP 두 장 → 침수 면적

```bash
conda activate pyps
cd sar/sentinel-1/water/flood

# 시기별로 한 번씩: 전처리 + Edge-Otsu 수체 마스크
python s1_processor.py \
  --input_zips <DATA_ROOT>/S1/pre.zip  --output_dir out/pre \
  --aoi_shp aoi.shp --polarization VV --slope_threshold 5.0
python s1_processor.py \
  --input_zips <DATA_ROOT>/S1/post.zip --output_dir out/post

# 두 마스크 차분 → GAIN/LOSS 면적
python s1_processor.py --before_mask out/pre/water.tif \
                       --after_mask  out/post/water.tif \
                       --output_dir out/flood --flood_stats yes
```

| 산출 | 내용 |
|---|---|
| `out/<시기>/water.tif` | 수체 마스크 (Edge-Otsu 임계는 로그에 기록됨) |
| `out/flood/` | GAIN·LOSS 래스터와 km² 집계 |

- DEM·경사는 주지 않으면 **Copernicus 30 m 를 자동으로 받아** 계산함
- SNAP 없이 돌리려면 [`satchat/s1_flood_nosnap.py`](sar/sentinel-1/water/flood/satchat/) — 입력이 dB GeoTIFF 임
- 상시 수체와 신규 침수를 가르려면 JRC 영구수체 마스크를 차분함
- 검증 절차는 [`sar/sentinel-1/water/flood/README.md`](sar/sentinel-1/water/flood/)

---

## 2. Sentinel-1 지반변위 — SLC 스택 → 변위속도·시계열

```bash
conda activate isce2_snaphu
```

| 순서 | 모듈 | 하는 일 |
|---|---|---|
| 1 | [`sar/sentinel-1/preprocessing/`](sar/sentinel-1/preprocessing/) | 다운로드·궤도 수집, `stack/` 의 topsStack 로 코레지 |
| 2a | [`sar/sentinel-1/insar/psinsar/`](sar/sentinel-1/insar/psinsar/) | PS — 진폭분산 0.4, 결맞음 0.4. 메모리 패치는 `stamps_patches/` |
| 2b | [`sar/sentinel-1/insar/sbas/`](sar/sentinel-1/insar/sbas/) | SBAS — 72일 이내 쌍, snaphu 언랩, 결맞음 가중 역산 |
| 3 | [`sar/sentinel-1/insar/sbas/wide-area/`](sar/sentinel-1/insar/sbas/wide-area/) | 광역이면 타일 분할 → 중첩부 평면 정합 병합 |
| 4 | [`sar/sentinel-1/insar/decomposition/`](sar/sentinel-1/insar/decomposition/) | 상승·하강 LOS → 수직·동서 분리 |
| 5 | [`sar/sentinel-1/insar/viz/`](sar/sentinel-1/insar/viz/) | `make_clickmap.py --shp <PS shp> --out map.html` |

```bash
# 3~5 예시
python sar/sentinel-1/insar/sbas/export_sbas.py --geo <geo 디렉터리> --out ts.csv --tag asc --ts
python sar/sentinel-1/insar/decomposition/decompose_asc_dsc.py --t0 2025-09-09 --t1 2026-04-26
python sar/sentinel-1/insar/viz/make_clickmap.py --shp ps.shp --out map.html
```

- PS·SBAS 비교는 `sar/sentinel-1/insar/compare_ps_sbas.py` — 300 m 공통격자 상관 r·잔차 RMS
- 병렬도는 `PSI_MAX_WORKERS` 로 조절함

---

## 3. 지진 피해 — SLC → 변위장 + 피해 등급도

```bash
conda activate isce2_snaphu
```

1. **DInSAR** — [`sar/sentinel-1/insar/dinsar/`](sar/sentinel-1/insar/dinsar/).
   SNAP 체인(Split → 궤도 → Back-Geocoding → 간섭도 → Deburst → Goldstein → TC) 뒤 snaphu 로 언랩,
   `d_LOS = −φλ/4π`
2. **CCD** — [`sar/sentinel-1/change-detection/coherence/`](sar/sentinel-1/change-detection/coherence/).
   `ΔCoh = γ_pre − γ_co`, γ_pre 저코히런스 마스크, ΔCoh < 0 은 제외
3. **등급·교차검증** — [`applications/disaster-damage/earthquake/`](applications/disaster-damage/earthquake/).
   OSM 건물·도로, 활성단층과 중첩. 광학 기반 건물 분류기는 `model_v7/`

---

## 4. NEXTSat-2 — HDF5 → 지오코딩 영상

```bash
conda activate pyps
cd sar/nextsat-2/sensor-model
```

헤더를 SI 로 정리 → 궤도 상태벡터 60점 다항식 적합 → 거리-도플러 → 대류권 보정 →
DEM 시뮬레이션 정합으로 센서 편향 추정 → 12씬 결합조정 → EGM2008 반영 → 지오코딩.

```bash
python step11_water_detect.py --indir <지오코딩 결과> --scenes <씬 목록> --outdir out
```

- 단계별 스크립트와 수식 근거: [`RD_MODEL_DETAIL.md`](sar/nextsat-2/sensor-model/RD_MODEL_DETAIL.md)
- 지오이드를 빼먹으면 range 가 약 24.5 m 어긋남 — 그 잔차가 융기량과 맞는지가 정합성 점검임

**ISCE2 로 InSAR 까지 가려면** — [`sar/nextsat-2/isce2-spoofing/`](sar/nextsat-2/isce2-spoofing/)

```bash
conda activate isce2_n2_spoof
export PYTHONPATH=sar/nextsat-2/isce2-spoofing:$PYTHONPATH   # sitecustomize.py 가 맨 앞
export N2_ROOT=<DATA_ROOT>/N2  N2_H5=... N2_XML=...
python sar/nextsat-2/isce2-spoofing/n2_main.py
```

ISCE2 를 고치지 않고 `COSMO_SkyMed_SLC` 의 parse·populateMetadata·extractImage 를 런타임에 덮어씀.
매핑 결과는 `Mapping_Report` 에 줄 단위로 쌓이므로 중간 실패도 추적됨.

---

## 5. COSMO-SkyMed PS-InSAR

```bash
conda activate isce2_snaphu
python sar/cosmo-skymed/preprocessing/unpack_csg.py -i <CSG HDF5> -o <출력> --block 2048
export CSK_ROOT=... CSK_OUT=... CSK_DEM=...
# stripmapStack 코레지 → StaMPS 포팅판 PS
python sar/cosmo-skymed/insar/psinsar/export_ps.py <npz> <출력 베이스> --fmt both --with-ts
```

CSG HDF5 를 1세대 CSK 레이아웃처럼 보이게 하는 어댑터가 `preprocessing/` 에 있음.

---

## 6. 광학 — Sentinel-2 · PlanetScope

| 목적 | 모듈 | 명령 |
|---|---|---|
| 산불 피해 등급 | [`eo/sentinel-2/burn-severity/`](eo/sentinel-2/burn-severity/) | dNBR → USGS 5등급. OmniCloudMask 로 구름·연기 제거 |
| 제련소 열원 | [`eo/sentinel-2/thermal-anomaly/`](eo/sentinel-2/thermal-anomaly/) | `python geocode_smelters.py --input <목록> --output aoi.geojson` |
| 식생 시계열 | [`eo/sentinel-2/vegetation/`](eo/sentinel-2/vegetation/) | NDVI·EVI 시계열 |
| 공사 변화탐지 | [`eo/planetscope/change-detection/`](eo/planetscope/change-detection/) | `python measure_construction.py --works <선형 shp> --mdl <MDL 선형> --csv out.csv` |

---

## 7. BlueBON — 다운링크 원본 → L1C

```bash
conda activate pyps
```

| 레벨 | 모듈 | 산출 |
|---|---|---|
| L0 | [`eo/bluebon/l0-to-l1a/`](eo/bluebon/l0-to-l1a/) | 밴드별 12 bit DN, 4096 × 16000 |
| L1A | [`eo/bluebon/radiometric/`](eo/bluebon/radiometric/) | `(raw − dark_ref)·flat_PRNU − δ` → 밴드정합 → TOA 복사휘도 float32 |
| L1C | [`eo/bluebon/geometric/`](eo/bluebon/geometric/) | 특징점 정합 → 이상점 제거 → RPC 적합 → 정사보정 UTM 4.8 m |

- 센서 상수(밴드 중심·FWHM·TDI·포화 DN)는 [`eo/bluebon/SPEC.md`](eo/bluebon/SPEC.md)
- **정량 분석 전에 반드시 읽을 것** — 정규화본 사용 금지, `×d_r²` vs `÷d_r` 버그(±10%), 단위 표기 오류, 0 라인 혼입
- 코드가 TDI·line rate 를 영상 메타데이터가 아니라 **상수로 들고 있음**. 다른 설정의 장면을 돌리려면 그 상수부터 고쳐야 함

---

## 8. 해빙 — PMW → 항로 개방 시기

```bash
conda activate netCDF4
```

[`passive-microwave/sea-ice/`](passive-microwave/sea-ice/) 의 `download/` → `convert/` → `plot/` 순서로 돌린 뒤
[`applications/arctic-route/`](applications/arctic-route/) 에서 SIC·SIT·선박 자료를 월별로 융합하고
SIC 15 % 기준으로 구간별 개방 시기를 냄.

---

## 9. 건물 판독 → 물건별 보고서

```bash
conda activate bldseg
cd applications/underwriting/building-seg

python dinov3_v2/selftest.py           # GPU·데이터 없이 설치 점검
python dinov3_v2/infer.py   --ckpt <stage1.pth> --images scene.png \
                            --out stage1_preds --overlap 256 --threshold 0.05 --save-masks
python dinov3_poly/infer.py --ckpt model/stage2_dinov3_poly_run2_best.pth \
                            --images scene.png --stage1 stage1_preds --out preds
```

Stage1 가중치는 저장소에 없음 — 용량과 백본 라이선스 때문임.
구조·하이퍼파라미터는 `model/stage1_run7_config.json` 에 전량 있어 재학습이 가능함.

```bash
conda activate pyps
cd applications/underwriting/report-gen
python -m sitecheck.tools.check               # 무엇이 있고 없는지 점검
python run.py "경상북도 구미시 공단동 293-15"
```

| 산출 | 내용 |
|---|---|
| `result.json` | 네 판정을 합친 정본 |
| `buildings · ledger · separation · yard .geojson` | 레이어별 결과 |
| `summary.md`, `보고서.html` · `.pdf` | 사람이 읽는 형태 |

- 정사영상·GIS건물통합정보·가중치는 용량 때문에 저장소에 없음. `sitecheck.tools.check` 가 무엇이 비었는지 알려줌
- VLM 키가 없으면 야적 레이어만 비고 나머지 셋은 그대로 나옴

---

## 10. 지반침하 조기경보

[`applications/subsidence-warning/`](applications/subsidence-warning/) 의 폴더 번호가 곧 순서임.

| 순서 | 폴더 | 하는 일 |
|---|---|---|
| 00 | `00_ground_data/` | 시추공 SPT 수집 → 통합 CSV |
| 01 | `01_accident_data/` | 사고 이력 수집·지오코딩·원인 라벨 |
| 02 | `02_fusion_poc/` | 지반등급 α → 3지표 × α → 융합 |
| 03 | `03_alarm_pipeline/` | 역속도법 + DBSCAN 클러스터 알람 |
| 04 | `04_leadtime_rules/` | 워크포워드 리드타임, 2단 게이트 |
| 05 | `05_point_grade_demo/` | 주소·기준일 → 정상/주의/위험 + 위험구역 GeoJSON |
| 06 | `06_recheck/` | 재확인 |
| 07 | `07_sweep/` | coh·tcoh·범위 스윕과 판별력 최적화 |
| 08 | `08_unified_map/` | PS·SBAS·시추공 통합 지도 |

```bash
export CLAB_ROOT=<DATA_ROOT>/subsidence
python applications/subsidence-warning/05_point_grade_demo/check_env.py   # 3초 자가진단
```

---

## 돌리기 전에 알아 둘 것

- **상수를 고쳐 돌리는 스크립트가 많음.** argparse 가 있는 파일은 95개이고 나머지는 파일 위쪽 상수를
  대상 자료에 맞게 바꾸는 구조임. 어느 상수인지는 각 모듈 README 의
  「상수를 고쳐 돌리는 스크립트」 표에 파일·이름·현재값으로 적어 뒀음
- **원본 위성자료·대용량 중간산출물은 저장소에 없음.** `.gitignore` 가 막고 있고, 어디서 받는지는
  각 모듈 README 의 입력 열에 적혀 있음
- **모델 가중치 두 개는 용량·라이선스 때문에 빠져 있음.** 어느 것이고 sha256 이 무엇인지는
  [`applications/underwriting/README.md`](applications/underwriting/) 참조
- **GEE 에서만 돌린 분석이 있음.** 맹그로브 분류와 누적 TAI 맵은 웹 편집기에서 수행해 코드가 없음.
  해당 모듈 README 에 그렇게 적어 뒀음
