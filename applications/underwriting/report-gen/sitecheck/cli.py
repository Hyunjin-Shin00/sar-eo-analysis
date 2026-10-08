"""`run.py` 와 `demo.py` 가 **같은 명령줄**을 쓰게 하는 자리.

두 진입점의 차이는 건물 폴리곤의 출처 하나여야 한다. 그런데 옵션 이름·기본값이 갈리면
「같은 조건으로 돌렸다」를 말할 수 없다 — 예전에 `run.py` 에는 `--no-reuse` 가 있고
`for_demo.py` 에는 `--refresh-yard` 가 있어서, 같은 뜻을 다른 말로 부르고 있었다.

그래서 **깃발은 한 벌**이고 그 뜻도 하나다. 길에 따라 물리지 않는 것이 하나 있는데
(`--gpu` 는 모델 추론에만 쓴다) 그것도 빼지 않고 두되 도움말에 적는다 — 있는 깃발이 안
먹는 것보다 없는 깃발을 찾아 헤매는 편이 더 오래 걸린다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sitecheck import analyze as AN
from sitecheck import console as con
from sitecheck import pipeline
from sitecheck.naming import read_addresses, slug


def parser(desc, *, default_out):
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("addresses", nargs="*", help="주소(여러 개 가능)")
    ap.add_argument("--file", help="주소 목록 파일(한 줄에 하나 · # 뒤는 주석)")
    ap.add_argument("--out", default=None, help=f"출력 상위 폴더(기본 {default_out}/)")
    ap.add_argument("--scene", default=None,
                    help="쓸 정사영상 key 를 지정한다(같은 지역 다른 촬영일을 고를 때). "
                         "기본은 좌표로 고름")
    ap.add_argument("--only", default=",".join(pipeline.JUDGE_ALL),
                    help="판정 항목을 골라서 — sep · yard · illegal")
    ap.add_argument("--no-yard", action="store_true", help="VLM 판독을 건너뛴다(비용 절약)")
    ap.add_argument("--refresh-yard", action="store_true",
                    help="저장된 야적 판독을 버리고 다시 부른다(유료)")
    ap.add_argument("--yard-model", default="gpt-5.6-terra")
    ap.add_argument("--no-reuse", action="store_true",
                    help="저장된 추론·판독을 무시하고 다시 돌린다")
    ap.add_argument("--fresh", action="store_true",
                    help="비교분석에서 **저장된 날짜분 결과를 쓰지 않고 값을 다시 낸다** — "
                         "손보정을 고쳤을 때 쓴다. `--no-reuse` 와 다르다: 추론·야적 판독 "
                         "캐시는 그대로 쓰므로 GPU 를 다시 돌리지도 VLM 을 다시 부르지도 "
                         "않는다(유료 호출 없음)")
    ap.add_argument("--fresh-site", action="store_true",
                    help="저장된 site 를 쓰지 않고 주소를 새로 해석한다")
    ap.add_argument("--gpu", type=int, default=None, help="모델 추론에만 쓴다")
    ap.add_argument("--compare", nargs=2, metavar=("1차", "2차"), default=None,
                    help="두 촬영일 비교분석 — 장면 key 둘(예: --compare daegu daegu2). "
                         "산출물은 위험분석과 **폴더가 다르다**(out/ 대 out_cmp/) — 주소마다 "
                         "보고서 한 부에 날짜분 두 폴더가 딸리므로 섞으면 구분이 안 된다. "
                         "모델 경로에서는 폴리곤이 날짜마다 새로 나와 경계가 흔들리는데, "
                         "변화 기준이 rules 의 측정오차 상수라 그 흔들림은 「변화 없음」으로 "
                         "떨어진다(report/compare.py 머리글)")
    ap.add_argument("--tag", default=None, help="추론 캐시 이름(기본은 길마다 다르다)")
    ap.add_argument("--save-tiles", action="store_true", help="VLM 에 넣은 타일을 남긴다")
    ap.add_argument("--no-images", action="store_true", help="결과 그림 네 장을 만들지 않는다")
    ap.add_argument("--no-report", action="store_true", help="보고서(PDF·HTML)를 만들지 않는다")
    ap.add_argument("--detail", action="store_true",
                    help="내막까지 찍는다 — 정합 이득 · 편이 추정 · 물려받은 레이어 · "
                         "실패 자취. 안 켜도 이 값들은 전부 결과 파일에 남는다"
                         "(site.notes · provenance.steps)")
    ap.add_argument("--quiet", action="store_true", help="아무것도 찍지 않는다")
    return ap


def main(argv=None, *, source, desc, default_out, default_out_cmp=None, table=None,
         stored=None):
    """주소를 모아 [[analyze.py]] `run_many` 에 넘긴다. 세 진입점의 공통 몸통.

    **비교분석은 폴더를 따로 쓴다**(`default_out_cmp`). 산출물의 모양이 다르기 때문이다 —
    위험분석은 주소마다 폴더 하나인데, 비교분석은 주소마다 보고서 한 부에 날짜분 두 폴더
    (`t1/` · `t2/`)가 딸린다. 손보정 길이 이미 그렇게 갈라 두었고(`demo/` 3건 ·
    `demo_cmp/` 2건), 모델 길도 같은 모양으로 둔다. 안 주면 `<출력폴더>_cmp` 다.
    """
    ap = parser(desc, default_out=default_out)
    a = ap.parse_args(argv)
    # **화면 등급은 여기서 한 번만 정한다**([[console.py]]). 깃발을 읽는 자리가 하나이므로,
    # 아래 단계들은 자기가 무엇을 찍을지만 알면 되고 얼마나 찍을지는 몰라도 된다.
    con.setup(con.QUIET if a.quiet else (con.DETAIL if a.detail else con.NORMAL))

    addrs = list(a.addresses)
    if a.file:
        addrs += read_addresses(a.file)
    if not addrs:
        ap.error("주소를 하나 이상 주세요 (또는 --file)")

    only = tuple(x.strip() for x in a.only.split(",") if x.strip())
    bad = [x for x in only if x not in pipeline.JUDGE_ALL]
    if bad:
        ap.error(f"--only 에 모르는 항목: {', '.join(bad)} ({' · '.join(pipeline.JUDGE_ALL)})")

    if a.compare:
        cmp_out = (Path(a.out) if a.out
                   else Path(default_out_cmp or f"{default_out}_cmp"))
        return compare(addrs, cmp_out, source=source,
                       scene1=a.compare[0], scene2=a.compare[1], table=table,
                       yard=not a.no_yard, refresh_yard=a.refresh_yard,
                       reuse=not (a.no_reuse or a.refresh_yard), fresh=a.fresh,
                       gpu=a.gpu, tag=a.tag,
                       report=not a.no_report, verbose=not a.quiet)

    ok, _skipped = AN.run_many(
        addrs, Path(a.out) if a.out else default_out, source=source, table=table,
        only=only, yard=not a.no_yard, yard_model=a.yard_model,
        reuse=not (a.no_reuse or a.refresh_yard), gpu=a.gpu, tag=a.tag,
        save_tiles=a.save_tiles, scene=a.scene,
        stored=(False if a.fresh_site else stored),
        images=not a.no_images, report=not a.no_report, verbose=not a.quiet)
    return 0 if ok else 1


def compare(addrs, out, *, scene1, scene2, source="gt", table=None, yard=True,
            refresh_yard=False, reuse=True, fresh=False, gpu=None, tag=None,
            report=True, verbose=True):
    """두 촬영일 비교분석 — 주소마다 한 부. `(0 · 1)`.

    **한 건이 실패해도 나머지는 낸다** — `run_many` 와 같은 규약이다. 목록으로 도는 것이
    기본이라 중간에서 멈추면 앞것만 새 판, 뒷것은 옛 판이 되어 폴더 안에서 판이 섞인다.

    손보정은 `table` 에서 주소마다 꺼낸다([[hand.py]] `of`) — 단일시점 길과 같은 표를 같은
    방식으로 본다. 표를 안 주면 손보정 없이 돈다.
    """
    from sitecheck import hand as H
    from sitecheck.report import compare as CMP
    out = Path(out)
    say = con if verbose else con.SILENT
    fail = []
    for i, address in enumerate(addrs, 1):
        say.head(f"[{i}/{len(addrs)}] {address}  (비교분석)")
        h = H.of(table, address)
        stem = out / f"위성_비교분석_{slug(address)}"
        stem.parent.mkdir(parents=True, exist_ok=True)
        try:
            made = list(CMP.build(address, str(stem), scene1=scene1, scene2=scene2,
                                  t1_root=out / "t1", t2_root=out / "t2",
                                  skip=h.road_side, hand=h, source=source, yard=yard,
                                  refresh_yard=refresh_yard, reuse=reuse, fresh=fresh,
                                  gpu=gpu, tag=tag,
                                  html_too=report, pdf=report, verbose=verbose))
            for f in made:
                say.detail(f"{f.name}  ({f.stat().st_size / 1024:,.0f} KB)")
            say.step("보고서", True, f"{len(made)}개 파일")
            say.result(None, [], stem.parent)
        except Exception as e:                               # noqa: BLE001
            fail.append((address, f"{type(e).__name__}: {e}"))
            say.step("보고서", False, fail[-1][1][:160])
    say.tail(f"완료 {len(addrs) - len(fail)}/{len(addrs)}"
             + (f" · 실패 {len(fail)}" if fail else ""))
    for address, why in fail:
        say.fail(address, why)
    return 1 if fail else 0


def run(source, desc, default_out, **kw):
    """진입점 한 줄용 — `sys.exit(cli.run("model", __doc__, config.OUT))`.

    비교분석 폴더는 `default_out_cmp=` 로 준다(안 주면 `<출력폴더>_cmp`).
    """
    sys.exit(main(source=source, desc=desc, default_out=default_out, **kw))
