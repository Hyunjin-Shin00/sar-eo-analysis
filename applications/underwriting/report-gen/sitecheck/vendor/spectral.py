"""4밴드(B,G,R,NIR) 원본 tif 에서 분광 지표를 뽑는다.

밴드 순서 주의
--------------
tif 의 colorinterp 태그는 (red, green, blue, undefined) 로 **틀려 있다**. meta.json 의
`band_order_src = "B,G,R,NIR"` 가 맞다. rasterio 는 1-based 이므로

    1=Blue  2=Green  3=Red  4=NIR

scene.png 는 이 tif 의 [3,2,1] 을 8bit 로 늘린 것이고 `crop_px` 가 없으므로
**scene 픽셀 좌표 = tif 픽셀 좌표(1:1)** 다. 검출 박스 좌표를 그대로 윈도우로 쓸 수 있다.

무엇에 쓰나
-----------
야적 판독(단계 2)에서 **개방지 판정** 하나에 쓴다 — 식생·물·그림자·nodata 를 뺀
진짜 '지면'. 타일에 빈 땅이 얼마 없으면 판독 모델을 부르지 않고(비용), 얼마나
비었는지는 캡션에 넣어 크기 감각을 준다.

지표는 DN(uint16) 기반이다. 대기보정된 반사율이 아니므로 **절대값을 물질 라이브러리와
비교하지 않는다.** 쓰는 것은 밴드 비율(NDVI/NDWI/NIR비)과 장면 내 상대값뿐이다 —
이쪽은 이득/오프셋에 둔감하다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

B, G, R, N = 0, 1, 2, 3          # read() 결과 배열의 축 인덱스
EPS = 1e-6


def scene_tif(scene_dir) -> Path:
    scene_dir = Path(scene_dir)
    meta = json.load(open(scene_dir / "meta.json", encoding="utf-8"))
    src = meta.get("src_tif")
    if src:
        p = (scene_dir.parents[1] / src) if not Path(src).is_absolute() else Path(src)
        if p.exists():
            return p
        p2 = scene_dir / Path(src).name
        if p2.exists():
            return p2
    tifs = sorted(scene_dir.glob("*.tif"))
    if not tifs:
        raise FileNotFoundError(f"{scene_dir} 에 원본 tif 가 없습니다")
    return tifs[0]


def read_window(ds, x0, y0, x1, y1):
    """scene 픽셀창 → (4,H,W) float32. 범위를 벗어나면 잘라서 읽는다."""
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(ds.width, int(np.ceil(x1))), min(ds.height, int(np.ceil(y1)))
    if x1 <= x0 or y1 <= y0:
        return None
    a = ds.read(window=Window(x0, y0, x1 - x0, y1 - y0)).astype(np.float32)
    return a if a.shape[0] >= 4 else None


def indices(a):
    """(4,H,W) → 분광 지표 묶음."""
    b, g, r, n = a[B], a[G], a[R], a[N]
    vis = (b + g + r) / 3.0
    mx = np.maximum(np.maximum(b, g), r)
    mn = np.minimum(np.minimum(b, g), r)
    return {
        "ndvi": (n - r) / (n + r + EPS),
        "ndwi": (g - n) / (g + n + EPS),          # McFeeters, 물 > 0
        "vis": vis,
        "nir_ratio": n / (vis + EPS),
        "sat": (mx - mn) / (mx + EPS),            # 채도: 인공 포장면은 낮다
        "flat": (np.std(a[:3], axis=0) / (vis + EPS)),   # 가시대역 평탄도
        "nodata": (a.sum(axis=0) <= 0),
    }


def open_ground(ix, *, ndvi_veg=0.20, ndwi_water=0.15, shadow_q=0.06):
    """식생·물·그림자·nodata 를 뺀 개방 지면 마스크.

    그림자 기준은 고정 DN 이 아니라 창 안 밝기 분위수로 잡는다. 장면·시각마다 노출이
    다르고, 같은 장면 안에서도 건물 그늘과 노지의 밝기 차가 크기 때문이다.
    """
    vis = ix["vis"]
    ok = ~ix["nodata"]
    if not ok.any():
        return ok
    thr = np.quantile(vis[ok], shadow_q) if ok.sum() > 32 else 0.0
    return ok & (ix["ndvi"] < ndvi_veg) & (ix["ndwi"] < ndwi_water) & (vis > thr)
