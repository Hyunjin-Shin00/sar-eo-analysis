"""건물이 정해진 뒤부터는 **한 길이다** — 모델이든 GT든 같은 코드를 지난다.

`run.py` 와 `tools/for_demo.py` 의 차이는 **건물 폴리곤을 어디서 얻는가** 하나다.

    run.py       s1_building.predict → attribute      모델 추론
    for_demo.py  gt_polygons → gt_buildings           GT(대장 시딩 + 손보정)

그 뒤의 야적 판독 · 이격 · 대장 대조와, 저장 · 그림 · 보고서는 전부 여기서 낸다. 두 곳에
적어 두면 같은 물건이 도구마다 다른 값·다른 그림·다른 보고서로 나오고, 그때 어느 쪽이 맞는지
사후에 알 수 없다(실측으로 그 일을 겪었다 — 데모는 보고서를 내는데 `run.py` 는 안 내서 같은
물건의 두 산출물을 비교할 수 없었다).

**결과 파일 이름만 갈라 둔다**(`result.json` / `demo.json`). 폴더만 보고 그 값이 모델에서
나왔는지 GT 에서 나왔는지 알 수 있어야 하기 때문이다 — 값 자체는 `provenance.model.building`
에도 적히지만, 파일 이름이 먼저 눈에 든다. 읽는 쪽([[report/single.py]] `find_result`)은 둘 다 본다.
"""
from __future__ import annotations

import json
from pathlib import Path

from sitecheck import console as con
from sitecheck import schema
from sitecheck import hand as H
from sitecheck.steps import s2_yard, s3_separation, s4_ledger

JUDGE_ALL = ("sep", "yard", "illegal")


def _worst(fc):
    from sitecheck import rules
    lv = [f["properties"].get("level") for f in fc.get("features") or []]
    lv = [x for x in lv if x]
    return min(lv, key=lambda x: rules.LEVEL_ORDER.get(x, 99)) if lv else "—"


def yard_layer(site, blds, out_dir, *, model, yard=True, refresh=False, save_tiles=False,
               yard_from=None):
    """야적 판독 — `s2_yard.detect` 를 부르고 **결과를 폴더에 캐시한다**.

    VLM 호출은 돈이 든다. 그림이나 보고서를 다시 뽑을 때마다 다시 부르면 물건 하나에 비용이
    계속 붙으므로 `_yard.json` 에 남기고 다음부터는 그것을 읽는다(다시 부르려면 `refresh`).
    **모델 경로에도 같은 캐시를 쓴다** — 판독 대상은 영상과 건물 밖 공지이고, 그건 건물을
    어디서 얻었느냐와 무관하게 같은 값이다.
    """
    if not yard:
        return schema.empty("yard", "야적 판독을 건너뛰었다")
    cache = Path(out_dir) / "_yard.json"
    # **판독을 다른 폴더에서 가져오는 손보정**([[hand.py]] `yard_from`). 이 폴더에 캐시가
    # 없을 때만 본다 — 한 번 가져오면 아래에서 이 폴더에 남기므로 다음부터는 그것을 쓴다.
    #
    # 왜 필요한가. 데모 산출물의 야적 값 일부는 **사람이 자리를 정해 파일에 적어 넣은 것**이고
    # (`demo_cmp/t*/…/_yard.json` 의 「데모용으로 …」), 그 값은 코드가 만들어 낼 수 없다.
    # 모델 경로 산출물을 데모와 같게 맞추려면 그 판독을 그대로 써야 하는데, 파일을 손으로
    # 복사하면 **어디서 왔는지가 아무 데도 안 남는다**. 그래서 손보정 표에 적고 여기서 읽는다
    # (`refeature` 가 건물까지의 거리·판정·번호를 지금 건물로 다시 계산하므로, 가져오는 것은
    # 「무엇이 쌓였나」와 그 자리뿐이다).
    if yard_from and not cache.exists() and not refresh:
        src = Path(yard_from.get((site.get("scene") or {}).get("key") or "") or "")
        if src and not src.is_absolute():
            src = Path(__file__).resolve().parents[1] / src
        if src.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(src.read_text("utf-8"), encoding="utf-8")
            con.sub(f"야적 판독을 {src.parent.parent.name}/{src.parent.name} 에서 "
                    f"가져왔다(사람이 정한 값)")
        else:
            con.warn(f"야적 판독을 가져올 파일이 없다: {src}")
    if cache.exists() and not refresh:
        fc = json.loads(cache.read_text("utf-8"))
        add = " · 저장된 판독 결과를 다시 씀"
        # **옛 캐시는 좌표가 영상 프레임이다.** 판독한 내용(무엇이 쌓였나)은 그대로 유효하니
        # 다시 부르지 않고 좌표만 지도 프레임으로 옮긴다 — 안 옮기면 야적 구역만 영상 편이
        # 만큼(남동공단 9 m) 밀린 채로 나가고, 그 사실이 어디에도 안 남는다.
        if fc.get("frame") != schema.FRAME:
            from sitecheck.steps import georef
            n = georef.migrate_fc(site, fc)
            cache.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
            add += f"(옛 프레임 {n}건을 지도 좌표로 옮겼다)"
        # **파생값은 다시 계산한다.** 캐시에는 모델이 말한 것과 우리가 계산한 것(건물까지
        # 거리 · 판정 · 번호)이 섞여 있는데, 뒤엣것은 건물이 달라지면 값이 달라진다. 그대로
        # 쓰면 캐시가 판정을 굳혀, 건물을 고친 뒤에도 옛 판정이 나간다.
        fc = s2_yard.refeature(fc, blds, site)
        fc["note"] = (fc.get("note") or "") + add
        return fc
    fc = s2_yard.detect(site, blds, model=model,
                        save_tiles=(Path(out_dir) / "tiles") if save_tiles else None)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return fc


def judge(site, blds, near, out_dir, *, only=JUDGE_ALL, yard=True,
          yard_model="gpt-5.6-terra", refresh_yard=False, save_tiles=False,
          lot_line=True, sep_also=(), sep_skip=(), yard_from=None, yard_drop=(),
          yard_shift=(), yard_grow=(), say=None):
    """건물 → 야적 · 이격 · 대장 판정. **모델·GT 공통.**

    한 단계가 죽어도 나머지를 버리지 않는다 — 빈 레이어에 사유를 담아 그대로 낸다. 빈 결과를
    그냥 내면 「없다」와 「못 쟀다」가 같은 모양이 되어 구분되지 않는다.

    `sep_also` 는 경계선 걷기에서 구간을 이기지 못한 **이격 상대를 손으로 더하는** 목록이다
    ([[steps/s3_separation]] `also`) — 값은 옆 지번 건물의 `bld_id` 다.

    `sep_skip` 은 그 반대로 **이격 후보에서만 빼는** id 다. `NEIGHBOR_DROP`([[settings.py]])이
    목록에서 아예 빼는 것과 다르다 — 이쪽은 `context.buildings_near` 에 남아 **지도에는
    그려지고** 이격 줄만 안 난다. 사람이 「저기 건물은 있지만 이 줄은 싣지 않는다」고 정한
    자리에 쓴다.

    **두 목록은 서로 배타가 아니다.** 같은 건물을 `sep_skip` 에 두고 `sep_also` 로 한 쌍만
    더할 수 있다 — 그래서 목록에서 미리 걸러 넘기지 않고 `skip` 으로 넘긴다. 걸러 넘기면
    `also` 가 그 건물을 찾지 못해 사람이 고른 쌍이 조용히 사라진다
    ([[steps/s3_separation]] `skip`).
    """
    say = say or con.SILENT
    layers, steps = {"buildings": blds}, []

    # **대장 면적을 종이와 같은 눈금으로 접는다**([[steps/s4_ledger]] `round_areas`) — 여기서
    # 한 번 접으면 site 를 담아 내보내는 값 파일과 보고서가 같은 숫자를 쓴다. 「illegal」을
    # 안 돌린 실행에서도 site 는 그대로 나가므로 이 단계 밖에 둔다.
    n = s4_ledger.round_areas(site)
    if n:
        say.detail(f"대장 면적 {n}칸을 정수 ㎡ 로 접었다(보고서와 같은 눈금)")
    # **대지면적도 같은 눈금이다.** 재는 함수는 이제 정수를 내지만
    # ([[steps/s0_locate]] `_parcel_area_m2`) 저장된 site(`_site.json` · 옛 result.json)에는
    # 0.1 자리가 남아 있다 — 그대로 내보내면 종이의 5,576 ㎡ 와 파일의 5,575.5 ㎡ 가 갈린다.
    pm = site.get("parcel_m2")
    if pm is not None and float(pm) != float(round(pm)):
        site["parcel_m2"] = float(round(pm))
        say.detail(f"대지면적을 정수 ㎡ 로 접었다({pm:,.1f} → {site['parcel_m2']:,.0f})")

    if "sep" in only:
        ran = True
        try:
            sep = s3_separation.run(blds, list(near or []), site,
                                    also=sep_also, skip=sep_skip)
            if sep_skip:
                # 뺀 것과 더한 것이 같은 건물일 수 있으므로(걷기에서만 뺀다) 어느 쌍이
                # 남았는지도 적는다 — 「뺐다」만 적으면 종이의 그 줄이 어디서 왔는지 모른다.
                kept = sorted({(f["properties"].get("pair") or [None, None])[1]
                               for f in sep["features"]} & set(sep_skip))
                sep["note"] = ((sep.get("note") or "")
                               + f" · 사람이 이격 후보에서 뺀 상대 {len(sep_skip)}동"
                                 f"({', '.join(sep_skip)}) — 지도에는 그려진다"
                               + (f", 그중 {', '.join(kept)} 은 손으로 고른 쌍만 남겼다"
                                  if kept else ""))
            if lot_line:
                # `sep` 를 넘긴다 — 도달거리 안에 상대가 있는 건물에는 대지경계선 보조
                # 판정을 붙이지 않는다(기준선이 둘이면 어느 것으로 읽을지 알 수 없다).
                sep["features"].extend(s3_separation.lot_line(blds, site, sep))
                sep["count"] = len(sep["features"])
            steps.append({"step": "separation", "ok": True,
                          "note": f"{sep['count']}쌍 · 최고 {_worst(sep)}"})
        except Exception as e:                                     # noqa: BLE001
            sep = schema.empty("separation", f"{type(e).__name__}: {e}")
            steps.append({"step": "separation", "ok": False, "note": str(e)[:160]})
            ran = False
        layers["separation"] = sep
        # **「돌았나」와 「무엇이 나왔나」는 다르다** — 0건은 실패가 아니라 결과다.
        say.step("이격거리", ran, f"{sep['count']}건" if ran else (sep.get("note") or "")[:160])

    if "yard" in only:
        ran = True
        try:
            yd = yard_layer(site, blds, out_dir, model=yard_model, yard=yard,
                            yard_from=yard_from,
                            refresh=refresh_yard, save_tiles=save_tiles)
            # **사람이 확인해 뺀 구역**([[hand.py]] `yard_drop`) — 판독이 한 무더기를 둘로
            # 갈라 낸 자리를 하나로 되돌린다. 뺀 사실은 레이어 note 와 site.notes 에 남는다.
            H.yard_drop(yd, yard_drop, site=site, verbose=True)
            # **옮기기는 빼기 뒤에**([[hand.py]] `yard_shift`) — 뺄 구역을 옮겨 놓고
            # 버리면 헛일이고, 옮긴 뒤에는 거리·판정을 다시 낸 값이라 순서가 뒤바뀌면 안 된다.
            H.yard_shift(yd, yard_shift, blds=blds, site=site, verbose=True)
            # **늘리기는 옮기기 뒤에** — 자리를 잡아 놓고 모자란 쪽을 채우는 차례다.
            H.yard_grow(yd, yard_grow, blds=blds, site=site, verbose=True)
            steps.append({"step": "yard", "ok": bool(yd.get("features")),
                          "note": yd.get("note") or f"{yd['count']}구역"})
        except Exception as e:                                     # noqa: BLE001
            yd = schema.empty("yard", f"{type(e).__name__}: {e}")
            steps.append({"step": "yard", "ok": False, "note": str(e)[:160]})
            ran = False
        layers["yard"] = yd
        say.step("야적물", ran, f"{yd['count']}건" if ran else (yd.get("note") or "")[:160])

    if "illegal" in only:
        ran = True
        try:
            led = s4_ledger.run(blds, site)
            steps.append({"step": "ledger", "ok": True,
                          "note": f"{led['count']}건 · 최고 {_worst(led)}"})
        except Exception as e:                                     # noqa: BLE001
            led = schema.empty("ledger", f"{type(e).__name__}: {e}")
            steps.append({"step": "ledger", "ok": False, "note": str(e)[:160]})
            ran = False
        layers["ledger"] = led
        say.step("대장 대조", ran, f"{led['count']}건" if ran else (led.get("note") or "")[:160])

    return layers, steps


def inherit(out_dir, name, layers, *, say=None):
    """`only` 로 일부만 돌렸을 때 **나머지 레이어를 지우지 않는다.**

    지난 결과의 그 레이어를 그대로 물려받는다(같은 주소·같은 site 라 값이 유효하다). 지우고
    내면 보고서가 「판단 보류」로 읽는다(실측: 야적 색만 고치려고 `--only yard` 로 돌렸다가
    1면이 무너졌다).
    """
    say = say or con.SILENT
    f = Path(out_dir) / name
    prev = {}
    if f.exists():
        try:
            o = json.loads(f.read_text("utf-8"))
            # **옛 판 레이어는 물려받지 않는다** — 좌표나 id 규약이 달라 이번에 낸 레이어와
            # 한 파일에 섞이면 조용히 어긋난다. 물려받지 못한 것은 빈 레이어에 사유가
            # 남으므로 「없다」와 구분된다.
            prev = (o.get("layers") or {}) if schema.is_current(o) else {}
            # **물려받을 것이 있을 때만 말한다.** 이번에 세 레이어를 다 돌렸으면 옛 파일을
            # 안 읽어도 결과가 온전하므로, 그때 경고를 찍으면 방금 돌린 사람에게 "다시
            # 돌리세요"라고 말하는 셈이 된다.
            if o and not schema.is_current(o) and (
                    {"separation", "yard", "ledger"} - set(layers)):
                say.warn("지난 결과가 옛 판이라 물려받지 않았다 — 이번에 안 돌린 "
                         "레이어는 비어 있다")
        except Exception:                                          # noqa: BLE001
            prev = {}
    for k in ("separation", "yard", "ledger"):
        if k not in layers and (prev.get(k) or {}).get("features"):
            layers[k] = prev[k]
            say.detail(f"{k} — 지난 결과를 그대로 물려받았다(이번에 돌리지 않음)")
    return layers


def summary_md(r):
    """사람이 읽는 한 장 — 짜는 곳은 [[analyze.py]] 하나다.

    예전에는 이 함수가 `from run import summary_md` 로 **뿌리의 스크립트를 거꾸로** 들여왔다.
    진입점이 셋이 되면서 그 방향이 성립하지 않는다.
    """
    from sitecheck.analyze import summary_md as _s
    return _s(r)


def finish(result, out_dir, *, name="result.json", near=(), images=True, report=True,
           skip=(), verbose=True):
    """저장 · 그림 · 보고서 — **세 진입점이 같은 산출물을 내는 곳.**

    그림은 [[draw.py]] `result_images` 하나가 그리고, 보고서는 [[report/single.py]] 하나가
    짠다. 도구마다 따로 그리면 같은 물건이 도구마다 다른 색·다른 판으로 나온다.

    `report` 는 True · False 말고 **`"html"`** 도 받는다 — 저장소에 든 데모 보고서 PDF 는
    코드가 못 뽑는 손판(Chrome 인쇄)이라, 다시 낼 때 matplotlib PDF 로 덮으면 판이 무너진다
    ([[hand_writting.py]]). 그때 HTML 과 그림만 새로 내고 PDF 는 `report/pdf_refit` 으로
    글자만 갈아 끼운다.
    """
    say = con if verbose else con.SILENT
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    # 값 파일 이름만 갈라 둔다(모델=result.json · GT=demo.json) — 폴더만 보고 어느 길로
    # 나온 값인지 알아야 하기 때문이다. **레이어 geojson 은 둘 다 낸다** — QGIS 에 얹는
    # 용도라 GT 결과에도 필요하고, 여기서 갈리면 도구 사이의 차이가 하나 더 늘어난다.
    # **형식을 내보내기 전에 한 번 본다**([[schema.validate]]). 여태 이 함수를 아무도
    # 부르지 않아서, 프레임처럼 좌표계 자체가 바뀌는 변경을 잡아 줄 자리가 없었다. 막지는
    # 않는다 — 값은 그대로 내고 무엇이 어긋났는지 적는다(빈 결과보다 낫다).
    for problem in schema.validate(result):
        say.warn(f"형식 점검 — {problem}")
    (out / name).write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    made.append(out / name)
    for k in schema.LAYERS:
        f = out / f"{k}.geojson"
        f.write_text(json.dumps(schema.layer_geojson(result["layers"][k]),
                                ensure_ascii=False), encoding="utf-8")
        made.append(f)
    # 바탕 둘 더 — 필지, 옆 지번 건물. 판정 레이어가 아니라 그리는 쪽과 참조를 위한 것이다.
    # **`name` 을 가리지 않는다** — 아래에서 보고서에 「어느 값 파일을 읽어라」로 넘기는 이름이다.
    for ctx_name, fc in schema.context_files(result).items():
        f = out / ctx_name
        f.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        made.append(f)
    md = out / "summary.md"
    md.write_text(summary_md(result), encoding="utf-8")
    made.append(md)

    ok = True
    if images:
        try:
            from sitecheck import draw
            # **그림 이름을 낱낱이 찍지 않는다** — 아래 한 줄이 몇 개를 냈는지 말하고,
            # 이름은 폴더를 열면 있다. `--detail` 에서만 낱낱이 나온다.
            made += draw.result_images(result, out, near=near,
                                       verbose=con.on(con.DETAIL))
        except Exception as e:                                      # noqa: BLE001
            say.warn(f"그림 — {type(e).__name__}: {e}")
            ok = False
    if report:
        # 늦게 들여온다 — 보고서 쪽이 무거운 그리기 묶음을 끌고 오므로, 값만 낼 때는
        # 그 비용을 물지 않는다.
        try:
            from sitecheck.report import single as FR
            for f in FR.build(result["request"]["address"], out.parent,
                              str(out / "보고서"), skip=skip, folder=out, name=name,
                              pdf=(report != "html")):
                made.append(f)
                say.detail(f"보고서 {f.name}")
        except Exception as e:                                      # noqa: BLE001
            say.warn(f"보고서 — {type(e).__name__}: {e}")
            ok = False
    say.step("산출물", ok, f"{len(made)}개 파일")
    return made
