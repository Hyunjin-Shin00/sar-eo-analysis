"""일반화(새 날짜 적용) 성능 기준 PINN-WCM 설정 선택.
검증 = 시간 블록 CV(연도 단위 leave-one-year-out) → 무작위 CV보다 엄격, 지도 산출(2025-26 신규 날짜) 상황과 같음.
비교: 네트워크 크기 × 물리항 가중치 λ × epoch, 그리고 기후값(지점별 평균) 기준선."""
import sys, numpy as np, pandas as pd, torch, itertools
sys.path.insert(0, '<WORK_ROOT>/code')
import importlib; tp = importlib.import_module('02_train_pinn')
d = pd.read_excel(tp.XLSX, 'Data_total'); d = d[d.resolution == 10].reset_index(drop=True)
X = d[tp.FEATS].values.astype(np.float32); y = d.SM_insitu.values.astype(np.float32); yr = d.date.dt.year.values
R = lambda a, b: np.corrcoef(a, b)[0, 1]
def evaluate(p):
    an = lambda v: v - pd.Series(v).groupby(d.site).transform('mean').values  # 지점 평균 제거(시간 변동만)
    return dict(R=R(y, p), RMSE=np.sqrt(np.mean((p - y) ** 2)), R_anom=R(an(y), an(p)))
# 기후값 기준선: 학습연도의 지점별 평균
clim = np.zeros(len(d))
for Y in np.unique(yr):
    tr = yr != Y; m = pd.Series(y[tr]).groupby(d.site[tr].values).mean()
    clim[~tr] = d.site[~tr].map(m).values
print('climatology', evaluate(clim), flush=True)
rows = []
for width, lam, ep in itertools.product([8, 32], [0.0, 0.1, 1.0, 10.0], [300, 1500]):
    tp.EPOCHS = ep; tp.LAMBDA = lam
    def make(mode):
        class N(tp.Net):
            def __init__(s, *a):
                super().__init__(*a)
                s.f = torch.nn.Sequential(torch.nn.Linear(4, width), torch.nn.Tanh(), torch.nn.Linear(width, width), torch.nn.Tanh(), torch.nn.Linear(width, 1))
        return N
    tp_Net = tp.Net; tp.Net = make('PINN_WCM')
    p = np.zeros(len(d))
    for Y in np.unique(yr):
        tr = yr != Y
        net = tp.fit('PINN_WCM' if lam > 0 else 'FFNN', X[tr], y[tr], X_unlab=X, seed=0)
        p[~tr] = tp.predict(net, X[~tr])
    tp.Net = tp_Net
    m = evaluate(p); m.update(width=width, lam=lam, epochs=ep); rows.append(m); print(m, flush=True)
pd.DataFrame(rows).to_csv('<WORK_ROOT>/outputs/cv_sweep_leave_year_out.csv', index=False)
