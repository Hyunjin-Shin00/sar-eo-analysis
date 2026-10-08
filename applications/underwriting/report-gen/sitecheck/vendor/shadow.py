"""촬영시각·위경도 → 태양 위치(방위각·고도)와 그림자 방향.

야적 판독(단계 2)이 타일 캡션에 넣는 단서다. 「해가 어느 쪽에 있고 5 m 높이 물체가
몇 px 짜리 그림자를 드리우는가」를 알려 주면 판독 모델이 지붕과 지면 적치물을,
건물과 팔레트 더미를 그림자 길이로 가른다.

    그림자 길이 L 인 물체의 높이 h = L x tan(태양고도)

촬영시각은 장면 tif 파일명에서 온다(`20260618_062345_ssc8...` = UTC).
UTC 로 읽는 것이 맞다는 것은 계산 방위와 장면 실측 방위의 대조로 확인했다 —
4장면 모두 계산 262~265°, 실측 270~300°. 현지시로 읽으면 100° 넘게 틀어진다.

원본은 `parcelscan` 이고, 이 폴더만 떼어가도 돌도록 필요한 부분만 옮겨 담았다.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone


def scene_datetime(meta) -> datetime | None:
    """meta.json 의 src_tif 파일명에서 촬영시각(UTC)을 뽑는다.

    Planet/SkySat 파일명 규약은 `YYYYMMDD_HHMMSS_<sat>_...` 이고 시각은 UTC 다.
    """
    src = str(meta.get("src_tif") or "")
    m = re.search(r"(20\d{6})_(\d{6})", src)
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
        tzinfo=timezone.utc)


def sun_position(dt_utc, lat, lon):
    """→ (방위각°, 고도°). 방위각은 북=0, 동=90(시계방향).

    NOAA 저정밀 알고리즘. 1950~2050 년에서 오차 0.01° 수준이라 그림자 계산에는 충분하다.
    """
    jd = (dt_utc - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds() / 86400.0
    L = math.radians((280.460 + 0.9856474 * jd) % 360.0)
    g = math.radians((357.528 + 0.9856003 * jd) % 360.0)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439 - 0.0000004 * jd)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = (18.697374558 + 24.06570982441908 * jd) % 24.0
    ha = math.radians(((gmst + lon / 15.0) * 15.0 - math.degrees(ra) + 180.0) % 360.0 - 180.0)
    phi = math.radians(lat)
    elev = math.asin(math.sin(phi) * math.sin(dec)
                     + math.cos(phi) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.sin(ha) * math.cos(dec),
                    (math.sin(dec) - math.sin(phi) * math.sin(elev)) / max(math.cos(phi), 1e-9))
    return math.degrees(az) % 360.0, math.degrees(elev)


def shadow_unit(sun_az_deg):
    """태양 방위각 → 영상 픽셀에서 그림자가 뻗는 단위벡터 (dx, dy).

    영상은 북쪽이 위(UTM 정사)라 북 = -y 다. 그림자는 태양 반대쪽으로 진다.
    """
    a = math.radians((sun_az_deg + 180.0) % 360.0)
    return math.sin(a), -math.cos(a)


def scene_sun(meta, verbose=True):
    """장면 meta → (촬영시각, 방위각, 고도, 그림자 단위벡터) 또는 None."""
    dt = scene_datetime(meta)
    if dt is None:
        return None
    bb = meta.get("bbox")
    lon = (bb[0] + bb[2]) / 2
    lat = (bb[1] + bb[3]) / 2
    az, el = sun_position(dt, lat, lon)
    if verbose:
        loc = dt.astimezone(timezone(__import__("datetime").timedelta(hours=9)))
        print(f"  태양 {loc:%Y-%m-%d %H:%M} KST · 방위 {az:.1f}° · 고도 {el:.1f}°")
    return dt, az, el, shadow_unit(az)
