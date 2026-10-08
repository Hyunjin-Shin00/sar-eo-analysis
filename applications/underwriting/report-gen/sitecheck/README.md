# sitecheck

주소 하나로 **건물 · 야적물 · 이격거리 · 대장 대조** 네 판정을 내는 패키지임.
바깥에는 진입점(`run.py` · `demo.py` · `hand_writting.py`)과 설치 목록만 두고 코드는 전부 여기 있음.

진입점 셋이 갈리는 지점은 **건물 폴리곤을 어디서 얻는가** 하나뿐이고,
그 뒤로는 `analyze.py` 한 길을 같이 지남.

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `analyze.py` | 주소 → 네 판정. 진입점 셋이 같이 지나는 한 길 | 주소, 건물 출처(model/GT) | `out/<주소>/result.json` |
| `pipeline.py` | 건물이 정해진 뒤의 공통 경로 | 건물 폴리곤·필지·대장 | 단계 1~4 결과 |
| `settings.py` | 경로·키·영상 등록부. **패키지 밖을 가리키는 것은 전부 여기 한 곳에만 둠** | 환경변수, `.env` | 설정 객체 |
| `rules.py` | A1·A3·A4·A5 법정 판정 규칙의 **단일 출처**. 임계값과 판정문구가 전부 여기 있음 | — | 임계값·문구 |
| `schema.py` | 네 결과물의 공통 출력 형식. 전부 GeoJSON FeatureCollection, 판정은 같은 key(`level`·`label`·`reason`·`basis`) | 단계별 산출 | 표준 Feature |
| `gt.py` | 건물 출처 ② — 사람이 그린 정답. 모델을 지나지 않는 길 | GT 폴리곤 | 건물 Feature |
| `hand.py` | 손보정 — 자동으로 못 내는 자리를 사람이 채움. **값은 여기 없고** 저장소 뿌리 `hand_writting.py` 에만 있음 | 보정표 | 치환된 값 |
| `draw.py` | 그림 규칙 — **그림을 만드는 곳은 이 파일 하나뿐임** | 결과 Feature | `0~3_*.png` |
| `ext.py` | 외부 공공데이터(소방서 좌표·기상 30년) — 활용신청이 끝난 것만 | 공개 API·정적표 | 보고서 5·6면 값 |
| `cli.py` | `run.py` 와 `demo.py` 가 **같은 명령줄**을 쓰게 하는 자리 | argv | 파싱된 옵션 |
| `console.py` | 화면 출력 — 한 벌이고 여기 하나임 | 진행 상태 | 단계별 한 줄 |
| `naming.py` | 주소 → 폴더 이름 | 주소 문자열 | slug |

## 하위 폴더

| 폴더 | 내용 |
|---|---|
| [`steps/`](steps/) | 단계 0~4 와 좌표 정합 보정 |
| [`report/`](report/) | 값 → 보고서 한 부 (단일시점 6면 · 비교분석 4면) |
| [`vendor/`](vendor/) | 떼어와 자립형으로 만든 부품 — 건물 탐지기·공공 API·VLM·분광 |
| [`tools/`](tools/) | 점검(`check.py`)·장면 등록(`add_scene.py`)·GT 동기화(`sync_gt.py`) |

## 키

- `VWORLD_KEY` · `DATA_GO_KR_KEY` — `assets/.env.geodata`
- `OPENAI_API_KEY` — `assets/.env.openai`
- 저장소에는 빈 `.env.*.example` 만 있음. VLM 키가 없으면 야적 레이어만 비고 그 사실을 `result.json` note 에 적음 — 나머지 셋은 그대로 나옴
