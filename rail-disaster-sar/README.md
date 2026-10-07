# rail-disaster-sar — 철도 재해 SAR 탐지 타당성 조사 코드

무료 Sentinel-1 로 철도 재해(침수·교량 유실·고가교 지진 손상·사면붕괴)를 사건 직후 판정할 수 있는지
실측으로 확인한 조사의 최종 코드. 성공 사례(고가교 결맞음 변화 스크리닝, 하천 범람 침수 판정)와
실패 사례(늦은 관측·해상도·결맞음·후방산란 대비)를 같은 방식으로 측정한다.

## 구성

| 경로 | 내용 |
|---|---|
| `run.sh` | 분석 env 래퍼. PYTHONPATH 제거 + PROJ_DATA/GDAL_DATA 를 `$CONDA_PREFIX` 기준으로 지정 |
| `src/acquire/fetch_bursts.sh` | ASF SLC-BURST 를 받아 `burst2safe` 로 SAFE 조립(전체 SLC 대비 약 8~10배 절약) |
| `src/process/run_coh_pairs.sh`, `run_hachinohe_coh.sh`, `tops_coh_single.xml` | SNAP gpt 결맞음 체인: Orbit → Back-Geocoding → ESD → Coherence(2×8) → Deburst → Multilook → Subset → Terrain-Correction(10 m). 단일 subswath 버스트 SAFE 용(TOPSAR-Split 생략) |
| `src/catalog/fetch_hachinohe_viaduct.py`, `fetch_hachinohe_allrail.py`, `build_hachinohe_target.py` | OSM Overpass 로 고가 구조물·장면 내 전체 철도 회랑 수집, 피해/대조 구간 정의 |
| `src/process/analyze_hachinohe_coh.py` | 12일 동일 기선 5구간(참조2·사건·복구·사후) 결맞음 시계열 |
| `src/process/hachinohe_profile.py` | 고가 중심선 25 m 간격·반경 30 m 중앙값 종단면 → 400 m 이동창 최저 구간 |
| `src/process/hachinohe_null.py` | 위약(참조2−참조1) 검정 + 반경 3 km 무작위 400 m 횡단선 2,000개 널 분포 |
| `src/process/hachinohe_railnull.py` | 장면 내 철도 148 km 전 구간 창 순위(사전 기준: 상위 1 %) |
| `src/process/chiba_change_detect.py` | 변화 기반 침수 판정(Δσ⁰ ≤ −3 dB ∧ 사건 당일 평탄지 하위 1 백분위) |
| `src/process/landmask.py` | SRTM 육지 마스크(해면 풍속 변화에 의한 오탐 제거) |
| `src/process/chiba_measure.py` | 모든 면적·거리를 원 10 m 격자에서 재는 단일 출처 스크립트 |
| `src/process/damage_extent_survey.py` | 과거 피해 범위의 최소외접사각형 장축 → 필요 씬 수 추정 |
| `src/market/revisit_stats.py` | ASF 전수 조회 → 5분 내 통과 묶음 → 가상 사건 대비 첫 취득 대기시간 분포 |
| `src/figures/*.py` | 탐지 가능 영역 종합도(시간×공간규모), 고가교 증거 그림, 공통 스타일 |
| `grd_python/grd_sigma0.py` | SNAP 없이 GRD 를 Python/GDAL 로 직접 보정: calibration LUT → GCP 로 AOI 윈도 → σ⁰=DN²/LUT² → `gdalwarp -tps` |
| `grd_python/analyse_flood.py` | 신규 수체 판정 + 조용한 12일 페어 널 대조 + 패치 크기 필터 + 하천 근접 검증 + 선로 트리아지 검정 |
| `grd_python/cdse_search.py` | Copernicus Data Space OData 카탈로그 검색(검색은 인증 불필요) |

## 실행 환경

- `WORK_ROOT` = 작업 루트(`config/aoi`, `data/raw`, `data/interim`, `outputs/` 를 가짐). 미설정 시 `<WORK_ROOT>` 자리표시자로 남는다.
- Python: geopandas, rasterio, shapely, scipy, pyproj, asf_search, matplotlib. ISCE2 와 같은 env 를 쓰면 PYTHONPATH 오염으로 pyproj CRS 초기화가 깨지므로 별도 env + `run.sh` 사용.
- SNAP 12 gpt: `SNAP_GPT` 로 경로 지정. 힙은 반드시 실행 때 제한(`XMX=12G` 등) — 전역 vmoptions 의 큰 -Xmx 가 공유 서버 메모리를 고갈시킨 사례가 있었다.
- burst2safe: `B2S_ENV`(gdal·burst2safe 설치 env). PROJ_DATA/GDAL_DATA 를 명시하지 않으면 SAFE 조립이 annotation 없이 깨진다. 날짜마다 별도 출력 디렉터리.
- 자격증명: ASF/Earthdata 는 `~/.netrc`. 코드에 값 없음.

## 재현 순서(고가교 결맞음)

```bash
export WORK_ROOT=/path/to/work
run.sh src/catalog/fetch_hachinohe_viaduct.py
run.sh src/catalog/build_hachinohe_target.py
src/acquire/fetch_bursts.sh $WORK_ROOT/data/raw/burst_hachinohe_t46 "141.35 40.40 141.62 40.70" IW1 \
    1103:61718 1115:61893 1127:62068 1209:62243 1221:62418 0102:62593
T=t46  XMX=12G src/process/run_hachinohe_coh.sh
T=t141 XMX=12G src/process/run_hachinohe_coh.sh
run.sh src/process/analyze_hachinohe_coh.py t46 t141
run.sh src/process/hachinohe_profile.py t46 t141
N_RAND=2000 run.sh src/process/hachinohe_null.py t46 t141
run.sh src/catalog/fetch_hachinohe_allrail.py && run.sh src/process/hachinohe_railnull.py
run.sh src/figures/hachinohe_evidence.py t46 t141
```

## 주의

- 결맞음 변화는 **스크리닝**이다. 400 m 구간 단위의 산란 변화이며 기둥 균열 자체를 보는 것이 아니다.
- 표시용 래스터(재추출 격자)로 면적을 재지 말 것 — `Resampling.max` 재추출로 면적이 31~94 % 부풀었던 사례가 있다. 수치는 `chiba_measure.py` 에서만 뽑는다.
- ASF 검색 날짜는 UTC. JST 새벽 영상은 전날 날짜로 검색해야 한다.
- 선형 σ⁰ 와 dB 래스터를 섞으면 임계 −18 dB 가 무의미해진다.
- 원 프로젝트 내부 레이아웃(`src/process` 등)을 유지했으므로 모듈 간 import 는 그대로 동작한다. `grd_python/` 은 별도 병행 조사의 스크립트로, 자기 상위 디렉터리를 루트로 쓴다.
