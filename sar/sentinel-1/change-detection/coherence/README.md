# sar/sentinel-1/change-detection/coherence

**CCD** — 사건 전후 코히런스 저하로 피해를 가린다. 건물 붕괴·침수처럼 산란 구조가 바뀌는 변화에 민감.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `analyze_coh.py` | 八戸線 本八戸~小中野 고가교 — 2025-12-08 青森県東方沖 지진 결맞음 변화 검정. | GeoTIFF · shp/GeoJSON | GeoTIFF · CSV · NumPy · 텍스트/로그 |
| `ccd_analysis_left.py` | Coherence Change Detection (CCD) — 지진 피해 예비분석 [DISCLAIMER] 현장 미검증 예비분석. 확정 피해 판정 아님. | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |
| `ccd_analysis_right.py` | 우측 궤도 코히런스 변화탐지 — 사건 전후 저하 구역 추출 | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |
| `coh_change.py` | 결맞음 변화 탐지 (Coherence Change Detection) — 2026 네팔 홍수 | GeoTIFF | — |
| `null_distribution.py` | 八戸線 결맞음 저하의 유의성을 두 갈래로 굳힌다. | shp/GeoJSON | CSV |
| `null_distribution_rail.py` | 결정적 검증 — 장면 안 모든 철도 회랑에 같은 400 m 창 탐색을 돌린다. | shp/GeoJSON | CSV |
| `profile_along_track.py` | 八戸線 고가교 결맞음 변화의 '위치'를 본다. | shp/GeoJSON | CSV |
| `run_coh.sh` | 八戸線 本八戸~小中野 고가교 — 2025-12-08 青森県東方沖 지진(Mj7.5, 八戸 진도 6강). 약 20개소 손상, 第2柏崎高架橋 약 400 m 기둥 曲げ破壊, 12/30 전선 재개. | — | — |
| `run_coh_pairs.sh` | 결맞음 페어 일괄 처리(범용). 사용: run_coh_pairs.sh <SAFE루트> <출력접두> <subswath> "<AOI wkt>" <cohAz> <cohRg> <nRg> <pix> <a:b | — | — |
| `s1_ccd.py` | S1 코히런스 변화탐지 + 진폭 변화 (Sentinel-1). N2 CCD와 동일 산출 구성. | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |
