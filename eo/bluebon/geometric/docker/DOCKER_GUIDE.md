# BlueBON 기하보정 파이프라인 — Docker 배포 가이드


---

## 1. 사전 요구사항

### 공통 (빌드·실행 모두)
| 항목 | 최소 사양 |
|------|----------|
| OS | Ubuntu 20.04 이상 (Linux x86_64) |
| GPU | NVIDIA GPU (VRAM 8GB 이상 권장) |
| NVIDIA 드라이버 | 525 이상 |
| Docker | 20.10 이상 |
| NVIDIA Container Toolkit | 최신 |
| 디스크 여유 공간 | 30GB 이상 |

### NVIDIA Container Toolkit 설치 (미설치 시)
```bash
# Ubuntu 기준
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# 정상 설치 확인
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

---

## 2. 이미지 빌드 (공급사)

> **납품처에 소스코드 없이 이미지만 전달할 경우 이 단계를 수행합니다.**

### 빌드 전 준비
```bash
cd BlueBON_Geometric_Correction_V3

# 실행 권한 부여
chmod +x docker/build.sh docker/run.sh docker/entrypoint.sh
```

### 빌드 실행
```bash
bash docker/build.sh
```

빌드 시간: 약 **20~40분** (인터넷 속도에 따라 상이)  
완료 후 이미지 크기: 약 **15~20GB**

### 빌드 확인
```bash
docker images blubon-geocorrect
docker run --rm --gpus all blubon-geocorrect:latest --help
```

---

## 3. 이미지 전달 방법

### 방법 A: 파일로 저장하여 전달 (오프라인 환경)
```bash
# 이미지 저장 (공급사에서 실행)
docker save blubon-geocorrect:latest | gzip > blubon-geocorrect.tar.gz
# 파일 크기: 약 15~20GB

# 이미지 로드 (납품처에서 실행)
docker load < blubon-geocorrect.tar.gz
```

### 방법 B: Docker Hub / Private Registry 활용
```bash
# 공급사: 이미지 푸시
docker tag blubon-geocorrect:latest your-registry/blubon-geocorrect:latest
docker push your-registry/blubon-geocorrect:latest

# 납품처: 이미지 풀
docker pull your-registry/blubon-geocorrect:latest
docker tag your-registry/blubon-geocorrect:latest blubon-geocorrect:latest
```

---

## 4. 수신측 설치 (납품처)

### 설치 확인 체크리스트
```bash
# 1. Docker 설치 확인
docker --version

# 2. GPU 인식 확인
nvidia-smi

# 3. NVIDIA Container Toolkit 확인
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi

# 4. 이미지 로드 확인 (파일 전달 방식)
docker load < blubon-geocorrect.tar.gz
docker images blubon-geocorrect

# 5. 실행 테스트
docker run --rm --gpus all blubon-geocorrect:latest --help
```

---

## 5. 실행 방법

### 기본 실행
```bash
docker run --rm --gpus all \
  -v /데이터/폴더:/data \
  -v /인증키/ee-service-account-key.json:/app/Code/auth/ee-service-account-key.json:ro \
  blubon-geocorrect:latest \
  --input /data/bb_l1a_20260220_025632_8band.tiff \
  --lat 37.1794 \
  --lon 126.9726
```

### 편의 스크립트 사용
```bash
bash docker/run.sh \
  --input /path/to/bb_l1a_20260220_025632_8band.tiff \
  --lat 37.1794 \
  --lon 126.9726 \
  --intermediate
```

### 전체 옵션
```bash
docker run --rm --gpus all \
  -v /데이터폴더:/data \
  -v /키경로/ee-key.json:/app/Code/auth/ee-service-account-key.json:ro \
  blubon-geocorrect:latest \
  --input /data/파일명.tiff \   # 입력 파일 (필수)
  --lat 37.1794 \               # 중심 위도 (필수)
  --lon 126.9726 \              # 중심 경도 (필수)
  --res 4.8 \                   # 목표 해상도 m (기본: 4.8)
  --segment 3 \                 # 영상 분할 수 1~3 (기본: 3)
  --intermediate                # 중간 결과물 저장 (선택)
```

### 입력 파일명 형식
```
bb_{레벨}_{날짜}_{시간}_{밴드수}band.tiff
예: bb_l1a_20260220_025632_8band.tiff
```

---

## 6. 입출력 구조

### 입력
| 항목 | 설명 |
|------|------|
| TIFF 파일 | BlueBON L1A 다중밴드 영상 |
| Google Earth Engine 인증키 | Sentinel-2 다운로드용 |

### 출력 (입력 파일과 같은 디렉토리에 생성)
```
/데이터폴더/
├── S2_mosaic_*.tif          # Sentinel-2 기준 영상
├── Copernicus_DEM.tif       # DEM
├── Top_Divide_1/            # 세그먼트별 처리 결과
│   └── 07_Final_results/
│       └── bb_l1c_*.tiff   # ✅ 최종 기하보정 결과
└── bb_l1c_*.tiff            # ✅ 최종 모자이크
```

---

## 7. 문제 해결

### GPU를 인식하지 못하는 경우
```bash
# nvidia-container-toolkit 재설치
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### 첫 실행이 느린 경우 (정상)
- RoMaV2, DINOv3 모델을 처음 실행 시 Hugging Face에서 다운로드합니다
- 이후 실행부터는 캐시를 사용하여 빠릅니다
- 인터넷이 없는 환경에서는 모델 캐시를 별도 볼륨으로 마운트하세요:
  ```bash
  docker run ... -v /모델캐시경로:/app/.cache ...
  ```

### Google Earth Engine 인증 실패
- `ee-service-account-key.json` 파일이 올바른 위치에 마운트되었는지 확인
- 서비스 계정에 Earth Engine 접근 권한이 있는지 확인

### 메모리 부족 (OOM) 오류
```bash
# GPU 메모리 확인
nvidia-smi

# --segment 옵션으로 처리 단위 줄이기
docker run ... --segment 1 ...
```

### 로그 상세 출력
```bash
docker run ... 2>&1 | tee pipeline.log
```

---

## 기술 지원
문의: [담당자 연락처]
