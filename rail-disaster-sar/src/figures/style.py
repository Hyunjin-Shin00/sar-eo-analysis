"""matplotlib 공통 스타일 — 한글·일본어 폰트 등록과 다크 테마 색상."""
import os
os.environ.pop("PYTHONPATH", None)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # 범CJK: 한글·일본어 모두 수록
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]

BG      = "#0d1526"
GRID    = "#1e2a42"
FG      = "#e8eef8"
MUTED   = "#8ea0bd"
ACCENT  = "#ff5c5c"
FREE    = "#4dd0a7"
PAID    = "#ffb454"


def setup():
    fam = None
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                fm.fontManager.addfont(p)
                fam = fm.FontProperties(fname=p).get_name()
                break
            except Exception:
                continue
    if fam is None:
        print("  !! 한글 폰트 미발견 — 그림의 한글이 깨질 수 있다")
    else:
        plt.rcParams["font.family"] = fam
    plt.rcParams.update({
        "axes.unicode_minus": False,
        "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
        "text.color": FG, "axes.labelcolor": FG, "axes.edgecolor": MUTED,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "grid.color": GRID, "figure.dpi": 110, "savefig.dpi": 300,
        "savefig.bbox": "tight",
    })
    return fam


if __name__ == "__main__":
    f = setup()
    print("등록 폰트:", f)
    fig, ax = plt.subplots(figsize=(7, 1.6))
    ax.text(0.02, 0.60, "한글 테스트 — 침수추정역·철도 피재 구간 판정", fontsize=13)
    ax.text(0.02, 0.22, "日本語テスト — 米坂線 越後下関 浸水推定域 令和4年8月3日", fontsize=13)
    ax.axis("off")
    out = os.path.join(os.environ.get("WORK_ROOT", "<WORK_ROOT>"), "outputs", "figures", "_font_test.png")
    fig.savefig(out); print("저장:", out)
