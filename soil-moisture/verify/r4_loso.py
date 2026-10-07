"""LOSO (leave-one-site-out) check on Cho 2026 Zenodo table: RF on 4 inputs vs constant baseline vs authors' published predictions."""
import numpy as np, pandas as pd
from sklearn.ensemble import RandomForestRegressor
X = "<WORK_ROOT>/ref_Cho2026_PINN/data/zenodo/Zenodo_PINN-WCM/data/Data_s1_rescale_QC_results_VF.xlsx"
d = pd.read_excel(X, "Data_total"); F = ["VVnorm", "VHnorm", "LIA", "DpRVI"]
def m(y, p):
    e = p-y; return f"R={np.corrcoef(y, p)[0,1]:.3f} RMSE={np.sqrt((e**2).mean()):.4f} ubRMSE={np.sqrt(((e-e.mean())**2).mean()):.4f}"
for res in (10, 30, 50):
    a = d[d.resolution == res].dropna(subset=F+["SM_insitu"]).reset_index(drop=True); y = a.SM_insitu.values
    prf = np.zeros(len(a)); pc = np.zeros(len(a))
    for s in a.site.unique():
        tr = a.site != s
        rf = RandomForestRegressor(300, min_samples_leaf=5, n_jobs=8, random_state=0).fit(a.loc[tr, F], y[tr]); prf[~tr] = rf.predict(a.loc[~tr, F])
        pc[~tr] = y[tr].mean()
    print(res, "m n", len(a), "sites", a.site.nunique(), "| LOSO RF", m(y, prf), "| const", m(y, pc), "| authors PINN_WCM", m(y, a.PINN_WCM.values) if "PINN_WCM" in a else "")
    bias = (a.PINN_WCM - a.SM_insitu).groupby(a.site).mean().round(4).to_dict(); print("   authors per-site mean bias", bias)
