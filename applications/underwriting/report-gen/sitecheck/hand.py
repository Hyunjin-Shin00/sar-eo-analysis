"""손보정 — **자동으로는 낼 수 없는 자리를 사람이 확인해 채우는 것.**

**이 파일에 값은 없다.** 값은 저장소 뿌리의 [[hand_writting.py]] 한 곳에만 있고, 여기에는
그것을 담는 그릇(`Hand`)과 적용하는 함수만 있다. 그렇게 가른 이유:

    run.py            모델 → 판정.  손보정 `TABLE_MODEL`   → out/
    demo.py           GT  → 판정.  손보정 `TABLE`         → out_gt/
    hand_writting.py  GT  → 판정.  손보정 `TABLE` + 손판   → demo/ · demo_cmp/

셋이 다 표를 읽지만 **표는 하나다.** 값이 두 곳에 흩어져 있으면 어떤 수치가 손을 탄 것인지
나중에 가릴 수 없다 — 실제로 예전에는 `settings.py` 에 넷, `tools/for_demo.py` 에 다섯이
나뉘어 있었고 `run.py` 는 그중 넷을 **자기도 모르게** 쓰고 있었다. 지금은 표를 열면 어느
주소에 무엇이 걸리는지 그 자리에서 보이고, **표에 없는 주소는 하나도 안 걸린다**(`NONE`).

모델 경로용 표가 따로인 이유는 `bld_id`(`N####`)가 창 안 기하 순서로 매기는 번호라, 옆 지번
건물의 집합이 다른 두 경로에서 같은 번호가 다른 건물을 가리키기 때문이다.

**채운 사실은 값에 남는다.** 모든 적용 함수가 `site.notes` 와 해당 Feature 의 속성에
「사람이 …했다」를 적는다. 종이만 본 사람도 무엇이 손으로 들어갔는지 읽을 수 있어야 한다.

**`bld_id` 로 가리키는 것은 지번(PNU)을 함께 적는다.** `N####` 는 창 안 기하 순으로 매기는
번호라([[steps/s1_building]] `label_features`) GT 나 창이 바뀌면 같은 번호가 다른 건물을
가리킬 수 있다. PNU 가 어긋나면 **조용히 엉뚱한 건물에 손대지 않고 건너뛰며 그 사실을 찍는다.**
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from sitecheck import schema


@dataclass(frozen=True)
class Hand:
    """한 주소분 손보정. 필드마다 뜻은 [[hand_writting.py]] 의 표 옆에 적혀 있다.

    빈 `Hand()` 는 「손보정 없음」이고, **표에 없는 주소가 받는 값**이다.
    """

    address: str = ""
    parcel_fix: tuple | None = None          # (동, 북) m — 대지 경계를 더 옮긴다
    ledger_fix: dict = field(default_factory=dict)       # {동 이름: 건축면적 ㎡}
    area_fix: dict = field(default_factory=dict)         # {동 이름: 판독 건축면적 ㎡}
    yard_shift: tuple = ()                   # ((Y0001, (동,북) m), …) — 적재 구역을 옮긴다
    yard_grow: tuple = ()                    # ((Y0001, (동,북) m), …) — 그 쪽으로 늘린다
    # {영상 key: 야적 판독 파일 경로} — 그 날짜의 판독을 **다른 폴더에서 가져온다**.
    # 영상 key 로 키를 두는 이유는 비교분석이 날짜마다 다른 판독을 쓸 수 있기 때문이다
    # (한 주소에 두 날짜). 경로는 저장소 뿌리 기준이다.
    yard_from: dict = field(default_factory=dict)
    yard_drop: tuple = ()                    # ("Y0002", …) — 판독된 적재 구역에서 뺀다
    # {영상 key: {추론 설정: 값}} — **이 물건 이 영상에서만** 추론 설정을 바꾼다.
    # 영상 전체에 거는 것은 [[settings.INFER_DINOV3_BY_SCENE]] 이고, 이쪽은 그 위에 얹는다.
    infer_fix: dict = field(default_factory=dict)
    # {영상 key: 다른 결과 파일} — 그 영상의 **옆 지번 건물 목록을 그 파일에서 가져온다.**
    neighbor_from: dict = field(default_factory=dict)
    ledger_drop: tuple = ()                  # (동 이름, …) — 대장에서 뺀다
    ledger_rename: dict = field(default_factory=dict)    # {옛 동: 새 동}
    neighbor_add: tuple = ()                 # ((설명, 경위도 링), …) — GT 에 없는 건물
    neighbor_drop: tuple = ()                # ((bld_id, PNU), …) — 옆 지번 목록에서 뺀다
    neighbor_shift: tuple = ()               # ((bld_id, PNU, (동,북) m), …)
    neighbor_grow: tuple = ()                # ((bld_id, PNU, (동,북) m), …) — 그 쪽으로 늘린다
    sep_also: tuple = ()                     # ((bld_id, PNU[, 우리 동 id]), …)
    sep_skip: tuple = ()                     # ((bld_id, PNU), …) — 이격 줄만 뺀다
    road_side: tuple = ()                    # ("북", …) — 도로라 이격 대상이 아닌 방향
    win_pad: float | None = None             # m — 그림 창 여백을 넓힌다

    def __bool__(self):
        return any((self.parcel_fix, self.ledger_fix, self.area_fix, self.yard_shift,
                    self.yard_grow,
                    self.ledger_drop, self.neighbor_add,
                    self.yard_from, self.yard_drop, self.infer_fix, self.neighbor_from,
                    self.neighbor_drop, self.neighbor_shift, self.neighbor_grow,
                    self.sep_also, self.sep_skip,
                    self.road_side, self.win_pad, self.ledger_rename))


NONE = Hand()       # 손보정 없음 — 표에 없는 주소가 받는 값


def of(table, address):
    """주소별 표에서 한 주소분을 꺼낸다. 없으면 `NONE`.

    표의 형태는 `{주소: {필드: 값}}` 이다 — [[hand_writting.py]] `TABLE`.
    """
    row = (table or {}).get(address)
    if not row:
        return NONE
    known = {f for f in Hand.__dataclass_fields__ if f != "address"}
    bad = set(row) - known
    if bad:
        # 오타를 조용히 삼키면 「적어 두었는데 안 먹는다」가 된다 — 그 상태가 제일 알기 어렵다.
        raise KeyError(f"{address}: 모르는 손보정 항목 {sorted(bad)} (쓸 수 있는 것: "
                       f"{sorted(known)})")
    return Hand(address=address, **row)


# ── 적용 ────────────────────────────────────────────────────────────────────
def parcel_fix(site, dxdy, *, verbose=False):
    """필지·인접필지를 사람이 정한 만큼 더 옮긴다. 옮겼으면 True.

    자동 편이 보정([[steps/parcel_bias.py]]) **위에** 얹는 것이다. 위성만으로는 대지 경계선을
    확정할 수 없고(담장·연석·포장 끝이 경계와 다르다), 자동 보정은 주변 수십 동의 평균이라
    이 필지 하나에서는 몇 m 어긋날 수 있다.

    **site 를 옮긴다** — 그림만 옮기면 면적·귀속·판정이 그림과 갈라진다.
    """
    if not dxdy or site.get("parcel_fix_m") is not None or not site.get("parcel"):
        return False
    dx, dy = float(dxdy[0]), float(dxdy[1])
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return False
    from pyproj import Transformer
    from shapely.affinity import translate
    from shapely.geometry import shape
    from shapely.ops import transform
    from sitecheck.steps import s0_locate
    fwd = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

    def move(g):
        return transform(inv.transform, translate(transform(fwd.transform, g), dx, dy))

    g = move(shape(site["parcel"]))
    site["parcel"] = g.__geo_interface__
    site["parcel_m2"] = s0_locate._parcel_area_m2(g)
    for nb in site.get("neighbors") or []:
        try:
            nb["geometry"] = move(shape(nb["geometry"])).__geo_interface__
        except Exception:                                    # noqa: BLE001
            pass
    site["parcel_fix_m"] = [dx, dy]
    site.setdefault("notes", []).append(
        f"대지 경계를 사람이 확인한 만큼 ({dx:+.0f},{dy:+.0f}) m 더 옮겼다 — 위성만으로는 "
        f"경계선을 확정할 수 없어 눈으로 맞춘 값이다")
    if verbose:
        print(f"  [대지경계] 수동 보정 ({dx:+.0f},{dy:+.0f}) m")
    return True


def ledger_fix(site, fix, *, verbose=False):
    """대장 건축면적을 사람이 넣은 값으로 갈아 넣는다. 바꿨으면 True.

    **건축면적만 바꾼다** — 연면적·층수·구조는 대장 그대로 둔다. 그쪽은 요율축이라 손대면
    뜻이 달라진다.
    """
    if not fix or site.get("ledger_fix"):
        return False
    hit = {}
    for b in site.get("ledger") or []:
        if b.get("dong") in fix:
            b["arch_area_m2"] = float(fix[b["dong"]])
            hit[b["dong"]] = b["arch_area_m2"]
    if not hit:
        return False
    site["ledger_fix"] = hit
    site.setdefault("notes", []).append(
        "건축물대장 건축면적을 데모용으로 사람이 넣은 값으로 바꿨다 — "
        + " · ".join(f"{k} {v:,.0f} ㎡" for k, v in hit.items())
        + ". 연면적·층수·구조·용도는 대장 그대로다")
    if verbose:
        print("  [대장] 건축면적 수동 설정 "
              + " · ".join(f"{k} {v:,.0f} ㎡" for k, v in hit.items()))
    return True


def win_pad(site, m, *, verbose=False):
    """그림 창의 여백(m)을 넓힌다. 넓혔으면 True.

    **site 에 싣는다** — 보고서는 값 파일을 디스크에서 다시 읽으므로([[report/single.py]]
    `build`) 인자로 넘기면 그 경로에서 끊긴다. 실린 값은 `demo.json` 에 그대로 남아, 종이의
    창이 왜 이 물건만 넓은지 값에서 되짚을 수 있다.

    창을 넓히는 것은 **그림에만** 닿는다 — 이격·면적·판정은 창과 무관하다. 다만 배지 번호
    (①②③)는 창 밖 건물에 붙지 않으므로([[draw.py]] `ext_index`) 표에 실릴 상대가 창 안에
    들어와야 종이의 번호와 지도의 번호가 같아진다.
    """
    if not m or site.get("win_pad_m") is not None:
        return False
    site["win_pad_m"] = float(m)
    # **기본값을 베끼지 않는다** — 여기 숫자를 적어 두면 `draw.WIN_PAD_M` 이 바뀐 날
    # 결과 파일에 남는 말만 옛 값이 된다(실제로 26 → 20 으로 바뀌었다).
    from sitecheck.draw import WIN_PAD_M
    site.setdefault("notes", []).append(
        f"그림 창 여백을 사람이 정한 {float(m):.0f} m 로 넓혔다(기본 {WIN_PAD_M:.0f} m) — "
        f"이격 상대가 기본 여백 밖에 있어 측정선이 종이에서 끊기고 배지를 놓을 자리가 "
        f"없었다. 값·판정은 창과 무관하다")
    if verbose:
        print(f"  [그림] 창 여백 {float(m):.0f} m (기본 {WIN_PAD_M:.0f} m)")
    return True


def ledger_rename(site, table, *, verbose=False):
    """대장의 **동 이름**을 판독 동 이름에 맞춰 갈아 넣는다. 바꿨으면 True.

    대장의 동 이름과 우리가 붙이는 이름(A동·B동)은 서로 다른 체계다 — 우리 것은 **건축면적
    큰 순**이고(설계서 BR-13), 대장은 등재 순서다. 보통은 눈에 안 거슬리는데, **둘 다 A·B·C 를
    쓰면서 가리키는 건물이 엇갈리면** 종이가 헷갈린다: 신당동 1187-2 는 판독 A동↔대장 C동,
    판독 B동↔대장 A동 이라 「A동」이 두 건물을 뜻했다(2026-08-25 지적).

    **동시에 바꾼다** — 「C동→A동, A동→B동」처럼 이름이 서로 자리를 바꾸므로, 하나씩 차례로
    바꾸면 먼저 바꾼 것을 두 번째 규칙이 또 잡는다.

    **짝짓기는 안 건드린다.** 대장 동과 판독 동을 잇는 것은 이름이 아니라 **면적**이고
    ([[steps/s4_ledger]] · 종이에도 「동 대응은 면적 기준 추정」이라 적혀 있다) 이 함수는 적히는
    글자만 바꾼다. 바꾼 사실은 `site.notes` 에 남는다.
    """
    if not table or site.get("ledger_rename"):
        return False
    rows = site.get("ledger") or []
    hit = {b.get("dong"): table[b["dong"]] for b in rows if b.get("dong") in table}
    if not hit:
        return False
    for b in rows:
        if b.get("dong") in hit:
            b["dong"] = hit[b["dong"]]
    site["ledger_rename"] = hit
    site.setdefault("notes", []).append(
        "건축물대장의 동 이름을 판독 동 이름에 맞춰 바꿨다 — "
        + " · ".join(f"{k}→{v}" for k, v in hit.items())
        + ". 대장과 판독을 잇는 것은 이름이 아니라 면적이므로 짝짓기·면적·판정은 그대로다")
    if verbose:
        print("  [대장] 동 이름 " + " · ".join(f"{k}→{v}" for k, v in hit.items()))
    return True


def neighbor_add(site, near, want, *, verbose=False):
    """GT 에 없는 옆 지번 건물을 링으로 이어 붙인다. 더한 개수를 돌려준다.

    GT 는 학습·평가용이라 **공장 본동 위주**고 소형 부속·창고·차양은 건너뛴 자리가 있다.
    GT 를 그대로 쓰는 길에서는 GT 에 없는 것이 이격 상대로 나올 방법이 아예 없다.

    **id 는 붙인 뒤에 더한다** — `label_features` 가 기하 순으로 `N####` 를 매긴 다음 그
    뒤에 이어 붙이므로 기존 번호가 밀리지 않는다(빼는 쪽과 같은 규약).

    **사람이 그린 것임을 값에 남긴다** — `source: "hand"` · `owner: null`(지번을 모른다) ·
    `registered: false`. 건물 폴리곤은 이격 거리·면적·번호를 직접 만드는 값이라 야적 구역보다
    출처가 더 중요하다.
    """
    if not want:
        return 0
    from shapely.geometry import Polygon, shape
    from shapely.ops import transform
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    hub = shape(site["parcel"]).centroid if site.get("parcel") else None
    own = [transform(fwd.transform, shape(f["geometry"]))
           for f in (site.get("_own_geoms") or [])]
    n0 = max((int(f["properties"]["bld_id"][1:]) for f in near
              if str(f["properties"].get("bld_id") or "").startswith("N")), default=0)
    made = []
    for i, (why, ring) in enumerate(want, 1):
        g = Polygon(ring)
        if not g.is_valid:
            g = g.buffer(0)
        gm = transform(fwd.transform, g)
        bid = f"N{n0 + i:04d}"
        c = g.centroid
        made.append(schema.feature(g, {
            "score": None, "source": "hand", "merged_from": 1,
            # 면적 눈금은 [[steps/s1_building]] `_area_m2` 와 같다(정수 ㎡) — 한쪽만
            # 0.1 자리를 가지면 동별 면적을 더한 값과 합계가 갈린다.
            "arch_area_m2": float(round(gm.area)),
            "in_parcel_frac": 0.0, "owner": None, "owner_by": "hand",
            "registered": False,
            "level": None, "label": None, "reason": None, "basis": None,
            "bld_id": bid, "role": "neighbor",
            "az_deg": (round(math.degrees(math.atan2(c.x - hub.x, c.y - hub.y)) % 360.0, 1)
                       if hub is not None else None),
            "dist_m": (round(min(gm.distance(o) for o in own), 2) if own else None),
            "dong": None,
            "hand_note": f"GT 에 없는 건물을 사람이 그려 넣었다 — {why}",
        }, fid=bid))
    near.extend(made)
    site.setdefault("notes", []).append(
        f"GT 에 없는 옆 지번 건물 {len(made)}동을 사람이 그려 넣었다("
        + " · ".join(f["properties"]["bld_id"] for f in made)
        + ") — GT 는 공장 본동 위주라 소형 부속이 빠져 있다. 이격 상대로만 쓰고 대장 대조에는 "
          "쓰지 않는다([[hand_writting.py]] `neighbor_add`)")
    if verbose:
        for f in made:
            p = f["properties"]
            print(f"  [건물추가] {p['bld_id']} {p['arch_area_m2']:.0f} ㎡ · 우리 동까지 "
                  f"{p['dist_m']} m · {p['hand_note']}")
    return len(made)


def neighbor_from(site, blds, path, *, verbose=False):
    """옆 지번 건물 목록을 **다른 결과 파일에서** 통째로 가져온다. 새 목록을 돌려준다.

    왜 필요한가. 두 촬영일을 견주는 문서에서 **옆 지번 건물은 두 날짜에 같아야 한다** — 그
    사이에 헐리거나 서지 않았다면. 그런데 모델은 날짜마다 그 영상에서 새로 뽑으므로 집합이
    흔들린다(실측 호산동 702-5: 1차 30동 · 2차 28동). 그러면 이격 표의 줄이 통째로
    생겼다 사라지고, 그것이 「변화」로 인쇄된다 — 건물이 변한 것이 아니라 **검출이 변한** 것인데.
    이 지번 건물은 그대로 두고 **옆 지번만** 한쪽 날짜의 것으로 맞춘다(사용자 결정, 2026-08-27).

    **두 날짜의 프레임 차이만큼 옮겨서 가져온다.** 가져온 폴리곤은 **그 날짜의 지도 좌표**
    인데, 두 날짜는 영상 지오레퍼런스 보정과 2차 정합을 각자 받으므로 같은 건물이 1~2 m
    어긋난 자리에 앉는다(실측 2026-08-27 신당동: 이 지번 두 동이 통째로 서쪽 1.34 m ·
    남쪽 1.60 m — 면적은 773→780 ㎡ 로 그대로다). 그대로 가져오면 그 어긋남이 **이격 거리의
    변화**로 인쇄된다(실측: 서쪽 상대 둘이 2.8 m → 0.8 m).

    그래서 **이 지번 건물로 프레임 차이를 재서** 그만큼 옮긴다 — 두 날짜의 같은 건물이
    같은 자리에 앉게 하는 것이고, [[steps/gt_parallax.py]] 가 이식한 GT 에 하는 것과 같은
    판단이다(재는 것은 이 지번, 옮기는 것은 가져온 상대 전부 — 그래야 상대끼리의 거리가
    보존된다). 동 이름으로 짝지어 중심점 차이의 평균을 쓴다.

    **번호는 가져온 그대로 두고, 거리·방위만 다시 잰다.**
      · 번호를 다시 매기면 안 된다 — 가져온 목록에는 사람이 그려 넣은 건물이 섞여 있고
        (그쪽에서는 번호를 붙인 **뒤에** 이어 붙였다) 다시 매기면 기하 순서로 끼어들어
        **뒤의 번호가 전부 밀린다**. 그러면 손보정 표의 `N####` 가 다른 건물을 가리킨다
        (실측 2026-08-27: `sep_also` 의 N0018 이 엉뚱한 지번을 물어 건너뛰었다).
      · 거리·방위는 다시 재야 한다 — 가져온 값은 **그 날짜의** 이 지번 건물에서 잰 것이다.
    """
    import json
    from pathlib import Path as _P

    from shapely.geometry import shape

    from sitecheck import schema as _schema
    from sitecheck.steps import s1_building as _S1
    p = _P(path)
    if not p.is_absolute():
        p = _P(__file__).resolve().parents[1] / p
    if not p.exists():
        print(f"  [!] 옆 지번을 가져올 파일이 없다: {p}", flush=True)
        return None
    src = json.loads(p.read_text("utf-8"))
    got = (src.get("context") or {}).get("buildings_near", {}).get("features") or []
    from shapely.affinity import translate as _mv
    from shapely.ops import transform as _tf
    from pyproj import Transformer as _Tr
    fwd = _Tr.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    own = [_tf(fwd.transform, shape(f["geometry"])) for f in (blds.get("features") or [])]
    hub = shape(site["parcel"]).centroid if site.get("parcel") else None

    # ── 프레임 차이를 이 지번 건물로 잰다(경위도로 옮길 것이라 경위도에서 잰다)
    here = {(f["properties"] or {}).get("dong"): shape(f["geometry"]).centroid
            for f in (blds.get("features") or [])}
    there = {(f["properties"] or {}).get("dong"): shape(f["geometry"]).centroid
             for f in ((src.get("layers") or {}).get("buildings") or {}).get("features") or []}
    pairs = [(here[d], there[d]) for d in here if d and d in there]
    dx = sum(a.x - b.x for a, b in pairs) / len(pairs) if pairs else 0.0
    dy = sum(a.y - b.y for a, b in pairs) / len(pairs) if pairs else 0.0
    if pairs:
        gm0 = _tf(fwd.transform, shape(got[0]["geometry"])) if got else None
        gm1 = _tf(fwd.transform, _mv(shape(got[0]["geometry"]), dx, dy)) if got else None
        mv_m = (gm1.centroid.distance(gm0.centroid) if gm0 is not None else 0.0)
        site.setdefault("notes", []).append(
            f"가져온 옆 지번을 {mv_m:.2f} m 옮겼다 — 두 촬영일의 지도 프레임이 그만큼 어긋나 "
            f"있다(이 지번 {len(pairs)}동의 중심점으로 쟀다). 건물이 움직인 것이 아니라 영상 "
            f"보정·2차 정합이 날짜마다 달라서 생기는 차이라, 안 옮기면 그것이 이격 변화로 나간다")
        if verbose:
            print(f"  [옆지번] 프레임 차이 {mv_m:.2f} m 를 이 지번 {len(pairs)}동으로 재어 "
                  f"가져온 상대를 그만큼 옮긴다", flush=True)

    near = []
    for f in got:
        q = dict(f.get("properties") or {})
        g = _mv(shape(f["geometry"]), dx, dy)
        gm = _tf(fwd.transform, g)
        c = g.centroid
        bid = q.get("bld_id")
        near.append(_schema.feature(g, {
            "score": q.get("score"), "source": q.get("source") or "model",
            "merged_from": q.get("merged_from") or 1,
            "arch_area_m2": q.get("arch_area_m2"),
            "in_parcel_frac": q.get("in_parcel_frac"), "owner": q.get("owner"),
            "owner_by": q.get("owner_by"), "registered": q.get("registered"),
            "level": None, "label": None, "reason": None, "basis": None,
            "bld_id": bid, "role": "neighbor", "dong": None,
            "az_deg": (round(math.degrees(math.atan2(c.x - hub.x, c.y - hub.y)) % 360.0, 1)
                       if hub is not None else None),
            "dist_m": (round(min(gm.distance(o) for o in own), 2) if own else None),
            "hand_note": (q.get("hand_note") or "")
            + (" · " if q.get("hand_note") else "")
            + f"옆 지번을 {p.parent.parent.name}/{p.parent.name} 에서 가져왔다",
        }, fid=bid))
    site.setdefault("notes", []).append(
        f"옆 지번 건물 {len(near)}동을 {p.parent.parent.name}/{p.parent.name} 의 결과에서 "
        f"가져왔다 — 두 촬영일에서 **같은 상대**를 보려는 것이다(검출이 날짜마다 흔들리면 "
        f"줄이 생겼다 사라져 그것이 변화로 읽힌다). 거리·방위·번호는 이 날짜의 건물에서 다시 쟀다")
    if verbose:
        print(f"  [옆지번] {len(near)}동을 {p.parent.parent.name}/{p.parent.name} 에서 가져왔다",
              flush=True)
    return near


def _owner_of(near):
    return {(f["properties"] or {}).get("bld_id"): (f["properties"] or {}).get("owner")
            for f in near or []}


def sep_also(want, near, *, verbose=False):
    """이격 상대 보충을 이번 실행의 `bld_id` 로 푼다 — **지번이 맞는 것만.**

    필지 밖 줄은 대지경계선 구간을 이긴 상대만 나오는데([[steps/s3_separation]]), 두 상대에게
    끼인 건물은 아무 자리도 못 이겨 표에서 빠진다. 눈으로 보면 분명히 마주 선 건물이라 더한다.

    세 번째 값이 있으면 **우리 동을 지정**한다(없으면 가장 가까운 동이 자동으로 잡힌다).
    """
    if not want:
        return ()
    owner = _owner_of(near)
    ids = set(owner)
    out = []
    for row in want:
        bid, pnu, own_id = (tuple(row) + (None,))[:3] if len(row) < 3 else tuple(row)
        if bid not in ids:
            print(f"  [!] 이격 보충 {bid} 을 건너뛴다 — 그 id 의 건물이 없다", flush=True)
            continue
        if owner.get(bid) != pnu:
            print(f"  [!] 이격 보충 {bid} 을 건너뛴다 — 그 id 의 지번이 "
                  f"{owner.get(bid)} (적어 둔 값 {pnu})", flush=True)
            continue
        out.append(bid if own_id is None else (bid, own_id))
    if out and verbose:
        print("  [이격] 손으로 더하는 상대 "
              + " · ".join(b if isinstance(b, str) else f"{b[0]}↔{b[1]}" for b in out))
    return tuple(out)


def sep_skip(want, near, *, verbose=False):
    """이격 후보에서만 빼는 것 — **그리기는 남긴다.**

    `neighbor_drop` 은 옆 지번 목록에서 아예 빼서 지도에도 안 그린다. 이쪽은 「저기 건물은
    있는데 이 줄은 싣지 않기로 했다」를 말해야 하는 자리다.

    **여기 있는 id 가 `sep_also` 에도 있을 수 있다.** 빼는 것은 경계선 걷기가 자동으로 내는
    줄이고 더하는 것은 사람이 고른 쌍이라, 둘이 같은 건물을 가리켜도 어긋나지 않는다.
    """
    if not want:
        return ()
    owner = _owner_of(near)
    out = []
    for bid, pnu in want:
        if bid in owner and owner.get(bid) == pnu:
            out.append(bid)
        else:
            print(f"  [!] 이격 제외 {bid} 을 건너뛴다 — 그 id 의 지번이 "
                  f"{owner.get(bid)} (적어 둔 값 {pnu})", flush=True)
    if out and verbose:
        print(f"  [이격] 후보에서 빼는 상대: {', '.join(out)} (지도에는 그려진다)")
    return tuple(out)


def yard_drop(yd, want, *, site=None, verbose=False):
    """판독된 적재 구역에서 **사람이 확인해 뺀다**. 뺀 개수를 돌려준다.

    VLM 이 한 무더기를 **둘로 갈라 내는** 일이 있다 — 실측 구미 공단동 293-15: 마당 남동쪽
    한 더미가 Y0001(34.2 m) · Y0002(35.1 m) 두 구역으로 나왔다. 눈으로 하나인 것을 종이가
    둘로 세면 개수가 사실과 다르다.

    **`Y####` 는 기하 순 번호라 판독이 바뀌면 다른 구역을 가리킬 수 있다** — 그래서 뺀 것을
    거리·분류까지 찍고 `site.notes` 에 남긴다. 못 찾은 id 도 말한다(조용히 지나가면 판독이
    바뀐 날 「뺐다고 적었는데 그대로 있는」 종이가 나온다).

    **값 파일에서 지운다** — 이격의 `sep_skip` 처럼 「지도에는 그린다」가 아니다. 한 더미를
    둘로 센 것을 하나로 고치는 일이라, 남겨 두면 그림에도 표에도 둘로 남는다.
    """
    want = tuple(want or ())
    if not want:
        return 0
    keep, gone = [], []
    for f in yd.get("features") or []:
        q = f["properties"]
        if q.get("yard_id") in want:
            gone.append(q)
        else:
            keep.append(f)
    for yid in want:
        if not any(q.get("yard_id") == yid for q in gone):
            print(f"  [!] 적재 구역 {yid} 을 못 찾았다 — 판독이 바뀌었을 수 있다", flush=True)
    if not gone:
        return 0
    yd["features"] = keep
    yd["count"] = len(keep)
    say = " · ".join(f"{q.get('yard_id')}"
                     f"({q.get('dist_to_building_m')} m · {q.get('cls_ko') or q.get('cls')})"
                     for q in gone)
    yd["note"] = ((yd.get("note") or "") + f" · 사람이 확인해 뺀 구역 {len(gone)}건({say})").strip(" ·")
    if verbose:
        print(f"  [야적] 사람이 확인해 빼는 구역: {say}")
    if site is not None:
        site.setdefault("notes", []).append(
            f"적재 구역 {say} 을 사람이 확인해 뺐다 — 판독이 한 무더기를 둘로 갈라 낸 자리다. "
            f"개수·판정·그림·표는 뺀 뒤의 값으로 낸다")
    return len(gone)


def area_fix(blds, fix, *, site=None, verbose=False):
    """**판독 건축면적**을 사람이 넣은 값으로 갈아 넣는다. 바꾼 개수를 돌려준다.

    `ledger_fix` 의 짝이다 — 그쪽은 **대장**의 건축면적, 이쪽은 **위성이 읽은** 건축면적이다.
    지붕 일부가 그늘에 들거나 차양에 가려 판독 면적이 실제보다 작게 잡히는데, 원본에서 지붕
    끝을 짚을 수 있으면 그 값을 적어 둔다.

    **폴리곤은 그대로다.** 그래서 종이의 숫자와 지도의 도형이 그만큼 어긋난다 — 옆 지번
    건물은 도형을 늘려(`neighbor_grow`) 면적을 다시 재지만, 이 지번 건물은 지도에서 그 동의
    윤곽이 곧 판독 결과라 늘리면 「위성이 이렇게 읽었다」가 거짓이 된다. 숫자만 고치고 **고친
    사실을 값에 남긴다**(`area_fix` 속성 · `site.notes`) — 종이만 본 사람도 어느 수치가 사람
    손을 탔는지 읽을 수 있어야 한다.
    """
    if not fix:
        return 0
    hit = {}
    for f in blds.get("features") or []:
        q = f["properties"]
        if q.get("dong") in fix:
            q["area_fix_from"] = q.get("arch_area_m2")
            q["arch_area_m2"] = float(fix[q["dong"]])
            hit[q["dong"]] = (q["area_fix_from"], q["arch_area_m2"])
    if not hit:
        return 0
    if site is not None:
        site["area_fix"] = {k: v[1] for k, v in hit.items()}
        site.setdefault("notes", []).append(
            "위성 판독 건축면적을 사람이 확인한 값으로 바꿨다 — "
            + " · ".join(f"{k} {a:,.0f} → {b:,.0f} ㎡" for k, (a, b) in hit.items())
            + ". 폴리곤은 그대로라 지도의 윤곽과 이 숫자는 그만큼 다르다")
    if verbose:
        print("  [건물] 판독 건축면적 수동 설정 "
              + " · ".join(f"{k} {a:,.0f} → {b:,.0f} ㎡" for k, (a, b) in hit.items()))
    return len(hit)


def yard_shift(yd, want, *, blds=None, site=None, verbose=False):
    """적재 구역을 **통째로 옮긴다**. 옮긴 개수를 돌려준다.

    VLM 이 더미의 자리를 한쪽으로 치우쳐 잡는 일이 있다 — 실측 구미 공단동 293-15: 창백한
    더미보다 상자가 오른쪽으로 밀려 있었다. **모양과 넓이는 그대로 두고 자리만** 옮기는 것이
    맞는 손질이다. 크기가 모자란 것이 아니라 자리가 어긋난 것이기 때문이다.

    한때 「그 쪽으로 늘리기」로 손봤는데(2026-08-27), 늘리면 잡힌 쪽 끝이 더미 밖으로 더
    나가고 넓이도 실제보다 커진다. 늘리기는 **지붕의 일부만 잡힌 옆 지번 건물**에나 맞는
    손질이다([[steps/s1_building]] `grow_neighbors`) — 그쪽은 못 잡은 쪽을 채우는 것이라
    잡힌 자리를 두어야 하고, 이쪽은 통째로 어긋난 것이라 통째로 옮겨야 한다.

    **인접 건물까지의 거리와 판정을 다시 낸다** — 옮긴 자리가 건물 쪽이면 거리가 바뀌고
    판정이 갈릴 수 있다. 판정을 손으로 고쳐 쓰지 않고 `rules.yard_verdict` 에 다시 묻는다.
    """
    want = dict(want or ())
    if not want:
        return 0
    from shapely.affinity import translate
    from shapely.geometry import shape
    from shapely.ops import transform
    from pyproj import Transformer
    from sitecheck import rules
    fwd = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    done = {}
    for f in yd.get("features") or []:
        q = f["properties"]
        d = want.get(q.get("yard_id"))
        if not d:
            continue
        u = translate(transform(fwd.transform, shape(f["geometry"])),
                      float(d[0]), float(d[1]))
        f["geometry"] = transform(inv.transform, u).__geo_interface__
        q["shift_m"] = [float(d[0]), float(d[1])]
        # 넓이는 평행이동이라 그대로다 — 다시 적지 않는다.
        gs = [transform(fwd.transform, shape(b["geometry"]))
              for b in ((blds or {}).get("features") or [])]
        if gs:
            dd = round(float(min(u.distance(g) for g in gs)), 1)
            q["dist_to_building_m"] = dd
            v = rules.yard_verdict(dd, q.get("cls"))
            q["level"], q["label"] = v["level"], v["label"]
            q["reason"], q["basis"] = v["reason"], v["basis"]
            q["level_rank"] = rules.LEVEL_ORDER.get(v["level"], 99)
        done[q["yard_id"]] = (float(d[0]), float(d[1]))
    for yid in want:
        if yid not in done:
            print(f"  [!] 적재 구역 {yid} 을 못 찾았다 — 판독이 바뀌었을 수 있다", flush=True)
    if not done:
        return 0
    if site is not None:
        site["yard_shift"] = {k: list(v) for k, v in done.items()}
        site.setdefault("notes", []).append(
            "적재 구역 " + " · ".join(f"{k} ({v[0]:+.1f},{v[1]:+.1f}) m" for k, v in done.items())
            + " 를 사람이 확인해 옮겼다 — 판독이 더미보다 한쪽으로 치우쳐 잡은 자리다. "
            "모양·넓이는 그대로이고, 인접 건물까지의 거리와 판정은 옮긴 자리에서 다시 낸다")
    if verbose:
        print("  [야적] 사람이 확인해 옮기는 구역: "
              + " · ".join(f"{k} ({v[0]:+.1f},{v[1]:+.1f}) m" for k, v in done.items()))
    return len(done)


def yard_grow(yd, want, *, blds=None, site=None, verbose=False):
    """적재 구역을 **그 쪽으로 늘린다**. 늘린 개수를 돌려준다.

    `yard_shift` 가 자리를 옮기는 것이라면 이쪽은 **크기를 키우는 것**이다 — 판독이 더미의
    한쪽 끝을 놓쳐 상자가 짧게 잡혔을 때 쓴다. 늘리는 방법은 폴리곤을 그만큼 옮긴 사본과
    합치는 것이라 **잡힌 자리는 그대로 두고 그 방향만 자란다.**

    합친 도형은 **최소 외접 사각형으로 다듬는다** — 적재 구역은 판독이 내는 도형이 사각형이고
    그림도 그렇게 읽히는데, 살짝 기울어진 사각형을 축과 나란히 밀어 합치면 이어붙은 자리에
    계단 자국이 남는다.

    **넓이·거리·판정을 다시 낸다** — 넓이는 커지고, 늘린 자리가 건물 쪽이면 거리가 줄어 판정이
    갈릴 수 있다. 판정은 손으로 적지 않고 `rules.yard_verdict` 에 다시 묻는다.
    """
    want = dict(want or ())
    if not want:
        return 0
    from shapely.affinity import translate
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    from pyproj import Transformer
    from sitecheck import rules
    fwd = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    done = {}
    for f in yd.get("features") or []:
        q = f["properties"]
        d = want.get(q.get("yard_id"))
        if not d:
            continue
        m = transform(fwd.transform, shape(f["geometry"]))
        u = unary_union([m, translate(m, float(d[0]), float(d[1]))])
        if u.geom_type != "Polygon":
            print(f"  [!] 적재 구역 늘리기 {q.get('yard_id')} 을 건너뛴다 — 도형이 갈라진다",
                  flush=True)
            continue
        u = u.minimum_rotated_rectangle
        f["geometry"] = transform(inv.transform, u).__geo_interface__
        q["grow_m"] = [float(d[0]), float(d[1])]
        q["area_m2"] = round(float(u.area), 1)
        gs = [transform(fwd.transform, shape(b["geometry"]))
              for b in ((blds or {}).get("features") or [])]
        if gs:
            dd = round(float(min(u.distance(g) for g in gs)), 1)
            q["dist_to_building_m"] = dd
            v = rules.yard_verdict(dd, q.get("cls"))
            q["level"], q["label"] = v["level"], v["label"]
            q["reason"], q["basis"] = v["reason"], v["basis"]
            q["level_rank"] = rules.LEVEL_ORDER.get(v["level"], 99)
        done[q["yard_id"]] = (float(d[0]), float(d[1]))
    for yid in want:
        if yid not in done:
            print(f"  [!] 적재 구역 {yid} 을 못 찾았다 — 판독이 바뀌었을 수 있다", flush=True)
    if not done:
        return 0
    if site is not None:
        site["yard_grow"] = {k: list(v) for k, v in done.items()}
        site.setdefault("notes", []).append(
            "적재 구역 " + " · ".join(f"{k} ({v[0]:+.1f},{v[1]:+.1f}) m" for k, v in done.items())
            + " 를 사람이 확인해 그 방향으로 늘렸다 — 판독이 더미의 한쪽 끝을 놓친 자리다. "
            "넓이·인접 건물까지의 거리·판정은 늘린 도형으로 다시 낸다")
    if verbose:
        print("  [야적] 사람이 확인해 늘리는 구역: "
              + " · ".join(f"{k} ({v[0]:+.1f},{v[1]:+.1f}) m" for k, v in done.items()))
    return len(done)
