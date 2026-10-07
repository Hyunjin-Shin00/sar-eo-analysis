"""Portfolio figure: Ma 2020 SCAN reproduction (retrieved vs in-situ), from case_US_Ma2020/outputs/retrievals.csv."""
import sys, numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
src, out = sys.argv[1], sys.argv[2]
d = pd.read_csv(src).dropna(subset=["SM_insitu"]); y, p = d.SM_insitu.values, d.SM_retrieved.values
r2 = np.corrcoef(y, p)[0, 1]**2; rmse = np.sqrt(np.mean((p-y)**2))
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#898781", "axes.labelcolor": "#52514e",
                     "xtick.color": "#52514e", "ytick.color": "#52514e", "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6,
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "font.size": 11})
fig, ax = plt.subplots(figsize=(6.4, 5.6), constrained_layout=True)
ax.plot([0.1, 0.47], [0.1, 0.47], color="#898781", lw=1, ls="--", label="1:1")
ax.scatter(y, p, s=64, color="#2a78d6", edgecolor="#fcfcfb", linewidth=2, zorder=3, label="Sentinel-1 retrieval (Oh-2004 + WCM)")
ax.set_xlim(0.1, 0.47); ax.set_ylim(0.1, 0.47); ax.set_aspect("equal")
ax.set_xlabel("SCAN in-situ soil moisture (m³/m³)"); ax.set_ylabel("Retrieved soil moisture (m³/m³)")
ax.set_title(f"SCAN 2001 (Nebraska), n = {len(y)}\nReproduced R² = {r2:.2f}, RMSE = {rmse:.3f}\nPaper (Ma 2020) R² = 0.597, RMSE = 0.069", loc="left", fontsize=11, color="#0b0b0b")
ax.legend(frameon=False, loc="upper left", fontsize=9)
fig.savefig(out, dpi=150)
