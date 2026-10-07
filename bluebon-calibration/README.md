# bluebon-calibration — 초소형 위성 전처리와 검보정

자사 CubeSat의 원시 바이너리를 영상으로 만들고, 포인팅 오차의 원인을 통계로 추적한다.

## 구성

| 디렉터리 | 내용 |
|---|---|
| `preprocessing/` | binary → GeoTIFF → RGB PNG 자동화 |
| `pointing/` | 포인팅 오차 ↔ 궤도·자세 메타데이터 상관분석 |

## preprocessing/

```
원시 bin → DN → Radiance → TOA Reflectance → 밴드 병합 → RGB 합성 → PNG
```

| 파일 | 역할 |
|---|---|
| `run.sh` / `run_band.sh` | 배치 처리 진입점 |
| `merge_bands.py` | 밴드별 GeoTIFF 병합 |
| `make_rgb_png.py` | RGB 합성 + 스트레치 + 감마 보정 |
| `read_thuillier.py` | Thuillier 태양 복사조도 스펙트럼 로드 (반사율 변환용) |

## pointing/

촬영 위치가 왜 어긋나는지를 메타데이터로 설명하려는 분석.

| 파일 | 역할 |
|---|---|
| `along_across_cal.py` | 기준 영상 대비 along/across 방향 오차 산출 |
| `build_analysis.py` | 오차값과 위성 메타데이터 매칭 테이블 구성 |
| `analysis_combined.py` | 상관분석 · 이상치 분석 · 그림 생성 |

### 분석 설계

표본이 65건(텔레메트리 보유 27건)으로 작아 **세 가지 상관계수를 함께** 본다.

| 계수 | 성격 | 쓰는 이유 |
|---|---|---|
| Pearson *r* | 선형 관계만 | 기준선 |
| Spearman *ρ* | 순위 기반, 비선형도 포착 | 이상치에 덜 민감 |
| Kendall *τ* | 쌍 비교 | n이 20대일 때 p-value가 더 정확 |

### 결론 요약

- **경과일(시간 드리프트)** 만이 along·across·total 모든 오차와 유의한 상관을 보였다 (along *r*=0.586, p<0.0001, n=65).
- across 오차는 **Tilt(roll)** 과 음의 상관 (*r*=−0.322, p=0.0089) — 자세 제어의 영향.
- 텔레메트리 27건에서 **GNSS–TLE 고도차 |Δalt|** 가 along·total 오차와 상관 (*r*=0.534 / 0.552).
- 이상치 그룹과 정상 그룹 사이에 **통계적으로 유의한 파라미터 차이는 없었다.**
  즉 이상치는 단일 원인으로 설명되지 않는다. 이 점을 그대로 보고에 남겼다.

> 메타데이터 자체(궤도 요소, 텔레메트리)는 비공개라 저장소에 포함하지 않았다.
> 코드는 동일 스키마의 CSV를 넣으면 그대로 돌아간다.
