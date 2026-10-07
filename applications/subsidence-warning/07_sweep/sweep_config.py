# -*- coding: utf-8 -*-
"""SBAS coh/tcoh 스윕 + 지반침하 판별 최적화 — 공통 설정(단일 진실원).
사상(Busan_Sasang_Hadan) 제외 7 AOI. 경로는 config.region_result_dir + merged 스택 맵에서 파생."""
import os
os.environ.pop("PYTHONPATH", None)
import sys
CLAB_ROOT = os.environ.get("CLAB_ROOT")
if not CLAB_ROOT:
    CLAB_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SINK = os.path.join(CLAB_ROOT, "analysis", "sinkhole")
if SINK not in sys.path:
    sys.path.insert(0, SINK)

from config import region_result_dir           # noqa: E402
from make_unified_map import AOI_SNWE           # noqa: E402  (bbox = SBAS 생성에 쓴 것과 동일)

CLAB = CLAB_ROOT

# 스윕 대상 7 AOI (사상 제외). region key → merged 스택 디렉토리(run_sbas --merged)
MERGED = {
    "Seoul_Gangdong":       f"{CLAB}/regions/seoul/workspace/stamps_seoul/stack/merged",
    "Seoul_Seodaemun":      f"{CLAB}/regions/seoul/workspace/stamps_seoul/stack/merged",
    "Gyeonggi_Gwangmyeong": f"{CLAB}/regions/seoul/workspace/stamps_seoul/stack/merged",
    "Incheon_Songdo":       f"{CLAB}/regions/seoul/workspace/ASC_incheon/stack/merged",
    "Incheon_Songdo_DSC":   f"{CLAB}/regions/seoul/workspace/DSC_incheon/stack/merged",
    "Busan_Mandeok_Centum": f"{CLAB}/regions/busan/workspace/ASC_mandeok/stack/merged",
    "Yangyang":             f"{CLAB}/regions/yangyang/workspace/ASC/stack/merged",
    # 사상: 기준 지역. 기존(coh0.30/tcoh0.70, AUC 0.98) 대비 개선 조합 탐색용으로 추가.
    "Busan_Sasang_Hadan":   f"{CLAB}/regions/busan/workspace/ASC_sasang/stack/merged",
}
REGIONS = list(MERGED.keys())

# 12조합 그리드 (사용자 확정): coh_min × tcoh_min
COH_GRID  = [0.2, 0.3, 0.4, 0.5]
TCOH_GRID = [0.5, 0.6, 0.7]
GRID = [(c, t) for c in COH_GRID for t in TCOH_GRID]

# 평가 하이퍼파라미터 자유도
BUFFERS = [100.0, 200.0, 300.0, 400.0]   # 사고 버퍼 반경(m) — AOI별 최적 자동선택
CUM_WINDOWS = {"1yr": 1.0, "2yr": 2.0, "full": None}   # 누적침하 창(년)
KIND_SETS = {"SBAS": ("SBAS",)}   # SBAS 단독만(사용자 결정: PS 전면 제거). PS_SBAS 폐기.

RGL, AZL = 9, 3                    # 캐시 window 일치 필수(base 생성값). 절대 변경 금지.
N_NEG = 500                        # 배경(비사고) 목표 표본
PRE_MIN_EPOCHS = 6                 # 사고 이전 최소 관측(indicators asof)
RUN_SBAS = f"{CLAB}/analysis/insar_bin/run_sbas.py"
RUN_SBAS_AUTO = f"{CLAB}/analysis/insar_bin/run_sbas_autoscale.py"
# geom이 full-res(1×1)라 배율 자동감지판을 써야 하는 지역(하강궤도 등). base가 autoscale로 생성됨.
AUTOSCALE_REGIONS = {"Incheon_Songdo_DSC"}


def runner_for(region):
    return RUN_SBAS_AUTO if region in AUTOSCALE_REGIONS else RUN_SBAS
PY = "$CONDA_PREFIX/bin/python3.8"
OUT_ROOT = f"{CLAB}/analysis/sbas_sweep/out"
ACC_CSV = f"{CLAB}/auxiliary/subsidence_list/subsidence_accidents_geocoded_update.csv"


def base_sbas_dir(region):
    """기존(base) SBAS 결과 폴더 = cache.npz 위치."""
    return region_result_dir(region, "sbas")


def sweep_dir(region, coh, tcoh):
    return os.path.join(base_sbas_dir(region), "sweep", f"coh{coh}_tcoh{tcoh}")


# AOI_SNWE에 없는 지역 → 동일 AOI(다른 궤도)의 박스 사용
BBOX_ALIAS = {"Incheon_Songdo_DSC": "Incheon_Songdo"}


def bbox(region):
    key = BBOX_ALIAS.get(region, region)
    S, N, W, E = AOI_SNWE[key]
    return (S, N, W, E)
