#!/usr/bin/env python
"""
2026 네팔 홍수 SAR 분석 카드뉴스 조립 (가로형).
문체는 평서체·개조식. 처리 도구명 등 기술 스택은 노출하지 않는다.
usage: build_card.py <TRACK> [version]
"""
import os, sys, json
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
from PIL import Image, ImageDraw, ImageFont

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
CARDS = f'{BASE}/analysis/cards'
FB = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
FR = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
def fb(s): return ImageFont.truetype(FB, s, index=1)
def fr(s): return ImageFont.truetype(FR, s, index=1)

Wc, Hc = 6600, 4700
BG = (14, 17, 22)
PANEL = (24, 29, 37)
ACC = (255, 76, 60)
CY = (95, 225, 240)
TXT = (238, 241, 245)
DIM = (168, 176, 188)
GOLD = (255, 196, 60)

MX, MY = 60, 340
PW = 1150
MW = 0      # 지도 종횡비에서 계산 (main에서 확정)
PX = Wc - 60 - PW
CX = 0
CW = 0
FOOT = Hc - 236
BOT = FOOT - 14

LABELS = [('Rasuwagadhi · Timure', 85.3792, 28.2810, 'r'),
          ('Syabrubesi', 85.3336, 28.1622, 'r'),
          ('Dhunche', 85.2971, 28.1004, 'r'),
          ('Haku Besi', 85.2400, 28.0200, 'l'),
          ('Betrawati', 85.1836, 27.9704, 'r'),
          ('Devighat', 85.1667, 27.8933, 'r'),
          ('Bidur', 85.1500, 27.8700, 'r')]
ZOOM_BOXES = [('source', 'A'), ('rasuwagadhi', 'B'), ('betrawati', 'C'), ('bidur', 'D')]
MAP_ONLY_BOXES = [('nrsc', 'E')]


def tb(d, xy, txt, font, fill, anchor=None):
    d.text(xy, txt, font=font, fill=fill, anchor=anchor)


def wrap(d, txt, font, maxw):
    out, line = [], ''
    for ch in txt:
        t = line + ch
        if d.textlength(t, font=font) > maxw and line:
            out.append(line); line = ch
        else:
            line = t
    if line:
        out.append(line)
    return out


def bullet(d, x, y, txt, font, fill, maxw, lh):
    for i, ln in enumerate(wrap(d, txt, font, maxw - 26)):
        if i == 0:
            tb(d, (x, y), '·', font, fill)
        tb(d, (x + 26, y), ln, font, fill)
        y += lh
    return y


def section(d, x, y, w, title):
    tb(d, (x, y), title, fb(44), GOLD)
    d.line([(x, y + 62), (x + w, y + 62)], fill=(85, 95, 110), width=3)
    return y + 88


def main():
    trk = sys.argv[1]
    ver = sys.argv[2] if len(sys.argv) > 2 else 'v1'
    exp = json.load(open(f'{BASE}/analysis/{trk}/exposure.json'))
    det = json.load(open(f'{BASE}/analysis/{trk}/flood_detect.json'))
    chips = json.load(open(f'{CARDS}/chips.json'))
    mm = json.load(open(f'{CARDS}/mainmap.json'))
    nrsc = json.load(open(f'{BASE}/analysis/nrsc_infra_check.json'))

    img = Image.new('RGB', (Wc, Hc), BG)
    d = ImageDraw.Draw(img)

    # ---------------- 헤더 ----------------
    d.rectangle([0, 0, Wc, 300], fill=(9, 11, 15))
    d.rectangle([0, 296, Wc, 302], fill=ACC)
    tb(d, (60, 34), 'NEPAL', fb(96), TXT)
    tb(d, (60, 142), '2026 Rasuwa · Nuwakot 돌발홍수 — 위성 레이더 피해 분석', fb(52), TXT)
    tb(d, (60, 212),
       '2026년 8월 26일 발생 · Langtang Lirung 북측 빙하 붕괴 → Bhote Koshi → Trishuli · 약 100 km 유하',
       fr(34), DIM)
    d.rectangle([Wc - 620, 60, Wc - 60, 190], outline=ACC, width=5)
    tb(d, (Wc - 340, 88), 'FLOOD', fb(66), ACC, anchor='ma')

    # ---------------- 좌: 주 지도 ----------------
    global MW, CX, CW
    mp = Image.open(f'{CARDS}/mainmap.png')
    MH = BOT - MY                                   # 좌측 열 전체 높이를 채운다
    MW = int(mp.width * MH / mp.height)
    CX = MX + MW + 46
    CW = PX - 46 - CX
    img.paste(mp.resize((MW, MH), Image.LANCZOS), (MX, MY))
    d.rectangle([MX, MY, MX + MW, MY + MH], outline=(90, 100, 115), width=3)

    def geo2px(lon, lat):
        return (MX + (lon - mm['W']) / (mm['E'] - mm['W']) * MW,
                MY + (mm['N'] - lat) / (mm['N'] - mm['S']) * MH)

    for nm, lo, la, side in LABELS:
        x, y = geo2px(lo, la)
        d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=GOLD, outline=(20, 20, 20), width=3)
        f = fb(30); tw = d.textlength(nm, font=f)
        bx = x + 20 if side == 'r' else x - 20 - tw - 16
        d.rectangle([bx - 8, y - 22, bx + tw + 10, y + 22], fill=(0, 0, 0))
        tb(d, (bx, y - 18), nm, f, TXT)

    sx0, sy0 = geo2px(85.52515, 28.28532)
    for rr, wdt in [(46, 7), (68, 5)]:
        d.ellipse([sx0 - rr, sy0 - rr, sx0 + rr, sy0 + rr], outline=(255, 240, 120), width=wdt)
    d.line([(sx0 - 30, sy0), (sx0 + 30, sy0)], fill=(255, 240, 120), width=6)
    d.line([(sx0, sy0 - 30), (sx0, sy0 + 30)], fill=(255, 240, 120), width=6)
    l1 = '빙하 붕괴 지점'; f1 = fb(36)
    bw2 = d.textlength(l1, font=f1) + 30
    lx, ly0 = sx0 - 120 - bw2, sy0 - 28
    d.rectangle([lx, ly0, lx + bw2, ly0 + 56], fill=(0, 0, 0), outline=(255, 240, 120), width=3)
    tb(d, (lx + 15, ly0 + 8), l1, f1, (255, 240, 120))
    d.line([(lx + bw2, sy0), (sx0 - 74, sy0)], fill=(255, 240, 120), width=4)

    for key, tag in ZOOM_BOXES + MAP_ONLY_BOXES:
        c = chips[key]
        x0, y0 = geo2px(c['lon'] - c['w_deg'] / 2, c['lat'] + c['h_deg'] / 2)
        x1, y1 = geo2px(c['lon'] + c['w_deg'] / 2, c['lat'] - c['h_deg'] / 2)
        d.rectangle([x0, y0, x1, y1], outline=(255, 255, 255), width=5)
        d.rectangle([x0, y0 - 82, x0 + 88, y0], fill=(255, 255, 255))
        tb(d, (x0 + 44, y0 - 76), tag, fb(60), (10, 10, 10), anchor='ma')

    d.rectangle([MX, MY, MX + MW, MY + 86], fill=(0, 0, 0))
    tb(d, (MX + 22, MY + 20),
       '레이더로 찾아낸 피해 지역 — 물이 휩쓸고 간 구간 전체 (약 70 km)', fb(38), TXT)
    ly = MY + MH - 250
    d.rectangle([MX + 16, ly, MX + 700, MY + MH - 16], fill=(0, 0, 0))
    d.rectangle([MX + 40, ly + 30, MX + 92, ly + 62], fill=ACC)
    tb(d, (MX + 110, ly + 26), '레이더로 찾아낸 피해 지역', fr(32), TXT)
    d.rectangle([MX + 40, ly + 84, MX + 92, ly + 116], fill=(60, 130, 140), outline=CY, width=3)
    tb(d, (MX + 110, ly + 80), '분석 범위 (물길 좌우 300 m)', fr(32), TXT)
    d.ellipse([MX + 46, ly + 136, MX + 86, ly + 176], outline=(255, 240, 120), width=5)
    tb(d, (MX + 110, ly + 138), '빙하 붕괴 지점', fr(32), TXT)
    km5 = 5.0 / 98.0 / (mm['E'] - mm['W']) * MW
    sx, sy = MX + 40, ly + 216
    d.line([(sx, sy), (sx + km5, sy)], fill=TXT, width=6)
    for xx in (sx, sx + km5):
        d.line([(xx, sy - 12), (xx, sy + 12)], fill=TXT, width=6)
    tb(d, (sx + km5 + 18, sy - 20), '5 km', fr(30), TXT)

    # ---------------- 중: 전후 비교 ----------------
    cy = MY
    d.rectangle([CX, cy, CX + CW, cy + 82], fill=PANEL)
    tb(d, (CX + 20, cy + 18), '위성 레이더 영상 전·후 비교', fb(40), TXT)
    cy += 100
    gapx = 16
    cw = (CW - 2 * gapx) // 3
    n_rows = len(ZOOM_BOXES)
    stats_h = 270
    avail = BOT - cy - stats_h - 220
    ch_ = min(avail // n_rows - 86, int(cw * chips['source']['px'][1] / chips['source']['px'][0]))
    pad = max(0, (avail - n_rows * (ch_ + 86)) // n_rows)
    for key, tag in ZOOM_BOXES:
        c = chips[key]
        tb(d, (CX, cy), f"[{tag}] {c['label']}   ·   폭 {c['km_w']:.1f} km", fb(34), GOLD)
        cy += 46
        for i, (sfx, cap) in enumerate([('pre', '사건 전  2026-08-16'),
                                        ('post_ov', '사건 후  2026-08-28'),
                                        ('chg', '변화')]):
            im = Image.open(f'{CARDS}/{key}_{sfx}.png').resize((cw, ch_), Image.LANCZOS)
            x = CX + i * (cw + gapx)
            img.paste(im, (x, cy))
            d.rectangle([x, cy, x + cw, cy + ch_],
                        outline=(ACC if sfx == 'post_ov' else (95, 105, 120)),
                        width=(5 if sfx == 'post_ov' else 3))
            d.rectangle([x, cy + ch_ - 58, x + cw, cy + ch_], fill=(0, 0, 0))
            tb(d, (x + 14, cy + ch_ - 51), cap, fb(36), TXT)
        cy += ch_ + 40 + pad
    cbx, cbw, cbh = CX + 2 * (cw + gapx), cw, 36
    for i in range(cbw):
        t = i / cbw * 16 - 8
        neg = max(0, min(1, -t / 8)); pos = max(0, min(1, t / 8))
        d.line([(cbx + i, cy), (cbx + i, cy + cbh)],
               fill=(int(235 - pos * 180), int(235 - pos * 60 - neg * 190), int(235 - neg * 190)))
    d.rectangle([cbx, cy, cbx + cbw, cy + cbh], outline=(120, 130, 145), width=2)
    tb(d, (cbx, cy + cbh + 10), '반사 감소', fr(26), DIM)
    tb(d, (cbx + cbw, cy + cbh + 10), '반사 증가', fr(26), DIM, anchor='ra')
    tb(d, (CX, cy + cbh + 4), '붉은색으로 표시한 곳이 홍수 피해를 입은 지역임.', fb(34), ACC)

    bx, by, bw = CX, cy + cbh + 66, 2 * cw + gapx
    d.rectangle([bx, by, bx + bw, by + stats_h], fill=PANEL, outline=(85, 95, 110), width=3)
    stats = [('피해 지역', f"{det['detect_km2']*100:.1f} ha"),
             ('거주 인구', f"{exp['detected']['pop']:,.0f} 명"),
             ('건물', f"{exp['detected']['bldg']:,} 동"),
             ('도로', f"{exp['detected']['road_km']:.0f} km")]
    for i, (k, v) in enumerate(stats):
        x = bx + 26 + i * (bw - 52) / 4
        tb(d, (x, by + 36), k, fr(30), DIM)
        tb(d, (x, by + 84), v, fb(62), TXT)
        if i:
            d.line([(x - 26, by + 32), (x - 26, by + stats_h - 44)], fill=(70, 80, 95), width=2)
    tb(d, (bx + 26, by + 196),
       '거주 인구·건물·도로는 피해 지역에서 200 m 이내(피해 영향권) 기준임.', fr(28), DIM)

    # ---------------- 우: 정보 패널 ----------------
    d.rectangle([PX, MY, PX + PW, BOT], fill=PANEL)
    px, py = PX + 26, MY + 26
    pw = PW - 52

    py = section(d, px, py, pw, '사건 개요')
    for t in ['2026년 8월 26일 오전 Langtang Lirung 북측 해발 4,900 m 지점에서 빙하와 암반이 붕괴함.',
              '토석류와 돌발홍수가 약 100 km를 흘러 Rasuwa · Nuwakot과 중국 Gyirong 일대를 덮침.']:
        py = bullet(d, px, py, t, fr(33), TXT, pw, 46) + 18
    py += 34

    py = section(d, px, py, pw, '사용 위성자료')
    for k, v in [('위성', 'Sentinel-1  (유럽우주국)'),
                 ('사건 전 촬영', '2026년 8월 16일'),
                 ('사건 후 촬영', '2026년 8월 28일'),
                 ('비교 기준 촬영', '2026년 8월 4일')]:
        tb(d, (px, py), k, fr(33), DIM)
        tb(d, (px + pw, py), v, fb(33), TXT, anchor='ra')
        py += 58
    py += 34

    py = section(d, px, py, pw, '분석 기법')
    for t in ['홍수가 지나간 자리는 매끄러운 퇴적물로 덮여 레이더 신호를 되돌려 보내지 못함.',
              '사건 전후 영상의 반사 강도 차이를 비교하여 지표가 달라진 구역을 찾아냄.',
              '홍수가 없던 기간의 변화와 비교하여 홍수로 인한 변화만 가려냄.']:
        py = bullet(d, px, py, t, fr(33), TXT, pw, 46) + 18
    py += 34

    py = section(d, px, py, pw, '추정 피해 규모')
    grp = [(0, '분석 범위', f"{exp['corridor']['area_km2']:.1f} km²"),
           (1, '거주 인구', f"{exp['corridor']['pop']:,.0f} 명"),
           (0, '피해 지역', f"{det['detect_km2']*100:.1f} ha"),
           (0, '피해 영향권', f"{exp['detected']['area_km2']:.1f} km²"),
           (1, '거주 인구', f"{exp['detected']['pop']:,.0f} 명"),
           (1, '건물', f"{exp['detected']['bldg']:,} 동"),
           (1, '도로', f"{exp['detected']['road_km']:.1f} km"),
           (1, '마을', f"{len(exp['detected_places'])} 개소")]
    for lvl, k, v in grp:
        if lvl == 0:
            tb(d, (px, py), k, fb(33), TXT)
            tb(d, (px + pw, py), v, fb(34), TXT, anchor='ra')
        else:
            tb(d, (px + 34, py), '└ ' + k, fr(31), DIM)
            tb(d, (px + pw, py), v, fr(32), TXT, anchor='ra')
        py += 58
    py += 34

    py = section(d, px, py, pw, '지역별 피해 정도')
    colx = [px, px + 350, px + 620, px + 860]
    for i, h in enumerate(['지역', '분석 범위', '피해 영향권', '거주 인구']):
        tb(d, (colx[i], py), h, fr(29), DIM)
    py += 50
    d.line([(px, py - 8), (px + pw, py - 8)], fill=(75, 85, 100), width=2)
    order = {'Rasuwa': 0, 'Nuwakot': 1, 'Gyirong County': 2, 'Dhading': 3}
    kor = {'Rasuwa': 'Rasuwa (Nepal)', 'Nuwakot': 'Nuwakot (Nepal)',
           'Gyirong County': 'Gyirong (China)', 'Dhading': 'Dhading (Nepal)'}
    for r in sorted(exp['districts'], key=lambda z: order.get(z['district'], 9)):
        vals = [kor.get(r['district'], r['district']), f"{r['corr_km2']:.1f} km²",
                f"{r['det_km2']:.2f} km²", f"{r['det_pop']:,.0f} 명"]
        for i, v in enumerate(vals):
            tb(d, (colx[i], py), v, (fb(31) if i == 0 else fr(31)), TXT)
        py += 58

    py += 30
    py = section(d, px, py, pw, '개별 시설 확인')
    py = bullet(d, px, py, '고해상도 광학위성이 유실로 판정한 시설임.', fr(30), DIM, pw, 40) + 14
    c = chips['nrsc']
    cwid = (pw - 20) // 3
    cph = int(cwid * c['px'][1] / c['px'][0])
    for i, (sfx, cap) in enumerate([('pre', '사건 전'), ('post_ov', '사건 후'), ('chg', '변화')]):
        im = Image.open(f'{CARDS}/nrsc_{sfx}.png').resize((cwid, cph), Image.LANCZOS)
        x = px + i * (cwid + 10)
        img.paste(im, (x, py))
        if sfx == 'pre':
            # 사건 전 영상에 두 시설의 위치를 표시한다
            w0, h0 = c['lon'] - c['w_deg'] / 2, c['lat'] + c['h_deg'] / 2
            for j, r in enumerate(nrsc):
                fx = (r['lon'] - w0) / c['w_deg']
                fy = (h0 - r['lat']) / c['h_deg']
                mx_, my_ = x + fx * cwid, py + fy * cph
                d.ellipse([mx_ - 16, my_ - 16, mx_ + 16, my_ + 16],
                          outline=(255, 240, 120), width=4)
                d.line([(mx_ - 26, my_), (mx_ - 20, my_)], fill=(255, 240, 120), width=4)
                d.line([(mx_ + 20, my_), (mx_ + 26, my_)], fill=(255, 240, 120), width=4)
                lb = '①' if j == 0 else '②'
                tb(d, (mx_, my_ - 62), lb, fb(40), (255, 240, 120), anchor='ma')
        d.rectangle([x, py, x + cwid, py + cph],
                    outline=(ACC if sfx == 'post_ov' else (95, 105, 120)),
                    width=(4 if sfx == 'post_ov' else 3))
        d.rectangle([x, py + cph - 46, x + cwid, py + cph], fill=(0, 0, 0))
        tb(d, (x + 10, py + cph - 41), cap, fb(30), TXT)
    py += cph + 24
    for j, r in enumerate(nrsc):
        nm = (r['name'].replace('Trishuli 수력 댐', 'Trishuli Hydropower Dam')
                       .replace('Bhainse Aama 신교', 'Bhainse Aama Bridge'))
        tb(d, (px, py), ('①' if j == 0 else '②'), fb(31), (255, 240, 120))
        tb(d, (px + 46, py), nm, fb(31), TXT)
        tb(d, (px + pw, py), '피해 확인', fb(31), ACC, anchor='ra')
        py += 52
    py += 8
    py = bullet(d, px, py, '두 시설 모두 레이더가 같은 자리에서 변화를 확인함.',
                fr(29), DIM, pw, 39)

    lm = Image.open(f'{CARDS}/locmap.png')
    top = py + 76
    avail_l = BOT - top - 40
    lw = pw; lh = int(lm.height * lw / lm.width)
    if lh > avail_l:
        lh = max(0, avail_l); lw = int(lm.width * lh / lm.height)
    if lh > 120:
        tb(d, (px, top - 66), '분석 지역', fb(44), GOLD)
        img.paste(lm.resize((lw, lh), Image.LANCZOS), (px, top))
        d.rectangle([px, top, px + lw, top + lh], outline=(90, 100, 115), width=3)

    # ---------------- 푸터 ----------------
    d.rectangle([0, FOOT, Wc, Hc], fill=(9, 11, 15))
    d.rectangle([0, FOOT, Wc, FOOT + 5], fill=ACC)
    cols = [('위성 영상', ['Sentinel-1  유럽우주국 (ESA)', '2026년 8월 4일 · 16일 · 28일 촬영']),
            ('지형 자료', ['Copernicus DEM  30 m']),
            ('인구 자료', ['WorldPop  UN 보정 인구격자']),
            ('지도 자료', ['OpenStreetMap  하천 · 건물 · 도로 · 행정구역']),
            ('참고 자료', ['UNOSAT · NRSC/ISRO 재난지도'])]
    for i, (h, lines) in enumerate(cols):
        x = 60 + i * (Wc - 120) / len(cols)
        tb(d, (x, FOOT + 34), h, fb(30), GOLD)
        for j, ln in enumerate(lines):
            tb(d, (x, FOOT + 82 + j * 38), ln, fr(26), DIM)
    tb(d, (60, Hc - 52),
       '분석·제작 TelePix  |  좌표계 WGS84', fr(26), DIM)

    out = f'{BASE}/analysis/(08.30)2026_네팔홍수_SAR분석_카드뉴스_{ver}.png'
    img.save(out)
    print('wrote', out)


if __name__ == '__main__':
    main()
