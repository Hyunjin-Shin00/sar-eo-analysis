# seoul-csk-psinsar — 서울 COSMO-SkyMed(X밴드) PS-InSAR + Sentinel-1 교차검증

COSMO-SkyMed 2세대(CSG) 32씬으로 서울 전역 PS-InSAR(약 600만 점)를 산출하고, Sentinel-1 상승(PS·SBAS)·하강(SBAS) 결과와 교차검증한 코드.
원 실행 환경: ISCE2 2.6.3 + StaMPS Python 포팅판(isce2psi) + snaphu + MintPy, conda env `isce2_snaphu`. MATLAB 없음.

경로 표기: `<DATA_ROOT>` = 프로젝트 데이터 루트(CSK_PSInSAR / S1_PSInSAR / S1_DSC 하위), `<WORK_ROOT>` = StaMPS Python 포팅판 등 작업 루트, `$CONDA_PREFIX` = conda env.

## 디렉토리
| 폴더 | 내용 |
|---|---|
| `csg_adapter/` | **CSG → ISCE2 어댑터(자체 개발)**. `csg_sensor.py`: CSG HDF5(`S01/IMG` float32 I/Q, 키 이름 변경)를 1세대 CSK 레이아웃처럼 보이게 하는 shim + 블록 단위 numpy 추출. `unpack_csg.py`: stripmapStack SLC 레이아웃으로 언팩. `csg_baselines.py`: 수직기선 표. `bedrock_candidates.py`: 기준점 후보 암반 산체 레이오버 선별 |
| `psi/` | 서울 크롭·마스크(`crop_seoul.py`), StaMPS 단계 실행 래퍼(`run_stamps.sh`, `psi_env.sh`), 최종 PS 산출(`make_ps_result.py` → npz), shapefile 내보내기 |
| `stamps_patches/` | StaMPS Python 포팅판에서 고친 파일 8개(전체 파일) + 원본 대비 `.diff` 6개. 결과 오류(seek 4배 과다, 마스크 첫 줄만 읽기, DEM을 복소수로 읽기, 패치 병합 오류 2건), 미종료(PS마다 `np.isreal` 1.79초 → 16.4일, 공간필터 전수 거리계산 → 4.4일), 메모리(OOM) 수정 |
| `sbas/` | 크롭 SLC에서 전해상도 간섭도를 디스크에 쓰지 않고 멀티룩 누적(`sbas_lib.py`), 쌍별 간섭도·snaphu(`run_sbas_igrams*.sh`), MintPy 설정(`seoul_csk.txt`), `.rsc` 룩수 보정(`fix_rsc_looks.py`) |
| `compare/` | 4종(CSK PS/SBAS, S1 PS/SBAS) 비교(`compare_all.py` 공용 함수), 계절창 실험(`season_test.py`), 평면경사·GNSS(`validate_ramp*.py`), 지도(`make_maps.py`), **상승/하강 경사 판정(`tilt_verdict.py`)**, 실패한 화소별 분해 2건(`decompose_asc_dsc.py`, `decomp_csk_dsc.py`) |
| `hotspots/` | S1 PS secular에서 평면 제거 후 국지 침하 이상 군집 추출·검증(홀/짝 에폭 분할, 공간 셔플 귀무, CSK 부호)·사고기록 대조 |
| `s1_asc/` | Sentinel-1 상승 path127 73씬 PS·SBAS 체인 |
| `s1_dsc/` | Sentinel-1C 하강 path32 21씬 다운로드(ASF, curl 쿠키자)·궤도·topsStack 코레지·SBAS |

## 실행 순서(요약)
1. `csg_adapter/run_unpack_all.sh` → stripmapStack 코레지(ISCE2 표준) → `psi/crop_seoul.py`
2. `psi/run_mt_prep.sh` → `run_extract_cands.sh` → `run_stamps.sh 1 6`, `run_stamps.sh 7 8`(step 8 블록이 7 안에 중첩되어 `-s 8 -e 8`은 아무것도 안 함)
3. `psi/make_ps_result.py` → `seoul_csk_ps.npz`
4. `sbas/run_sbas_igrams.sh` → `run_mintpy.sh`
5. `compare/compare_run.py`, `season_test.py`, `make_maps.py`, `tilt_verdict.py`
6. `hotspots/hotspots.py` → `hotspot_validate.py` → `hotspot_export.py`

## 주의
- `stamps_patches/` 실행은 `psi_env.sh`처럼 PYTHONPATH 앞에 섀도 디렉토리를 두어 원본 포팅판을 덮어쓰는 방식. 원 StaMPS 라이선스(GPL) 적용 대상.
- PS npz의 `inc_deg` 필드는 이름과 달리 **라디안**. MintPy geo h5의 입사각은 도.
- CSK 0.72년(겨울→여름) 결과는 mm/yr로 환산하지 말 것. 누적 변위(mm)로만.
- 데이터(SLC·h5·npz·shp)는 포함하지 않음.
