# -*- coding: utf-8 -*-
"""AOI 93건의 원인 라벨을 국토안전관리원 Open API 실제 원인값(sagoReason)으로 확정.
usage: cause_api_label.py

배경: 2026-07-30까지 이 프로젝트의 원인 라벨은 '복구방법(trMethod) 원문 수작업 추정'
(out/cause_relabel.csv)이었다. 원인 필드가 상세 API(sagoDetail)에 공란이었기 때문.
실제 원인은 리스트 API(getSubsidenceList01)의 sagoReason에만 있었고, 수집기가 이를
버리고 있었다(2026-07-30 수정). 이제 실제 원인이 확보돼 추정 라벨을 폐기한다.

출력
  out/cause_api_label.csv  — 93건 원장(no, region, api_reason, cause, old_manual_cause)
  out/cause_census93.json  — AOI×원인 전수 카운트(리포트 표의 입력)
"""
import csv
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out")
ACC_CSV = "<DATA_ROOT>/auxiliary/subsidence_list/subsidence_accidents_geocoded_update.csv"
LEGACY = os.path.join(OUT, "cause_relabel.csv")     # 구 수작업 추정 원장(비교·이력용)

# API 원인 신고값(8종) → 리포트 5분류. 표에 그대로 싣는 공개 매핑이다.
REASON_TO_CAUSE = {
    "하수관 손상":        "관로형",
    "상수관 손상":        "관로형",
    "기타매설물 손상":     "관로형",
    "다짐(되메우기) 불량": "되메움형",
    "굴착공사 부실":       "굴착공사형",
    "기타":              "기타",
    "상하수관공사 부실":   "기타",      # 공사부실이나 '굴착'이 아니라 굴착공사형에 넣지 않음
    "기타매설공사 부실":   "기타",      # 동일
}
CAUSES = ["관로형", "되메움형", "굴착공사형", "기타", "미상"]
KR = ["사상", "양양", "송도", "광명", "서대문", "강동", "만덕"]


def cause_of_reason(reason):
    """sagoReason → 5분류. 공란/결측 = 미상(원인 미기재), 미등록 신고값 = 기타.

    pandas로 읽으면 빈칸이 NaN(float)으로 오므로 문자열화해서 처리한다.
    """
    r = "" if reason is None else str(reason).strip()
    if not r or r.lower() == "nan":
        return "미상"
    return REASON_TO_CAUSE.get(r, "기타")


def main():
    acc = {}
    with open(ACC_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            acc[r["sagoNo"].strip()] = r
    legacy = list(csv.DictReader(open(LEGACY, encoding="utf-8-sig")))

    rows, miss = [], []
    for L in legacy:
        no = L["no"].strip()
        a = acc.get(no)
        if a is None:
            miss.append(no)
            continue
        reason = (a.get("sagoReason") or "").strip()
        rows.append({"no": no, "region": L["region"], "api_reason": reason,
                     "cause": cause_of_reason(reason),
                     "old_manual_cause": L["new_cause"]})
    if miss:
        print(f"⚠️ 사고 CSV에 없는 sagoNo {len(miss)}건: {miss}")

    with open(os.path.join(OUT, "cause_api_label.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["no", "region", "api_reason", "cause", "old_manual_cause"])
        w.writeheader()
        w.writerows(rows)

    cen = {k: {c: 0 for c in CAUSES} for k in KR}
    for r in rows:
        cen[r["region"]][r["cause"]] += 1
    for k in KR:
        cen[k]["합"] = sum(cen[k][c] for c in CAUSES)
    json.dump(cen, open(os.path.join(OUT, "cause_census93.json"), "w"),
              ensure_ascii=False, indent=2)

    # 요약 출력
    tot = defaultdict(int)
    chg = 0
    for r in rows:
        tot[r["cause"]] += 1
        if r["cause"] != r["old_manual_cause"]:
            chg += 1
    print(f"원장 {len(rows)}건 → out/cause_api_label.csv, out/cause_census93.json")
    print("신라벨 분포: " + " · ".join(f"{c} {tot[c]}" for c in CAUSES))
    print(f"구 수작업 라벨과 불일치: {chg}건 ({chg/len(rows)*100:.0f}%)")
    for k in KR:
        print(f"  {k:4s} " + " ".join(f"{c}{cen[k][c]}" for c in CAUSES) + f"  합{cen[k]['합']}")


if __name__ == "__main__":
    main()
