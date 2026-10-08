"""주소 → 네 판정. **진입점 셋이 같이 지나는 한 길.**

    run.py            source="model"   손보정 `TABLE_MODEL`  out/<주소>/result.json
    demo.py           source="gt"      손보정 있음        out_gt/<주소>/demo.json
    hand_writting.py  source="gt"      손보정 있음        demo/<주소>/demo.json · demo_cmp/

**갈리는 것은 딱 두 가지다** — 건물 폴리곤을 어디서 얻는가(`source`), 사람이 확인한 값을
얹는가(`hand`). 그 밖의 것(주소 해석 · 정합 · 야적 판독 · 이격 · 대장 대조 · 저장 · 그림 ·
보고서)은 **전부 이 파일 하나**를 지난다.

예전에는 `run.py` 와 `tools/for_demo.py` 가 각자 이 순서를 적어 두고 있었다. 「같은 코드를
지난다」고 문서에 적혀 있었지만 실제로는 여덟 군데가 갈려 있었고, 그중 넷은 **`run.py` 도
모르게 손보정을 쓰고 있던 것**이었다(`ROAD_SIDE` · `NEIGHBOR_DROP` · `NEIGHBOR_SHIFT` ·
`LEDGER_DROP` 이 `settings.py` 에 있었다). 두 곳에 적어 두면 같은 물건이 도구마다 다른 값을
내고, 그때 어느 쪽이 맞는지 사후에 알 수 없다.

**값 파일 이름만 갈라 둔다**(`result.json` / `demo.json`). 폴더만 보고 그 값이 모델에서
나왔는지 GT 에서 나왔는지 알 수 있어야 하기 때문이다 — 값 자체는 `provenance.model.building`
에도 적히지만 파일 이름이 먼저 눈에 든다.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from sitecheck import console as con
from sitecheck import hand as H
from sitecheck import pipeline
from sitecheck import schema
from sitecheck import settings as config
from sitecheck.naming import slug
from sitecheck.steps import align, georef, parcel_bias, s0_locate, s1_building

SOURCES = ("model", "gt")
RESULT_NAME = {"model": "result.json", "gt": "demo.json"}
# 추론 캐시 · `provenance.tag` 의 앞머리. 길마다 다르게 두는 이유는 **모델 추론 캐시가
# 섞이면 안 되기** 때문이다 — GT 로 낸 결과 옆에 모델 캐시가 같은 이름으로 앉으면 어느
# 것이 무엇인지 파일 이름으로 가릴 수 없다.
TAG = {"model": "sitecheck", "gt": "demo"}


def load_site(address, out_dir=None, *, stored=True, scene=None, ledger_drop=()):
    """site — 이미 있는 것을 먼저 쓰고, 없으면 주소를 새로 해석해 **결과 폴더에 남긴다.**

    같은 주소를 여러 번 그릴 때(그림을 고칠 때마다) V-World 와 건축물대장을 다시 두드릴
    이유가 없다 — 필지·대장·인접필지 대장은 그 사이 바뀌지 않는다. 인접 필지 대장은 주소
    하나에 수십 건이라 이 캐시가 재실행 시간을 분 단위에서 초 단위로 줄인다.

    순서: `out/<주소>/result.json`(모델 경로가 낸 것) → `<결과폴더>/_site.json` → 새로 해석.

    `stored=False` 면 캐시를 보지 않는다 — `run.py` 의 기본값이다. 모델 경로는 매번 새로
    해석해도 느리지 않고, 「저장본을 썼나」가 결과에 섞이지 않는 편이 낫다.
    """
    if stored:
        p = config.OUT / slug(address) / "result.json"
        if p.exists():
            site = json.loads(p.read_text("utf-8"))["site"]
            georef.migrate(site)
            # **장면을 지정했으면 그 장면의 site 만 쓴다** — 저장본은 좌표로 고른 장면(같은
            # 지역의 1차 영상)이라, 두 촬영일을 견주는 실행에서 그대로 쓰면 두 날짜가 같은
            # 영상을 본다.
            if not scene or (site.get("scene") or {}).get("key") == scene:
                site.setdefault("address", address)
                return site, f"저장된 {p.parent.name}/result.json 의 site"
        cache = (Path(out_dir) / "_site.json") if out_dir else None
        if cache is not None and cache.exists():
            site = json.loads(cache.read_text("utf-8"))
            # 옮겼으면 **캐시도 다시 쓴다** — 안 쓰면 옛 좌표와 옛 key(`vector_shift_*`)가
            # 디스크에 남아, 다음에 이 파일을 읽는 사람이 어느 프레임인지 다시 따져야 한다.
            if georef.migrate(site):
                cache.write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")
            if not scene or (site.get("scene") or {}).get("key") == scene:
                site.setdefault("address", address)
                return site, "결과 폴더에 저장된 site(_site.json)"
    site = s0_locate.run(address, scene=scene, ledger_drop=ledger_drop)
    cache = (Path(out_dir) / "_site.json") if (out_dir and stored) else None
    if cache is not None and not site.get("error"):
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")
    return site, "주소를 새로 해석했다(V-World · 건축물대장)"


def footprints_near(site, *, pad_deg=0.0012):
    """필지 주변의 GIS건물통합정보 행 — **지번을 가리지 않고** 다 가져온다.

    정합을 보이는 데 쓴다. 이 지번으로 등록된 기하가 아예 없는 필지가 흔한데(실측 14곳 중
    구미 293-25 등), 그때 이 지번만 그리면 빈 패널이 나와 '정합을 확인했다'가 아니라
    '아무것도 안 보인다'가 된다. **주변 footprint 가 지붕에 얹히는 것이 곧 정합의 증거**다.
    """
    try:
        from shapely.geometry import shape
        from sitecheck.vendor import gisdb
        # **조회한 좌표 그대로** — 영상 편이는 영상 쪽에서 고쳤다([[steps/georef.py]]).
        return gisdb.near(shape(site["parcel"]).buffer(pad_deg).bounds)
    except Exception:                                        # noqa: BLE001
        return []


def _prepare(site, hand, *, say):
    """site 를 판정에 쓸 상태로 맞춘다 — **저장본이든 새로 해석한 것이든 같은 상태로.**

    `s0_locate.run` 은 이 셋을 이미 걸지만, 저장본은 그 보정을 넣기 전에 만든 것일 수 있다.
    전부 **멱등**이라 두 번 걸어도 같은 결과다(각자 `site` 에 남긴 자국을 보고 지나간다).

    **사람이 넣은 값은 찍고 자동 보정은 `--detail` 에서만 찍는다.** 앞은 결과를 읽는 사람이
    알아야 하는 것이고, 뒤는 알고 싶을 때 `site.notes` 에서 읽으면 되는 것이다. 깊은 자리의
    `verbose=` 에 `deep` 을 넘기는 이유도 같다 — 그쪽이 스스로 찍으면 여기서 찍는 줄과
    같은 말이 두 번 나온다(예전에 대장 뺀 동이 그랬다).
    """
    deep = con.on(con.DETAIL)
    if s0_locate.apply_ledger_drop(site, hand.ledger_drop, verbose=deep):
        say.sub(f"대장에서 사람이 확인해 뺀 동 {' · '.join(site['ledger_drop'])}")
    # 이름 바꾸기는 **빼기 다음**이다 — 빼는 목록은 대장에 적힌 원래 이름으로 적어 두었다.
    if H.ledger_rename(site, hand.ledger_rename, verbose=deep):
        say.sub(f"대장 동 이름 {site['ledger_rename']}")
    # 없는 채로 지나가면 건물·야적 좌표가 영상 편이만큼 밀린 채로 나간다.
    if not site.get("georef"):
        georef.apply(site, verbose=deep)
    g = site.get("georef") or {}
    if g.get("applied"):
        say.detail(f"영상 좌표 보정 {g['offset_m']} m (동,북) 되돌림 · {g.get('src')}")
    # 필지가 24 m 밀린 채로 그리면 이격·야적 판정이 남의 땅 위에서 나온다.
    if parcel_bias.apply(site, verbose=deep):
        say.detail(f"필지 레이어 편이 {site['parcel_bias_m']} m 보정")
    if H.parcel_fix(site, hand.parcel_fix, verbose=deep):
        say.sub(f"대지 경계 수동 보정 {site['parcel_fix_m']} m")
    # 대장 건축면적 수동 설정은 **판정을 내기 전에** — 값·그림·보고서가 한 숫자를 쓴다
    # (`s4_ledger` 는 `site.ledger` 를 읽는다).
    if H.ledger_fix(site, hand.ledger_fix, verbose=deep):
        say.sub(f"대장 건축면적 수동 설정 {site['ledger_fix']}")
    # 그림 창 여백 — 값·판정에는 안 닿고 그림에만 닿는다. site 에 싣는 이유는 보고서가 값
    # 파일을 디스크에서 다시 읽기 때문이다([[hand.py]] `win_pad`).
    if H.win_pad(site, hand.win_pad, verbose=deep):
        say.sub(f"그림 창 여백 {site['win_pad_m']:.0f} m")


def _buildings_model(site, *, hand, tag, gpu, reuse, mark, say):
    """건물 출처 ① 모델 — 추론 → **2차 정합** → 귀속.

    순서가 중요하다: 2차 정합은 영상 지오레퍼런스를 조금 더 되돌리는데, 그러면 영상에서 나온
    폴리곤 좌표도 같이 움직인다. 귀속을 먼저 하면 아직 덜 맞은 좌표로 임자를 가른 셈이 된다.
    """
    raw, ens_note = s1_building.predict(site, tag=tag, gpu=gpu, reuse=reuse,
                                        infer_fix=hand.infer_fix)
    n0 = len(site.get("notes") or [])
    moved = align.refine(site, [p for p, _s in raw])
    raw = [(g, s0) for g, (_p, s0) in zip(moved, raw)]
    for n in (site.get("notes") or [])[n0:]:
        say.detail(n)
    _mark_align(site, mark)
    blds, near = s1_building.attribute(site, raw, ens_note,
                                       drop=hand.neighbor_drop, shift=hand.neighbor_shift,
                                       grow=hand.neighbor_grow)
    # **옆 지번을 다른 날짜의 것으로 갈아 끼운다**([[hand.py]] `neighbor_from`). 이 지번
    # 건물은 그대로 두고 상대만 맞춘다 — 두 촬영일에서 같은 상대를 봐야 이격 표의 줄이
    # 생겼다 사라지지 않는다.
    src = (hand.neighbor_from or {}).get((site.get("scene") or {}).get("key") or "")
    if src:
        got = H.neighbor_from(site, blds, src, verbose=con.on())
        if got is not None:
            near = got
    return blds, near


def _buildings_gt(site, *, hand, mark, say):
    """건물 출처 ② GT — 창 안 GT → **2차 정합** → 귀속 → 손으로 그린 건물 이어 붙이기.

    정합 순서는 모델 경로와 같다(2차 정합이 영상을 더 되돌리면 GT 좌표도 같이 움직인다).
    """
    from sitecheck import gt
    if not gt.gt_file(site["scene"]["key"]):
        raise FileNotFoundError(
            f"GT 파일이 없다 — {site['scene']['ko']} 장면의 seglab 지역을 찾지 못했다")
    polys = gt.polygons(site, verbose=con.on(con.DETAIL))
    say.detail(f"GT {len(polys)}동 (필지 ±80 m)")
    polys = align.refine(site, polys)
    _mark_align(site, mark)
    blds, near = gt.buildings(site, polys, hand=hand)
    say.detail(blds.get("note") or "")
    return blds, near


def _mark_align(site, mark):
    r = site.get("align_residual_m")
    mark("align", r is not None,
         (f"잔차 ({r[0]:+.2f},{r[1]:+.2f}) m · 짝 {site.get('align_pairs')}동 · "
          f"IoU {site.get('align_iou')}") if r else "GIS footprint 짝이 모자라 재지 못함")


def _bld_note(site, blds, near):
    """건물 한 줄에 적을 말 — **동수와 정합이 한 줄에 있어야** 그 동수를 믿을지 알 수 있다.

    잔차는 동·북 두 값 대신 크기 하나로 적는다(화면에서 부호까지 읽을 일이 없다 —
    방향이 필요하면 `align_residual_m` 에 그대로 있다).
    """
    r = site.get("align_residual_m")
    fit = f"정합 잔차 {math.hypot(r[0], r[1]):.2f} m" if r else "정합 못 잼"
    return f"{blds['count']}동 · 옆 지번 {len(near)}동 · {fit}"


def analyze(address, out_dir, *, source="model", hand=H.NONE, only=pipeline.JUDGE_ALL,
            yard=True, yard_model="gpt-5.6-terra", gpu=None, reuse=True, tag=None,
            save_tiles=None, stored=None, scene=None, verbose=True):
    """주소 한 건 → 결과 봉투(`schema.envelope`). 실패하면 `(None, 사유)`.

    `source` 는 건물 폴리곤의 출처("model" · "gt")이고, `hand` 는 사람이 확인한 값
    ([[hand.py]] `Hand`)이다. 나머지 인자는 두 길에 똑같이 걸린다.
    """
    if source not in SOURCES:
        raise ValueError(f"source 는 {SOURCES} 중 하나다 — 받은 값 {source!r}")
    stored = (source == "gt") if stored is None else stored
    tag = tag or TAG[source]
    t0 = time.time()
    say = con if verbose else con.SILENT
    steps_log = []
    out_dir = Path(out_dir)

    def mark(name, ok, msg=""):
        """**기록만 한다.** 화면에 무엇을 낼지는 아래에서 따로 정한다 — 재현에 쓰는 칸
        (`provenance.steps`)과 사람이 읽는 줄은 담을 것을 고르는 기준이 다르다."""
        steps_log.append({"step": name, "ok": ok, "note": msg})

    # ── 0 주소 해석 ──────────────────────────────────────────────────────
    site, src = load_site(address, out_dir, stored=stored, scene=scene,
                          ledger_drop=hand.ledger_drop)
    if site.get("error"):
        mark("locate", False, site["error"])
        say.step("주소 해석", False, site["error"])
        return None, site["error"]
    if not site.get("scene"):
        mark("locate", False, "정사영상 범위 밖")
        names = " · ".join(v["ko"] for v in config.SCENES.values())
        say.step("주소 해석", False, f"정사영상 범위 밖 — 처리 대상은 {names} 뿐이다")
        return None, f"정사영상 범위 밖 주소 — 처리 대상은 {names} 뿐이다"
    if source == "gt" and not site.get("parcel"):
        say.step("주소 해석", False, "연속지적도 필지를 얻지 못해 그릴 바탕이 없다")
        return None, "연속지적도 필지를 얻지 못해 그릴 바탕이 없다"
    mark("locate", True, f"PNU {site.get('pnu')} · 대장 {len(site.get('ledger') or [])}동 · "
                         f"영상 {site['scene']['ko']} · {src}")
    say.step("주소 해석", True,
             f"PNU {site.get('pnu')} · 대장 {len(site.get('ledger') or [])}동 · "
             f"영상 {site['scene']['ko']}")
    say.detail(src)
    for n in site.get("notes", []):
        say.detail(n)
    _prepare(site, hand, say=say)

    # ── 1 건물 ──────────────────────────────────────────────────────────
    tag_pnu = f"{tag}_{site.get('pnu') or 'nopnu'}"      # 캐시 키에 필지를 넣는다 — scene
    try:                                                 #   단위면 같은 지역 두 번째 주소가
        if source == "model":                            #   첫 주소의 결과를 재사용한다
            blds, near = _buildings_model(site, hand=hand, tag=tag_pnu, gpu=gpu,
                                          reuse=reuse, mark=mark, say=say)
        else:
            blds, near = _buildings_gt(site, hand=hand, mark=mark, say=say)
        mark("buildings", blds["count"] > 0,
             blds.get("note") or f"{blds['count']}동 (옆 필지 {len(near)}동)")
        say.step("건물 폴리곤", blds["count"] > 0, _bld_note(site, blds, near))
    except Exception as e:                               # noqa: BLE001
        say.step("건물 폴리곤", False, f"{type(e).__name__}: {e}"[:160])
        if source == "gt":
            return None, f"{type(e).__name__}: {e}"      # GT 가 없으면 그릴 바탕이 없다
        blds, near = schema.empty("buildings", f"{type(e).__name__}: {e}"), []
        mark("buildings", False, str(e)[:160])

    # **손으로 그려 넣는 옆 지번 건물은 두 길에 다 걸린다**(2026-08-27).
    #
    # 예전에는 GT 경로 안에만 있었다 — GT 는 학습·평가용으로 그린 것이라 소형 부속·창고·차양을
    # 건너뛴 자리가 있고, 그것을 메우는 것이 이 보정이었다. 그런데 **모델도 놓친다**(실측
    # 2026-08-27: 같은 창에서 옆 지번 46동 대 36동). 놓치는 이유는 다르지만 결과는 같다 —
    # 이격 상대가 표에서 빠지고 그 줄이 통째로 사라진다.
    #
    # **id 를 붙인 뒤에 이어 붙인다** — 그래야 기존 `N####` 가 밀리지 않는다. `_own_geoms` 는
    # 거리를 재는 데만 쓰고 곧 지운다(site 에 남기지 않는다).
    # `neighbor_from` 이 건 날짜에는 **그려 넣지 않는다** — 가져온 목록에 이미 들어 있어
    # 같은 건물이 두 번 서고 이격 표에 두 줄로 오른다.
    if hand.neighbor_add and not (hand.neighbor_from or {}).get(
            (site.get("scene") or {}).get("key") or ""):
        site["_own_geoms"] = list(blds.get("features") or [])
        n_add = H.neighbor_add(site, near, hand.neighbor_add, verbose=con.on(con.DETAIL))
        site.pop("_own_geoms", None)
        if n_add:
            blds["note"] = (blds.get("note") or "") + f" · 사람이 그려 넣은 옆 지번 {n_add}동"
            say.sub(f"사람이 그려 넣은 옆 지번 {n_add}동")

    # **판독 건축면적을 사람이 넣은 값으로**([[hand.py]] `area_fix`). 대장 대조(A3)가 이 값을
    # 쓰므로 판정 앞에 둔다 — 동 이름이 붙은 뒤라야 걸린다(`label_features` 가 붙인다).
    if H.area_fix(blds, hand.area_fix, site=site, verbose=con.on()):
        say.sub("판독 건축면적 수동 설정 "
                + " · ".join(f"{k} {v:,.0f} ㎡" for k, v in site["area_fix"].items()))

    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 2·3·4 판정 ──────────────────────────────────────────────────────
    # 여기부터는 **모델이든 GT든 같은 길**이다 — [[pipeline.py]] 한 곳에서 낸다.
    layers, jsteps = pipeline.judge(
        site, blds, near, out_dir, only=only, yard=yard, yard_model=yard_model,
        refresh_yard=not reuse, save_tiles=bool(save_tiles),
        sep_also=H.sep_also(hand.sep_also, near, verbose=con.on()),
        sep_skip=H.sep_skip(hand.sep_skip, near, verbose=con.on()),
        yard_from=hand.yard_from, yard_drop=hand.yard_drop,
        yard_shift=hand.yard_shift, yard_grow=hand.yard_grow, say=say)
    name = RESULT_NAME[source]
    layers = pipeline.inherit(out_dir, name, layers, say=say)

    # 옆 지번 건물은 **결과에 담는다**(`context.buildings_near`) — 이격 결과의 `pair[1]` 이
    # 가리키는 상대이므로, 담지 않으면 받는 쪽이 풀 수 없는 참조가 나간다.
    result = schema.envelope(
        {"address": address, "requested_at": schema.now_iso()}, site, layers,
        _provenance(site, source, steps_log + jsteps, t0, tag_pnu,
                    yard_model if yard else None, src),
        near=near)
    return result, None


def _provenance(site, source, steps_log, t0, tag, yard_model, src):
    """무엇으로 냈는지 — 재현에 필요한 최소값. 없으면 나중에 수치를 설명할 수 없다."""
    if source == "model":
        avail = config.available_models()
        # **이 영상에서 실제로 쓴 값을 적는다.** 설정에는 영상별 덮어쓰기가 있어
        # (`INFER_DINOV3_BY_SCENE` — 2차 영상은 마스크·검출 임계값이 다르다) 기본 dict 을
        # 그대로 적으면 「무엇으로 냈는지」 칸에 **돌지도 않은 값**이 남는다. 재현에 쓰는
        # 칸이라 그러면 안 된다. 키는 늘리지 않는다 — 어느 모델이었는지는 `building` 이 말한다.
        infer, score_thr = config.infer_for((site.get("scene") or {}).get("key") or "")
        model = {"building": [m["tag"] for m in avail],
                 "building_geom": next((m["tag"] for m in avail if m.get("geom")), None),
                 "ensemble": dict(config.ENSEMBLE),
                 "yard_vlm": yard_model,
                 "infer": infer,
                 "score_threshold": score_thr}
    else:
        from sitecheck import gt
        model = {"building": f"GT {gt.gt_file(site['scene']['key'])}",
                 "yard_vlm": yard_model}
    return {"model": model,
            "rules": "PoC_결정항목_기준근거_A1_A3_A4_A5 (2026-08-13)",
            "tag": tag,
            "steps": [{"step": "site", "ok": True, "note": src}] + steps_log,
            "seconds": round(time.time() - t0, 1)}


def save(result, out_dir, *, source="model", images=True, report=True, hand=H.NONE,
         verbose=True):
    """result.json/demo.json · 레이어 geojson · summary.md · 그림 넷 · 보고서.

    **세 진입점이 같은 함수로 낸다** — [[pipeline.py]] `finish`. 산출물이 도구마다 다르면
    같은 물건의 두 결과를 견줄 수 없다. 그림 규칙(색·선·배지)과 이름·판정어는 [[draw.py]]
    한 벌이고, 보고서 판짜기는 [[report/single.py]] 한 벌이다.
    """
    near = (result.get("context") or {}).get("buildings_near", {}).get("features") or ()
    return pipeline.finish(result, out_dir, name=RESULT_NAME[source], near=near,
                           images=images, report=report, skip=hand.road_side,
                           verbose=verbose)


def run_many(addresses, root, *, source="model", table=None, verbose=True,
             images=True, report=True, **kw):
    """주소 여러 건 — 한 건이 실패해도 나머지는 낸다. `(성공 수, [(주소, 사유)])`.

    **장면 순으로 처리한다** — 장면 PNG 는 한 장만 메모리에 두므로, 섞이면 큰 파일을 여러 번
    디코드한다(구미 450 MB).

    **한 건이 죽어도 멈추지 않는다.** 목록으로 도는 것이 기본이라 중간에서 멈추면 앞것만 새
    판, 뒷것은 옛 판이 되어 폴더 안에서 판이 섞인다 — 그 상태가 제일 알기 어렵다.
    """
    root = Path(root)
    addresses = sorted(addresses, key=lambda a: _scene_hint(a, root))
    say = con if verbose else con.SILENT
    ok, skipped = 0, []
    for i, address in enumerate(addresses, 1):
        say.head(f"[{i}/{len(addresses)}] {address}")
        d = root / slug(address)
        hand = H.of(table, address)
        try:
            r, err = analyze(address, d, source=source, hand=hand, verbose=verbose, **kw)
        except Exception as e:                               # noqa: BLE001
            r, err = None, f"{type(e).__name__}: {e}"
            # 자취는 `--detail` 에서만 — 사유는 아래 한 줄로 나가므로, 기본 화면에서는
            # 스무 줄짜리 자취가 나머지 건의 결과를 밀어낸다.
            if con.on(con.DETAIL):
                import traceback
                traceback.print_exc()
        if r is None:
            skipped.append((address, err))
            say.fail(address, err)
            continue
        save(r, d, source=source, hand=hand, verbose=verbose,
             images=images, report=report)
        ok += 1
        if verbose:
            _print_summary(r, d)
    say.tail(f"완료 {ok}/{len(addresses)}"
             + (f" · 건너뜀 {len(skipped)}" if skipped else ""))
    return ok, skipped


def _scene_hint(address, root):
    for p, key in ((config.OUT / slug(address) / "result.json", "site"),
                   (root / slug(address) / "_site.json", None)):
        if not p.exists():
            continue
        try:
            o = json.loads(p.read_text("utf-8"))
            o = o[key] if key else o
            return (o.get("scene") or {}).get("key") or ""
        except Exception:                                    # noqa: BLE001
            continue
    return ""


LAYER_KO = {"buildings": "건물", "ledger": "대장 대조",
            "separation": "이격거리", "yard": "야적물"}


def _print_summary(r, d):
    """끝맺음 — **넷을 한 줄에 적는다.** 항목마다 줄을 나누면 여러 건을 잇달아 돌릴 때
    화면이 판정보다 여백으로 찬다. 항목별 내역은 `summary.md` 가 근거 조문까지 적어 둔다."""
    from sitecheck import rules
    s = r["summary"]
    parts = []
    for k in schema.LAYERS:
        by = " · ".join(f"{x} {y}" for x, y in sorted(
            s[k]["by_level"].items(), key=lambda kv: rules.LEVEL_ORDER.get(kv[0], 99)))
        parts.append(f"{LAYER_KO[k]} {s[k]['count']}" + (f"({by})" if by else ""))
    con.result(s.get("worst_level"), parts, d)


def summary_md(r):
    """사람이 먼저 읽는 한 장. 판정이 높은 것부터, 근거 조문과 함께."""
    from sitecheck import rules
    s, site = r["summary"], r["site"]
    L = [f"# {r['request']['address']}", "",
         f"- 조회 {r['request']['requested_at']} · 소요 {r['provenance']['seconds']}초",
         f"- PNU {site.get('pnu')} · 필지 {site.get('parcel_m2')} ㎡ · "
         f"영상 {(site.get('scene') or {}).get('ko')}",
         f"- 최고 판정 **{s.get('worst_level') or '—'}**", ""]
    for b in (site.get("ledger") or [])[:6]:
        L.append(f"  - 대장: {b.get('dong') or '(동명 없음)'} · {b.get('struct') or '—'} · "
                 f"건축 {b.get('arch_area_m2')} ㎡ · 연면적 {b.get('total_area_m2')} ㎡ · "
                 f"지상 {b.get('floors_above')}층")
    L.append("")
    for k in schema.LAYERS:
        fc = r["layers"][k]
        by = " · ".join(f"{a} {b}" for a, b in sorted(
            s[k]["by_level"].items(), key=lambda kv: rules.LEVEL_ORDER.get(kv[0], 99)))
        L += ["", f"## {LAYER_KO[k]} — {fc['count']}건" + (f"  ({by})" if by else "")]
        if fc.get("note"):
            L.append(f"> {fc['note']}")
        for f in fc["features"][:12]:
            p = f["properties"]
            if not p.get("level"):
                continue
            who = p.get("bld_id") or p.get("yard_id") or "·".join(p.get("pair") or [])
            if p.get("dir"):                  # 이격은 방향마다 한 줄이다 — 어느 쪽인지 먼저 쓴다
                who = f"{p['dir']}쪽 {who}"
            L.append(f"- **{p['level']}** {who} — {p.get('label')} · {p.get('reason')}"
                     + (f"  \n  <sub>{p['basis']}</sub>" if p.get("basis") else ""))
        if fc["count"] > 12:
            L.append(f"- … 외 {fc['count'] - 12}건")
    return "\n".join(L) + "\n"
