"""
설정 관리 시스템

YAML 파일 기반의 설정 관리 클래스를 제공합니다.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

from ..exceptions import (
    ConfigError,
    ConfigFileNotFoundError,
    ConfigValidationError
)


@dataclass
class PathConfig:
    """파일 경로 설정"""
    reference: str = ""
    target: str = ""
    dem: str = ""
    output: str = ""


@dataclass
class MatchingConfig:
    """매칭 설정"""
    initial_resolution: int = 4
    method: str = "superpoint"
    superpoint_max_keypoints: int = 4096
    stage2_resolution: int = 4
    stage3_resolution: int = 2
    stage4_resolution: int = 1
    patch_size: int = 49


@dataclass
class RANSACConfig:
    """RANSAC 필터링 설정"""
    threshold: float = 5.0
    max_iterations: int = 5000
    confidence: float = 0.99


@dataclass
class GridFilteringConfig:
    """GRID 필터링 설정"""
    enabled: bool = True
    grid_size: int = 5
    min_points_per_grid: int = 1
    max_points_per_grid: int = 5
    min_occupied_grids: int = 16


@dataclass
class RegionConfig:
    """영역 추출 설정"""
    buffer_factor: float = 1.2


@dataclass
class TargetMetadataConfig:
    """TARGET 영상 메타데이터"""
    center_lat: float = 37.5151
    center_lon: float = 127.0724
    resolution: float = 4.8


@dataclass
class CorrectionConfig:
    """기하보정 방법 설정"""
    initial_method: str = "RPC"


@dataclass
class RPCConfig:
    """RPC 생성 설정"""
    min_gcps: int = 20
    use_ransac: bool = True


@dataclass
class DeviceConfig:
    """GPU/CPU 설정"""
    force_gpu: bool = False
    gpu_memory_limit: Optional[int] = None


@dataclass
class VisualizationConfig:
    """시각화 설정"""
    enabled: bool = True
    max_points: int = 100


@dataclass
class OutputConfig:
    """출력 설정"""
    save_intermediate: bool = True
    save_visualizations: bool = True


@dataclass
class LoggingConfig:
    """로깅 설정"""
    level: str = "INFO"
    save_to_file: bool = True


@dataclass
class PipelineConfig:
    """전체 파이프라인 설정"""
    paths: PathConfig = field(default_factory=PathConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    ransac: RANSACConfig = field(default_factory=RANSACConfig)
    grid_filtering: GridFilteringConfig = field(default_factory=GridFilteringConfig)
    region: RegionConfig = field(default_factory=RegionConfig)
    target_metadata: TargetMetadataConfig = field(default_factory=TargetMetadataConfig)
    correction: CorrectionConfig = field(default_factory=CorrectionConfig)
    rpc: RPCConfig = field(default_factory=RPCConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    visualization: VisualizationConfig = field(default_factory=VisualizationConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


class ConfigManager:
    """설정 관리 클래스"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        설정 관리자 초기화
        
        Args:
            config_path: 설정 파일 경로 (None이면 기본 설정 사용)
        """
        self.config_path = config_path
        self.config = PipelineConfig()
        
        if config_path:
            self.load_from_yaml(config_path)
    
    def load_from_yaml(self, yaml_path: str) -> None:
        """
        YAML 파일에서 설정을 로드합니다.
        
        Args:
            yaml_path: YAML 파일 경로
            
        Raises:
            ConfigFileNotFoundError: 파일이 존재하지 않을 경우
            ConfigError: YAML 파싱 실패 시
        """
        yaml_path = Path(yaml_path)
        
        if not yaml_path.exists():
            raise ConfigFileNotFoundError(f"설정 파일을 찾을 수 없습니다: {yaml_path}")
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                yaml_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML 파일 파싱 실패: {e}")
        
        # YAML 데이터를 config 객체에 매핑
        self._parse_yaml_data(yaml_data)
        
        # 설정 유효성 검사
        self.validate()
    
    def _parse_yaml_data(self, data: Dict[str, Any]) -> None:
        """YAML 데이터를 파싱하여 config 객체에 할당"""
        
        # Paths
        if 'paths' in data:
            paths = data['paths']
            self.config.paths = PathConfig(
                reference=paths.get('reference', ''),
                target=paths.get('target', ''),
                dem=paths.get('dem', ''),
                output=paths.get('output', '')
            )
        
        # Matching
        if 'matching' in data:
            matching = data['matching']
            superpoint = matching.get('superpoint', {})
            stages = matching.get('stages', {})
            
            self.config.matching = MatchingConfig(
                initial_resolution=matching.get('initial_resolution', 4),
                method=matching.get('method', 'superpoint'),
                superpoint_max_keypoints=superpoint.get('max_keypoints', 4096),
                stage2_resolution=stages.get('stage2_resolution', 4),
                stage3_resolution=stages.get('stage3_resolution', 2),
                stage4_resolution=stages.get('stage4_resolution', 1),
                patch_size=matching.get('patch_size', 49)
            )
        
        # RANSAC
        if 'ransac' in data:
            ransac = data['ransac']
            self.config.ransac = RANSACConfig(
                threshold=ransac.get('threshold', 5.0),
                max_iterations=ransac.get('max_iterations', 5000),
                confidence=ransac.get('confidence', 0.99)
            )
        
        # Grid Filtering
        if 'grid_filtering' in data:
            grid = data['grid_filtering']
            self.config.grid_filtering = GridFilteringConfig(
                enabled=grid.get('enabled', True),
                grid_size=grid.get('grid_size', 5),
                min_points_per_grid=grid.get('min_points_per_grid', 1),
                max_points_per_grid=grid.get('max_points_per_grid', 5),
                min_occupied_grids=grid.get('min_occupied_grids', 16)
            )
        
        # Region
        if 'region' in data:
            self.config.region = RegionConfig(
                buffer_factor=data['region'].get('buffer_factor', 1.2)
            )
        
        # Target Metadata
        if 'target_metadata' in data:
            meta = data['target_metadata']
            self.config.target_metadata = TargetMetadataConfig(
                center_lat=meta.get('center_lat', 37.5151),
                center_lon=meta.get('center_lon', 127.0724),
                resolution=meta.get('resolution', 4.8)
            )
        
        # Correction
        if 'correction' in data:
            self.config.correction = CorrectionConfig(
                initial_method=data['correction'].get('initial_method', 'RPC')
            )
        
        # RPC
        if 'rpc' in data:
            rpc = data['rpc']
            self.config.rpc = RPCConfig(
                min_gcps=rpc.get('min_gcps', 20),
                use_ransac=rpc.get('use_ransac', True)
            )
        
        # Device
        if 'device' in data:
            device = data['device']
            self.config.device = DeviceConfig(
                force_gpu=device.get('force_gpu', False),
                gpu_memory_limit=device.get('gpu_memory_limit', None)
            )
        
        # Visualization
        if 'visualization' in data:
            vis = data['visualization']
            self.config.visualization = VisualizationConfig(
                enabled=vis.get('enabled', True),
                max_points=vis.get('max_points', 100)
            )
        
        # Output
        if 'output' in data:
            output = data['output']
            self.config.output = OutputConfig(
                save_intermediate=output.get('save_intermediate', True),
                save_visualizations=output.get('save_visualizations', True)
            )
        
        # Logging
        if 'logging' in data:
            logging = data['logging']
            self.config.logging = LoggingConfig(
                level=logging.get('level', 'INFO'),
                save_to_file=logging.get('save_to_file', True)
            )
    
    def validate(self) -> None:
        """
        설정 값의 유효성을 검사합니다.
        
        Raises:
            ConfigValidationError: 유효하지 않은 설정 값이 있을 경우
        """
        # 해상도 값 검증
        if self.config.matching.initial_resolution < 1:
            raise ConfigValidationError("initial_resolution은 1 이상이어야 합니다")
        
        # RANSAC 신뢰도 검증
        if not 0 < self.config.ransac.confidence <= 1:
            raise ConfigValidationError("RANSAC confidence는 0과 1 사이여야 합니다")
        
        # 그리드 크기 검증
        if self.config.grid_filtering.grid_size < 1:
            raise ConfigValidationError("grid_size는 1 이상이어야 합니다")
        
        # 버퍼 배율 검증
        if self.config.region.buffer_factor < 1.0:
            raise ConfigValidationError("buffer_factor는 1.0 이상이어야 합니다")
        
        # 보정 방법 검증
        valid_methods = ["TPS", "RPC"]
        if self.config.correction.initial_method not in valid_methods:
            raise ConfigValidationError(
                f"initial_method는 {valid_methods} 중 하나여야 합니다"
            )
        
        # 로깅 레벨 검증
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.config.logging.level not in valid_levels:
            raise ConfigValidationError(
                f"logging level은 {valid_levels} 중 하나여야 합니다"
            )
    
    def save_to_yaml(self, yaml_path: str) -> None:
        """
        현재 설정을 YAML 파일로 저장합니다.
        
        Args:
            yaml_path: 저장할 YAML 파일 경로
        """
        yaml_data = {
            'paths': {
                'reference': self.config.paths.reference,
                'target': self.config.paths.target,
                'dem': self.config.paths.dem,
                'output': self.config.paths.output
            },
            'matching': {
                'initial_resolution': self.config.matching.initial_resolution,
                'method': self.config.matching.method,
                'superpoint': {
                    'max_keypoints': self.config.matching.superpoint_max_keypoints
                },
                'stages': {
                    'stage2_resolution': self.config.matching.stage2_resolution,
                    'stage3_resolution': self.config.matching.stage3_resolution,
                    'stage4_resolution': self.config.matching.stage4_resolution
                },
                'patch_size': self.config.matching.patch_size
            },
            'ransac': {
                'threshold': self.config.ransac.threshold,
                'max_iterations': self.config.ransac.max_iterations,
                'confidence': self.config.ransac.confidence
            },
            'grid_filtering': {
                'enabled': self.config.grid_filtering.enabled,
                'grid_size': self.config.grid_filtering.grid_size,
                'min_points_per_grid': self.config.grid_filtering.min_points_per_grid,
                'max_points_per_grid': self.config.grid_filtering.max_points_per_grid,
                'min_occupied_grids': self.config.grid_filtering.min_occupied_grids
            },
            'region': {
                'buffer_factor': self.config.region.buffer_factor
            },
            'target_metadata': {
                'center_lat': self.config.target_metadata.center_lat,
                'center_lon': self.config.target_metadata.center_lon,
                'resolution': self.config.target_metadata.resolution
            },
            'correction': {
                'initial_method': self.config.correction.initial_method
            },
            'rpc': {
                'min_gcps': self.config.rpc.min_gcps,
                'use_ransac': self.config.rpc.use_ransac
            },
            'device': {
                'force_gpu': self.config.device.force_gpu,
                'gpu_memory_limit': self.config.device.gpu_memory_limit
            },
            'visualization': {
                'enabled': self.config.visualization.enabled,
                'max_points': self.config.visualization.max_points
            },
            'output': {
                'save_intermediate': self.config.output.save_intermediate,
                'save_visualizations': self.config.output.save_visualizations
            },
            'logging': {
                'level': self.config.logging.level,
                'save_to_file': self.config.logging.save_to_file
            }
        }
        
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        점(.) 표기법으로 설정 값을 가져옵니다.
        
        Args:
            key: 설정 키 (예: "matching.initial_resolution")
            default: 기본값
            
        Returns:
            설정 값
        """
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = getattr(value, k)
            return value
        except AttributeError:
            return default
    
    def set(self, key: str, value: Any) -> None:
        """
        점(.) 표기법으로 설정 값을 변경합니다.
        
        Args:
            key: 설정 키 (예: "matching.initial_resolution")
            value: 설정할 값
        """
        keys = key.split('.')
        obj = self.config
        
        # 마지막 키 전까지 탐색
        for k in keys[:-1]:
            obj = getattr(obj, k)
        
        # 마지막 키에 값 할당
        setattr(obj, keys[-1], value)
        
        # 재검증
        self.validate()


def load_config(config_path: Optional[str] = None) -> PipelineConfig:
    """
    설정을 로드하는 편의 함수
    
    Args:
        config_path: 설정 파일 경로 (None이면 기본 설정 사용)
        
    Returns:
        PipelineConfig 객체
    """
    manager = ConfigManager(config_path)
    return manager.config

