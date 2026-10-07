# ============================================================
# BlueBON 기하보정 파이프라인 Docker 이미지
# Base: CUDA 12.4 + Ubuntu 22.04
# ============================================================
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

# ---------- 시스템 기본 설정 ----------
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Seoul
ENV LANG=C.UTF-8

# 시스템 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget curl git \
        build-essential make \
        libglib2.0-0 libsm6 libxext6 libxrender1 \
        libgomp1 libgl1 \
        libtiff-dev zlib1g-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------- Miniforge 설치 (conda + mamba) ----------
RUN wget -q https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh \
        -O /tmp/miniforge.sh \
    && bash /tmp/miniforge.sh -b -p /opt/conda \
    && rm /tmp/miniforge.sh

ENV PATH=/opt/conda/bin:$PATH
RUN conda init bash && conda config --set always_yes true

# ---------- conda 환경 생성 ----------
COPY docker/environment.yml /tmp/environment.yml
RUN CONDA_OVERRIDE_CUDA=13.2 mamba env create -f /tmp/environment.yml \
    && conda clean -afy

# conda 환경 활성화를 모든 RUN에 적용
SHELL ["conda", "run", "-n", "geocorrect", "/bin/bash", "-c"]

# ---------- 코드 복사 ----------
WORKDIR /app
COPY Code/ /app/Code/
COPY RoMaV2/ /app/RoMaV2/

# ---------- 로컬 패키지 설치 ----------
# RoMaV2
RUN pip install -e /app/RoMaV2

# lightglue (Code/lightglue 디렉토리가 패키지 역할)
RUN pip install -e /app/Code/lightglue || true

# ---------- 환경 변수 ----------
ENV PYTHONPATH=/app/Code:/app/Code/03.geometric_correction
ENV TORCH_HOME=/app/.cache/torch
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
# Flash SDPA 비활성화 (triton cuda.h 불필요)
ENV TORCH_SDPA_FLASH_ATTENTION=0

# ---------- 모델 가중치 사전 다운로드 ----------
# (빌드 시 인터넷 필요 — 오프라인 환경이면 아래 COPY 방식 사용)
RUN mkdir -p /app/.cache/torch/hub/checkpoints
COPY .cache/torch/hub/ /app/.cache/torch/hub/

# ---------- 인증키 마운트 포인트 ----------
# Google Earth Engine 인증키는 런타임에 마운트
# docker run -v /호스트/key.json:/app/Code/auth/ee-service-account-key.json
RUN mkdir -p /app/Code/auth

# ---------- 데이터 마운트 포인트 ----------
RUN mkdir -p /data

# ---------- 진입점 ----------
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
