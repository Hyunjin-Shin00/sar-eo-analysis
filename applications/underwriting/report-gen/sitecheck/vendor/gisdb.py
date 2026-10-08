"""GIS건물통합정보 조회 — **PNU 로 고른다.**

이 자산은 건축물대장을 도형에 붙여 만든 것이라 한 행이 대장의 한 동에 대응하고,
**어느 지번(PNU)의 건물인지 속성에 들어 있다.** 그런데 sitecheck 은 오랫동안 그것을
안 쓰고 "필지 폴리곤과 겹치는가"로 골랐다. 공단처럼 필지가 작고 빽빽한 곳에서는 옆 지번
건물이 죄다 딸려 와 GIS 합계가 대장의 몇 배가 된다(실측 대구 호산동 700-9: 대장 634㎡ 인데
겹침 기준 5,158㎡ · 호림동 5-2: 1,316㎡ 인데 4,518㎡). 그 값으로 등록 여부를 가렸으니
동별 대조가 틀릴 수밖에 없었다.

PNU 로 고르면 대장과 맞아떨어진다 — 시험한 11필지 중 8필지에서 GIS 건축면적 합이 대장
건축면적 합과 **정확히 같았다**(같은 대장에서 나온 값이므로 당연한 결과다).

컬럼 이름
---------
원본 SHP 의 필드명이 GeoPackage 로 옮겨지면서 `A0`~`A39` 로 뭉개졌다. 값을 보고 되짚은
대응이 아래 `COLS` 다. 자산을 다시 만들면 순서가 바뀔 수 있으므로 `check_schema()` 가
PNU 모양(19자리 숫자)을 확인하고, 아니면 조용히 틀리는 대신 예외를 낸다.
"""
from __future__ import annotations

import re

from sitecheck import settings as config

LAYER = "buildings"
COLS = {
    "pnu": "A1",          # 19자리 PNU — 이 건물이 선 지번
    "sido_dong": "A3",    # 시도·읍면동 이름
    "jibun": "A6",        # 지번 표기(322-1 등)
    "ledger_kind": "A9",  # 일반건축물 / 집합건축물
    "dong": "A19",        # 동명칭(가동 · 1동 · 주건축물제1동)
    "main_sub": "A21",    # 주건축물 / 부속건축물
    "arch_m2": "A23",     # 건축면적 — 대장의 그 값이다
    "total_m2": "A24",    # 연면적
    "struct": "A28",      # 구조
}
_PNU = re.compile(r"^\d{19}$")
_checked = False


def check_schema(gdf):
    """PNU 열이 정말 PNU 인지 확인한다 — 아니면 조용히 틀리는 대신 멈춘다."""
    global _checked
    if _checked or gdf is None or gdf.empty:
        return
    col = COLS["pnu"]
    if col not in gdf.columns:
        raise RuntimeError(f"GIS건물통합정보에 {col} 열이 없다 — vendor/gisdb.COLS 를 다시 맞추세요")
    vals = [str(v) for v in gdf[col].head(20) if v is not None]
    if not vals or sum(bool(_PNU.match(v)) for v in vals) < len(vals) * 0.8:
        raise RuntimeError(
            f"{col} 열이 PNU 모양이 아니다(예: {vals[:3]}) — 자산을 다시 만들었다면 "
            f"vendor/gisdb.COLS 의 열 대응을 고치세요")
    _checked = True


def _rows(gdf):
    out = []
    for r in gdf.itertuples():
        if r.geometry is None:
            continue
        rec = {"geometry": r.geometry}
        for k, c in COLS.items():
            v = getattr(r, c, None)
            rec[k] = None if (v is None or str(v) == "nan") else v
        out.append(rec)
    return out


def near(bounds):
    """bbox 안의 모든 건물 행(속성 포함). 정합 기준선처럼 지번을 안 가릴 때 쓴다."""
    import geopandas as gpd
    if not config.GIS_BUILDINGS.exists():
        return []
    g = gpd.read_file(config.GIS_BUILDINGS, layer=LAYER, bbox=tuple(bounds))
    if g.empty:
        return []
    check_schema(g)
    return _rows(g)


def by_pnu(pnu, bounds):
    """**이 지번의** 건물만. bounds 는 조회 범위(공간 인덱스를 쓰기 위한 것).

    bounds 를 요구하는 이유는 전국 569만 행을 훑지 않기 위해서다. PNU 는 전국 유일하므로
    범위만 넉넉하면 결과는 같다.
    """
    return [r for r in near(bounds) if str(r.get("pnu") or "") == str(pnu)]
