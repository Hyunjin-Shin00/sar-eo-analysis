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
