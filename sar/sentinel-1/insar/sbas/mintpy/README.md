# sar/sentinel-1/insar/sbas/mintpy

MintPy 기반 SBAS 파이프라인 (대기보정 포함).

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `asc_rerun_aoi.sh` | Re-run ASC MintPy with the reference point moved INTO the AOI. Diagnosis: ASC spatial coherence in the AOI is  | H5 | — |
| `best_ref_pixel.py` | Pick a reference pixel that is reliable (connComp>0) in as many KEPT interferograms as possible, with the high | HDF5 | 텍스트/로그 |
| `build_dem.sh` | Build ISCE-ready COP30 DEM for Usoi Dam AOI. COP30 vertical datum = EGM2008 geoid -> convert to WGS84 ellipsoi | DEM · TIF | — |
| `decompose.sh` | Combine ASC + DSC LOS velocities into vertical (Up) + horizontal (E-W). asc_desc2horz_vert.py needs BOTH track | H5 · TIF | — |
| `download_track.sh` | Parallel, resumable-by-restart ASF Sentinel-1 SLC downloader with size verification. Robust against ASF quirks | ZIP | — |
| `dsc_era5.sh` | Re-do DSC atmospheric correction with ERA5 (PyAPS) instead of height_correlation, to remove | H5 | — |
| `dsc_pipeline.sh` | Self-driving DSC pipeline (disk-aware), IW2, reference=20220930, 224 scenes. Order: run_01..07 (coreg+merge SL | H5 · ZIP | — |
| `fetch_orbits.py` | Generalized Sentinel-1 POEORB precise-orbit fetcher (ESA mirror, no auth). usage: fetch_orbits.py --urls URLS. | — | 텍스트/로그 |
| `finish_igrams_asc.sh` | Disk-safe completion of ASC run_08 (generateIgram) + run_09 (mergeBursts) on a nearly-full SHARED disk. Key id | — | — |
| `pipeline.sh` | Master processing chain (run AFTER SLC downloads complete). DEM -> orbits -> [per track: topsStack setup + run | TXT | — |
| `run_mintpy.sh` | Run MintPy smallbaselineApp SBAS for one track, with a PER-TRACK reference pixel. The auto maxCoherence refere | H5 | — |
| `run_stack.sh` | Execute ISCE2 topsStack run_files in order for one track. Each run_file holds N independent commands (one per  | — | — |
| `setup_stack.sh` | Configure ISCE2 topsStack (interferogram workflow) for one track. usage: setup_stack.sh <asc/dsc> | — | — |

## 주요 인자

- `fetch_orbits.py` — `--out` `--urls`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 진입점

```bash
python fetch_orbits.py --urls <값> --out <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--urls` | ● |  |  |
| `--out` | ● |  |  |
