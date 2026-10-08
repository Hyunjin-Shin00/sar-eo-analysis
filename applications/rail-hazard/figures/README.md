# applications/rail-hazard/figures

근거 그림 생성.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `hachinohe_evidence.py` | 八戸線 고가교 결맞음 변화 증거도. | CSV · shp/GeoJSON | PNG 그림 |
| `style.py` | matplotlib 공통 스타일 — 한글·일본어 폰트 등록과 다크 테마 색상. | PNG | PNG 그림 |
| `synthesis_detectability.py` | 전 케이스 종합 — SAR 탐지 가능 영역 (사건 후 경과시간 × 대상 공간규모). | PNG | PNG 그림 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `WORK_ROOT` | 작업 디렉터리 루트 |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `hachinohe_evidence.py`, `style.py`, `synthesis_detectability.py`
