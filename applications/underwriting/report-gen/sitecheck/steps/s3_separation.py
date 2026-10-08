"""단계 3 — 건물 사이 이격거리 (A1).

**세는 규칙은 [[rules.py]] 에 있다** — 도달거리(`SEP_REACH_M` = 11.3 m) · 걸음
(`SEP_WALK_STEP_M`) · 마주하는 폭 하한(`SEP_MIN_FRONT_M`)과 그 값을 그렇게 정한 근거가
거기 있다. 이 파일은 그 규칙을 기하로 실행하기만 한다(`rules` 는 shapely 를 들여오지
않는다 — 순수 임계값 파일로 두는 것이 그 파일의 성격이다).

**두 조문을 따로 낸다.** 예전에는 둘을 한 규칙(둘레 25 m 안 전부)에서 뽑고 접는 방식만
달리했는데, 그러면 같은 물건에서 그림의 선 수와 표의 줄 수가 갈린다.

    필지 안   소방시설법 시행규칙 제17조 제2호가 **직접 말하는 구조**다(대지경계선 안 둘
              이상 건축물). 걸을 경계선이 없으므로 **쌍마다** 낸다. **도달거리로 자르지
              않는다** — 필지 밖과 같은 이유다(아래).

    필지 밖   조문 밖이지만 연소는 경계를 넘는다. **대지경계선을 걸으며 자리마다 가장
              가까운 상대 하나**를 낸다. 임자가 바뀌는 곳이 구간 경계이고, 구간들은
              대지경계선의 분할이라 빈틈도 겹침도 없다 — 「부지를 한 바퀴 돈다」가 정렬
              규칙이 아니라 구조가 된다. **도달거리로 자르지 않는다** — 자르는 것은
              판정선이지 측정 여부가 아니다. 18 m 떨어진 쪽은 「이상없음 18 m」로 적고,
              행이 없는 것은 「그쪽 60 m 안에 아무것도 없다」는 뜻으로만 쓴다.
              구간 하나에 **도달거리 안으로 마주 선 우리 동은 전부** 적는다(근거는 rules.py).

    상대 없음 탐색반경 안에 아무것도 없으면 대지경계선까지의 거리(`lot_line`, 제22조 제2항).

**거리는 두 조문 모두 외벽 간(지붕 외곽선 간) 최단거리다.** 제17조가 그렇게 쓰여 있다.
대지경계선은 필지 밖 상대의 **방향과 자리를 정하는 눈금**일 뿐이고, 판정 숫자는 아니다.
그래서 필지 밖 구간 하나에는 거리가 둘 붙는다 — 임자를 가른 `front_d_m`(그 자리에서
경계선까지)과 판정에 쓰는 `dist_m`(외벽 간).

**결과를 선(LineString)으로 낸다.** 두 건물의 최근접점을 잇는 선 그 자체가 잰 거리다.
폭 있는 구역으로 그리면 지도에서 건물을 가리고, 선 위치가 실제로 어디를 잰 것인지도
흐려진다. 길이 = `dist_m` 이므로 도형과 숫자가 어긋날 수 없다.

거리는 **UTM-K(EPSG:5179)로 투영해서** 잰다. 경위도에서 잰 거리는 위도에 따라 축척이
달라 미터가 아니다.

측정 대상은 지붕 외곽선이다. 지붕이 벽보다 처마만큼 튀어나오므로 지붕 기준 거리는 실제
외벽 간 거리보다 **짧게** 나온다 — 안전측이다(근거문서 A1 '측정 오차').
"""
from __future__ import annotations

import math

from sitecheck import settings as config
from sitecheck import rules
from sitecheck import schema

# 탐색반경 — **판정선이 아니라 「여기까지는 재고, 밖은 없는 것으로 본다」는 선.** 필지 밖
# 구간의 임자는 이 안에서 고르고, 거리는 도달거리를 넘어도 그대로 적는다(넘으면 판정이
# 「이상없음」이 될 뿐이다). 이 값이 곧 「비어 있다」고 말할 수 있는 한계다.
SEARCH_M = 60.0
DIRS = ("북", "동", "남", "서")     # 4방위 — `--skip-dir`(도로면 제외)가 이 이름을 쓴다
# 표·지도에 적는 방위는 8방위다(설계서 BR-13 의 「북동 1.2 m 위험」). 4방위로 적으면 비스듬히
# 마주 선 상대가 다 「동」이 되어 지도에서 어느 선인지 못 찾는다.
DIRS8 = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")


def _to_utm():
    from pyproj import Transformer
    return (Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True),
            Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True))


def build_floor_index(site):
    """(필지 폴리곤, 최고 층수) 목록 — 대상 필지 + 주변 필지 전부.

    층수를 **그 건물이 선 필지의 대장**에서 가져오기 위한 색인이다. 대상 필지 대장을
    옆 건물에도 쓰면 1층 공장 옆의 3층 건물이 1층으로 판정되어 6 m/10 m 기준이 갈린다.
    """
    from shapely.geometry import shape
    idx = []
    def top(rows):
        fl = [b.get("floors_above") for b in (rows or []) if b.get("floors_above")]
        return int(max(fl)) if fl else None
    if site.get("parcel"):
        idx.append((shape(site["parcel"]), top(site.get("ledger")), site.get("pnu")))
    for n in site.get("neighbors") or []:
        try:
            idx.append((shape(n["geometry"]), top(n.get("ledger")), n.get("pnu")))
        except Exception:                                    # noqa: BLE001
            continue
    return idx


def _floors_of(feat, site, idx=None):
    """건물 feature 의 층수 → (층수, 어디서 왔나). 못 정하면 (None, 사유).

    층수는 그 건물이 **가장 많이 걸친 필지**의 대장에서 온다. 어느 필지에도 안 걸치면 가장
    가까운 필지의 것을 쓰는데, 그것은 **추측이므로 그렇다고 적는다** — 이 값 하나로 6 m/10 m
    기준이 갈리기 때문이다. 못 정하면 판정은 보수적으로 2층 기준(10 m)을 쓴다.

    돌려주는 두 번째 값

        ledger         그 건물이 선 필지의 대장에서 왔다 — 이것만 확실하다
        empty          필지는 찾았으나 그 대장에 층수가 없다
        nearest        어느 필지에도 안 걸쳐 **가장 가까운 필지**의 층수를 썼다 — 추측이다
        nearest_empty  위와 같은데 그 필지 대장에도 층수가 없다
        none           필지 색인 자체가 없다(필지도 인접필지도 못 얻었다)

    `nearest` 와 `empty` 를 한 이름으로 묶으면 안 된다 — 앞은 「남의 층수를 빌려 썼다」이고
    뒤는 「아무 데도 없다」다. 받는 쪽이 판정을 얼마나 믿을지가 그 차이로 갈린다.
    """
    from shapely.geometry import shape
    if idx is None:
        idx = build_floor_index(site)
    if not idx:
        return None, "none"
    g = shape(feat["geometry"])
    best, best_a = None, 0.0
    for poly, fl, _pnu in idx:
        try:
            a = g.intersection(poly).area
        except Exception:                                    # noqa: BLE001
            continue
        if a > best_a:
            best, best_a = fl, a
    if best_a > 0:
        return best, ("ledger" if best is not None else "empty")
    near = min(idx, key=lambda t: g.distance(t[0]))
    return near[1], ("nearest" if near[1] is not None else "nearest_empty")


def az_of(x0, y0, x1, y1):
    """방위각(도, 북=0 시계방향). **선 자체에서 뽑는다** — 중심점끼리 재면 그린 선과 라벨이
    어긋난다."""
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360.0


def dir_of(x0, y0, x1, y1):
    """4방위 — `--skip-dir` 가 도로면을 뺄 때 쓰는 거친 눈금."""
    return DIRS[int((az_of(x0, y0, x1, y1) + 45.0) // 90) % 4]


def dir8(az):
    """방위각 → 8방위 이름."""
    return DIRS8[int((az + 22.5) // 45) % 8]


def _ring_walk(par_m, step_m, max_steps):
    """대지경계선을 **북쪽부터 시계방향으로** 걷는 자리 목록 → [(Point, 둘레 위 거리 m)].

    시계방향으로 고정하고 북에서 시작하는 이유는 표의 순서 그 자체다 — 위에서 아래로 읽으면
    지도를 한 바퀴 도는 순서가 되어야 한다(설계서 BR-13). 옛 코드는 방위각으로 정렬해서 그
    순서를 흉내 냈는데, 상대가 필지 반대편에 있으면 방위각과 둘레 위 자리가 어긋났다.
    """
    from shapely.geometry import Point
    ring = par_m.exterior if par_m.geom_type == "Polygon" else \
        max(par_m.geoms, key=lambda g: g.area).exterior
    P = ring.length
    n = max(8, min(max_steps, int(P / step_m)))
    pts = [ring.interpolate(P * i / n) for i in range(n)]
    # 시계방향으로 뒤집는다 — shapely 는 방향을 보장하지 않는다(is_ccw 가 참이면 반시계).
    if ring.is_ccw:
        pts = [pts[0]] + pts[1:][::-1]
    # 북쪽에서 시작 — 필지 중심에서 본 방위가 0 에 가장 가까운 자리
    c = par_m.centroid
    k = min(range(n), key=lambda i: min(
        (math.degrees(math.atan2(pts[i].x - c.x, pts[i].y - c.y)) % 360.0),
        360.0 - (math.degrees(math.atan2(pts[i].x - c.x, pts[i].y - c.y)) % 360.0)))
    pts = pts[k:] + pts[:k]
    return [(pt, P * i / n) for i, pt in enumerate(pts)], P, P / n


def _runs(win, seg_m):
    """자리별 임자 배열(원형) → [(임자, 마주하는 폭 m, 시작 index, 개수)].

    임자가 바뀌는 자리를 찾아 그곳에서 시작한다 — 배열 0번에서 시작하면 북쪽을 걸치고 있는
    한 구간이 앞뒤 둘로 쪼개져 같은 상대가 표에 두 번 나온다.
    """
    n = len(win)
    if not any(w is not None for w in win):
        return []
    if len(set(win)) == 1:
        return [(win[0], n * seg_m, 0, n)]
    s = 0
    while win[(s - 1) % n] == win[s % n]:
        s += 1
    out, i, done = [], s, 0
    while done < n:
        j = i
        while win[j % n] == win[i % n] and done < n:
            j += 1
            done += 1
        if win[i % n] is not None:
            out.append((win[i % n], (j - i) * seg_m, i % n, j - i))
        i = j
    return out


def run(buildings_fc, neighbors, site, *, search_m=SEARCH_M, reach_m=None,
        step_m=None, min_front_m=None, shadow_m=None, also=(), skip=()):
    """두 조문을 따로 낸다 — 세는 규칙과 그 근거는 [[rules.py]] 의 「무엇을 한 쌍으로 세나」.

        필지 안   제17조 제2호가 직접 말하는 구조 → **쌍마다**, 탐색반경 안
        필지 밖   대지경계선을 걸으며 **자리마다 최근접 하나** → 구간마다,
                  그 구간에 도달거리 안으로 마주 선 우리 동마다 한 줄

    거리는 둘 다 **외벽 간 최단거리**다(제17조). 축에 투영하지 않는다 — 투영하면 비스듬히
    마주 선 건물이 실제보다 멀게 나와 연소 우려를 과소평가한다.

    층수는 그 건물이 선 필지의 대장에서 온다(`build_floor_index`) — 대상 필지 대장을 옆
    건물에도 쓰면 1층 공장 옆 3층 건물이 1층으로 판정되어 6 m/10 m 기준이 갈린다.

    `pair` 규약 — **`pair[0]` 은 늘 이 지번 건물**이다. 필지 안 쌍은 양쪽에서 한 번씩 **두
    줄**로 나온다(건물마다 「내 둘레에 무엇이 있나」를 적는 표이므로 그것이 맞고, 쌍의 개수를
    세려면 절반이다). 필지 밖은 구간마다 나오고, **한 구간에 도달거리 안으로 마주 선 우리 동이
    둘 이상이면 그만큼 줄이 늘어난다** — `pair[0]` 이 그 동이고 `run_id` 는 같다.

    필지 밖 줄에만 붙는 값

        run_id      구간 번호(북부터 시계방향, 1부터). 이것이 그 줄의 정체다 — 같은 상대가
                    떨어진 두 구간을 이길 수 있으므로(L 자로 감싼 필지) 상대 id 로는 못 센다
        front_m     그 상대가 마주하는 대지경계선 길이. **좁다고 버리지 않고 값으로 낸다**
        front_d_m   구간 중앙에서 그 상대까지 — 임자를 가른 거리(판정에는 쓰지 않는다)
        arc_m       구간 중앙의 둘레 위 자리(m). 표·그림의 정렬 기준

    `shadow_m` — **구간을 이기지 못했어도 이만큼 가까우면 자동으로 낸다**(기본
    [[rules.py]] `SEP_SHADOW_M` = 30 m). 자리마다 임자가 하나라 앞엣것에 가린 건물은 한
    자리도 못 이겨 표에서 통째로 빠지는데, 그 잣대(경계선 위 자리에서의 거리)와 판정의
    잣대(우리 동에서의 거리)가 달라 **경고가 통째로 사라지기도 한다**(실측 공단동 152-2:
    9.6 m 법정선 미달 상대에게 줄이 없었다). 이 줄에는 `shadowed=True` 를 달고 `front_m` 을
    비운다 — `also` 와 같은 모양이고, 다른 것은 사람이 골랐나 규칙이 골랐나뿐이다.
    `skip` 으로 걷기에서 뺀 상대는 여기서도 안 나온다.

    `also` — **구간을 이기지 못한 상대를 손으로 더한다**(옆 지번 건물의 `bld_id` 목록).
    자리마다 최근접 하나만 세므로 두 상대에게 끼인 건물은 아무 자리도 못 이겨 표에서
    아예 빠진다(실측 호림동 3-10 남서쪽 건물: 우리 동에서 4.9 m 인데 남쪽·서쪽 건물이
    모든 자리를 이겨 줄이 없었다). 그런 줄에는 `hand=True` 를 달고 **`front_m` 을
    비운다** — 마주한 폭이 0 인 것이 아니라 「어느 자리도 이기지 않았다」가 맞는 말이고,
    0 으로 적으면 「폭 0 m 로 마주한다」로 읽힌다. 거리·방위·판정은 이긴 줄과 같다.

    `skip` — **경계선 구간을 이기지 못하게 하는 상대**(옆 지번 건물의 `bld_id` 목록).
    「저기 건물은 있지만 자동으로 나는 줄은 싣지 않는다」고 사람이 정한 자리다. `also` 와
    반대 방향이지만 **서로 배타가 아니다** — 걷기에서만 빼고 `also` 에는 남긴다. 그래야
    「자동으로 이긴 줄은 빼고, 사람이 고른 쌍 하나만 싣는다」를 말할 수 있다(실측 호림동
    3-10 N0044: A동 17.8 m 자동 줄은 안 싣고 B동 34.8 m 만 싣는다). 걷기에서 뺀 자리는
    그 상대가 없던 것과 같은 구간·노출률을 낸다 — `also` 로 더한 줄은 구간을 만들지 않기
    때문이다.

    사람이 확인해 뺀 옆 지번 건물은 **여기 오기 전에 이미 빠져 있다**
    ([[steps/s1_building.label_features]] · [[settings.py]] `NEIGHBOR_DROP`) — 이 단계가
    다시 가릴 것이 없다.
    """
    from shapely.geometry import LineString, shape
    from shapely.ops import nearest_points, transform

    reach_m = rules.SEP_REACH_M if reach_m is None else reach_m
    step_m = rules.SEP_WALK_STEP_M if step_m is None else step_m
    min_front_m = rules.SEP_MIN_FRONT_M if min_front_m is None else min_front_m
    shadow_m = rules.SEP_SHADOW_M if shadow_m is None else shadow_m

    feats = list(buildings_fc.get("features") or [])
    if len(feats) + len(neighbors or []) < 2:
        return schema.empty("separation", "건물이 둘 미만이라 이격을 낼 수 없다")

    fwd, inv = _to_utm()
    idx = build_floor_index(site)
    own = [(f, transform(fwd.transform, shape(f["geometry"]))) for f in feats]
    nbs = [(f, transform(fwd.transform, shape(f["geometry"]))) for f in (neighbors or [])]
    if not own:
        return schema.empty("separation", "이 지번에 귀속된 건물이 없다")
    floors = {id(f): _floors_of(f, site, idx) for f, _g in own + nbs}

    def emit(fa, ga, fb, gb, d, **extra):
        fa_fl, fa_src = floors[id(fa)]
        fb_fl, fb_src = floors[id(fb)]
        fl = [x for x in (fa_fl, fb_fl) if x]
        v = rules.separation_verdict(d, max(fl) if fl else None)
        pa, pb = nearest_points(ga, gb)
        az = az_of(pa.x, pa.y, pb.x, pb.y)
        props = schema.verdict_props(
            v, pair=[fa["properties"]["bld_id"], fb["properties"]["bld_id"]],
            dir=DIRS[int((az + 45.0) // 90) % 4], dir8=dir8(az),
            # **종이와 같은 눈금으로 담는다** — 보고서는 거리를 소수 한 자리로 적는다
            # (`draw.dist_text`). 값 파일에만 둘째 자리를 두면 같은 쌍이 종이에서 2.0 m,
            # 파일에서 2.05 m 가 되어 대조하는 사람이 어느 쪽이 정본인지 물어야 한다.
            # 판정은 접기 전 실수로 내므로(`separation_verdict(d, …)`) 이 접기로 판정이
            # 흔들리지 않는다.
            az_deg=round(az, 1), dist_m=round(float(d), 1), floors=[fa_fl, fb_fl],
            # **층수를 어디서 얻었는지 같이 적는다** — `nearest` 는 그 건물이 선 필지를
            # 못 찾아 옆 필지 대장을 쓴 것이라 추측이고, 그 값으로 6 m/10 m 가 갈린다.
            floors_src=[fa_src, fb_src], caveat=rules.SEP_UNVERIFIABLE, **extra)
        line = LineString([pa, pb]) if d > 0 else LineString([pa, pa])
        return schema.feature(transform(inv.transform, line), props,
                              fid=(f"S:{fa['properties']['bld_id']}:"
                                   f"{fb['properties']['bld_id']}"))

    # ── 필지 안 (제17조 제2호) — 쌍마다, 탐색반경 안 ──────────────────────
    # **도달거리로 자르지 않는다.** 필지 밖에는 진작 그렇게 두었는데 여기만 11.3 m 로
    # 잘라 냈고, 그래서 18 m 떨어진 두 동이 선 필지는 표가 「이 지번 건물이 하나뿐 ·
    # 판정 불가」라고 말했다(실측 고잔동 672-6 A동↔B동 18.03 m) — 두 동이 있고 재기까지
    # 한 물건에 대고 하는 거짓말이다. 근거는 [[rules.py]] `SEP_REACH_M` 단락.
    inside = []
    for fa, ga in own:
        for fb, gb in own:
            if fb is fa:
                continue
            d = ga.distance(gb)
            if d <= search_m:
                inside.append(emit(fa, ga, fb, gb, d, same_parcel=True))
    inside.sort(key=lambda f: (f["properties"]["pair"][0], f["properties"]["dist_m"]))

    # ── 필지 밖 — 대지경계선을 걸으며 자리마다 최근접 하나 ──────────────────
    outside, expo, perim, n_reach, n_hand, n_runs, n_shadow = [], 0.0, None, 0, 0, 0, 0
    par_m = transform(fwd.transform, shape(site["parcel"])) if site.get("parcel") else None
    # **후보를 도달거리로 자르지 않는다 — 자르는 것은 판정선이지 측정 여부가 아니다.**
    # 처음에는 여기서도 도달거리로 걸렀는데, 그러면 11.3 m 밖 상대는 행이 아예 없어서
    # 「이쪽은 18 m 비어 있다」를 말할 수 없다(실측: 60 m 안인데 재지 않은 옆 지번이 23곳에
    # 328동). 재지 않은 것과 재서 이상 없는 것은 다른 말이고, 표는 그 둘을 구분해야 한다.
    #
    # 이렇게 풀어도 줄이 터지지 않는다 — **줄 수를 정하는 것은 상대 수가 아니라 둘레 모양**
    # 이기 때문이다(경계선의 분할이므로 구간은 둘레를 나눠 가진다). 실측 23곳: 도달거리로
    # 걸렀을 때 91구간, 탐색반경까지 풀어 142구간(물건당 4.0 → 6.2줄). 옛 25 m 반경 방식은
    # 물건당 9.6줄이었다.
    cand = [(fb, gb, min(ga.distance(gb) for _fa, ga in own)) for fb, gb in nbs]
    cand = [c for c in cand if c[2] <= search_m]
    # **걷기에서 빼는 상대는 `also` 에는 남는다**(`skip`) — 뺀 것과 더한 것이 같은 건물일 수
    # 있다. 자동으로 이긴 줄은 싣지 않고 사람이 고른 쌍 하나만 싣는 자리다.
    skip = set(skip or ())
    walk_cand = [c for c in cand
                 if (c[0]["properties"] or {}).get("bld_id") not in skip]
    if par_m is not None and cand:
        walk, perim, seg = _ring_walk(par_m, step_m, rules.SEP_WALK_MAX_STEPS)
        win = []
        for pt, _arc in walk:
            dd = [c[1].distance(pt) for c in walk_cand]
            if not dd:
                win.append(None)
                continue
            k = min(range(len(walk_cand)), key=lambda i: dd[i])
            # 탐색반경 밖이면 임자가 없다 — 「그쪽은 60 m 안에 아무것도 없다」가 맞는 말이다.
            win.append(k if dd[k] <= search_m else None)
            # **노출은 자리마다 센다 — 구간 길이로 세면 안 된다.** 구간의 임자가 도달거리 안
            # 이라고 그 구간 전체가 붙어 있는 것은 아니다. 8 m 짜리 상대 하나가 둘레 250 m 를
            # 이기면 노출이 250 m 로 잡혀 어느 물건이나 100 % 가 된다(실측 공단동 152-2 ·
            # 호림동 2-2 · 고잔동 716 이 그렇게 나왔다).
            #
            # 재는 것은 **대지경계선에서 도달거리 안에 옆 지번 건물이 있는 둘레 길이**다 —
            # 우리 건물이 어디 섰는지와 무관한 필지 자체의 성질이고(둘레의 몇 %가 이웃
            # 건물에 둘러싸였나), 그래서 `dist_m`(외벽 간)이 아니라 자리에서 상대까지의
            # 거리로 센다. 판정은 `dist_m` 이 내고, 이 값은 물건을 가르는 눈금이다.
            if dd[k] <= reach_m:
                expo += seg
        for no, (k, front, i0, cnt) in enumerate(_runs(win, seg), 1):
            if front < min_front_m:
                continue
            fb, gb, d = walk_cand[k]
            mid = walk[(i0 + cnt // 2) % len(walk)]
            # **그 상대에게 도달거리 안으로 마주 선 우리 동은 전부 적는다** — 하나만
            # 고르면 두 번째 경고가 조용히 사라진다(근거·실측은 [[rules.py]]). 도달거리
            # 안에 아무 동도 없으면 가장 가까운 동 하나로 그 구간을 대표한다 — 구간은
            # 대지경계선의 분할이라 빈 구간을 둘 수 없다.
            facing = sorted(((fa, ga, ga.distance(gb)) for fa, ga in own),
                            key=lambda t: t[2])
            for fa, ga, dd in ([t for t in facing if t[2] <= reach_m] or facing[:1]):
                # `front_m` 은 두 줄에 같은 값이다 — 「마주한 폭」은 **그 상대가** 마주하는
                # 경계선 길이라 우리 동마다 갈리는 값이 아니다.
                outside.append(emit(fa, ga, fb, gb, dd, same_parcel=False, run_id=no,
                                    # 종이는 마주한 폭을 정수로 적는다 — 같은 눈금으로 담는다
                                    front_m=float(round(front)),
                                    front_d_m=round(float(gb.distance(mid[0])), 2),
                                    arc_m=round(mid[1], 1)))
            n_runs += 1
            if d <= reach_m:
                n_reach += 1
        # ── 가려진 상대 보충(자동) ──────────────────────────────────────────
        # 자리마다 임자가 하나라 앞엣것에 가린 건물은 한 자리도 못 이긴다. **가까우면 낸다**
        # — 눈금과 그 근거는 [[rules.py]] `SEP_SHADOW_M`. 이긴 줄과 같은 코드(`emit`)로 내고
        # `front_m` 을 비운다(어느 자리도 이기지 않았다). `walk_cand` 에서 고르므로 사람이
        # 걷기에서 뺀 상대(`skip`)는 여기서도 안 나온다 — 「자동으로 나는 줄은 싣지 않는다」가
        # 구간에서만 지켜지고 여기서 깨지면 그 손보정이 뜻을 잃는다.
        won_nb = {f["properties"]["pair"][1] for f in outside}
        for fb, gb, d in walk_cand:
            bid = (fb["properties"] or {}).get("bld_id")
            if bid in won_nb or d > shadow_m:
                continue
            k = min(range(len(walk)), key=lambda i: gb.distance(walk[i][0]))
            # **우리 동을 고르는 규칙은 구간과 같다** — 도달거리 안이면 전부, 없으면 가장
            # 가까운 하나. 여기만 다르게 두면 같은 상대가 이겼을 때와 가렸을 때 줄 수가 갈린다.
            facing = sorted(((fa, ga, ga.distance(gb)) for fa, ga in own), key=lambda t: t[2])
            # **번호는 상대마다 하나다** — 우리 동이 둘 붙어 두 줄이 나도 같은 자리를 가리키는
            # 줄이므로, 이긴 구간과 같이 `run_id` 를 공유한다(갈라 두면 지도의 한 상대에
            # 번호가 둘 붙는다).
            no = max([f["properties"].get("run_id") or 0 for f in outside] or [0]) + 1
            for fa, ga, dd in ([t for t in facing if t[2] <= reach_m] or facing[:1]):
                outside.append(emit(fa, ga, fb, gb, dd, same_parcel=False,
                                    run_id=no, front_m=None,
                                    front_d_m=round(float(gb.distance(walk[k][0])), 2),
                                    arc_m=round(walk[k][1], 1), shadowed=True))
            n_shadow += 1
            if d <= reach_m:
                n_reach += 1

        # ── 구간을 이기지 못한 상대 보충(`also`) ────────────────────────────
        # 자리마다 최근접 하나만 세면 두 상대에게 끼인 건물이 표에서 빠진다. 눈으로 확인해
        # 더하기로 정한 상대는 여기서 낸다 — **거리·방위·판정은 이긴 줄과 같은 코드**(`emit`)
        # 로 내고, 마주한 폭만 비운다(이 상대는 어느 자리도 이기지 않았다).
        # `also` 항목은 상대 id 하나(`"N0030"`) 또는 **(상대, 우리 동) 쌍**이다. 뒤엣것은
        # 「이 상대에게 이 동도 이어라」는 뜻으로, 상대에게 이미 줄이 있어도 낸다 — 도달거리
        # 밖(29 m)이라 「구간마다 도달거리 안 우리 동 전부」 규칙이 두 번째 동을 안 내주는
        # 자리를 사람이 채우는 길이다.
        seen = {(f["properties"]["pair"][0], f["properties"]["pair"][1]) for f in outside}
        have_nb = {f["properties"]["pair"][1] for f in outside}
        for item in (also or ()):
            bid, own_id = (item, None) if isinstance(item, str) else (item[0], item[1])
            if own_id is None and bid in have_nb:
                continue
            pick = next((c for c in cand
                         if (c[0]["properties"].get("bld_id")) == bid), None)
            if pick is None:
                continue
            fb, gb, d = pick
            k = min(range(len(walk)), key=lambda i: gb.distance(walk[i][0]))
            if own_id is None:
                fa, ga = min(own, key=lambda t: t[1].distance(gb))
            else:
                hit = [t for t in own if t[0]["properties"].get("bld_id") == own_id]
                if not hit:
                    continue
                fa, ga = hit[0]
                d = ga.distance(gb)
            if (fa["properties"]["bld_id"], bid) in seen:
                continue
            seen.add((fa["properties"]["bld_id"], bid))
            no = max([f["properties"].get("run_id") or 0 for f in outside] or [0]) + 1
            # **자리는 실제로 잰 둘레 자리다** — 그 상대에게 가장 가까운 경계선 위 지점.
            # 이긴 줄의 `arc_m` 은 구간 **중앙**이라 눈금이 정확히 같지는 않지만, 다른 값으로
            # 바꿔 끼우면 값이 「북쪽 건물인데 서쪽 자리」처럼 거짓이 되거나 번호가 엉뚱한
            # 자리로 튄다(둘 다 해 보고 되돌렸다 — 2026-08-23). 북쪽 변 전체와 거리가 같은
            # 상대는 자리가 그 변의 한쪽 끝으로 잡히는데, 그것도 북쪽 변 위의 자리다.
            outside.append(emit(fa, ga, fb, gb, d, same_parcel=False, run_id=no,
                                front_m=None,
                                front_d_m=round(float(gb.distance(walk[k][0])), 2),
                                arc_m=round(walk[k][1], 1), hand=True))
            n_hand += 1
            if d <= reach_m:
                n_reach += 1
        outside.sort(key=lambda f: f["properties"]["arc_m"])
    elif cand:
        # 필지를 못 얻은 물건 — 걸을 경계선이 없으니 도달거리 안 상대만 낸다(그 밖은 무엇을
        # 기준으로 골라야 할지 정할 근거가 없다). 무엇으로 냈는지 note 에 적는다.
        for fb, gb, d in walk_cand:
            if d > reach_m:
                continue
            fa, ga = min(own, key=lambda t: t[1].distance(gb))
            outside.append(emit(fa, ga, fb, gb, d, same_parcel=False))
        outside.sort(key=lambda f: f["properties"]["az_deg"])

    out = inside + outside
    # **구간과 줄을 갈라 센다.** 한 구간이 여러 줄을 낼 수 있게 된 뒤로 `len(outside)` 는
    # 구간 수가 아니다 — 한 수로 적으면 「구간은 둘레의 분할」이라는 성질이 안 읽힌다.
    # 필지 안도 쌍 수로 적는다(줄은 양쪽에서 하나씩 나오므로 그 절반이다).
    note = (f"건물 {len(own)}동 · 도달거리 {reach_m:.1f} m — "
            f"필지 안 {len(inside) // 2}쌍 · 필지 밖 {n_runs}구간 {len(outside)}줄"
            f"(그중 도달거리 안 {n_reach}구간)")
    if n_shadow:
        # **가려서 못 이긴 상대를 몇 동 더 냈는지 적는다.** 이 줄들도 경계선의 분할이 아니라
        # 그 위에 얹은 것이라, 「구간 수 = 둘레의 분할」이 이 물건에서 몇 줄만큼 어긋난다.
        note += f" · 구간을 못 이겨 자동으로 더한 상대 {n_shadow}동({shadow_m:.0f} m 안)"
    if n_hand:
        # **더한 사실을 값에 적는다.** 이 줄들은 경계선의 분할이 아니라 사람이 골라 넣은
        # 것이라, 「구간 수 = 둘레의 분할」이라는 성질이 이 물건에서는 깨져 있다.
        note += f" · 구간을 못 이겨 손으로 더한 상대 {n_hand}동"
    if perim:
        # **무엇을 잰 값인지 note 에 그대로 적는다.** 「노출 147 m」만 적으면 무엇에
        # 노출된 147 m 인지 읽는 쪽이 알 수 없다.
        note += (f" · 대지경계선 {perim:.0f} m 중 옆 건물이 {reach_m:.1f} m 안에 있는"
                 f" 구간 {expo:.0f} m ({expo / perim:.0%})")
    elif par_m is None:
        note += " (필지를 얻지 못해 경계선을 걷지 못했다 — 필지 밖은 도달거리로만 걸렀다)"
    return schema.collection(out, "separation", note=note)


def lot_line(buildings_fc, site, sep=None):
    """**상대 건물이 없는 건물에 한해** 대지경계선까지의 거리(보조, 피난·방화규칙 제22조 제2항).

    「없을 때만」은 예전부터 이 함수의 설명이었지만 **코드가 지키지 않았다** — 모든 건물에
    한 줄씩 냈고, 그 줄이 보고서의 필지밖 표에 그대로 붙었다(공단동 150 은 33줄이 붙어 정작
    「둘레에 무엇이 있나」가 그 속에 묻혔다). 도달거리 안에 상대가 있는 건물은 제17조로 판정이
    나므로 다른 기준선까지의 거리를 덧붙일 이유가 없다 — 기준이 둘이면 읽는 사람이 어느
    것으로 판단할지 알 수 없다.

    `sep` 를 주면 그 결과에 이미 쌍이 있는 건물을 뺀다 — 그 쌍은 탐색반경 안에서 고른
    것이므로, 남는 것은 **60 m 안에 상대가 정말 없는 건물**이다. 안 주면(옛 호출) 전부 낸다.
    """
    from shapely.geometry import shape
    from shapely.ops import nearest_points, transform
    if not site.get("parcel"):
        return []
    paired = set()
    for f in (sep or {}).get("features") or []:
        p = f["properties"]
        if p.get("kind") == "lot_line":
            continue
        for b in (p.get("pair") or [])[:1]:
            paired.add(b)
    fwd, inv = _to_utm()
    par = transform(fwd.transform, shape(site["parcel"]))
    # 필지는 MultiPolygon 일 수 있다(분할된 지번). .exterior 는 Polygon 에만 있으므로
    # boundary 를 쓴다 — 안쪽 구멍 경계까지 포함되지만 대지경계선 판정에는 그쪽이 맞다.
    par = par.boundary
    out = []
    for f in buildings_fc.get("features") or []:
        if f["properties"]["bld_id"] in paired:
            continue
        g = transform(fwd.transform, shape(f["geometry"]))
        d = g.distance(par)
        fl, fl_src = _floors_of(f, site)
        v = rules.lot_line_verdict(d, fl)
        pa, pb = nearest_points(g, par)
        from shapely.geometry import LineString
        line = LineString([pa, pb]) if d > 0 else LineString([pa, pa])
        out.append(schema.feature(
            transform(inv.transform, line),
            schema.verdict_props(v, bld_id=f["properties"]["bld_id"],
                                 dist_m=round(float(d), 1), kind="lot_line",
                                 floors=[fl], floors_src=[fl_src]),
            fid=f"L:{f['properties']['bld_id']}"))
    return out
