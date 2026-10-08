"""두 촬영일 결과 → **비교분석 보고서 한 부** (PDF + HTML, 기존 보고서와 같은 판짜기).

기존 보고서([[single.py]])는 한 시점을 설명한다. 이 도구는 **같은 물건을 두 날짜에 재서
무엇이 바뀌었는지**만 낸다. 언더라이팅에서 이 질문이 따로 서는 이유는 특건 점검주기가
1~2년이라 그 사이의 변화를 아무도 보지 않기 때문이다(갭분석 Tier3 #18).

  1면  개요 · 변화 기준 · 변화 탐지
  2면  ① 건물 간 이격거리 변화
  3면  ② 야외 적재물 변화
  4면  ③ 미등록·증축 변화

**단일시점 보고서와 같은 길로 간다** — `source` 를 부르는 쪽이 정한다. 야적 판독은 어느
길이든 날짜마다 실제 VLM 을 부른다. 같은 물건의 두 문서(단일시점·비교분석)가 다른 입력을
쓰면 숫자가 갈리므로, **부르는 진입점의 길을 그대로 따라간다**.

    demo.py · hand_writting.py   source="gt"     건물 GT      demo_cmp/ · out_gt_cmp/
    run.py                       source="model"  모델 추론    out_cmp/

**모델 경로로 비교할 때 알아야 할 것.** 비교분석은 「같은 지붕을 두 날짜에 놓고 본다」는
전제 위에 선다. GT 는 사람이 그린 같은 폴리곤을 옮겨 쓰므로 그 전제가 성립하지만, 모델은
날짜마다 그 영상에서 새로 뽑으므로 **경계가 조금씩 흔들린다** — 그 흔들림이 변화로 보일 수
있다. 그래서 변화 기준을 새로 만들지 않고 [[rules.py]] 의 **측정오차 상수**를 그대로 쓴다
(아래) — 이격 1.3 m · 면적 30 ㎡ 이면서 2 % 는 그 흔들림을 넘기려고 둔 문턱이다. 그보다 작은
차이는 애초에 「변화 없음」으로 나간다. 그래도 두 판을 나란히 볼 때는 `t1`·`t2` 폴더의
`0_모델건물.png` 두 장을 먼저 보세요 — 어느 동이 어떻게 잡혔는지가 거기 있다.

**문구·표·판정어는 [[single.py]] 의 함수를 그대로 부른다**(`overview_rows` · `_criteria` ·
`lv` · `render_pdf` · `render_html` · `img_*`). 데모 보고서를 고치면 이 보고서도 같이 바뀐다 —
같은 칸을 두 곳에 적어 두면 어느 쪽이 맞는지 나중에 알 수 없다.

**기후·소방 면은 넣지 않는다.** 그 값은 물건의 위치에 붙는 것이라 열흘 사이에 바뀌지 않는다.

**변화 기준은 새로 만들지 않는다** — [[rules.py]] 의 측정오차 상수를 그대로 쓴다.

    이격거리   |Δ| ≥ SEP_MEASURE_ERR_M (1.3 m)
    건물면적   |Δ| ≥ LEDGER_EXT_MIN_M2 (30 ㎡) **그리고** LEDGER_MODEL_AREA_ERR (2 %)
    야외적재물 구역 수 · 판정이 달라짐 (면적은 애초에 산출하지 않는다 — 근거문서 A5)

    cd <WORK_ROOT>/sitecheck
    .venv/bin/python -m sitecheck.report.compare "<주소>" --scene1 daegu --scene2 daegu2
    .venv/bin/python hand_writting.py --only cmp        # 저장소에 든 표본 2건

**표본 목록은 `addresses.txt` 가 아니라 `cmp_addresses.txt` 다.** 두 촬영일이 다 있어야
하므로 기준이 다르다 — 2차 영상 밖(구미·남동공단)이거나 GT 이식이 되레 밀린 필지는 빠진다.
**저장소에 든 표본 2건은 [[hand_writting.py]] 가 손보정과 함께 낸다** — 이 파일을 직접
돌리면 손보정 없이 나온다.
뺀 것과 그 이유는 그 파일 머리에 적혀 있다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from sitecheck import draw as DR
from sitecheck import rules as RL
from sitecheck import schema as SC
from sitecheck import settings as config
from sitecheck.report import single as FR
from sitecheck import hand as H
from sitecheck.naming import slug

Image.MAX_IMAGE_PIXELS = None

# 변화 표시의 잉크 — **판정 색(빨강 위험 · 노랑 주의 · 초록 안전)과 일부러 다른 계열**을 쓴다.
# 이 문서에는 축이 둘이다: 「위험한가」(항목 면의 판정)와 「변화 여부」(차이 정리 면). 같은 색을
# 두 축에 쓰면 초록이 「안전」인지 「안 바뀜」인지 알 수 없다. 그래서 차이는 자홍·보라로 적고
# **안 바뀐 것은 회색**으로 눌러 둔다 — 달라진 줄만 눈에 걸리게.
# **판정어는 셋이다** — 「변화 확인 · 변화 없음 · 판단 보류」.
#
# 예전에는 「변화 있음」(등급이 나빠짐)과 「변화 확인」(값이 달라짐)을 갈라 적었다. 그런데
# 한 표 안에서 둘이 섞이면 읽는 사람이 **두 말의 차이부터 물어야 한다** — 종이의 목적은
# 「무엇이 달라졌나」를 보이는 것이지 달라짐의 등급을 말로 나누는 것이 아니다(사용자 결정,
# 2026-08-27). 등급이 나빠졌다는 사실은 그 줄의 1차·2차 판정 칸에 그대로 남아 있다
# (「위험」 → 「주의」처럼). `CHG["변화 있음"]` 은 옛 값을 읽는 쪽을 위해 남긴다.
CHG = {"변화 있음": "#7c3aed", "변화 확인": "#7c3aed",
       "변화 없음": "#6b7280", "판단 보류": "#9aa0a8"}
CHG_ORDER = ["변화 확인", "변화 없음", "판단 보류"]


def _c(level):
    return (level, CHG.get(level, FR.DIM))


def _worse(a, b):
    """두 판정 중 나쁜 쪽. `rules.LEVEL_ORDER`(7단계)를 그대로 쓴다."""
    o = RL.LEVEL_ORDER
    if a is None or b is None:
        return None
    return a if o.get(a, 99) <= o.get(b, 99) else b


def _rank(level):
    """판정 → 나쁜 순서 값(작을수록 나쁨). **없음(None)은 「이상 없음」 계열로 본다.**

    야적은 탐지된 구역이 없으면 판정 자체가 없다(None). 그것을 「비교 불가」로 두면 **없던
    적재물이 생겨 법정선을 밑도는 것**이 악화로 잡히지 않는다(실측 호산동 710: 0구역 →
    1구역 「해당」인데 「변화 확인」으로 나왔다). 그래서 None 을 「기록」(=이상 없음 표기)과
    같은 자리에 두고, 그보다 나쁜 등급이 생기면 악화로 센다.
    """
    return RL.LEVEL_ORDER.get(level, 99) if level else RL.LEVEL_ORDER["기록"]


def _degraded(l1, l2):
    """판정 등급이 나빠졌나 — 7단계 순서에서 뒤(나쁨)로 갔으면 True."""
    return _rank(l2) < _rank(l1)


def verdict(delta, limit, l1=None, l2=None):
    """(변화량, 오차선, 1차 판정, 2차 판정) → 3단계."""
    if delta is None:
        return "판단 보류"
    if _degraded(l1, l2):
        return "변화 확인"                      # 등급이 나빠진 것도 「변화 확인」이다(위 CHG)
    return "변화 확인" if abs(delta) >= limit else "변화 없음"


def area_verdict(dv, pct, l1, l2):
    """면적 변화 → (판정, 방향말). **증가와 감소를 한 칸에 뭉개지 않는다.**

    A3(증축)는 대장을 **넘는 분만** 본다. 그래서 판독 면적이 절반으로 줄어도 규칙은
    「이상없음」이다(실측 호산동 704-1: 1,137 → 586 ㎡ 인데 두 날짜 다 이상없음). 그것을
    「변화 없음」으로 적으면 종이가 거짓말을 한다 — 줄어든 것은 **철거이거나 판독 누락**이고
    둘 다 현장 확인 대상이다. 그래서 방향을 말로 적어 돌려준다.
    """
    if dv is None:
        return "판단 보류", "—"
    over = (abs(dv) >= RL.LEDGER_EXT_MIN_M2
            and abs(pct or 0) >= RL.LEDGER_MODEL_AREA_ERR * 100)
    if not over:
        return "변화 없음", "측정오차 범위"
    if _degraded(l1, l2):
        return "변화 확인", "증축 의심"
    return "변화 확인", ("증축 의심" if dv > 0 else "철거 또는 판독 누락")


# ── 날짜별 측정값 뽑기 ──────────────────────────────────────────────────────
def sep_metrics(L, *, skip=()):
    """이격 — 필지 내/외 각각의 **최소 거리**와 최고 판정, 법정선 미달 쌍 수.

    쌍마다 견주지 않는 이유: 동 번호(`bld_id`)는 두 날짜에서 같다고 보장되지 않는다.
    필지 대표값(가장 가까운 쌍)은 그 번호에 흔들리지 않는다.
    """
    fs = [f["properties"] for f in (L["separation"].get("features") or [])
          if f["properties"].get("dir") not in skip]
    out = {}
    for key, want in (("in", True), ("out", False)):
        v = [p for p in fs if bool(p.get("same_parcel")) is want]
        d = [p["dist_m"] for p in v if p.get("dist_m") is not None]
        lv = None
        for p in v:
            lv = _worse(lv, p.get("level")) if lv else p.get("level")
        out[key] = {"min_m": min(d) if d else None, "n": len(v), "level": lv,
                    "n_warn": sum(1 for p in v if p.get("level") in ("경고", "해당"))}
    out["n_pair"] = len(fs)
    return out


def led_metrics(L):
    """대장 대조 — 필지 총량 판정 한 줄(측정 면적 · 대장 면적 · 동수 · 판정)."""
    for f in L["ledger"].get("features") or []:
        p = f["properties"]
        if p.get("scope") == "parcel":
            return {"measured": p.get("measured_sum_m2"), "ledger": p.get("ledger_sum_m2"),
                    "n_model": p.get("n_model"), "n_ledger": p.get("n_ledger"),
                    "level": p.get("level"), "label": p.get("label")}
    return {"measured": None, "ledger": None, "n_model": None, "n_ledger": None,
            "level": None, "label": None}


def yard_demo(L):
    """이 날짜의 적재 구역이 **사람이 자리를 정한 데모 값**인가.

    데모를 만들다 보면 판독 결과 대신 손으로 자리를 정하는 일이 있다(변화가 드러나는 표본이
    필요할 때). 그 사실은 야적 레이어의 `note` 에 「데모용…」으로 남는데, **종이에는 남지
    않았다** — 각주를 걷어 낸 뒤로는 더 그렇다. 그러면 2·3면이 손으로 정한 자리를 위성 판독
    결과처럼 말하게 된다.

    각주 삭제 원칙과 어긋나지 않는다 — 걷어 낸 것은 「물건마다 달라지지 않는 회색 글」이고,
    이것은 **이 물건에만 해당하는 사실**이라 표와 1면 개요에 들어갈 값이다.
    """
    note = L["yard"].get("note") or ""
    if "데모용" not in note:
        return None
    # **비운 것과 그린 것은 다른 사실이다.** 앞것은 판독 결과를 버린 것이고 뒷것은 없던 구역을
    # 세운 것이라, 한 말로 뭉치면 종이가 1차에도 없는 구역을 그린 것처럼 말한다.
    return "비움" if "비웠다" in note else "손으로 정함"


def yard_metrics(L):
    """야적 — 구역 수 · 종류 · 최근접 거리 · 최고 판정. **면적은 없다**(근거문서 A5)."""
    fs = [f["properties"] for f in (L["yard"].get("features") or [])]
    d = [p["dist_to_building_m"] for p in fs if p.get("dist_to_building_m") is not None]
    lv = None
    for p in fs:
        lv = _worse(lv, p.get("level")) if lv else p.get("level")
    note = (L["yard"].get("note") or "").strip()
    # 「종류」는 담지 않는다 — 각주를 걷어 낸 뒤로 쓰는 곳이 없고, 종이에서도 그 칸이
    # 빠졌다(2026-08-23). 필요해지면 레이어에서 다시 뽑으면 된다.
    return {"n": len(fs), "min_m": min(d) if d else None, "level": lv, "note": note}


def _font(px):
    for q in ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"):
        if Path(q).exists():
            try:
                return ImageFont.truetype(q, px)
            except Exception:                                     # noqa: BLE001
                pass
    return ImageFont.load_default()


def pair_png(p1, p2, lab1, lab2, out):
    """두 날짜 그림을 **같은 높이로 맞춰** 나란히 붙이고 위에 촬영일 띠를 얹는다.

    항목마다 한 면에 넣는 이유: 눈이 두 그림을 왕복해야 변화가 보이는데, 면을 넘기면 그 왕복이
    끊긴다. 높이를 맞추는 것도 그래서다 — 축척이 다르면 같은 건물이 다르게 보인다.
    """
    a, b = Image.open(p1).convert("RGB"), Image.open(p2).convert("RGB")
    h = min(a.height, b.height)
    a = a.resize((round(a.width * h / a.height), h), Image.LANCZOS)
    b = b.resize((round(b.width * h / b.height), h), Image.LANCZOS)
    bar, gap, pad = max(26, h // 22), max(8, h // 90), 2
    img = Image.new("RGB", (a.width + gap + b.width, h + bar + pad), (255, 255, 255))
    img.paste(a, (0, bar + pad)); img.paste(b, (a.width + gap, bar + pad))
    dr = ImageDraw.Draw(img)
    f = _font(int(bar * 0.62))
    for x, w, t in ((0, a.width, lab1), (a.width + gap, b.width, lab2)):
        dr.rectangle([x, 0, x + w - 1, bar - 1], fill=(31, 56, 100))
        dr.text((x + (w - dr.textlength(t, font=f)) / 2, bar * 0.18), t, font=f,
                fill=(255, 255, 255))
    img.save(out)
    return out


def _date(r):
    return FR.scene_date(r["site"])


def _imgs(r, d, *, skip=(), force=()):
    """한 날짜분 결과 그림 세 장 — **데모 보고서와 같은 함수**로 그린다.

    `force` 는 **두 날짜가 같이 번호를 줄 상대**다(`common_ext`) — 안 주면 창 가장자리에
    걸친 건물이 한쪽 그림에서만 번호를 잃어, 나란히 놓은 두 그림이 서로 다른 것을 가리킨다.
    """
    d.mkdir(parents=True, exist_ok=True)
    site, L = r["site"], r["layers"]
    near = FR._neighbors(r)
    return {"sep": FR.img_separation(site, L["buildings"], L["separation"], near,
                                     d / "1_이격거리.png", skip=skip, force=force),
            "yard": FR.img_yard(site, L["buildings"], L["yard"], near, d / "2_야적물.png"),
            "led": FR.img_ledger(site, L["buildings"], L["ledger"], d / "3_미등록증축.png")}


# ── 내용 한 벌 ──────────────────────────────────────────────────────────────
def _dm(v1, v2):
    """(차이, 문구). 한쪽이 없으면 (None, '—')."""
    if v1 is None or v2 is None:
        return None, "—"
    d = v2 - v1
    return d, f"{d:+,.1f}"


def _overview(r1, r2, d1, d2, sc2, skip):
    """1면 개요 — 한 시점 보고서와 **같은 줄**이고 「2차 영상」 줄만 더 붙는다.

    **「적재 구역 출처」 줄은 두지 않는다**(사용자 결정, 2026-08-27). 적재 구역을 사람이
    정했는지는 **3면 적재 표의 제목**이 이미 말한다(`yard_demo` → 「손으로 정한 값」) —
    개요에 한 줄 더 두면 같은 사실이 종이에 두 번 적히고, 1면은 이 물건의 사실을 싣는
    자리인데 그 줄은 도구 사정이다.
    """
    return FR.overview_rows(
        r1, FR._ledger_view(r1), DR.dong_names(r1["layers"]["buildings"]), skip=skip,
        scene2=f"위성 정사영상 {sc2.get('res_m')} m/px  ·  촬영일 {d2}  ·  {sc2.get('ko')}")


def build_doc(r1, r2, imgs1, imgs2, *, skip=()):
    """변화 탐지 1면 + 항목 면 셋.

    **야적·대장 면은 데모 보고서의 면을 그대로 쓴다** — `for_report.build_doc` 을 날짜마다
    불러 `kind` 로 항목 면만 골라내고 제목에 날짜 딱지를 붙여 **날짜별 표를 나란히** 둔다.
    그 두 항목은 줄마다 견줄 짝이 없다 — 적재 구역도 대장 동도 두 날짜에서 같은 것이라는
    보장이 없으니, 표를 합치면 어느 줄이 어느 줄과 짝인지 지어내는 셈이 된다.

    **이격 면만 표를 뒤집는다**(`sep_change_groups`, 2026-08-23) — 이격은 짝이 있다(둘레의
    같은 자리, 같은 번호). 열을 번호로 두고 행을 전 · 후 · 변화 여부로 두면 한 열이 곧 「그
    자리에서 무엇이 달라졌나」이고, 날짜별로 표 두 벌을 늘어놓을 때처럼 눈이 번호를 맞추며
    왕복하지 않아도 된다.

    데모 보고서를 고치면 이 보고서의 야적·대장 면도 같이 바뀐다.
    """
    d1, d2 = _date(r1), _date(r2)
    sp1, sp2 = sep_metrics(r1["layers"], skip=skip), sep_metrics(r2["layers"], skip=skip)
    ld1, ld2 = led_metrics(r1["layers"]), led_metrics(r2["layers"])
    yd1, yd2 = yard_metrics(r1["layers"]), yard_metrics(r2["layers"])
    sc2 = r2["site"].get("scene") or {}

    # ── 항목별 변화 판정
    rows, worst = [], "변화 없음"
    # 이름은 **짧게, 작대기 없이**(2026-08-23). 「이격거리 — 필지 내 최소」처럼 작대기를 긋고
    # 덧말을 붙이면 한 칸에 설명이 들어앉는다 — 무엇을 잰 값인지는 뒤 면의 같은 이름 표가
    # 말하고, 단위는 차이 칸(± m)이 말한다.
    for key, ko in (("in", "이격거리(필지 내 최소)"), ("out", "이격거리(필지 외 최소)")):
        a, b = sp1[key]["min_m"], sp2[key]["min_m"]
        dv, dt = _dm(a, b)
        # **두 날짜 다 잰 것이 없으면 「변화 없음」이다** — 필지 내 쌍이 애초에 없는 물건
        # (이 지번 건물이 하나뿐)이 그렇다. 그것을 「판단 보류」로 적으면 못 잰 것처럼
        # 읽히는데, 없던 것이 두 날짜에 다 없었으면 그 사이에 달라진 것도 없다.
        if a is None and b is None:
            v = "변화 없음"
        elif a is None or b is None:
            # 한쪽에만 있다 — 오차선으로 가릴 수 없다. 등급이 나빠졌으면 그렇게 적는다.
            v = "변화 확인"
        else:
            v = verdict(dv, RL.SEP_MEASURE_ERR_M, sp1[key]["level"], sp2[key]["level"])
        rows.append([ko, DR.dist_text(a) if a is not None else "—",
                     DR.dist_text(b) if b is not None else "—",
                     f"{dt} m" if dv is not None else "—", _c(v)])
        worst = _cw(worst, v)
    dv, dt = _dm(ld1["measured"], ld2["measured"])
    pct = (dv / ld1["measured"] * 100) if (dv is not None and ld1["measured"]) else None
    v_area, area_dir = area_verdict(dv, pct, ld1["level"], ld2["level"])
    rows.append([("판독 건물 면적 합계" if v_area == "변화 없음"
                  else f"판독 건물 면적 합계\n{area_dir}"),
                 _m2(ld1["measured"]), _m2(ld2["measured"]),
                 (f"{dt} ㎡ ({pct:+.0f} %)" if dv is not None else "—"), _c(v_area)])
    # 대장 줄은 **4면과 같은 말**로 적는다(일치·불일치·판정 불가) — 한때 이 줄만 일곱
    # 등급을 옮기는 다른 표를 써서 「이상 없음」이라고 적었다. 대장이 아예 없으면 `None` 을
    # 넘겨 「판정 불가」가 되게 한다(`led_match` 가 그렇게 읽는다).
    rows.append(["대장 정합 판정(미등록·증축)",
                 FR.led_lv(ld1 if ld1.get("level") else None)[0],
                 FR.led_lv(ld2 if ld2.get("level") else None)[0],
                 ("변화 없음" if ld1["level"] == ld2["level"] else "바뀜"),
                 _c("변화 확인" if ld1["level"] != ld2["level"] else "변화 없음")])
    # **두 날짜 다 0 곳이면 「변화 없음」이다.** 예전에는 「판단 보류」로 두었는데, 돌려서
    # 아무것도 안 나온 것은 못 잰 것이 아니라 **없다는 결과**다 — 두 날짜에 다 없었으면 그
    # 사이에 달라진 것도 없다([[single.py]] 의 야적 표도 같은 말로 적는다).
    v_yard = ("변화 확인" if (_degraded(yd1["level"], yd2["level"]) or yd1["n"] != yd2["n"])
              else "변화 없음")
    rows.append(["야외 적재물 구역 수", f"{yd1['n']}개소", f"{yd2['n']}개소",
                 f"{yd2['n'] - yd1['n']:+d}개소", _c(v_yard)])
    for v in (v_area, v_yard):
        worst = _cw(worst, v)
    n_chg = sum(1 for r in rows if FR._cell(r[4])[0] in ("변화 있음", "변화 확인"))

    p1 = {"kind": "diff",
          "title": f"위성 비교분석 — {r1['site']['address']}",
          # **1면 제목 밑에는 아무 글도 두지 않는다** — 한 시점 보고서의 1면도 그렇다
          # (`single` 의 overview 면). 무엇을 본 문서인지는 제목과 바로 아래 표가
          # 말하므로, 부제로 다시 말하면 설명이 하나 늘 뿐이다. 자리는 판이 갈리지 않게
          # 비운 채로 남는다(`single` 의 렌더가 그렇게 한다).
          "sub": "",
          "blocks": [
              ("tbl", [["종합", "촬영 간격", "변동 항목"],
                       [_c(worst), _gap_days(d1, d2), f"{n_chg}건"]],
               {"colw": [1 / 3] * 3, "head": True}),
              ("sec", "물건 개요"),
              ("tbl", _overview(r1, r2, d1, d2, sc2, skip),
               {"colw": [0.22, 0.78], "label": True}),
              ("sec", "변화 판정 기준"),
              ("tbl", [["항목", "변화 판정 기준", "근거"],
                       ["이격거리", f"|차이| ≥ {RL.SEP_MEASURE_ERR_M} m",
                        "두 건물 간 거리 측정오차 고려"],
                       ["건물 면적", f"|차이| ≥ {RL.LEDGER_EXT_MIN_M2:.0f} ㎡ 이고 "
                                 f"≥ {RL.LEDGER_MODEL_AREA_ERR * 100:.0f} %",
                        "측정오차와 구분되는 유의 수준"],
                       ["야외 적재물", "구역 수 또는 판정의 변동",
                        "적재량은 위성 영상으로 측정하지 않음"]],
               {"colw": [0.20, 0.38, 0.42], "head": True}),
              ("sec", "변화 탐지 결과"),
              ("tbl", [["항목", f"1차 ({d1})", f"2차 ({d2})", "차이", "변화 여부"]] + rows,
               {"colw": [0.28, 0.17, 0.17, 0.18, 0.20], "head": True}),
          # **회색 각주는 두지 않는다**(2026-08-23). 표에 적힌 값이 무슨 뜻인지는 표의 머리와
          # 판정어가 말한다 — 각주로 다시 말하면 종이마다 글이 늘고, 물건에서 실제로 벌어진
          # 일까지 각주에 적으면 표와 각주 둘 중 어느 것이 결과인지 알 수 없다.
          ]}

    # ── 항목 면 — **데모 보고서의 면을 날짜마다 만들어 블록만 가져와** 한 면에 합친다
    #    (면을 그대로 두 장 쓰지 않는 이유: 이미지를 나란히 놓아야 차이가 눈에 보인다)
    docs = {i: FR.build_doc(r, im, near=FR._neighbors(r), skip=skip, ctx=None)
            for i, (r, im) in ((1, (r1, imgs1)), (2, (r2, imgs2)))}
    pages = [p1]
    # **이격 면만 표를 뒤집는다** — `sep_change_groups` 를 보라. 야적·대장은 날짜별 표를
    # 나란히 두는 것이 그대로 낫다(줄마다 견줄 짝이 없다 — 구역도 대장 동도 두 날짜에서
    # 같은 것이라는 보장이 없다).
    # 손으로 자리를 정한 날짜는 **그 표 위에** 밝힌다(1면 개요에도 한 줄 선다) — 표만 보고
    # 넘어가는 사람이 판독 결과로 읽지 않게.
    hand = (yard_demo(r1["layers"]), yard_demo(r2["layers"]))   # None 이면 표시 없음
    for kind, ko, gr in (("sep", "① 건물 이격거리 변화",
                          sep_change_groups(r1, r2, d1, d2, skip=skip)),
                         ("yard", "② 야외 적재물 변화", None),
                         ("led", "③ 미등록·증축 변화", None)):
        pages += item_pages(kind, ko, docs, imgs1, imgs2, d1, d2, groups=gr,
                            mark=(hand if kind == "yard" else (None, None)))
    return pages


# ── 이격 변화 표 — **열이 번호, 행이 전·후** ────────────────────────────────
def _dong_sep_rows(r, *, skip=(), keep=(), force=()):
    """한 날짜분 → ({동 이름: {열쇠: 줄}}, 동 차례) — **한 시점 보고서와 같은 함수**로 뽑는다
    ([[single.py]] `sep_dong_rows`). 두 문서가 같은 표를 다른 모양으로 내면 안 된다."""
    L = r["layers"]
    dong, ext = FR.sep_labels(r, FR._neighbors(r), skip=skip, force=force)
    by = FR.sep_dong_rows(L["separation"], dong, ext, skip=skip, keep=keep)
    return ({name: _keyed(rows, _rowkey) for name, rows in by.items()},
            [n for n in FR.dong_order(dong) if n in by])


def common_ext(r1, r2, *, skip=()):
    """두 날짜가 **같이 번호를 줄** 옆 지번 건물 — 한쪽에서라도 번호를 받은 것의 합집합.

    번호를 주는 잣대는 「창 안쪽 상자에 배지 한 개를 앉힐 수 있나」인데(`draw.label_box`),
    두 영상의 지붕 시차는 1~2 m 라 **같은 건물이 그 문턱을 사이에 두고 갈릴 수 있다** —
    실측 신당동 1187-2 N0028 은 창 안으로 1차 4.01 m · 2차 5.11 m 들어와 1차만 번호를
    잃었다. 그러면 나란히 놓은 두 그림이 서로 다른 것을 가리키고, 표에서는 없던
    「변화 확인」이 생긴다.

    합집합으로 두는 까닭은 **덜 보이는 쪽에 맞추면 잘 보이는 쪽의 정보를 버리기** 때문이다.
    번호를 더 받는 쪽은 그 배지가 화면 가장자리에 앉을 뿐 가리키는 것이 없어지지는 않는다.
    """
    out = set()
    for r in (r1, r2):
        _dong, ext = FR.sep_labels(r, FR._neighbors(r), skip=skip)
        out |= {b for b, n in ext.items() if n}
    return out


def _hidden(r, *, skip=()):
    """그 날짜에 **종이에서 뺀 상대**의 bld_id — 지도·표가 쓰는 그 함수 그대로."""
    _dong, ext = FR.sep_labels(r, FR._neighbors(r), skip=skip)
    return DR.sep_hidden(r["layers"]["separation"], ext, skip=skip)


def _rowkey(q):
    """두 날짜의 줄을 맞추는 열쇠 — **번호가 아니라 방위와 자리**다.

    번호는 둘레를 도는 차례라 한 날짜에 이웃이 하나 늘거나 빠지면 **그 뒤가 통째로 밀린다**
    (실측 2026-08-26 호산동 702-5: 2차에서 동쪽 한 구간이 빠져 ③ 이하 여섯 줄이 서로 다른
    상대끼리 짝지어졌다). 줄은 둘레 순으로 늘어서 있으므로 **같은 방위의 몇 번째**가 훨씬
    안정된 이름이다 — `_keyed` 가 같은 열쇠에 순번을 붙인다.

    필지 안 줄은 **상대 동 이름**으로 맞춘다(A동↔B동). 그 이름은 날짜가 달라도 같다.
    """
    return f"own:{q['no']}" if q.get("kind") == "own" else f"{q.get('kind')}:{q['dir']}"


def _keyed(rows, key):
    """줄 목록 → {열쇠: 줄}. **같은 열쇠가 두 번 나오면 뒤에 순번을 붙인다** — 번호를 못 받은
    줄(창 밖 상대)이 여럿이면 「— 남동」이 겹쳐 하나로 덮인다."""
    out, seen = {}, {}
    for q in rows:
        k = key(q)
        seen[k] = seen.get(k, 0) + 1
        out[f"{k}#{seen[k]}" if seen[k] > 1 else k] = q
    return out


def _sep_cell(q, res):
    """전·후 칸 — 「① 3.3 m · 위험」. **거리는 먹색, 이격 번호와 판정은 판정색**이다.

    **번호를 날짜 칸 안에 둔다**(2026-08-27, 사용자 결정). 그 번호는 그 날짜 지도의 거리
    배지가 달고 있는 바로 그 번호라([[draw.py]] `_meas_text` 의 「① 2.5 m」) 칸과 그 날짜의
    그림이 번호 하나로 이어진다. **날짜마다 자기 칸에 자기 번호를 적으므로** 두 날짜의 번호가
    달라도 거짓이 되지 않는다 — 한 칸에 하나만 적어 두 날짜를 잇는 것이 아니다.

    번호를 못 받은 줄(창 밖 상대)은 `id` 가 「—」다. 그때는 **적지 않는다** — 「— 3.3 m」는
    번호가 「—」인 것처럼 읽힌다.
    """
    if q is None:
        return "—"
    word, color = FR.sep_lv(q["level"])
    runs = [(f"{DR.dist_text(q['dist'], res_m=res)} · ", None), (word, color)]
    no = str(q.get("id") or "—")
    if no != "—":
        runs.insert(0, (f"{no} ", color))
    return FR.Runs(runs)


def _sep_chg(q1, q2):
    """전·후 한 짝 → 변화 여부 칸. 한쪽에만 있는 줄은 **오차선으로 가릴 수 없다.**"""
    if q1 is None or q2 is None:
        return _c("변화 확인")
    return _c(verdict(q2["dist"] - q1["dist"], RL.SEP_MEASURE_ERR_M,
                      q1["level"], q2["level"]))


# 이격 변화 표 열 폭 — 번호 · 방위 · 1차 · 2차 · 변화 여부.
# 번호가 날짜 칸으로 들어가면서 그 두 칸이 넓어야 한다(`_sep_cell`) — 앞의 두 칸에서 뗀다.
CHG_OPT = {"colw": [0.11, 0.12, 0.28, 0.28, 0.21], "head": True}


def row_no(q1, q2):
    """변화 표의 번호 칸 — **하나만 적는다.** 1차 번호가 정본이고, 없으면 2차 번호를 쓴다.

    예전에는 두 날짜의 번호가 다르면 둘 다 적었다(「④→③」). 이웃이 하나 늘거나 빠지면 그
    뒤의 번호가 밀리므로 같은 상대가 두 날짜에서 다른 번호를 받고, 한쪽만 적으면 그 날짜의
    지도에서 그 번호를 못 찾기 때문이었다. 그런데 **칸 하나에 번호가 둘 들어가면 읽는 사람이
    먼저 「이게 무슨 뜻이냐」를 묻는다**(사용자 결정, 2026-08-27) — 표는 한 줄이 한 상대라는
    것이 먼저 읽혀야 한다.

    2차 지도에서 그 상대를 찾는 길은 남아 있다: 줄의 방위와 거리가 그 자리를 가리키고,
    2차 그림의 배지는 그림 자신의 번호를 쓴다.
    """
    # **「—」도 없는 것으로 본다**(2026-08-27). 한쪽 날짜에서만 창에 걸려 번호를 못 받은 줄이
    # 살아 있게 되면서(`sep_change_rows` 의 `keep`) 1차 번호가 「—」인 짝이 생겼는데, 그대로
    # 쓰면 상대가 분명히 있는 줄의 상대 칸이 비어 2차 지도에서도 못 찾는다.
    for q in (q1, q2):
        no = (q or {}).get("no")
        if no and no != "—":
            return no
    return "—"


def sep_change_rows(r1, r2, *, skip=()):
    """{동 이름: [(1차 줄, 2차 줄), …]} — **번호·방위로 짝지은** 전·후 한 벌.

    한쪽에만 있는 줄은 그쪽이 `None` 이다. **자리로 짝짓지 않는다** — 한쪽에만 있는 구간이
    생기면 그 뒤가 통째로 밀려 엉뚱한 줄끼리 견주게 된다(실측 2026-08-26 호산동 702-5:
    1차 8줄 · 2차 7줄에서 「③ 동 15.9 m」가 2차의 「③ 남 4.9 m」와 짝지어졌다).

    종이 고치기([[refit.py]] `cmp_rows`)도 이 함수를 쓴다 — 짝짓기가 두 곳에 있으면 화면과
    종이가 다른 줄을 견준다.
    """
    # **종이에서 빼는 것은 두 날짜가 같이 한다**(2026-08-27, 사용자 결정). 한쪽에서만 빠지면
    # 그 줄의 짝이 「—」가 되어 **없던 변화가 인쇄된다** — 창 가장자리에 걸친 상대는 두 영상의
    # 지붕 시차(1~2 m)만으로 한쪽에서만 배지를 잃기 때문이다. 한쪽에라도 번호가 있으면
    # (`^` = 한쪽에서만 뺀 상대) 두 날짜 다 살린다. 둘 다 뺀 상대는 그대로 뺀다 — 그때는
    # 짝이 온전하므로 「변화 확인」이 지어지지 않는다.
    # **그림과 같은 잣대로 번호를 준다**(`common_ext`) — 표와 그림이 갈리면 번호가 뜻을 잃는다.
    force = common_ext(r1, r2, skip=skip)
    keep = _hidden(r1, skip=skip) ^ _hidden(r2, skip=skip)
    g1, names1 = _dong_sep_rows(r1, skip=skip, keep=keep, force=force)
    g2, names2 = _dong_sep_rows(r2, skip=skip, keep=keep, force=force)
    out = {}
    for name in names1 + [n for n in names2 if n not in names1]:
        k1, k2 = g1.get(name, {}), g2.get(name, {})
        out[name] = [(k1.get(k), k2.get(k))
                     for k in list(k1) + [k for k in k2 if k not in k1]]
    return out


def sep_change_groups(r1, r2, d1, d2, *, skip=()):
    """이격 면의 표 — **대상 동마다 하나**, 한 줄에 1차·2차를 나란히 둔다.

    한 시점 보고서의 2면과 **같은 표**다(번호 · 방위 · 거리 · 판정) — 거기에 날짜 두 칸이
    붙었을 뿐이라, 같은 물건의 두 문서를 오갈 때 표를 다시 읽지 않아도 된다. 예전에는 열을
    번호로 두고 행을 전·후로 뒤집었는데, 그러면 한 시점 보고서와 표 모양이 갈렸다.

    짝을 맞추는 열쇠는 **번호와 방위**다 — 두 날짜에 같은 규칙으로 다시 매기므로 같은 자리에
    같은 번호가 온다. 한쪽에만 있는 줄은 「—」로 두고 변화 여부를 「변화 확인」으로 적는다.
    """
    res = (r1["site"].get("scene") or {}).get("res_m") or 0.5
    # **이격 번호는 날짜 칸 안에 넣는다**(2026-08-27, 사용자 결정 · `_sep_cell`).
    #
    # 열을 따로 두지 않는 까닭은 그 전에 적어 둔 그대로다 — 두 날짜의 측정선이 같은 선이라는
    # 보장이 없어서(이웃이 하나 늘거나 빠지면 뒤가 통째로 밀린다 · `_rowkey` 가 번호가 아니라
    # 방위·갈래로 짝짓는 것도 그래서다) **공용 칸 하나에 적으면 없는 대응을 지어낸다.**
    # 날짜 칸 안에 넣으면 그 문제가 없다: 「1차 ①」과 「2차 ③」이 나란히 서도 각자 자기 날짜의
    # 지도를 가리킬 뿐이고, 두 줄이 한 행에 있다는 사실은 방위·갈래가 이미 말한다.
    head = ["외부건물 번호", "방위", f"1차 ({d1})", f"2차 ({d2})", "변화 여부"]
    groups = []
    for name, pairs in sep_change_rows(r1, r2, skip=skip).items():
        rows = [head]
        for q1, q2 in pairs:
            rows.append([row_no(q1, q2), (q1 or q2)["dir"],
                         _sep_cell(q1, res), _sep_cell(q2, res), _sep_chg(q1, q2)])
        if len(rows) == 1:
            rows.append(["—", "—", "—", "—", _c("변화 없음")])
        groups.append([("sec", f"{name} 이격거리 변화"), ("tbl", rows, CHG_OPT)])
    if not groups:
        groups = [[("sec", "이격거리 변화"),
                   ("tbl", [head, ["—", "—", "—", "—", _c("변화 없음")]], CHG_OPT)]]
    return groups


IMG_FLOOR = 0.24          # 이보다 줄이면 선·배지가 뭉개져 비교하는 뜻이 없어진다


def _pick(doc, kind):
    """그 항목의 면(들)에서 (범례, [(절제목, 표블록), ...], 각주) 를 꺼낸다.

    표를 **(절 제목, 표) 짝**으로 묶는 이유: 비교 면에서 같은 표의 1차·2차를 붙여 놓아야
    읽힌다. 이격은 표가 길면 데모에서 면이 갈리므로 그 항목의 면 전부를 훑어 모은다.
    """
    leg, units, notes, sec = None, [], [], None
    for q in doc:
        if q.get("kind") != kind:
            continue
        for b in q["blocks"]:
            if b[0] == "legend" and leg is None:
                leg = b[1]
            elif b[0] == "sec":
                sec = b[1]
            elif b[0] == "tbl":
                units.append((sec, b))
                sec = None
            elif b[0] == "note" and b[1] not in notes:
                notes.append(b[1])
    return leg, units, notes


def _units(body):
    """블록들이 먹는 세로(figure 비율).

    **줄 수를 셀의 줄바꿈까지 세어야 한다.** 대장 표는 「대장 동 · 용도 · 구조」가 두 줄이라
    행 수로만 세면 표가 실제보다 짧게 잡히고, 그만큼 종이 밑으로 흘러넘친다(실측: 신당동
    322 · 파호동 93-17 · 호산동 704-1 이 2 mm 씩 넘쳤다). 데모 보고서가 같은 표에 1.62 배를
    곱해 두는 것과 같은 이유다.
    """
    u = 0.0
    for b in body:
        if b[0] == "sec":
            u += FR.SEC_H
            continue
        rows = b[1]
        n = 1.15                                   # 머리행
        for row in rows[1:]:
            n += max((FR._nlines(c) for c in row), default=1)
        u += FR.ROW_H * n + 0.017                  # 표 아래 여백
    return u


def _cut_last(tb):
    """표 맨 아랫줄을 잘라 「외 N줄」로 바꾼다. 이미 「…」 줄이면 세던 수를 늘린다."""
    rows = tb[1]
    last, was = rows[-1], 0
    if isinstance(last[0], str) and last[0] == "…":
        was = int("".join(ch for ch in str(last[-1]) if ch.isdigit()) or 0)
        rows = rows[:-1]
    keep = rows[:-1]
    keep.append(["…"] + [""] * (len(rows[0]) - 2) + [f"외 {was + 1}줄"])
    tb[1] = keep


# 항목 면 절 제목 — **비교분석은 짧게 적는다.** 한 시점 보고서는 그 면 하나가 설명을 다
# 해야 하니 「대장에 적힌 것 ↔ 위성에서 판독한 면적 (동 대응은 …)」처럼 길어도 되지만, 이
# 문서는 같은 표가 날짜마다 두 번 나오고 그 뒤에 날짜 딱지까지 붙는다 — 긴 이름을 두 번
# 읽히면 정작 견주어야 할 숫자가 뒤로 밀린다. 한 시점 보고서의 문구는 그대로 두고
# ([[single.py]] 는 그쪽 몫이다) **이 문서에서 부르는 이름만** 여기서 정한다.
# 절 제목은 **한 시점 보고서와 같은 말**이다 — 같은 물건의 두 문서에서 같은 표가 다른
# 이름으로 불리면 어느 것이 어느 것인지 되짚어야 한다([[single.py]] 3·4면).
SEC_SHORT = {"led": "대장 ↔ 위성 건축면적 비교", "yard": "적재 구역 탐지 결과"}


def _short_sec(kind, sec, first):
    """절 제목 → 이 문서에서 부를 이름. 첫 표는 짧은 이름, 그 뒤는 덧말만 떼어 낸다."""
    if first and kind in SEC_SHORT:
        # 첫 표는 못 박은 이름 + 원본의 덧말(「(동 대응은 면적 기준 추정)」)을 그대로 잇는다.
        extra = sec.split("비교", 1)[1].strip() if (sec and "비교" in sec) else ""
        return f"{SEC_SHORT[kind]}  {extra}".rstrip() if extra else SEC_SHORT[kind]
    if not sec:
        return sec
    for cut in ("↔", "—"):
        if cut in sec:
            sec = sec.split(cut)[0]
    return sec.strip()


# 야적 표의 판정은 **위험분석 3면과 같은 말**이다 — 거리로 갈린 안전 · 주의 · 위험
# ([[single.py]] `_zone_lv`, 사용자 결정 2026-08-27). 한때 이 문서만 탐지된 구역을 거리와
# 무관하게 전부 「확인 필요」로 덮어썼는데(`_yard_verdicts`), 그러면 1면 「판정 기준」 표가
# 6 m / 15 m 로 갈라 놓은 것을 3면이 하나로 뭉개고, 같은 값을 두 문서가 다른 말로 적었다.


HAND_MARK = {"비움": "데모용으로 비움", "손으로 정함": "데모용 · 사람이 정한 자리"}


def _group_blocks(u1, u2, d1, d2, *, kind=None, first=True, mark=(None, None)):
    """짝 하나 → 블록들. 같은 표의 1차·2차를 붙여 놓고 절 제목에 날짜를 단다.

    `mark` 가 참인 날짜는 제목에 **손으로 정한 값**임을 적는다(이 파일 `yard_demo`).
    """
    out = []
    for (sec, tb), tag, hand in ((u1, f"1차 · {d1}", mark[0]), (u2, f"2차 · {d2}", mark[1])):
        name = _short_sec(kind, sec, first)
        head = f"{name}   ·   {tag}" if name else tag
        out.append(("sec", f"{head}   ·   {HAND_MARK[hand]}" if hand else head))
        out.append(tuple(tb))
    return out


def _fit_pair(blocks, room):
    """자리가 모자라면 **같은 위치의 1차·2차 표를 같은 줄 수로** 자른다.

    한쪽만 자르면 1차 1줄 · 2차 2줄이 되어 **차이가 없는데도 달라 보인다**(실측 호산동 704-1).
    비교표에서 그것은 값을 틀리게 적는 것과 같다. 잘렸다는 사실은 「외 N줄」로 남긴다.
    """
    bl = [list(x) for x in blocks]
    tbs = [x for x in bl if x[0] == "tbl"]
    pairs = list(zip(tbs[0::2], tbs[1::2]))
    while _units(bl) > room and pairs:
        big = max(pairs, key=lambda pr: max(len(pr[0][1]), len(pr[1][1])))
        if max(len(big[0][1]), len(big[1][1])) <= 3:
            break
        for tb in big:
            if len(tb[1]) > 2:
                _cut_last(tb)
    return [tuple(x) for x in bl]


def item_pages(kind, title, docs, imgs1, imgs2, d1, d2, *, groups=None,
               mark=(None, None)):
    """항목 하나 → 면 목록. **표가 길면 면을 나눈다**(자르는 것보다 낫다).

    한 면에 다 들어가면 한 면으로 낸다. 넘치면 그림을 하한까지 줄이고, 그래도 안 되면
    **표 덩이 단위로 다음 면으로 넘긴다** — 줄을 자르면 그 물건에서 실제로 잰 값이 종이에서
    사라지고, 두 날짜를 견주는 표에서는 그 손실이 특히 아프다. 넘어간다는 사실은 제목의
    「(이어서)」로 남긴다.

    `groups` 를 주면 그 블록 덩이를 그대로 쓴다(이격 면이 그렇다 — 전·후를 한 표에 겹쳐
    두므로 날짜별 표 짝이 아니다). 안 주면 데모 보고서의 날짜별 표를 짝지어 늘어놓는다.

    **회색 각주와 부제는 두지 않는다**(2026-08-23) — 표와 그림에 이미 있는 말이다.
    """
    leg1, u1, _ = _pick(docs[1], kind)
    leg2, u2, _ = _pick(docs[2], kind)
    leg = list(leg1 or [])
    for x in (leg2 or []):
        if x not in leg:
            leg.append(x)
    img = pair_png(imgs1[kind], imgs2[kind], f"1차 · {d1}", f"2차 · {d2}",
                   Path(imgs1[kind]).parent.parent / f"{kind}_비교.png")
    paired = groups is None
    if paired:
        groups = [_group_blocks(a, b, d1, d2, kind=kind, first=(i == 0), mark=mark)
                  for i, (a, b) in enumerate(zip(u1, u2))]

    def room(h, legend=True):
        return (FR.BODY_ROOM - 0.010 - (FR.LEGEND_H if (legend and leg) else 0.0)
                - h - 0.008)

    # 1) 다 들어가나 — 그림을 크게 두고 시작해 하한까지 줄여 본다
    flat = [b for g in groups for b in g]
    h = FR._img_h(str(img), FR.IMG_MAX)
    while h > IMG_FLOOR and _units(flat) > room(h):
        h = round(h - 0.01, 3)
    if _units(flat) <= room(h):
        return [{"kind": kind, "title": title, "sub": "",
                 "blocks": [("img", str(img), {"h": h})]
                           + ([("legend", leg)] if leg else []) + flat}]

    # 2) 안 들어간다 — **표 덩이는 통째로** 다음 면으로 넘긴다.
    #    줄을 자르면 그 물건에서 실제로 잰 값이 종이에서 사라진다. 면은 한 장 더 쓰면 되고,
    #    「(이어서)」로 이어짐을 밝히면 읽는 사람이 잃는 것이 없다. 순서는 지킨다 — 앞 덩이가
    #    안 들어가면 뒤 덩이도 넘긴다(표 순서가 뒤집히면 어느 표인지 찾기 어렵다).
    h = FR._img_h(str(img), FR.IMG_MAX + 0.2)
    r0, first, rest = room(h), [], []
    for g in groups:
        if not rest and _units(first) + _units(g) <= r0:
            first += g
        else:
            rest.append(g)
    pages = [{"kind": kind, "title": title, "sub": "",
              "blocks": [("img", str(img), {"h": h})]
                        + ([("legend", leg)] if leg else []) + first}]
    # 남은 덩이를 표 면에 순서대로 채운다 — 한 면에 다 안 들어가면 면을 더 쓴다.
    tr = FR.BODY_ROOM - 0.010 - 0.008
    cur, n_more = [], 0
    def flush(body):
        nonlocal n_more
        n_more += 1
        pages.append({"kind": kind,
                      "title": f"{title} (이어서)" + (f" {n_more}" if n_more > 1 else ""),
                      "sub": "",
                      # 자르는 것은 **날짜별 표 짝일 때만** 한다 — 뒤집은 표는 한 열이
                      # 전·후·변화 여부 한 벌이라 아랫줄을 자르면 그 열의 변화가 사라진다.
                      "blocks": (_fit_pair(body, tr) if paired else body)})
    for g in rest:
        if cur and _units(cur) + _units(g) > tr:
            flush(cur); cur = []
        cur += g
    if cur:
        flush(cur)
    return pages


def _cw(a, b):
    """변화 판정 둘 중 나쁜 쪽."""
    return a if CHG_ORDER.index(a) <= CHG_ORDER.index(b) else b


def _m2(v):
    return f"{v:,.0f} ㎡" if v is not None else "—"


def _pp(a, b):
    """초과율 차이(%p). 한쪽이라도 못 재면 —."""
    if not (a["ledger"] and b["ledger"]) or a["measured"] is None or b["measured"] is None:
        return "—"
    r1 = (a["measured"] - a["ledger"]) / a["ledger"] * 100
    r2 = (b["measured"] - b["ledger"]) / b["ledger"] * 100
    return f"{r2 - r1:+.0f} %p"


def _pct_txt(ld):
    if not ld["ledger"] or ld["measured"] is None:
        return "—"
    return f"{(ld['measured'] - ld['ledger']) / ld['ledger'] * 100:+.0f} %"


def _gap_days(d1, d2):
    from datetime import date
    try:
        a = date(*[int(x) for x in d1.split("-")])
        b = date(*[int(x) for x in d2.split("-")])
        return f"{abs((b - a).days)}일"
    except Exception:                                             # noqa: BLE001
        return "—"


# ── 조립 ────────────────────────────────────────────────────────────────────
def _short(p):
    """경로를 저장소 기준으로 짧게 — **저장소 밖이면 그대로 낸다.**

    `relative_to` 는 밖이면 ValueError 를 낸다. 화면에 짧게 적자고 실행을 멈출 이유가 없다
    (실측: `--t1` 을 저장소 밖으로 주면 이 print 하나 때문에 비교분석 전체가 실패했다).
    """
    try:
        return Path(p).relative_to(config.HERE)
    except ValueError:
        return Path(p)


def make_side(address, root, scene, *, source="gt", hand=None, yard=True,
              refresh_yard=False, reuse=True, fresh=False, gpu=None, tag=None,
              verbose=True):
    """한 날짜분 결과를 만든다 — **부르는 쪽의 길로**([[analyze.py]] `source`).

    파일 이름은 그 길이 정한다(`demo.json` · `result.json`) — 되읽는 쪽은 둘 다 본다
    ([[single.find_result]]). 야적은 어느 길이든 실제 VLM 판독이다. 이미 있으면 다시 만들지
    않는다(야적 판독은 유료라 같은 영상을 두 번 부를 이유가 없다 — 다시 부르려면
    `refresh_yard`).

    `gpu`·`tag` 는 모델 경로에만 걸린다(추론용). GT 경로에서는 무시된다 — 깃발을 길마다
    갈라 두면 「같은 조건으로 돌렸다」를 말하기 어려워지므로 받아만 두고 넘긴다.
    """
    from sitecheck import analyze as AN
    hand = hand or H.NONE
    d = Path(root) / slug(address)
    # **이름을 출처로 못 박는다.** `FR.find_result` 는 `demo.json` 을 먼저 집는 함수라
    # ([[single.find_result]]), 한 폴더에 두 출처의 값이 있으면 모델 실행이 GT 값을 읽고
    # 「재사용」이라고 찍는다 — 그러면 종이에 모델이 낸 적 없는 숫자가 앉는다.
    # `single.build` 가 `name=` 으로 막아 둔 것과 같은 사고다.
    # **`fresh` 는 「날짜분 결과만 버린다」**(2026-08-27). `reuse=False`(`--no-reuse`)는 추론
    # 캐시까지 열어 모델을 다시 돌리는데, 손보정을 고쳐 값을 다시 내고 싶을 때 필요한 것은
    # 그게 아니다 — 같은 영상·같은 추론에서 **판정만 다시** 나면 된다. 그래서 깃발을 갈라
    # 둔다: `fresh` 는 이 함수가 들고 있는 저장분을 안 쓰고, 안쪽 `analyze` 에는 `reuse` 를
    # 그대로 넘겨 추론·야적 판독 캐시를 살린다(유료 호출도 없다).
    want = d / AN.RESULT_NAME[source]
    have = want if want.exists() else None
    if have and reuse and not refresh_yard and not fresh:
        r = json.loads(have.read_text("utf-8"))
        # **옛 판 결과는 다시 만든다** — 두 시기를 겹쳐 보는 문서라 한쪽만 옛 모양이면
        # 변화가 아닌 것이 변화로 보인다(옛 좌표는 장면 편이만큼 전부 움직인 것으로,
        # 옛 id 는 ①②③ 이 엉뚱한 건물에 붙는 것으로).
        if not SC.is_current(r):
            if verbose:
                print(f"  · {scene}: 저장된 결과가 옛 판({r.get('schema_version')})이라 "
                      f"다시 만든다")
        elif ((r.get("site") or {}).get("scene") or {}).get("key") == scene:
            if verbose:
                # **무엇을 지우면 다시 도는지 같이 찍는다** — 이 줄만 보고 위쪽 보고서
                # 파일을 지워도 아무 일이 없다(재사용을 정하는 것은 이 값 파일이다).
                print(f"  · {scene}: {_short(have)} 재사용"
                      f"  (다시 내려면 `--fresh` 또는 이 파일을 지운다)")
            return _side_images(r, d, verbose=verbose)
    if verbose:
        print(f"  · {scene}: 결과를 만든다 "
              f"(건물 {'GT' if source == 'gt' else '모델 추론'} · 야적 판독)")
    # 날짜별 단일시점 보고서는 만들지 않는다(`report=False`) — 비교분석은 그 면들을 자기
    # 방식으로 다시 짜므로 여기서 뽑으면 같은 렌더를 두 번 하는 셈이다.
    # **`reuse` 를 analyze 까지 흘린다.** 예전에는 `reuse=not refresh_yard` 를 넘겼는데, 그
    # 값은 이 함수 자신의 「저장된 날짜분 결과를 쓸까」 판단에만 쓰이고 analyze 안쪽에는
    # 닿지 않았다 — GT 경로에서는 `reuse` 가 야적 캐시만 건드리니 차이가 안 보였지만, 모델
    # 경로에서는 그 값이 **추론 캐시**까지 건드린다([[steps/s1_building.predict]]). 그래서
    # `--no-reuse` 를 주고 돌려도 옛 추론 결과가 조용히 다시 쓰였다.
    # 두 캐시를 한 깃발이 함께 여는 것은 단일시점 길과 같은 규약이다([[cli.py]]
    # `reuse=not (a.no_reuse or a.refresh_yard)`) — 길마다 뜻이 다르면 「같은 조건으로
    # 돌렸다」를 말할 수 없다.
    r, err = AN.analyze(address, d, source=source, hand=hand, scene=scene, yard=yard,
                        reuse=(reuse and not refresh_yard), gpu=gpu, tag=tag,
                        verbose=verbose)
    if err:
        raise RuntimeError(f"{scene}: {err}")
    # **건물 0동이면 여기서 멈춘다.** [[analyze.py]] 는 GT 실패만 `(None, 사유)` 로 올리고
    # 모델 실패(가중치 없음 · 추론 죽음 · 임계값 이상 폴리곤 없음)는 **빈 buildings 레이어로
    # 삼킨다** — 단일시점에서는 「건물 0동」이 그대로 읽히니 맞는 정책이다. 그런데 비교분석은
    # 두 날짜를 견주는 문서라, 한쪽이 0동이면 이격·면적이 전부 「변화 없음」으로 인쇄된다.
    # 추론이 죽어서 나온 「변화 없음」은 아무도 알아채지 못하므로 그때는 안 내는 쪽이 맞다.
    if source != "gt" and not ((r.get("layers") or {}).get("buildings") or {}).get("count"):
        note = (((r.get("layers") or {}).get("buildings") or {}).get("note") or "").strip()
        raise RuntimeError(f"{scene}: 건물 0동 — 비교분석을 낼 수 없다"
                           + (f" ({note})" if note else ""))
    AN.save(r, d, source=source, hand=hand, images=False, report=False, verbose=verbose)
    return _side_images(json.loads(want.read_text("utf-8")), d, verbose=verbose)


def _side_images(r, d, *, verbose=True):
    """날짜분 폴더에 **재료 두 장**을 남긴다 — 영상 바탕과 건물 폴리곤(`draw.input_images`).

    비교분석 보고서의 그림은 `_이미지/1차`·`2차` 로 나가므로 `t1`·`t2` 에는 값만 남아 있었다.
    그런데 두 시기를 견줄 때 사람이 제일 먼저 보는 것은 **얹은 것 없는 영상과 폴리곤**이다
    (정합이 맞나 · 어느 동이 빠졌나) — 그 두 장은 값 옆에 있어야 한다.

    **재사용 경로에도 둔다** — 이미 만들어 둔 옛 폴더를 다시 돌리면 그림이 채워지게 하기
    위해서다(야적 판독은 다시 부르지 않는다). 실패해도 보고서는 계속 낸다 — 이 두 장은
    보고서가 쓰는 그림이 아니라 폴더에 남기는 재료다.
    """
    try:
        DR.input_images(r, d, near=FR._neighbors(r), verbose=verbose)
    except Exception as e:                                            # noqa: BLE001
        print(f"  · 재료 그림 실패 — {type(e).__name__}: {e}")
    return r


def _same_site(r1, r2, *, verbose=True):
    """두 날짜의 **지도 쪽 사실이 같은지** 확인하고, 다르면 그 사실을 찍는다.

    비교분석은 「영상만 다르고 나머지는 같다」는 전제 위에 선다 — 필지도 대장도 오늘 같은
    API 에서 받아 온 것이라 두 날짜가 다를 이유가 없다. 그런데 날짜분 결과는 **폴더마다
    따로** 만들어지므로(주소 해석도 각자 한 번씩) 어긋날 여지가 있고, 어긋나면 「변화」로
    읽힌다 — 건물이 아니라 필지가 움직여서 생긴 면적 차이를 증축으로 읽는 것이 제일 나쁘다.

    막지는 않는다(어긋난 채로도 종이는 나와야 한다). **말하지 않는 것만 막는다.**
    """
    def facts(r):
        site = r.get("site") or {}
        led = site.get("ledger") or []
        return {"PNU": site.get("pnu"), "대장 동수": len(led),
                "대장 건축면적합": round(sum((x.get("arch_area_m2") or 0) for x in led)),
                "필지 면적": round(site.get("parcel_m2") or 0)}
    a, b = facts(r1), facts(r2)
    diff = [f"{k}: 1차 {a[k]} · 2차 {b[k]}" for k in a if a[k] != b[k]]
    if diff and verbose:
        print("  [!] 두 날짜의 지도 쪽 사실이 다르다 — " + " · ".join(diff)
              + "\n      (영상만 달라야 한다. 이 차이는 건물 변화가 아니라 주소 해석 차이다)")
    return not diff


def build(address, out_stem, *, scene1, scene2, t1_root, t2_root, skip=(), hand=None,
          source="gt", yard=True, refresh_yard=False, reuse=True, fresh=False,
          gpu=None, tag=None, html_too=True, pdf=True, verbose=True):
    hand = hand or H.NONE
    r1 = make_side(address, t1_root, scene1, source=source, hand=hand, yard=yard,
                   refresh_yard=refresh_yard, reuse=reuse, fresh=fresh,
                   gpu=gpu, tag=tag, verbose=verbose)
    r2 = make_side(address, t2_root, scene2, source=source, hand=hand, yard=yard,
                   refresh_yard=refresh_yard, reuse=reuse, fresh=fresh,
                   gpu=gpu, tag=tag, verbose=verbose)
    _same_site(r1, r2, verbose=verbose)
    d = Path(out_stem).parent / f"{Path(out_stem).name}_이미지"
    force = common_ext(r1, r2, skip=skip)
    imgs1 = _imgs(r1, d / "1차", skip=skip, force=force)
    imgs2 = _imgs(r2, d / "2차", skip=skip, force=force)
    doc = build_doc(r1, r2, imgs1, imgs2, skip=skip)
    # `pdf=False` 는 손으로 만든 PDF 를 지키는 자리다 — [[single.py]] `build` 와 같은 규약.
    made = [FR.render_pdf(doc, Path(f"{out_stem}.pdf"))] if pdf else []
    if html_too:
        made.append(FR.render_html(doc, Path(f"{out_stem}.html")))
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description="두 촬영일 → 비교분석 보고서(PDF · HTML)")
    ap.add_argument("addresses", nargs="*", help="주소(여러 개 가능)")
    ap.add_argument("--file", help="주소 목록 파일(한 줄에 하나) — 기본 표본은 cmp_addresses.txt")
    ap.add_argument("--scene1", default="daegu", help="1차 영상 key")
    ap.add_argument("--scene2", default="daegu2", help="2차 영상 key")
    ap.add_argument("--t1", default=None, help="1차 결과 폴더(기본 demo_cmp/t1)")
    ap.add_argument("--t2", default=None, help="2차 결과 폴더(기본 demo_cmp/t2)")
    ap.add_argument("--out", default=None, help="확장자 없는 저장 이름")
    ap.add_argument("--skip-dir", action="append", default=None)
    ap.add_argument("--no-yard", action="store_true", help="야적 판독을 건너뛴다(비용)")
    ap.add_argument("--refresh-yard", action="store_true", help="저장된 판독을 버리고 다시 부른다")
    ap.add_argument("--no-html", action="store_true")
    ap.add_argument("--source", choices=("gt", "model"), default="gt",
                    help="건물 폴리곤의 출처. 기본은 GT(demo_cmp 를 낼 때의 그 길). "
                         "model 은 run.py 와 같은 길이고 결과는 out_cmp 로 낸다")
    ap.add_argument("--gpu", type=int, default=None, help="모델 추론에만 쓴다")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    addrs = list(a.addresses)
    if a.file:
        for ln in Path(a.file).read_text("utf-8").splitlines():
            ln = ln.split("#", 1)[0].strip()      # 인라인 주석 제거 — run.py 와 같은 규칙
            if ln:
                addrs.append(ln)
    if not addrs:
        ap.error("주소를 하나 이상 주세요 (또는 --file cmp_addresses.txt)")
    if a.out and len(addrs) > 1:
        ap.error("--out 은 주소 하나일 때만 쓴다 — 여러 건은 서로 덮어쓴다")

    # 길에 따라 폴더가 다르다 — 한 폴더에 섞으면 무엇이 무엇인지 폴더만 보고 알 수 없다.
    base = config.OUT_CMP if a.source == "model" else config.HERE / "demo_cmp"
    # **한 건이 실패해도 나머지는 낸다.** 목록으로 도는 것이 기본이라 중간에서 멈추면 앞것만
    # 새 판, 뒷것은 옛 판이 되어 demo_cmp 안에서 판이 섞인다 — 그 상태가 제일 알기 어렵다.
    fail = []
    for i, address in enumerate(addrs, 1):
        if len(addrs) > 1 and not a.quiet:
            print(f"[{i}/{len(addrs)}] {address}")
        stem = a.out or str(base / f"위성_비교분석_{slug(address)}")
        Path(stem).parent.mkdir(parents=True, exist_ok=True)
        skip = tuple(a.skip_dir or ())
        try:
            for f in build(address, stem, scene1=a.scene1, scene2=a.scene2,
                           t1_root=a.t1 or (base / "t1"), t2_root=a.t2 or (base / "t2"),
                           skip=skip, source=a.source, yard=not a.no_yard,
                           refresh_yard=a.refresh_yard, gpu=a.gpu,
                           html_too=not a.no_html, verbose=not a.quiet):
                print(f"  → {f}  ({f.stat().st_size / 1024:,.0f} KB)")
        except Exception as e:                                   # noqa: BLE001
            fail.append((address, f"{type(e).__name__}: {e}"))
            print(f"  실패 — {fail[-1][1]}"[:200])
    for address, why in fail:
        print(f"[실패] {address} — {why}"[:200])
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
