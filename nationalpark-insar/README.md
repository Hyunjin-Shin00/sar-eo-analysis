# nationalpark-insar — NEXTSat-2(N2) SAR → ISCE2 InSAR (COSMO-SkyMed spoofing)

국산 소형 SAR 위성 NEXTSat-2(N2)의 L1A HDF5를 ISCE2 `stripmapApp.py`에서 처리하기 위한 코드.
ISCE2에는 N2 센서 리더가 없으므로, ISCE2를 수정하지 않고 **COSMO-SkyMed SLC 리더를 런타임에 monkey-patch**해
N2 헤더 값을 주입한다(“spoofing”). 영상 화소는 그대로, 메타데이터 번역만 바꾼다.

## 파일
| 파일 | 역할 |
|---|---|
| `n2_main.py` | 진입점(이식판). 타임스탬프 작업폴더 생성 → `~/isce_n2_spoof/sitecustomize.py` 배포 → `PYTHONPATH` 선두 삽입 → `stripmapApp.py` 실행 → PNG. 경로는 `N2_ROOT`/`N2_XML` 환경변수 또는 스크립트 위치로 결정 |
| `n2_patch.py` | 핵심. `PATCH_CONTENT` 문자열 = sitecustomize 본문. `N2MetadataEngine`(키 대소문자/공백 무시 매칭, 파생값 계산, `Mapping_Report_*.txt` 즉시 기록) + `COSMO_SkyMed_SLC.parse/populateMetadata/extractImage` 패치 + 런타임 패치 2종 |
| `n2_viz.py` | 결과 PNG(geo 위상, rdr 래스터) |
| `input_n2.xml` | stripmapApp 설정 템플릿 (`sensor name = COSMO_SKYMED_SLC`, 외부 DEM은 반드시 `<component name="insar">` 안에) |
| `doppler_h5.py` | N2 자세각(yaw/pitch/roll)+궤도로 도플러 중심 다항식 추정(참고용; 헤더 값과 부호·크기 불일치 미해결 — notes 참조) |
| `csk_main.py`, `csk_viz.py` | 실제 COSMO-SkyMed 쌍으로 같은 ISCE2 체인(코레지→간섭도→필터→지오코딩→snaphu 언래핑→GeoTIFF/PNG) 검증용 |
| `environment.yml` | conda 환경(isce2 2.6, snaphu, numpy 1.26, h5py, rasterio, gdal) |
| `verify/` | 2026-10 재검증 스크립트: 헤더 기하 재계산(range-Doppler 지오로케이션, 입사각, 수직기선), 결맞음·언래핑 통계, 위상-DEM 회귀, 그림 생성 |

## N2 HDF5 → ISCE2 매핑(요지)
- `Radar Frequency` → 파장 λ = c/f (9.65 GHz → 0.03107 m)
- `S01/SBI Zero Doppler Range First Time` τ0 → 시작 경사거리 R0 = c·τ0/2, `Column Spacing` Δr → fs = c/(2Δr) (=150 MHz)
- `Zero Doppler Azimuth First/Last Time`(unix) → sensingStart/Stop/Mid
- `State Vectors Times / ECEF Position / Velocity` (60개) → ISCE Orbit (ECR)
- `PRF`, `Range Chirp Rate/Length`, `Look Side`(Right→-1), `Line/Column Samples`
- `Doppler Centroid`(스칼라) → 상수 다항식 1항 (N2는 range 방향 도플러 다항식 미제공)
- 입사각 = asin((Re+H)/Re · sin|look|), Re=6371 km (구면 근사)

## 런타임 패치
1. `_RunWrapper.__call__`: `runRefineSecondaryTiming` 실패 시 skip — 1×1 화소 구조 시험파일 완주용.
   **실데이터에서는 이 skip이 조용히 일어나면 코레지가 궤도+DEM 기하만으로 끝난다 → 로그에서 반드시 확인.**
2. `DataAccessor.methodSelector`: CSK 리더의 access mode `'r'`를 `'read'`로 정규화(ISCE2 버그 우회).
3. `extractImage`: 이미지 length 설정 + SLC 파일을 lines×samples×8 B로 sparse 확장.

## 실행
```bash
conda env create -f environment.yml && conda activate isce2_snaphu
# input_n2.xml 의 reference/secondary 를 서로 다른 날짜 N2 HDF5 로 수정
python n2_main.py          # → N2_INSAR_YYYYMMDD_HHMMSS/ (Mapping_Report, interferogram, export/png)
```
DEM 자동 다운로드(SRTM)는 NASA Earthdata 계정(`~/.netrc`)이 필요. SRTM은 60°S 이남·60°N 이북을 덮지 않는다.

## 알려진 한계 / 미해결
- 두 날짜 실제 N2 데이터로는 이 코드 저장소 환경에서 실행 기록 없음(구조 시험파일 자기쌍만 완주 — 출력 화소 전부 0).
- `csk_main.py`의 snaphu `-c topophase.cor`: ISCE2 `topophase.cor`는 2밴드 BIL(진폭, 결맞음)이라 단일밴드 결맞음을 기대하는 snaphu 입력으로 부적합. 밴드2 추출 후 전달 필요(미수정·미시험).
- 도플러: 헤더 스칼라 32.9 Hz vs 자세각 기반 추정 −21.5 Hz — 규약 차이 미해결(ISCE는 zero-Doppler 처리라 영향 제한적으로 판단).
