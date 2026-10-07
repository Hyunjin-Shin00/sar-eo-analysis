# sar/sentinel-1/insar/psinsar/stamps_patches

StaMPS 파이썬 포팅본에 적용한 패치 — 업스트림 원본은 포함하지 않는다.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `ps_load_initial_isce.py` | [StaMPS 패치] ISCE2 산출물을 StaMPS 초기 구조로 적재 | HGT · TXT | — |
| `ps_merge_patches.py` | [StaMPS 패치] 패치별 PS 결과 병합 | NumPy · 파일 묶음 | NumPy |
| `ps_scn_filt.py` | [StaMPS 패치] 공간상관 대기오차(SCN) 필터 | NumPy | NumPy |
| `ps_select.py` | FIX: upstream built one task tuple per PS (n_ps can be >1.5M) with `pm` inside it, so Pool.map pickled pm - in | NumPy | NumPy |
| `ps_unwrap.py` | [StaMPS 패치] 3D 위상 언래핑 | NumPy | NumPy |
| `selpsc_patch.py` | [StaMPS 패치] 진폭분산 기준 PS 후보 선별 | — | 텍스트/로그 |
| `uw_unwrap_from_grid.py` | [StaMPS 패치] 격자 기반 언래핑 | NumPy | — |
