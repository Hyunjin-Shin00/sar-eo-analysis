import os
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch
f="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"; font_manager.fontManager.addfont(f)
plt.rcParams["font.family"]=font_manager.FontProperties(fname=f).get_name()
BLUE="#2a78d6"; GRAY="#8a8880"; INK="#0b0b0b"; LB="#e8f0fb"; LG="#f1f0ec"
fig,ax=plt.subplots(figsize=(12,6.2),dpi=150); ax.set_xlim(0,12); ax.set_ylim(0,6.2); ax.axis("off")
def box(x,y,w,h,t,fc,ec,fs=10,bold=False):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.02,rounding_size=0.08",fc=fc,ec=ec,lw=1.2))
    ax.text(x+w/2,y+h/2,t,ha="center",va="center",fontsize=fs,color=INK,fontweight="bold" if bold else "normal",linespacing=1.35)
def arr(x1,y1,x2,y2): ax.annotate("",(x2,y2),(x1,y1),arrowprops=dict(arrowstyle="-|>",color=GRAY,lw=1.2))
ax.text(0.1,5.95,"입력 (공공데이터 · 위성)",fontsize=11,fontweight="bold")
ins=[("주소 → 지오코딩 · 연속지적도(PNU)",5.2),("위성 정사영상 0.5 m",4.45),("건축물대장 표제부 API",3.7),
     ("GIS건물통합정보 (A0~A39 익명 필드)",2.95),("공장등록현황 CSV + KSIC 11차 연계표",2.2),("소방관서 좌표 · 기상 ASOS 30년",1.45)]
for t,y in ins: box(0.1,y,3.3,0.58,t,LG,GRAY,9.5)
ax.text(4.3,5.95,"분석",fontsize=11,fontweight="bold")
box(4.3,4.3,3.4,1.45,"건물 탐지 · 이격거리 · 적재물 · 대장 면적 대조\n(DINOv3+Mask2Former · 규칙 판정)\n— 동료 개발자 담당",LG,GRAY,9.5)
box(4.3,2.55,3.4,1.45,"필지 → 지번 → 업종명 → KSIC\n대상 · 인접 건물 업종 연결\n— 본인 담당",LB,BLUE,9.5,True)
box(4.3,0.8,3.4,1.45,"특수건물 공백 산출\n(공장 연면적 3,000㎡ 기준)\n— 본인 담당",LB,BLUE,9.5,True)
for _,y in ins[:4]: arr(3.42,y+0.29,4.28,5.0)
arr(3.42,2.2+0.29,4.28,3.27); arr(3.42,2.95+0.29,4.28,1.55); arr(3.42,1.45+0.29,4.28,4.45)
ax.text(8.5,5.95,"산출",fontsize=11,fontweight="bold")
box(8.5,2.2,3.35,3.4,"물건별 위성 분석 보고서\n\n① 건물 이격거리\n② 업종 · 인접 업종\n③ 야외 적재물\n④ 미등록 · 증축\n⑤ 소방 접근성\n⑥ 자연재해(기후)\n+ 2시기 변화 비교",LG,GRAY,10)
box(8.5,0.8,3.35,1.1,"SME 공장 인수심사 필요성 근거\n필지 1,237곳 중 966곳(78.1%)",LB,BLUE,9.5,True)
arr(7.72,5.0,8.48,4.4); arr(7.72,3.27,8.48,3.4); arr(7.72,1.55,8.48,1.35)
fig.savefig(os.environ.get("OUT_DIR", ".") + "/workflow.png",bbox_inches="tight",facecolor="white")
