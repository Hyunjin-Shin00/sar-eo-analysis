import os
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
f="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"; font_manager.fontManager.addfont(f)
plt.rcParams["font.family"]=font_manager.FontProperties(fname=f).get_name()
BLUE="#2a78d6"; RED="#e34948"; GRAY="#b4b2aa"; MUTED="#52514e"
rows=[("공장등록현황 · 업종명 채움률",100.0,"3,637 / 3,637",BLUE),
      ("업종명 → KSIC 11차 매칭률",99.4,"3,616 / 3,637",BLUE),
      ("공장등록현황 · 생산품 채움률",99.3,"3,612 / 3,637",BLUE),
      ("공장등록현황 · 주원자재 채움률",55.8,"2,028 / 3,637",GRAY),
      ("인화성 용제 키워드 적중 (위험물 프록시)",0.1,"수 건 · 키워드에 따라 2~17건",RED),
      ("상권정보 247개 업종분류 중 제조업",0.0,"0 / 247",RED),
      ("주소 단위 위험물 사업장 공공데이터",0.0,"후보 6종 모두 불가",RED)][::-1]
fig,ax=plt.subplots(figsize=(10,4.6),dpi=160)
for i,(l,v,t,c) in enumerate(rows):
    ax.barh(i,v,color=c,height=0.6)
    ax.text(max(v,0)+1.5,i,f"{v:.1f}%  ({t})",va="center",fontsize=9.5,color=MUTED)
ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows])
ax.set_xlim(0,130); ax.set_xticks([0,25,50,75,100]); ax.set_xlabel("커버리지 (%) · 공장등록현황 항목은 성서산단 3,637건 기준")
ax.set_title("업종 · 위험물 정보원 검증 — 쓸 수 있는 것과 막힌 길",loc="left",fontsize=13)
for s in ("top","right"): ax.spines[s].set_visible(False)
fig.savefig(os.environ.get("OUT_DIR", ".") + "/source_coverage.png",bbox_inches="tight",facecolor="white")
