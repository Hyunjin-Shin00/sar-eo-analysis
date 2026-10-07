# nepal-flood — 2026 네팔 라수와 빙하붕괴 돌발홍수 Sentinel-1 SLC 분석

Sentinel-1D SLC 버스트(ASF)로 ISCE2 topsStack 간섭 스택을 만들고, (1) 결맞음 변화와 (2) 후방산란(dB) 감소로 홍수 피해를 탐지하려 한 코드. 결맞음 방식은 실패했고(고도 교란), 후방산란 강임계 + 대조쌍 방식으로 하류 피해와 붕괴 원점을 탐지함.

## 구성
| 폴더 | 파일 | 역할 |
|---|---|---|
| `download/` | `burst_pick.py` | 관심 지점(붕괴원점·마을)을 덮는 버스트 ID 선택 (asf_search) |
| | `dl.py` | ASF SLC-BURST 다운로드 (`~/.netrc` 의 Earthdata 자격 사용, 코드에 값 없음) |
| | `mk_safe.py` | burst2safe 로 버스트를 SAFE 로 재조립 |
| `stack/` | `setup_stack.sh` | stackSentinel.py 설정 (27룩: `-z 3 -r 9`) |
| | `run_stack.sh` | run_files 를 `&` 제거 후 순차 실행 + 종료코드 검사 |
| | `geocode_pairs.sh` | 결맞음·간섭도 지오코딩 (룩수는 config 에서 읽음) |
| `analysis/` | `coh_change.py` | Δcoh = coh(사건쌍) − coh(기준쌍) |
| | `corridor_matched2.py` | 고도 + 기준결맞음 2차원 매칭 후 하천 회랑 초과 Δcoh 검정 (→ 신호 없음) |
| | `make_map.py` | 결맞음 변화 지도 |
| | `db_geocode.py` | 날짜별 멀티룩 강도(dB)를 간섭도 격자로 만들어 지오코딩 준비 |
| | `otsu_flood.py` | Otsu 분할 시도 (실패 기록 보존) |
| | `flood_detect.py` | 하천 300 m 버퍼 안 강임계(dB 감소) + 연결성분 필터 + 대조쌍(정상 12일) 오탐 보정 |
| | `source_scar.py` | 붕괴 원점 주변 박스에 같은 기준 적용 |
| | `flood_map.py` | 탐지 지도 + 군집 좌표 |
| | `exposure.py` | WorldPop 2020 + OSM 건물·도로·행정구역 노출 집계 |
| | `nrsc_check.py` | 공개 재난지도(NRSC/ISRO)가 지목한 시설 지점의 SAR 변화 대조 |
| `render/` | `render_chips.py`, `render_mainmap.py`, `render_extras.py`, `build_card.py` | 결과 요약 카드(인포그래픽) 조립 |

## 실행 순서
```bash
export DATA_ROOT=<DATA_ROOT>     # SLC/, work/, DEM/, aux/, analysis/ 를 가진 루트
python download/burst_pick.py; python download/dl.py; python download/mk_safe.py
bash stack/setup_stack.sh ASC_085 && bash stack/run_stack.sh ASC_085 && bash stack/geocode_pairs.sh ASC_085
python analysis/coh_change.py ASC_085; python analysis/corridor_matched2.py ASC_085
python analysis/db_geocode.py ASC_085 20260804 20260816 20260828   # 이후 geocodeIsce.py 로 db_*.geo 생성
python analysis/flood_detect.py ASC_085 -6 300 5     # 보수 기준 (카드는 -5 300 3)
python analysis/source_scar.py ASC_085 -6 3
python analysis/flood_map.py ASC_085; python analysis/exposure.py ASC_085; python analysis/nrsc_check.py ASC_085
python render/render_chips.py ASC_085; python render/render_mainmap.py ASC_085; python render/render_extras.py ASC_085; python render/build_card.py ASC_085 v13
```

## 환경 메모
- ISCE2 2.6.3 은 미션 ID `S1D` 를 거부함. `isceobj/Sensor/TOPS/Sentinel1.py` 에 다음 분기를 추가해야 한다(42 는 절대궤도→상대궤도 실측 7건으로 역산한 값, 175개 후보 중 유일해):
  ```python
  elif mission == 'S1D':
      burst.trackNumber = (orbitnumber-42)%175 + 1
  ```
- 결맞음 분석은 27룩 필수. 4룩(`-z 1 -r 4`)은 결맞음 편향이 커서 결론 불가.
- topsStack run_file 각 줄 끝의 `&` 를 그대로 eval 하면 다음 run 과 경합한다 → `run_stack.sh` 사용.
- merged SLC 는 VRT 만 만들어지므로 `reference/`·`secondarys/` 버스트를 지우면 진폭 분석 불가.
- 진폭은 SLC DN 기반이라 절대 σ⁰ 보정이 안 되어 있음. 날짜 간 차이에는 상수가 상쇄되지만 절대 dB 임계에는 쓰면 안 됨.
