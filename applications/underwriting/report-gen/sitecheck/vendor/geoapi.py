"""V-World · 건축물대장 API 클라이언트 — **이 폴더만 떼어가도 도는** 자립형.

`geopipe` 를 import 하지 않는다. 폴더를 옮기면 그 경로가 깨지고, 그때 무엇이 없어서
안 도는지 알기 어렵다. 필요한 호출 네 가지만 여기 담는다.

  · geocode          주소 → 좌표
  · reverse_geocode  좌표 → 지번 주소
  · parcels_in_bbox  연속지적도 필지(LP_PA_CBND_BUBUN)
  · fetch_ledger_pnu 건축물대장 표제부(getBrTitleInfo)

응답은 캐시한다 — 같은 필지를 여러 번 조회하는 일이 흔하고, 공공 API 는 느리고 한도가 있다.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VWORLD_ADDR = "https://api.vworld.kr/req/address"
VWORLD_DATA = "https://api.vworld.kr/req/data"
LEDGER_TITLE = ("https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo")
PAGE_SIZE = 1000
LEDGER_ROWS = 100
TIMEOUT = 25
RETRIES = 3

CACHE_DIR = Path(__file__).resolve().parent.parent / "out" / "_cache" / "api"


def _get(url, params, *, what="api", retries=RETRIES):
    q = urllib.parse.urlencode(params, safe=":,()")
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(f"{url}?{q}", timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503):
                time.sleep(1.5 ** i + 0.5)
                continue
            break
        except Exception as e:                                # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 ** i + 0.5)
    raise RuntimeError(f"{what} 실패 — {last}")


class Transient(RuntimeError):
    """조회가 **실패**한 것 — 「없다」와 다르다. 이것은 캐시에 굳히지 않는다."""


def _cached(key, fn):
    """디스크 캐시. **실패는 캐시하지 않는다.**

    예전에는 조회가 끊겨도 그때 모인 빈 목록을 그대로 파일에 썼다. 그러면 API 가 다시
    살아나도 그 지번은 **영원히 「대장 없음」**이 된다 — 캐시는 「없다」와 「못 물어봤다」를
    구분하지 못하기 때문이다(실측 2026-08-26 17:10: 한 번 끊긴 사이에 1,123 지번이 `[]` 로
    박혔고, 그 뒤로 새로 해석한 주소는 옆 필지 대장·층수를 통째로 잃었다).
    """
    f = CACHE_DIR / f"{key}.json"
    if f.exists():
        try:
            return json.loads(f.read_text("utf-8"))
        except Exception:                                     # noqa: BLE001
            pass
    try:
        v = fn()
    except Transient as e:
        # 이번 실행에서는 빈 값으로 지나가되 **파일로 남기지 않는다** — 다음 실행이 다시
        # 물어본다. 조용히 지나가면 「없는 것」과 구분되지 않으므로 그 사실을 찍는다.
        print(f"  [!] {e} — 캐시에 남기지 않는다(다음 실행에서 다시 묻는다)",
              file=sys.stderr)
        return []
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(v, ensure_ascii=False), "utf-8")
    return v


# ── V-World ────────────────────────────────────────────────────────────────
def geocode(address, key, *, addr_type="PARCEL"):
    """주소 → (lon, lat). 실패 시 None."""
    try:
        d = _get(VWORLD_ADDR, {"service": "address", "request": "getCoord", "version": "2.0",
                               "crs": "EPSG:4326", "type": addr_type, "address": address,
                               "format": "json", "key": key}, what="vworld geocode")
    except RuntimeError:
        return None
    r = d.get("response", {})
    if r.get("status") != "OK":
        return None
    p = (r.get("result") or {}).get("point") or {}
    try:
        return float(p["x"]), float(p["y"])
    except (KeyError, TypeError, ValueError):
        return None


def reverse_geocode(lon, lat, key):
    """좌표 → 지번 주소. 임의 지점을 시험할 때 쓴다."""
    try:
        d = _get(VWORLD_ADDR, {"service": "address", "request": "getAddress", "version": "2.0",
                               "crs": "EPSG:4326", "point": f"{lon},{lat}", "format": "json",
                               "type": "PARCEL", "key": key}, what="vworld reverse")
    except RuntimeError:
        return None
    r = d.get("response", {})
    if r.get("status") != "OK":
        return None
    for it in (r.get("result") or []):
        if it.get("text"):
            return it["text"]
    return None


def parcels_in_bbox(bbox, key, *, max_pages=5):
    """연속지적도 필지 → {pnu: geometry(GeoJSON, EPSG:4326)}."""
    minx, miny, maxx, maxy = bbox
    out = {}
    for page in range(1, max_pages + 1):
        try:
            d = _get(VWORLD_DATA, {"service": "data", "request": "GetFeature", "version": "2.0",
                                   "data": "LP_PA_CBND_BUBUN", "key": key, "domain": "localhost",
                                   "geomFilter": f"BOX({minx},{miny},{maxx},{maxy})",
                                   "crs": "EPSG:4326", "format": "json",
                                   "size": PAGE_SIZE, "page": page}, what="vworld 연속지적도")
        except RuntimeError:
            break
        r = d.get("response", {})
        if r.get("status") != "OK":
            break
        feats = (((r.get("result") or {}).get("featureCollection") or {}).get("features")) or []
        for f in feats:
            pnu = (f.get("properties") or {}).get("pnu")
            if pnu and pnu not in out:
                out[pnu] = f.get("geometry")
        if len(feats) < PAGE_SIZE:
            break
    return out


# ── 건축물대장 ──────────────────────────────────────────────────────────────
def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def fetch_ledger_pnu(pnu, data_key, *, use_cache=True):
    """PNU → 건축물대장 표제부 행 목록(원본 필드 그대로).

    PNU 19자리: 시군구(5) 법정동(5) 필지구분(1) 본번(4) 부번(4).
    필지구분 2(산)는 API 의 platGbCd 1 에 대응한다.
    """
    def go():
        sg, bj = pnu[:5], pnu[5:10]
        plat_gb = "1" if pnu[10] == "2" else "0"
        bun, ji = pnu[11:15], pnu[15:19]
        rows, page = [], 1
        while page <= 50:
            try:
                d = _get(LEDGER_TITLE, {"serviceKey": data_key, "sigunguCd": sg, "bjdongCd": bj,
                                        "platGbCd": plat_gb, "bun": bun, "ji": ji,
                                        "numOfRows": LEDGER_ROWS, "pageNo": page,
                                        "_type": "json"}, what=f"대장 {pnu}")
            except RuntimeError as e:
                # **한 줄도 못 받았으면 「없다」가 아니라 「못 물어봤다」다.** 굳혀 두면
                # 그 지번은 다음부터 대장이 없는 땅이 된다(`_cached`). 몇 쪽이라도 받은
                # 뒤 끊긴 것은 받은 만큼 쓴다 — 빈 것과 구분되므로 굳혀도 된다.
                if not rows:
                    raise Transient(f"대장 {pnu} 조회 실패 — {e}") from e
                break
            body = ((d.get("response") or {}).get("body")) or {}
            items = (body.get("items") or {})
            it = items.get("item") if isinstance(items, dict) else None
            if it is None:
                break
            if isinstance(it, dict):
                it = [it]
            for r in it:
                r = dict(r)
                r["pnu"] = pnu
                rows.append(r)
            total = _num(body.get("totalCount")) or 0
            if page * LEDGER_ROWS >= total:
                break
            page += 1
        return rows

    return _cached(f"ledger_{pnu}", go) if use_cache else go()


def parcel_by_pnu(pnu, key):
    """PNU → 필지 geometry(GeoJSON, EPSG:4326) + 속성. 없으면 (None, None).

    **bbox 조회보다 이쪽이 옳다.** 지오코딩 좌표는 필지 밖에 떨어지는 일이 있고
    (실측: 호산동 700-9 에서 620 m 밖), 그때 bbox 조회는 '가장 가까운 필지'로 물러나
    엉뚱한 땅을 집는다. PNU 는 대장·지적이 공유하는 식별자라 모호함이 없다.
    """
    try:
        d = _get(VWORLD_DATA, {"service": "data", "request": "GetFeature", "version": "2.0",
                               "data": "LP_PA_CBND_BUBUN", "key": key, "domain": "localhost",
                               "attrFilter": f"pnu:=:{pnu}", "crs": "EPSG:4326",
                               "format": "json", "size": 10, "page": 1},
                 what=f"vworld 필지 {pnu}")
    except RuntimeError:
        return None, None
    r = d.get("response", {})
    if r.get("status") != "OK":
        return None, None
    feats = (((r.get("result") or {}).get("featureCollection") or {}).get("features")) or []
    if not feats:
        return None, None
    f = feats[0]
    return f.get("geometry"), (f.get("properties") or {})


def pnu_at(lon, lat, key):
    """좌표 → 그 지점의 PNU. 역지오코딩 주소 대신 지적도에서 직접 얻는다."""
    got = parcels_in_bbox([lon - 3e-4, lat - 3e-4, lon + 3e-4, lat + 3e-4], key)
    from shapely.geometry import Point, shape
    p = Point(lon, lat)
    for pnu, g in got.items():
        try:
            if shape(g).contains(p):
                return pnu
        except Exception:                                     # noqa: BLE001
            continue
    return None
