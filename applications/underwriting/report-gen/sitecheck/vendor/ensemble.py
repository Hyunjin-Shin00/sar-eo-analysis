"""여러 폴리곤 모델의 예측을 **합의 기반 재점수**로 합친다.

`seglab/scripts/ensemble_poly.py` 의 `pct_norm`·`fuse` 를 그대로 옮겼다(CLI 는 뺐다).
사본을 두는 이유는 vendor/ 의 나머지와 같다 — 이 폴더만 떼어가도 돌아야 한다. 순수 함수라
모델 코드처럼 갈라질 여지가 없다.

**왜 단순 합치기가 아니라 재점수인가.** 두 모델의 score 는 서로 보정되어 있지 않다
(SAMPolyBuild 는 0.39 이하를 내지 않고 GCP 는 0.1 까지 낸다). 그냥 이어붙여 NMS 하면
점수 스케일이 큰 쪽이 이기고, 앙상블의 핵심 정보 — **두 모델이 같은 건물을 봤다** — 가
버려진다. 모델별로 score 를 백분위로 정규화한 뒤 겹치는 예측을 한 덩어리로 묶고
`덩어리 점수 = (구성원 정규화점수 합) / 모델수` 로 매긴다. 그러면

  · 두 모델이 다 잡은 건물 → 점수 유지 (0.8, 0.7 → 0.75)
  · 한 모델만 잡은 건물   → 점수 절반 (0.9, 없음 → 0.45)

검출 집합 자체는 합집합이라 recall 은 잃지 않고, 순위가 좋아지므로 같은 recall 에서
precision 이 오른다.
"""
from __future__ import annotations

import numpy as np


def pct_norm(scores):
    """score → 백분위 [0,1]. 모델 간 스케일 차이를 없앤다(순위만 남긴다)."""
    s = np.asarray(scores, float)
    if len(s) == 0:
        return s
    order = np.argsort(np.argsort(s))            # 동점은 안정적으로 처리
    return (order + 1) / len(s)


def fuse(per_tag, iou_thr=0.5, mode="consensus", geom_from=None):
    """per_tag = {tag: (rings, scores)} → (rings, scores).

    mode='consensus' — 덩어리 점수 = 구성원 정규화점수 합 / 모델수.
        서로 **같은 것을 보려고 하는** 모델들을 합칠 때(다른 아키텍처, 같은 입력).
    mode='union' — 덩어리 점수 = 구성원 정규화점수의 최대값(합의 벌점 없음).
        **서로 다른 것을 보는** 소스를 합칠 때(다중 스케일).

    geom_from — 덩어리 안에 이 tag 의 예측이 있으면 **그 폴리곤을 기하로 채택**한다.
        점수(무엇이 건물인가)와 기하(어디까지가 건물인가)는 서로 다른 능력이다. 실측상
        GCP 는 검출이, SAMPolyBuild 는 경계가 낫다(PoLiS 0.91 vs 0.79 m).
    """
    from shapely.geometry import Polygon
    from shapely.strtree import STRtree

    items = []                                    # (poly, norm_score, tag, ring)
    for tag, (rings, scores) in per_tag.items():
        ns = pct_norm(scores)
        for r, s in zip(rings, ns):
            p = Polygon(r)
            if not p.is_valid:
                p = p.buffer(0)
            if p.is_empty or p.geom_type != "Polygon":
                continue
            items.append((p, float(s), tag, r))
    if not items:
        return [], []
    items.sort(key=lambda t: -t[1])
    polys = [t[0] for t in items]
    tree = STRtree(polys)
    assigned = -np.ones(len(items), int)          # 각 예측이 속한 덩어리 id
    clusters = []
    for i, (p, s, tag, _r) in enumerate(items):
        if assigned[i] >= 0:
            continue
        cid = len(clusters)
        assigned[i] = cid
        cl = {"best": i, "scores": {tag: s}}
        if geom_from and tag == geom_from:
            cl["geom"] = i
        for j in tree.query(p):
            j = int(j)
            if j == i or assigned[j] >= 0:
                continue
            q = polys[j]
            inter = p.intersection(q).area
            if inter <= 0:
                continue
            if inter / (p.area + q.area - inter) >= iou_thr:
                assigned[j] = cid
                tj, sj = items[j][2], items[j][1]
                cl["scores"][tj] = max(cl["scores"].get(tj, 0.0), sj)
                if geom_from and tj == geom_from and "geom" not in cl:
                    cl["geom"] = j
        clusters.append(cl)

    n_models = len(per_tag)
    out_rings, out_scores = [], []
    for cl in clusters:
        pick = cl.get("geom", cl["best"])
        out_rings.append(items[pick][3])
        v = list(cl["scores"].values())
        out_scores.append(max(v) if mode == "union" else sum(v) / n_models)
    o = np.argsort(-np.asarray(out_scores))
    return [out_rings[i] for i in o], [float(out_scores[i]) for i in o]
