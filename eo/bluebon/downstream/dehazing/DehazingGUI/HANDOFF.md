# DehazingGUI 인수인계 메모

> 다음 Claude Code 세션에서 이어받을 수 있도록 정리. 작업자: <email>

## 프로젝트 개요

- **이름**: TELEPIX Dehazing GUI
- **언어/스택**: Python 3.11 / PyQt5 / NumPy / SciPy / CuPy / GDAL / PyInstaller
- **빌드 방식**: WSL2 (개발) → Windows (PyInstaller 폴더 번들) → 오프라인 PC 복사
- **표준 안정성**: dist 폴더만 복사해 어떤 Win10/11 환경에서도 동작해야 함 (인터넷 없이)

## 타깃 배포 머신 (중요한 제약)

| 항목 | 사양 |
|---|---|
| 모델 | Dell 7910 |
| CPU | Intel Xeon E5 2690 v4 (Broadwell, 14C, 2.6GHz) |
| RAM | 128 GB |
| **GPU** | **NVIDIA Quadro M6000 24GB (Maxwell, compute capability 5.2)** |
| OS | Windows 10 (오프라인) |

**Maxwell 제약** → CuPy 13.x + CUDA 12.x 만 가능. 13.0+ / CuPy 14 미지원. FP8/TF32/bfloat16 하드웨어 없음.

---

## 현재 진행 중인 두 가지 이슈

### Issue 1 — CuPy 14 / FP8 E8M0 NVRTC 컴파일 에러 (해결책 적용 완료, 빌드/검증 대기)

**증상**:
```
CompileException: ... cuda_fp8.h: error: incomplete type "__nv_fp8_e8m0" is not allowed
... 42 errors detected in the compilation of "...cubin.cu"
```
`xp.argpartition(...)` → `unravel_index` → `.any()` → CUB reduction 커널 JIT 컴파일에서 발생.

**근본 원인**:
- 번들 CuPy 14.0.1 의 CCCL/libcudacxx 헤더는 `__nv_fp8_e8m0` 사용 (CUDA 12.8+ 기능).
- 번들된 `_internal/Library/include/cuda_fp8.h` 는 CUDA 12.6 세대 (forward decl만, 본체 정의 없음).
- libcudacxx 의 매크로 `_CCCL_HAS_NVFP8_E8M0() = (_CCCL_HAS_NVFP8() && _CCCL_CTK_AT_LEAST(12, 8))` 가 NVRTC 12.9 보고 기반으로 참이 되어 컴파일이 incomplete type 에러로 실패.

**적용한 해결책 (소스 수정 → 재빌드 필요)**:

1. `environment.yml` — CuPy 와 CUDA 핀:
   ```yaml
   - cupy=13.*
   - cuda-version=12.*
   ```
   CuPy 13.x 의 CCCL 은 E8M0 코드 경로 없음. CUDA 12.x 는 Maxwell PTX JIT 지원.

2. `dehaze_gui.spec` — 빌드 시점 가드:
   ```python
   import cupy as _cupy_check
   _major = int(_cupy_check.__version__.split('.')[0])
   if _major != 13:
       raise SystemExit(...)
   ```

3. `hooks/rthook_cupy.py` — 런타임 가드:
   ```python
   if not os.environ.get('CUPY_ACCELERATORS'):
       os.environ['CUPY_ACCELERATORS'] = 'cub'
   ```

**상태**: Windows 빌드 머신에서 conda env 재생성 + 재빌드 + M6000 PC 검증 대기.

---

### Issue 2 — 다중 파일 순차 처리 UI (코드 완료, 검증 대기)

**요구**: rhorc 영상 (~12805×14829×4밴드, 1.5GB) 여러 개를 한 번에 입력받아 처리.

**설계 결정**:
- **동시 (parallel) 처리 안 함**: M6000 단일 GPU 에서 Maxwell HyperQ 한계 + NVRTC JIT 캐시 충돌 + 드라이버 크래시 위험으로 실효 가속 없음. → **순차 큐**.
- **폴리라인 + 다중 선택 = 불가**: 폴리라인은 preview 한 장 기준이라 의미 충돌. UI 가드로 차단, 저장된 user basis 또는 builtin basis 만 허용.
- **NVRTC 캐시 효과**: 2번째 파일부터 JIT 비용 0 → throughput 이득.
- **파일 사이 GPU 메모리 풀 명시 해제**: OOM 방지.
- **에러 격리**: 한 파일 실패해도 다음 진행, 최종 summary.

**변경된 파일**:

| 파일 | 핵심 변경 |
|---|---|
| `ui/worker.py` | 완전 재작성. `DehazingWorker(fins: list[str], ...)`. `_resolve_basis_for_file()` 로 basis 결정 분리. 파일 사이 `_free_gpu_memory()`. 신규 시그널 `file_started_signal` / `file_finished_signal` / `file_failed_signal` / `batch_finished_signal`. 기존 `finished_signal` 은 "마지막 성공 파일" 전용. |
| `ui/control_panel.py` | `QFileDialog.getOpenFileNames` (복수형). `self._selected_files: list[str]` 보관. `edit_input` 표시 `"[N개 파일] first.tif 외 N-1개"`. 다중 선택 시 폴리라인 그리기 버튼 비활성, 콤보가 폴리라인이면 센서 기본 basis 로 자동 전환. `process_requested` 시그널 시그너처를 `(list, str, str, str, object)` 로 변경. |
| `ui/main_window.py` | `_on_process_requested(fins: list, ...)`. `self._loaded_path` 추가 (첫 파일 캐시 매칭용). 4 개 배치 시그널 슬롯 (`_on_file_started/_finished/_failed/_on_batch_finished`). 모든 파일 실패해도 버튼 복원되도록 `_on_batch_finished` 끝에 `panel.processing_done()` 호출. |

**상태**: 코드/문법 검증 통과 (offscreen Qt 임포트/인스턴스 OK). M6000 PC 실측 대기.

---

## 미해결 사항

- **PC 재부팅 인시던트** ([[project-pc-reboot]] memory): dehazing 처리 중 재부팅 — CuPy + 번들 CUDA DLL 드라이버 크래시 의심. CuPy 13 핀 + CUB 명시로 해결됐을 가능성 있지만 **현장 검증 안 됨**.
- **단일 파일 처리 시간 미측정**: M6000 에서 매칭 단계 wall-clock 측정해서 배치 N개의 총 시간 추정 자료 만들 것.

---

## 다음 단계 — 사용자가 해야 할 일

### A. Windows 빌드 머신에서 (Anaconda Prompt)

```bat
conda env remove -n dehaze_gui -y
conda env create -f environment.yml
call conda activate dehaze_gui
python -c "import cupy; print(cupy.__version__)"
REM ↑ 13.x.x 가 찍히는지 반드시 확인. 14.x 면 conda 채널/캐시 문제.
build_windows.bat
```

### B. 빌드된 `dist\DehazingGUI` 를 M6000 PC 로 복사 후

| # | 시나리오 | 기대 |
|---|---|---|
| 1 | 단일 파일 선택 → 처리 | 종전과 동일 (회귀 없음). preview/폴리라인/처리/compare 정상. |
| 2 | builtin basis + 2-3 개 파일 배치 | 순차 처리, 진행바 0-100% 반복, 상태바 `[i/N] stage`. 마지막 파일 preview 표시. |
| 3 | 다중 선택 후 콤보 폴리라인 시도 | 그리기 버튼이 비활성 유지. 로그에 "단일 파일 전용" 안내. |
| 4 | 처리 중 "중지" | 현재 파일이 종결/중단되고 멈춤. 배치 summary 로그. |
| 5 | 깨진 경로 1개 포함된 배치 | 다음 파일 계속 진행. summary 에 실패 1 표기. |
| 6 | NVRTC 캐시 효과 | 2번째 파일의 "스펙트럼 매칭" timer 가 첫 파일 대비 짧은지 확인. |
| 7 | GPU 메모리 해제 | `nvidia-smi` 로 파일 전환 직후 메모리 사용량 줄어드는지 확인. |
| 8 | 1.5GB 파일 (12805×14829×4) 단일 처리 시간 측정 | 매칭 단계 wall-clock 로그. 향후 배치 시간 추정 기준. |

---

## 핵심 참고 파일

### 메모리 (Claude 자동 메모리)

`<WORK_ROOT>/.claude/projects/-mnt-e-<USER>-working-DehazingGUI/memory/`:

| 파일 | 내용 |
|---|---|
| `MEMORY.md` | 인덱스 (자동 로드됨) |
| `user.md` | 사용자 프로필 |
| `feedback_plan_first.md` | 사소하지 않은 기능은 ExitPlanMode 워크플로우 사용 |
| `feedback_design_defaults.md` | UI 기본값: 한국어+영문 알고리즘 용어 / built-in 보호 / 비교=수직 디바이더 / 영속성=exe 옆 JSON |
| `feedback_bulk_diagnostics.md` | 후보 여러 개면 한 번에 다 점검 |
| `feedback_standalone_guarantee.md` | dist 복사만으로 동작 보증 |
| `project_pc_reboot.md` | 미해결 인시던트 |
| `project_target_machine.md` | M6000 / Maxwell 제약 (이 작업으로 신규 추가) |

### 플랜

- `<WORK_ROOT>/.claude/plans/abstract-sprouting-ullman.md` — 다중 파일 배치 처리 플랜 (승인됨)

### 핵심 코드

| 파일 | 역할 |
|---|---|
| `main.py` | 진입점 |
| `dehaze_gui.spec` | PyInstaller spec |
| `build_windows.bat` | Windows 빌드 스크립트 |
| `environment.yml` | conda env 정의 (CuPy/CUDA 핀 사유 주석 포함) |
| `hooks/rthook_*.py` | PyInstaller 런타임 훅 (DLL 검색, GDAL, CuPy) |
| `ui/main_window.py` | MainWindow + 워커 시그널 슬롯 |
| `ui/control_panel.py` | 우측 컨트롤 패널 + 파일 선택 |
| `ui/worker.py` | QThread 워커 (배치 큐) |
| `pipeline/runner.py` | `run_dehazing(fin, ...)` — 단일 파일 처리 |
| `pipeline/loader.py` | `load_image(fin)` |
| `pipeline/mem_utils.py` | 동적 타일 사이즈 (RAM 30% 예산) |
| `vendor/basematch_sub_NEW.py` | 스펙트럼 매칭 (GPU 타일링) |
| `vendor/box_average2.py` | 박스 평균 (CPU 4-스레드) |

---

## 작업 컨벤션 (memory 에서 옮긴 핵심)

- **플랜 먼저**: 사소하지 않은 기능 변경은 ExitPlanMode 워크플로우.
- **묶음 진단**: 후보 여러 개면 ping-pong 금지, 한 번에 다 점검.
- **언어**: 모든 응답 한국어. 기술 용어/식별자는 원문 유지.
- **표준 안정성**: dist 복사만으로 어떤 Win10/11 에서도 동작해야 함.
- **UI**: 한국어 + 영문 알고리즘 용어 (예: "스펙트럼 매칭", "boxsize").
- **영속성**: exe 옆 JSON (offline 머신 가정).
- **builtin 보호**: builtin basis 는 수정/삭제 불가.
