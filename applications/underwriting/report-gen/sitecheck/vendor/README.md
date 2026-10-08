# vendor — 떼어와 자립형으로 만든 부품

다른 저장소에서 옮겨 온 코드임. 공통 원칙은 **폴더만 떼어가도 돌아야 한다**는 것이라
원본 패키지를 import 하지 않음.

| 파일·폴더 | 역할 | 입력 | 출력 |
|---|---|---|---|
| [`dinov3seg/`](dinov3seg/) | 건물 탐지기 — DINOv3 + Mask2Former. [`../../../building-seg/`](../../../building-seg/) 의 **그 전 세대(run4)** | 장면 창 | 폴리곤 |
| `dinov3seg_run.py` | 위 모델 추론을 이 폴더 안에서 돌리는 진입점 | 장면, 가중치 | 장면좌표 폴리곤 |
| `geoapi.py` | V-World · 건축물대장 API 클라이언트. `geopipe` 를 import 하지 않는 자립형 | 주소·PNU, 키 | 좌표, 필지, 대장 표제부 |
| `gisdb.py` | GIS건물통합정보 조회 — **PNU 로 고름**. 한 행이 대장의 한 동에 대응함 | PNU | 건물 footprint·속성 |
| `yard_vlm.py` | 야적물 판독 VLM — 프롬프트·스키마·호출. 원본은 `parcelscan/yardscan.py` | 타일 이미지, 캡션 | 적재 구역 판독 |
| `shadow.py` | 촬영시각·위경도 → 태양 방위각·고도와 그림자 방향. 야적 판독 타일 캡션의 단서 | 시각, 좌표 | 방위각·고도·그림자 길이 |
| `spectral.py` | 4밴드(B·G·R·NIR) tif 에서 분광 지표 산출. **밴드 순서 주의** — colorinterp 태그를 믿지 말 것 | 4밴드 tif | 지표 배열 |
| `ensemble.py` | 여러 폴리곤 모델 예측을 합의 기반으로 재점수·융합 | 모델별 폴리곤 | 융합 폴리곤 |

## 출처 표기

- `dinov3seg/ORIGIN.md` · `UPSTREAM_README.md` 에 원본 위치와 수정 내역이 있음
- `hf/` 아래 `config.json` · `preprocessor_config.json` 은 오프라인 구성용 설정만 있고 **가중치는 없음**
