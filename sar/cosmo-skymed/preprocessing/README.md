# sar/cosmo-skymed/preprocessing

CSG 산출물 언팩과 센서 어댑터 — StaMPS 입력 형식으로 맞춤.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `bedrock_candidates.py` | Screen Seoul's exposed-bedrock massifs as PS-InSAR reference-point candidates. | GeoTIFF | — |
| `csg_baselines.py` | Perpendicular/temporal baselines for the CSG stack, and master selection. | HDF5 · 파일 묶음 | — |
| `csg_sensor.py` | COSMO-SkyMed Second Generation (CSG) SLC reader for ISCE2 2.6.3. | HDF5 | — |
| `run_unpack_all.sh` | Unpack every CSG scene into SLC/<date>/.  Re-running skips finished scenes, so this is also the "3~4장 추가분" cat | HDF5 · 파일 묶음 | — |
| `unpack_csg.py` | Unpack one CSG scene into the ISCE2 stripmapStack SLC layout. | 파일 묶음 | — |

## 주요 인자

- `unpack_csg.py` — `--block`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate isce2_snaphu      # ISCE2 · snaphu
```

- 환경 정의: [`environment/`](../../../environment/)

### 진입점

```bash
python unpack_csg.py -i <값> -o <값>
```
Unpack one CSG scene into the ISCE2 stripmapStack SLC layout. Produces <slcdir>/<date>.slc , <date>.slc.xml , <date>.slc.vrt , data(.dat/.dir) exactly

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `-i` | ● |  | directory holding the CSG .h5 (or the .h5 itself) |
| `-o` | ● |  | output SLC directory, named <YYYYMMDD> |
| `--block` |  | `2048` | lines per I/O block (caps peak memory) |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `bedrock_candidates.py` | `INC` | `20.05` |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `csg_baselines.py`
