# -*- coding: utf-8 -*-
"""
pointing_diff_20260408.xlsx + SatRev_metadata CSV 7개
→ pointing_diff_analysis0.xlsx 생성

조인 방법: 각 관측 시각에서 가장 가까운 CSV 타임스탬프를 찾아 붙임
베이스 Excel의 모든 컬럼(pitch, tilt 포함)을 그대로 유지하고
메타데이터 컬럼을 지정 순서로 뒤에 추가
"""

import pandas as pd
import numpy as np
import re
from pathlib import Path

# ============================================================
# 경로 설정
# ============================================================
BASE_EXCEL = r"<DATA_ROOT>\10_BlueBON\pointing_diff\pointing_diff_20260408.xlsx"
CSV_DIR    = Path(r"<DATA_ROOT>\10_BlueBON\pointing_diff\SatRev_metadata\20260331")  # 메타데이터 CSV 파일들이 있는 폴더, 날짜는 메타데이터 마지막날
OUT_EXCEL  = r"<DATA_ROOT>\10_BlueBON\pointing_diff\SatRev_metadata\1_merge\20260331\pointing_diff_analysis_20260331.xlsx"

# ============================================================
# CSV 파일 목록 (glob으로 자동 탐지)
# ============================================================
# 파일명 패턴으로 구분
def find_csv(keyword):
    """키워드를 포함하는 CSV 파일 경로 반환"""
    matches = list(CSV_DIR.glob(f"*{keyword}*.csv"))
    if not matches:
        raise FileNotFoundError(f"CSV 파일을 찾을 수 없음: *{keyword}*.csv")
    return matches[0]

csv_alt_gnss = find_csv("Mean Sea Level Altitude-data")          # GNSS 고도
csv_alt_tle  = find_csv("Mean Sea Level Altitude (TLE)")         # TLE 고도
csv_ecef_v   = find_csv("ECEF Velocity")                         # ECEF 속도
csv_eci_v    = find_csv("ECI Velocity")                          # ECI 속도
csv_gps_sat  = find_csv("Number of Available GPS")               # GPS 위성 수
csv_ang_rate = find_csv("Satellite Angular Rates")               # 각속도
csv_time_diff = find_csv("System Time Diffrence")                # GNSS-OBC 시간차

print("CSV 파일 확인:")
for f in [csv_alt_gnss, csv_alt_tle, csv_ecef_v, csv_eci_v,
          csv_gps_sat, csv_ang_rate, csv_time_diff]:
    print(f"  {f.name}")

# ============================================================
# 공통 파싱 함수
# ============================================================
def parse_utf16_tsv(path):
    """CSV 읽기 (인코딩·구분자 자동 감지: UTF-16/UTF-8 × tab/comma)"""
    for enc in ('utf-16', 'utf-16-le', 'utf-16-be', 'utf-8-sig', 'utf-8'):
        for sep in ('\t', ','):
            try:
                df = pd.read_csv(path, sep=sep, encoding=enc, skipinitialspace=True)
                if len(df.columns) > 1:
                    return df
            except (UnicodeError, UnicodeDecodeError):
                continue
    raise ValueError(f"인코딩/구분자 자동 감지 실패: {path}")

def strip_unit(series):
    """'496 km', '-5840 m/s', '0.00184 °/s' 등에서 숫자만 추출"""
    def _extract(val):
        if pd.isna(val):
            return np.nan
        s = str(val).strip()
        if s == '' or s == 'nan':
            return np.nan
        m = re.match(r'^([+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?)', s)
        return float(m.group(1)) if m else np.nan
    return series.map(_extract)

def coalesce_cols(df, col_prefix):
    """같은 변수를 여러 텔레메트리 파일에서 가져온 컬럼을 첫 번째 유효값으로 합침"""
    cols = [c for c in df.columns if col_prefix.lower() in c.lower()]
    if not cols:
        return pd.Series(np.nan, index=df.index)
    result = pd.Series(np.nan, index=df.index)
    for c in cols:
        result = result.combine_first(strip_unit(df[c]))
    return result

def parse_time_col(df, col='Time'):
    df = df.copy()
    df[col] = pd.to_datetime(df[col].astype(str).str.strip(), errors='coerce')
    return df.dropna(subset=[col]).reset_index(drop=True)

def nearest_join(base_dt_series, csv_df, value_cols, time_col='Time', tolerance_min=35):
    """
    base_dt_series: 관측 시각 Series (datetime)
    csv_df: Time 컬럼을 가진 DataFrame
    value_cols: {out_col: csv_col} 매핑
    tolerance_min: 이 분 이상 차이나면 NaN 처리
    """
    result = pd.DataFrame(index=base_dt_series.index)
    csv_times = csv_df[time_col].values.astype('datetime64[ns]')

    for out_col, csv_col in value_cols.items():
        vals = []
        for obs_t in base_dt_series:
            if pd.isna(obs_t):
                vals.append(np.nan)
                continue
            obs_ns = np.datetime64(obs_t, 'ns')
            diffs = np.abs(csv_times - obs_ns)
            idx_min = diffs.argmin()
            diff_min = diffs[idx_min] / np.timedelta64(1, 'm')
            if diff_min > tolerance_min:
                vals.append(np.nan)
            else:
                vals.append(csv_df[csv_col].iloc[idx_min])
        result[out_col] = vals
    return result

# ============================================================
# 1. 베이스 Excel 읽기
# ============================================================
print("\n[1] 베이스 Excel 읽기...")
df = pd.read_excel(BASE_EXCEL)
print(f"  shape: {df.shape}")
print(f"  columns: {df.columns.tolist()}")

# obs_time 컬럼 찾기 (obs_time 또는 obs_time.1 모두 대응)
obs_time_col = 'obs_time.1' if 'obs_time.1' in df.columns else 'obs_time'
df['obs_dt'] = pd.to_datetime(df[obs_time_col], errors='coerce')
print(f"  사용 시간 컬럼: {obs_time_col}, 유효: {df['obs_dt'].notna().sum()}건")

# ============================================================
# 2. GNSS 고도 (Alt_GNSS)
# ============================================================
print("\n[2] GNSS 고도...")
raw = parse_utf16_tsv(csv_alt_gnss)
raw = parse_time_col(raw)
# 첫 번째 데이터 컬럼 = "Mean sea level altitude" (여러 파일 중 첫 유효값)
raw['_val'] = coalesce_cols(raw, 'Mean sea level altitude')
joined = nearest_join(df['obs_dt'], raw, {'Alt_GNSS(km)': '_val'})
df['Alt_GNSS(km)'] = joined['Alt_GNSS(km)']
print(f"  매칭: {df['Alt_GNSS(km)'].notna().sum()}건")

# ============================================================
# 3. TLE 고도 (Alt_TLE)
# ============================================================
print("\n[3] TLE 고도...")
raw = parse_utf16_tsv(csv_alt_tle)
raw = parse_time_col(raw)
raw['_val'] = coalesce_cols(raw, 'SatAlt')
joined = nearest_join(df['obs_dt'], raw, {'Alt_TLE(km)': '_val'})
df['Alt_TLE(km)'] = joined['Alt_TLE(km)']
print(f"  매칭: {df['Alt_TLE(km)'].notna().sum()}건")

# ============================================================
# 4. ECEF 속도
# ============================================================
print("\n[4] ECEF 속도...")
raw = parse_utf16_tsv(csv_ecef_v)
raw = parse_time_col(raw)
raw['_vx'] = coalesce_cols(raw, 'ecef_vx')
raw['_vy'] = coalesce_cols(raw, 'ecef_vy')
raw['_vz'] = coalesce_cols(raw, 'ecef_vz')
joined = nearest_join(df['obs_dt'], raw,
                      {'ECEF_Vx(m/s)': '_vx',
                       'ECEF_Vy(m/s)': '_vy',
                       'ECEF_Vz(m/s)': '_vz'})
df['ECEF_Vx(m/s)'] = joined['ECEF_Vx(m/s)']
df['ECEF_Vy(m/s)'] = joined['ECEF_Vy(m/s)']
df['ECEF_Vz(m/s)'] = joined['ECEF_Vz(m/s)']
print(f"  매칭: {df['ECEF_Vx(m/s)'].notna().sum()}건")

# ============================================================
# 5. ECI 속도 (TLE)
# ============================================================
print("\n[5] ECI 속도...")
raw = parse_utf16_tsv(csv_eci_v)
raw = parse_time_col(raw)
raw['_vx'] = coalesce_cols(raw, 'SatVelEciX')
raw['_vy'] = coalesce_cols(raw, 'SatVelEciY')
raw['_vz'] = coalesce_cols(raw, 'SatVelEciZ')
joined = nearest_join(df['obs_dt'], raw,
                      {'ECI_Vx(m/s)': '_vx',
                       'ECI_Vy(m/s)': '_vy',
                       'ECI_Vz(m/s)': '_vz'})
df['ECI_Vx(m/s)'] = joined['ECI_Vx(m/s)']
df['ECI_Vy(m/s)'] = joined['ECI_Vy(m/s)']
df['ECI_Vz(m/s)'] = joined['ECI_Vz(m/s)']
print(f"  매칭: {df['ECI_Vx(m/s)'].notna().sum()}건")

# ============================================================
# 6. GPS 위성 수
# ============================================================
print("\n[6] GPS 위성 수...")
raw = parse_utf16_tsv(csv_gps_sat)
raw = parse_time_col(raw)
raw['_val'] = coalesce_cols(raw, 'sv_number')
joined = nearest_join(df['obs_dt'], raw, {'GPS_Sats': '_val'})
df['GPS_Sats'] = joined['GPS_Sats']
print(f"  매칭: {df['GPS_Sats'].notna().sum()}건")

# ============================================================
# 7. 각속도
# ============================================================
print("\n[7] 각속도...")
raw = parse_utf16_tsv(csv_ang_rate)
raw = parse_time_col(raw)
raw['_rx'] = coalesce_cols(raw, 'EstRateOrcX')
raw['_ry'] = coalesce_cols(raw, 'EstRateOrcY')
raw['_rz'] = coalesce_cols(raw, 'EstRateOrcZ')
joined = nearest_join(df['obs_dt'], raw,
                      {'AngRate_X(°/s)': '_rx',
                       'AngRate_Y(°/s)': '_ry',
                       'AngRate_Z(°/s)': '_rz'})
df['AngRate_X(°/s)'] = joined['AngRate_X(°/s)']
df['AngRate_Y(°/s)'] = joined['AngRate_Y(°/s)']
df['AngRate_Z(°/s)'] = joined['AngRate_Z(°/s)']
print(f"  매칭: {df['AngRate_X(°/s)'].notna().sum()}건")

# ============================================================
# 8. GNSS-OBC 시간차 (System Time Difference)
# ============================================================
print("\n[8] GNSS-OBC 시간차...")
raw_td = pd.read_csv(csv_time_diff, encoding='utf-8-sig')
raw_td.columns = raw_td.columns.str.strip()
raw_td = parse_time_col(raw_td, 'Time')
# "Time diff" 컬럼: "-2 ms" → -2
raw_td['_val'] = strip_unit(raw_td.iloc[:, 1])
joined = nearest_join(df['obs_dt'], raw_td, {'TimeDiff_GNSS_OBC': '_val'})
df['TimeDiff_GNSS_OBC'] = joined['TimeDiff_GNSS_OBC']
print(f"  매칭: {df['TimeDiff_GNSS_OBC'].notna().sum()}건")

# ============================================================
# 9. 컬럼 순서 정렬 후 저장
# ============================================================
df = df.drop(columns=['obs_dt'], errors='ignore')

# 분석 스크립트들이 'obs_time.1'을 참조하므로 컬럼명 통일
if 'obs_time' in df.columns and 'obs_time.1' not in df.columns:
    df = df.rename(columns={'obs_time': 'obs_time.1'})

# 베이스 컬럼 + 메타데이터 컬럼 순서 지정
TELEM_COLS = [
    'Alt_GNSS(km)', 'Alt_TLE(km)', 'GPS_Sats',
    'AngRate_X(°/s)', 'AngRate_Y(°/s)', 'AngRate_Z(°/s)',
    'ECEF_Vx(m/s)', 'ECEF_Vy(m/s)', 'ECEF_Vz(m/s)',
    'ECI_Vx(m/s)', 'ECI_Vy(m/s)', 'ECI_Vz(m/s)',
    'TimeDiff_GNSS_OBC',
]
base_cols = [c for c in df.columns if c not in TELEM_COLS]
final_cols = base_cols + [c for c in TELEM_COLS if c in df.columns]
df = df[final_cols]

print(f"\n[9] 저장: {OUT_EXCEL}")
df.to_excel(OUT_EXCEL, index=False)
print(f"  완료! shape: {df.shape}")
print(f"  columns: {df.columns.tolist()}")
