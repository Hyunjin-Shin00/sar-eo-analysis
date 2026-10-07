"""Maslanka et al. (2022) TU Wien 변화탐지 재현 (Ann-Dir β) + COSMOS-UK 검증, Table IV 비교.
  σ0(dB) = 10·log10(γ0_RTC · cosθ_orbit)               (평지 근사, 논문은 SNAP σ0)
  마스크: σ0 > −5 dB 또는 < −22 dB (영상별), WorldCover 50(시가지)·80(수면) 제외
  Eq.2  σ0(40°,t) = σ0(θ,t) − β(θ − 40°),  β(Ann-Dir) = 화소별 σ0(dB)–θ 회귀 기울기(두 궤도)
  집계  10 m 정규화 σ0 → 100/250/500/1000 m 셀 산술평균(선형) → dB
  Eq.1  rSSM = (σ0 − σd)/(σw − σd)·100,  σd = P10 − (P90−P10)/8,  σw = P90 + (P90−P10)/8
        −20<rSSM<0 → 0, 100<rSSM<120 → 100, 그 밖 NaN
  검증  지점 포함 셀, 2016-2019, VWC_I = min-max(COSMOS VWC, S1 날짜만)·100,
        양쪽 14-orbit 이동평균 후 r², RMSE(%)  — 논문 Table IV 와 비교
"""
import glob, json, numpy as np, pandas as pd, rasterio
from rasterio.vrt import WarpedVRT
from rasterio.transform import from_origin
from rasterio.enums import Resampling

B = "<WORK_ROOT>/case_UK_Maslanka2022"
SITES = {"CHIMN": "Chimney Meadows", "SHEEP": "Sheepdrove", "WADDN": "Waddesdon"}
INC = json.load(open(f"{B}/data/incidence_angles.json"))
PAPER = {  # Table IV, RMSE(%) / r²  — Ann-Dir, Mon-Reg(본문 대표값)
    ("CHIMN", 1000): (12.1, 0.29, 11.9, 0.27), ("CHIMN", 500): (12.0, 0.21, 11.5, 0.15), ("CHIMN", 250): (8.2, 0.41, 8.3, 0.36), ("CHIMN", 100): (6.6, 0.58, 7.0, 0.53),
    ("SHEEP", 1000): (10.7, 0.64, 10.8, 0.59), ("SHEEP", 500): (9.2, 0.62, 9.0, 0.58), ("SHEEP", 250): (9.0, 0.51, 8.7, 0.47), ("SHEEP", 100): (9.7, 0.40, 9.5, 0.35),
    ("WADDN", 1000): (17.4, 0.53, 17.6, 0.53), ("WADDN", 500): (16.6, 0.51, 16.9, 0.51), ("WADDN", 250): (14.9, 0.48, 14.9, 0.47), ("WADDN", 100): (12.4, 0.42, 12.4, 0.41)}
WC = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N51W003_Map.tif"

def vwc(site):
    f = glob.glob(f"{B}/data/{site}/*.csv")[0]
    d = pd.read_csv(f, skiprows=8, header=None, names=["t", "vwc"])
    d["date"] = pd.to_datetime(d.t.str[:10]); d.loc[d.vwc < 0, "vwc"] = np.nan
    return d.set_index("date").vwc

def met(a, b):
    k = np.isfinite(a) & np.isfinite(b); a, b = a[k], b[k]
    return dict(n=int(k.sum()), r2=float(np.corrcoef(a, b)[0, 1] ** 2), RMSE=float(np.sqrt(np.mean((a - b) ** 2))), r=float(np.corrcoef(a, b)[0, 1]))

rows, series = [], {}
for site in SITES:
    z = np.load(f"{B}/data/s1rtc_{site}.npz")
    dates = pd.to_datetime(pd.Series(z["dates"]).str[:10]); orb = z["orbit"]; g0 = z["vv"]
    th = np.array([INC[site][str(o)] for o in orb])
    sig = 10 * np.log10(g0 * np.cos(np.deg2rad(th))[:, None, None])
    sig[(sig > -5) | (sig < -22)] = np.nan
    H, W = sig.shape[1:]; x0, y1, res = float(z["x0"]), float(z["y1"]), float(z["res"])
    with rasterio.open(WC) as src, WarpedVRT(src, crs="EPSG:32630", transform=from_origin(x0, y1, res, res), width=W, height=H,
                                             resampling=Resampling.nearest) as v:
        wc = v.read(1)
    sig[:, np.isin(wc, [50, 80])] = np.nan
    # 같은 날짜 중복(인접 프레임) 제거: 날짜·궤도별 nanmean
    key = pd.Series(dates.dt.strftime("%Y-%m-%d") + "_" + orb.astype(str))
    uk = key.drop_duplicates().index.values
    if len(uk) < len(key):
        sig = np.stack([np.nanmean(sig[(key == key[i]).values], 0) for i in uk]); dates = dates[uk].reset_index(drop=True); orb = orb[uk]; th = th[uk]
    # β Ann-Dir: 화소별 회귀 (두 궤도 → 궤도 평균 차 / 입사각 차 와 동등)
    m30 = np.nanmean(sig[orb == 30], 0); m132 = np.nanmean(sig[orb == 132], 0)
    beta = (m30 - m132) / (INC[site]["30"] - INC[site]["132"])
    sn = sig - beta[None] * (th[:, None, None] - 40.0)
    lin = 10 ** (sn / 10)
    xs, ys = float(z["xs"]), float(z["ys"])
    vw = vwc(site)
    for cell in (100, 250, 500, 1000):
        cx0 = np.floor(xs / cell) * cell; cy1 = np.ceil(ys / cell) * cell     # 셀 경계 = cell 배수 정렬
        c0 = int(round((cx0 - x0) / res)); r0 = int(round((y1 - cy1) / res)); n = int(cell // res)
        blk = lin[:, r0:r0 + n, c0:c0 + n]
        valid_frac = np.isfinite(blk).mean((1, 2))
        s = 10 * np.log10(np.nanmean(blk, (1, 2))); s[valid_frac < 0.5] = np.nan
        p10, p90 = np.nanpercentile(s, [10, 90]); sd = p10 - (p90 - p10) / 8; sw = p90 + (p90 - p10) / 8
        r = (s - sd) / (sw - sd) * 100
        r = np.where((r < 0) & (r >= -20), 0, r); r = np.where((r > 100) & (r <= 120), 100, r); r[(r < -20) | (r > 120)] = np.nan
        df = pd.DataFrame(dict(date=dates, orbit=orb, rssm=r)).sort_values("date")
        df = df[(df.date >= "2016-01-01") & (df.date <= "2019-12-31")]
        df["vwc"] = vw.reindex(df.date).values
        k = df.vwc.notna()
        df["vwc_i"] = (df.vwc - df.vwc[k].min()) / (df.vwc[k].max() - df.vwc[k].min()) * 100
        df = df.dropna(subset=["rssm", "vwc_i"]).reset_index(drop=True)
        df["rssm_ma"] = df.rssm.rolling(14, center=True).mean(); df["vwc_i_ma"] = df.vwc_i.rolling(14, center=True).mean()
        ms = met(df.rssm_ma.values, df.vwc_i_ma.values); mr = met(df.rssm.values, df.vwc_i.values)
        p = PAPER[(site, cell)]
        rows.append(dict(site=site, res_m=cell, n=ms["n"], ours_r2=round(ms["r2"], 2), paper_r2_AnnDir=p[1],
                         ours_RMSE=round(ms["RMSE"], 1), paper_RMSE_AnnDir=p[0], paper_r2_MonReg=p[3], paper_RMSE_MonReg=p[2],
                         ours_raw_r2=round(mr["r2"], 2), ours_raw_RMSE=round(mr["RMSE"], 1), beta_median=round(float(np.nanmedian(beta)), 3)))
        series[(site, cell)] = df
        df.to_csv(f"{B}/outputs/timeseries_{site}_{cell}m.csv", index=False)
    print(site, "n_dates", len(dates), "β median", np.nanmedian(beta).round(3), flush=True)

M = pd.DataFrame(rows); M.to_csv(f"{B}/outputs/metrics_vs_paper.csv", index=False); print(M.to_string())

# ---------------- 그림 ----------------
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
fm.fontManager.addfont("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"); plt.rcParams["font.family"] = "Noto Sans CJK JP"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#898781", "axes.labelcolor": "#52514e",
                     "xtick.color": "#52514e", "ytick.color": "#52514e", "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6,
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "font.size": 10, "axes.unicode_minus": False})
BLUE, ORANGE, MUTED, INK = "#2a78d6", "#eb6834", "#898781", "#0b0b0b"
fig, axs = plt.subplots(3, 1, figsize=(12, 9), sharex=True, constrained_layout=True)
for ax, site in zip(axs, SITES):
    df = series[(site, 100)]; m = M[(M.site == site) & (M.res_m == 100)].iloc[0]
    ax.plot(df.date, df.vwc_i_ma, color=MUTED, lw=2, label="COSMOS-UK 현장 (VWC 지수, 14회 이동평균)")
    ax.plot(df.date, df.rssm_ma, color=BLUE, lw=2, label="Sentinel-1 rSSM (100 m, 14회 이동평균)")
    ax.set_ylim(0, 100); ax.set_ylabel("상대 토양수분 (%)")
    ax.set_title(f"{SITES[site]} ({site})   재현 r²={m.ours_r2:.2f}, RMSE={m.ours_RMSE:.1f}%   |   논문 r²={m.paper_r2_AnnDir:.2f}, RMSE={m.paper_RMSE_AnnDir:.1f}%",
                 loc="left", fontsize=11, color=INK)
axs[0].legend(loc="lower left", frameon=False, fontsize=9, ncol=2)
fig.savefig(f"{B}/outputs/figures/fig1_timeseries_100m.png", dpi=160); plt.close(fig)

fig, axs = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
lab = [f"{s}\n{c} m" for s, c in zip(M.site, M.res_m)]; x = np.arange(len(M)); w = 0.38
for ax, (o, p, yl) in zip(axs, [("ours_r2", "paper_r2_AnnDir", "r²"), ("ours_RMSE", "paper_RMSE_AnnDir", "RMSE (%)")]):
    ax.bar(x - w / 2, M[p], w, color=MUTED, label="논문 Table IV (Ann-Dir)")
    ax.bar(x + w / 2, M[o], w, color=BLUE, label="본 재현")
    ax.set_xticks(x); ax.set_xticklabels(lab, fontsize=7.5); ax.set_ylabel(yl); ax.grid(axis="x", visible=False)
axs[0].legend(frameon=False, fontsize=9); axs[0].set_title("결정계수 r² (높을수록 좋음)", loc="left"); axs[1].set_title("RMSE (낮을수록 좋음)", loc="left")
fig.savefig(f"{B}/outputs/figures/fig2_ours_vs_paper.png", dpi=160); plt.close(fig)
