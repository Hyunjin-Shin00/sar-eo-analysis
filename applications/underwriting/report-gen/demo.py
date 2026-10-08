#!/usr/bin/env python
"""주소 → 건물 · 야적 · 이격 · 대장 네 결과. **건물을 GT(사람이 그린 정답)에서 얻는 길.**

    python demo.py "경상북도 구미시 공단동 282"
    python demo.py --file addresses.txt
    python demo.py "..." --only sep               # 한 항목만
    python demo.py "..." --no-yard                # VLM 판독 건너뛰기(비용)
    python demo.py "..." --compare daegu daegu2   # 두 촬영일 비교분석

**손보정을 쓴다**(사용자 결정, 2026-08-26). 주소별 손보정 표는 [[hand_writting.py]] `TABLE`
한 곳에 있고 이 파일은 그것을 그대로 넘긴다 — 그래서 **같은 주소·같은 시나리오면 이 파일의
결과가 `demo/` 의 산출물과 값까지 같다.** 예전에는 손보정 없이 돌아 「GT 를 그대로 썼을 때의
값」을 내는 기준선이었는데, 그 기준선보다 **다섯 부의 산출물을 손 안 대고 재현할 수 있는
것**을 택했다. 기준선이 다시 필요하면 `table=None` 로 부르면 된다(아래 한 줄).

산출물은 **`out_gt/`** 로 간다. `demo/` 가 아닌 이유는 그쪽 PDF 가 [[hand_writting.py]] 가
지키는 **손판(Chrome 인쇄본)**이기 때문이다 — 여기서 쓰면 matplotlib 판이 그 위를 덮는다.
값·레이어·그림·HTML 은 두 폴더가 같고, PDF 만 판이 다르다.

    out/        run.py            모델 · 손보정 `TABLE_MODEL`
    out_gt/     demo.py           GT  · **손보정 있음** · PDF 는 코드가 뽑는다
    demo/       hand_writting.py  GT  · 손보정 있음 · PDF 는 손판   ← 저장소에 담기는 산출물

**`run.py` 와 이 파일의 차이는 건물 폴리곤을 어디서 얻는가 하나다.** 명령줄도 단계도 판정도
저장물도 같다 — 둘 다 [[sitecheck/analyze.py]] 한 길을 지나고 [[sitecheck/cli.py]] 한 벌의
깃발을 쓴다. 그래서 같은 주소의 두 결과를 나란히 놓고 **「모델이 GT 만큼 잡았나」만** 보면
된다.

    run.py    source="model"   `s1_building.predict` → `attribute`   out/<주소>/result.json
    demo.py   source="gt"      `gt.polygons` → `gt.buildings`        demo/<주소>/demo.json

**왜 모델을 통과하지 않는 길이 필요한가.** 판정이 어떤 근거로 나오는지 보여야 할 때 건물
폴리곤이 흔들리면 설명하려는 것이 가려진다. 모델 성능은 따로 재고(seglab 벤치), 여기서는
이격·야적·미등록 판정의 절차와 숫자만 보이게 한다. GT 는 학습·평가에 쓴 그 파일이고
(`assets/gt/<장면>.json`) 장면 전체에 있으므로(대구 2,651 · 구미 6,443 · 남동공단 4,748동)
주소는 **영상 안이면 아무 곳이나** 된다.

**손보정이 어디에 들어갔는지는 값에 남는다.** 적용하는 함수([[sitecheck/hand.py]])가 전부
`site.notes` 와 해당 Feature 의 속성에 「사람이 …했다」를 적으므로, 종이만 본 사람도 무엇이
손으로 들어갔는지 읽을 수 있다. 표에 없는 주소는 손보정이 하나도 안 걸린다.

**다섯 시나리오를 다 낼 수 있다** — 단일시점 셋은 그냥 주소로, 비교분석 둘은 `--compare` 로.

    python demo.py --file addresses.txt
    python demo.py "대구광역시 달서구 호산동 702-5" "대구광역시 달서구 신당동 1187-2" \
           --compare daegu daegu2

값 파일 이름만 갈라 둔다(`demo.json`). 폴더만 보고 그 값이 모델에서 나왔는지 GT 에서
나왔는지 알 수 있어야 하기 때문이다 — 값 자체는 `provenance.model.building` 에도 적히지만
파일 이름이 먼저 눈에 든다. 읽는 쪽([[sitecheck/report/single.py]] `find_result`)은 둘 다 본다.
"""

from sitecheck import cli
from sitecheck import settings as config

if __name__ == "__main__":
    # 손보정 표는 [[hand_writting.py]] 에만 있다 — 여기서는 **읽기만** 한다. 표를 이 파일로
    # 옮기면 정의가 둘이 되어, 한쪽만 고친 날 두 산출물이 조용히 갈린다.
    from hand_writting import TABLE
    cli.run("gt", "주소 → 건물·야적·이격·대장 4결과 (건물은 GT · 손보정 적용)",
            config.HERE / "out_gt", table=TABLE)
