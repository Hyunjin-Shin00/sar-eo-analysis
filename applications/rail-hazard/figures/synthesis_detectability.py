"""전 케이스 종합 — SAR 탐지 가능 영역 (사건 후 경과시간 × 대상 공간규모).

측정점은 모두 본 조사에서 실측했거나(○/✕), 공개자료로 확인된 것(◆)이다.
추정치는 넣지 않는다.
"""
import os, sys, pathlib
os.environ.pop("PYTHONPATH", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import style

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
OUT = ROOT/"outputs"/"figures"; OUT.mkdir(parents=True, exist_ok=True)

# (라벨, 사건후 경과 hr, 대상 특성규모 m, 결과, 출처)
#   결과: 'ok' 탐지, 'no' 미탐지, 'pub' 공개자료로 포착 확인
PTS = [
 ("水郡線 大子町 침수\n+2.4h · 0.48 km²",        2.4,   700,  "ok",
  "본 조사 실측 (하천근접 50%)"),
 ("水郡線 당일 오후\n+14h · 배경수준",             14.2,  700,  "no",
  "본 조사 실측 (하천근접 15% = 대조군 18%)"),
 ("③ 나가노 차량센터 침수\n+110h · 7.36 km²",    110.4, 2700, "no",
  "본 조사 실측 (물 화소 0.00%)"),
 ("水郡線 第六久慈川橋梁\n+146h · 137 m",          146.4, 137,  "no",
  "본 조사 실측 (z=+0.45)"),
 ("① 米坂線 연변 土砂移動 4개소\n+5.8h · 5~15 ha · 진폭·코히런스 모두",
                                                  5.8,   320,  "no",
  "본 조사 실측 (진폭 z −0.32~+0.17 / 코히런스 z −0.03)"),
 ("ALOS-2 나가노 3m\n+9h · 破堤部·浸水域",          8.6,  2700, "pub",
  "JAXA Earth-graphy 2019-10-28"),
 ("ALOS-2 2022호우 3m\n+25h · 土砂移動·浸水",      25.0,  320,  "pub",
  "JAXA 災害事例集 事例15 — 같은 4개소를 검출"),
]



def main():
    style.setup()
    fig, ax = plt.subplots(figsize=(14.6, 9.4))

    # 배경 영역
    ax.axhspan(5, 30, color="#ff5c5c", alpha=0.07, zorder=0)
    ax.axvspan(48, 400, color="#ff5c5c", alpha=0.07, zorder=0)
    ax.text(300, 6.5, "Sentinel-1 분해능 한계\n(5×20 m → 판정에 수십 m 필요)",
            color="#ff8a8a", fontsize=10.5, ha="right", va="bottom", zorder=2)
    ax.text(330, 4000, "침수 소멸 이후\n(관측해도 늦다)", color="#ff8a8a",
            fontsize=10.5, ha="center", va="center", zorder=2)

    # 센서 분해능 가로선
    for y, lab, c in [(20, "Sentinel-1 IW  5×20 m (무료)", style.FREE),
                      (3,  "ALOS-2 高分解能  3 m (유상)", style.PAID),
                      (0.5, "ICEYE·Umbra·Capella  0.25~0.5 m (유상)", "#c792ea")]:
        ax.axhline(y, color=c, lw=1.1, ls=":", alpha=0.75, zorder=1)
        ax.text(0.68, y*1.14, lab, color=c, fontsize=9.5, va="bottom", zorder=2)

    # 재방문 세로선
    for x, lab in [(12, "S1 최단 통과\n(운 좋을 때)"), (144, "S1 트랙별\n재방문 12일")]:
        ax.axvline(x, color=style.MUTED, lw=1.0, ls="--", alpha=0.5, zorder=1)
        ax.text(x*1.06, 9000, lab, color=style.MUTED, fontsize=9, va="top", zorder=2)

    style_map = {"ok": dict(marker="o", mfc=style.FREE, mec="#0d1526", ms=19, label="탐지 성공 (본 조사)"),
                 "no": dict(marker="x", mfc="#ff5c5c", mec="#ff5c5c", ms=19, label="탐지 실패 (본 조사)"),
                 "pub": dict(marker="D", mfc=style.PAID, mec="#0d1526", ms=15, label="포착 확인 (공개자료)")}
    for lab, hr, m, res, src in PTS:
        st = style_map[res]
        ax.plot(hr, m, ls="none", marker=st["marker"], mfc=st["mfc"], mec=st["mec"],
                mew=1.6, ms=st["ms"], zorder=6)
    # 라벨 배치
    off = {"水郡線 大子町 침수\n+2.4h · 0.48 km²": (-190, 40),
           "水郡線 당일 오후\n+14h · 배경수준": (30, -66),
           "③ 나가노 차량센터 침수\n+110h · 7.36 km²": (-90, 58),
           "水郡線 第六久慈川橋梁\n+146h · 137 m": (-215, -52),
           "① 米坂線 연변 土砂移動 4개소\n+5.8h · 5~15 ha · 진폭·코히런스 모두": (-120, -92),
           "ALOS-2 나가노 3m\n+9h · 破堤部·浸水域": (26, 52),
           "ALOS-2 2022호우 3m\n+25h · 土砂移動·浸水": (30, 40)}
    for lab, hr, m, res, src in PTS:
        dx, dy = off[lab]
        col = {"ok": style.FREE, "no": "#ff8a8a", "pub": style.PAID}[res]
        ax.annotate(lab, xy=(hr, m), xytext=(dx, dy), textcoords="offset points",
                    fontsize=10.5, color=col, zorder=7,
                    bbox=dict(boxstyle="round,pad=0.35", fc="#101a2e", ec=col, lw=1.0, alpha=0.95),
                    arrowprops=dict(arrowstyle="-", color=col, lw=1.1, alpha=0.8,
                                    shrinkA=2, shrinkB=12))

    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(0.6, 400); ax.set_ylim(0.3, 12000)
    ax.set_xlabel("사건 발생 후 경과 시간 (시간, 로그)", fontsize=12.5, color=style.FG)
    ax.set_ylabel("탐지 대상의 특성 공간규모 (m, 로그)", fontsize=12.5, color=style.FG)
    ax.set_xticks([1, 3, 6, 12, 24, 48, 96, 168, 336])
    ax.set_xticklabels(["1h", "3h", "6h", "12h", "1일", "2일", "4일", "7일", "14일"])
    ax.set_yticks([0.5, 1, 3, 10, 20, 100, 500, 2000, 10000])
    ax.set_yticklabels(["0.5 m", "1 m", "3 m", "10 m", "20 m", "100 m", "500 m", "2 km", "10 km"])
    ax.grid(True, which="major", color=style.GRID, lw=0.7, alpha=0.6, zorder=0)
    ax.set_axisbelow(True)
    for s in ax.spines.values(): s.set_color(style.MUTED)
    ax.tick_params(labelsize=10.5)

    handles = [Line2D([], [], ls="none", marker=v["marker"], mfc=v["mfc"], mec=v["mec"],
                      mew=2.0, ms=12, label=v["label"]) for v in style_map.values()]
    ax.legend(handles=handles, loc="lower right", frameon=True, fontsize=11,
              labelcolor=style.FG, ncol=1, facecolor="#101a2e", edgecolor=style.MUTED,
              framealpha=0.95, borderpad=0.8)

    fig.suptitle("철도 피해 SAR 탐지 가능 영역 — 실측 종합",
                 fontsize=17.5, color=style.FG, y=0.975)
    fig.text(0.5, 0.932,
             "가로축 = 사건 후 첫 유효 관측까지의 시간 · 세로축 = 탐지 대상의 공간규모 · "
             "타이밍·규모가 맞아도 후방산란 대비가 없으면 안 된다 (① 米坂線)",
             ha="center", fontsize=11, color=style.MUTED)
    fig.text(0.5, 0.022,
             "○✕ = 본 조사 Sentinel-1 실측 (2026-09-15) · ◆ = JAXA 공개자료로 포착이 확인된 ALOS-2 긴급관측. "
             "0.25~0.5 m급 상업 SAR 행은 조회 불가(API Key 미보유·2019년 미운용)로 실측점이 없다.",
             ha="center", fontsize=9.5, color="#6b7a92")
    fig.tight_layout(rect=[0, 0.035, 1, 0.92])
    p = OUT/"synthesis_detectability.png"
    fig.savefig(p); fig.savefig(OUT/"synthesis_detectability.svg")
    print("저장:", p)


if __name__ == "__main__":
    main()
