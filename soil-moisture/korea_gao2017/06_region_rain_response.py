"""지역 평균 위성 토양수분(Gao 방법1) vs 선행강수지수(API, k=0.8) — 관측소 한 점이 아닌 지도 전체의 강수 반응 검증."""
import numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
fm.fontManager.addfont("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"); plt.rcParams["font.family"] = "Noto Sans CJK JP"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#e6e5e0",
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.edgecolor": "#898781", "axes.unicode_minus": False})
R = "<WORK_ROOT>"; OUT = f"{R}/outputs/korea_region"
rows = []
fig, axs = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True)
for ax, (site, name, ins) in zip(axs, [("GP", "가평", f"{R}/data/insitu_rda/GP_daily_2017_2026.csv"), ("HS", "화성", f"{R}/data/HS/insitu_rda/HS_daily.csv")]):
    t = pd.read_csv(f"{R}/outputs/{site}/{site}_station_timeseries_gao2017.csv", parse_dates=["date"])
    i = pd.read_csv(ins, parse_dates=["date"]).set_index("date"); i.loc[i.sm_vol <= 0, "sm_vol"] = np.nan
    api = (i.rain_mm.fillna(0).ewm(alpha=0.2).mean() * 5)            # API_k=0.8 (mm)
    t["api"] = api.reindex(t.date).values; t["insitu"] = i.sm_vol.reindex(t.date).values
    v = t.dropna(subset=["map_mean_method1"])
    r_api = np.corrcoef(v.map_mean_method1, v.api)[0, 1]; k = v.insitu.notna(); r_ins = np.corrcoef(v.map_mean_method1[k], v.insitu[k])[0, 1]
    rows.append(dict(site=site, n=len(v), R_vs_API=round(r_api, 2), R_vs_insitu_station=round(r_ins, 2)))
    z = lambda s: (s - s.mean()) / s.std()
    ax.plot(v.date, z(v.api), color="#898781", lw=1.5, label="선행강수지수 API (표준화)")
    ax.plot(v.date, z(v.map_mean_method1), "o-", color="#2a78d6", lw=2, ms=4, label="위성 토양수분 지역 평균 (표준화)")
    ax.set_title(f"{name}: 지역 평균 위성 토양수분 vs 선행강수  R = {r_api:.2f} (n={len(v)})", loc="left", fontsize=12)
    ax.legend(loc="upper left", frameon=False, fontsize=9); ax.set_ylabel("표준화 값")
fig.savefig(f"{OUT}/fig_region_mean_vs_API.png", dpi=160, bbox_inches="tight")
pd.DataFrame(rows).to_csv(f"{OUT}/region_mean_correlations.csv", index=False); print(pd.DataFrame(rows))
