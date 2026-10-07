# sar/sentinel-1/insar/psinsar/ascending

상승궤도 PS 처리 체인.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `chain_s1.sh` | 상승궤도 PS 체인 일괄 실행 (크롭 → 스택 → StaMPS) | — | — |
| `chain_s1_678.sh` | StaMPS 6~8단계만 이어서 실행 | — | — |
| `crop_s1.py` | Crop the existing Sentinel-1 coregistered stack to the Seoul window. | JSON | — |
| `make_ps_result_s1.py` | Final PS product: SCLA- and SCN-corrected LOS displacement + WLS velocity. | NumPy | — |
| `run_crop_slc.sh` | AOI로 SLC 스택 크롭 | — | — |
| `run_make_sm.sh` | 단일 마스터 스택 생성 | — | — |
| `run_mintpy_s1.sh` | MintPy SBAS 실행 (상승궤도) | TXT | — |
| `run_sbas_s1.sh` | 자체 SBAS 역산 실행 | JSON | — |
| `run_stamps_s1.sh` | StaMPS 단계별 실행 | — | — |
| `sbas_lib_s1.py` | S1 SBAS helpers - multilooked interferograms from the cropped coregistered stack. | JSON | — |
| `unwrap_s1.py` | snaphu unwrapping for the S1 SBAS pairs. | XML | — |
