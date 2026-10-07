# sar/sentinel-1/water/soil-moisture/pinn_cho2026

Cho 2026 PINN-WCM 재구현 시도 (동료심사 전 논문, 검증용).

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `02_train_pinn.py` | Cho et al. (2026, Zenodo 10.5281/zenodo.20606294) PINN-WCM 재구현. | Excel | CSV · JSON |
| `04_cv_sweep.py` | 일반화(새 날짜 적용) 성능 기준 PINN-WCM 설정 선택. | Excel | CSV |
