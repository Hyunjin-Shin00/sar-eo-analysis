# sar/sentinel-1/preprocessing/stack

ISCE2 `stackSentinel` 기반 코레지 SLC 스택 생성 — PS/SBAS 공통 입력.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `geocode_pairs.sh` | 간섭쌍별 결맞음/간섭도를 지오코딩. usage: geocode_pairs.sh <TRACK> | — | — |
| `run_all_steps.sh` | stackSentinel.py가 생성한 run 파일들을 순서대로 실행 run_stackSentinel.sh 실행 후 이 스크립트를 실행할 것 | — | — |
| `run_stack.sh` | topsStack run_files 순차 실행. run_file의 각 줄은 '&'로 끝나 병렬 실행을 의도하지만, 그러면 종료코드를 잃고 다음 run과 경합한다. 여기서는 '&'를 제거해 순차 실행 | — | — |
| `run_stackSentinel.sh` | stackSentinel.py 실행 스크립트 (PSInSAR / StaMPS 전처리) ISCE2 2.6.4, conda env: isce2_snaphu | — | — |
| `setup_stack.sh` | ISCE2 topsStack (interferogram) 설정 — 2026 네팔 홍수 (Rasuwa/Nuwakot + 붕괴원점) usage: setup_stack.sh <ASC_085/DSC_019 | — | — |
