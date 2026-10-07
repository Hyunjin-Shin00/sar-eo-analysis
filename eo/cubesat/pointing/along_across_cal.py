import math
import sys
import numpy as np
from datetime import datetime, timedelta
from sgp4.api import Satrec, jday

# -----------------------------
# 1. Haversine 거리 계산 (meters)
# -----------------------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius (m)

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# -----------------------------
# 2. 방위각 계산 (deg)
# -----------------------------
def bearing(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)

    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - \
        math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)

    brng = math.degrees(math.atan2(x, y))

    return (brng + 360) % 360  # 0~360 정규화


# -----------------------------
# 3. Along / Across 계산
# -----------------------------
def along_across(center_lat, center_lon,
                 target_lat, target_lon,
                 sat_heading_deg):

    # 거리
    D = haversine(center_lat, center_lon,
                  target_lat, target_lon)

    # center → target 방위각
    az = bearing(center_lat, center_lon,
                 target_lat, target_lon)

    # 상대각 (deg → rad)
    theta = math.radians(az - sat_heading_deg)

    along = D * math.cos(theta)
    # across > 0 : left of track
    # across < 0 : right of track
    across = D * math.sin(theta)

    return along, across, D

# -----------------------------
# 1. ECEF 변환 (ECI → ECEF)
# -----------------------------
def gmst(dt):
    # Greenwich Mean Sidereal Time (rad)
    jd, fr = jday(dt.year, dt.month, dt.day,
                  dt.hour, dt.minute,
                  dt.second + dt.microsecond * 1e-6)

    T = (jd - 2451545.0) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) \
           + 0.000387933 * T**2 - T**3 / 38710000.0

    return np.radians(gmst % 360)


def eci_to_ecef(r_eci, dt):
    theta = gmst(dt)
    R = np.array([
        [ np.cos(theta),  np.sin(theta), 0],
        [-np.sin(theta),  np.cos(theta), 0],
        [ 0,              0,             1]
    ])
    return R @ r_eci


# -----------------------------
# 2. ECEF → 위경도
# -----------------------------
def ecef_to_latlon(r):
    a = 6378137.0
    e2 = 6.69437999014e-3

    x, y, z = r

    lon = np.arctan2(y, x)
    p = np.sqrt(x**2 + y**2)

    lat = np.arctan2(z, p*(1-e2))
    for _ in range(5):
        N = a / np.sqrt(1 - e2*np.sin(lat)**2)
        lat = np.arctan2(z + e2*N*np.sin(lat), p)

    return np.degrees(lat), np.degrees(lon)

# -----------------------------
# 4. Heading 계산 함수
# -----------------------------
def satellite_heading(tle_line1, tle_line2, obs_time):

    sat = Satrec.twoline2rv(tle_line1, tle_line2)

    dt1 = obs_time
    dt2 = obs_time + timedelta(milliseconds=200)  # 200ms 후

    jd1, fr1 = jday(dt1.year, dt1.month, dt1.day,
                    dt1.hour, dt1.minute,
                    dt1.second + dt1.microsecond * 1e-6)

    jd2, fr2 = jday(dt2.year, dt2.month, dt2.day,
                    dt2.hour, dt2.minute,
                    dt2.second + dt2.microsecond * 1e-6)

    e1, r1, v1 = sat.sgp4(jd1, fr1)
    e2, r2, v2 = sat.sgp4(jd2, fr2)

    if e1 != 0 or e2 != 0:
        raise RuntimeError("SGP4 propagation error")

    r1 = np.array(r1) * 1000  # km → m
    r2 = np.array(r2) * 1000

    # ECEF 변환
    r1_ecef = eci_to_ecef(r1, dt1)
    v1_ecef = eci_to_ecef(v1, dt1)
    r2_ecef = eci_to_ecef(r2, dt2)

    # 위성 지상투영점 (sub-satellite point)
    lat1, lon1 = ecef_to_latlon(r1_ecef)
    lat2, lon2 = ecef_to_latlon(r2_ecef)

    # 방위각 계산
    heading = bearing(lat1, lon1, lat2, lon2)

    return heading, (lat1, lon1), r1_ecef, v1_ecef

def latlon_to_ecef(lat, lon, h=0):
    a = 6378137.0
    e2 = 6.69437999014e-3

    lat = np.radians(lat)
    lon = np.radians(lon)

    N = a / np.sqrt(1 - e2 * np.sin(lat)**2)

    x = (N + h) * np.cos(lat) * np.cos(lon)
    y = (N + h) * np.cos(lat) * np.sin(lon)
    z = (N * (1 - e2) + h) * np.sin(lat)

    return np.array([x, y, z])

def compute_roll_pitch(r_sat_ecef, v_sat_ecef, target_lat, target_lon):
    r_target = latlon_to_ecef(target_lat, target_lon, 0)

    los = r_target - r_sat_ecef
    los = los / np.linalg.norm(los)

    x_hat = v_sat_ecef / np.linalg.norm(v_sat_ecef)   # along
    z_hat = -r_sat_ecef / np.linalg.norm(r_sat_ecef)  # down (nadir)
    y_hat = np.cross(z_hat, x_hat)
    y_hat /= np.linalg.norm(y_hat)

    R = np.vstack([x_hat, y_hat, z_hat]).T

    los_lvlh = R.T @ los

    pitch = np.degrees(np.arctan2(los_lvlh[0], -los_lvlh[2]))
    roll  = np.degrees(np.arctan2(los_lvlh[1], -los_lvlh[2]))

    return roll, pitch



# -----------------------------
# 4. 예시 입력
# -----------------------------

center_lat = float(sys.argv[4])
center_lon = float(sys.argv[5])

target_lat = float(sys.argv[2])
target_lon = float(sys.argv[3])

input_time= sys.argv[1]

tle1="1 62688U 25009CH  26076.49036913  .00006637  00000+0  23687-3 0  9992"
tle2="2 62688 097.4018 159.9516 0000491  47.0948 313.0333 15.29204400 64950"

#input_time="20260214151635.268"
otime = datetime.strptime(input_time, "%Y-%m-%dT%H:%M:%S.%f")

sat_heading_deg, (sat_lat, sat_lon), r_sat_ecef, v_sat_ecef = satellite_heading(tle1, tle2, otime)

roll_actual, pitch_actual = compute_roll_pitch(r_sat_ecef, v_sat_ecef, center_lat, center_lon)
roll_target, pitch_target = compute_roll_pitch(r_sat_ecef, v_sat_ecef, target_lat, target_lon)

along, across, distance = along_across(
    center_lat, center_lon,
    target_lat, target_lon,
    sat_heading_deg
)

# print(f"총 거리: {distance/1000:.2f} km")
# print(f"Along-track 차이: {along/1000:.2f} km")
# print(f"Across-track 차이: {across/1000:.2f} km")
# print(f"Roll Target: {roll_target:.2f}")
# print(f"Roll Actual: {roll_actual:.2f}")
# print(f"Pitch Target: {pitch_target:.2f}")
# print(f"Pitch Actual: {pitch_actual:.2f}")
print(f"{along/1000:.2f} {across/1000:.2f}")
