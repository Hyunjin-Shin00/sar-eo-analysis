"""Gao(2017) 방법 1·2 결과 검증(RDA 현장) + 그림. 논문 보고값과 같은 지표(RMSE, ubRMSE, bias, R)."""
import glob, json, os
import numpy as np, pandas as pd, rasterio
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from site_config import C, SITE
ROOT = "<WORK_ROOT>"; OUT = C["out"]; FIG = f"{OUT}/figures"; os.makedirs(FIG, exist_ok=True)
NAME = C["name"]
fp = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
fm.fontManager.addfont(fp); plt.rcParams["font.family"] = "Noto Sans CJK JP"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#898781",
                     "axes.labelcolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e",
                     "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6, "figure.facecolor": "#fcfcfb",
                     "axes.facecolor": "#fcfcfb", "font.size": 10, "axes.unicode_minus": False})
BLUE, ORANGE, AQUA, MUTED, INK = "#2a78d6", "#eb6834", "#1baf7a", "#898781", "#0b0b0b"
PAPER = {"방법1": dict(RMSE=0.087, ubRMSE=0.083, bias=0.026), "방법2": dict(RMSE=0.059, ubRMSE=0.053, bias=None)}

def met(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float); k = np.isfinite(y) & np.isfinite(p); y, p = y[k], p[k]
    if len(y) < 3: return dict(n=len(y))
    b = np.mean(p - y); rmse = np.sqrt(np.mean((p - y) ** 2))
    return dict(n=int(len(y)), R=round(float(np.corrcoef(y, p)[0, 1]), 3), RMSE=round(float(rmse), 3),
                ubRMSE=round(float(np.sqrt(max(rmse**2 - b**2, 0))), 3), bias=round(float(b), 3))

ts = pd.read_csv(f"{OUT}/{SITE}_station_timeseries_gao2017.csv", parse_dates=["date"])
prm = json.load(open(f"{OUT}/gao2017_fitted_params.json"))
ins = pd.read_csv(f"{C['data']}/{C['insitu']}", parse_dates=["date"])
ins.loc[ins.sm_vol <= 0, "sm_vol"] = np.nan
v = ts[ts.valid]
rows = {"방법1 (관측소 100 m 셀)": met(v.sm_vol, v.SM_method1),
        "방법1 (3×3 셀 평균)": met(v.sm_vol, v.SM_method1_3x3),
        "방법2 (관측소 100 m 셀)": met(v.sm_vol, v.SM_method2),
        "방법2 (전체 날짜, 마스크 구간 값 유지)": met(ts.sm_vol, ts.SM_method2)}
clim = ins[(ins.date < "2024-01-01")].sm_vol.mean()                  # 검증기간 이전(2019-2023) 평균
rows["기준선: 상수(2019-23 현장 평균, 무기술 예측)"] = {**met(v.sm_vol, np.full(len(v), clim)), "R": None}
M = pd.DataFrame(rows).T
for k in ("방법1", "방법2"):
    M.loc[f"논문 보고값 {k} (Urgell, 3·5 cm)"] = dict(n=None, R=None, **PAPER[k])
M.to_csv(f"{OUT}/validation_metrics.csv"); print(M.to_string())
seas = v.assign(season=v.date.dt.month.map(lambda m: "봄(3-5)" if m in (3, 4, 5) else "여름(6-8)" if m in (6, 7, 8) else "가을(9-11)" if m in (9, 10, 11) else "겨울(12-2)"))
S = pd.DataFrame({s: met(g.sm_vol, g.SM_method1) for s, g in seas.groupby("season")}).T
S.to_csv(f"{OUT}/validation_method1_by_season.csv"); print(S)

# 그림1 시계열 (강수는 별도 패널 — 이중축 사용 안 함)
fig, (ax, axr) = plt.subplots(2, 1, figsize=(12, 6.2), sharex=True, gridspec_kw=dict(height_ratios=[3, 1], hspace=0.06))
iv = ins[ins.date >= ts.date.min() - pd.Timedelta(days=5)]
ax.plot(iv.date, iv.sm_vol, color=MUTED, lw=1.4, label=f"현장 {NAME} (일평균, 10 cm)")
ax.plot(ts.date, ts.SM_method2, "-", color=AQUA, lw=1.5, alpha=0.9, label="방법2 (연속차분 누적)")
ax.plot(v.date, v.SM_method2, "o", color=AQUA, ms=5, mec="#fcfcfb", mew=1)
ax.plot(v.date, v.SM_method1, "o-", color=BLUE, lw=2, ms=6, mec="#fcfcfb", mew=1.5, label="방법1 (건조기준 대비)")
inv = ts[~ts.valid]
ax.plot(inv.date, np.full(len(inv), 0.03), "|", color=MUTED, ms=8, label="NDVI>0.8 등 마스크된 날짜")
ax.set_ylabel("토양수분 (m³/m³)"); ax.set_ylim(0, 0.5)
ax.legend(loc="upper left", ncol=2, frameon=False, fontsize=9)
ax.set_title(f"{NAME} 관측소: Sentinel-1/2 변화탐지(Gao et al. 2017) vs 현장 토양수분", loc="left", fontsize=12, color=INK)
axr.bar(iv.date, iv.rain_mm, color=BLUE, width=1); axr.set_ylabel("일강수 (mm)")
fig.savefig(f"{FIG}/fig1_timeseries.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# 그림2 산점도
fig, axs = plt.subplots(1, 2, figsize=(10, 4.8))
for axx, col, ttl, c in zip(axs, ["SM_method1", "SM_method2"], ["방법1", "방법2"], [BLUE, AQUA]):
    m = met(v.sm_vol, v[col])
    axx.scatter(v.sm_vol, v[col], s=36, color=c, edgecolor="#fcfcfb", lw=1)
    axx.plot([0, 0.5], [0, 0.5], color=MUTED, lw=1); axx.set_xlim(0, 0.5); axx.set_ylim(0, 0.5); axx.set_aspect("equal")
    p = PAPER[ttl]
    axx.text(0.02, 0.48, f"{SITE}: n={m['n']}  R={m['R']:.2f}\nRMSE={m['RMSE']:.3f}  ubRMSE={m['ubRMSE']:.3f}  bias={m['bias']:+.3f}\n"
             f"논문(Urgell): RMSE={p['RMSE']:.3f}  ubRMSE={p['ubRMSE']:.3f}", fontsize=8.5, va="top", color=INK)
    axx.set_title(f"{ttl}", loc="left"); axx.set_xlabel("현장 토양수분 (m³/m³)"); axx.set_ylabel("Sentinel 추정 (m³/m³)")
fig.savefig(f"{FIG}/fig2_scatter.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# 그림3 포락선 f(NDVI), g(NDVI) (논문 Fig.4/Fig.7 대응)
fig, axs = plt.subplots(1, 2, figsize=(10, 4))
for axx, key, ttl, yl in zip(axs, ["f", "g"], ["f(NDVI): 건조기준 대비 Δσ 최대(99백분위)", "g(NDVI): 연속날짜 |δσ| 최대(99백분위)"], ["Δσ_max (dB)", "|δσ|_max (dB)"]):
    e = prm[key]; x = np.array(e["ndvi"]); y = np.array(e["env"])
    sl = e["a"] if key == "f" else e["b"]
    axx.plot(x, y, "o", color=BLUE, ms=6, mec="#fcfcfb")
    xx = np.linspace(0.1, 0.8, 10); axx.plot(xx, sl * xx + e["dsig_max_bare"], color=ORANGE, lw=2)
    axx.text(0.12, min(y) + 0.1, f"{sl:+.2f}·NDVI {e['dsig_max_bare']:+.2f}", color=INK)
    axx.set_title(ttl, loc="left", fontsize=10); axx.set_xlabel("NDVI"); axx.set_ylabel(yl)
fig.savefig(f"{FIG}/fig3_envelopes.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# 그림4 지도 (방법1, 계절 대표 8장)
z = np.load(f"{OUT}/gao2017_stack_100m.npz", allow_pickle=True)
dates = pd.to_datetime(z["dates"]); MV1 = z["MV1"]; vf = np.isfinite(MV1).mean((1, 2))
x0, y1, res = float(z["x0"]), float(z["y1"]), float(z["res"]); H, W = MV1.shape[1:]
ext = (x0 / 1e3, (x0 + W * res) / 1e3, (y1 - H * res) / 1e3, y1 / 1e3)
from pyproj import Transformer
sx, sy = Transformer.from_crs(4326, int(z["epsg"]), always_xy=True).transform(C["lon"], C["lat"])
cand = [i for i in range(len(dates)) if vf[i] > 0.05]
want = pd.to_datetime(["2024-04-15", "2024-07-15", "2024-10-15", "2025-03-15", "2025-05-15", "2025-08-15", "2025-10-15", "2026-04-15"])
pick = sorted({min(cand, key=lambda i: abs((dates[i] - w).days)) for w in want})[:8]
fig, axs = plt.subplots(2, 4, figsize=(15, 7.6), constrained_layout=True)
insd = ins.set_index("date").sm_vol
for axx, i in zip(axs.flat, pick):
    im = axx.imshow(MV1[i], cmap="Blues", vmin=0.05, vmax=0.32, extent=ext, interpolation="nearest")
    axx.plot(sx / 1e3, sy / 1e3, "^", color=ORANGE, ms=9, mec=INK, mew=0.8)
    axx.set_title(f"{dates[i]:%Y-%m-%d}  현장 {insd.get(dates[i], np.nan):.2f}", loc="left", fontsize=10)
    axx.tick_params(labelsize=7); axx.grid(False); axx.set_facecolor("#e6e5e0")
for axx in axs.flat[len(pick):]: axx.axis("off")
fig.colorbar(im, ax=axs, shrink=0.7, label="토양수분 (m³/m³)")
fig.suptitle(f"{NAME} 일대 100 m 표층 토양수분 — Gao et al.(2017) 방법1 (회색=NDVI>0.8 산림·수면 등 논문 기준 마스크, ▲=RDA 관측소, 좌표 UTM52N km)",
             x=0.01, ha="left", fontsize=11)
fig.savefig(f"{FIG}/fig4_maps_method1.png", dpi=150, bbox_inches="tight"); plt.close(fig)
json.dump(dict(metrics=M.reset_index().astype(str).to_dict("records"), season=S.reset_index().astype(str).to_dict("records")),
          open(f"{OUT}/validation_summary.json", "w"), ensure_ascii=False, indent=1)
