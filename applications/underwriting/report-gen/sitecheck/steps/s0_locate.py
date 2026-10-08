"""단계 0 — 주소 → 좌표 → 필지(PNU) → 건축물대장 → 영상 선택.

뒤 단계가 전부 이 결과 위에서 돈다. 여기서 나오는 세 가지가 없으면 나머지가 성립하지 않는다.

  · **필지 폴리곤** — 야적 탐지 영역(필지 − 건물)의 바깥 경계이자 대지경계선 이격의 기준선
  · **건축물대장** — 대장 대조(A3)의 정본이고, 이격(A1) 판정에 필요한 **층수**의 유일한 출처
  · **영상** — 건물 폴리곤을 뽑을 정사영상. 없으면 뒤 단계를 돌리지 않고 그렇게 적는다

주소가 PoC 영상 3장의 범위 밖이면 여기서 멈춘다. 빈 결과를 내면 '건물이 0동'과
'영상이 없음'이 같은 모양이 되어 구분되지 않는다.

좌표 프레임
-----------
여기서 담는 필지·인접필지는 **조회한 그대로**다 — 어디로도 옮기지 않는다. 영상과 어긋나는
쪽은 영상이므로 [[georef.py]] 가 영상의 지오레퍼런스를 되돌린다. 예외는 연속지적도 필지
레이어 자신의 편이 하나뿐이고([[parcel_bias.py]]), 그것은 옮긴 양을 결과에 적는다.
"""
from __future__ import annotations

from sitecheck import settings as config
from sitecheck.vendor import geoapi

# 주변 필지 조회 반경(도). 0.0015° ≈ 130~165 m — 이격 판정 반경 60 m 와 건물 크기를 덮는다.
NEIGHBOR_PAD_DEG = 0.0015


def _geocode(address, vworld_key):
    """주소 → (lon, lat, 종류). 도로명 우선, 실패 시 지번."""
    for t in ("ROAD", "PARCEL"):
        pt = geoapi.geocode(address, vworld_key, addr_type=t)
        if pt:
            return {"lon": float(pt[0]), "lat": float(pt[1]), "addr_type": t}
    return None


def reverse_geocode(lon, lat, vworld_key):
    """좌표 → 지번 주소. 임의 지점을 시험할 때 쓴다(주소 목록을 손으로 만들지 않아도 된다)."""
    return geoapi.reverse_geocode(lon, lat, vworld_key)


def parcels_near(lon, lat, vworld_key, pad_deg):
    """점 주변 bbox 의 연속지적도 필지 전부 → {pnu: shapely Polygon}."""
    from shapely.geometry import shape
    bbox = [lon - pad_deg, lat - pad_deg, lon + pad_deg, lat + pad_deg]
    out = {}
    for pnu, geom in (geoapi.parcels_in_bbox(bbox, vworld_key) or {}).items():
        if not geom:
            continue
        try:
            g = shape(geom)
        except Exception:                                    # noqa: BLE001
            continue
        if not g.is_valid:
            g = g.buffer(0)
        if not g.is_empty:
            out[pnu] = g
    return out


def _parcel_at(lon, lat, vworld_key, pad_deg=0.0012):
    """점을 담는 연속지적도 필지 → (pnu, geometry, raw).

    **점을 담는 필지가 없으면 포기한다.** 예전에는 '가장 가까운 필지'로 물러났는데,
    지오코딩 좌표가 필지 밖에 떨어지는 경우(실측: 호산동 700-9) 620 m 떨어진 엉뚱한
    땅을 집었다. 그러면 그 뒤 판정이 전부 남의 땅 위에서 이뤄진다.
    호출부가 PNU 를 알면 `parcel_by_pnu` 를 쓰는 편이 낫다.
    """
    from shapely.geometry import Point, shape
    bbox = [lon - pad_deg, lat - pad_deg, lon + pad_deg, lat + pad_deg]
    got = geoapi.parcels_in_bbox(bbox, vworld_key) or {}
    pt = Point(lon, lat)
    best = None
    for pnu, geom in got.items():          # 반환은 {pnu: geometry(4326)} — 한 겹 더 없다
        if not geom:
            continue
        try:
            poly = shape(geom)
        except Exception:                  # noqa: BLE001
            continue
        if poly.contains(pt):
            return pnu, poly, geom
        d = poly.distance(pt)
        if best is None or d < best[0]:
            best = (d, pnu, poly, geom)
    if best and best[0] <= pad_deg * 0.25:   # 아주 가까운 경계 오차만 허용
        return best[1], best[2], best[3]
    return None, None, None


def _ledger(pnu, data_key):
    """PNU → 건축물대장 표제부 목록. 층수·건축면적·연면적·용도가 여기서 온다."""
    try:
        return geoapi.fetch_ledger_pnu(pnu, data_key) or []
    except Exception as e:                                   # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_ledger(rows):
    """대장 원본 행 → 뒤 단계가 쓰는 최소 필드만.

    필드명이 API 원본 그대로면 뒤 단계가 전부 API 스키마에 묶인다. 여기서 한 번만 번역한다.
    """
    out = []
    for r in rows or []:
        out.append({
            "dong": (r.get("dongNm") or "").strip() or None,          # 동 명칭
            "main_purpose": (r.get("mainPurpsCdNm") or "").strip() or None,
            "struct": (r.get("strctCdNm") or "").strip() or None,     # 구조 — 요율 1차축
            "roof": (r.get("roofCdNm") or "").strip() or None,        # 지붕재
            "arch_area_m2": _num(r.get("archArea")),                  # 건축면적 — A3 비교 대상
            "total_area_m2": _num(r.get("totArea")),                  # 연면적 — 특수건물 판정
            "floors_above": _num(r.get("grndFlrCnt")),                # 지상층수 — A1 판정
            "floors_below": _num(r.get("ugrndFlrCnt")),
            "use_approval": (r.get("useAprDay") or "").strip() or None,
            "pnu": r.get("pnu"),
        })
    return out


def apply_ledger_drop(site, names=(), *, verbose=False):
    """대장에서 **사람이 확인해 빼기로 한 동**을 뺀다([[hand.py]] `ledger_drop`). 뺐으면 True.

    저장된 site(`_site.json` · `result.json`)에도 걸어야 하므로 함수로 따로 둔다 — GT 경로는
    주소를 다시 해석하지 않고 저장본을 쓴다([[analyze.py]] `load_site`).
    **두 번 걸어도 같은 결과다**(`ledger_drop` 을 남겨 두고 두 번째는 지나간다).
    """
    if site.get("ledger_drop") is not None:
        return False
    if not names:
        return False
    keep, gone = [], []
    for b in site.get("ledger") or []:
        (gone if (b.get("dong") or "") in names else keep).append(b)
    if not gone:
        return False
    site["ledger"] = keep
    site["ledger_drop"] = [b.get("dong") for b in gone]
    site.setdefault("notes", []).append(
        "대장 " + " · ".join(f"{b.get('dong')}({b.get('arch_area_m2') or 0:.0f} ㎡)" for b in gone)
        + " 을 사람이 확인해 뺐다 — 위성 판독에 대응하는 동이 없다. 위성이 「없다」를 "
          "확정한 것이 아니고, 뺀 사정은 지번마다 다르다([[hand_writting.py]] `ledger_drop`)")
    if verbose:
        print(f"  [대장] 사람이 확인해 뺀 동 {site['ledger_drop']}")
    return True


def run(address, *, scene=None, ledger_drop=()):
    """주소 한 줄 → site 딕셔너리. 실패해도 예외를 던지지 않고 `error` 를 담아 돌려준다.

    `scene` 을 주면 좌표로 고르지 않고 **그 장면을 쓴다** — 같은 지역을 다른 날 찍은 영상이
    둘 이상이면 좌표만으로는 어느 날짜를 원하는지 알 수 없다(비교분석이 그 경우다).
    지정한 장면이 이 좌표를 담지 못하면 담기는 장면으로 되돌리고 그 사실을 `notes` 에 남긴다.
    """
    k = config.keys()
    site = {"address": address, "point": None, "pnu": None, "parcel": None,
            "scene": None, "ledger": [], "error": None, "notes": []}

    if not k.get("VWORLD_KEY"):
        site["error"] = "VWORLD_KEY 없음 — assets/.env.geodata 확인"
        return site

    pt = _geocode(address, k["VWORLD_KEY"])
    if not pt:
        site["error"] = f"주소를 찾지 못했다: {address}"
        return site
    site["point"] = pt

    # 지적도에서 이 지점의 PNU 를 먼저 얻고, **PNU 로 필지를 직접 조회**한다.
    # 좌표→bbox→포함 판정은 지오코딩 좌표가 필지 밖일 때 엉뚱한 땅을 집는다.
    pnu = geoapi.pnu_at(pt["lon"], pt["lat"], k["VWORLD_KEY"])
    poly = None
    if pnu:
        g, _props = geoapi.parcel_by_pnu(pnu, k["VWORLD_KEY"])
        if g:
            from shapely.geometry import shape as _shape
            poly = _shape(g)
            if not poly.is_valid:
                poly = poly.buffer(0)
    if poly is None:
        pnu, poly, _raw = _parcel_at(pt["lon"], pt["lat"], k["VWORLD_KEY"])
    if pnu and poly is not None:
        site["pnu"] = pnu
        site["parcel"] = poly.__geo_interface__
        site["parcel_m2"] = _parcel_area_m2(poly)
    else:
        site["notes"].append("연속지적도에서 필지를 찾지 못했다 — 야적 탐지 영역과 "
                             "대지경계선 이격을 낼 수 없다")

    if pnu and k.get("DATA_GO_KR_KEY"):
        rows = _ledger(pnu, k["DATA_GO_KR_KEY"])
        if isinstance(rows, dict):
            site["notes"].append(f"건축물대장 조회 실패 — {rows['error']}")
        else:
            site["ledger"] = normalize_ledger(rows)
            apply_ledger_drop(site, ledger_drop)
            if not rows:
                site["notes"].append("이 PNU 에 건축물대장 표제부가 없다")
    elif pnu:
        site["notes"].append("DATA_GO_KR_KEY 없음 — 대장 대조(A3)와 층수 기반 이격(A1) 불가")

    # ── 주변 필지와 그 대장 ──────────────────────────────────────────────
    # 이격(A1)은 **옆 땅 건물까지** 봐야 한다. 연소는 지번 경계를 넘어 옮겨붙고,
    # 층수는 그 건물이 선 필지의 대장에서 와야 한다(대상 필지 대장을 옆 건물에 쓰면
    # 층수가 틀린 채로 6 m/10 m 기준이 갈린다).
    if pnu and k.get("VWORLD_KEY"):
        near = parcels_near(pt["lon"], pt["lat"], k["VWORLD_KEY"], NEIGHBOR_PAD_DEG)
        site["neighbors"] = []
        for npnu, g in near.items():
            if npnu == pnu:
                continue
            rec = {"pnu": npnu, "geometry": g.__geo_interface__, "ledger": []}
            if k.get("DATA_GO_KR_KEY"):
                rows = _ledger(npnu, k["DATA_GO_KR_KEY"])
                if not isinstance(rows, dict):
                    rec["ledger"] = normalize_ledger(rows)
            site["neighbors"].append(rec)
        if not site["neighbors"]:
            site["notes"].append("주변 필지를 찾지 못했다 — 옆 건물 층수를 대장에서 가져올 수 없다")

    want, scene = scene, None
    if want:
        m = config.SCENES.get(want) and config.scene_meta(want)
        if not m:
            site["notes"].append(f"지정한 영상 '{want}' 이 등록되어 있지 않다 — 좌표로 고른다")
        elif not (m["bbox"][0] <= pt["lon"] <= m["bbox"][2]
                  and m["bbox"][1] <= pt["lat"] <= m["bbox"][3]):
            site["notes"].append(f"지정한 영상 '{want}' 이 이 좌표를 담지 않는다 — 좌표로 고른다")
        else:
            scene = want
    scene = scene or config.scene_for(pt["lon"], pt["lat"])
    if scene:
        m = config.scene_meta(scene)
        site["scene"] = {"key": scene, "ko": config.SCENES[scene]["ko"],
                         "bbox": m["bbox"], "res_m": m.get("res_m"),
                         "m2_per_px": m.get("m2_per_px"),
                         "size": [m.get("width"), m.get("height")]}
        # **영상을 고치고 지도는 그대로 둔다** — [[georef.py]]. 필지·대장·footprint 는
        # 조회한 좌표 그대로 나가고, 밀려 있던 영상의 지오레퍼런스를 되돌린다. 그래서 이
        # 아래 어디에서도 필지를 옮기지 않는다(예전에는 여기서 옮겼다).
        from sitecheck.steps import georef, parcel_bias
        georef.apply(site)
        # 영상을 고쳐도 **연속지적도 필지 레이어 자신의 편이**는 남는다(대구 24 m ·
        # 지적불부합). 필지가 그만큼 밀리면 야적 영역과 대지경계선 이격이 남의 땅에서
        # 나오므로 이것만은 옮기고, 옮겼다는 사실을 결과에 적는다 — [[parcel_bias.py]].
        parcel_bias.apply(site)
    else:
        site["notes"].append("이 좌표를 담는 정사영상이 없다 — 건물 폴리곤·야적 탐지를 "
                             "낼 수 없다(현 PoC 영상: 대구·구미·남동공단)")
    return site


def sc_res(site):
    return float((site.get("scene") or {}).get("res_m") or 0.5)


def to_px(T, crs, geom):
    from pyproj import Transformer
    from shapely.ops import transform as sh_transform
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = ~T

    def f(xs, ys):
        e, n = tr.transform(list(xs), list(ys))
        ax, ay = [], []
        for a, b in zip(e, n):
            c = inv * (a, b)
            ax.append(c[0]); ay.append(c[1])
        return ax, ay
    return sh_transform(f, geom)


def to_lonlat(T, crs, geom):
    from pyproj import Transformer
    from shapely.ops import transform as sh_transform
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    def f(xs, ys):
        e = [T.c + T.a * x + T.b * y for x, y in zip(xs, ys)]
        n = [T.f + T.d * x + T.e * y for x, y in zip(xs, ys)]
        lon, lat = tr.transform(e, n)
        return list(lon), list(lat)
    return sh_transform(f, geom)


def _parcel_area_m2(poly):
    """경위도 폴리곤의 실면적(㎡) — UTM-K(EPSG:5179)로 투영해 잰다. **정수로 낸다.**

    종이는 대지면적을 정수로 적는다(`f"{v:,.0f} ㎡"`) — 값 파일에 0.1 자리를 두면 같은 필지가
    종이에서 5,576 ㎡, 파일에서 5,575.5 ㎡ 가 된다. 건물 면적과 같은 눈금이다
    ([[steps/s1_building]] `_area_m2`).
    """
    try:
        from pyproj import Transformer
        from shapely.ops import transform
        tr = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
        return float(round(transform(tr.transform, poly).area))
    except Exception:                                        # noqa: BLE001
        return None
