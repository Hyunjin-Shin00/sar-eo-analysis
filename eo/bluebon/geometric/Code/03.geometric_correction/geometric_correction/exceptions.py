"""
커스텀 예외 클래스 정의

기하보정 파이프라인의 다양한 에러 상황을 명확하게 처리하기 위한
커스텀 예외 클래스들을 정의합니다.
"""


class GeometricCorrectionError(Exception):
    """기하보정 관련 기본 예외 클래스"""
    pass


class FileError(GeometricCorrectionError):
    """파일 관련 에러의 기본 클래스"""
    pass


class FileNotFoundError(FileError):
    """파일을 찾을 수 없을 때 발생하는 예외"""
    pass


class FileValidationError(FileError):
    """파일 유효성 검사 실패 시 발생하는 예외"""
    pass


class ImageError(GeometricCorrectionError):
    """이미지 처리 관련 에러의 기본 클래스"""
    pass


class ImageLoadError(ImageError):
    """이미지 로딩 실패 시 발생하는 예외"""
    pass


class ImageProcessingError(ImageError):
    """이미지 처리 중 발생하는 예외"""
    pass


class CRSError(GeometricCorrectionError):
    """좌표계 관련 에러"""
    pass


class CRSMismatchError(CRSError):
    """좌표계 불일치 시 발생하는 예외"""
    pass


class CRSTransformError(CRSError):
    """좌표계 변환 실패 시 발생하는 예외"""
    pass


class MatchingError(GeometricCorrectionError):
    """특징점 매칭 관련 에러"""
    pass


class InsufficientMatchesError(MatchingError):
    """매칭점이 부족할 때 발생하는 예외"""
    pass


class MatchingFailedError(MatchingError):
    """매칭 프로세스 자체가 실패했을 때 발생하는 예외"""
    pass


class GCPError(GeometricCorrectionError):
    """GCP(Ground Control Points) 관련 에러"""
    pass


class InsufficientGCPsError(GCPError):
    """GCP 개수가 부족할 때 발생하는 예외"""
    pass


class GCPGenerationError(GCPError):
    """GCP 생성 실패 시 발생하는 예외"""
    pass


class ModelError(GeometricCorrectionError):
    """모델(RPC/TPS) 관련 에러"""
    pass


class RPCGenerationError(ModelError):
    """RPC 모델 생성 실패 시 발생하는 예외"""
    pass


class TPSTransformError(ModelError):
    """TPS 변환 실패 시 발생하는 예외"""
    pass


class WarpingError(GeometricCorrectionError):
    """영상 워핑 관련 에러"""
    pass


class WarpingFailedError(WarpingError):
    """워핑 프로세스 실패 시 발생하는 예외"""
    pass


class ConfigError(GeometricCorrectionError):
    """설정 관련 에러"""
    pass


class ConfigFileNotFoundError(ConfigError):
    """설정 파일을 찾을 수 없을 때 발생하는 예외"""
    pass


class ConfigValidationError(ConfigError):
    """설정 값 유효성 검사 실패 시 발생하는 예외"""
    pass


class ValidationError(GeometricCorrectionError):
    """데이터 유효성 검사 관련 에러"""
    pass


class MetadataError(GeometricCorrectionError):
    """메타데이터 관련 에러"""
    pass


class MetadataMissingError(MetadataError):
    """필수 메타데이터가 누락되었을 때 발생하는 예외"""
    pass

