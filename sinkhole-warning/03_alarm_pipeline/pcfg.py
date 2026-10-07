# -*- coding: utf-8 -*-
"""파이프라인 공통 설정. 기존 sinkhole/ 검증자산(loaders·indicators·config·events)을 재사용.
⚠️ 신규 임계치·계수는 전부 '백테스팅 확정 전 잠정값'."""
import os, sys
os.environ.pop("PYTHONPATH", None)   # pyproj CRS 오염 방지(기존 로더 규약)

SINK = "<DATA_ROOT>/analysis/sinkhole"          # 기존 PoC 코드(재사용)
if SINK not in sys.path:
    sys.path.insert(0, SINK)

# 기존 검증자산 임포트(임계치·좌표계·지역·사고라벨)
from config import CONFIG, REGIONS, AOI_REF          # noqa: E402
from events import EVENTS                            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# GIMS 서비스별 키 자동 로드(있으면). export KEY="val" 형식 파싱.
_kf = os.path.join(HERE, "gims_keys.env")
if os.path.exists(_kf):
    import re as _re
    for _ln in open(_kf, encoding="utf-8"):
        _m = _re.match(r'\s*export\s+(\w+)\s*=\s*"?([^"#\n]+)"?', _ln)
        if _m and not os.environ.get(_m.group(1)):
            os.environ[_m.group(1)] = _m.group(2).strip()

PATHS = {
    "aoi_xlsx":     "<DATA_ROOT>/auxiliary/AOI.xlsx",
    "ground_csv":   "<DATA_ROOT>/auxiliary/borehole/지반정보_통합_SPT단위.csv",
    "subsidence":   "<DATA_ROOT>/auxiliary/subsidence_list/subsidence_accidents_geocoded.csv",
    "geo_integrated_dir": os.path.join(SINK, "out"),   # geo_integrated_{region}.csv (α)
    "borehole_grade":     os.path.join(SINK, "out", "step1_borehole_grade.csv"),
    "out":          HERE,
    "features":     os.path.join(HERE, "features"),
    "alarms":       os.path.join(HERE, "alarms"),
    "backtest":     os.path.join(HERE, "backtest"),
    "gims":         os.path.join(HERE, "data", "gims"),
    "jis":          os.path.join(HERE, "data", "jis"),
    "cache":        os.path.join(HERE, "data", "_cache"),
}

# 한글 AOI명 → region 키(폴더명) 매핑(AOI.xlsx 순서 고정)
AOI_TO_REGION = {
    "서울 강동구 명일동": "Seoul_Gangdong",
    "서울 서대문구 연희동": "Seoul_Seodaemun",
    "경기 광명 신안산선 5-2": "Gyeonggi_Gwangmyeong",
    "인천 송도국제도시": "Incheon_Songdo",
    "부산 만덕~센텀 대심도": "Busan_Mandeok_Centum",
    "부산 사상~하단선 도시철도": "Busan_Sasang_Hadan",
    "강원 양양 낙산해변": "Yangyang",
}

# ---------------- (A) 역속도법(Fukuzono) 파라미터 [잠정] ----------------
INVVEL = {
    "vel_win": 6,             # 국소속도 추정 창(관측수). S1 12일주기 ≈ 2.4개월
    "recent_win": 8,          # 역속도 직선적합에 쓰는 최근 속도표본 수
    "min_series": 12,         # 최소 관측수(미만 판정불가)
    "smooth_win": 5,          # s(t) 롤링중앙값 평활 창
    "late_min_rate_mmyr": 3.0,# 최근 침하율 하한(노이즈 바닥, config trend와 정합)
    "r2_min": 0.5,            # 1/v 선형성 R² 하한(가속 신뢰)
    "iv_floor_mmyr": 1.0,     # v 하한(1/v 폭주 방지, |v|<이 값이면 제외)
    "horizon_days_max": 3650, # t_f 외삽 상한(10년). 초과는 '원거리'로 절단
}

# ---------------- (B) GIMS 지하수위 방아쇠 [잠정] ----------------
# GIMS 실측규격(2026-07-14 확인): base http://www.gims.go.kr/api/data/{svc}/{svc},
#  인증 파라미터 KEY(=서비스별 키, serviceKey 아님), type=JSON. 시간자료 엔드포인트 확인됨:
#  observationStationTimeService (params: gennum, begindate, enddate, datatype[1실시간/5연보]).
#  응답: ymd(관측날짜), elev(수위), lev(심도), wtemp(수온), ec.
# ⚠️ 서비스별 키라, (B)수위시계열엔 '국가지하수측정자료조회서비스(일/시간자료)' 키가 별도 필요.
#    아래 station/depth 엔드포인트 URI는 사용자 로그인 상세화면 '요청주소'에서 확정 필요(미확정).
GIMS = {
    "enable": False,   # ★2026-07-14 사용자 결정: 지하수(B) 레이어 제외. 국가망만 과거계열 가능·보조망 미공개·도심밀도 성김 → 최종 설계는 (A)InSAR+(C)지반. (참고자산은 PROJ/underwater/에 보존)
    "base": "http://www.gims.go.kr/api/data",
    "svc_time": "observationStationTimeService/observationStationTimeService",  # 시간자료(확인됨)
    "svc_day":  "observationStationDayService/observationStationDayService",    # 일자료(추정, 확인필요)
    # 측정망제원조회서비스(WFS): 엔드포인트 확정(키 매칭됨). ★단 필수 파라미터 [XMLParam] 1개 미상
    #  (PARAM_REQUIRED — GIMS 상세기능 '요청 파라미터' 표에서 확인 필요). 그 값 채우면 즉시 로스터 수집.
    "svc_station": "groundwaterMonitoringNetworkService/getNationalGroundwater",
    "svc_station_required": {},   # 예: {"<필수파라미터명>": "<값>"} — 확인 후 기입
    "svc_depth":   None,   # 지하수심도분포도조회서비스 상세주소(서비스명) — 사용자 상세화면서 확인 후 기입
    "keys": {              # 서비스별 인증키(제공분). timeseries 키는 미제공 → (B)시계열 skip
        "station": os.environ.get("GIMS_KEY_STATION"),   # 측정망제원(관측소 목록)
        "depth":   os.environ.get("GIMS_KEY_DEPTH"),     # 지하수심도분포도(정적 심도맵)
        "timeseries": os.environ.get("GIMS_KEY"),        # 국가지하수측정자료(일/시간자료) — 필요
    },
    "timeout": 12, "retries": 3,
    "drawdown_mm_per_month": 500.0,   # 급강하 방아쇠(월 낙폭 임계, 잠정)
    "coincide_days": 180,             # InSAR 가속구간과 수위급강하 동행 허용 시차(일)
    "aoi_pad_km": 5.0,                # AOI bbox 확장(최근접 관측소 탐색)
}

# ---------------- (4) 융합 스코어링·알람 [잠정] ----------------
RISK = {
    # 3-레이어 조합: InSAR 위험등급(A) 기반 + 역속도 가속(A') + 지하수 방아쇠(B) + 지반취약 α(C, 이미 임계 반영)
    #  최종 점수는 등급 서수(0/1/2) + 부스터. 클러스터 단위로 집계.
    "grade_score": {"정상": 0, "주의": 1, "위험": 2},
    "invvel_boost": 1,        # 역속도 가속확정(t_f 유의)이면 점수 +1
    "gwl_boost": 0,           # 지하수(B) 제외 결정(2026-07-14) → 부스터 비활성(GIMS enable=False)
    "subsidence_only": True,  # 융기점 제외(기존 정책)
}
# 클러스터 알람 3단계(관심/주의/경보) — 클러스터 대표점수·규모로 판정 [잠정]
ALARM = {
    "eps_m": CONFIG["cluster"]["eps_m"],          # DBSCAN 반경(기존 100m)
    "min_samples": CONFIG["cluster"]["min_samples"],  # 코어 최소점수(기존 5)
    "level_by_score": {0: "관심", 1: "주의", 2: "경보"},  # 클러스터 대표(최대) 점수 매핑
    "min_cluster_elevated": 3,   # 상위등급(주의+) 멤버 최소수(단발 노이즈 억제)
}

for _p in ("features", "alarms", "backtest", "gims", "jis", "cache"):
    os.makedirs(PATHS[_p], exist_ok=True)
