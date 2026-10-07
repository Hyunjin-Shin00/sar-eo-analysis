#!/usr/bin/env python3
"""
좌표 계산 스크립트
Center 좌표를 기준으로 Top과 Bottom 좌표를 계산합니다.

규칙:
- Top: 위도 +0.15, 경도 +0.06
- Bottom: 위도 -0.15, 경도 -0.06
"""

import json
from pathlib import Path

# 배치 설정 파일 읽기
config_path = Path("/Users/kyle_kim/Downloads/geometric_correction/batch_config.json")
with open(config_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 데이터셋을 region별로 그룹화
regions = {}
for key, dataset in data.items():
    name = dataset['name']
    # region 이름 추출 (예: "01_Grand_Canyon(usa) 2025-11-02_center" -> "01_Grand_Canyon(usa) 2025-11-02")
    if '_center' in name:
        region_key = name.replace('_center', '')
        regions[region_key] = {
            'center': {
                'lat': dataset['target_center_lat'],
                'lon': dataset['target_center_lon'],
                'name': name
            }
        }
    elif '_top' in name:
        region_key = name.replace('_top', '')
        if region_key not in regions:
            regions[region_key] = {}
        regions[region_key]['top'] = {
            'lat': dataset['target_center_lat'],
            'lon': dataset['target_center_lon'],
            'name': name
        }
    elif '_bottom' in name:
        region_key = name.replace('_bottom', '')
        if region_key not in regions:
            regions[region_key] = {}
        regions[region_key]['bottom'] = {
            'lat': dataset['target_center_lat'],
            'lon': dataset['target_center_lon'],
            'name': name
        }

# Center 좌표를 기준으로 Top과 Bottom 계산
calculated_coords = {}
updated_data = data.copy()

print("="*80)
print("좌표 계산 및 업데이트")
print("="*80)

for region_key, coords in sorted(regions.items()):
    if 'center' not in coords:
        print(f"⚠️ {region_key}: center 좌표가 없습니다. 건너뜁니다.")
        continue
    
    center_lat = coords['center']['lat']
    center_lon = coords['center']['lon']
    
    # 계산된 좌표
    top_lat = center_lat + 0.15
    top_lon = center_lon + 0.06
    bottom_lat = center_lat - 0.15
    bottom_lon = center_lon - 0.06
    
    calculated_coords[region_key] = {
        'center': {'lat': center_lat, 'lon': center_lon},
        'top': {'lat': top_lat, 'lon': top_lon},
        'bottom': {'lat': bottom_lat, 'lon': bottom_lon}
    }
    
    print(f"\n{region_key}:")
    print(f"  Center: 위도 {center_lat:.6f}, 경도 {center_lon:.6f}")
    print(f"  Top:    위도 {top_lat:.6f}, 경도 {top_lon:.6f} (+0.15, +0.06)")
    print(f"  Bottom: 위도 {bottom_lat:.6f}, 경도 {bottom_lon:.6f} (-0.15, -0.06)")
    
    # batch_config.json 업데이트
    for key, dataset in updated_data.items():
        name = dataset['name']
        if region_key in name:
            if '_top' in name:
                dataset['target_center_lat'] = round(top_lat, 6)
                dataset['target_center_lon'] = round(top_lon, 6)
            elif '_bottom' in name:
                dataset['target_center_lat'] = round(bottom_lat, 6)
                dataset['target_center_lon'] = round(bottom_lon, 6)
            # center는 그대로 유지

# batch_config.json 저장
with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(updated_data, f, indent=2, ensure_ascii=False)

print(f"\n✅ batch_config.json 업데이트 완료: {config_path}")

# CSV 파일 생성 (QGIS용)
csv_path = config_path.parent / "qgis_coordinates_updated.csv"
with open(csv_path, 'w', encoding='utf-8') as f:
    f.write("name,region,type,latitude,longitude\n")
    for region_key, coords in sorted(calculated_coords.items()):
        # Region 이름 추출 (숫자 접두사 제거)
        region_name = region_key.split(' ', 1)[0] if ' ' in region_key else region_key
        
        f.write(f"{region_key},Top,{coords['top']['lat']:.6f},{coords['top']['lon']:.6f}\n")
        f.write(f"{region_key},Center,{coords['center']['lat']:.6f},{coords['center']['lon']:.6f}\n")
        f.write(f"{region_key},Bottom,{coords['bottom']['lat']:.6f},{coords['bottom']['lon']:.6f}\n")

print(f"✅ QGIS CSV 파일 생성 완료: {csv_path}")

# GeoJSON 파일 생성 (QGIS용)
geojson_path = config_path.parent / "qgis_coordinates_updated.geojson"
features = []
for region_key, coords in sorted(calculated_coords.items()):
    # Top
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [coords['top']['lon'], coords['top']['lat']]},
        "properties": {"name": f"{region_key}_top", "region": region_key, "type": "Top"}
    })
    # Center
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [coords['center']['lon'], coords['center']['lat']]},
        "properties": {"name": f"{region_key}_center", "region": region_key, "type": "Center"}
    })
    # Bottom
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [coords['bottom']['lon'], coords['bottom']['lat']]},
        "properties": {"name": f"{region_key}_bottom", "region": region_key, "type": "Bottom"}
    })

geojson = {
    "type": "FeatureCollection",
    "features": features
}

with open(geojson_path, 'w', encoding='utf-8') as f:
    json.dump(geojson, f, indent=2, ensure_ascii=False)

print(f"✅ QGIS GeoJSON 파일 생성 완료: {geojson_path}")

# 표 형식으로 출력 (마크다운 테이블)
print("\n" + "="*80)
print("계산된 좌표 표")
print("="*80)
print("\n| 지역 | Top (위도, 경도) | Center (위도, 경도) | Bottom (위도, 경도) |")
print("|------|------------------|---------------------|---------------------|")
for region_key, coords in sorted(calculated_coords.items()):
    region_short = region_key.split('(')[0].strip()
    print(f"| {region_short} | {coords['top']['lat']:.4f}, {coords['top']['lon']:.4f} | "
          f"{coords['center']['lat']:.4f}, {coords['center']['lon']:.4f} | "
          f"{coords['bottom']['lat']:.4f}, {coords['bottom']['lon']:.4f} |")

print("\n✅ 모든 작업 완료!")

