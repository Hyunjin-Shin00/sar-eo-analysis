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

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate isce2_snaphu      # ISCE2 · snaphu
```

- 환경 정의: [`environment/`](../../../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `COH_THRESH` | 결맞음 임계값 |
| `S1_ROOT` | Sentinel-1 원본 트리 |
| `S1_SRC_STACK` | 코드 참조 |

### 진입점

```bash
python unwrap_s1.py -i <값> -c <값> -u <값>
```
snaphu unwrapping for the S1 SBAS pairs. stripmapStack's unwrap.py wants a full ISCE frame shelve, which topsStack's merged product does not provide. 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `-i` | ● |  |  |
| `-c` | ● |  |  |
| `-u` | ● |  |  |
| `-r` |  | `8` |  |
| `-a` |  | `2` |  |
| `-d` |  | `4.0` |  |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `crop_s1.py`
