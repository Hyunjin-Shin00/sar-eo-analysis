# -*- coding: utf-8 -*-
"""
싱크홀 발생점 좌표 (사용자 제공) — STEP 3 (A)제약 검증용.
각 항목: region -> dict(lon, lat, buffer_m, event_date, quad, type)
  · lon, lat : 발생점 WGS84 경위도 (사용자 확정)
  · buffer_m : 발생점 버퍼 반경(m) — 인근 PS/SBAS 판정 대상 범위
  · event_date : 실제 사고일 (리드타임 기준)
  · type : positive(강동①·광명②·양양⑦·연희동⑧·사상⑨) / negative(송도③·만덕④)
           — ③분면 예외 폐지(2026-07-09): 발생 케이스는 분면 무관 전건 양성.

⚠️ lon/lat 이 None 인 항목은 좌표 미제공 → STEP3에서 제외.
   사용자가 좌표를 채우면 그대로 실행.
"""

# 좌표 출처: <DATA_ROOT>/auxiliary/AOI.xlsx (사용자 제공, 형식='위도, 경도')
# buffer_m: 발생점 버퍼 반경(m). 기본 200m(조정 가능).
EVENTS = {
    # ── 양성(붕괴/함몰 발생) — (A)제약 대상: 무조건 주의/위험 ──
    "Seoul_Gangdong":       {"lon": 127.1558, "lat": 37.5459, "buffer_m": 200,
                             "event_date": "2025-03-24", "quad": "①", "type": "positive",
                             "desc": "서울 강동구 명일동 대명초사거리"},
    "Gyeonggi_Gwangmyeong": {"lon": 126.8808, "lat": 37.4123, "buffer_m": 200,
                             "event_date": "2025-04-11", "quad": "②", "type": "positive",
                             "desc": "경기 광명 일직동 신안산선 5-2"},
    "Yangyang":             {"lon": 128.6320, "lat": 38.1175, "buffer_m": 200,
                             "event_date": "2022-08-03", "quad": "⑦", "type": "positive",
                             "desc": "강원 양양 낙산해변 편의점"},
    # 천층/노후관 사고 — ③분면 '예외' 폐지(2026-07-09) → 양성 통합(무조건 주의/위험 대상)
    "Seoul_Seodaemun":      {"lon": 126.9240, "lat": 37.5665, "buffer_m": 200,
                             "event_date": "2024-08-29", "quad": "⑧", "type": "positive",
                             "desc": "서울 서대문구 연희동"},
    "Busan_Sasang_Hadan":   {"lon": 128.9815, "lat": 35.1494, "buffer_m": 200,
                             "event_date": "2024-09-01", "quad": "⑨", "type": "positive",
                             "desc": "부산 사상~하단선(학장동 '25-04-13 병행)"},
    # ── 음성(붕괴 없음) — FP 기준선 (지역 전체로 평가, 발생점 없음) ──
    "Incheon_Songdo":       {"lon": None, "lat": None, "buffer_m": 200,
                             "event_date": None, "quad": "③", "type": "negative",
                             "desc": "인천 송도 매립지 점진변위(안정화)"},
    # 만덕~센텀: 대심도터널 심부 사고(지표 함몰 아님)·발생점 좌표 미기재 → 음성 재분류(2026-07-09)
    "Busan_Mandeok_Centum": {"lon": None, "lat": None, "buffer_m": 200,
                             "event_date": "2023-02-25", "quad": "④", "type": "negative",
                             "desc": "부산 만덕~센텀 대심도(음성 재분류)"},
}

# 학장동 2차 발생점(⑨ 보조) — 필요시
EVENTS_EXTRA = {
    # "Busan_Sasang_Hadan_2": {"lon": None, "lat": None, "buffer_m": 200,
    #                          "event_date": "2025-04-13", "quad": "⑨", "type": "positive_shallow"},
}
