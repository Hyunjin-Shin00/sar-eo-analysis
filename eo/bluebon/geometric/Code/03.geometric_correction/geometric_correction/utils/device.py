"""
Device Selection Utility

PyTorch 디바이스 선택 유틸리티 함수
- CUDA (NVIDIA GPU) 지원
- MPS (Apple Silicon GPU) 지원 (현재 비활성화 - 정밀도 문제)
- CPU fallback (안정성 우선)

주의: MPS는 정밀도 문제로 인해 현재 비활성화되어 있습니다.
안정적인 기하보정 결과를 위해 CPU를 사용합니다.
"""

import torch


def get_device(force_device: str = None) -> str:
    """
    사용 가능한 최적의 PyTorch 디바이스를 자동으로 선택합니다.
    
    Args:
        force_device (str, optional): 강제로 사용할 디바이스 ('cuda', 'mps', 'cpu')
        
    Returns:
        str: 선택된 디바이스 문자열 ('cuda', 'mps', 또는 'cpu')
    
    Priority:
        1. CUDA (NVIDIA GPU) - 가장 빠름
        2. MPS (Apple Silicon GPU) - Apple M1/M2/M3/M4 칩에서 사용 가능 (현재 비활성화)
        3. CPU - fallback (안정성 우선)
    
    Note:
        MPS는 현재 정밀도 문제로 인해 비활성화되어 있습니다.
        안정적인 결과를 위해 CPU를 사용합니다.
    """
    if force_device:
        return force_device.lower()
    
    # CUDA 우선 (NVIDIA GPU)
    if torch.cuda.is_available():
        return "cuda"
    
    # MPS 비활성화 - 정밀도 문제로 인해 CPU 사용
    # TODO: MPS 정밀도 문제 해결 후 다시 활성화
    # if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    #     return "mps"
    
    # CPU fallback (안정성 우선)
    return "cpu"


def get_device_info() -> dict:
    """
    현재 사용 가능한 디바이스 정보를 반환합니다.
    
    Returns:
        dict: 디바이스 정보 딕셔너리
            - device: 선택된 디바이스
            - cuda_available: CUDA 사용 가능 여부
            - mps_available: MPS 사용 가능 여부
            - cuda_device_count: CUDA 디바이스 개수 (CUDA 사용 시)
    """
    device = get_device()
    
    info = {
        "device": device,
        "cuda_available": torch.cuda.is_available(),
        "mps_available": hasattr(torch.backends, 'mps') and torch.backends.mps.is_available() if hasattr(torch.backends, 'mps') else False,
        "cuda_device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
    }
    
    if device == "cuda" and torch.cuda.is_available():
        info["cuda_device_name"] = torch.cuda.get_device_name(0)
    
    return info

