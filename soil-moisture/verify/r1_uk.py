"""Independent recompute of UK (Maslanka 2022 reproduction) numbers from original npz/csv outputs."""
import json, glob, numpy as np, pandas as pd
B = "<WORK_ROOT>/case_UK_Maslanka2022"
# (a) metrics from saved timeseries CSVs
M = pd.read_csv(f"{B}/outputs/metrics_vs_paper.csv")
rows = []
for _, m in M.iterrows():
    d = pd.read_csv(f"{B}/outputs/timeseries_{m.site}_{m.res_m}m.csv")
    k = d.rssm_ma.notna() & d.vwc_i_ma.notna()
    r = np.corrcoef(d.rssm_ma[k], d.vwc_i_ma[k])[0, 1]; rm = np.sqrt(np.mean((d.rssm_ma[k] - d.vwc_i_ma[k]) ** 2))
    rr = np.corrcoef(d.rssm, d.vwc_i)[0, 1]
    rows.append(dict(site=m.site, res=m.res_m, n=int(k.sum()), r2=round(r*r, 3), file_r2=m.ours_r2, rmse=round(rm, 2), file_rmse=m.ours_RMSE, raw_r2=round(rr*rr, 3), file_raw=m.ours_raw_r2, paper_r2=m.paper_r2_AnnDir))
R = pd.DataFrame(rows); print(R.to_string())
print("mean r2 recomputed", R.r2.mean().round(3), "paper", R.paper_r2.mean().round(3), "within0.10:", int((abs(R.r2-R.paper_r2)<=0.10).sum()))
# (b) independent 100 m map rSSM for winter/summer dates (no WorldCover mask, as in map script)
inc = json.load(open(f"{B}/data/incidence_angles.json"))["CHIMN"]
z = np.load(f"{B}/data/s1rtc_CHIMN.npz"); dates = pd.to_datetime(pd.Series(z["dates"]).str[:10]); orb = z["orbit"]
print("n scenes", len(dates), "orbit counts", dict(zip(*np.unique(orb, return_counts=True))), "shape", z["vv"].shape)
th = np.array([inc[str(o)] for o in orb])
sig = 10*np.log10(z["vv"]*np.cos(np.radians(th))[:, None, None]); sig[(sig > -5) | (sig < -22)] = np.nan
beta = (np.nanmean(sig[orb == 30], 0) - np.nanmean(sig[orb == 132], 0)) / (inc["30"] - inc["132"])
print("beta median", round(float(np.nanmedian(beta)), 3))
lin = 10**((sig - beta*(th[:, None, None]-40))/10)
T, Hh, Ww = lin.shape; s = 10*np.log10(np.nanmean(lin[:, :Hh//10*10, :Ww//10*10].reshape(T, Hh//10, 10, Ww//10, 10), (2, 4)))
p10, p90 = np.nanpercentile(s, [10, 90], 0); sd = p10-(p90-p10)/8; sw = p90+(p90-p10)/8
rs = (s-sd)/(sw-sd)*100; rs = np.where((rs < 0) & (rs >= -20), 0, rs); rs = np.where((rs > 100) & (rs <= 120), 100, rs); rs[(rs < -20) | (rs > 120)] = np.nan
def day(ds):
    i = [j for j, d in enumerate(dates) if str(d.date()) == ds]
    return i[0]
w, su = day("2017-12-26"), day("2018-07-18")
for nm, k in (("winter", w), ("summer", su)):
    a = rs[k]; print(nm, dates[k].date(), "orbit", orb[k], "mean", round(float(np.nanmean(a)), 2), "dry<=20(all cells)", round(float(np.mean(a <= 20)), 3), "wet>=80", round(float(np.mean(a >= 80)), 3), "valid", round(float(np.isfinite(a).mean()), 3))
d = rs[su]-rs[w]; N = d.size
print("cells", N, "decrease frac(all)", round(float(np.mean(d < 0)), 3), "valid-only", round(float(np.nanmean(d[np.isfinite(d)] < 0)), 3),
      ">30pp decrease(all)", round(float(np.mean(d < -30)), 3), "valid-only", round(float(np.mean(d[np.isfinite(d)] < -30)), 3), "mean change", round(float(np.nanmean(d)), 2))
h = d.shape[0]//2
for q, a in (("NW", d[:h, :h]), ("NE", d[:h, h:]), ("SW", d[h:, :h]), ("SE", d[h:, h:])): print(q, round(float(np.nanmean(a)), 1))
yrs = np.array([2016 <= x.year <= 2019 for x in dates]); print("4yr mean", round(float(np.nanmean(rs[yrs])), 2))
# COSMOS VWC on the two days
f = glob.glob(f"{B}/data/CHIMN/*.csv")[0]; v = pd.read_csv(f, skiprows=8, header=None, names=["t", "vwc"]); v["date"] = pd.to_datetime(v.t.str[:10]); v.loc[v.vwc < 0, "vwc"] = np.nan; v = v.set_index("date").vwc
print("COSMOS VWC 2017-12-26", v.get(pd.Timestamp("2017-12-26")), "2018-07-18", v.get(pd.Timestamp("2018-07-18")), "4yr min/max", v.min(), v.max())
