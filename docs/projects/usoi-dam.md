# usoi-dam — Usoi 자연댐(Sarez 호) Sentinel-1 ASC+DSC SBAS

타지키스탄 파미르 고원의 Usoi 자연댐(1911년 산사태로 형성, Sarez 호) 일대를 Sentinel-1 IW SLC 로
SBAS 처리하고, 상승(ASC)·하강(DSC) 두 궤도를 결합해 수직/동서 성분으로 분해하려 한 파이프라인.
ISCE2 topsStack(간섭도) + MintPy 1.6 smallbaselineApp(시계열) + MintPy asc_desc2horz_vert(분해).

## 환경
- conda env: ISCE2 2.6 + MintPy 1.6.2 + snaphu + PyAPS(ERA5), GDAL, h5py, matplotlib
- 환경변수 `DATA_ROOT` = `SBAS/`, `sentinel1/` 를 담는 작업 루트
- 자격증명: ASF 다운로드는 `~/.netrc`(Earthdata), ERA5 는 `~/.cdsapirc`(CDS API) 를 사용 — 코드에 값 없음

## 구성
| 경로 | 역할 |
|---|---|
| `pipeline/download_track.sh` | ASF SLC 병렬 다운로드(크기 프로브·매 시도 새로 받기·자가치유) |
| `pipeline/build_dem.sh` | COP30 DEM EGM2008 → WGS84 타원체고, ISCE 포맷 |
| `pipeline/fetch_orbits.py` | ESA 미러에서 POEORB 정밀궤도 수집(인증 불필요) |
| `pipeline/setup_stack.sh` | stackSentinel: IW2 고정(`-n 2`), `-C geometry`, `-c 4`, 3×9 룩, snaphu |
| `pipeline/run_stack.sh` | run_files 순차 실행. **줄 끝 `&` 제거** 후 xargs 동기 실행(.done 재개) |
| `pipeline/finish_igrams_asc.sh` | 디스크 부족 시 페어별 merge → 즉시 버스트 간섭도 삭제(페어당 1.23 GB) |
| `pipeline/dsc_pipeline.sh` | DSC 자가구동: 코레지 → secondary zip 삭제 → 간섭도 → coreg 삭제 → unwrap → MintPy |
| `pipeline/run_mintpy.sh` + `best_ref_pixel.py` | 트랙별 기준픽셀 자동계산(유지 간섭도 다수에서 connComp>0 + 최고결맞음) 후 SBAS |
| `pipeline/smallbaseline_template.cfg` | ≤24일 네트워크, unwrapError=no, minTempCoh 0.3, subset 끔 |
| `pipeline/asc_rerun_aoi.sh` | 진단용: ASC 기준점을 AOI 내부로 옮겨 재역산(회복 실패 기록) |
| `pipeline/dsc_era5.sh` | DSC 대류권 보정을 ERA5(PyAPS)로 교체, correct_troposphere 부터 재개 |
| `pipeline/decompose.sh` | 두 트랙 마스크·공통격자 geocode(0.0005°) → asc_desc2horz_vert |
| `pipeline/pipeline.sh` | DEM→궤도→트랙별 스택·MintPy→분해 전체 오케스트레이션 |
| `analysis/diag_era5.py` | 속도~고도 상관·기울기 진단 |
| `analysis/export_dsc_corrected.py` | ERA5 결과 위에 경험적 고도 detrend + 안정암반 재기준 + 호수 마스킹 + AOI 크롭 → GeoTIFF·메타 |
| `analysis/make_dsc_corr_map.py` | Leaflet 웹맵(원시 속도장 임베드, 색범위·투명도·시계열 인터랙티브) |
| `analysis/plot_decomp.py`, `seasonal_point.py` | 분해 4패널 지도, 지점 계절성(연·반년 주기) 적합 |
| `verify/recompute.py` | 핸드오프용 재계산(원본 h5 읽기 전용) |
| `verify/make_figs.py` | 핸드오프 그림 생성 |

## 실행 순서
```bash
export DATA_ROOT=/path/to/Usoi_Dam
bash pipeline/download_track.sh $DATA_ROOT/sentinel1/asc/urls.txt $DATA_ROOT/sentinel1/asc 6
bash pipeline/pipeline.sh            # 또는 DSC 는 pipeline/dsc_pipeline.sh
bash pipeline/dsc_era5.sh            # DSC ERA5 재보정
python analysis/export_dsc_corrected.py && python analysis/make_dsc_corr_map.py
```

## 알려진 함정
- topsStack run_file 의 각 줄이 `&` 로 끝나 그대로 eval 하면 즉시 완료 처리 → 단계 경합.
- 작은 AOI 에서 NESD 코레지는 버스트 겹침 영역이 없어 run_08 이 빈 목록으로 실패 → `-C geometry`.
- 기준 날짜의 burst SLC 는 원본 zip 을 `/vsizip/` 로 참조 → run_10 끝나기 전 기준 zip 삭제 금지.
- MintPy `maxCoherence` 자동 기준점은 평균만 보고 고르므로 개별 간섭도의 35% 에서 신뢰불가 → 시간결맞음 전역 0.
- MintPy `subset.lalo` 는 레이더 스와스가 위경도 직사각형과 달라 geo2radar 실패 → `auto`.
- asc_desc2horz_vert 는 두 입력의 REF_LAT/LON 이 3 px 이내여야 함 → 공통 기준점으로 재참조 후 실행.
- `--start correct_troposphere` 는 reference_point 이후라 cfg 의 reference.lalo 가 반영되지 않음.
