# insar-ground — Sentinel-1 PS-InSAR + SBAS 처리 스크립트

ISCE2 topsStack 코레지 → StaMPS(Python 포팅) PS → 자체 SBAS → 하강궤도 분해 → PS/SBAS 비교까지의 최종본 스크립트.
경로는 `${DATA_ROOT}`/`<DATA_ROOT>`(결과·워크스페이스), `${WORK_ROOT}`/`<WORK_ROOT>`(하강궤도·광역 작업), `$CONDA_PREFIX` 로 일반화함.

## 구성

| 폴더 | 파일 | 역할 |
|---|---|---|
| coreg | `coreg_parallel_then_ps_sbas.sh` | stackSentinel run_files 의 씬별 독립 명령을 `wait -n` 으로 NP개 병렬 실행 → topo 검증 → PS+SBAS 호출 |
| ps | `process_region.sh` | AOI bbox 크롭 → `mt_prep_isce 0.4` → `stamps(1,7)` → `ps_scn_filt` → 차감 전/후 2버전 출력 → 기준영역 자동선정 → `stamps(7,7)` → SBAS → 클릭맵 |
| ps | `mp_patch.py` | `ps_select` 의 pickle 폭증 OOM 해결용 `multiprocessing.Pool` 치환(fork COW 공유 + 워커 재생성) 및 언랩 `compute_ph_uw` isreal 캐시. 원 패키지 무수정, import 만으로 적용 |
| ps | `env_seoul.sh` | 세션 환경 예시(ISCE2·psi_python env 경로는 설치 환경에 맞게) |
| sbas | `run_sbas_autoscale.py` | MintPy 알고리즘 numpy 구현 SBAS: 9×3 멀티룩, ≤4연결·≤72일, snaphu, 최대결맞음 기준, 결맞음가중 역산, deramp, tcoh≥0.7. geom↔SLC 배율 자동감지 |
| wide | `make_tiles.py` `make_subtiles.py` `run_sbas_tile.py` `run_region_tiles.sh` `merge_capital_tiles.py`(수도권·부산 공용) | 광역 타일 SBAS: 픽셀창 타일(중첩 60) → 저채택 타일 2×2 재분할 → 프로세스 수 기반 동시실행 → 중첩부로 타일별 보정평면(a+bX+cY) 최소제곱 병합 |
| dsc | `download_dsc.py` `download_orbits_dsc.py` | asf_search 로 하강궤도 SLC·궤도 일괄 수신(인증은 `~/.netrc`, 코드에 자격증명 없음) |
| dsc | `setup_coreg_dsc.sh` `run_coreg_dsc.sh` `env_isce2_dsc.sh` `watchdog_t134.sh` `run_sbas_dsc.sh` | 하강궤도 코레지(크기 기준 skip 재개, GDAL 캐시 제한), 별도 unit 워치독, AOI별 SBAS |
| dsc | `decomp_build.py` | ASC/DSC SBAS → 55m 격자 공통셀·DSC 날짜로 ASC 보간 → 수직(UP)/동서(EW) 2성분 분해 csv |
| compare | `ps_sbas_analysis.py` | PS vs SBAS 300m 격자 집계 → 중앙 오프셋 제거 → r·Theil-Sen 기울기·잔차 RMS + 4패널 그림 |
| viz | `make_clickmap_big.py` | PS/SBAS 클릭맵 HTML(점 클릭 → 시계열 SVG, 기준영역·POI 마커) |

## 실행 순서(예)

```bash
# 0) 환경: ISCE2(topsStack) + psi_python(StaMPS Python 포팅) + snaphu(GMTSAR 빌드)
export DATA_ROOT=/path/to/data WORK_ROOT=/path/to/work
source ps/env_seoul.sh
# 1) 신규 지역: 코레지(병렬) + PS + SBAS
bash coreg/coreg_parallel_then_ps_sbas.sh Busan_Sasang_Hadan "부산 사상~하단" 35.1294 35.1664 128.9677 129.0049 $WORK/ASC_sasang 20220217 none none 8
# 2) 기존 스택 재사용: PS + SBAS
bash ps/process_region.sh Seoul_Gangdong "서울 강동" 37.5097 37.5840 127.1033 127.1994 $STACK 20220902 37.545961 127.155900
# 3) 하강궤도 SBAS + 분해
python sbas/run_sbas_autoscale.py --merged $DSC_STACK/merged --bbox S N W E --out $OUT --region Seoul_Gangdong_DSC
python dsc/decomp_build.py 강동
# 4) 비교
python compare/ps_sbas_analysis.py
```

대형 작업은 `systemd-run --user --unit=NAME --service-type=exec` 트랜지언트 서비스로 띄움.
**메모리 상한(MemoryMax/High/SwapMax)은 걸지 않는다** — systemd-oomd 가 상한 근처의 cgroup 압박(PSI)을 보고 그 unit 을 먼저 죽임. 메모리는 원인 쪽(GDAL_CACHEMAX, mp_patch)에서 줄임.

## 배치 주의
원본은 모든 스크립트가 한 폴더(`$BIN`)에 평탄하게 있었음. 실행할 때는 하위폴더의 파일을 `$BIN` 하나에 모아야 함.
`process_region.sh` 는 번들에서 제외한 `select_reference.py`·`ps_output_raw.py` 를, `run_sbas_dsc.sh` 는 경보 지도 생성기 `make_dsc_map.py` 를 호출한다(없으면 해당 단계만 WARN 후 계속).
구버전 `run_sbas.py`(9×3 geom 전제)는 `run_sbas_autoscale.py` 와 9×3 스택에서 결과가 같아 최종본만 넣었음.

## 주요 함정

- 소영역 PS 언랩 에러 `grid(17) < prefilt_win(32)` → `setparm unwrap_grid_size=100, unwrap_gold_n_win=16`.
- bbox 를 바꿀 때 `stamps_dev3` 를 지우지 않으면 `run_SLCcropStack` 이 옛 크롭을 재사용함.
- `-r1 -z1` 로 만든 스택은 geom 이 full-res 라 구버전 SBAS 창 계산이 raster 밖으로 나간다 → `run_sbas_autoscale.py`(배율 자동감지) 사용.
- 원본 SLC zip 을 지운 뒤에는 reference 날짜의 `.slc.full.vrt` 가 열리지 않는다 → `.slc.full` 평면 바이너리를 `np.memmap(complex64)` 로 직접 읽도록 바꿔야 함.
- `pkill -f`/`pgrep -f` 패턴이 점검 셸 자신과 매칭된다 → `/proc/PID/comm` 으로 거르기.
- 부호: SBAS csv 의 `velocity`·`Dyyyymmdd` 는 **음수 = 침하**(위성에서 멀어짐).

## 의존 / 제외
- 의존: ISCE2 2.6.x topsStack, psi_python(StaMPS Python 포팅, 사내 공유 패키지), snaphu 2.0.7, numpy/pandas/geopandas/gdal.
- `decomp_build.py` 는 csv 로더(`swept_loader`, 별도 경보 프로젝트 코드)를 import 함.
- 제외: PS 기준영역 자동선정 스크립트(사내 매뉴얼 원문 그대로라 미포함 — 알고리즘: 반경 150m 내 |속도|·추세잔차 z-score 합 최소 클러스터, PS≥15),
  `ps_output_raw.py`(포팅 패키지 `ps_output.py` 에서 기준 차감 한 줄만 0으로 바꾼 파생본), 경보 평가 스크립트(decomp_eval, dsc_full_analysis).
