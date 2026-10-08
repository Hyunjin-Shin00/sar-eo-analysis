"""단계 2 — 야외 적재물 탐지 (A4·A5).

탐지 영역은 **필지 − 건물**이다. 건물 폴리곤을 어두운 베일로 덮어 지붕을 적재물로 읽지
않게 한다(v1 실측: 덮지 않으면 톱날 지붕 공장동을 '목재 팔레트 6,241 ㎡'로 읽었다).

판독은 VLM 이 한다. 프롬프트·JSON 스키마·API 호출은 [[vendor/yard_vlm.py]] 에 있다 —
원본은 `parcelscan/yardscan.py` 이고, 이 폴더만 떼어가도 돌도록 사본을 두었다.
**프롬프트 문구는 한 글자도 바꾸지 않았다**(분류 기준이 근거문서 A4·A5 와 1:1 대응한다).

yardscan 과 다른 점은 하나다. yardscan 은 장면 전체를 훑고 여기는 **필지 하나**만 본다.
타일 크기(192 m)와 배율(×2 → 0.25 m/px)은 같게 두었다 — 프롬프트가 "모든 타일이 같은
지상면적을 같은 축척으로 담는다"를 전제로 크기를 판단하기 때문이다.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from sitecheck import settings as config
from sitecheck import rules
from sitecheck import schema
from sitecheck.vendor import shadow as sd
from sitecheck.vendor import spectral as sp
from sitecheck.vendor import yard_vlm as YS

SEARCH_M = 60.0      # 건물까지 최단거리 탐색 반경 — 이 밖은 '인접 건물 없음'
TILE_M = 192.0       # yardscan 과 동일 — 프롬프트가 이 축척을 전제한다
STRIDE_M = 168.0     # 12.5 % 중첩 — 타일 경계에 걸친 적치물을 놓치지 않게
UP = 2               # 표시 배율 → 0.25 m/px
MIN_OPEN_M2 = 300.0  # 이보다 빈 땅이 적으면 부를 가치가 없다
BLD_FILL = (10, 20, 55, 160)
BLD_EDGE = (70, 200, 255)
YEL = (255, 220, 40)


def detection_area(site, buildings_fc):
    """탐지 영역 = 필지 − 건물. shapely geometry(4326) 또는 None."""
    from shapely.geometry import shape
    from shapely.ops import unary_union
    if not site.get("parcel"):
        return None
    par = shape(site["parcel"])
    blds = [shape(f["geometry"]) for f in (buildings_fc.get("features") or [])]
    return par.difference(unary_union(blds)) if blds else par


# ── 좌표 변환 ────────────────────────────────────────────────────────────────
def _lonlat_to_px(T, crs, geom):
    """경위도 geometry → 영상 픽셀 geometry."""
    from pyproj import Transformer
    from shapely.ops import transform as sh_transform
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = ~T

    def f(xs, ys):
        e, n = tr.transform(list(xs), list(ys))
        px, py = [], []
        for a, b in zip(e, n):
            c = inv * (a, b)
            px.append(c[0])
            py.append(c[1])
        return px, py
    return sh_transform(f, geom)


def _px_box_to_lonlat(T, crs, x0, y0, x1, y1):
    """영상 픽셀 bbox → 경위도 Polygon."""
    from pyproj import Transformer
    from shapely.geometry import Polygon
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    e = [T.c + T.a * x + T.b * y for x, y in corners]
    n = [T.f + T.d * x + T.e * y for x, y in corners]
    lon, lat = tr.transform(e, n)
    return Polygon(list(zip(lon, lat)))


def zones_from_fc(fc):
    """저장된 FeatureCollection → 판독 원본(zone dict) 목록.

    `_yard.json` 은 **판독이 끝난 결과**를 담는데, 그 안에는 모델이 말한 것(무엇이 · 어떻게
    쌓였나)과 우리가 계산한 것(건물까지 거리 · 판정 · 번호)이 섞여 있다. 뒤엣것은 건물이
    달라지면 값이 달라지므로 캐시에서 되살릴 때 **다시 계산해야 한다** — 그래서 모델이 말한
    것만 골라 되돌린다. VLM 을 다시 부르지 않는 이유는 그것이 유료이고, 판독 대상(영상과
    건물 밖 공지)은 그대로이기 때문이다.
    """
    out = []
    for f in fc.get("features") or []:
        p = f.get("properties") or {}
        out.append({"geometry": f.get("geometry"), "cls": p.get("cls"),
                    "subtype": p.get("subtype"), "order": p.get("order"),
                    "covered": p.get("covered"), "height": p.get("height_band"),
                    "confidence": p.get("confidence"), "is_ground": p.get("is_ground"),
                    "evidence": p.get("evidence"), "wall": bool(p.get("wall_note"))})
    return out


def refeature(fc, buildings_fc, site):
    """저장된 판독 결과를 **지금의 건물·필지로 다시 판정한다.** 새 FeatureCollection.

    거리·판정·번호가 저장 시점의 건물 집합에 묶여 있으면, 건물이 바뀐 뒤에도 옛 판정이
    그대로 나간다(캐시가 판정을 굳힌다). 모델 답만 남기고 나머지를 다시 계산한다.
    """
    got = to_features(zones_from_fc(fc), buildings_fc, site)
    old = (fc.get("note") or "").split(" · 저장된")[0]
    if old and old not in (got.get("note") or ""):
        got["note"] = f"{old} · {got.get('note') or ''}".strip(" ·")
    return got


# ── 장면 그림 ────────────────────────────────────────────────────────────────
_PNG = {}      # {scene_dir: 디코드한 scene.png} — **한 장만 들고 있는다**
_PNG_LOCK = threading.Lock()


def scene_png(scene_dir):
    """`scene.png` 를 열어 **한 번만 디코드하고 들고 있는다.**

    장면 하나가 9,936×10,079 라 여는 데 3~5 초 걸린다. 필지 하나마다 다시 열면 여러
    필지를 잇달아 훑을 때(`run.py --file` · 뷰어 훑기) 판독보다 디코드가 오래 걸린다 —
    1,000 필지면 디코드만 한 시간이다.

    **장면이 바뀌면 앞의 것을 버린다.** 두 장을 같이 들고 있을 이유가 없고(한 실행은 보통
    한 장면을 본다), 한 장이 300 MB 라 쌓이면 그것이 먼저 문제가 된다.

    돌려주는 그림은 **읽기만 해야 한다** — 여러 갈래가 같은 객체를 나눠 쓴다(`crop` 은
    새 그림을 만들므로 안전하다).
    """
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    key = str(scene_dir)
    with _PNG_LOCK:                     # 여러 갈래가 같이 첫 호출을 하면 둘 다 디코드한다
        if key not in _PNG:
            _PNG.clear()
            im = Image.open(Path(scene_dir) / "scene.png").convert("RGB")
            im.load()                   # 게으른 디코드를 여기서 끝낸다 — 캐시의 뜻이 그것이다
            _PNG[key] = im
        return _PNG[key]


# ── 타일 만들기 ──────────────────────────────────────────────────────────────
def _tile_image(png, arr_idx, tx, ty, x1, y1, bld_px, par_px, res_m):
    """VLM 에 넣을 타일 이미지 — 건물 베일(짙은 남색+시안) + 필지 외곽선(노랑)."""
    from PIL import Image, ImageDraw
    ww, hh = x1 - tx, y1 - ty
    canvas = png.crop((tx, ty, x1, y1)).resize((ww * UP, hh * UP), Image.LANCZOS).convert("RGBA")
    if bld_px:
        veil = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        vd = ImageDraw.Draw(veil)
        for b in bld_px:
            pts = [((px - tx) * UP, (py - ty) * UP) for px, py in b.exterior.coords]
            if len(pts) >= 3:
                vd.polygon(pts, fill=BLD_FILL, outline=BLD_EDGE)
        canvas = Image.alpha_composite(canvas, veil)
    canvas = canvas.convert("RGB")
    dd = ImageDraw.Draw(canvas)
    for g in par_px:
        for gg in (g.geoms if g.geom_type.startswith("Multi") else [g]):
            if gg.geom_type != "Polygon" or gg.is_empty:
                continue
            pts = [((px - tx) * UP, (py - ty) * UP) for px, py in gg.exterior.coords]
            if len(pts) >= 3:
                dd.line(pts + [pts[0]], fill=YEL, width=2)
    return canvas


def _caption(ww, hh, res_m, usable_m2, veg, sun, uses):
    """yardscan 과 같은 문장 구조 — 프롬프트가 이 단서들을 전제로 쓰여 있다."""
    mpp = res_m / UP
    sunline = ""
    if sun is not None:
        _dt, az, el, u = sun
        sunline = (f"Sun at {az:.0f}deg azimuth, {el:.0f}deg above the horizon: shadows "
                   f"fall toward the {YS.compass(u)} of whatever casts them, and a 5 m tall "
                   f"object throws a "
                   f"shadow {5.0 / np.tan(np.radians(el)) / mpp:.0f} px long. A building "
                   f"throws a long one; a pallet stack a short one. ")
    return (f"Tile {ww * UP}x{hh * UP} px at {mpp:.2f} m/px ({TILE_M:.0f} m on the ground). "
            f"A passenger car is {4.5 / mpp:.0f} px long, a shipping container "
            f"{12.2 / mpp:.0f} px, a wooden pallet {1.2 / mpp:.0f} px. "
            f"Open ground inside the parcels, buildings excluded: {usable_m2:,.0f} m2. "
            f"Vegetation covers {veg * 100:.0f}% of the tile (measured NDVI). "
            + sunline
            + (f"Registered uses here: {', '.join(uses)}. " if uses else "")
            + "Inventory material stored on open ground. Work through STEP 1-2-3.")


# ── 판독 ────────────────────────────────────────────────────────────────────
def detect(site, buildings_fc, *, model="gpt-5.6-terra", save_tiles=None, verbose=False):
    """필지를 타일로 잘라 VLM 에 묻고, 나온 구역에 A5 판정을 붙여 공통 형식으로 낸다."""
    area = detection_area(site, buildings_fc)
    if area is None:
        return schema.empty("yard", "필지가 없어 탐지 영역(필지−건물)을 만들 수 없다")
    sc = site.get("scene")
    if not sc:
        return schema.empty("yard", "정사영상이 없어 판독할 수 없다")
    key = config.keys().get("OPENAI_API_KEY")
    if not key:
        return schema.empty("yard", "OPENAI_API_KEY 없음 — 판독 모델을 부를 수 없다")

    import rasterio
    from shapely.geometry import box as shbox
    from shapely.geometry import shape

    scene_dir = config.SCENES[sc["key"]]["dir"].resolve()
    # **보정된 지오트랜스폼**을 쓴다 — 필지를 영상 위에 얹어 타일을 자르고, 판독 결과
    # 픽셀 상자를 다시 좌표로 되돌리는 양쪽이 같은 기준이어야 한다([[georef.py]]).
    from sitecheck.steps import georef
    T, crs, W, H = georef.xform(site)
    res_m = float(sc.get("res_m") or 0.5)
    meta = config.scene_meta(sc["key"])
    sun = sd.scene_sun(meta, verbose=False)

    par_px = _lonlat_to_px(T, crs, shape(site["parcel"]))
    bld_px = [_lonlat_to_px(T, crs, shape(f["geometry"]))
              for f in (buildings_fc.get("features") or [])]
    bld_px = [b for b in bld_px if b.geom_type == "Polygon" and not b.is_empty]

    png = scene_png(scene_dir)
    ds = rasterio.open(sp.scene_tif(scene_dir))

    tpx = int(round(TILE_M / res_m))
    spx = int(round(STRIDE_M / res_m))
    px0, py0, px1, py1 = par_px.bounds
    xs = list(range(max(0, int(px0) - tpx // 4), min(W, int(px1) + tpx // 4), spx)) or [int(px0)]
    ys = list(range(max(0, int(py0) - tpx // 4), min(H, int(py1) + tpx // 4), spx)) or [int(py0)]

    uses = sorted({(b.get("main_purpose") or "").split(" · ")[0]
                   for b in (site.get("ledger") or [])} - {""})[:3]
    zones, calls, errs, skipped = [], 0, [], 0
    for ty in ys:
        for tx in xs:
            x1, y1 = min(W, tx + tpx), min(H, ty + tpx)
            if x1 - tx < tpx * 0.6 or y1 - ty < tpx * 0.6:
                continue
            tbox = shbox(tx, ty, x1, y1)
            if not par_px.intersects(tbox):
                continue
            arr = sp.read_window(ds, tx, ty, x1, y1)
            if arr is None:
                continue
            ix = sp.indices(arr)
            if ix["nodata"].mean() > 0.35:
                continue
            og = sp.open_ground(ix)
            hh, ww = og.shape
            usable = _usable_m2(og, par_px, bld_px, tx, ty, ww, hh, res_m)
            if usable < MIN_OPEN_M2:
                skipped += 1
                continue
            img = _tile_image(png, ix, tx, ty, x1, y1,
                              [b for b in bld_px if b.intersects(tbox)],
                              [par_px.intersection(tbox)], res_m)
            cap = _caption(ww, hh, res_m, usable, float((ix["ndvi"] > 0.20).mean()), sun, uses)
            try:
                r = YS.call_api(key, model, img, cap)
                calls += 1
            except Exception as e:                              # noqa: BLE001
                errs.append(f"tile {tx},{ty}: {type(e).__name__}: {e}")
                continue
            if save_tiles:
                # **모델에 보낸 바이트를 그대로 남긴다**(`YS.encode`) — 다시 인코딩하면
                # 「모델이 본 그림」이 아니라 그것을 한 번 더 뭉갠 그림이 남는다.
                Path(save_tiles).mkdir(parents=True, exist_ok=True)
                (Path(save_tiles) / f"t{tx}_{ty}.jpg").write_bytes(YS.encode(img))
            for it in r.get("items", []):
                b = it["bbox_px"]
                sx0, sy0 = tx + min(b[0], b[2]) / UP, ty + min(b[1], b[3]) / UP
                sx1, sy1 = tx + max(b[0], b[2]) / UP, ty + max(b[1], b[3]) / UP
                if sx1 - sx0 < 2 or sy1 - sy0 < 2:
                    continue
                zones.append({
                    "geometry": _px_box_to_lonlat(T, crs, sx0, sy0, sx1, sy1).__geo_interface__,
                    "cls": it.get("cls"), "subtype": it.get("subtype") or None,
                    "order": it.get("order"), "covered": it.get("covered"),
                    "height": it.get("height"), "confidence": it.get("confidence"),
                    "is_ground": it.get("is_ground_not_roof"),
                    "evidence": it.get("evidence"),
                    "wall": False,
                })
    ds.close()

    fc = to_features(zones, buildings_fc, site)
    notes = []
    if errs:
        notes.append(f"타일 {len(errs)}개 판독 실패 — {errs[0][:120]}")
    if skipped:
        notes.append(f"빈 땅이 {MIN_OPEN_M2:.0f} ㎡ 미만인 타일 {skipped}개는 건너뜀")
    notes.append(f"VLM 호출 {calls}회 · 모델 {model}")
    fc["note"] = " · ".join([n for n in [fc.get("note")] if n] + notes)
    return fc


def _usable_m2(og, par_px, bld_px, tx, ty, ww, hh, res_m):
    """타일 안 '필지 − 건물 − 초목/물/그림자' 면적(㎡). 캡션에 넣어 크기 감각을 준다."""
    from PIL import Image, ImageDraw
    from shapely.geometry import box as shbox
    tbox = shbox(tx, ty, tx + ww, ty + hh)

    def mask_of(geoms):
        im = Image.new("1", (ww, hh), 0)
        d = ImageDraw.Draw(im)
        for g in geoms:
            gg = g.intersection(tbox)
            for q in (gg.geoms if gg.geom_type.startswith("Multi") else [gg]):
                if q.geom_type != "Polygon" or q.is_empty:
                    continue
                pts = [(px - tx, py - ty) for px, py in q.exterior.coords]
                if len(pts) >= 3:
                    d.polygon(pts, fill=1)
        return np.asarray(im, bool)

    pm = mask_of([par_px])
    bm = mask_of(bld_px) if bld_px else np.zeros((hh, ww), bool)
    return float((og & pm & (~bm)).sum() * res_m * res_m)


def to_features(zones, buildings_fc, site=None):
    """판독 결과 zone 목록 → yard FeatureCollection.

    거리는 여기서 잰다 — 판독 모델에 거리를 물으면 눈대중이 들어간다.
    """
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union

    fwd = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    bfs = list(buildings_fc.get("features") or [])
    blds = [transform(fwd.transform, shape(f["geometry"])) for f in bfs]
    bu = unary_union(blds) if blds else None
    par = transform(fwd.transform, shape(site["parcel"])) if (site or {}).get("parcel") else None

    out, dropped = [], 0
    for z in (zones or []):
        cls = z.get("cls")
        if cls in rules.YARD_EXCLUDED:      # 고철·토사·차량은 별표2 품명에 없다 → 버린다
            dropped += 1
            continue
        if cls not in rules.YARD_CLASSES:
            cls = "other_stock"
        g = transform(fwd.transform, shape(z["geometry"]))
        if par is not None and not par.intersects(g):
            dropped += 1                    # 필지 밖은 이 지번의 위험이 아니다
            continue
        # **어느 건물까지 잰 것인지 같이 담는다.** 값은 union 까지의 거리와 같지만(최소값),
        # 상대를 적어 두지 않으면 「인접 건물까지 15.9 m」의 그 건물을 받는 쪽이 못 찾는다 —
        # 그림은 그 선을 그리는데 값에는 없었다.
        #
        # **미결 — 상대가 이 지번 건물뿐이다.** `buildings_fc` 는 이 지번 건물만 담으므로
        # 옆 지번 건물이 더 가까워도 잡히지 않는다(실측 구미 공단동 282: 1·2번 구역이 이
        # 지번 건물까지 150·163 m 인데 옆 지번 건물까지는 31·30 m). 이격(A1)은 「연소는 지번
        # 경계를 넘어 옮겨붙는다」며 옆 필지 건물까지 재는데 여기는 안 잰다 — 어느 쪽이 맞는지
        # 는 판정 규칙의 문제이고, 바꾸면 A5 등급이 달라지므로 손대지 않고 남긴다.
        d = near_id = None
        if bu is not None:
            pick = min(((float(bg.distance(g)), bf) for bg, bf in zip(blds, bfs)),
                       key=lambda t: t[0])
            d, near_id = pick[0], pick[1]["properties"].get("bld_id")
        if d is not None and d > SEARCH_M:
            d, near_id = None, None
        v = rules.yard_verdict(d, cls)
        meta = rules.YARD_CLASSES[cls]
        props = schema.verdict_props(
            v,
            yard_id=None,          # 아래에서 기하 순으로 매긴다
            cls=cls, cls_ko=meta["ko"], law=meta["law"], kfs=meta["kfs"],
            subtype=z.get("subtype"), order=z.get("order"), covered=z.get("covered"),
            height_band=z.get("height"), confidence=z.get("confidence"),
            is_ground=z.get("is_ground"), evidence=z.get("evidence"),
            dist_to_building_m=None if d is None else round(d, 1),
            near_bld_id=near_id,
            wall_note=rules.YARD_WALL_NOTE if z.get("wall") else None,
            # 수량·면적은 내지 않는다 — 별표2 수량은 kg·㎥ 라 위성으로 못 재고,
            # 별표3 나목의 50 ㎡ 는 '쌓는 부분' 1개 기준이라 구역 전체와 단위가 다르다.
            note="수량·면적은 산출하지 않는다(근거문서 A5)",
        )
        out.append(schema.feature(transform(inv.transform, g), props))

    # **번호는 기하 순으로 매긴다**(건물과 같은 규칙 — [[s1_building.id_sort_key]]). 판독
    # 타일을 도는 순서로 매기면 같은 영상을 다시 판독할 때 번호가 밀리고, 판정 순으로 매기면
    # 판정이 바뀔 때 번호가 따라 바뀐다. 정렬은 그 뒤에 따로 한다(표에 싣는 순서는 판정 순).
    from sitecheck.steps.s1_building import id_sort_key
    for i, f in enumerate(sorted(out, key=lambda f: id_sort_key(shape(f["geometry"]))), 1):
        f["properties"]["yard_id"] = f"Y{i:04d}"
        f["id"] = f["properties"]["yard_id"]

    out.sort(key=rules.yard_sort_key)
    note = None if out else "검출된 적재 구역이 없다"
    if dropped:
        note = (note + " · " if note else "") + f"대상 외/필지 밖 {dropped}건 제외"
    return schema.collection(out, "yard", note=note)
