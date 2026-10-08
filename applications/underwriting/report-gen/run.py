#!/usr/bin/env python
"""주소 → 건물 · 야적 · 이격 · 대장 네 결과. **건물을 모델 추론으로 얻는 길.**

    python run.py "경상북도 구미시 공단동 282"
    python run.py "주소1" "주소2" "주소3"          # 하나씩 순서대로, 각자 폴더에 저장
    python run.py --file addresses.txt            # 한 줄에 하나
    python run.py "..." --no-yard                 # VLM 판독 건너뛰기(비용 절약)
    python run.py --file cmp_addresses.txt \
        --compare daegu daegu2                    # 두 촬영일 비교분석 → out_cmp/

진입점은 셋이고, **서로 무엇이 다른지가 이 세 줄이 전부**다.

    run.py            모델 추론으로 건물을 얻는다        손보정 `TABLE_MODEL`  out/
    demo.py           GT(사람이 그린 정답)에서 얻는다    손보정 있음      out_gt/
    hand_writting.py  GT + 손보정 + **손판 PDF 맞추기**   데모 산출물 5건

명령줄 · 단계 · 판정 · 저장물은 **셋이 완전히 같다** — [[sitecheck/analyze.py]] 한 길을
지나고 [[sitecheck/cli.py]] 한 벌의 깃발을 쓴다. 예전에는 `run.py` 와 `tools/for_demo.py` 가
각자 그 순서를 적어 두어 여덟 군데가 갈려 있었고, 그중 넷은 **이 파일도 모르게 손보정을 쓰던
것**이었다(`ROAD_SIDE`·`NEIGHBOR_DROP`·`NEIGHBOR_SHIFT`·`LEDGER_DROP` 이 `settings.py` 에
있었다). 지금은 손보정이 [[hand_writting.py]] 한 곳에 있고 이 파일은 `TABLE_MODEL` 을 **읽기만**
한다 — 무엇이 손을 탔는지 표를 열면 바로 보인다. **표에 없는 주소는 하나도 안 걸리므로**
그 주소에서 나오는 수치는 전부 모델과 규칙이 낸 것이다.

**정사영상 안의 주소만 처리한다.** 그 밖이면 영상이 없어 건물 폴리곤을 낼 수 없고, 건물이
없으면 나머지 셋도 성립하지 않는다. 빈 결과를 만들면 '건물 0동'과 구분되지 않으므로 아예
폴더를 만들지 않고 그렇게 말한다.

단계는 순서가 있고, 앞이 실패해도 **뒤를 건너뛰되 그 사실을 결과에 적는다.**

    0 주소 해석   주소 → 좌표 · 필지(PNU) · 건축물대장 · 영상 선택
    1 건물        정사영상 → 지붕 폴리곤 → **정합** → 지번 귀속   (모델)
    2 야적        필지 − 건물 → 적재 구역           A4 · A5  (VLM)
    3 이격        건물마다 둘레 25 m 안의 상대 전부까지 최단거리   A1
    4 대장        건물별 건축면적 대조              A3

**산출물은 두 종류이고 폴더가 다르다** — 손보정 길이 갈라 둔 것과 같은 모양이다
(`demo/` 3건 · `demo_cmp/` 2건 → [[hand_writting.py]]).

    out/<주소>/                      위험분석 — 한 촬영일 (아래)
    out_cmp/위성_비교분석_<주소>.pdf   비교분석 — 두 촬영일 (`--compare daegu daegu2`)
    out_cmp/t1/<주소>/ · t2/<주소>/    그 두 날짜분 값 — 보고서의 재료다

한 폴더에 섞지 않는 이유는 모양이 다르기 때문이다: 위험분석은 주소마다 폴더 하나인데
비교분석은 주소마다 **보고서 한 부 + 날짜분 폴더 둘**이다. 섞으면 폴더만 보고 무엇이
무엇인지 알 수 없다.

저장물(주소마다 한 폴더)

    out/<주소슬러그>/
    ├ result.json        넷을 합친 것 — API·웹이 읽는 정본
    ├ buildings.geojson  건물 폴리곤
    ├ ledger.geojson     대장 대조        A3
    ├ separation.geojson 이격 측정선       A1
    ├ yard.geojson       야적 구역        A4·A5
    ├ summary.md         사람이 읽는 요약
    ├ 0_위성영상.png      얹지 않은 바탕 — 아래 셋과 같은 창
    ├ 1_이격거리.png      항목별 결과 그림 — 규칙은 [[sitecheck/draw.py]] (--no-images)
    ├ 보고서.pdf/.html    보고서 한 부 — [[sitecheck/report/single.py]] (--no-report)
    ├ 2_야적물.png
    ├ 3_미등록증축.png
    └ tiles/             VLM 에 보낸 JPEG 바이트 그대로(--save-tiles)
"""
from sitecheck import cli
from sitecheck import settings as config

if __name__ == "__main__":
    # **손보정 표는 [[hand_writting.py]] 에만 있다** — 여기서는 읽기만 한다. 모델 경로용 표가
    # 따로 있는 이유는 그 파일에 적혀 있다(`N####` 는 창 안 기하 순서로 매기는 번호라 옆 지번
    # 건물의 집합이 다르면 같은 번호가 다른 건물을 가리킨다).
    from hand_writting import TABLE_MODEL
    cli.run("model", "주소 → 건물·야적·이격·대장 4결과 (건물은 모델 추론 · 손보정 적용)",
            config.OUT, default_out_cmp=config.OUT_CMP, table=TABLE_MODEL)
