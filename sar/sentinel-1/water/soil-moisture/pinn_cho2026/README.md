# sar/sentinel-1/water/soil-moisture/pinn_cho2026

Cho 2026 PINN-WCM 재구현 시도 (동료심사 전 논문, 검증용).

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `02_train_pinn.py` | Cho et al. (2026, Zenodo 10.5281/zenodo.20606294) PINN-WCM 재구현. | Excel | CSV · JSON |
| `04_cv_sweep.py` | 일반화(새 날짜 적용) 성능 기준 PINN-WCM 설정 선택. | Excel | CSV |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate bldseg      # PyTorch · transformers
```

- 환경 정의: [`environment/`](../../../../../environment/)

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `02_train_pinn.py` | `ROOT` | `<WORK_ROOT>` |
