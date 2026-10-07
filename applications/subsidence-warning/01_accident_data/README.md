# applications/subsidence-warning/01_accident_data

지반침하 사고 이력 수집·지오코딩 (공공데이터).

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `cause_api_label.py` | AOI 93건의 원인 라벨을 국토안전관리원 Open API 실제 원인값(sagoReason)으로 확정. | CSV · JSON | JSON |
| `collect_subsidence.py` | 국토안전관리원 지하안전정보 Open API 지반침하사고 전수 수집기. | CSV | — |
| `fetch_reasons.py` | 리스트 API(getSubsidenceList01)에서 사고원인(sagoReason)만 전수 수집. | CSV | — |
| `geocode_subsidence.py` | subsidence_accidents.csv 의 주소를 VWorld 지오코더로 위경도(EPSG:4326) 변환. | CSV | — |
| `kakao_fallback.py` | VWorld 무매칭(none) 행을 Kakao 지오코더로 2차 폴백. | CSV · JSON | — |

## 주요 인자

- `collect_subsidence.py` — `--date-from` `--date-to` `--out` `--rows` `--service-key` `--tps` `--workers`
- `geocode_subsidence.py` — `--in` `--key` `--limit` `--out` `--tps` `--workers`
- `kakao_fallback.py` — `--csv` `--key` `--sleep` `--types`
