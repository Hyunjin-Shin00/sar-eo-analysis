"""
Ma, Li & McCabe (2020) Remote Sens. 12:2303 재현 — SCAN 2001 Rogers Farm #1 (Nebraska), Fig. 9
  보고값: N=14, R²=0.597, bias=−0.04, MAE=0.058, RMSE=0.069, ubRMSE=0.051 (m³/m³)

방법 (논문 Eq.1–6, SCA-VV, VWC = NDWI(B8A,B11) 식, WCM 'all land uses' 파라미터)
  Oh-2004:  q = 0.095(0.13+sin1.5θ)^1.4 (1−e^{−1.3(ks)^0.9}),  σVH = 0.11 SM^0.7 cos^2.2θ (1−e^{−0.32(ks)^1.8}),  σVV,soil = σVH/q
  WCM:      σ = A·mV·cosθ(1−τ²)(1−e^{−α}) + τ²σsoil,  τ² = exp(−2B·mV/cosθ)
            A=0.0012, B=0.091, α=2.12 (Bindlish & Barros 2001 'all land uses')
  VWC:      mV = 0.2091·exp(4.7637·NDWI),  NDWI=(B8A−B11)/(B8A+B11)
  비용:     J = (σVV,obs − σVV,sim)²,  SM∈[0.15,0.45], RMSH s∈[0.25,0.85] cm,  k = 2π/5.547 cm
  위성자료: S1A 상승(상대궤도 136) 2017-10~2018-07, 관측소 10 m 픽셀 1개 / S2 L2A ±3일, 구름 없는 픽셀

재현 시 차이(명기):
  - σ0: Planetary Computer sentinel-1-rtc γ0(지형평탄화)를 σ0 ≈ γ0·cosθ 로 환산 (평지, θ=GRD 주석 입사각)
  - SCE-UA 대신 격자탐색. 한 방정식·두 미지수라 해가 곡선이므로 'J 최소 곡선 위 SM 평균'으로 고정
"""
import io, re, json, numpy as np, pandas as pd, rasterio, pystac_client, planetary_computer as pc, requests
from rasterio.warp import transform as wtransform
from concurrent.futures import ThreadPoolExecutor

ROOT = "<WORK_ROOT>/case_US_Ma2020"
LON, LAT = -96.46625, 40.84617
A, B, ALPHA = 0.0012, 0.091, 2.12
K = 2 * np.pi / 5.547
PAPER = dict(N=14, R2=0.597, bias=-0.04, MAE=0.058, RMSE=0.069, ubRMSE=0.051)

def px(href, lon=LON, lat=LAT):
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES"):
        with rasterio.open(href) as s:
            x, y = wtransform("EPSG:4326", s.crs, [lon], [lat]); r, c = s.index(x[0], y[0])
            return float(s.read(1, window=((r, r + 1), (c, c + 1)))[0, 0])

# ---------- S1 ----------
cpc = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
pt = {"type": "Point", "coordinates": [LON, LAT]}
s1 = [i for i in cpc.search(collections=["sentinel-1-rtc"], intersects=pt, datetime="2017-10-01/2018-07-31").items()
      if i.properties.get("sat:orbit_state") == "ascending" and i.properties.get("sat:relative_orbit") == 136 and i.id.startswith("S1A")]
print("S1 RTC items", len(s1))
# 입사각: GRD 주석 geolocationGrid
g = next(i for i in cpc.search(collections=["sentinel-1-grd"], intersects=pt, datetime="2018-05-01/2018-05-31").items()
         if i.properties.get("sat:relative_orbit") == 136)
xml = requests.get(g.assets["schema-product-vv"].href, timeout=60).text
pts = re.findall(r"<latitude>([-+\d.eE]+)</latitude>\s*<longitude>([-+\d.eE]+)</longitude>.*?<incidenceAngle>([-+\d.eE]+)</incidenceAngle>", xml, re.S)
P = np.array(pts, float); d = (P[:, 0] - LAT) ** 2 + (P[:, 1] - LON) ** 2; nn = np.argsort(d)[:4]
THETA = float(np.average(P[nn, 2], weights=1 / (d[nn] + 1e-12))); print("incidence angle at site", round(THETA, 2))
def s1row(it):
    g0 = px(it.assets["vv"].href)
    return dict(dt_utc=pd.Timestamp(it.properties["datetime"]).tz_convert(None), gamma0_vv=g0)
with ThreadPoolExecutor(12) as ex: S1 = pd.DataFrame(list(ex.map(s1row, s1))).sort_values("dt_utc")
S1["sigma0_vv"] = S1.gamma0_vv * np.cos(np.radians(THETA))

# ---------- S2 ----------
ces = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
s2 = list(ces.search(collections=["sentinel-2-l2a"], intersects=pt, datetime="2017-09-25/2018-08-05").items())
def s2row(it):
    try:
        scl = px(it.assets["scl"].href)
        if scl not in (4, 5): return None                      # 식생·나지만(구름·그림자·물 제외)
        b8a, b11 = px(it.assets["nir08"].href), px(it.assets["swir16"].href)
        off = 1000 if it.properties.get("earthsearch:boa_offset_applied") is False and pd.Timestamp(it.properties["datetime"]) >= pd.Timestamp("2022-01-25", tz="UTC") else 0
        b8a, b11 = b8a - off, b11 - off
        return dict(date=pd.Timestamp(it.properties["datetime"]).tz_convert(None).normalize(), NDWI=(b8a - b11) / (b8a + b11))
    except Exception as e:
        return None
with ThreadPoolExecutor(12) as ex: S2 = pd.DataFrame([r for r in ex.map(s2row, s2) if r]).groupby("date").NDWI.mean().reset_index()
print("S2 clear dates", len(S2))

# ---------- 현장 SCAN 5 cm (현지표준시 CST; S1 00:2x UTC = 전날 18:2x CST) ----------
url = ("https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customSingleStationReport/hourly/"
       "2001:NE:SCAN%7Cid=%22%22%7Cname/2017-09-25,2018-08-05/SMS:-2:value,PRCP:-1:value")
txt = requests.get(url, timeout=120).text; open(f"{ROOT}/data/scan2001_hourly.csv", "w").write(txt)
sc = pd.read_csv(io.StringIO("\n".join(l for l in txt.splitlines() if not l.startswith("#"))), parse_dates=["Date"])
sc.columns = ["t_cst", "sm_pct", "prcp_in"]; sc["t_utc"] = sc.t_cst + pd.Timedelta(hours=6); sc = sc.dropna(subset=["sm_pct"]).set_index("t_utc")

# ---------- 매칭 + 역산 ----------
SMg = np.arange(0.15, 0.4501, 0.001); Sg = np.arange(0.25, 0.8501, 0.005)
SMm, Sm = np.meshgrid(SMg, Sg, indexing="ij")
th = np.radians(THETA); ks = K * Sm
q = 0.095 * (0.13 + np.sin(1.5 * th)) ** 1.4 * (1 - np.exp(-1.3 * ks ** 0.9))
svh = 0.11 * SMm ** 0.7 * np.cos(th) ** 2.2 * (1 - np.exp(-0.32 * ks ** 1.8))
svv_soil = svh / q
rows = []
for _, r in S1.iterrows():
    dd = (S2.date - r.dt_utc.normalize()).dt.days.abs()
    if dd.min() > 3: continue
    ndwi = S2.NDWI[dd.idxmin()]; mv = 0.2091 * np.exp(4.7637 * ndwi)
    tau2 = np.exp(-2 * B * mv / np.cos(th))
    sim = A * mv * np.cos(th) * (1 - tau2) * (1 - np.exp(-ALPHA)) + tau2 * svv_soil
    J = (r.sigma0_vv - sim) ** 2
    best_sm_per_s = SMg[np.argmin(J, 0)]                       # 각 거칠기별 최적 SM
    jmin_per_s = J.min(0); on_curve = jmin_per_s <= max(J.min() * 10, 1e-8)
    sm_ret = float(best_sm_per_s[on_curve].mean())
    k = sc.index.get_indexer([r.dt_utc], method="nearest")[0]
    rows.append(dict(dt_utc=r.dt_utc, sigma0_vv_dB=10 * np.log10(r.sigma0_vv), NDWI=ndwi, VWC=mv, s2_dt_days=int(dd.min()),
                     SM_retrieved=sm_ret, SM_global_min=float(SMm.flat[np.argmin(J)]), SM_insitu=sc.sm_pct.iloc[k] / 100,
                     insitu_time_utc=sc.index[k]))
R = pd.DataFrame(rows); R.to_csv(f"{ROOT}/outputs/retrievals.csv", index=False)
def met(y, p):
    b = np.mean(p - y); rmse = np.sqrt(np.mean((p - y) ** 2))
    return dict(N=len(y), R2=round(np.corrcoef(y, p)[0, 1] ** 2, 3), bias=round(b, 3), MAE=round(np.mean(np.abs(p - y)), 3),
                RMSE=round(rmse, 3), ubRMSE=round(np.sqrt(max(rmse**2 - b**2, 0)), 3))
M = pd.DataFrame({"논문 Ma 2020 Fig.9": PAPER, "재현 (곡선 평균 해)": met(R.SM_insitu.values, R.SM_retrieved.values),
                  "재현 (전역 최소 해)": met(R.SM_insitu.values, R.SM_global_min.values)}).T
M.to_csv(f"{ROOT}/outputs/metrics_vs_paper.csv"); print(M.to_string()); print(R.round(3).to_string())
json.dump(dict(theta=THETA, A=A, B=B, alpha=ALPHA, n_s1=len(S1), n_s2=len(S2)), open(f"{ROOT}/outputs/run_info.json", "w"), indent=1)
