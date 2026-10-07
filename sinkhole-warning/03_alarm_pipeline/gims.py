# -*- coding: utf-8 -*-
"""(1-1)(B) GIMS 국가지하수측정망 지하수위 방아쇠 레이어.
실측 규격(2026-07-14 확인): base http://www.gims.go.kr/api/data/{svc}/{svc},
  인증 파라미터 KEY(=서비스별 키), type=JSON. 시간자료 observationStationTimeService
  (params: gennum, begindate, enddate, datatype). 응답: ymd, elev(수위), lev(심도), wtemp, ec.
⚠️ GIMS는 **서비스별 키**. (B) 수위 시계열엔 '국가지하수측정자료조회서비스(일/시간자료)' 키 필요
  (측정망제원·심도분포도 키로는 UNMATCHED_KEY). 관측소목록/심도맵 엔드포인트 URI는 사용자
  로그인 상세화면 '요청주소'에서 확정(pcfg.GIMS svc_station/svc_depth). 미확정/미제공 시 우아하게 skip."""
import os; os.environ.pop("PYTHONPATH", None)
import re, time
import numpy as np, pandas as pd
import requests

from pcfg import PATHS, GIMS

TODO = os.path.join(PATHS["gims"], "README_GIMS_TODO.md")


def _get(uri, key, params):
    """GIMS REST 호출. uri='{svc}/{svc}' 상대경로. KEY 파라미터 사용."""
    url = f"{GIMS['base']}/{uri}"
    last = None
    for i in range(GIMS["retries"]):
        try:
            r = requests.get(url, params={"KEY": key, "type": "JSON", **params}, timeout=GIMS["timeout"])
            r.raise_for_status()
            try:
                return r.json()
            except ValueError:
                return {"_raw": r.text}
        except Exception as e:
            last = e; time.sleep(0.5 * (2 ** i))
    raise ConnectionError(f"GIMS 호출 실패({uri}): {last}")


def _result_code(js):
    try:
        return js.get("response", {}).get("resultCode")
    except Exception:
        return None


def _items(js):
    r = js.get("response", js) if isinstance(js, dict) else {}
    for k in ("resultData", "data", "items", "list"):
        v = r.get(k) if isinstance(r, dict) else None
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            inner = v.get("item", v)
            return inner if isinstance(inner, list) else [inner]
    return []


def fetch_timeseries(gennum, y0, y1):
    """수위 시계열 → DataFrame[date, gwl(m)]. keys['timeseries'] 필요. 일자료 우선, 실패 시 시간자료."""
    key = GIMS["keys"].get("timeseries")
    if not key:
        return pd.DataFrame(columns=["date", "gwl"])
    for uri in (GIMS["svc_day"], GIMS["svc_time"]):
        js = _get(uri, key, {"gennum": gennum, "begindate": f"{int(y0)}0101",
                             "enddate": f"{int(y1)}1231"})
        if _result_code(js) in ("UNMATCHED_KEY", "INVALID_KEY", "NO_AUTH"):
            continue
        rows = _items(js)
        if not rows:
            continue
        df = pd.DataFrame(rows)
        dcol = next((c for c in ["ymd", "obsdate", "관측날짜", "date"] if c in df.columns), None)
        gcol = next((c for c in ["elev", "지하수위", "gwl", "waterlevel"] if c in df.columns), None)
        if dcol and gcol:
            s = df[dcol].astype(str).str.strip()
            # ymd: YYYYMMDDHH(시간자료, 10자리) 또는 YYYYMMDD(8자리)
            dt = pd.to_datetime(s.str.slice(0, 10), format="%Y%m%d%H", errors="coerce")
            dt = dt.fillna(pd.to_datetime(s.str.slice(0, 8), format="%Y%m%d", errors="coerce"))
            return pd.DataFrame({"date": dt,
                                 "gwl": pd.to_numeric(df[gcol], errors="coerce")}).dropna().sort_values("date")
    return pd.DataFrame(columns=["date", "gwl"])


def fetch_stations():
    """측정망제원조회서비스 → DataFrame[stn, lat, lon]. svc_station URI + keys['station'] 필요."""
    uri = GIMS.get("svc_station"); key = GIMS["keys"].get("station")
    if not uri or not key:
        raise ValueError("측정망제원 엔드포인트(svc_station) 또는 키 미확정")
    req = GIMS.get("svc_station_required") or {}
    if not req:
        raise ValueError("getNationalGroundwater 필수 파라미터 미상(svc_station_required) — GIMS 상세기능 요청파라미터 확인 필요")
    js = _get(uri, key, {"numOfRows": 5000, "pageNo": 1, **req})
    rc = _result_code(js)
    if rc and rc != "NORMAL_SERVICE":
        raise ValueError(f"측정망제원 응답코드 {rc}")
    rows = _items(js)
    if not rows:
        raise ValueError("측정망제원 응답 비어있음")
    df = pd.DataFrame(rows)
    def pick(cands):
        return next((c for c in cands if c in df.columns), None)
    sid = pick(["gennum", "측정망번호", "stnId", "obsid"]); la = pick(["lat", "위도", "yLat", "latitude"])
    lo = pick(["lon", "경도", "xLon", "longitude"])
    if not (sid and la and lo):
        raise ValueError(f"측정망제원 컬럼 매핑 실패: {list(df.columns)[:12]}")
    return pd.DataFrame({"stn": df[sid].astype(str),
                         "lat": pd.to_numeric(df[la], errors="coerce"),
                         "lon": pd.to_numeric(df[lo], errors="coerce")}).dropna()


def drawdown_trigger(gwl):
    """수위 시계열 → 최근 최대 월낙폭(mm/월)·급강하 방아쇠. 수위 하강=방아쇠."""
    if len(gwl) < 30:
        return {"triggered": False, "max_drawdown_mm_month": np.nan, "n": len(gwl)}
    g = gwl.set_index("date")["gwl"].resample("MS").mean().interpolate()
    d = -g.diff() * 1000.0
    mx = float(d.max())
    return {"triggered": mx >= GIMS["drawdown_mm_per_month"],
            "max_drawdown_mm_month": round(mx, 1), "n": len(gwl)}


def _write_todo(reason):
    with open(TODO, "w", encoding="utf-8") as f:
        f.write(f"""# GIMS 지하수 연동 — 확정 필요 (현재 (B) 시계열 skip)

사유: {reason}

## 확인된 GIMS 규격 (2026-07-14)
- base: `http://www.gims.go.kr/api/data/{{서비스URI}}` , 인증 파라미터 `KEY`(서비스별), `type=JSON`
- 시간자료(확인): `observationStationTimeService/observationStationTimeService?KEY=..&type=JSON&gennum=&begindate=YYYYMMDD&enddate=YYYYMMDD&datatype=1`
- 응답: `ymd`(관측날짜), `elev`(수위), `lev`(심도), `wtemp`, `ec`
- ★ GIMS는 **서비스별 키**. 제공된 두 키는 각각 **측정망제원조회**/**지하수심도분포도조회** 전용
  → 시간/일자료 엔드포인트엔 `UNMATCHED_KEY`(유효하나 다른 서비스).

## 사용자가 제공/확정할 것 (택1 이상)
1. **(핵심) '국가지하수측정자료조회서비스(일/시간자료)' 키** → `GIMS_KEY` 환경변수.
   이게 있어야 (B) 수위 **시계열 급강하 방아쇠**를 계산.
2. **제공한 두 서비스의 정확한 요청주소(엔드포인트 URI)** — GIMS 로그인 후
   '오픈API > 서비스 상세 > 상세기능'의 **요청주소**란에서 복사:
   - 측정망제원조회서비스 URI → `pcfg.GIMS['svc_station']` (관측소 목록+좌표: AOI 필터·gennum 확보)
   - 지하수심도분포도조회서비스 URI → `pcfg.GIMS['svc_depth']` (정적 심도맵: (C) 보강)
   키는 이미 환경변수로 주입: `GIMS_KEY_STATION`, `GIMS_KEY_DEPTH`.

## 실행
```
GIMS_KEY=<시계열키> GIMS_KEY_STATION=<측정망제원키> python3 run_pipeline.py --gims-key <시계열키>
```
미확정 시: (A)InSAR + (C)지반으로 정상 동작(현행).
""")


def run_all(aoi, key=None):
    """전 AOI GIMS 방아쇠. 시계열 키 없으면 (B) skip(TODO). station URI 있으면 관측소밀도만 기록."""
    ts_key = key or GIMS["keys"].get("timeseries")
    st_key = GIMS["keys"].get("station")
    # (선택) 측정망제원 URI+키 있으면 관측소목록·AOI 밀도 저장
    if GIMS.get("svc_station") and st_key:
        try:
            stns = fetch_stations()
            stns.to_csv(os.path.join(PATHS["gims"], "stations_all.csv"), index=False, encoding="utf-8-sig")
            for region, info in aoi.items():
                b = info["bbox"]; pk = GIMS["aoi_pad_km"]; dl = pk / 111.0
                do = pk / (111.0 * np.cos(np.radians((b["S"] + b["N"]) / 2)))
                m = ((stns.lat >= b["S"] - dl) & (stns.lat <= b["N"] + dl) &
                     (stns.lon >= b["W"] - do) & (stns.lon <= b["E"] + do))
                print(f"[GIMS] {region}: AOI±{pk}km 관측소 {int(m.sum())}개")
        except Exception as e:
            print(f"[GIMS] 관측소목록 skip: {e}")
    if not GIMS.get("enable", True) or not ts_key:
        _write_todo("시계열(국가지하수측정자료) 키 미제공 — 제공된 키는 측정망제원/심도분포도 전용")
        print("[GIMS] 수위 시계열 키 없음 → (B) 방아쇠 skip. 안내: data/gims/README_GIMS_TODO.md")
        return {"status": "skip_timeseries"}
    # 시계열 키가 있으면: 관측소별 시계열→방아쇠 (station URI 확정 시 gennum 순회)
    print("[GIMS] 시계열 키 감지 — 관측소별 급강하 방아쇠 산출(관측소목록 URI 확정 필요)")
    return {"status": "ok_timeseries_key"}


if __name__ == "__main__":
    from aoi import load_aoi
    print(run_all(load_aoi()))
