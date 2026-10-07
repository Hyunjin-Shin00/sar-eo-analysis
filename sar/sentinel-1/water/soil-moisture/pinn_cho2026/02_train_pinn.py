"""
Cho et al. (2026, Zenodo 10.5281/zenodo.20606294) PINN-WCM 재구현.

공개 자료에는 학습 코드가 없고 입출력 표(Data_s1_rescale_QC_results_VF.xlsx)만 있으므로
표에서 역산한 전처리식 + 표준 Water Cloud Model(Attema & Ulaby 1978)로 손실함수를 구성한다.

  입력  x = [VVnorm(dB), VHnorm(dB), LIA(deg), DpRVI]
  정규화 σ0_norm(dB) = σ0(dB) + 0.13·(LIA − 38)          ← 표에서 오차 1e-15로 역산
  DpRVI = 1 − m·β,  q=VH/VV, m=(1−q)/(1+q), β=1/(1+q)    ← 표의 q, mc, bc 컬럼과 일치

  세 네트워크 (논문과 동일 명칭)
   FFNN     : L = MSE(SM, SM_insitu)
   PINN_LR  : L = MSE + λ·MSE_dB( a + b·SM_pred , VVnorm )                      (선형회귀 물리항)
   PINN_WCM : L = MSE + λ·MSE_dB( WCM(SM_pred, V=DpRVI, θ) , σ0_norm ) (VV, VH 각각)
              σ0 = A·V·cosθ·(1−τ²) + τ²·σ0_soil,  τ² = exp(−2·B·V/cosθ),  σ0_soil[dB] = C + D·SM
              A,B,C,D 는 편광별 학습 가능 파라미터 (A,B,D>0 softplus 제약)

  검증: 해상도(10/30/50 m)별, 5-fold 교차검증 out-of-fold 예측 → 저자 공개 예측값과 같은 지표로 비교.
  최종 모델: 10 m 전체 자료로 학습해 지도 산출(04_apply_map.py)에 사용.
"""
import json, sys
import numpy as np, pandas as pd, torch, torch.nn as nn
from sklearn.model_selection import KFold

ROOT = "<WORK_ROOT>"
XLSX = f"{ROOT}/data/zenodo/Zenodo_PINN-WCM/data/Data_s1_rescale_QC_results_VF.xlsx"
FEATS = ["VVnorm", "VHnorm", "LIA", "DpRVI"]
LAMBDA = 0.1
EPOCHS = 4000
torch.set_num_threads(8)


class Net(nn.Module):
    def __init__(self, mode, mu, sd):
        super().__init__()
        self.mode = mode
        self.register_buffer("mu", torch.tensor(mu, dtype=torch.float32))
        self.register_buffer("sd", torch.tensor(sd, dtype=torch.float32))
        self.f = nn.Sequential(nn.Linear(4, 64), nn.Tanh(), nn.Linear(64, 64), nn.Tanh(), nn.Linear(64, 64), nn.Tanh(), nn.Linear(64, 1))
        # 물리 파라미터 (VV, VH)
        self.lr = nn.Parameter(torch.tensor([-14.0, 10.0]))          # a, b  (dB = a + b·SM)
        self.A = nn.Parameter(torch.tensor([-2.0, -4.0]))            # softplus → A
        self.B = nn.Parameter(torch.tensor([-1.0, -1.0]))            # softplus → B
        self.C = nn.Parameter(torch.tensor([-16.0, -24.0]))          # dB
        self.D = nn.Parameter(torch.tensor([15.0, 15.0]))            # dB per m3/m3 (softplus 미적용, 초기 양수)

    def forward(self, x):
        sm = 0.5 * torch.sigmoid(self.f((x - self.mu) / self.sd))   # 0~0.5 m3/m3
        return sm.squeeze(-1)

    def wcm_db(self, sm, theta_deg, V):
        cos = torch.cos(torch.deg2rad(theta_deg)).unsqueeze(-1)
        V = V.unsqueeze(-1)
        A = nn.functional.softplus(self.A); B = nn.functional.softplus(self.B)
        tau2 = torch.exp(-2 * B * V / cos)
        soil = 10 ** ((self.C + nn.functional.relu(self.D) * sm.unsqueeze(-1)) / 10)
        sig = A * V * cos * (1 - tau2) + tau2 * soil
        return 10 * torch.log10(sig.clamp_min(1e-6))                  # [N,2] VV,VH dB

    def phys_loss(self, x, sm):
        if self.mode == "PINN_LR":
            return ((self.lr[0] + self.lr[1] * sm - x[:, 0]) ** 2).mean()
        if self.mode == "PINN_WCM":
            return ((self.wcm_db(sm, x[:, 2], x[:, 3]) - x[:, :2]) ** 2).mean()
        return torch.zeros(())


def fit(mode, X, y, X_unlab=None, seed=0):
    torch.manual_seed(seed)
    net = Net(mode, X.mean(0), X.std(0))
    X = torch.tensor(X, dtype=torch.float32); y = torch.tensor(y, dtype=torch.float32)
    Xu = torch.tensor(X_unlab, dtype=torch.float32) if X_unlab is not None else X
    opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=0)
    for _ in range(EPOCHS):
        opt.zero_grad()
        loss = ((net(X) - y) ** 2).mean()
        if mode != "FFNN":
            # 물리항은 dB² 단위 → (0.06 m3/m3)² 수준의 데이터항과 맞추도록 스케일
            loss = loss + LAMBDA * 1e-3 * net.phys_loss(Xu, net(Xu))
        loss.backward(); opt.step()
    return net


def predict(net, X):
    with torch.no_grad():
        return net(torch.tensor(X, dtype=torch.float32)).numpy()


def metrics(y, p):
    b = np.mean(p - y); rmse = np.sqrt(np.mean((p - y) ** 2))
    return dict(n=len(y), R=np.corrcoef(y, p)[0, 1], RMSE=rmse, bias=b, ubRMSE=np.sqrt(max(rmse**2 - b**2, 0)))


def main():
    d = pd.read_excel(XLSX, "Data_total")
    out = []
    for res in (10, 30, 50):
        dr = d[d.resolution == res].reset_index(drop=True)
        X = dr[FEATS].values.astype(np.float32); y = dr.SM_insitu.values.astype(np.float32)
        for mode in ("FFNN", "PINN_LR", "PINN_WCM"):
            oof = np.zeros(len(dr))
            for k, (tr, te) in enumerate(KFold(5, shuffle=True, random_state=42).split(X)):
                net = fit(mode, X[tr], y[tr], X_unlab=X, seed=k)   # 물리항은 라벨 없는 전체 입력에도 적용
                oof[te] = predict(net, X[te])
            dr[f"ours_{mode}_cv"] = oof
            dr[f"ours_{mode}_insample"] = predict(fit(mode, X, y, seed=0), X)   # 저자 표와 같은 조건(학습자료 적합)
            print(res, mode, "CV", metrics(y, oof), "IN", metrics(y, dr[f"ours_{mode}_insample"].values), flush=True)
        out.append(dr)
    res_df = pd.concat(out)
    res_df.to_csv(f"{ROOT}/outputs/table_reproduction_oof.csv", index=False)

    # 최종 모델 (10 m 전체) 저장 → 지도 적용
    dr = d[d.resolution == 10]
    X = dr[FEATS].values.astype(np.float32); y = dr.SM_insitu.values.astype(np.float32)
    net = fit("PINN_WCM", X, y, seed=0)
    torch.save(net.state_dict(), f"{ROOT}/outputs/pinn_wcm_10m.pt")
    sp = nn.functional.softplus
    wcm = dict(A=sp(net.A).tolist(), B=sp(net.B).tolist(), C=net.C.tolist(), D=nn.functional.relu(net.D).tolist(),
               mu=net.mu.tolist(), sd=net.sd.tolist())
    json.dump(wcm, open(f"{ROOT}/outputs/pinn_wcm_10m_params.json", "w"), indent=1)
    print("WCM params (VV,VH):", wcm)


if __name__ == "__main__":
    main()
