# 환경 설정

코드가 실제로 읽는 설정을 전부 모은 문서임. 값은 AST 로 `os.environ.get(...)` 을 훑어 뽑은 것이라
여기 없는 이름은 코드도 쓰지 않음.

---

## 1. conda 환경

| 환경 | 정의 | 쓰는 곳 |
|---|---|---|
| `isce2_snaphu` | [`isce2_snaphu.yml`](isce2_snaphu.yml) | ISCE2 기반 InSAR 전반 — topsStack · stripmapStack · snaphu |
| `isce2_n2_spoof` | [`isce2_n2_spoof.yml`](isce2_n2_spoof.yml) | NEXTSat-2 를 CSK 로 위장해 ISCE2 를 돌리는 경로 |
| `pyps` | 아래 pip 목록 | geopandas · rasterio 를 쓰는 분석·시각화 전반 |
| `netCDF4` | 아래 pip 목록 | OSI-SAF · NSIDC · SMOS 등 NetCDF 자료 |
| `bldseg` | 아래 pip 목록 | 건물 분할 모델 (PyTorch · transformers) |

```bash
conda env create -f environment/isce2_snaphu.yml
conda env create -f environment/isce2_n2_spoof.yml

conda create -n pyps    python=3.10 && conda activate pyps    && pip install -r requirements.txt
conda create -n netCDF4 python=3.10 && conda activate netCDF4 && pip install numpy pandas xarray netCDF4 h5py matplotlib cartopy
conda create -n bldseg  python=3.10 && conda activate bldseg  && \
  pip install torch torchvision "transformers>=4.40" opencv-python pycocotools numpy scipy pillow tqdm
```

각 모듈 README 의 「실행 → 환경」 절에 그 모듈이 어느 환경을 쓰는지 적혀 있음.

---

## 2. 자격증명 — `.env`

[`.env.example`](../.env.example) 을 `.env` 로 복사해 값을 채움. `.env` 는 `.gitignore` 로 막혀 있음.

| 이름 | 발급처 | 쓰는 모듈 |
|---|---|---|
| `EARTHDATA_USER` · `EARTHDATA_PASS` | https://urs.earthdata.nasa.gov/ | ASF Sentinel-1 다운로드 |
| `EARTHDATA_USERNAME` · `EARTHDATA_PASSWORD` | 같음 | BlueBON AOD 검증 — **아래 주의 참조** |
| `CDSE_USER` · `CDSE_PASS` | https://dataspace.copernicus.eu/ | Sentinel-2 |
| `USGS_USER` · `USGS_TOKEN` | https://m2m.cr.usgs.gov/ | Landsat 8/9 |
| `GFW_API_TOKEN` | https://globalfishingwatch.org/our-apis/ | 북극항로 선박 자료 |
| `KMA_API_KEY` | https://apihub.kma.go.kr/ | 기상 자료 |
| `DATA_GO_KR_KEY` | https://www.data.go.kr/ | 건축물대장 표제부, 시추공 SPT |
| `VWORLD_KEY` | https://www.vworld.kr/ | 지오코딩 · 연속지적도(PNU) |
| `KAKAO_KEY` | https://developers.kakao.com/ | 주소 지오코딩 보조 |
| `GIMS_KEY` · `GIMS_KEY_DEPTH` · `GIMS_KEY_STATION` | 국가지하수정보센터 | 지하수 수위·관측소 |
| `OPENAI_API_KEY` | https://platform.openai.com/ | 야적물 판독 VLM |
| `GSPREAD_CREDENTIALS` | 구글 서비스계정 JSON 경로 | BlueBON 미션 시트 |
| `BLUEBON_SHEET_ID` | 시트 URL 의 ID | BlueBON 처리 목록 |
| `BUS_SIM_PASSWORD` | 사내 | BlueBON 지상 시험 |

> ⚠ **Earthdata 변수 이름이 두 벌임.** 대부분은 `EARTHDATA_USER` · `EARTHDATA_PASS` 를 읽지만,
> `eo/bluebon/downstream/aod/` 아래 `validate_bb_aod.py` 두 벌은 `EARTHDATA_USERNAME` ·
> `EARTHDATA_PASSWORD` 를 읽음. 한쪽만 채우면 다른 쪽이 **조용히 빈 값으로 돌다 인증 실패**함.
> 네 개를 모두 같은 값으로 채우는 것이 안전함.

---

## 3. 경로·실행 설정 — 셸에서 `export`

`.env` 가 아니라 셸 환경으로 넘김. 기본값이 있는 것은 비워 둬도 됨.

### 공통

| 이름 | 뜻 | 기본값 |
|---|---|---|
| `DATA_ROOT` | 원본·중간 산출물 루트 | 없음 — 지정 필요 |
| `WORK_ROOT` | 작업 디렉터리 루트 | 없음 — 지정 필요 |
| `OUT_DIR` | 산출물 디렉터리 | 스크립트별 기본값 |
| `CONDA_PREFIX` | conda 가 자동 설정 | — |
| `PROJ_LIB` · `PROJ_DATA` · `GDAL_DATA` | PROJ·GDAL 자료 경로. conda 환경이 꼬였을 때만 지정 | 환경 기본값 |
| `CJK_FONT` | 그림에 쓸 한글 글꼴 파일 | 시스템 탐색 |

### SAR 처리

| 이름 | 뜻 |
|---|---|
| `S1_ROOT` · `S1_SRC_STACK` | Sentinel-1 원본·스택 트리 |
| `SNAPHU_BIN` | snaphu 실행 파일 경로 (PATH 에 없을 때) |
| `COH_THRESH` | 결맞음 임계값 기본치 |
| `PSI_MAX_WORKERS` · `NWORKERS` · `MAXTASKSPERCHILD` · `CHUNKSIZE` | PS 처리 병렬화 |
| `TILE_TMP` | 타일 임시 디렉터리 |
| `CSK_ROOT` · `CSK_OUT` · `CSK_DEM` · `CSK_EXT_DEM` · `CSK_RUN` | COSMO-SkyMed 처리 경로 |
| `N2_ROOT` · `N2_H5` · `N2_XML` | NEXTSat-2 원본·헤더 경로 |
| `CUDA_HOME` · `CUDA_PATH` · `CUPY_ACCELERATORS` | GPU 가속 (선택) |

### 인수심사 · 보고서 생성

| 이름 | 뜻 |
|---|---|
| `CLAB_ROOT` | 지반침하 과제 트리 루트 |
| `SITECHECK_PYTHON` | sitecheck 가 쓸 파이썬 실행 파일 |
| `SITECHECK_DINOV3_PYTHON` | 건물 탐지 추론용 파이썬 (분리 환경일 때) |
| `SITECHECK_SCENES` | 정사영상 디렉터리 |
| `SITECHECK_SEGLAB` | 분할 모델 코드 경로 |
| `NDVI_ROOT` · `RAD` · `SITE` · `N_RAND` | 모듈 전용 — 해당 README 참조 |

### 예시

```bash
export DATA_ROOT=/mnt/data/eo
export WORK_ROOT=$HOME/work
export SNAPHU_BIN=$(command -v snaphu)
set -a; source .env; set +a      # .env 의 자격증명을 환경으로
```

---

## 4. 외부 도구

코드에 포함되지 않음. 따로 설치해야 하는 것들임.

| 도구 | 쓰는 곳 | 비고 |
|---|---|---|
| **ISCE2** 2.6.3 | topsStack · stripmapStack 코레지, 간섭도 | conda 환경 yml 에 포함 |
| **snaphu** 2.0.4 이상 | 위상 언래핑 | `SNAPHU_BIN` 으로 경로 지정 가능 |
| **SNAP** (ESA) | GRD 전처리, 일부 DInSAR 체인 | GUI 또는 `gpt` CLI |
| **MintPy** | SBAS 시계열 | pip |
| **PyGMTSAR** | 일부 SBAS 비교 | pip |
| **Google Earth Engine** | 맹그로브 분류, 누적 TAI 맵 | 웹 편집기에서 수행 — 코드 미포함 모듈 있음 |
