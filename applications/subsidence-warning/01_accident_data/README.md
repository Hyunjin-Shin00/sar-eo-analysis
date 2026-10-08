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

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 환경변수

| 이름 | 설명 |
|---|---|
| `DATA_GO_KR_KEY` | 공공데이터포털 인증키 |
| `KAKAO_KEY` | 카카오 로컬 API 키 |
| `VWORLD_KEY` | V-World 인증키 |

### 진입점

```bash
python collect_subsidence.py 
```
국토안전관리원 지하안전정보 Open API 지반침하사고 전수 수집기. 1단계: getSubsidenceList01 로 사고 리스트를 전 기간 페이징 수집 (sagoNo + 리스트에만 있는 사고원인 sagoReason 확보) 2단계: getSubsidenceInfo01 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--date-from` |  | `20000101` | 조회 시작일 YYYYMMDD (기본 20000101) |
| `--date-to` |  |  |  |
| `--rows` |  | `100` | 리스트 페이지당 건수 (기본 100) |
| `--out` |  | `./subsidence_accidents.csv` | 출력 CSV 경로 |
| `--service-key` |  |  | data.go.kr Decoding 서비스키 |
| `--workers` |  |  |  |
| `--tps` |  |  |  |

```bash
python geocode_subsidence.py 
```
subsidence_accidents.csv 의 주소를 VWorld 지오코더로 위경도(EPSG:4326) 변환. 전략(주소당 순차 시도, 첫 성공 채택): 1) parcel(지번) : "시도 시군구 동 <지번>" (addr 괄호 앞 숫자부, 서술어 tail 제거) 2)

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--in` |  | `./subsidence_accidents.csv` |  |
| `--out` |  | `./subsidence_accidents_geocoded.csv` |  |
| `--key` |  |  | VWorld apiKey (또는 VWORLD_KEY 환경변수) |
| `--workers` |  |  |  |
| `--tps` |  |  |  |
| `--limit` |  | `0` | 상위 N건만 처리(테스트용, 0=전체) |

```bash
python kakao_fallback.py 
```
VWorld 무매칭(none) 행을 Kakao 지오코더로 2차 폴백. Kakao 주소검색(지번/도로명) → 실패 시 키워드(장소명) 검색 순으로 시도. subsidence_accidents_geocoded.csv 를 제자리 갱신(백업 생성). 새 geocodeType:

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--csv` |  |  |  |
| `--key` |  |  | Kakao REST API 키 (또는 KAKAO_KEY 환경변수) |
| `--types` |  | `none` | 재지오코딩 대상 geocodeType (콤마구분, 기본 none) |
| `--sleep` |  | `0.05` |  |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `cause_api_label.py`
