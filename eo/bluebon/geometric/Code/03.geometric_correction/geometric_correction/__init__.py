"""
Geometric Correction Pipeline

위성영상 기하보정 파이프라인 패키지
"""

__version__ = '2.0.0'
__author__ = 'AI Assistant'

# 주요 클래스 및 함수 임포트
from .exceptions import (
    GeometricCorrectionError,
    ImageLoadError,
    CRSError,
    MatchingError,
    GCPError,
    ModelError,
    ConfigError
)

from .models.rpc import RPCModel, RPCGenerator

from .config.config_manager import (
    ConfigManager,
    PipelineConfig,
    load_config
)

__all__ = [
    # 버전 정보
    '__version__',
    '__author__',
    
    # 예외 클래스
    'GeometricCorrectionError',
    'ImageLoadError',
    'CRSError',
    'MatchingError',
    'GCPError',
    'ModelError',
    'ConfigError',
    
    # 모델 클래스
    'RPCModel',
    'RPCGenerator',
    
    # 설정 관리
    'ConfigManager',
    'PipelineConfig',
    'load_config',
]

