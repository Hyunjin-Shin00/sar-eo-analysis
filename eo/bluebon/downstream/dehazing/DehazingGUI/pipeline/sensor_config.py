"""센서별 basis / band 매핑.

지원 센서 (haze_spec_modeling 미사용 함수만):
  - sky      : SkySat 4-band rhorc
  - msi_20m  : Sentinel-2 MSI 20m rhorc (Wonsan1/Kuwait/Pyeongyang 선택)
  - msi_10m  : Sentinel-2 MSI 10m rhorc (20m basis 의 bds20to10 서브셋)

basis_id 는 basis_catalog 가 정의한 'builtin:<sensor>:<suffix>' 형식.
None 또는 'default' 를 주면 센서별 기본 항목을 선택.
"""
from .basis_catalog import get_builtin_func, default_basis_id

# (display label, sensor key)
SENSOR_OPTIONS = [
    ('SkySat (rhorc)',              'sky'),
    ('Sentinel-2 MSI 20m (rhorc)',  'msi_20m'),
    ('Sentinel-2 MSI 10m (rhorc)',  'msi_10m'),
]

SENSOR_KEYS = {opt[1] for opt in SENSOR_OPTIONS}


def _resolve_basis_func(sensor: str, basis_id: str | None):
    if basis_id is None or basis_id == 'default':
        basis_id = default_basis_id(sensor)
    func = get_builtin_func(basis_id) if basis_id else None
    if func is None:
        raise ValueError(
            f'알 수 없는 basis_id: {basis_id!r} (sensor={sensor!r})'
        )
    return func


def get_sensor_params(sensor: str, nb_input: int, basis_id: str | None = None):
    """
    Returns (bases, u0, bds, bds_rgb, bxsize).
      bases   : (K, len(bds))  basis vectors after band subset
      u0      : (len(bds),)    aerosol spectrum (normalized)
      bds     : list of band indices used from input image
      bds_rgb : RGB preview band indices into the subset image
      bxsize  : box-average window
    """
    func = _resolve_basis_func(sensor, basis_id)

    if sensor == 'sky':
        bds = list(range(nb_input))
        bases0, u0 = func()
        return bases0[:, bds], u0[bds], bds, [2, 1, 0], 11

    if sensor == 'msi_20m':
        bds = list(range(10))
        bases0, u0 = func()
        return bases0[:, bds], u0[bds], bds, [2, 1, 0], 5

    if sensor == 'msi_10m':
        bds = list(range(4))
        bds20to10 = [0, 1, 2, 7]
        bases0, u0 = func()
        bases0 = bases0[:, bds20to10]
        u0 = u0[bds20to10]
        return bases0[:, bds], u0[bds], bds, [2, 1, 0], 11

    raise ValueError(f'지원하지 않는 센서: {sensor!r}. 가능: {sorted(SENSOR_KEYS)}')


def auto_detect_sensor(fin: str) -> str | None:
    """파일명으로 센서 추정. 실패 시 None."""
    name = fin.lower()
    if 'sky' in name or 'ssc' in name:
        return 'sky'
    if 'msi_res10m' in name or 'msi_10m' in name:
        return 'msi_10m'
    if 'msi_res20m' in name or 'msi_20m' in name or 'msi_' in name:
        return 'msi_20m'
    return None
