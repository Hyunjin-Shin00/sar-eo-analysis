import os
"""
Global Fishing Watch - AIS Vessel Presence GeoTIFF 다운로드
해역: Arctic Sea, Atlantic NE/NW, Pacific NE/NW
기간: 2012-01 ~ 2026-04 (매월 15일)
공간 해상도: LOW (0.1°)
시간 해상도: DAILY
포맷: TIF (GeoTIFF)

실행:
    python3 gfw_download_date_final.py
"""

import requests
import zipfile
import json
import sys
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
ACCESS_TOKEN = os.environ.get("GFW_API_TOKEN", "")

SAVE_BASE = Path(r"<DATA_ROOT>\14_NSR\GFW\data")

REPORT_URL = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"

# ─────────────────────────────────────────────
# 해역 정의 (GeoJSON Polygon)
# ─────────────────────────────────────────────
REGIONS = {
    "arctic": {
        "name": "Arctic Sea",
        "geojson": {
            "type": "Polygon",
            "coordinates": [[
                [-180.0, 65.0], [-90.0, 65.0], [0.0, 65.0],
                [90.0, 65.0], [180.0, 65.0], [180.0, 90.0],
                [90.0, 90.0], [0.0, 90.0], [-90.0, 90.0],
                [-180.0, 90.0], [-180.0, 65.0],
            ]]
        }
    },
    "atlantic_ne": {
        "name": "Atlantic, Northeast",
        "geojson": {
            "type": "Polygon",
            "coordinates": [[
                [-42.0, 30.0], [0.0, 30.0], [30.0, 30.0],
                [30.0, 65.0], [0.0, 65.0], [-42.0, 65.0],
                [-42.0, 30.0],
            ]]
        }
    },
    "atlantic_nw": {
        "name": "Atlantic, Northwest",
        "geojson": {
            "type": "Polygon",
            "coordinates": [[
                [-80.0, 30.0], [-42.0, 30.0], [-42.0, 65.0],
                [-80.0, 65.0], [-80.0, 30.0],
            ]]
        }
    },
    "pacific_ne": {
        "name": "Pacific, Northeast",
        "geojson": {
            "type": "Polygon",
            "coordinates": [[
                [-180.0, 30.0], [-100.0, 30.0], [-100.0, 65.0],
                [-180.0, 65.0], [-180.0, 30.0],
            ]]
        }
    },
    "pacific_nw": {
        "name": "Pacific, Northwest",
        "geojson": {
            "type": "Polygon",
            "coordinates": [[
                [100.0, 30.0], [180.0, 30.0], [180.0, 65.0],
                [100.0, 65.0], [100.0, 30.0],
            ]]
        }
    },
}

# ─────────────────────────────────────────────
# 날짜 범위 생성 (매월 15일 하루치)
# ─────────────────────────────────────────────
def generate_months(start_str="2012-01", end_str="2026-04"):
    start = datetime.strptime(start_str, "%Y-%m")
    end = datetime.strptime(end_str, "%Y-%m")
    months = []
    current = start
    while current <= end:
        date_from = current.strftime("%Y-%m-15")
        date_to = current.strftime("%Y-%m-16")
        tag = current.strftime("%Y-%m")
        months.append((date_from, date_to, tag))
        current += relativedelta(months=1)
    return months

# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────
HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

def save_and_extract(response, region_key, date_tag):
    save_dir = SAVE_BASE / region_key
    save_dir.mkdir(parents=True, exist_ok=True)

    zip_path = save_dir / f"presence_{region_key}_{date_tag}.zip"
    print(f"    ZIP 저장 -> {zip_path}")
    with open(zip_path, "wb") as f:
        f.write(response.content)
    print(f"    저장 완료: {zip_path.stat().st_size / 1024**2:.2f} MB")

    extract_dir = save_dir / f"presence_{region_key}_{date_tag}"
    extract_dir.mkdir(exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
        names = zf.namelist()

    for name in names:
        fpath = extract_dir / name
        fsize = fpath.stat().st_size / 1024**2 if fpath.is_file() else 0
        print(f"      - {name}  ({fsize:.2f} MB)")

def request_and_download(region_key, region_info, date_from, date_to, date_tag):
    geojson = region_info["geojson"]
    region_name = region_info["name"]

    # 이미 다운로드된 파일이 있으면 스킵
    check_dir = SAVE_BASE / region_key / f"presence_{region_key}_{date_tag}"
    if check_dir.exists() and any(check_dir.iterdir()):
        print(f"  [SKIP] {region_name} {date_tag} - 이미 존재")
        return

    params = {
        "datasets[0]": "public-global-presence:latest",
        "date-range": f"{date_from},{date_to}",
        "format": "TIF",
        "spatial-resolution": "LOW",
        "temporal-resolution": "DAILY",
        "spatial-aggregation": "false",
    }

    print(f"  [요청] {region_name} | {date_tag} (15일)")

    resp = requests.post(
        REPORT_URL,
        params=params,
        headers=HEADERS,
        json={"geojson": geojson},
        timeout=300,
    )

    if resp.status_code != 200:
        # 데이터가 없는 해역/월은 스킵
        if resp.status_code == 422:
            print(f"    [SKIP] 데이터 없음 (Empty data)")
            return
        print(f"    [오류 {resp.status_code}]")
        try:
            print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
        except Exception:
            print(resp.text[:500])
        sys.exit(1)

    ct = resp.headers.get("Content-Type", "")
    if "application/zip" not in ct and "image/tiff" not in ct and "application/octet-stream" not in ct:
        print(f"    [오류] 예상치 못한 응답 Content-Type: {ct}")
        print(resp.text[:500])
        sys.exit(1)

    save_and_extract(resp, region_key, date_tag)

# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    months = generate_months("2012-01", "2026-04")
    region_keys = list(REGIONS.keys())

    total = len(months) * len(region_keys)
    print("=" * 60)
    print("GFW AIS Vessel Presence 일괄 다운로드")
    print(f"  해역: {', '.join(r['name'] for r in REGIONS.values())}")
    print(f"  기간: 2012-01 ~ 2026-04 ({len(months)}개월, 매월 15일)")
    print(f"  총 다운로드: {total}건")
    print(f"  해상도: LOW (0.1도)")
    print(f"  저장 경로: {SAVE_BASE}")
    print("=" * 60)

    count = 0
    for date_from, date_to, date_tag in months:
        for region_key in region_keys:
            count += 1
            print(f"\n[{count}/{total}] {REGIONS[region_key]['name']} - {date_tag} (15일)")
            request_and_download(region_key, REGIONS[region_key], date_from, date_to, date_tag)

    print("\n" + "=" * 60)
    print(f"완료! 총 {total}건 처리")
    print("=" * 60)

if __name__ == "__main__":
    main()
