#!/usr/bin/env python3
"""
BlueBON Pipeline Configuration
===============================
PipelineConfig 데이터클래스 및 파일명/출력 관련 유틸리티 함수.
"""

import os
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class PipelineConfig:
    """Pipeline configuration dataclass"""
    input_path: str
    level: str
    date: str           # yyyymmdd
    time: str           # HHMMSS
    band_count: int
    center_lat: float
    center_lon: float
    num_segments: int   # 1, 2, 3
    save_intermediate: bool
    target_resolution: float = 4.8
    gcp_chips_dir: Optional[str] = None
    gcp_chip_resolution: float = 1.2


def parse_filename(filename: str) -> Optional[dict]:
    """Parse filename: bb_{level}_{yyyymmdd}_{HHMMSS}_{band}.tiff"""
    basename = os.path.basename(filename)
    pattern = r'^bb_([a-zA-Z0-9]+)_(\d{8})_(\d{6})_(\d+)band\.tiff?$'
    match = re.match(pattern, basename, re.IGNORECASE)

    if match:
        return {
            'level':      match.group(1),
            'date':       match.group(2),
            'time':       match.group(3),
            'band_count': int(match.group(4)),
        }

    if basename.lower().endswith(('.tiff', '.tif')):
        return {'level': 'unknown', 'date': 'unknown',
                'time': 'unknown', 'band_count': 0}

    return None


def get_rgb_band_indices(band_count: int) -> list:
    """Return RGB band indices (1-based).
    4-band -> [1,2,3]   8-band -> [2,3,4]
    """
    return [2, 3, 4] if band_count == 8 else [1, 2, 3]


def get_output_folder_name(config: PipelineConfig) -> str:
    return f"bb_{config.level}_{config.date}_{config.time}_{config.band_count}band"


def get_output_filename(config: PipelineConfig, location: str = None) -> str:
    base = f"bb_l1c_{config.date}_{config.time}_{config.band_count}band"
    return f"{base}_{location.lower()}.tiff" if location else f"{base}.tiff"


def get_segment_names(num_segments: int) -> list:
    return {1: ["Full"], 2: ["Upper", "Lower"],
            3: ["Top", "Center", "Bottom"]}.get(num_segments, [])
