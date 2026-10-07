#!/usr/bin/env python3
"""성서산단 등록 공장의 KSIC 중분류 구성 막대그림 (ksic_link.py 의 매칭 결과 사용).
사용: python fig_ksic_mix.py <factory.csv> <ksic.csv> <out.png>
"""
import os
import sys
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from ksic_link import load, upjong_to_ksic

fac, n2k, se2k = load(sys.argv[1], sys.argv[2])
sub = fac[fac["단지명"].str.contains("성서", na=False)]
res = [upjong_to_ksic(u, n2k, se2k)[1] for u in sub["업종명"]]
ok = [r for r in res if r]
c = Counter(r.split(";")[0] for r in ok).most_common()
top, rest = c[:11], sum(v for _, v in c[11:])
labels = [k for k, _ in top][::-1] + []
vals = [v for _, v in top][::-1]
labels = ["기타 (나머지 중분류)"] + labels
vals = [rest] + vals

cjk = os.environ.get("CJK_FONT", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
if os.path.exists(cjk):
    font_manager.fontManager.addfont(cjk)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=cjk).get_name()
BLUE, GRAY, MUTED = "#2a78d6", "#b4b2aa", "#52514e"
fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
cols = [GRAY if (l.startswith("L") or l.startswith("기타 (")) else BLUE for l in labels]
ax.barh(labels, vals, color=cols, height=0.62)
for i, v in enumerate(vals):
    ax.text(v + 8, i, f"{v:,}", va="center", fontsize=9.5, color=MUTED)
ax.set_title(f"성서산단 등록 공장 {len(sub):,}건 → KSIC 중분류 매칭 {len(ok):,}건 ({len(ok)/len(sub):.1%})",
             loc="left", fontsize=13)
ax.set_xlabel("공장 수 (공장등록현황 2025-07 기준)")
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.text(1, -0.16, "회색 = 제조업 아님(L68 부동산 임대) 또는 나머지 합계", transform=ax.transAxes,
        ha="right", fontsize=9, color=MUTED)
fig.savefig(sys.argv[3], bbox_inches="tight", facecolor="white")
