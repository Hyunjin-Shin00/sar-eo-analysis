# wildfire — dNBR 산불 피해등급 분류

화재 전후 NBR 차분으로 피해 범위와 심각도를 USGS 5등급으로 나눈다.

## 지수

```
NBR  = (NIR − SWIR2) / (NIR + SWIR2)      # Sentinel-2: (B8 − B12) / (B8 + B12)
dNBR = NBR_before − NBR_after
```

연소 후에는 NIR이 떨어지고 SWIR이 올라가므로 dNBR이 커진다.

## USGS 피해등급

| dNBR | 등급 |
|---|---|
| < 0 | 1 — 미피해 (Unburned) |
| 0 ~ 0.12 | 2 — 저피해 (Low) |
| 0.12 ~ 0.24 | 3 — 중저 (Moderate-low) |
| 0.24 ~ 0.36 | 4 — 중고 (Moderate-high) |
| > 0.36 | 5 — 고피해 (High) |

## 파일

`notebooks/dnbr_wildfire.ipynb` — 영상 수집 → 구름·연기 마스킹 → dNBR → 등급 분류 → 시각화

## 구름·연기 마스킹

**OmniCloudMask**를 쓴다. 연기를 구름과 함께 지우지 않으면 피해등급이 과대 추정된다
(연기가 NIR을 가려 dNBR을 부풀린다). 실제로 겪은 문제라 마스킹을 먼저 건다.

## 적용 사례

하와이(2023.08), 그리스 에비아·키티라(2025.07), 산청(2025.03), 의성(2025.03)

## 정지궤도 병행

GK2A / GOCI-II 로 화점(hotspot)과 연기 확산을 시간 단위로 추적한다.
극궤도(Sentinel-2)는 공간해상도, 정지궤도는 시간해상도를 맡는 역할 분담.
기상 자료(풍향·풍속·습도)를 겹쳐 확산 방향과 대조한다.
