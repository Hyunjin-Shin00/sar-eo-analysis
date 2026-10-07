"""S1D 절대궤도→상대궤도 offset 을 관측값으로 역산·검증한다.

관계식(ESA 표준형): relative = (absolute - offset) % 175 + 1
offset 후보 0..174 를 전수 대입해 모든 관측쌍을 만족하는 값을 찾는다.
관측쌍은 CDSE 메타데이터(absolute orbit, relative orbit)에서 읽은 실측값이다.
"""
# (absolute orbit, relative orbit) — CDSE 메타데이터 실측값(2026). 원 메모는 "7건"이나 기록된 쌍은 6개
PAIRS = [(3976, 85), (4326, 85), (4085, 19), (4260, 19), (4012, 121), (4187, 121)]
# 독립 검증: 다른 지역(일본 지바, 하강 상대궤도 46)의 S1D GRD 파일명 속 절대궤도
HOLDOUT = [(3762, 46), (3937, 46), (4112, 46)]

sol = [k for k in range(175) if all((a - k) % 175 + 1 == r for a, r in PAIRS)]
print("offset 해:", sol)
for k in sol:
    ok = all((a - k) % 175 + 1 == r for a, r in HOLDOUT)
    print(f"offset {k}: holdout {HOLDOUT} -> {'일치' if ok else '불일치'}")
