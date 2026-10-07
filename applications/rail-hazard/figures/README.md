# applications/rail-hazard/figures

근거 그림 생성.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `hachinohe_evidence.py` | 八戸線 고가교 결맞음 변화 증거도. | CSV · shp/GeoJSON | PNG 그림 |
| `style.py` | matplotlib 공통 스타일 — 한글·일본어 폰트 등록과 다크 테마 색상. | PNG | PNG 그림 |
| `synthesis_detectability.py` | 전 케이스 종합 — SAR 탐지 가능 영역 (사건 후 경과시간 × 대상 공간규모). | PNG | PNG 그림 |
