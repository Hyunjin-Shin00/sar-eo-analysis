"""영문 발표용 그림 (TelePIX 템플릿 색상)"""
import json, numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": "#E9E9E9", "figure.facecolor": "white", "axes.facecolor": "white", "axes.edgecolor": "#94A3B8",
                     "axes.labelcolor": "#334155", "xtick.color": "#334155", "ytick.color": "#334155", "font.size": 12})
R = "<WORK_ROOT>"; F = f"{R}/presentation/figs_en"
RED, SLATE, GRAY, TEAL, OCHRE = "#E7344C", "#334155", "#94A3B8", "#01665e", "#bf812d"
# A. 4-year time series
t = pd.read_csv(f"{R}/case_UK_Maslanka2022/outputs/timeseries_CHIMN_250m.csv", parse_dates=["date"]).dropna(subset=["rssm_ma", "vwc_i_ma"])
fig, ax = plt.subplots(figsize=(12, 4.2))
ax.plot(t.date, t.vwc_i_ma, color=GRAY, lw=2.4, label="In-situ soil moisture index (COSMOS-UK)")
ax.plot(t.date, t.rssm_ma, color=RED, lw=2.4, label="Sentinel-1 relative soil moisture (250 m)")
ax.set_ylim(0, 100); ax.set_ylabel("Relative soil moisture (%)"); ax.legend(loc="upper center", ncol=2, frameon=False)
fig.savefig(f"{F}/A_timeseries.png", dpi=200, bbox_inches="tight"); plt.close(fig)
# E. winter vs summer
W_ = json.load(open(f"{R}/satchat/UK_winter_stats.json")); S_ = json.load(open(f"{R}/satchat/UK_summer_stats.json"))
fig, axs = plt.subplots(1, 2, figsize=(12, 4.4))
for ax, vals, ttl, ylab, ylim, fmt in [(axs[0], [W_["mean"], S_["mean"]], "Satellite: mean relative soil moisture", "Relative soil moisture (%)", 105, "{:.0f}%"),
                                       (axs[1], [40.1, 18.5], "In-situ: volumetric soil moisture (COSMOS-UK)", "Volumetric soil moisture (%)", 52, "{:.1f}%")]:
    ax.bar([0, 1], vals, 0.55, color=[TEAL, OCHRE])
    for xi, v in zip([0, 1], vals): ax.text(xi, v + ylim * 0.02, fmt.format(v), ha="center", fontsize=14, color=SLATE)
    ax.set_xticks([0, 1], [f"Winter\n{W_['date']}", f"Summer drought\n{S_['date']}"]); ax.set_ylim(0, ylim); ax.set_ylabel(ylab)
    ax.set_title(ttl, loc="left", fontsize=13, color=SLATE); ax.grid(axis="x", visible=False)
fig.tight_layout(); fig.savefig(f"{F}/E_winter_summer.png", dpi=200, bbox_inches="tight"); plt.close(fig)
# ---- 한국어판 ----
from matplotlib import font_manager as fm
fm.fontManager.addfont("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"); plt.rcParams["font.family"] = "Noto Sans CJK JP"; plt.rcParams["axes.unicode_minus"] = False
fig, ax = plt.subplots(figsize=(12, 4.2))
ax.plot(t.date, t.vwc_i_ma, color=GRAY, lw=2.4, label="현장 토양수분 지수 (COSMOS-UK)")
ax.plot(t.date, t.rssm_ma, color=RED, lw=2.4, label="Sentinel-1 상대 토양수분 (250 m)")
ax.set_ylim(0, 100); ax.set_ylabel("상대 토양수분 (%)"); ax.legend(loc="upper center", ncol=2, frameon=False)
fig.savefig(f"{F}/A_timeseries_ko.png", dpi=200, bbox_inches="tight"); plt.close(fig)
fig, axs = plt.subplots(1, 2, figsize=(12, 4.4))
for ax, vals, ttl, ylab, ylim, fmt in [(axs[0], [W_["mean"], S_["mean"]], "위성 평균 상대 토양수분", "상대 토양수분 (%)", 105, "{:.0f}%"),
                                       (axs[1], [40.1, 18.5], "현장 관측 체적 토양수분 (COSMOS-UK)", "체적 토양수분 (%)", 52, "{:.1f}%")]:
    ax.bar([0, 1], vals, 0.55, color=[TEAL, OCHRE])
    for xi, v in zip([0, 1], vals): ax.text(xi, v + ylim * 0.02, fmt.format(v), ha="center", fontsize=14, color=SLATE)
    ax.set_xticks([0, 1], [f"겨울\n{W_['date']}", f"여름 가뭄\n{S_['date']}"]); ax.set_ylim(0, ylim); ax.set_ylabel(ylab)
    ax.set_title(ttl, loc="left", fontsize=13, color=SLATE); ax.grid(axis="x", visible=False)
fig.tight_layout(); fig.savefig(f"{F}/E_winter_summer_ko.png", dpi=200, bbox_inches="tight"); plt.close(fig)
print("ok")
