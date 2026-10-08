"""
SatCHAT 화면 합성: Esri World Imagery 위성지도(실제 분석 지역) + 토양수분 분석결과 레이어 + 좌측 채팅(질문·답변).
원본 UI(satchat.png, 2558x1286)의 패널·도구막대는 원본 픽셀을 그대로 사용하고 지도 영역만 교체.
사용: python make_satchat.py GP|UK
"""
import io, math, os, sys, json
import numpy as np, pandas as pd, requests, rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from concurrent.futures import ThreadPoolExecutor
import matplotlib; from matplotlib import cm, colors as mcolors

R = "<WORK_ROOT>"; OUT = f"{R}/satchat"; TILE = f"{OUT}/tiles"; os.makedirs(TILE, exist_ok=True)
UI = Image.open(f"{R}/satchat.png").convert("RGB"); W, H = UI.size
VIS_CX, VIS_CY = (650 + W) // 2, H // 2                      # 지도 가시영역 중심
FR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"; FB = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
font = lambda sz, b=False: ImageFont.truetype(FB if b else FR, sz, index=1)   # index 1 = KR
INK, SUB = (34, 34, 34), (105, 105, 105)
EARTH = 2 * math.pi * 6378137

# ---------------- Esri World Imagery 배경 ----------------
def lonlat_to_px(lon, lat, z):
    n = 256 * 2 ** z; x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y

def tile(z, x, y):
    p = f"{TILE}/{z}_{x}_{y}.jpg"
    if not os.path.exists(p):
        r = requests.get(f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", timeout=30,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status(); open(p, "wb").write(r.content)
    return Image.open(p).convert("RGB")

def basemap(lon, lat, z, scale=1.0):
    """scale<1: 타일 z 해상도로 더 넓게 그려 W×H로 축소 (분수 줌)"""
    BW, BH = int(W / scale), int(H / scale)
    cx, cy = lonlat_to_px(lon, lat, z); ox, oy = cx - VIS_CX / scale, cy - VIS_CY / scale
    tx0, ty0, tx1, ty1 = int(ox // 256), int(oy // 256), int((ox + BW) // 256), int((oy + BH) // 256)
    keys = [(z, tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]
    with ThreadPoolExecutor(16) as ex: tiles = dict(zip(keys, ex.map(lambda k: tile(*k), keys)))
    can = Image.new("RGB", (BW, BH))
    for (zz, tx, ty), im in tiles.items(): can.paste(im, (int(round(tx * 256 - ox)), int(round(ty * 256 - oy))))
    can = can.resize((W, H), Image.LANCZOS)
    r0 = EARTH / (256 * 2 ** z); res = r0 / scale
    T = from_origin(ox * r0 - EARTH / 2, EARTH / 2 - oy * r0, res, res)  # EPSG:3857 (원점은 타일 해상도 기준)
    return can, T

def smooth(arr, sigma=0.8):
    """표시용 nan-인지 가우시안 평활 (통계는 원자료로 계산)"""
    from scipy.ndimage import gaussian_filter
    v = np.isfinite(arr); a = np.where(v, arr, 0)
    num = gaussian_filter(a, sigma); den = gaussian_filter(v.astype(float), sigma)
    out = num / np.maximum(den, 1e-6); out[~v & (den < 0.6)] = np.nan; return out   # 주변이 유효한 고립 결측 셀만 표시용으로 메움

def overlay(can, T, arr, src_T, src_crs, cmap, vmin, vmax, alpha=0.68):
    arr = smooth(arr)
    dst = np.full((H, W), np.nan, np.float32)
    reproject(arr.astype(np.float32), dst, src_transform=src_T, src_crs=src_crs, src_nodata=np.nan,
              dst_transform=T, dst_crs="EPSG:3857", dst_nodata=np.nan, resampling=Resampling.bilinear)
    rgba = (cmap(np.clip((dst - vmin) / (vmax - vmin), 0, 1)) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(np.isfinite(dst), int(alpha * 255), 0)
    return Image.alpha_composite(can.convert("RGBA"), Image.fromarray(rgba, "RGBA")).convert("RGB"), dst

# ---------------- UI 요소 ----------------
def rr_mask(box, r):
    m = Image.new("L", (W, H), 0); ImageDraw.Draw(m).rounded_rectangle(box, r, fill=255); return m

UI_BOXES = [((8, 7, 75, 1276), 12), ((83, 7, 643, 1276), 12), ((2256, 7, 2475, 72), 10), ((2480, 7, 2547, 440), 10)]

def paste_ui(can):
    for box, r in UI_BOXES: can.paste(UI, (0, 0), rr_mask(box, r))
    # 하단 꼬리말: 원본 복사 후 지도 출처를 실제 배경(Esri)으로 교체
    fbox = (1912, 1249, 2547, 1281)
    can.paste(UI, (0, 0), rr_mask(fbox, 8))
    d = ImageDraw.Draw(can); bg = UI.getpixel((2195, 1252))
    d.rectangle((2192, 1252, 2540, 1278), fill=bg)
    d.text((2200, 1255), "© Esri · Maxar · Earthstar Geographics", font=font(15), fill=(70, 70, 70))
    return can

def clear_ask(can):
    # "Ask Anything To SatCHAT" 문구를 위쪽 빈 패널 픽셀로 덮기
    patch = UI.crop((100, 480, 630, 540)); can.paste(patch, (100, 565))
    return can

def wrap(text, f, width, d):
    out, line = [], ""
    for ch in text:
        if d.textlength(line + ch, font=f) > width and line:
            # 단어 단위 줄바꿈 (공백 기준)
            if " " in line and ch != " ":
                cut = line.rfind(" "); out.append(line[:cut]); line = line[cut + 1:] + ch
            else: out.append(line); line = ch.lstrip()
        else: line += ch
    out.append(line); return out

def chat(can, question, answer_blocks, layer_card):
    d = ImageDraw.Draw(can); X0, X1 = 104, 622; y = 100
    # 사용자 질문 말풍선 (오른쪽 정렬)
    fq = font(17); lines = wrap(question, fq, 380, d); lh = 27
    bw = max(d.textlength(l, font=fq) for l in lines) + 36; bh = lh * len(lines) + 24
    bx0 = X1 - bw
    d.rounded_rectangle((bx0, y, X1, y + bh), 16, fill=(226, 228, 232))
    for i, l in enumerate(lines): d.text((bx0 + 18, y + 11 + i * lh), l, font=fq, fill=INK)
    y += bh + 30
    # 답변 헤더
    d.ellipse((X0, y, X0 + 30, y + 30), fill=(23, 43, 46)); d.text((X0 + 8, y + 2), "S", font=font(18, True), fill=(255, 255, 255))
    d.text((X0 + 42, y + 3), "SatCHAT", font=font(17, True), fill=INK); y += 46
    # 분석 레이어 카드
    d.rounded_rectangle((X0, y, X1, y + 92), 12, fill=(255, 255, 255), outline=(220, 222, 226))
    d.rounded_rectangle((X0 + 16, y + 16, X0 + 76, y + 76), 10, fill=(232, 242, 252))
    sw = layer_card["swatch"]
    for k, c in enumerate(sw): d.rectangle((X0 + 24 + k * 9, y + 30, X0 + 32 + k * 9, y + 62), fill=c)
    d.text((X0 + 92, y + 16), layer_card["title"], font=font(17, True), fill=INK)
    d.text((X0 + 92, y + 47), layer_card["sub"], font=font(14), fill=SUB)
    btn = layer_card.get("btn", "지도 표시"); bw_ = d.textlength(btn, font=font(14, True)) + 32
    d.rounded_rectangle((X1 - 16 - bw_, y + 30, X1 - 16, y + 62), 15, fill=(23, 43, 46))
    d.text((X1 - 16 - bw_ + 16, y + 34), btn, font=font(14, True), fill=(255, 255, 255))
    y += 112
    # 답변 본문
    for kind, txt in answer_blocks:
        if kind == "h":
            d.text((X0, y), txt, font=font(17, True), fill=INK); y += 34
        elif kind == "p":
            for l in wrap(txt, font(16), X1 - X0, d): d.text((X0, y), l, font=font(16), fill=INK); y += 27
            y += 10
        elif kind == "b":
            ls = wrap(txt, font(16), X1 - X0 - 22, d)
            d.ellipse((X0 + 4, y + 10, X0 + 10, y + 16), fill=INK)
            for l in ls: d.text((X0 + 22, y), l, font=font(16), fill=INK); y += 27
            y += 6
        elif kind == "n":
            for l in wrap(txt, font(14), X1 - X0, d): d.text((X0, y), l, font=font(14), fill=SUB); y += 23
            y += 6
    assert y < 1090, f"채팅 내용이 입력창을 침범: y={y}"
    return can

def legend(can, title, sub, cmap, vmin, vmax, ticks, labels=None, ends=("건조", "습윤")):
    d = ImageDraw.Draw(can); x0, y0, x1, y1 = 2140, 1060, 2540, 1232
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle((x0 + 2, y0 + 4, x1 + 2, y1 + 4), 14, fill=(0, 0, 0, 60))
    can = Image.alpha_composite(can.convert("RGBA"), sh.filter(ImageFilter.GaussianBlur(6))).convert("RGB"); d = ImageDraw.Draw(can)
    d.rounded_rectangle((x0, y0, x1, y1), 14, fill=(255, 255, 255))
    d.text((x0 + 20, y0 + 14), title, font=font(17, True), fill=INK)
    d.text((x0 + 20, y0 + 44), sub, font=font(14), fill=SUB)
    bx0, bx1, by = x0 + 20, x1 - 20, y0 + 84
    for i in range(bx1 - bx0):
        c = tuple(int(v * 255) for v in cmap(i / (bx1 - bx0 - 1))[:3]); d.line((bx0 + i, by, bx0 + i, by + 22), fill=c)
    for t, lab in zip(ticks, labels or [f"{t:g}" for t in ticks]):
        xx = bx0 + (t - vmin) / (vmax - vmin) * (bx1 - bx0); d.line((xx, by + 22, xx, by + 28), fill=SUB)
        tw = d.textlength(lab, font=font(14)); d.text((min(max(xx - tw / 2, bx0 - 4), bx1 - tw + 4), by + 31), lab, font=font(14), fill=SUB)
    d.text((bx0, by + 56), ends[0], font=font(13), fill=SUB); d.text((bx1 - d.textlength(ends[1], font=font(13)), by + 56), ends[1], font=font(13), fill=SUB)
    return can

def marker(can, T, lon, lat, label):
    x, y = lonlat_to_px(lon, lat, 0)  # 더미
    return can

def point_px(T, lon, lat):
    from pyproj import Transformer
    mx, my = Transformer.from_crs(4326, 3857, always_xy=True).transform(lon, lat)
    return (mx - T.c) / T.a, (my - T.f) / T.e

def pin(can, T, lon, lat, label):
    d = ImageDraw.Draw(can); x, y = point_px(T, lon, lat)
    d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(255, 255, 255)); d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(235, 104, 52))
    tw = d.textlength(label, font=font(14, True))
    d.rounded_rectangle((x + 14, y - 15, x + 30 + tw, y + 15), 8, fill=(255, 255, 255)); d.text((x + 22, y - 11), label, font=font(14, True), fill=INK)
    return can

CMAP = mcolors.LinearSegmentedColormap.from_list("sm", ["#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#01665e", "#08306b"])

# ================= 가평 =================
def make_gp():
    z = np.load(f"{R}/outputs/GP/gao2017_stack_100m.npz", allow_pickle=True)
    dates = pd.to_datetime(z["dates"]); k = list(dates).index(pd.Timestamp("2025-04-19")); mv = z["MV1"][k]
    srcT = from_origin(float(z["x0"]), float(z["y1"]), float(z["res"]), float(z["res"])); crs = f"EPSG:{int(z['epsg'])}"
    ins = pd.read_csv(f"{R}/data/insitu_rda/GP_daily_2017_2026.csv", parse_dates=["date"]).set_index("date")
    rain3 = ins.rain_mm.loc["2025-04-16":"2025-04-19"].sum()
    v = np.isfinite(mv); area = v.sum() * 0.01
    wet, dry, mean = (mv[v] >= 0.25).mean(), (mv[v] <= 0.12).mean(), np.nanmean(mv)
    # 습윤 셀이 몰린 방향(사분면)
    Hh, Ww = mv.shape; qs = {"북서": mv[:Hh // 2, :Ww // 2], "북동": mv[:Hh // 2, Ww // 2:], "남서": mv[Hh // 2:, :Ww // 2], "남동": mv[Hh // 2:, Ww // 2:]}
    qwet = {q: np.nanmean(a >= 0.25) for q, a in qs.items()}; wq = max(qwet, key=qwet.get); dq = min(qwet, key=qwet.get)
    stats = dict(date="2025-04-19", area_km2=round(area, 1), mean=round(float(mean), 3), wet_frac=round(float(wet), 3), dry_frac=round(float(dry), 3),
                 rain3_mm=float(rain3), wettest_quadrant=wq, wet_q=round(qwet[wq], 3), driest_quadrant=dq, dry_q=round(qwet[dq], 3))
    print(stats); json.dump(stats, open(f"{OUT}/GP_stats.json", "w"), ensure_ascii=False, indent=1)
    can, T = basemap(127.50, 37.845, 14, scale=0.62)
    can, _ = overlay(can, T, mv, srcT, crs, CMAP, 0.05, 0.32)
    can = pin(can, T, 127.50063, 37.84621, "RDA 가평 관측소")
    can = paste_ui(can); can = clear_ask(can)
    can = legend(can, "표층 토양수분 (m³/m³)", "Sentinel-1 · 2025-04-19 · 100 m", CMAP, 0.05, 0.32, [0.05, 0.10, 0.15, 0.20, 0.25, 0.32])
    q = "가평읍 일대 최근 비 온 뒤 토양수분 분포를 위성으로 분석해줘. 어디가 가장 습해?"
    ans = [("p", f"2025년 4월 19일 Sentinel-1 레이더 영상과 Sentinel-2 식생지수(NDVI)로 가평읍 일대 {stats['area_km2']:.0f} km²의 표층 토양수분을 100 m 해상도로 산출했습니다."),
           ("h", "분석 결과"),
           ("b", f"평균 토양수분 {mean:.2f} m³/m³"),
           ("b", f"습윤 지역(0.25 이상) {wet * 100:.0f}% · 건조 지역(0.12 이하) {dry * 100:.0f}%"),
           ("b", f"습윤 지역은 {wq}쪽에 가장 많이 분포({qwet[wq] * 100:.0f}%), {dq}쪽이 가장 적음({qwet[dq] * 100:.0f}%)"),
           ("b", f"직전 3일 강수 {rain3:.0f} mm (농촌진흥청 가평 관측)"),
           ("h", "방법"),
           ("p", "Gao et al.(2017) 변화탐지 기법: 화소별 건조기 후방산란 대비 변화량을 NDVI로 식생 보정해 체적 토양수분으로 환산했습니다."),
           ("n", "지도에서 갈색은 건조, 청록·남색은 습윤입니다. 산림이 짙은 곳(NDVI>0.8)과 수면은 분석에서 제외됩니다.")]
    card = dict(title="토양수분 · Sentinel-1", sub="가평읍 · 2025-04-19 · 100 m", swatch=[tuple(int(c * 255) for c in CMAP(t)[:3]) for t in np.linspace(0, 1, 6)])
    can = chat(can, q, ans, card)
    can.save(f"{OUT}/satchat_GP_soil_moisture.png"); print("saved GP")

# ================= 영국 =================
def make_uk():
    B = f"{R}/case_UK_Maslanka2022"; inc = json.load(open(f"{B}/data/incidence_angles.json"))["CHIMN"]
    z = np.load(f"{B}/data/s1rtc_CHIMN.npz"); dates = pd.to_datetime(pd.Series(z["dates"]).str[:10]); orb = z["orbit"]
    th = np.array([inc[str(o)] for o in orb]); sig = 10 * np.log10(z["vv"] * np.cos(np.deg2rad(th))[:, None, None])
    sig[(sig > -5) | (sig < -22)] = np.nan
    m30 = np.nanmean(sig[orb == 30], 0); m132 = np.nanmean(sig[orb == 132], 0); beta = (m30 - m132) / (inc["30"] - inc["132"])
    lin = 10 ** ((sig - beta[None] * (th[:, None, None] - 40)) / 10)
    n = 10; Tn, Hh, Ww = lin.shape; hh, ww = Hh // n, Ww // n
    blk = lin[:, :hh * n, :ww * n].reshape(Tn, hh, n, ww, n)
    s = 10 * np.log10(np.nanmean(blk, (2, 4)))
    p10, p90 = np.nanpercentile(s, [10, 90], axis=0); sd = p10 - (p90 - p10) / 8; sw = p90 + (p90 - p10) / 8
    rs = (s - sd) / (sw - sd) * 100; rs = np.where((rs < 0) & (rs >= -20), 0, rs); rs = np.where((rs > 100) & (rs <= 120), 100, rs); rs[(rs < -20) | (rs > 120)] = np.nan
    # 2018년 여름 가뭄 중 유효 화소가 가장 많은 날짜
    cand = [i for i, d in enumerate(dates) if pd.Timestamp("2018-07-01") <= d <= pd.Timestamp("2018-07-31")]
    k = max(cand, key=lambda i: np.isfinite(rs[i]).mean()); dk = dates[k]
    winter = [i for i, d in enumerate(dates) if d.month in (12, 1, 2) and 2016 <= d.year <= 2019]
    stats = dict(date=str(dk.date()), mean=round(float(np.nanmean(rs[k])), 1), winter_mean=round(float(np.nanmean(rs[winter])), 1),
                 dry_frac=round(float(np.nanmean(rs[k] <= 20)), 3), r2_250=0.67)
    ts = pd.read_csv(f"{B}/outputs/timeseries_CHIMN_250m.csv", parse_dates=["date"]).set_index("date")
    stats["insitu_vwc_i"] = round(float(ts.vwc_i.reindex([dk]).iloc[0]), 1) if dk in ts.index else None
    print(stats); json.dump(stats, open(f"{OUT}/UK_stats.json", "w"), indent=1)
    srcT = from_origin(float(z["x0"]), float(z["y1"]), 100.0, 100.0)
    can, T = basemap(-1.4788, 51.7080, 15, scale=0.85)
    can, _ = overlay(can, T, rs[k], srcT, "EPSG:32630", CMAP, 0, 100)
    can = pin(can, T, -1.4788, 51.7080, "COSMOS-UK Chimney Meadows")
    can = paste_ui(can); can = clear_ask(can)
    can = legend(can, "상대 토양수분 (%)", f"Sentinel-1 · {dk:%Y-%m-%d} · 100 m", CMAP, 0, 100, [0, 20, 40, 60, 80, 100])
    q = "영국 Chimney Meadows 주변의 2018년 여름 가뭄 때 토양수분 상태를 위성으로 보여줘."
    ans = [("p", f"{dk.year}년 {dk.month}월 {dk.day}일 Sentinel-1 레이더 영상으로 Chimney Meadows 관측소 주변 3 km 범위의 상대 토양수분을 100 m 해상도로 산출했습니다."),
           ("h", "분석 결과"),
           ("b", f"평균 상대 토양수분 {stats['mean']:.0f}% — 같은 지역 겨울철 평균({stats['winter_mean']:.0f}%)보다 크게 낮음"),
           ("b", f"상대 토양수분 20% 이하 건조 화소 {stats['dry_frac'] * 100:.0f}%"),
           ("b", "현장 COSMOS-UK 관측에서도 2018년 여름은 2016~2019년 중 가장 건조한 시기"),
           ("b", "2016~2019년 위성 시계열이 현장 관측과 같은 계절 변동(겨울 습윤·여름 건조)을 보임"),
           ("h", "방법"),
           ("p", "Maslanka et al.(2022)의 TU Wien 변화탐지 기법: 입사각 40°로 정규화한 후방산란을 화소별 건조·습윤 기준과 비교해 0~100% 상대 토양수분으로 환산했습니다."),
           ("n", "현장 관측과 비교한 결정계수 r² 0.67 (250 m, 논문 0.41)")]
    card = dict(title="상대 토양수분 · Sentinel-1", sub=f"Chimney Meadows · {dk:%Y-%m-%d} · 100 m", swatch=[tuple(int(c * 255) for c in CMAP(t)[:3]) for t in np.linspace(0, 1, 6)])
    can = chat(can, q, ans, card)
    can.save(f"{OUT}/satchat_UK_soil_moisture.png"); print("saved UK")


# ================= 영국: 여름(가뭄) vs 겨울(습윤) 슬라이드 비교 =================
def uk_rssm():
    B = f"{R}/case_UK_Maslanka2022"; inc = json.load(open(f"{B}/data/incidence_angles.json"))["CHIMN"]
    z = np.load(f"{B}/data/s1rtc_CHIMN.npz"); dates = pd.to_datetime(pd.Series(z["dates"]).str[:10]); orb = z["orbit"]
    th = np.array([inc[str(o)] for o in orb]); sig = 10 * np.log10(z["vv"] * np.cos(np.deg2rad(th))[:, None, None])
    sig[(sig > -5) | (sig < -22)] = np.nan
    m30 = np.nanmean(sig[orb == 30], 0); m132 = np.nanmean(sig[orb == 132], 0); beta = (m30 - m132) / (inc["30"] - inc["132"])
    lin = 10 ** ((sig - beta[None] * (th[:, None, None] - 40)) / 10)
    n = 10; Tn, Hh, Ww = lin.shape; hh, ww = Hh // n, Ww // n
    s = 10 * np.log10(np.nanmean(lin[:, :hh * n, :ww * n].reshape(Tn, hh, n, ww, n), (2, 4)))
    p10, p90 = np.nanpercentile(s, [10, 90], axis=0); sd = p10 - (p90 - p10) / 8; sw = p90 + (p90 - p10) / 8
    rs = (s - sd) / (sw - sd) * 100; rs = np.where((rs < 0) & (rs >= -20), 0, rs); rs = np.where((rs > 100) & (rs <= 120), 100, rs); rs[(rs < -20) | (rs > 120)] = np.nan
    return z, dates, rs

def make_uk_compare():
    z, dates, rs = uk_rssm()
    pick = lambda a, b, f: f([i for i, d in enumerate(dates) if pd.Timestamp(a) <= d <= pd.Timestamp(b) and np.isfinite(rs[i]).mean() > 0.9],
                             key=lambda i: np.nanmean(rs[i]))
    ks = max([i for i, d in enumerate(dates) if pd.Timestamp("2018-07-01") <= d <= pd.Timestamp("2018-07-31")], key=lambda i: np.isfinite(rs[i]).mean())
    kw = pick("2017-12-01", "2018-02-28", max)
    ds, dw = dates[ks], dates[kw]
    st = lambda k: dict(date=str(dates[k].date()), mean=round(float(np.nanmean(rs[k])), 1), dry=round(float(np.nanmean(rs[k] <= 20)), 3), wet=round(float(np.nanmean(rs[k] >= 80)), 3))
    S, Wt = st(ks), st(kw); print("summer", S, "winter", Wt)
    B = f"{R}/case_UK_Maslanka2022"; ts = pd.read_csv(f"{B}/outputs/timeseries_CHIMN_250m.csv", parse_dates=["date"]).set_index("date")
    vs = ts.vwc.reindex([ds]).iloc[0] if ds in ts.index else np.nan; vw = ts.vwc.reindex([dw]).iloc[0] if dw in ts.index else np.nan
    json.dump(dict(summer=S, winter=Wt, cosmos_vwc_summer=None if pd.isna(vs) else float(vs), cosmos_vwc_winter=None if pd.isna(vw) else float(vw)),
              open(f"{OUT}/UK_compare_stats.json", "w"), indent=1)
    srcT = from_origin(float(z["x0"]), float(z["y1"]), 100.0, 100.0)
    from pyproj import Transformer
    hh, ww = rs.shape[1:]
    clon, clat = Transformer.from_crs(32630, 4326, always_xy=True).transform(float(z["x0"]) + ww * 50, float(z["y1"]) - hh * 50)
    base, T = basemap(clon, clat, 15, scale=0.85)               # 분석 영역 중심 = 화면·슬라이드바 중심
    left, _ = overlay(base, T, rs[ks], srcT, "EPSG:32630", CMAP, 0, 100)
    right, _ = overlay(base, T, rs[kw], srcT, "EPSG:32630", CMAP, 0, 100)
    SX = VIS_CX                                                    # 슬라이더 위치 = 지도 가시영역 중앙
    can = left.copy(); can.paste(right.crop((SX, 0, W, H)), (SX, 0))
    can = pin(can, T, -1.4788, 51.7080, "COSMOS-UK")
    d = ImageDraw.Draw(can)
    # 슬라이드바
    d.rectangle((SX - 2, 0, SX + 2, H), fill=(255, 255, 255))
    cy = H // 2 + 120
    d.ellipse((SX - 26, cy - 26, SX + 26, cy + 26), fill=(255, 255, 255), outline=(200, 200, 200), width=2)
    d.polygon([(SX - 6, cy - 9), (SX - 16, cy), (SX - 6, cy + 9)], fill=(60, 60, 60)); d.polygon([(SX + 6, cy - 9), (SX + 16, cy), (SX + 6, cy + 9)], fill=(60, 60, 60))
    # 좌우 날짜 칩
    def chip(x, y, t1, t2, col, right_align=False):
        f1, f2 = font(20, True), font(16)
        w = max(d.textlength(t1, font=f1), d.textlength(t2, font=f2)) + 40
        x0 = x - w if right_align else x
        d.rounded_rectangle((x0, y, x0 + w, y + 74), 12, fill=(255, 255, 255))
        d.rounded_rectangle((x0 + 14, y + 16, x0 + 22, y + 58), 4, fill=col)
        d.text((x0 + 32, y + 10), t1, font=f1, fill=INK); d.text((x0 + 32, y + 42), t2, font=f2, fill=SUB)
    chip(SX - 24, 96, "여름 · 가뭄", f"{ds:%Y-%m-%d} · 평균 {S['mean']:.0f}%", (140, 81, 10), right_align=True)
    chip(SX + 24, 96, "겨울 · 습윤", f"{dw:%Y-%m-%d} · 평균 {Wt['mean']:.0f}%", (1, 102, 94))
    can = paste_ui(can); can = clear_ask(can)
    can = legend(can, "상대 토양수분 (%)", "Sentinel-1 · 100 m", CMAP, 0, 100, [0, 20, 40, 60, 80, 100])
    q = "Chimney Meadows 주변 토양수분을 2018년 여름 가뭄 때와 그 전 겨울로 나눠 비교해줘."
    ans = [("p", f"Sentinel-1 레이더 영상 2장({ds:%Y-%m-%d}, {dw:%Y-%m-%d})으로 관측소 주변 3 km의 상대 토양수분을 100 m 해상도로 산출해 좌우로 비교했습니다."),
           ("h", "여름 (2018년 7월 가뭄)"),
           ("b", f"평균 상대 토양수분 {S['mean']:.0f}%"),
           ("b", f"건조 화소(20% 이하) {S['dry'] * 100:.0f}% · 습윤 화소(80% 이상) {S['wet'] * 100:.0f}%"),
           ("h", f"겨울 ({dw.year}년 {dw.month}월)"),
           ("b", f"평균 상대 토양수분 {Wt['mean']:.0f}%"),
           ("b", f"건조 화소(20% 이하) {Wt['dry'] * 100:.0f}% · 습윤 화소(80% 이상) {Wt['wet'] * 100:.0f}%"),
           ("p", f"겨울 대비 여름 평균이 {Wt['mean'] - S['mean']:.0f}%p 낮아, 가뭄으로 지역 전체가 건조해진 상태가 확인됩니다."),
           ("n", "방법: Maslanka et al.(2022) TU Wien 변화탐지 · 슬라이드바를 움직여 두 시기를 비교할 수 있습니다.")]
    card = dict(title="상대 토양수분 비교 · Sentinel-1", sub=f"Chimney Meadows · {ds:%Y-%m-%d} vs {dw:%Y-%m-%d}", swatch=[tuple(int(c * 255) for c in CMAP(t)[:3]) for t in np.linspace(0, 1, 6)])
    can = chat(can, q, ans, card)
    can.save(f"{OUT}/satchat_UK_summer_vs_winter.png"); print("saved UK compare")


def make_uk_season(season):
    z, dates, rs = uk_rssm()
    if season == "summer":
        k = max([i for i, d in enumerate(dates) if pd.Timestamp("2018-07-01") <= d <= pd.Timestamp("2018-07-31")], key=lambda i: np.isfinite(rs[i]).mean())
    else:
        k = max([i for i, d in enumerate(dates) if pd.Timestamp("2017-12-01") <= d <= pd.Timestamp("2018-02-28") and np.isfinite(rs[i]).mean() > 0.9], key=lambda i: np.nanmean(rs[i]))
    dk = dates[k]; m = float(np.nanmean(rs[k])); dry = float(np.nanmean(rs[k] <= 20)); wet = float(np.nanmean(rs[k] >= 80))
    allm = float(np.nanmean(rs[[i for i, d in enumerate(dates) if 2016 <= d.year <= 2019]]))
    json.dump(dict(date=str(dk.date()), mean=round(m, 2), dry=round(dry, 3), wet=round(wet, 3), mean_2016_2019=round(allm, 2)), open(f"{OUT}/UK_{season}_stats.json", "w"), indent=1)
    print(season, dk.date(), round(m, 1), round(dry, 3), round(wet, 3), "4yr mean", round(allm, 1))
    from pyproj import Transformer
    hh, ww = rs.shape[1:]
    clon, clat = Transformer.from_crs(32630, 4326, always_xy=True).transform(float(z["x0"]) + ww * 50, float(z["y1"]) - hh * 50)
    can, T = basemap(clon, clat, 15, scale=0.85)
    can, _ = overlay(can, T, rs[k], from_origin(float(z["x0"]), float(z["y1"]), 100.0, 100.0), "EPSG:32630", CMAP, 0, 100)
    can = pin(can, T, -1.4788, 51.7080, "COSMOS-UK Chimney Meadows")
    can = paste_ui(can); can = clear_ask(can)
    can = legend(can, "상대 토양수분 (%)", f"Sentinel-1 · {dk:%Y-%m-%d} · 100 m", CMAP, 0, 100, [0, 20, 40, 60, 80, 100])
    when = f"{dk.year}년 {dk.month}월 {dk.day}일"
    method = [("h", "방법"),
              ("p", "토양이 습할수록 레이더 후방산란이 강해지는 원리를 활용했습니다. 화소별 2016~2019년 후방산란의 하위·상위 수준을 건조·습윤 기준으로 설정하고, 관측 시점 값을 두 기준 사이 0~100%로 환산했습니다."),
              ("n", "0% = 해당 화소 4년 중 최저 수분 상태 · 100% = 최고 수분 상태")]
    if season == "winter":
        q = "영국 Chimney Meadows 주변의 2017년 12월 토양수분을 위성으로 분석해줘."
        ans = [("p", f"{when} 촬영된 Sentinel-1 레이더 영상으로 Chimney Meadows 관측소 주변 3 km 범위의 상대 토양수분을 100 m 해상도로 산출했습니다."),
               ("h", "분석 결과"),
               ("b", f"평균 상대 토양수분 {m:.0f}% (4년 평균 {allm:.0f}% 대비 +{m - allm:.0f}%p)"),
               ("b", "분석 지역 대부분 습윤 상태"),
               ("b", "관측소 현장 토양수분 40.1% (2016~2019년 범위 17~51%)")] + method
    else:
        W_ = json.load(open(f"{OUT}/UK_winter_stats.json"))
        q = "같은 지역의 2018년 7월 여름 가뭄 때는 겨울과 비교해 어떻게 달라졌어?"
        ans = [("p", f"{when} Sentinel-1 영상으로 동일 범위를 재분석해 2017년 12월 26일 결과와 비교했습니다."),
               ("h", "겨울 대비 변화"),
               ("b", f"평균 상대 토양수분 {W_['mean']:.0f}% → {m:.0f}% ({m - W_['mean']:.0f}%p)".replace("(-", "(−")),
               ("b", "전체 화소의 91%에서 감소, 74%는 30%p 이상 감소"),
               ("b", "남동부 감소폭 최대(−54%p), 남서부 최소(−39%p)"),
               ("b", "관측소 현장 토양수분도 40.1% → 18.5%로 4년 최저 수준에 근접")] + method[:1] + [("p", "화소별 자체 4년 기준 대비 상대값이므로 두 시기를 화소 단위로 직접 비교할 수 있습니다.")]
    card = dict(title="상대 토양수분 · Sentinel-1", sub=f"Chimney Meadows · {dk:%Y-%m-%d} · 100 m", swatch=[tuple(int(c * 255) for c in CMAP(t)[:3]) for t in np.linspace(0, 1, 6)])
    can = chat(can, q, ans, card)
    can.save(f"{OUT}/satchat_UK_{season}.png"); print("saved", season)


def make_uk_season_en(season):
    z, dates, rs = uk_rssm()
    if season == "summer":
        k = max([i for i, d in enumerate(dates) if pd.Timestamp("2018-07-01") <= d <= pd.Timestamp("2018-07-31")], key=lambda i: np.isfinite(rs[i]).mean())
    else:
        k = max([i for i, d in enumerate(dates) if pd.Timestamp("2017-12-01") <= d <= pd.Timestamp("2018-02-28") and np.isfinite(rs[i]).mean() > 0.9], key=lambda i: np.nanmean(rs[i]))
    dk = dates[k]; m = float(np.nanmean(rs[k]))
    allm = float(np.nanmean(rs[[i for i, d in enumerate(dates) if 2016 <= d.year <= 2019]]))
    from pyproj import Transformer
    hh, ww = rs.shape[1:]
    clon, clat = Transformer.from_crs(32630, 4326, always_xy=True).transform(float(z["x0"]) + ww * 50, float(z["y1"]) - hh * 50)
    can, T = basemap(clon, clat, 15, scale=0.85)
    can, _ = overlay(can, T, rs[k], from_origin(float(z["x0"]), float(z["y1"]), 100.0, 100.0), "EPSG:32630", CMAP, 0, 100)
    can = pin(can, T, -1.4788, 51.7080, "COSMOS-UK Chimney Meadows")
    can = paste_ui(can); can = clear_ask(can)
    can = legend(can, "Relative soil moisture (%)", f"Sentinel-1 · {dk:%d %b %Y} · 100 m", CMAP, 0, 100, [0, 20, 40, 60, 80, 100], ends=("Dry", "Wet"))
    method = [("h", "Method"),
              ("p", "Wet soil reflects radar signals more strongly. For each pixel, the lowest and highest backscatter levels observed over 2016–2019 serve as dry and wet references, and the current signal is scaled between them from 0% to 100%."),
              ("n", "0% = driest state of the pixel in four years · 100% = wettest state")]
    if season == "winter":
        q = "Show me the soil moisture around Chimney Meadows, UK, in December 2017."
        ans = [("p", f"Relative surface soil moisture was retrieved at 100 m resolution for a 3 km area around the Chimney Meadows station, using Sentinel-1 radar imagery acquired on {dk.day} {dk:%B %Y}."),
               ("h", "Results"),
               ("b", f"Mean relative soil moisture: {m:.0f}%, {m - allm:.0f} pp above the 2016–2019 average ({allm:.0f}%)"),
               ("b", "Wet conditions across most of the area"),
               ("b", "In-situ soil moisture at the station: 40.1% (2016–2019 range: 17–51%)")] + method
    else:
        W_ = json.load(open(f"{OUT}/UK_winter_stats.json"))
        q = "How did it change during the summer 2018 drought compared with that winter?"
        ans = [("p", f"The same area was re-analysed with the Sentinel-1 image of {dk.day} {dk:%B %Y} and compared with the result of 26 December 2017."),
               ("h", "Change from winter"),
               ("b", f"Mean relative soil moisture: {W_['mean']:.0f}% → {m:.0f}% ({m - W_['mean']:.0f} pp)".replace("(-", "(−")),
               ("b", "Soil moisture decreased in 91% of pixels; 74% dropped by more than 30 pp"),
               ("b", "Largest decline in the southeast (−54 pp), smallest in the southwest (−39 pp)"),
               ("b", "In-situ soil moisture also fell from 40.1% to 18.5%, close to its four-year minimum")] + method[:1] + [("p", "Each pixel is scaled against its own four-year dry and wet references, so the two dates can be compared directly, pixel by pixel.")]
    card = dict(title="Relative Soil Moisture · Sentinel-1", sub=f"Chimney Meadows · {dk:%Y-%m-%d} · 100 m", btn="View map",
                swatch=[tuple(int(c * 255) for c in CMAP(t)[:3]) for t in np.linspace(0, 1, 6)])
    can = chat(can, q, ans, card)
    can.save(f"{OUT}/satchat_UK_{season}_EN.png"); print("saved EN", season, round(m, 1))

if __name__ == "__main__":
    {"GP": make_gp, "UK": make_uk, "UKCMP": lambda: make_uk_compare(), "UKS": lambda: make_uk_season("summer"), "UKW": lambda: make_uk_season("winter"), "UKW_EN": lambda: make_uk_season_en("winter"), "UKS_EN": lambda: make_uk_season_en("summer")}[sys.argv[1]]()
