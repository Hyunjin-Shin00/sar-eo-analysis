# -*- coding: utf-8 -*-
"""
지반침하·함몰 워닝 PoC — 공통 설정(CONFIG)
====================================================================
국내 대형 손해보험사 PoC 과제② / 6·22 회의 확정 2단계 판정 체계 구현.

■ 방법론 개요
  STEP1  시추공 시추자료 → 지층별 연약 판정 → 시추공 3등급(연약/주의/양호) → 보정계수 α
  STEP2  PS-InSAR/SBAS 변위 3지표(속도·누적·추세)에 α를 융합 → 정상/주의/위험 3단계
         · 결합구조: [1단 SBAS 광역 스크리닝(hotspot)] → [2단 PS 정밀 확인]
         · PS 공백(반경 R 내 PS<K)이면 SBAS 단독 경보 허용
  STEP3  싱크홀 발생지 vs 미발생지 지표·등급 분포 차이 + (A)제약 검증

■ 좌표계 (STEP0 확인)
  - 지반 CSV(X좌표/Y좌표): EPSG:5186 (중부원점 127E, false N 600k) — 전국 균일 확인
  - PS/SBAS shp: WGS84 (EPSG:4326) 경위도
  - 반경/거리 계산: UTM 52N (EPSG:32652, meters)로 통일 변환

■ ⚠️ 잠정값(PROVISIONAL) 고지
  아래 임계치·α계수·R·K·버퍼는 모두 "백테스팅 확정 전 잠정값"이다.
  - α계수(0.6/0.8/1.0)와 base 임계치의 외부근거(EGMS 등)는 변경 금지.
  - 임계치 자동조정은 (A)제약(발생케이스 전건 상위등급) 충족 위한 '하향'만 허용,
    상향 금지, 물리적 floor(속도 3mm/yr, 누적 10mm) 미만으로는 내리지 않음.
"""

CONFIG = {
    # ---------------- 좌표계 ----------------
    "crs_ground": 5186,     # 지반 CSV X/Y
    "crs_wgs":    4326,     # PS/SBAS 경위도
    "crs_metric": 32652,    # 거리/반경 계산용 UTM 52N (m)
    "korea_bounds": {"lon": (124.0, 132.0), "lat": (33.0, 39.0)},  # garbage 좌표 제거

    # ---------------- STEP1: 지반등급 ----------------
    # SPT N값 산정: 관입깊이 30cm 기준 정규화. 관입불능(pen<30, 고타격)=경질→N↑.
    "spt": {
        "pen_full_cm": 30.0,     # 표준 관입 30cm
        "pen_min_cm": 1.0,       # pen<=이 값 무효
        "blow_min": 0, "blow_max": 500,  # 타격회수 유효범위(그 밖=garbage)
        "N_cap": 100.0,          # 정규화 N 상한(과대 방지)
    },
    # 연약층 판정 규칙 [한국도로공사 도로설계요령(2009) 표1.6-1]
    #   점성토·이탄질: N<=4 AND 대표심도<10m
    #   사질토:        N<=6 AND 대표심도>=10m
    "soft": {
        # 토질분류(USCS 접두어 대문자). 사용자 확정('26-07-07): 풍화토(RS)도 제외.
        "cohesive": {"CL", "CH", "ML", "MH", "OL", "OH", "PT"},   # 점성토·이탄
        "sandy":    {"SM", "SP", "SW", "SC", "GM", "GP", "GW", "GC"},  # 사질토·자갈
        "rock_exclude_uscs": {"WR", "RS", "SR", "MR", "HR"},      # 풍화암·풍화토·암반 제외
        "rock_exclude_civil": {"풍화암층", "연암층", "경암층", "보통암층"},  # 토목용지층명
        "cohesive_N": 4.0,  "cohesive_depth_max_m": 10.0,
        "sandy_N":    6.0,  "sandy_depth_min_m":    10.0,
        "layer_depth_mode": "mid",   # 대표심도='mid'(층중간) 잠정. 'top' 선택 가능.
        "rep_N_mode": "min",         # 구간 대표 N = 최솟값(보수적)
    },
    # 시추공 3등급 → α [6·22 자료 p.5]
    "grade_alpha": {"연약": 0.6, "주의": 0.8, "양호": 1.0},
    "grade_watch_N": 10.0,   # 주의: 연약층 없으나 최저N<=10 / 양호: 최저N>10

    # ---------------- STEP2: 변위 3지표 임계치 (base, 6·22 자료 p.7) ----------------
    # 근거: 속도 5/10=EGMS 분류임계, 30=지질재해 민감도연구
    #       누적 15/20=허용침하 25mm(국도건설공사)×계측관리 60/80%
    #       가속=크리프3단계+Fukuzono 역속도법(1985), 연속횟수=조기경보 오탐통제
    "thr_base": {
        "vel_watch": 5.0, "vel_danger": 10.0, "vel_immediate": 30.0,   # mm/yr(침하=양수 크기)
        "cum_watch": 15.0, "cum_danger": 20.0,                          # mm
        "accel_watch_consec": 2, "accel_danger_consec": 4,             # 연속 가속 구간 수
    },
    # 임계치 물리적 하한(floor) — 자동조정 시 이 아래로 내리지 않음
    "thr_floor": {"vel": 3.0, "cum": 10.0},
    # α 적용식: threshold_adj = base_threshold × α  (연약일수록 낮은 변위에서 상위등급)
    # (가속 임계치는 연속횟수라 α 미적용 — 시간 조건은 물리량 아님)

    # ---------------- PS 공백 / 결합 (사용자 확정 R=30, K=1) ----------------
    "R_m": 30.0,             # PS 공백 판정 반경(m)
    "K_ps": 1,               # 반경 내 유효 PS 최소 개수(< K 이면 PS 공백)
    "ps_rep_mode": "invdist",  # PS 대표값: 거리 역가중평균('invdist') 또는 'nearest'
    "join_far_flag_m": 300.0,  # α nearest-join 과도거리 플래그(m)

    # ---------------- SBAS 광역 스크리닝(hotspot) ----------------
    # hotspot = 자신이 침하 스크리닝 임계 초과 + 반경 내 이웃도 다수 침하(공간 연속성)
    "sbas": {
        "screen_vel_mmyr": 5.0,     # 스크리닝 침하속도 임계(잠정, base 주의와 동일)
        "neighbor_R_m": 150.0,      # 공간 연속성 이웃 반경
        "neighbor_min_frac": 0.3,   # 이웃 중 침하비율 임계
        "neighbor_min_cnt": 3,      # 최소 이웃 침하 개수
        "tcoh_min": 0.5,            # SBAS 신뢰 최소 tcoh(양양 등 저결맞음 배제, 잠정)
        # 고신뢰 단독 구제(2026-07-09): hotspot 미형성·PS공백이라도, 고품질·강신호 SBAS 단독점은
        #  2단 확인 없이 최종등급 유지(조기경보 recall 우선). 강신호=위험(자체) AND (가속확정 OR 누적≥cum_danger).
        "rescue_enable": True,
        "rescue_tcoh": 0.7,         # 구제 최소 tcoh(고품질만)
    },

    # ---------------- PS·SBAS 결합 규칙(CONFIG 분리) + 클러스터 판정단위 ----------------
    # 도로 아스팔트엔 PS가 안 생기므로(싱크홀 다발지) SBAS 단독으로도 상위등급 가능해야 함.
    #  · active = step2가 실제 사용하는 규칙(기본=현행 hotspot+rescue). ★사용자 확정 전 변경 금지.
    #  · 후보 3종의 recall/FP 비교는 analyze_options.py(a1). 최종선택은 사용자.
    #  · 판정단위는 개별점이 아닌 DBSCAN 클러스터(도로 위 PS부재로 점단위 TP 부적절).
    "combine_rule": {
        "active": "hotspot_rescue",   # 현행: hotspot 게이팅 + 고신뢰 단독구제(step2 sbas 블록)
        "cand": {
            # (i) SBAS 단독 상위등급이면 채택 — 가장 공격적(FP 최대)
            "i_standalone": {},
            # (ii) SBAS 상위등급 + 반경 내 동방향(침하) 이웃 >= min_cnt
            "ii_neighbor": {"R_m": 150.0, "min_cnt": 3},
            # (iii) SBAS 상위등급이 일정 규모 이상 DBSCAN 클러스터에 속할 때만 채택
            "iii_cluster": {"min_pts": 10},
        },
    },
    # DBSCAN 클러스터(판정단위) — UTM 미터. eps=이웃반경, min_samples=코어 최소점수.
    "cluster": {"eps_m": 100.0, "min_samples": 5},

    # 침하만 경보: 융기(LOS velocity>=0) 점은 주의/위험에서 제외(정상 강제). 침하(vel<0)만 상위등급.
    #  · SBAS 최종등급이 인접 PS 등급을 흡수(np.maximum)하므로, '표시점 자체가 침하(vel<0)'일 때만
    #    최종 주의/위험 유지(사용자 지시: 최종 변위속도 −만 경보). vel>=0 → 정상 강제.
    "subsidence_only": True,

    # ---------------- 공통모드 보정 CMC (SBAS 광역 공통추세 제거) ----------------
    # 전체 점이 공유하는 공통추세(예: 부산 사상 '변위 상승→유지', corr 0.97·분산 93%)를
    # 네트워크 중앙값 시계열로 제거 → 국소 이상(싱크홀) 신호 강조. 진단이 '매우 뚜렷'한 지역만 명시 적용.
    #  · 송도(공통모드 0.97이나 실제 광역 압밀 침하)는 제외 — 실신호 보존.
    #  · disp -= median_t(전점), vel -= median(vel) (일관성). PS는 사용자 기준점 재기준화 사용 → 기본 미적용.
    "cmc": {
        "enable": True,
        "sbas_regions": ["Busan_Sasang_Hadan"],   # CMC 적용 SBAS 지역(진단 뚜렷). 빈=미적용
        "ps_regions": [],                          # PS 기본 미적용
        "diag_corr_min": 0.6, "diag_var_expl_min": 0.5,  # (참고 진단 임계)
    },

    # ---------------- 언래핑 오류(정수배 λ/2 점프) 억제 ----------------
    # Sentinel-1 C-band LOS 1위상사이클 = λ/2 = 27.73mm (λ=55.465mm). 국소 시간중앙값(win) 대비
    # 잔차가 27.73mm 정수배(±tol)이고 국소 강건척도(MAD×k)를 초과하는 '진짜 점프'만 정수배 되돌림.
    #  · 인접차분 단순판정은 노이즈 과대검출(30~86%) → 국소중앙값+MAD 게이트로 이상점만 보정.
    #  · disp 시계열만 보정(그래프·누적·추세 보호). vel(StaMPS 강건추정)은 유지.
    "unwrap": {
        "enable": True,
        "cycle_mm": 27.73,        # λ/2
        "tol_mm": 8.0,            # 정수배 근접 허용(±). 8mm≈0.29 cycle
        "max_n": 3,              # 보정 최대 정수배(|n|<=3, ~83mm)
        "win": 7,               # 국소 시간중앙값 창(에폭수, 홀수)
        "outlier_k": 4.0,        # 이상점 게이트: |잔차| > k×(1.4826·MAD)
        "scale_floor_mm": 2.0,   # 강건척도 하한(clean 점 과보정 방지)
        "apply_to": ["ps", "sbas"],
    },

    # PS 재기준화(사용자 기준점): AOI.xlsx 기준점 위경도로 PS만 재기준화(SBAS는 기존 유지).
    #  · output_final − 사용자기준점(반경 내 평균 시계열/속도) = raw − 사용자기준점 (순수차감 검증됨)
    "ps_reref": True,
    "ps_reref_mode": "nearest",   # 'nearest'=최근접 단일 PS(사용자 선정점) / 'radius'=반경평균
    "ps_reref_radius_m": 150.0,   # mode='radius'일 때 평균 반경

    # 누적변위 산정: 최근 고정창(cum_window_years) net 침하 — 스택기간 정합성 확보.
    #  · 7년 아카이브에서 절대 15mm를 느린침하·노이즈가 초과하는 문제 방지.
    #  · 창 내 강건 net = median(창끝 k) - median(창시작 k). 사고前 최근 침하에 집중.
    "cum_robust_k": 3,          # 양끝 median에 쓰는 에폭수
    "cum_window_years": 2.0,    # 누적 산정 최근 창(년). 스택이 짧으면 전체.

    # ---------------- 추세(가속) 산정 — 2구간 강건 기울기 ----------------
    # s(t)=-LOS변위(침하 양수). 전반/후반 강건기울기 비교로 가속 판별
    #  (sliding-window 자기상관 오탐 회피). Fukuzono 역속도법·크리프3단계 취지:
    #   등속·감속=정상 / 후반이 전반보다 delta_watch↑=가속의심 / delta_danger↑=가속확정.
    #  "2회/4~5회 연속" 취지는 '후반 구간(다수 연속관측)에서 지속 가속'으로 조작화.
    # method(판정에 실제 사용) 기본='2seg'(현행). 후보 2seg|slidewin|quad|inflection —
    #  방법별 recall(양성5)/FP(음성2) 비교는 analyze_options.py, 최종 선택은 사용자(클로드 단독확정 금지).
    "trend": {
        "method": "2seg",            # ★잠정 기본. 사용자 확정 전 변경 금지.
        "smooth_win": 5,             # 롤링 중앙값 평활 창(관측수)
        "late_min_rate_mmyr": 3.0,   # 가속 인정: 후반 침하율 절대 하한(노이즈 바닥)
        "accel_delta_watch_mmyr": 3.0,   # 후반-전반 속도증가 >= → 가속의심(주의)
        "accel_delta_danger_mmyr": 6.0,  # 후반-전반 속도증가 >= → 가속확정(위험)
        "min_series": 12,            # 시계열 최소 관측수(미만이면 추세 판정 불가)
        # --- slidewin(이동창 회귀) ---
        "slide_win": 8,              # 이동창 관측수(국소속도 추정 창)
        # --- quad(2차항 가속도 유의성) ---
        "quad_t_watch": 2.0,         # 가속도계수 t통계 임계(주의) ≈95%
        "quad_t_danger": 3.0,        # 〃 (위험) ≈99.7%
        "quad_accel_min_mmyr2": 1.0, # 최소 가속도 크기(mm/yr²) 노이즈 바닥(잠정)
        # --- inflection(3구간 단조가속) ---
        "infl_delta_watch_mmyr": 3.0,
        "infl_delta_danger_mmyr": 6.0,
    },

    # ---------------- 통합맵 시각화(평활·변곡점) — 표시용, 위험판정 원본수치 불변 ----------------
    # 팝업/리포트 누적변위 그래프를 원본(연한 회색) + 평활(검은 실선)로 다시 그림.
    #  · 평활은 시각화·전조탐지용. step2/3 위험등급(속도·누적·추세) 원본값은 절대 덮어쓰지 않음.
    #  · 사용자 확정(2026-07-09): 방식=중앙값→이동평균(강건), 창=7관측(S1 12일주기≈2.8개월), 급변=기울기변화폭 Δv.
    #  · 급변 임계(infl_*)는 ★잠정 — CONFIG로 여러 값 시도 가능.
    "map_viz": {
        "smooth_method": "median_then_ma",  # 'median' | 'ma' | 'median_then_ma'(강건 기본)
        "smooth_window": 7,                 # 이동창 관측수(홀수 권장). 12일주기 → ~2.8개월
        # 침하개시(변곡점) 탐지: 평활곡선 전/후 구간 기울기(침하속도)차 Δv로 '팍 꺾임' 판정
        "infl_metric": "vjump",             # 'vjump'(Δv 강건) | 'accel'(2차미분) | 'both'
        "infl_seg": 5,                      # Δv 계산용 전/후 구간 관측수(국소 기울기 창)
        "infl_vjump_min_mmyr": 8.0,         # ★잠정: 후반-전반 침하속도차 ≥ 이 값이면 급변 후보
        "infl_accel_min_mmyr2": 200.0,      # ★잠정: accel 기준 사용 시 2차미분 임계(mm/yr²)
        "infl_late_min_mmyr": 3.0,          # 후반 침하율 하한(약한 서서히 침하 배제)
        "infl_top_n": 3,                    # 급변 강도순 상위 후보 표시 수
    },

    # ---------------- 역속도법(Fukuzono) — 포인트 팝업 '예상 붕괴시점' t_f ----------------
    # 침하 가속 시 1/v 가 시간에 대해 선형 하강하며 0에서 붕괴(t_f). 최근 속도표본 1/v 직선적합.
    #  · 표시/보조용(붕괴시점 예측). 위험등급 판정 원본수치 불변. 값은 sinkhole_pipeline/pcfg.INVVEL와 정합(잠정).
    "invvel": {
        "vel_win": 6,              # 국소속도 추정 창(관측수). S1 12일주기 ≈ 2.4개월
        "recent_win": 8,           # 1/v 직선적합에 쓰는 최근 속도표본 수
        "min_series": 12,          # 최소 관측수(미만 판정불가)
        "smooth_win": 5,           # s(t) 롤링중앙값 평활 창
        "late_min_rate_mmyr": 3.0, # 최근 침하율 하한(노이즈 바닥)
        "r2_min": 0.5,             # 1/v 선형성 R² 하한(가속 신뢰)
        "iv_floor_mmyr": 1.0,      # v 하한(1/v 폭주 방지)
        "horizon_days_max": 3650,  # t_f 외삽 상한(10년) 초과=원거리 절단
    },

    # ---------------- 경로 (2026-07-19 통합 재정리 반영) ----------------
    "paths": {
        "ground_csv": "<DATA_ROOT>/auxiliary/borehole/지반정보_통합_SPT단위.csv",
        "data_base": "<DATA_ROOT>",
        "out_dir": "<DATA_ROOT>/analysis/sinkhole/out",
        "cache_dir": "<DATA_ROOT>/analysis/sinkhole/out/_cache",
    },
}

# 지역 케이스 정의 — 사용자 확정(2026-07-09): 분면(①③…) 구분은 위치라벨일 뿐,
#  발생/미발생(TP/FN) 판정에는 사용하지 않는다. ③분면(천층/노후관) InSAR 미탐 '예외'를 폐지하고
#  발생 케이스는 전건 양성(무조건 주의/위험 대상)으로 통합. 만덕~센텀은 음성(FP 기준선)으로 재분류.
#   · 양성(발생, positive) : 강동①·연희동⑧·광명②·양양⑦·사상⑨  (전건 주의/위험이어야 함)
#   · 음성(미발생, negative): 송도③·만덕~센텀④  (FP 기준선)
REGIONS = {
    "Seoul_Gangdong":       {"quad": "①", "label": "서울 강동구 명일동(대명초사거리)", "type": "positive",
                             "event_date": "2025-03-24", "note": "9호선 굴착+노후하수관"},
    "Gyeonggi_Gwangmyeong": {"quad": "②", "label": "경기 광명 일직동 신안산선 5-2", "type": "positive",
                             "event_date": "2025-04-11", "note": "대형터널굴착, 감사원 5등급 사전지적"},
    "Yangyang":             {"quad": "⑦", "label": "강원 양양 낙산해변", "type": "positive",
                             "event_date": "2022-08-03", "note": "해안 모래지반, 전조 27차례 장기"},
    "Seoul_Seodaemun":      {"quad": "⑧", "label": "서울 서대문구 연희동", "type": "positive",
                             "event_date": "2024-08-29", "note": "노후하수관 천층(굴착형 아님). 예외 폐지→양성 통합"},
    "Busan_Sasang_Hadan":   {"quad": "⑨", "label": "부산 사상~하단선", "type": "positive",
                             "event_date": "2024-09-01", "note": "흙막이누수 천층. '25-04-13 학장동. 예외 폐지→양성 통합"},
    # ── 음성(미발생, FP 기준선) ──
    "Incheon_Songdo":       {"quad": "③", "label": "인천 송도국제도시", "type": "negative",
                             "event_date": None, "note": "매립지 압밀 점진변위→안정화(비붕괴)"},
    "Busan_Mandeok_Centum": {"quad": "④", "label": "부산 만덕~센텀 대심도", "type": "negative",
                             "event_date": "2023-02-25", "note": "대심도터널(지표 함몰 아님)→음성 재분류(2026-07-09). 스택 2023-06까지"},
    # ⑤ GPR 공동복구구간, ⑥ 안정지반 baseline 은 좌표·데이터 확보 시 추가
}

# ── 2026-07-19 통합 재정리: 결과 경로가 regions/<group>/{psinsar,sbas}/[<aoi>] 로 변경 ──
#  region key → (group, aoi|None). aoi=None 이면 단일 AOI(하위폴더 없이 psinsar/·sbas/ 바로 아래).
import os as _os
REGION_LAYOUT = {
    "Seoul_Gangdong":          ("seoul",    "gangdong"),
    "Seoul_Seodaemun":         ("seoul",    "seodaemun"),
    "Gyeonggi_Gwangmyeong":    ("gyeonggi", None),
    "Yangyang":                ("yangyang", None),
    "Busan_Mandeok_Centum":    ("busan",    "mandeok_centum"),
    "Busan_Sasang_Hadan":      ("busan",    "sasang_hadan"),
    "Incheon_Songdo":          ("incheon",  "songdo"),
    "Incheon_Songdo_DSC":      ("incheon",  "songdo_dsc"),
    "Incheon_Songdo_baseline": ("incheon",  "songdo_baseline"),
}

def region_result_dir(region, tech):
    """지역 결과 폴더 절대경로. tech: 'psinsar'(PS) | 'sbas'(SBAS).
    (구) {data_base}/{region}/{PS,SBAS} → (신) {data_base}/regions/<group>/{psinsar,sbas}/[<aoi>]."""
    grp, aoi = REGION_LAYOUT.get(region, (region.lower(), None))
    p = _os.path.join(CONFIG["paths"]["data_base"], "regions", grp, tech)
    return _os.path.join(p, aoi) if aoi else p

# ---------------- 지질 기반 지반등급 (시추공 공백 보완) ----------------
# ⚠️ lithology 매핑은 실제 수치지질도 SHP 속성값 확인 후 최종화(현재 과제기준 초안).
GEO_CONFIG = {
    "gap_dist_m": 500.0,          # 판정점~최근접 시추공 > 이 거리면 '시추공 공백' → 지질 기반 사용(사용자 확정)
    "use_fault": False,           # 단층 정보 사용 여부(사용자 지시로 제거). False면 단층 판정·표시 없음.
    "fault_buffer_m": 500.0,      # (use_fault=True일 때만) 단층선 버퍼 → '단층 인접' 연약 상향
    "shp_dir": "<DATA_ROOT>/auxiliary/geology/processed",   # (구)5만 도폭 배치 경로(레거시). 2026-07-19 _geology→auxiliary/geology/processed
    # 전국 25만 축척 수치지질도(1:250K) — 5만 도폭 미확보 지역 보완 위해 전국판으로 대체(사용자 제공 2026-07-09).
    #  · 단일 전국 Litho SHP(WGS84). 속성 lithoname/age → LITHONAME/AGE 정규화. 7개 AOI 전부 커버.
    "scale": "1:25만(250K)",
    "nationwide_shp": "<DATA_ROOT>/auxiliary/geology/processed/_250K/Geology_250K_Litho.shp",
    # 암상(한글 키워드 부분일치) → 지반등급. 위험도: 기반암<풍화대<충적<매립/카르스트/단층
    "lith_soft": ["충적", "충적층", "하성", "해성", "제4기", "미고결", "저지대",
                  "매립", "간척", "성토", "인공", "석회암", "돌로마이트", "고회암", "카르스트"],
    "lith_watch": ["풍화암", "풍화토", "풍화대", "붕적", "잔류토"],
    "lith_good": ["화강암", "편마암", "편암", "규암", "석영", "반암", "안산암", "현무암",
                  "응회암", "유문암", "섬록암", "각섬암", "사암", "셰일", "역암", "이암", "혼펠스",
                  # 미분류 7종 확정(2026-07-08): 관입 경암·고결 퇴적암 → 양호
                  "암맥", "반려암", "섬장암", "다대포",
                  # 25만 전국판 추가(2026-07-09): 맥암류(암맥)·규장암·편마암복합체 잔여
                  "맥암", "규장암"],
    "karst_kw": ["석회암", "돌로마이트", "고회암", "카르스트"],   # 카르스트 위험 플래그
    "grade_alpha": {"양호": 1.0, "주의": 0.8, "연약": 0.6},      # 시추공 체계와 동일 스케일
    "confidence": {"borehole": "high", "geology": "medium"},
}

# AOI별 PS 재기준화 기준점 (lat, lon) — AOI.xlsx '기준점 위경도'
AOI_REF = {
    "Seoul_Gangdong":       (37.54514, 127.11945),
    "Seoul_Seodaemun":      (37.58663, 126.97465),
    "Gyeonggi_Gwangmyeong": (37.43859, 126.89128),
    "Incheon_Songdo":       (37.42869, 126.67965),
    "Busan_Mandeok_Centum": (35.19206, 129.13878),
    "Busan_Sasang_Hadan":   (35.15308, 129.00656),
    "Yangyang":             (38.11839, 128.62834),
    "Incheon_Songdo_DSC":   (37.42869, 126.67965),   # 송도 하강궤도(track134) 보조 — 상승본과 동일 기준점
}

# ③분면 InSAR-미탐 '예외' 폐지(2026-07-09, 사용자 확정): 발생 케이스는 분면과 무관하게
#  전건 양성으로 통합 판정. 코드 하위호환을 위해 빈 집합으로 유지(step3에서 예외분기 무력화).
QUAD3_INSAR_LIMIT = set()

# (A)제약 대상 양성 케이스(무조건 주의/위험이어야 함): 강동①·광명②·양양⑦·연희동⑧·사상⑨
POSITIVE_STRICT = {"Seoul_Gangdong", "Gyeonggi_Gwangmyeong", "Yangyang",
                   "Seoul_Seodaemun", "Busan_Sasang_Hadan"}
# 음성(미발생, FP 기준선): 송도③·만덕~센텀④
NEGATIVE_CASES = {"Incheon_Songdo", "Busan_Mandeok_Centum"}
