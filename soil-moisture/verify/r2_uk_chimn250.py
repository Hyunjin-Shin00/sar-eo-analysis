"""Independent end-to-end CHIMN 250 m r2 from s1rtc npz + COSMOS csv (+WorldCover mask, remote COG)."""
import json, glob, sys, numpy as np, pandas as pd
B = "<WORK_ROOT>/case_UK_Maslanka2022"; site = "CHIMN"; cell = int(sys.argv[1]) if len(sys.argv) > 1 else 250
inc = json.load(open(f"{B}/data/incidence_angles.json"))[site]; z = np.load(f"{B}/data/s1rtc_{site}.npz")
dates = pd.to_datetime(pd.Series(z["dates"]).str[:10]); orb = z["orbit"]; th = np.array([inc[str(o)] for o in orb])
sig = 10*np.log10(z["vv"]*np.cos(np.radians(th))[:, None, None]); sig[(sig > -5) | (sig < -22)] = np.nan
H, W = sig.shape[1:]; x0, y1, res = float(z["x0"]), float(z["y1"]), float(z["res"])
try:
    import rasterio; from rasterio.vrt import WarpedVRT; from rasterio.transform import from_origin; from rasterio.enums import Resampling
    with rasterio.open("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N51W003_Map.tif") as s, \
         WarpedVRT(s, crs="EPSG:32630", transform=from_origin(x0, y1, res, res), width=W, height=H, resampling=Resampling.nearest) as v:
        wc = v.read(1)
    sig[:, np.isin(wc, [50, 80])] = np.nan; print("WorldCover mask applied, masked frac", np.isin(wc, [50, 80]).mean().round(4))
except Exception as e:
    print("WorldCover unavailable:", type(e).__name__)
key = (dates.dt.strftime("%Y-%m-%d") + "_" + orb.astype(str)); first = ~key.duplicated()
if (~first).any():
    sig = np.stack([np.nanmean(sig[(key == key[i]).values], 0) for i in np.where(first)[0]]); dates = dates[first].reset_index(drop=True); orb = orb[first.values]; th = th[first.values]
beta = (np.nanmean(sig[orb == 30], 0)-np.nanmean(sig[orb == 132], 0))/(inc["30"]-inc["132"])
lin = 10**((sig-beta*(th[:, None, None]-40))/10)
xs, ys = float(z["xs"]), float(z["ys"]); cx0 = np.floor(xs/cell)*cell; cy1 = np.ceil(ys/cell)*cell
c0 = int(round((cx0-x0)/res)); r0 = int(round((y1-cy1)/res)); n = int(cell//res); blk = lin[:, r0:r0+n, c0:c0+n]
s = 10*np.log10(np.nanmean(blk, (1, 2))); s[np.isfinite(blk).mean((1, 2)) < 0.5] = np.nan
p10, p90 = np.nanpercentile(s, [10, 90]); sd = p10-(p90-p10)/8; sw = p90+(p90-p10)/8; r = (s-sd)/(sw-sd)*100
r = np.where((r < 0) & (r >= -20), 0, r); r = np.where((r > 100) & (r <= 120), 100, r); r[(r < -20) | (r > 120)] = np.nan
f = glob.glob(f"{B}/data/{site}/*.csv")[0]; v = pd.read_csv(f, skiprows=8, header=None, names=["t", "vwc"]); v["date"] = pd.to_datetime(v.t.str[:10]); v.loc[v.vwc < 0, "vwc"] = np.nan
d = pd.DataFrame(dict(date=dates, rssm=r)).sort_values("date"); d = d[(d.date >= "2016-01-01") & (d.date <= "2019-12-31")]
d["vwc"] = v.set_index("date").vwc.reindex(d.date).values; d = d.dropna(); d["vi"] = (d.vwc-d.vwc.min())/(d.vwc.max()-d.vwc.min())*100
a = d.rssm.rolling(14, center=True).mean(); b = d.vi.rolling(14, center=True).mean(); k = a.notna() & b.notna()
print(site, cell, "n", len(d), "n_ma", int(k.sum()), "r2_ma", round(np.corrcoef(a[k], b[k])[0, 1]**2, 3), "RMSE", round(float(np.sqrt(np.mean((a[k]-b[k])**2))), 2), "r2_raw", round(np.corrcoef(d.rssm, d.vi)[0, 1]**2, 3))
