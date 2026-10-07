"""
런처용 monkeypatch: ps_select(step3)의 OOM 폭증을 막는 '스마트 Pool'.

근본 문제 (ps_select.py:280-284):
    args_list = [(i, ix, pm, n_win, n_i, n_j, n_ifg, alpha, beta, osf) for i in range(n_ps)]
    results   = pool.map(compute_ph_patch, args_list)
  - n_ps = 수십만. 각 튜플이 거대한 pm(dict, ph_grid 등)과 ix(대형 인덱스배열)를 '참조'.
  - pool.map 은 각 작업 인자를 개별 pickle 직렬화 → pm/ix 가 수십만 번 복제 → 수십~수백 GB OOM.
  - 워커 수를 줄이거나 캡을 키워도 부모의 직렬화 큐가 터지므로 소용 없음(실측: 4워커+90G도 OOM).

해결:
  multiprocessing.Pool 을 _SmartPool 로 치환. _SmartPool.map 은
  ps_select 패턴(인자 튜플의 [2]가 dict=pm)을 감지하면:
    1) 공통인 fn/ix/pm 을 '모듈 전역'에 세팅 (작업마다 들고 다니지 않음)
    2) 작업 큐엔 픽셀 인덱스+스칼라만(light) 담아 보냄 → pickle 페이로드 미미
    3) 실제 Pool(fork) 워커는 fork 시점에 전역 pm/ix 를 COW 상속 → pm 복제 없음(메모리 1벌 공유)
  → 병렬성 유지(8워커) + 메모리 bounded. compute_ph_patch 는 순수함수라 결과·순서 동일.

전제: start method=fork(Linux 기본), OMP_NUM_THREADS=1(드라이버가 export → fork-후-BLAS 락 안전).
공유 psi_python(StaMPS Python 포팅) 패키지는 미수정. 런처 측에서만 적용.
"""
import os
import multiprocessing as _mp
import multiprocessing.pool as _mpp

_RealPool = _mpp.Pool  # 원본 Pool (치환 전에 캡처)

# fork 로 워커에 COW 상속될 모듈 전역 (작업마다 pickle 하지 않을 공통 대형 객체)
_G = {"fn": None, "ix": None, "pm": None}

_NWORKERS = int(os.environ.get("NWORKERS", "8"))
# 워커 재생성 주기. fork COW 는 Python 참조카운트(객체 헤더 write)로 점차 깨져
# 워커가 pm 페이지를 각자 복사 → 8*pm 으로 메모리 증가. 일정 작업마다 워커를 재fork 하면
# COW 누적이 리셋되어 메모리가 낮게 묶인다. (속도 영향 미미: 재fork 수회뿐)
# 주의: maxtasksperchild 는 '청크' 단위로 카운트됨. 기본 chunksize 가 크면 청크가 몇 개뿐이라
# 재생성이 안 일어남 → chunksize 를 작게 강제해야 maxtasksperchild 가 동작한다.
_MAXTASKS = int(os.environ.get("MAXTASKSPERCHILD", "50"))   # 청크 50개마다 워커 재fork
_CHUNK = int(os.environ.get("CHUNKSIZE", "50"))             # 1청크=50 픽셀 → 재생성당 2500 픽셀


def _wrap(light):
    # light = (i, n_win, n_i, n_j, n_ifg, clap_alpha, clap_beta, slc_osf)
    full = (light[0], _G["ix"], _G["pm"]) + tuple(light[1:])
    return _G["fn"](full)


class _SmartPool:
    def __init__(self, processes=None, initializer=None, initargs=(), maxtasksperchild=None, *a, **k):
        n = processes or _mp.cpu_count()
        self._n = max(1, min(int(n), _NWORKERS))
        # 일반 Pool 호출의 initializer/initargs/maxtasksperchild 는 반드시 보존·전달해야 함.
        # (예: uw_unwrap_from_grid 는 initializer=init_worker 로 워커 전역을 세팅 →
        #  버리면 워커에서 global_gridix=None → 'NoneType not subscriptable' crash)
        self._initializer = initializer
        self._initargs = initargs
        self._maxtasks = maxtasksperchild

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def map(self, fn, iterable, chunksize=None):
        items = list(iterable)
        if not items:
            return []
        first = items[0]
        # ps_select 패턴 감지: 인자 튜플 (i, ix, pm(dict), ...) — pm pickle 폭증 방지 특수경로.
        # (이 경로의 원본 호출엔 initializer 없음)
        if (self._initializer is None
                and isinstance(first, (list, tuple)) and len(first) >= 3 and isinstance(first[2], dict)):
            _G["fn"] = fn
            _G["ix"] = first[1]
            _G["pm"] = first[2]
            light = [(t[0],) + tuple(t[3:]) for t in items]
            # 전역 세팅 후 Pool 생성 → 워커가 fork 시 pm/ix 를 COW 상속(pickle 0회)
            with _RealPool(processes=self._n, maxtasksperchild=_MAXTASKS) as p:
                res = p.map(_wrap, light, _CHUNK)   # 작은 chunksize 강제 → 워커 재생성 동작
            _G["fn"] = _G["ix"] = _G["pm"] = None  # 참조 해제
            return res
        # 일반 경우: 원본 Pool 동작 그대로 (워커 수만 제한, initializer/initargs/maxtasksperchild 전달)
        with _RealPool(processes=self._n, initializer=self._initializer,
                       initargs=self._initargs, maxtasksperchild=self._maxtasks) as p:
            return p.map(fn, items, chunksize)

    def close(self):
        pass

    def join(self):
        pass

    def terminate(self):
        pass


# 주의: multiprocessing.pool.Pool(=_RealPool 구현체)은 내부에서 자기 클래스명 'Pool'을
# 모듈 전역으로 참조하므로 절대 덮어쓰지 말 것(덮으면 _handle_workers 등 AttributeError).
# ps_select 는 `multiprocessing.Pool` 만 사용하므로 그 이름만 치환한다.
_mp.Pool = _SmartPool

print(f"[mp_patch] multiprocessing.Pool -> _SmartPool (fork COW 공유, {_NWORKERS}워커, pm pickle 제거)", flush=True)


# ---------------------------------------------------------------------------
# uw_unwrap_from_grid.compute_ph_uw 최적화 패치
# 원본은 PS 픽셀마다(수십만 회) np.isreal(global_uw['ph_in']).all() (전체 45M 배열)을
# 재계산 → O(n_ps * n_ps * n_ifg) 사실상 정체(8코어 ~22분+). isreal 은 상수이므로
# 워커당 1회만 계산(캐시)하도록 compute_ph_uw 를 교체. 결과 동일.
# ---------------------------------------------------------------------------
def _fast_compute_ph_uw(i):
    import numpy as _np
    import psi_python.uw_unwrap_from_grid as _U
    ix = _U.global_gridix[int(_U.global_grid_ij[i, 0]), int(_U.global_grid_ij[i, 1])]
    if ix == 0:
        return i, _np.nan
    ph_uw_pix = _U.global_uu['ph_uw'][ix, :]
    isreal = getattr(_U, '_isreal_cache', None)
    if isreal is None:
        isreal = bool(_np.isreal(_U.global_uw['ph_in']).all())
        _U._isreal_cache = isreal           # 워커당 1회만 계산
    if isreal:
        ph_uw = ph_uw_pix + _np.angle(_np.exp(1j * (_U.global_uw['ph_in'][i, :] - ph_uw_pix)))
    else:
        ph_uw = ph_uw_pix + _np.angle(_U.global_uw['ph_in'][i, :] * _np.exp(-1j * ph_uw_pix))
    return i, ph_uw

try:
    import psi_python.uw_unwrap_from_grid as _U
    _U.compute_ph_uw = _fast_compute_ph_uw
    print("[mp_patch] uw_unwrap_from_grid.compute_ph_uw -> 최적화판(isreal 캐시) 교체됨", flush=True)
except Exception as _e:
    print(f"[mp_patch] WARN: compute_ph_uw 패치 실패({type(_e).__name__}: {_e}) — 원본 사용", flush=True)
