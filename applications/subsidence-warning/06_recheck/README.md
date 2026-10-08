# applications/subsidence-warning/06_recheck

판정 결과 재검증.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `recheck_sasang_rule.py` | 사상 2단(선별 게이트 + 경보) 규칙을 lead_time_bk npz 로 독립 재계산. | NumPy | — |
| `recheck_zone.py` | 사상 위험구역 면적·사고 포함 여부 재계산 (shapely+pyproj). | JSON | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../environment/)
