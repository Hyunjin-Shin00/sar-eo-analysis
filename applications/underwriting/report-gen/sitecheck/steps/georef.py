"""영상 지오레퍼런스 보정 — **영상을 고치고 지도는 그대로 둔다.**

방향이 예전과 반대다. 예전에는 영상을 기준으로 두고 들어오는 지도 기하(연속지적도 필지 ·
GIS건물통합정보 footprint)를 전부 영상 쪽으로 끌어왔다. 값은 서로 맞았지만 **내보낸 좌표가
지도 좌표가 아니었다** — 지도에 얹으면 장면마다 2~9 m 어긋났고(실측: 구미 2~5 m · 대구
4~5 m · 남동공단 9 m), 받는 쪽은 result.json 의 네 가지 보정값을 직접 합쳐 되돌려야 했다.

그릴 사람이 프론트라면 그건 성립하지 않는다. 그래서 뒤집었다.

    예전   지도 기하 += S        (영상 프레임으로)   → geojson 이 지도와 어긋남
    지금   영상 지오트랜스폼 -= S (지도 프레임으로)   → geojson 을 그대로 얹으면 맞음

**어느 쪽이 틀렸는지는 처음부터 정해져 있었다.** 연속지적도 필지와 GIS footprint 는 서로 다른
출처인데 같은 방향으로 같이 어긋난다 — 함께 틀릴 수는 없으므로 어긋난 쪽은 영상이다
([[parcel_fit.py]]). 그때도 그렇게 적어 놓고 고치는 대상만 반대로 잡았던 것이다.

재는 방법은 하나도 바꾸지 않았다 — `parcel_fit.estimate_local`(footprint 경계 ↔ 영상 엣지)
과 `align.refine`(모델 폴리곤 ↔ footprint IoU 짝) 그대로다. 그 값을 **지도에 더하는 대신
지오트랜스폼에서 뺀다.** 그래서 추정 숫자는 예전 실행과 같고, 부호만 뒤집혀 들어간다.

    T'  =  T 에서 원점만 (gx, gy) 옮긴 것        (a·b·d·e 는 그대로 — 회전·축척은 손대지 않는다)
    gx, gy  =  -(영상이 실제보다 밀려 있던 양)     장면 좌표계(EPSG:32652) 미터

**평행이동만 한다.** 실측 잔차가 짝당 IoU 0.6~0.9 수준에서 남는 양은 1 m 미만이라 회전·축척을
넣을 근거가 없고, 근거 없는 자유도는 조용히 틀리는 쪽으로만 쓰인다.

무엇이 여전히 지도 쪽에서 움직이는가
------------------------------------
하나뿐이다 — **연속지적도 필지 레이어**([[parcel_bias.py]]). 대구에서 이 레이어는 영상과
footprint 둘 다에 대해 24 m 남쪽에 있다(지적불부합). 영상을 고쳐도 그 24 m 는 남는다.
필지가 그만큼 밀리면 그 위에서 내리는 야적 영역(필지−건물)과 대지경계선 이격이 남의 땅에서
나오므로 옮기고, **옮겼다는 사실과 원본 좌표를 결과에 적는다.**

    python -m sitecheck.steps.georef              장면별 보정량 표
    python -m sitecheck.steps.georef --write      장면마다 georef.json 을 남긴다(타일용)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sitecheck import settings as config

# 정합 추정용 필지 수집 반경(도) — 0.006° ≈ 550 m. 수십 필지가 들어와야 편이가 안정된다.
ALIGN_PAD_DEG = 0.006
LOCAL_WIN_M = 300.0     # 국소 정합 창 반경(m)
SCENE_WIN_PX = 4000     # 장면 평균을 잴 중앙 창 한 변(px) — 전장면은 비싸고 창이 밖으로 난다
MAP_CRS = "EPSG:5179"   # 사람이 읽는 미터 표기 기준(동·북)

_XFORM_CACHE = {}
_TR_CACHE = {}


# ── 원본 ────────────────────────────────────────────────────────────────────
def raw_xform(scene_dir):
    """(지오트랜스폼, crs, 폭, 높이) — **보정 없는 원본 tif 그대로.**

    `meta.bbox` 선형근사를 쓰면 안 된다 — UTM 사각형의 경위도 외접 사각형이라 자오선
    수렴만큼 넓고, 장면 안에서 위치의존 오차가 난다(실측 대구 27 m · 구미 42 m ·
    남동공단 109 m).

    **장면당 한 번만 읽고 캐시한다.** 한 실행에서 수십 번 여는데 큰 tif 를 반복해 열면
    간헐적으로 TIFFReadDirectory 오류가 난다(실측). 값은 파일마다 불변이라 캐시가 안전하다.
    """
    key = str(scene_dir)
    if key in _XFORM_CACHE:
        return _XFORM_CACHE[key]
    import rasterio
    tifs = sorted(Path(scene_dir).glob("*.tif"))
    if not tifs:
        raise FileNotFoundError(f"{scene_dir} 에 원본 tif 가 없다")
    for attempt in range(3):
        try:
            with rasterio.open(tifs[0]) as ds:
                v = (ds.transform, ds.crs, ds.width, ds.height)
            _XFORM_CACHE[key] = v
            return v
        except Exception:                                    # noqa: BLE001
            if attempt == 2:
                raise
    raise RuntimeError("unreachable")


def scene_dir(site):
    sc = site.get("scene") or {}
    if not sc.get("key"):
        raise ValueError("site 에 scene 이 없다 — 영상 좌표를 다룰 수 없다")
    return config.SCENES[sc["key"]]["dir"].resolve()


# ── 보정된 지오트랜스폼 ──────────────────────────────────────────────────────
def xform(site):
    """(보정된 지오트랜스폼, crs, 폭, 높이). **이것을 쓰면 나오는 좌표가 지도 좌표다.**

    보정량이 없으면 원본을 그대로 돌려준다 — 못 잰 것을 0 으로 눙치지 않고, 그 사실은
    `site['georef']['applied']` 와 notes 에 남는다.
    """
    from affine import Affine
    if "vector_shift_px" in site or "vector_shift_extra_m" in site:
        # **조용히 원본을 돌려주면 안 된다.** 그런 site 는 필지가 영상 프레임으로 옮겨져
        # 있어서, 원본 지오트랜스폼으로 그리면 그 편이만큼 어긋난 픽셀에 그린다. 값이
        # 틀렸다고 말하지 않고 틀린 그림을 내는 것이 여기서 가장 위험하다.
        raise ValueError("옛 영상 프레임 site 다 — georef.migrate(site) 를 먼저 부르세요")
    T, crs, W, H = raw_xform(scene_dir(site))
    g = site.get("georef") or {}
    gx, gy = (g.get("origin_shift") or [0.0, 0.0])
    if not gx and not gy:
        return T, crs, W, H
    return Affine(T.a, T.b, T.c + gx, T.d, T.e, T.f + gy), crs, W, H


def _tr(src, dst):
    key = (str(src), str(dst))
    if key not in _TR_CACHE:
        from pyproj import Transformer
        _TR_CACHE[key] = Transformer.from_crs(src, dst, always_xy=True)
    return _TR_CACHE[key]


def _ref_lonlat(site):
    """보정량 단위 변환의 기준점 — 필지 중심(없으면 지오코딩 점).

    미터 편이를 좌표계 사이에 옮길 때 방향이 좌표계마다 조금 다르다(격자북 차이). 장면
    전체를 대표하는 점 하나를 쓰면 그 차이가 0.1 m 수준으로 눌린다.
    """
    if site.get("parcel"):
        from shapely.geometry import shape
        c = shape(site["parcel"]).centroid
        return c.x, c.y
    p = site.get("point") or {}
    return float(p.get("lon") or 127.5), float(p.get("lat") or 36.0)


def _map_delta_to_scene(site, crs, de, dn):
    """EPSG:5179 (동, 북) 미터 편이 → 장면 좌표계 미터 편이.

    두 좌표계 모두 횡축 메르카토르 북향이라 사실상 같은 방향이지만, 격자북이 자오선
    수렴만큼 다르다. 기준점에서 실제로 옮겨 보고 차이를 잰다 — 상수로 근사하지 않는다.
    """
    lon, lat = _ref_lonlat(site)
    f = _tr("EPSG:4326", MAP_CRS)
    b = _tr(MAP_CRS, "EPSG:4326")
    s = _tr("EPSG:4326", crs)
    x, y = f.transform(lon, lat)
    lon2, lat2 = b.transform(x + de, y + dn)
    sx0, sy0 = s.transform(lon, lat)
    sx1, sy1 = s.transform(lon2, lat2)
    return sx1 - sx0, sy1 - sy0


def _scene_delta_to_map(site, crs, gx, gy):
    """장면 좌표계 미터 편이 → EPSG:5179 (동, 북) 미터. 사람이 읽는 표기용."""
    lon, lat = _ref_lonlat(site)
    s = _tr("EPSG:4326", crs)
    si = _tr(crs, "EPSG:4326")
    f = _tr("EPSG:4326", MAP_CRS)
    sx, sy = s.transform(lon, lat)
    lon2, lat2 = si.transform(sx + gx, sy + gy)
    x0, y0 = f.transform(lon, lat)
    x1, y1 = f.transform(lon2, lat2)
    return x1 - x0, y1 - y0


def _blank(applied=False):
    # 잔차·짝수·IoU 는 여기 담지 않는다 — `align.refine` 이 `site` 최상위에 적고
    # (`align_residual_m` · `align_pairs` · `align_iou`) 두 곳에 두면 갈라진다.
    # `frame` 은 담지 않는다 — 프레임을 말하는 곳은 `result.frame` 하나여야 한다.
    # 두 곳에 적으면 한쪽만 고쳐지는 날이 온다.
    return {"applied": bool(applied), "origin_shift": [0.0, 0.0],
            "offset_m": [0.0, 0.0], "px": [0, 0], "steps": [], "src": None}


def _restate(site, crs):
    """`origin_shift` 가 바뀐 뒤 사람이 읽는 값(offset_m · px)을 다시 맞춘다."""
    g = site["georef"]
    gx, gy = g["origin_shift"]
    de, dn = _scene_delta_to_map(site, crs, gx, gy)
    # `offset_m` 은 **원본 영상이 실제보다 얼마나 밀려 있었나**다 — 보정량의 반대 부호다.
    g["offset_m"] = [round(-de, 2), round(-dn, 2)]
    T, _crs, _W, _H = raw_xform(scene_dir(site))
    if T.a and T.e:
        g["px"] = [round(gx / T.a, 2), round(gy / T.e, 2)]
    g["applied"] = bool(abs(gx) > 1e-6 or abs(gy) > 1e-6)
    g["crs"] = str(crs)
    return g


def add_px(site, dx, dy, *, src=""):
    """지도 기하를 (dx, dy) px 옮겨야 영상과 맞는다 → **영상을 그만큼 반대로** 옮긴다.

    `parcel_fit` 이 내는 값이 이 모양이다(픽셀 정수). 축척·회전은 지오트랜스폼에서 읽어
    쓴다 — 해상도를 상수로 박으면 다른 영상에서 조용히 틀린다.
    """
    T, crs, _W, _H = raw_xform(scene_dir(site))
    gx = -(T.a * dx + T.b * dy)
    gy = -(T.d * dx + T.e * dy)
    g = site.setdefault("georef", _blank())
    g["origin_shift"] = [g["origin_shift"][0] + gx, g["origin_shift"][1] + gy]
    de, dn = _scene_delta_to_map(site, crs, gx, gy)
    g["steps"].append({"src": src or "px", "px": [dx, dy],
                       "east_m": round(-de, 2), "north_m": round(-dn, 2)})
    if src:
        g["src"] = src if not g.get("src") else f"{g['src']} + {src}"
    return _restate(site, crs)


def add_m(site, de, dn, *, src=""):
    """지도 기하를 (동 de, 북 dn) m 옮겨야 영상과 맞는다 → 영상을 그만큼 반대로 옮긴다.

    `align.refine` 이 내는 잔차가 이 모양이다(EPSG:5179 미터).
    """
    _T, crs, _W, _H = raw_xform(scene_dir(site))
    sx, sy = _map_delta_to_scene(site, crs, de, dn)
    g = site.setdefault("georef", _blank())
    g["origin_shift"] = [g["origin_shift"][0] - sx, g["origin_shift"][1] - sy]
    # **부호는 `add_px` 와 같은 뜻으로 적는다** — "원본 영상이 실제보다 얼마나 밀려
    # 있었나". 인자 `de`·`dn` 이 이미 그 뜻이므로(지도를 그만큼 옮겨야 영상과 맞는다)
    # 여기서 뒤집으면 두 단계의 표기가 엇갈린다.
    g["steps"].append({"src": src or "m", "east_m": round(de, 2), "north_m": round(dn, 2)})
    if src:
        g["src"] = src if not g.get("src") else f"{g['src']} + {src}"
    return _restate(site, crs)


# ── 1차 추정(엣지 정합) ──────────────────────────────────────────────────────
def _footprints_near(polys):
    """필지들의 bbox 안 GIS건물통합정보 footprint — **원본 좌표 그대로**(기준선이다)."""
    try:
        import geopandas as gpd
        from shapely.ops import unary_union
        U = unary_union(polys)
        g = gpd.read_file(config.GIS_BUILDINGS, layer="buildings", bbox=U.bounds)
        return [r.geometry for r in g.itertuples() if r.geometry is not None]
    except Exception:                                        # noqa: BLE001
        return []


def apply(site, *, force=False, verbose=False):
    """영상 편이를 재서 `site['georef']` 에 담는다. 쟀으면 True.

    **국소 우선.** 정사보정 오차는 지형 기복을 타므로 장면 안에서 위치에 따라 변한다(실측:
    대구 장면 평균 +8 px 를 적용해도 호산동 필지는 수십 m 밀려 있었다). 그래서 필지 주변
    창에서 먼저 재고, 실패할 때만 장면 값으로 물러난다. 순서가 중요하다 — 장면 값은 처음
    보는 영상에서 엣지맵을 장면 전체에 만들어야 해서 비싸다(창원 217 Mpx 에서 50 s).
    """
    if site.get("georef") and not force:
        return False
    site.setdefault("notes", [])
    if not site.get("scene"):
        return False
    from shapely.geometry import shape
    from sitecheck.steps import parcel_fit
    from sitecheck.steps.s0_locate import parcels_near, to_px

    sk = site["scene"]["key"]
    site["georef"] = _blank()
    try:
        T, crs, _W, _H = raw_xform(scene_dir(site))
        targets = []
        if site.get("parcel"):
            targets.append(shape(site["parcel"]))
        for n in site.get("neighbors") or []:
            targets.append(shape(n["geometry"]))
        if not targets:
            site["notes"].append("필지가 없어 영상 편이를 잴 기준이 없다 — 영상 좌표를 "
                                 "보정하지 않았다. 결과 좌표가 지도와 어긋날 수 있다")
            return False
        key = config.keys().get("VWORLD_KEY")
        wide = list(parcels_near(site["point"]["lon"], site["point"]["lat"],
                                key, ALIGN_PAD_DEG).values()) if key else []
        fps = _footprints_near(wide or targets)
        fpx = [to_px(T, crs, g) for g in fps]

        dx = dy = 0
        src = None
        if site.get("parcel"):
            tgt = to_px(T, crs, shape(site["parcel"]))
            m = LOCAL_WIN_M / float(site["scene"].get("res_m") or 0.5)
            b = tgt.bounds
            loc = parcel_fit.estimate_local(
                sk, fpx, (b[0] - m, b[1] - m, b[2] + m, b[3] + m))
            if loc:
                dx, dy = loc[0], loc[1]
                src = f"국소(footprint {loc[3]}동 · 이득 {loc[2]:.2f})"
        if src is None:
            dx, dy = parcel_fit.shift_for(sk, fpx)
            src = "장면"
        if dx == 0 and dy == 0:
            # **조용히 넘어가면 안 된다.** 보정 0 은 '편이가 없다'가 아니라 대개 '재지
            # 못했다'다 — 주변 footprint 가 모자라거나 정합 신호가 약한 경우. 이때 영상에서
            # 나온 좌표는 밀린 채로 나가므로 결과에 남긴다.
            site["notes"].append("영상 지오레퍼런스 편이를 재지 못했다 — 주변 "
                                 "GIS건물통합정보 footprint 가 모자라거나 정합 신호가 약하다. "
                                 "건물·야적 좌표가 지도와 몇 m 어긋난 채로 나올 수 있다")
            return False
        g = add_px(site, dx, dy, src=src)
        e, n = g["offset_m"]
        site["notes"].append(
            f"영상 지오레퍼런스를 보정했다 — 원본이 실제보다 ({e:+.1f},{n:+.1f}) m "
            f"(동,북) 밀려 있어 영상 좌표를 그만큼 되돌렸다 · 기준 {src}. "
            f"필지·대장·footprint 는 손대지 않았다")
        if verbose:
            print(f"  [영상보정] ({e:+.1f},{n:+.1f}) m · {src}")
        return True
    except Exception as e:                                   # noqa: BLE001
        site["notes"].append(f"영상 지오레퍼런스 보정 실패 — {type(e).__name__}: {e}")
        return False


# ── 변환 (여기를 지나면 좌표는 지도 좌표다) ──────────────────────────────────
def px_rings_to_ll(site, rings_px, *, center=True):
    """영상 픽셀 폴리곤 목록 → 경위도 링 목록. 보정된 지오트랜스폼을 쓴다.

    `center` 는 픽셀 중심(+0.5)을 쓴다는 뜻이다 — 모델이 내는 좌표는 픽셀 격자의 칸
    번호라 모서리로 읽으면 반 픽셀(0.25 m) 치우친다.
    """
    T, crs, _W, _H = xform(site)
    tr = _tr(crs, "EPSG:4326")
    h = 0.5 if center else 0.0
    out = []
    for ring in rings_px:
        e = [T.c + T.a * (x + h) + T.b * (y + h) for x, y in ring]
        n = [T.f + T.d * (x + h) + T.e * (y + h) for x, y in ring]
        lon, lat = tr.transform(e, n)
        out.append([[float(a), float(b)] for a, b in zip(lon, lat)])
    return out


def ll_to_px(site, geom):
    """경위도 geometry → 영상 픽셀 geometry. 보정된 지오트랜스폼의 역이다.

    지도 기하를 영상 위에 그리거나(그림) 영상을 읽을 창을 정할 때(야적 타일) 쓴다.
    """
    from shapely.ops import transform as sh_transform
    T, crs, _W, _H = xform(site)
    tr = _tr("EPSG:4326", crs)
    inv = ~T

    def f(xs, ys):
        e, n = tr.transform(list(xs), list(ys))
        ax, ay = [], []
        for a, b in zip(e, n):
            c = inv * (a, b)
            ax.append(c[0]); ay.append(c[1])
        return ax, ay
    return sh_transform(f, geom)


def px_box_to_ll(site, x0, y0, x1, y1):
    """영상 픽셀 bbox → 경위도 Polygon."""
    from shapely.geometry import Polygon
    T, crs, _W, _H = xform(site)
    tr = _tr(crs, "EPSG:4326")
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    e = [T.c + T.a * x + T.b * y for x, y in corners]
    n = [T.f + T.d * x + T.e * y for x, y in corners]
    lon, lat = tr.transform(e, n)
    return Polygon(list(zip(lon, lat)))


def raw_ll_to_map(site, geom):
    """**원본 지오트랜스폼으로 만든** 경위도 기하 → 지도 좌표.

    옛 캐시를 위한 것이다. 야적 판독 결과(`_yard.json`)는 픽셀 상자를 원본 지오트랜스폼으로
    되돌려 담았으므로 보정 이전 좌표다. VLM 을 다시 부르는 것은 돈이 드니(판독 대상은 영상과
    건물 밖 공지라 값 자체는 그대로 유효하다) 좌표만 옮긴다.

    원본으로 픽셀에 되돌린 뒤 보정된 것으로 다시 내보낸다 — 결과는 평행이동이지만, 이렇게
    쓰면 보정량을 다시 계산해 더하는 곳이 생기지 않는다.
    """
    from shapely.ops import transform as sh_transform
    Traw, crs, _W, _H = raw_xform(scene_dir(site))
    Tfix, _crs, _W2, _H2 = xform(site)
    if (Traw.c, Traw.f) == (Tfix.c, Tfix.f):
        return geom
    tr = _tr("EPSG:4326", crs)
    tri = _tr(crs, "EPSG:4326")
    inv = ~Traw

    def f(xs, ys):
        e, n = tr.transform(list(xs), list(ys))
        ex, ny = [], []
        for a, b in zip(e, n):
            c = inv * (a, b)                       # 원본 기준 픽셀
            ex.append(Tfix.c + Tfix.a * c[0] + Tfix.b * c[1])
            ny.append(Tfix.f + Tfix.d * c[0] + Tfix.e * c[1])
        lon, lat = tri.transform(ex, ny)
        return list(lon), list(lat)
    return sh_transform(f, geom)


def migrate_fc(site, fc):
    """옛 프레임으로 저장된 FeatureCollection 의 좌표를 지도 프레임으로. 옮긴 건수를 돌려준다."""
    from shapely.geometry import shape
    n = 0
    for ft in fc.get("features") or []:
        if not ft.get("geometry"):
            continue
        try:
            ft["geometry"] = raw_ll_to_map(site, shape(ft["geometry"])).__geo_interface__
            n += 1
        except Exception:                                    # noqa: BLE001
            pass
    fc["frame"] = "map"          # FeatureCollection 은 파일로 나가므로 여기엔 적는다
    return n


def scene_bbox(site):
    """보정된 영상의 경위도 외접 사각형 — `site.scene.bbox` 로 나간다.

    `meta.json` 의 bbox 는 **원본** 영상 것이라 보정한 만큼(4~9 m) 어긋난다. 출력 안의 다른
    모든 좌표가 지도 좌표인데 이것만 영상 좌표면, 나중에 이 값으로 영상 위치를 잡는 쪽이
    조용히 그만큼 틀린다. 읽는 코드는 전부 `settings.scene_meta` 의 원본을 쓰므로(장면 고르기)
    여기서 고쳐도 판정에는 영향이 없다.
    """
    T, crs, W, H = xform(site)
    tr = _tr(crs, "EPSG:4326")
    xs = [T.c, T.c + T.a * W]
    ys = [T.f, T.f + T.e * H]
    lon, lat = tr.transform([xs[0], xs[1], xs[0], xs[1]], [ys[0], ys[0], ys[1], ys[1]])
    return [min(lon), min(lat), max(lon), max(lat)]


def refresh_scene_bbox(site):
    """`site.scene.bbox` 를 지금의 보정 상태로 다시 쓴다. 고쳤으면 True.

    **결과를 담을 때 부른다**([[schema.envelope]]). 주소 해석 시점에 한 번 쓰면 2차
    정합(`align.refine`)이 보정을 더 손질한 뒤의 값과 어긋난다.
    """
    sc = site.get("scene")
    if not sc:
        return False
    try:
        sc["bbox"] = [round(v, 9) for v in scene_bbox(site)]
        return True
    except Exception:                                        # noqa: BLE001
        return False


# ── 옛 결과 읽기 ────────────────────────────────────────────────────────────
def migrate(site, *, verbose=False):
    """**영상 프레임으로 저장된 옛 site** 를 지도 프레임으로 되돌린다. 고쳤으면 True.

    옛 형식은 필지·인접필지를 `vector_shift_px` + `vector_shift_extra_m` 만큼 영상 쪽으로
    옮겨 담았다. 그 두 값을 필지에서 빼고 같은 양을 영상 보정으로 옮겨 놓으면 값의 관계는
    그대로이고 좌표만 지도 프레임이 된다. **V-World·대장 조회 결과를 버리지 않으려고**
    다시 해석하지 않는다(인접 필지 대장은 주소당 수십 건이다).

    `parcel_bias_m` · `parcel_fix_m` 은 그대로 둔다 — 그것은 연속지적도 레이어 자신의
    편이라 프레임과 무관한 상대 이동이고, 새 방식에서도 유지하는 보정이다.
    """
    px = site.pop("vector_shift_px", None)
    ex = site.pop("vector_shift_extra_m", None)
    src = site.pop("vector_shift_src", None)
    if px is None and ex is None:
        return False
    if not site.get("scene"):
        return False
    from shapely.affinity import translate
    from shapely.geometry import shape
    from shapely.ops import transform as sh_transform
    from sitecheck.steps.s0_locate import _parcel_area_m2

    T, crs, _W, _H = raw_xform(scene_dir(site))
    dx, dy = (px or [0, 0])
    de, dn = (ex or [0.0, 0.0])
    site["georef"] = _blank()
    if dx or dy:
        add_px(site, dx, dy, src=(src or "옛 결과").split(" + ")[0])
    if abs(de) > 1e-6 or abs(dn) > 1e-6:
        add_m(site, de, dn, src="옛 결과의 모델정합")

    # 필지에서 같은 양을 뺀다 — 픽셀 편이는 픽셀에서, 미터 잔차는 미터에서(옛 코드가 그
    # 순서로 더했다. 합쳐서 한 번에 빼면 0.25 m 가 어긋난다).
    fwd = _tr("EPSG:4326", MAP_CRS)
    back = _tr(MAP_CRS, "EPSG:4326")
    tr_s = _tr("EPSG:4326", crs)
    tr_si = _tr(crs, "EPSG:4326")

    def unshift(g):
        if abs(de) > 1e-6 or abs(dn) > 1e-6:
            g = sh_transform(back.transform,
                             translate(sh_transform(fwd.transform, g), -de, -dn))
        if dx or dy:
            def to_px(xs, ys):
                e, n = tr_s.transform(list(xs), list(ys))
                inv = ~T
                ax, ay = [], []
                for a, b in zip(e, n):
                    c = inv * (a, b)
                    ax.append(c[0]); ay.append(c[1])
                return ax, ay

            def to_ll(xs, ys):
                e = [T.c + T.a * x + T.b * y for x, y in zip(xs, ys)]
                n = [T.f + T.d * x + T.e * y for x, y in zip(xs, ys)]
                lon, lat = tr_si.transform(e, n)
                return list(lon), list(lat)
            g = sh_transform(to_ll, translate(sh_transform(to_px, g), -dx, -dy))
        return g

    if site.get("parcel"):
        g = unshift(shape(site["parcel"]))
        site["parcel"] = g.__geo_interface__
        site["parcel_m2"] = _parcel_area_m2(g)
    for nb in site.get("neighbors") or []:
        try:
            nb["geometry"] = unshift(shape(nb["geometry"])).__geo_interface__
        except Exception:                                    # noqa: BLE001
            pass
    site.setdefault("notes", []).append(
        "옛 결과(영상 프레임)를 지도 프레임으로 되돌렸다 — 필지에 얹혀 있던 영상 편이 "
        f"({dx:+d},{dy:+d}) px · ({de:+.2f},{dn:+.2f}) m 를 빼고 같은 양을 영상 "
        "지오레퍼런스 보정으로 옮겼다")
    if verbose:
        print(f"  [프레임이관] 필지에서 ({dx:+d},{dy:+d}) px · ({de:+.2f},{dn:+.2f}) m 를 뺐다")
    return True


# ── 장면 단위 보정값(타일·QGIS 용) ───────────────────────────────────────────
def scene_offset(scene_key, *, verbose=False):
    """장면 하나의 **평균** 편이(px) — 영상 자체를 고쳐 내보낼 때 쓴다.

    실제 판정에는 주소마다 국소로 잰 값이 쓰인다(위 `apply`). 이것은 영상 타일을 프론트에
    띄울 때처럼 **한 장면에 하나의 지오트랜스폼**이 필요한 자리를 위한 값이다. 국소 값과
    몇 m 다를 수 있고, 그 차이는 정사보정 오차가 장면 안에서 위치를 타기 때문이다.
    """
    from sitecheck.steps import parcel_fit
    if scene_key in parcel_fit.VERIFIED:
        return parcel_fit.VERIFIED[scene_key]
    fpx = _scene_footprints_px(scene_key)
    if not fpx:
        raise RuntimeError(f"{scene_key} 장면 범위의 GIS건물통합정보 footprint 를 얻지 못했다 "
                           f"— 장면 평균 편이를 잴 수 없다")
    # **장면 중앙 창에서 잰다.** `parcel_fit.estimate`(전장면)는 footprint 가 장면을 거의
    # 덮으면 후보 창이 영상 밖으로 나가 하나도 못 재고 (0,0) 을 돌려준다(실측 daegu2 ·
    # footprint 4,019동인데 점수 0). 전장면 엣지맵도 비싸다(217 Mpx 에서 50 s · 4.7 GB).
    T, _crs, W, H = raw_xform(config.SCENES[scene_key]["dir"].resolve())
    half = min(W, H, SCENE_WIN_PX) // 2
    cx, cy = W // 2, H // 2
    loc = parcel_fit.estimate_local(scene_key, fpx,
                                    (cx - half, cy - half, cx + half, cy + half),
                                    min_rings=30, verbose=verbose)
    if loc:
        return loc[0], loc[1]
    raise RuntimeError(f"{scene_key} 장면 평균 편이를 재지 못했다 — 중앙 창에서 정합 신호가 "
                       f"약하다(footprint {len(fpx)}동). 주소별 국소 보정은 따로 돈다")


def _scene_footprints_px(scene_key):
    """장면 bbox 안 footprint → **원본 기준 픽셀**. 장면 평균 편이 추정의 표본이다."""
    import geopandas as gpd
    from shapely.ops import transform as sh_transform
    d = config.SCENES[scene_key]["dir"].resolve()
    T, crs, _W, _H = raw_xform(d)
    m = config.scene_meta(scene_key) or {}
    if not m.get("bbox"):
        return []
    try:
        g = gpd.read_file(config.GIS_BUILDINGS, layer="buildings", bbox=tuple(m["bbox"]))
    except Exception:                                        # noqa: BLE001
        return []
    if g.empty:
        return []
    if g.crs and g.crs.to_epsg() != 4326:
        g = g.to_crs(4326)
    tr = _tr("EPSG:4326", crs)
    inv = ~T

    def f(xs, ys):
        e, n = tr.transform(list(xs), list(ys))
        ax, ay = [], []
        for a, b in zip(e, n):
            c = inv * (a, b)
            ax.append(c[0]); ay.append(c[1])
        return ax, ay
    return [sh_transform(f, x) for x in g.geometry if x is not None]


def write_scene_georef(scene_key, *, verbose=False):
    """`assets/scenes/<장면>/georef.json` — 보정된 지오트랜스폼을 파일로 남긴다.

    영상을 배경으로 띄우려면 **영상도 같이 옮겨야** 한다. geojson 만 고치고 타일을 두면
    우리 결과가 우리 영상과 어긋난다(고객 배경지도와는 맞고). 그 보정을 GDAL 로 한 번에
    넣을 수 있게 원본·보정 지오트랜스폼과 명령을 함께 적는다.
    """
    from affine import Affine
    d = config.SCENES[scene_key]["dir"].resolve()
    T, crs, W, H = raw_xform(d)
    dx, dy = scene_offset(scene_key, verbose=verbose)
    gx = -(T.a * dx + T.b * dy)
    gy = -(T.d * dx + T.e * dy)
    T2 = Affine(T.a, T.b, T.c + gx, T.d, T.e, T.f + gy)
    ulx, uly = T2.c, T2.f
    lrx, lry = T2.c + T2.a * W, T2.f + T2.e * H
    tif = sorted(Path(d).glob("*.tif"))
    out = {
        "scene": scene_key, "crs": str(crs), "width": W, "height": H,
        "shift_px": [dx, dy],
        "origin_shift": [round(gx, 3), round(gy, 3)],
        "transform_raw": [T.a, T.b, T.c, T.d, T.e, T.f],
        "transform_fixed": [T2.a, T2.b, T2.c, T2.d, T2.e, T2.f],
        "gdal_edit": (f"gdal_edit.py -a_ullr {ulx:.3f} {uly:.3f} {lrx:.3f} {lry:.3f} "
                      f"{tif[0].name if tif else '<scene>.tif'}"),
        "note": ("원본 영상이 실제보다 밀려 있던 양을 되돌린 지오트랜스폼이다. 결과 "
                 "geojson 은 이미 이 기준(지도 좌표)으로 나온다 — 영상 타일을 함께 띄울 때만 "
                 "이 값을 영상에 넣으면 된다. 판정에는 주소별 국소 보정이 쓰이므로 이 장면 "
                 "평균과 몇 m 다를 수 있다."),
    }
    (d / "georef.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    return d / "georef.json"


def _report(write=False):
    print(f"{'장면':10s} {'편이(px)':>10s} {'원점이동(m)':>16s}  파일")
    print("─" * 74)
    for k in config.SCENES:
        try:
            dx, dy = scene_offset(k)
            T, _crs, _W, _H = raw_xform(config.SCENES[k]["dir"].resolve())
            gx = -(T.a * dx + T.b * dy)
            gy = -(T.d * dx + T.e * dy)
            f = write_scene_georef(k) if write else None
            print(f"{k:10s} {('(%+d,%+d)' % (dx, dy)):>10s} "
                  f"{('(%+.1f,%+.1f)' % (gx, gy)):>16s}  {f.name if f else '—'}")
        except Exception as e:                                # noqa: BLE001
            print(f"{k:10s} {'—':>10s} {'—':>16s}  {type(e).__name__}: {e}")


if __name__ == "__main__":
    _report(write="--write" in sys.argv[1:])
