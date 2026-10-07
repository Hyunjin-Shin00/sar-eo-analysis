"""SMAP L3E (surviving test-run extract, 8 days) vs RDA in-situ from Cho 2026 Zenodo table."""
import numpy as np, pandas as pd, sys
S = sys.argv[1]
d = pd.read_excel("<WORK_ROOT>/ref_Cho2026_PINN/data/zenodo/Zenodo_PINN-WCM/data/Data_s1_rescale_QC_results_VF.xlsx", "Data_total")
d["date"] = pd.to_datetime(d.date).dt.normalize()
s = pd.read_csv(f"{S}/smap_daily_9sites.csv", parse_dates=["date"])
print("smap rows", len(s), "dates", s.date.nunique(), "sites", s.site.nunique(), "l3 valid", s.l3.notna().sum())
for res in (10, 30, 50):
    a = d[d.resolution == res][["site", "date", "SM_insitu", "PINN_WCM"]].merge(s[["site", "date", "l3"]], on=["site", "date"]).dropna(subset=["l3", "SM_insitu"])
    if len(a) < 3: print(res, "n", len(a)); continue
    e = a.l3-a.SM_insitu; ep = a.PINN_WCM-a.SM_insitu
    print(res, "m: n", len(a), "SMAP R", round(np.corrcoef(a.l3, a.SM_insitu)[0, 1], 3), "ubRMSE", round(np.sqrt(((e-e.mean())**2).mean()), 3), "bias", round(e.mean(), 3),
          "| same-sample PINN R", round(np.corrcoef(a.PINN_WCM, a.SM_insitu)[0, 1], 3), "ubRMSE", round(np.sqrt(((ep-ep.mean())**2).mean()), 3))
q = pd.read_csv(f"{S}/direct_l3e_s1dates.csv"); q = q[q.sm > -9000]
print("direct L3E valid rows", len(q), "retrieval_qual_flag bit0 set:", int((q.q.astype(int) & 1).sum()), "/", len(q))
