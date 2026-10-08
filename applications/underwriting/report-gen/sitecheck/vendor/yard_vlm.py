"""야적물 판독 VLM — 프롬프트·스키마·호출. **자립형**(parcelscan 을 import 하지 않는다).

원본은 `parcelscan/yardscan.py` 다. 폴더를 떼어가도 돌아야 하므로 여기 옮겨 담았고,
**프롬프트 문구는 한 글자도 바꾸지 않았다** — 분류 기준과 판독 절차가 근거문서(A4·A5)와
1:1로 대응하고 있어 문구가 갈리면 리포트의 근거가 흔들린다.

원본이 바뀌면 여기도 같이 바꿔야 한다. 두 벌이 갈렸는지는 `diff` 로 확인한다.
"""
from __future__ import annotations

import base64
import io
import json
import threading
import time
import urllib.error
import urllib.request

import numpy as np

API_URL = "https://api.openai.com/v1/responses"

# 분류·제외 라벨은 rules.py 가 단일 출처다. 여기서는 스키마 enum 으로만 쓴다.
from sitecheck.rules import YARD_CLASSES as _C, YARD_EXCLUDED as _E   # noqa: E402
SUBTYPES = {
    "tarpaulin": "방수포·비닐로 덮임",
    "drums_ibc": "드럼·IBC 용기",
    "containers": "컨테이너 3기 이상",
    "regular_blocks": "규칙적인 덩어리",
    "unclear": "형태 미상",
}
ALL_LABELS = list(_C) + list(_E)

_usage = {"in": 0, "out": 0, "calls": 0, "errors": 0}
_lock = threading.Lock()


SYSTEM = """You are a fire-insurance risk surveyor reading a 0.5 m/px orthophoto tile of a \
Korean industrial area. Every tile covers exactly the same ground area at the same scale, so \
judge sizes consistently.

WHAT YOU ARE LOOKING FOR
Korean fire law (화재예방법 시행령 별표2) lists the goods that make a site a fire risk when
they are stored in bulk: cotton/fibre, bark and wood shavings, rags and waste paper, silk,
straw, combustible solids, coal and charcoal, combustible liquids, WOOD PRODUCTS AND WOOD
SCRAP, and FOAMED RUBBER AND PLASTIC. Stored OUTDOORS these cannot be sprinklered, and 별표3
requires them to sit at least 6 m from any building. Your job is to find such material lying
in the open, and nothing else.

*** THIS IS A PROPOSAL STEP, NOT THE VERDICT. *** Everything you report is re-examined: an
exact outline is cut, the spectral bands are measured, the shadow is measured for height, and
the spot is shown again magnified next to a HIGHER-RESOLUTION AERIAL PHOTO that settles
roof-versus-ground far better than this 0.5 m view can. Wrong guesses are cheap and get
removed there. A pile you never mention is lost for good. So report every distinct stockpile
you can see, including ones you are only moderately sure about, and let `confidence` carry
your doubt.

ANNOTATION
  · DARK BLUE VEIL with CYAN edge = known buildings. Do not report material there.
  · YELLOW outlines = land parcels under review. Prefer material inside them.
  · The veil is INCOMPLETE — some real buildings are missing from it, so apply the roof test
    everywhere, not only outside the veil.

DECIDE IN THIS ORDER, for every candidate patch:

STEP 1 — IS IT ON THE GROUND?
Korean factories have saw-tooth and ribbed metal roofs whose parallel ridges look exactly like
rows of stacked timber. This was the single largest error in the previous run. A ROOF is an
elevated plane: its texture stops dead at a clean straight boundary, one side carries the
building's own shadow (the caption tells you which side shadows fall), ridges run the FULL
length of the plane at perfectly even spacing, and roof furniture (vents, monitors, skylight
strips) repeats along it. GROUND is continuous with roads, aprons and parking; edges are
irregular, spacing varies, and pavement shows between the piles.
If it reads clearly as a roof, skip it. If you truly cannot tell, still report it with
`is_ground_not_roof` = false and low confidence — the aerial check will settle it.

STEP 2 — IS IT STORED MATERIAL AT ALL?
Not material: vegetation, water, shadow, wet ground, road markings, cars in a marked car park,
greenhouses, solar arrays, tanks, silos, conveyors, machinery, and construction earthworks in
progress.

STEP 3 — WHICH LABEL? Use exactly these seven.

TARGET — reported to the underwriter
  timber_pallet    Wood. Brown/grey slatted rectangular modules repeating in rows; sawn timber
                   stacks are aligned along their long axis; pallet towers are banded and of
                   uniform size. Tone is a warm mid-grey-brown, close to bare ground.
  plastic_rubber   Foamed plastic and rubber. Two very different looks, both count:
                   (a) BRIGHT — white/blue/colour sheeting, wrapped bales, resin sacks, plastic
                       crates, foam blocks; often glossy with specular highlights;
                   (b) DARK — matte black mounds of tyres or rubber, round outlines, granular.
  waste_recycle    Waste and recycling heaps. Irregular boundary, mixed colours, no repeating
                   module; compressed bales are regular blocks stacked in a yard that also
                   holds loose heaps. Skips, hoppers and a wheel loader nearby support this.
  other_stock      Bulk stored in the open whose material you cannot name. INCLUDES anything
                   under tarpaulin or sheeting, drums and IBC totes, and groups of THREE OR
                   MORE shipping containers. Field survey decides what it is.

NOT TARGET — label them so they are not mistaken for the above; they are dropped later
  metal_scrap      Grey-brown irregular metal heaps, glinting, no regular form; steel coils,
                   pipe, rebar, crushed metal. Non-combustible — not in 별표2.
  inert_bulk       Soil, sand, gravel, aggregate, crushed concrete, earthworks. Non-combustible.
  vehicles         Any concentration of vehicles — car park, dealer lot, wrecking yard, truck
                   yard, containers still on trailers. Vehicles are not in 별표2.

Rules that decide close calls:
  · A SINGLE shipping container, or one or two used as a site office or store, is site
    furniture, not a stockpile. Three or more grouped or stacked = other_stock.
  · Tidiness is NOT a reason to skip. Neatly stacked timber, banded pallet towers, rows of
    drums, baled cardboard, wrapped plastic bales and tidy rows of tyres are precisely what
    the fire codes single out. Report tidy stacks and loose heaps alike.
  · If it is combustible but you cannot choose between the three named classes, use
    other_stock. Do not guess a class to look decisive.
  · If it is clearly metal scrap or soil, say so — do not push it into a target class.

BOXES: the smallest axis-aligned rectangle containing the material itself. A later step cuts
the exact outline, so a tight, correctly-centred box matters far more than covering
everything. Two separate stockpiles = two findings. Never one box spanning a whole yard.

Also judge `order` (stacked = uniform modules in rows | piled = loose heap) and `covered`
(under tarpaulin or a canopy). Give `height` as your visual impression only — the height is
measured from the shadow afterwards, so do not agonise over it.

A busy industrial tile commonly holds several separate stockpiles — list them all. An empty
tile of bare roads, fields or housing is a fine "no items" answer, but do not empty a working
factory yard just because each pile is small or hard to name."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "description": "Material stored on open ground, one entry per distinct stockpile.",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["bbox_px", "cls", "subtype", "order", "covered", "height",
                             "confidence", "is_ground_not_roof", "evidence"],
                "properties": {
                    "bbox_px": {"type": "array", "items": {"type": "number"},
                                "minItems": 4, "maxItems": 4,
                                "description": "[x0,y0,x1,y1] in this tile's pixels, TIGHT."},
                    "cls": {"type": "string", "enum": ALL_LABELS},
                    "subtype": {"type": "string", "enum": list(SUBTYPES) + [""],
                                "description": "Appearance of other_stock; \"\" otherwise."},
                    "order": {"type": "string", "enum": ["stacked", "piled"]},
                    "covered": {"type": "boolean"},
                    "height": {"type": "string", "enum": ["low", "mid", "high"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "is_ground_not_roof": {
                        "type": "boolean",
                        "description": "True only if you applied STEP 1 and it is ground."},
                    "evidence": {"type": "string",
                                 "description": "What you saw, in one sentence."},
                },
            },
        },
    },
}



JPEG_Q = 92          # 모델에 보내는 인코딩 — 저장하는 타일도 **같은 값**이어야 한다


def encode(img):
    """타일 → 모델에 보내는 JPEG 바이트. **보내는 쪽과 남기는 쪽이 이 함수 하나를 쓴다.**

    예전에는 보낼 때 q92, 남길 때 q88 로 따로 인코딩해서 「모델에 넣은 그대로」라고 적어 둔
    타일이 실제로는 모델이 본 것보다 더 뭉갠 그림이었다 — 탐지가 왜 그렇게 나왔는지 그 타일로
    따지면 다른 그림을 놓고 따지는 셈이 된다.
    """
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_Q)
    return buf.getvalue()


def call_api(key, model, img, caption, retries=4):
    b64 = base64.b64encode(encode(img)).decode()
    body = {"model": model,
            "input": [{"role": "system", "content": [{"type": "input_text", "text": SYSTEM}]},
                      {"role": "user", "content": [
                          {"type": "input_text", "text": caption},
                          {"type": "input_image",
                           "image_url": f"data:image/jpeg;base64,{b64}",
                           "detail": "original"}]}],
            "text": {"format": {"type": "json_schema", "name": "tile_storage",
                                "strict": True, "schema": SCHEMA}}}
    data = json.dumps(body).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                API_URL, data=data,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            r = json.load(urllib.request.urlopen(req, timeout=300))
            u = r.get("usage", {})
            with _lock:
                _usage["in"] += u.get("input_tokens", 0)
                _usage["out"] += u.get("output_tokens", 0)
                _usage["calls"] += 1
            for it in r.get("output", []):
                if it.get("type") == "message":
                    for c in it.get("content", []):
                        if c.get("type") == "output_text":
                            return json.loads(c["text"])
            raise RuntimeError("no output_text")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:160]}"
            if e.code in (429, 500, 502, 503, 529):
                time.sleep(2.0 ** attempt + 1)
                continue
            break
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(2.0 ** attempt + 1)
    with _lock:
        _usage["errors"] += 1
    raise RuntimeError(last or "unknown")



def compass(u):
    """그림자 단위벡터 → 화면 방향 이름. 캡션에 그대로 쓴다."""
    dx, dy = u
    ns = "lower" if dy > 0.35 else "upper" if dy < -0.35 else ""
    ew = "right" if dx > 0.35 else "left" if dx < -0.35 else ""
    return " ".join(t for t in (ns, ew) if t) or "straight down"


