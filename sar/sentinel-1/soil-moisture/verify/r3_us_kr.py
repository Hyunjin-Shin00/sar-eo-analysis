import numpy as np, pandas as pd
R = "<WORK_ROOT>"
d = pd.read_csv(f"{R}/case_US_Ma2020/outputs/retrievals.csv").dropna(subset=["SM_insitu"])
for c in ["SM_retrieved", "SM_global_min"]:
    y, p = d.SM_insitu.values, d[c].values; e = p-y
    print("US", c, "N", len(y), "R2", round(np.corrcoef(y, p)[0, 1]**2, 3), "bias", round(e.mean(), 3), "RMSE", round(np.sqrt((e**2).mean()), 3), "ubRMSE", round(np.sqrt(((e-e.mean())**2).mean()), 3))
# Korea region mean vs API, station metrics
for site, ins in [("GP", f"{R}/data/insitu_rda/GP_daily_2017_2026.csv"), ("HS", f"{R}/data/HS/insitu_rda/HS_daily.csv")]:
    t = pd.read_csv(f"{R}/outputs/{site}/{site}_station_timeseries_gao2017.csv", parse_dates=["date"])
    i = pd.read_csv(ins, parse_dates=["date"]).set_index("date"); i.loc[i.sm_vol <= 0, "sm_vol"] = np.nan
    # API with k=0.8: API_t = 0.8*API_{t-1} + P_t  (independent recursion, daily index)
    P = i.rain_mm.fillna(0); P = P.reindex(pd.date_range(P.index.min(), P.index.max()), fill_value=0)
    api = np.zeros(len(P)); 
    for j in range(len(P)): api[j] = (0.8*api[j-1] if j else 0) + P.iloc[j]
    api = pd.Series(api, P.index)
    v = t.dropna(subset=["map_mean_method1"]).copy(); v["api"] = api.reindex(v.date).values; v["ins"] = i.sm_vol.reindex(v.date).values
    k = v.api.notna(); kk = v.ins.notna()
    print(site, "region n", len(v), "R_vs_API(recursive k=0.8)", round(np.corrcoef(v.map_mean_method1[k], v.api[k])[0, 1], 3),
          "R_vs_insitu", round(np.corrcoef(v.map_mean_method1[kk], v.ins[kk])[0, 1], 3))
    s = t[t.valid == True].copy(); s["ins"] = i.sm_vol.reindex(s.date).values; s = s.dropna(subset=["ins", "SM_method1"])
    e = s.SM_method1-s.ins
    print(site, "station method1 n", len(s), "R", round(np.corrcoef(s.SM_method1, s.ins)[0, 1], 3), "ubRMSE", round(np.sqrt(((e-e.mean())**2).mean()), 3),
          "R(VV,insitu)", round(np.corrcoef(s.VV_dB, s.ins)[0, 1], 3), "insitu std", round(s.ins.std(), 3))
print("--- VV vs insitu variants")
for site, ins in [("GP", f"{R}/data/insitu_rda/GP_daily_2017_2026.csv"), ("HS", f"{R}/data/HS/insitu_rda/HS_daily.csv")]:
    t = pd.read_csv(f"{R}/outputs/{site}/{site}_station_timeseries_gao2017.csv", parse_dates=["date"])
    i = pd.read_csv(ins, parse_dates=["date"]).set_index("date"); i.loc[i.sm_vol <= 0, "sm_vol"] = np.nan
    t["ins"] = i.sm_vol.reindex(t.date).values; a = t.dropna(subset=["ins", "VV_dB"])
    b = a[a.date < "2025-07-01"]
    print(site, "all dates n", len(a), "R(VV,ins)", round(np.corrcoef(a.VV_dB, a.ins)[0, 1], 3), "| before 2025-07 n", len(b), round(np.corrcoef(b.VV_dB, b.ins)[0, 1], 3), "ins std", round(b.ins.std(), 3))
    if site == "GP":
        vv = t.set_index("date").VV_dB; print("GP VV 2025-06-18 -> 07-24:", vv.get(pd.Timestamp("2025-06-18")), vv.get(pd.Timestamp("2025-07-24")))
    if site == "HS": print("HS NDVI station cell range", round(t.NDVI.min(), 3), round(t.NDVI.max(), 3), "valid dates", int(t.valid.sum()), "/", len(t))
