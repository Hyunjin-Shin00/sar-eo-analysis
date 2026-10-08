"""외부 공공데이터 — **활용신청이 끝난 것만** 여기 있다.

리포트 5·6면(소방 접근성 · 자연재해·지역 위험)이 쓰는 값을 만든다. 두 갈래다.

  · 받은 것   `소방청_전국소방서 좌표현황`(15138232) · `소방청_화재발생 정보`(15044003)
  · 못 받은 것 `MISSING` — 항목마다 **무엇을 신청해야 열리는지** 적어 둔다

**못 받은 칸을 리포트에서 지우지 않는 이유.** 지우면 그 항목을 안 보는 것과 구별되지
않는다(특건자료가 대지면적 `0.00` 을 그렇게 남긴다). 칸은 그대로 두고 「미확보」와 사유를
찍으면, 같은 종이가 받는 쪽에는 커버리지 고지가 되고 우리에게는 취득 잔여 목록이 된다.
사유 문구는 `seglab/reports/특건_외부데이터_취득절차.md` 의 항목 번호와 같은 말을 쓴다.

**odcloud 를 쓴다.** 두 자료는 data.go.kr 의 *파일데이터* 인데, 활용신청을 하면 같은 내용이
`api.odcloud.kr/api/<pk>/v1/uddi:<...>` 로 열린다. 파일을 손으로 받아 두면 갱신 시점이
사람 기억에 남고, 어느 판을 썼는지 리포트에서 되짚을 수 없다 — API 로 받고 **받은 날짜와
행 수를 캐시에 함께 적는다**.

캐시는 `data/ext/` 다. 물건 1건마다 API 를 때리지 않는다 — 소방서는 1,216행뿐이고 화재는
19만행이라 한 번 받아 두고 로컬에서 잰다. 다시 받으려면 `refresh=True` 또는

    python -m sitecheck.ext --refresh
"""
from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from sitecheck import settings as config

EXT = config.HERE / "data" / "ext"
TIMEOUT = 180
RETRIES = 4

# ── 자료 등록부 ─────────────────────────────────────────────────────────────
# `uddi` 는 data.go.kr 의 파일데이터마다 붙는 판 식별자다. **파일이 새 판으로 갈리면 uddi 가
# 바뀐다** — 그때 404 가 나므로 여기 값을 갱신해야 한다(자료 페이지 「오픈 API」 탭에 있다).
ODCLOUD = {
    "fire_station": {
        "pk": "15138232",
        "uddi": "uddi:da0c6c93-f05a-453d-849f-e4c3697222e3",
        "name": "소방청_전국소방서 좌표현황(XY좌표)",
        "as_of": "2024-09-01",          # 파일명 기준일. 갱신주기가 「수시(1회성)」라 낡을 수 있다
        "per_page": 1500,               # 1,216행 — 한 번에 다 온다
    },
    "fire_incident": {
        "pk": "15044003",
        "uddi": "uddi:5bb0f25d-61e9-4c45-8c9a-cad5f129c6d0",
        "name": "소방청_화재발생 정보",
        "as_of": "2024-12-31",
        # perPage 10000 은 3쪽부터 빈 응답(`{"code":0,"msg":"정상"}`)을 준다 — 오류도 아니고
        # 데이터도 없다. 5000 은 끝까지 온다(실측). 조용히 20,000행에서 끊기는 것이 가장 나쁘다.
        "per_page": 5000,
    },
}

# ── odcloud 클라이언트 ──────────────────────────────────────────────────────
def _key():
    k = config.keys().get("DATA_GO_KR_KEY", "")
    if not k:
        raise RuntimeError("DATA_GO_KR_KEY 없음 — assets/.env.geodata 확인")
    return k


def _get_json(url, params, *, what="api", retries=RETRIES):
    """공공데이터포털 표준 GET — JSON 을 돌려준다. 실패는 재시도 후 예외."""
    q = urllib.parse.urlencode(params)
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(f"{url}?{q}", timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code not in (429, 500, 502, 503):
                break
        except Exception as e:                                     # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 ** i + 0.5)
    raise RuntimeError(f"{what} 실패 — {last}")


def _page(spec, key, page):
    url = f"https://api.odcloud.kr/api/{spec['pk']}/v1/{spec['uddi']}"
    q = urllib.parse.urlencode({"serviceKey": key, "page": page,
                                "perPage": spec["per_page"]})
    last = None
    for i in range(RETRIES):
        try:
            with urllib.request.urlopen(f"{url}?{q}", timeout=TIMEOUT) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            if "data" in d:
                return d
            # 활용신청 전에는 여기로 온다 — 200 에 본문만 다르다.
            last = f"data 없음: {str(d)[:120]}"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code not in (429, 500, 502, 503):
                break
        except Exception as e:                                     # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 ** i + 0.5)
    raise RuntimeError(f"{spec['name']} {page}쪽 실패 — {last}")


def fetch(which, *, key=None, progress=False):
    """등록부의 자료 전량을 dict 목록으로 받는다."""
    spec, key = ODCLOUD[which], key or _key()
    rows, page = [], 1
    while True:
        d = _page(spec, key, page)
        rows += d["data"]
        tot = d.get("totalCount") or len(rows)
        if progress:
            print(f"  {spec['name']} {len(rows):,}/{tot:,}")
        if not d["data"] or len(rows) >= tot:
            return rows, tot
        page += 1


def _write_csv(path, header, rows, meta):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    (path.parent / f"_{path.stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")


def _read_csv(path):
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _meta(path):
    f = path.parent / f"_{path.stem}.json"
    return json.loads(f.read_text("utf-8")) if f.exists() else {}


# ── 소방서 · 119안전센터 ────────────────────────────────────────────────────
STATIONS = EXT / "fire" / "소방서좌표.csv"


def stations(*, refresh=False):
    """[(이름, 유형, 본부, 주소, 전화, lat, lon)]. 캐시가 있으면 그것을 읽는다.

    **원본의 `X좌표` 가 위도이고 `Y좌표` 가 경도다**(실측: X 33.2~38.4 · Y 124.7~130.9).
    이름을 그대로 믿고 넣으면 전국이 중국 앞바다로 간다 — 여기서 바로잡아 캐시에 넣는다.
    """
    if refresh or not STATIONS.exists():
        raw, tot = fetch("fire_station")
        out = []
        for r in raw:
            try:
                lat, lon = float(r["X좌표"]), float(r["Y좌표"])
            except (TypeError, ValueError, KeyError):
                continue
            if not (32 < lat < 40 and 123 < lon < 133):      # 뒤집힌 행이 섞이면 여기서 걸린다
                continue
            out.append([r.get("소방서 및 안전센터명", ""), r.get("유형", ""),
                        r.get("상위 본부명", ""), r.get("주소", ""),
                        r.get("전화번호", ""), f"{lat:.7f}", f"{lon:.7f}"])
        _write_csv(STATIONS, ["이름", "유형", "본부", "주소", "전화", "위도", "경도"], out,
                   {"source": ODCLOUD["fire_station"]["name"],
                    "pk": ODCLOUD["fire_station"]["pk"],
                    "as_of": ODCLOUD["fire_station"]["as_of"],
                    "fetched": time.strftime("%Y-%m-%d"),
                    "rows": len(out), "total": tot,
                    "note": "원본 X좌표=위도 · Y좌표=경도 (컬럼명이 뒤바뀌어 있어 바로잡음)"})
    return _read_csv(STATIONS), _meta(STATIONS)


def _geod():
    from pyproj import Geod
    return Geod(ellps="WGS84")


DIR16 = ("북", "북북동", "북동", "동북동", "동", "동남동", "남동", "남남동",
         "남", "남남서", "남서", "서남서", "서", "서서북", "북서", "북북서")


def bearing_ko(az):
    return DIR16[int((az % 360) / 22.5 + 0.5) % 16]


RADII_M = (3000, 5000, 10000)


def fire_access(lat, lon, *, refresh=False, n_center=3):
    """소방 접근성 — 최근접 소방서 1곳 · 가까운 119안전센터 몇 곳 · 반경 안 관서 수.

    거리는 **직선(측지선)** 이다. 주행거리는 도로망이 없어 아직 못 낸다.

    「관할」이 아니라 「최근접」으로 적는다 — 관할구역 경계 데이터가 없어 이 좌표가 어느
    소방서 관할인지는 알 수 없다. 대개 최근접과 관할이 같지만 늘 같지는 않다.

    안전센터를 여럿 내는 이유는 **초기 출동을 안전센터가 하기 때문**이다. 소방서 한 곳까지의
    거리만 적으면 주변에 센터가 셋인 곳과 하나인 곳이 같은 값으로 보인다. 반경 안 개소 수가
    그 차이를 한 줄로 보여준다 — 특건 서식에는 없는 칸이다.
    """
    rows, meta = stations(refresh=refresh)
    g, all_d = _geod(), []
    for r in rows:
        az, _, d = g.inv(lon, lat, float(r["경도"]), float(r["위도"]))
        all_d.append({"name": r["이름"], "type": r["유형"] or "기타", "hq": r["본부"],
                      # **정수 m 로 담는다** — 나눗셈 그대로 두면 값 파일에
                      # `1226.9994424001545` 가 남는다. 종이는 km 로 한 자리만 적으므로
                      # (`_km`) 이 자리에서 뜻을 갖는 것은 m 단위까지다.
                      "addr": r["주소"], "tel": r["전화"], "dist_m": float(round(d)),
                      "dir": bearing_ko(az),
                      "lat": float(r["위도"]), "lon": float(r["경도"])})
    all_d.sort(key=lambda q: q["dist_m"])
    within = {m: sum(1 for q in all_d if q["dist_m"] <= m) for m in RADII_M}
    return {"station": next((q for q in all_d if q["type"] == "소방서"), None),
            "centers": [q for q in all_d if q["type"] == "119안전센터"][:n_center],
            "within": within, "nearest": all_d[0] if all_d else None}, meta


# ── 지역 화재 실적 — **리포트에서 쓰지 않는다** ────────────────────────────
# 뺀 이유: 시군구 전체의 절대 건수라 이 물건의 인수 조건을 바꾸지 못한다(「달서구 224건 ·
# 전국 27위」를 읽고 심사역이 할 일이 없다). 분모(해당 용도 시설 동수)가 붙어 **동당 연
# 발생확률**이 되면 요율과 같은 차원이 되므로 그때 되살린다. 취득은 이미 열려 있어(활용신청
# 완료) 캐시만 다시 만들면 된다 — `fire_stats(refresh=True)`.─
FIRESTAT = EXT / "hazard" / "화재발생_집계.csv"


def fire_stats(*, refresh=False):
    """(시도, 시군구, 장소대분류, 장소중분류, 발화요인) 별 건수·피해 집계.

    19만행 원본을 그대로 두지 않는다 — 리포트가 쓰는 것은 이 다섯 칸의 집계뿐이고, 원본은
    40 MB 라 저장소에 넣을 것이 아니다. 기간·총행수는 옆 `_화재발생_집계.json` 에 남긴다.
    발화요인을 키에 넣어 집계가 7,635 → 25,698 행(2 MB)이 됐다 — 「무엇 때문에 났나」를
    한 줄 낼 수 있게 되는 값이라 그만큼은 낸다.

    `재산피해소계` 는 **천원 단위**다(원본 최대 23,745,538 = 237억). 여기서는 그대로 두고
    표시할 때 만원으로 바꾼다.
    """
    if refresh or not FIRESTAT.exists():
        raw, tot = fetch("fire_incident", progress=True)
        agg, years = {}, set()
        for r in raw:
            k = (r.get("시도") or "", r.get("시군구") or "",
                 r.get("장소대분류") or "", r.get("장소중분류") or "",
                 r.get("발화요인대분류") or "")
            a = agg.setdefault(k, [0, 0, 0, 0])
            a[0] += 1
            a[1] += r.get("재산피해소계") or 0
            a[2] += r.get("사망") or 0
            a[3] += r.get("부상") or 0
            d = (r.get("화재발생년원일") or "")[:4]
            if d.isdigit():
                years.add(d)
        rows = [list(k) + v for k, v in sorted(agg.items())]
        _write_csv(FIRESTAT,
                   ["시도", "시군구", "장소대분류", "장소중분류", "발화요인",
                    "건수", "재산피해_천원", "사망", "부상"], rows,
                   {"source": ODCLOUD["fire_incident"]["name"],
                    "pk": ODCLOUD["fire_incident"]["pk"],
                    "as_of": ODCLOUD["fire_incident"]["as_of"],
                    "fetched": time.strftime("%Y-%m-%d"),
                    "rows_raw": tot, "rows_agg": len(rows),
                    "years": sorted(years),
                    "unit": "재산피해_천원 = 천원 단위(원본 그대로)"})
    return _read_csv(FIRESTAT), _meta(FIRESTAT)


# 물건 용도에서 화재통계의 장소중분류로 가는 길. 원본 값은 「산업시설 > 공장시설 · 창고시설 ·
# 작업장 …」 이다(실측). 대장 용도가 「창고시설」이면 같은 이름이 통계에도 있어 그대로 쓴다.
PLACE_BY_PURPOSE = (("창고", "창고시설"), ("공장", "공장시설"), ("작업", "작업장"))
INDUSTRIAL = "산업시설"


def place_class(purpose):
    for k, v in PLACE_BY_PURPOSE:
        if k in (purpose or ""):
            return v
    return None


def region_fire(address, purpose=None, *, refresh=False):
    """시군구의 산업시설 화재 실적 + 전국 시군구 안에서의 순위.

    주소 앞 두 토큰이 시도·시군구다(「대구광역시 달서구 …」·「경상북도 구미시 …」) — 화재통계
    쪽 표기와 그대로 맞는다(실측). 세종처럼 시군구가 비는 곳은 매칭이 안 되므로 None 을 낸다.

    **두 줄을 낸다** — 이 물건 용도(창고시설·공장시설)와 산업시설 전체다. 용도 한 줄만 내면
    표본이 너무 작아 보이고(달서구 창고시설 5년 10건), 전체 한 줄만 내면 이 물건과 무슨
    상관인지가 사라진다.
    """
    rows, meta = fire_stats(refresh=refresh)
    t = (address or "").split()
    if len(t) < 2:
        return None
    sido, sgg = t[0], t[1]
    ind = [r for r in rows if r["장소대분류"] == INDUSTRIAL]

    def one(cls):
        mine = [r for r in ind if r["시도"] == sido and r["시군구"] == sgg
                and (cls is None or r["장소중분류"] == cls)]
        if not mine:
            return None
        n = sum(int(r["건수"]) for r in mine)
        # 전국 시군구별 같은 분류 합 → 이 시군구의 순위. 특건 KFRI 가 「업종대분류 평균」과
        # 견주는 자리다(우리는 전국을 다 스캔하므로 평균이 아니라 순위를 낼 수 있다).
        by = {}
        for r in ind:
            if cls is None or r["장소중분류"] == cls:
                k = (r["시도"], r["시군구"])
                by[k] = by.get(k, 0) + int(r["건수"])
        order = sorted(by.values(), reverse=True)
        return {"place": cls or "산업시설 전체", "n": n,
                "damage_k": sum(int(r["재산피해_천원"]) for r in mine),
                "dead": sum(int(r["사망"]) for r in mine),
                "hurt": sum(int(r["부상"]) for r in mine),
                "rank": (order.index(n) + 1) if n in order else None,
                "of": len(order), "nat_n": sum(by.values())}

    def causes(cls, top=3):
        """발화요인 상위 — 표본이 얕으면(20건 미만) 순위가 흔들려 내지 않는다."""
        by = {}
        for r in ind:
            if r["시도"] != sido or r["시군구"] != sgg:
                continue
            if cls is not None and r["장소중분류"] != cls:
                continue
            by[r["발화요인"]] = by.get(r["발화요인"], 0) + int(r["건수"])
        n = sum(by.values())
        if n < 20:
            return None, n
        out = sorted(by.items(), key=lambda x: -x[1])[:top]
        return [{"cause": c, "n": v, "pct": v / n * 100} for c, v in out], n

    want = place_class(purpose)
    focus = one(want) if want else None
    total = one(None)
    if not (focus or total):
        return None
    # 발화요인은 표본이 두꺼운 쪽에서 뽑는다 — 용도별이 20건을 못 넘거나 용도를 못 고르면
    # 산업시설 전체로 센다. **용도가 없을 때 `want`(None)를 문구에 쓰지 않는다** — 종이에
    # 「None 276건 기준」이 찍혔다(실측 고잔동 524-8: 대장 용도가 공장·창고가 아니다).
    cs, base_n, scope = None, 0, None
    if want:
        cs, base_n = causes(want)
        scope = f"{want} {base_n}건"
    if cs is None:
        cs, base_n = causes(None)
        scope = f"산업시설 전체 {base_n}건"
    return {"sido": sido, "sigungu": sgg, "focus": focus, "total": total,
            "causes": cs, "cause_scope": scope if cs else None,
            "years": meta.get("years") or [], "meta": meta}


# ── 기후 · 설계기준 ─────────────────────────────────────────────────────────
# 특건 「자연재해위험 › 기후」 절에 대응한다. 값은 셋으로 짝을 이룬다.
#
#   ① 관측 극값        — 기준 관측소의 30년 최대값(ASOS 일자료 API)
#   ② 전국 백분위       — 같은 값을 95개 ASOS 지점에서 재서 이 지점이 어디에 서는지
#   ③ 법정 기준값       — 지역별 기본풍속(법령 별표) 과 대조 → **초과 이력 판정**
#
# ①만 내면 「62 cm 라서 뭐」가 된다. ②는 모집단 위치를, ③은 넘었는지 못 넘었는지를 준다.
# 특건은 ①만(그리고 존 단위로) 준다 — 우리가 ②③을 더한다.
ASOS_URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
ASOS_STN = EXT / "code" / "asos_stations.csv"        # 저장소에 든 정적 표(95지점)
WIND_TBL = EXT / "code" / "기본풍속_별표5.csv"        # 저장소에 든 정적 표(법령 별표 5)
CLIMATE_DIR = EXT / "weather" / "asos"
CLIMATE_Y0, CLIMATE_Y1 = 1996, 2025                  # 30년 — 평년값 관례와 같은 길이
STORM_MS = 13.9          # 기상청 강풍일수 정의(일최대풍속 13.9 m/s 이상)를 프록시로 쓴다


def asos_stations():
    """[(지점번호, 지점명, 위도, 경도, 해발)] — `data/ext/code/asos_stations.csv`.

    **런타임에 웹을 긁지 않는다.** 지점정보 조회서비스(15058846)는 개발·운영 모두 심의승인이라
    쓸 수 없고, 지점은 거의 변하지 않는다. 만든 경로는 옆 `_asos_stations.json` 에 적어 두었다.
    """
    if not ASOS_STN.exists():
        raise RuntimeError(f"{ASOS_STN} 없음 — 저장소에 들어 있어야 한다")
    return _read_csv(ASOS_STN)


def nearest_asos(lat, lon):
    g = _geod()
    best = None
    for r in asos_stations():
        az, _, d = g.inv(lon, lat, float(r["경도"]), float(r["위도"]))
        if best is None or d < best["dist_m"]:
            best = {"stn": r["지점번호"], "name": r["지점명"], "dist_m": float(round(d)),
                    "dir": bearing_ko(az), "lat": float(r["위도"]),
                    "lon": float(r["경도"]), "alt_m": r.get("해발고도_m")}
    return best


def _asos_rows(stn, y0, y1, key):
    """지점 하나의 일자료 전량. 한 해씩 끊어 받는다 — 30년을 한 번에 달면 한 쪽이 실패했을 때
    어느 해가 빈지 알 수 없고, 재시도가 30년치를 다시 받는다."""
    rows = []
    for y in range(y0, y1 + 1):
        page = 1
        while True:
            q = {"serviceKey": key, "dataType": "JSON", "dataCd": "ASOS", "dateCd": "DAY",
                 "startDt": f"{y}0101", "endDt": f"{y}1231", "stnIds": stn,
                 "numOfRows": 999, "pageNo": page}
            d = _get_json(ASOS_URL, q, what=f"ASOS {stn} {y}")
            body = (((d or {}).get("response") or {}).get("body") or {})
            items = ((body.get("items") or {}).get("item")) or []
            if isinstance(items, dict):
                items = [items]
            rows += items
            tot = int(body.get("totalCount") or 0)
            if page * 999 >= tot or not items:
                break
            page += 1
    return rows


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def station_climate(stn, *, y0=CLIMATE_Y0, y1=CLIMATE_Y1, refresh=False, key=None):
    """지점의 30년 극값·일수 요약. 원자료(약 11,000행)는 버리고 요약만 캐시한다.

    극값은 **날짜를 함께** 남긴다 — 「34.6 m/s」만 적으면 언제 일인지 못 되짚는다(태풍 이름이
    붙는 값이라 심사역이 바로 안다). 일수는 연평균으로 낸다 — 관측 연수가 지점마다 달라서
    합계로 적으면 오래 관측한 지점이 위험해 보인다.
    """
    f = CLIMATE_DIR / f"{stn}_{y0}_{y1}.json"
    if f.exists() and not refresh:
        return json.loads(f.read_text("utf-8"))
    rows = _asos_rows(stn, y0, y1, key or _key())
    ext_max = {}                     # 항목 → (값, 날짜)
    per_year = {}                    # 연 → [강풍일, 뇌전일, 관측일]
    for r in rows:
        tm = (r.get("tm") or "")[:10]
        y = tm[:4]
        a = per_year.setdefault(y, [0, 0, 0])
        a[2] += 1
        ws = _f(r.get("maxWs"))
        if ws is not None and ws >= STORM_MS:
            a[0] += 1
        if "뇌전" in (r.get("iscs") or ""):
            a[1] += 1
        for k, fld in (("일최다강수량", "sumRn"), ("1시간최다강수량", "hr1MaxRn"),
                       ("최대풍속", "maxWs"), ("최대순간풍속", "maxInsWs"),
                       ("일최심신적설", "ddMefs"), ("일최심적설", "ddMes")):
            v = _f(r.get(fld))
            if v is None:
                continue
            if k not in ext_max or v > ext_max[k][0]:
                ext_max[k] = (v, tm, r.get("maxWsWd") if fld == "maxWs" else
                              (r.get("maxInsWsWd") if fld == "maxInsWs" else None))
    # 관측일이 300일도 안 되는 해는 일수 평균에서 뺀다 — 개소·폐소 연도가 값을 끌어내린다.
    full = {y: v for y, v in per_year.items() if v[2] >= 300}
    n = len(full) or 1
    out = {"stn": stn, "y0": y0, "y1": y1,
           "years_full": sorted(full), "n_years": len(full),
           "days_obs": sum(v[2] for v in per_year.values()),
           "storm_days_per_year": sum(v[0] for v in full.values()) / n,
           "thunder_days_per_year": sum(v[1] for v in full.values()) / n,
           "storm_ms": STORM_MS,
           "ext": {k: {"value": v[0], "date": v[1], "wd": v[2]} for k, v in ext_max.items()},
           "fetched": time.strftime("%Y-%m-%d")}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False), "utf-8")
    return out


def _cached_climate(y0=CLIMATE_Y0, y1=CLIMATE_Y1):
    """캐시에 있는 지점 요약 전부 — 백분위의 모집단이다."""
    if not CLIMATE_DIR.exists():
        return []
    out = []
    for f in CLIMATE_DIR.glob(f"*_{y0}_{y1}.json"):
        try:
            out.append(json.loads(f.read_text("utf-8")))
        except Exception:                                          # noqa: BLE001
            pass
    return out


def _rank(pop, value):
    """(순위, 모집단 수) — **1위가 전국에서 가장 센 곳**이다.

    백분위로 적었다가 순위로 바꿨다. 「상위 74 %」는 74 % 지점이 더 크다는 뜻인데 읽는 쪽은
    「센 쪽 74 %」로 읽는다(2026-08-20). 「95지점 중 71위」는 헷갈릴 여지가 없다.
    캐시가 아직 다 안 찼을 수 있으므로 모집단 수를 늘 함께 낸다.
    """
    v = [x for x in pop if x is not None]
    if not v or value is None:
        return None, len(v)
    return sum(1 for x in v if x > value) + 1, len(v)


# 법정 기본풍속 — 「건축물의 구조기준 등에 관한 규칙」 별표 5(제13조 관련)
def basic_wind(address):
    """주소 → 지역별 기본풍속(m/s). 못 찾으면 None.

    별표는 시·군을 적고 일부는 읍·면으로 값을 갈라 둔다(경주시 45 / 35 / 30). 주소가 그 읍·면을
    가리키면 그 값을, 아니면 **후보 중 가장 큰 값**을 쓴다 — 모르면 안전측으로 붙인다.
    제주는 표가 「전지역」 한 줄이다.
    """
    if not WIND_TBL.exists():
        return None
    rows = _read_csv(WIND_TBL)
    t = (address or "").split()
    if not t:
        return None
    if "제주" in t[0]:
        v = [r for r in rows if r["지역"] == "전지역"]
        if v:
            return {"ms": int(v[0]["기본풍속_ms"]), "matched": "제주도 전지역",
                    "basis": "「건축물의 구조기준 등에 관한 규칙」 별표 5"}
    for tok in (t[1] if len(t) > 1 else None, t[0]):     # 시·군이 먼저, 없으면 광역시
        if not tok:
            continue
        cand = [r for r in rows if r["지역"] == tok]
        if not cand:
            continue
        exact = [r for r in cand if r["세부"] and any(
            x.strip() and x.strip() in address for x in r["세부"].split(","))]
        pick = max(exact or cand, key=lambda r: int(r["기본풍속_ms"]))
        return {"ms": int(pick["기본풍속_ms"]),
                "matched": pick["지역"] + (f"({pick['세부']})" if pick["세부"] else ""),
                "split": len(cand) > 1 and not exact,
                "basis": "「건축물의 구조기준 등에 관한 규칙」 별표 5"}
    return None


CLIMATE_ITEMS = (("일최다강수량", "mm"), ("1시간최다강수량", "mm"),
                 ("최대풍속", "m/s"), ("최대순간풍속", "m/s"), ("일최심신적설", "cm"))


def climate(site, *, refresh=False):
    """리포트 기후 표 한 벌 — 기준 관측소 · 극값 · 전국 백분위 · 법정 기본풍속 대조."""
    pt = (site or {}).get("point") or {}
    if not (pt.get("lat") and pt.get("lon")):
        return None
    st = nearest_asos(pt["lat"], pt["lon"])
    sm = station_climate(st["stn"], refresh=refresh)
    pop = _cached_climate()
    rows = []
    for name, unit in CLIMATE_ITEMS:
        e = (sm.get("ext") or {}).get(name) or {}
        rk, n = _rank([(x.get("ext") or {}).get(name, {}).get("value") for x in pop],
                      e.get("value"))
        rows.append({"item": name, "unit": unit, "value": e.get("value"),
                     "date": e.get("date"), "wd": e.get("wd"), "rank": rk, "pop": n})
    for key, name, unit in (("storm_days_per_year", "폭풍일수", "일/년"),
                            ("thunder_days_per_year", "낙뢰일수", "일/년")):
        rk, n = _rank([x.get(key) for x in pop], sm.get(key))
        # **종이와 같은 눈금으로 담는다** — 표는 연평균 일수를 소수 한 자리로 적는데
        # (`_cval`) 값 파일에는 나눗셈 그대로 `2.1666666666666665` 가 남아 있었다. 순위는
        # 접기 전 값으로 이미 냈다(`_rank`) — 접기로 자리가 바뀌지 않는다.
        v = sm.get(key)
        rows.append({"item": name, "unit": unit,
                     "value": None if v is None else round(float(v), 1),
                     "date": None, "wd": None, "rank": rk, "pop": n})
    return {"station": st, "summary": {k: sm[k] for k in
                                       ("y0", "y1", "n_years", "years_full", "storm_ms")},
            "rows": rows, "wind_code": basic_wind(site.get("address"))}


# ── 리포트가 받는 한 벌 ─────────────────────────────────────────────────────
def context(site, purpose=None, *, refresh=False):
    """리포트 5·6면이 쓰는 값. 실패해도 리포트는 나와야 하므로 예외를 삼키고 사유를 남긴다."""
    pt = (site or {}).get("point") or {}
    out = {"fire": None, "climate": None, "errors": []}
    if pt.get("lat") and pt.get("lon"):
        try:
            acc, meta = fire_access(pt["lat"], pt["lon"], refresh=refresh)
            out["fire"] = dict(acc, meta=meta)
        except Exception as e:                                     # noqa: BLE001
            out["errors"].append(f"소방서 좌표: {type(e).__name__}: {e}")
    else:
        out["errors"].append("물건 좌표가 없어 소방서 거리를 재지 못했다")
    try:
        out["climate"] = climate(site, refresh=refresh)
    except Exception as e:                                         # noqa: BLE001
        out["errors"].append(f"기후: {type(e).__name__}: {e}")
    return out


def build_climate(*, workers=8, refresh=False, only=None):
    """전국 ASOS 지점의 30년 요약을 받아 캐시에 채운다 — **백분위의 모집단**을 만드는 일이다.

    한 지점이 30호출(해마다 한 번)이고 응답이 5초쯤이라 직렬로는 4시간이 넘는다. 지점별로
    독립이므로 스레드로 나눈다(API 한도는 30 tps 라 8 스레드는 넉넉히 안쪽이다).
    **지점마다 파일 하나**라 중간에 끊겨도 다시 돌리면 남은 것만 받는다.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    key = _key()
    todo = [r["지점번호"] for r in asos_stations()
            if (only is None or r["지점번호"] in only)
            and (refresh or not (CLIMATE_DIR / f"{r['지점번호']}_{CLIMATE_Y0}_{CLIMATE_Y1}.json").exists())]
    print(f"기후 캐시 — 받을 지점 {len(todo)} / 전체 {len(asos_stations())}")
    done, fail = 0, []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fs = {ex.submit(station_climate, t, refresh=refresh, key=key): t for t in todo}
        for f in as_completed(fs):
            t = fs[f]
            try:
                f.result(); done += 1
            except Exception as e:                                 # noqa: BLE001
                fail.append((t, f"{type(e).__name__}: {e}"))
            print(f"  {done + len(fail)}/{len(todo)}  (실패 {len(fail)})", flush=True)
    if fail:
        print("실패 지점:", fail[:10])
    return done, fail


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="외부 공공데이터 캐시 만들기/갱신")
    ap.add_argument("--refresh", action="store_true", help="캐시를 무시하고 다시 받는다")
    ap.add_argument("--climate", action="store_true",
                    help="전국 ASOS 30년 요약을 받는다(백분위 모집단). 재시작 가능")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    if a.climate:
        build_climate(workers=a.workers, refresh=a.refresh)
        pop = _cached_climate()
        print(f"기후 캐시 지점 {len(pop)} 개 → {CLIMATE_DIR}")
        return 0
    rows, meta = stations(refresh=a.refresh)
    print(f"소방서·안전센터 {len(rows):,}행  ({meta.get('as_of')} 기준, "
          f"받은 날 {meta.get('fetched')})  → {STATIONS}")
    rows, meta = fire_stats(refresh=a.refresh)
    print(f"화재발생 집계 {len(rows):,}행  (원본 {meta.get('rows_raw'):,}행 · "
          f"{'~'.join([meta['years'][0], meta['years'][-1]]) if meta.get('years') else '?'})"
          f"  → {FIRESTAT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
