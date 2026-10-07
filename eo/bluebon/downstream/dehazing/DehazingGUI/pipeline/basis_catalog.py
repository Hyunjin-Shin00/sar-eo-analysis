"""Built-in basis 레지스트리.

vendor/baseu_NEW.py 의 basis_u_* 함수들을 센서별로 묶어 GUI에서 선택할 수 있게 한다.
basis_id 포맷: 'builtin:<sensor>:<suffix>'  (예: 'builtin:msi_20m:wonsan1_240809')
"""
import baseu_NEW as BUNEW


# (suffix, label, func, is_default)
_MSI_RHORC_OPTIONS = [
    ('wonsan1_240809',    'Wonsan1 (240809)',    BUNEW.basis_u_NEW_msi20m_rhorc_240809_Wonsan1,    True),
    ('kuwait',            'Kuwait',              BUNEW.basis_u_NEW_msi20m_rhorc_Kuwait,            False),
    ('pyeongyang_260401', 'Pyeongyang (260401)', BUNEW.basis_u_NEW_msi20m_rhorc_260401_Pyeongyang, False),
]

# msi_10m 은 20m basis 를 bds20to10 으로 4-band 슬라이싱해 재사용 (sensor_config 가 처리).
BUILTIN_BY_SENSOR = {
    'sky': [
        ('sky_rhorc', 'SkySat rhorc', BUNEW.basis_u_sky_rhorc, True),
    ],
    'msi_20m': _MSI_RHORC_OPTIONS,
    'msi_10m': _MSI_RHORC_OPTIONS,
}


def list_builtin(sensor: str) -> list:
    """(basis_id, label, is_default) 목록."""
    return [
        (f'builtin:{sensor}:{suf}', label, default)
        for suf, label, _func, default in BUILTIN_BY_SENSOR.get(sensor, [])
    ]


def get_builtin_func(basis_id: str):
    """basis_id -> callable. 없으면 None."""
    try:
        prefix, sensor, suffix = basis_id.split(':', 2)
    except ValueError:
        return None
    if prefix != 'builtin':
        return None
    for suf, _label, func, _default in BUILTIN_BY_SENSOR.get(sensor, []):
        if suf == suffix:
            return func
    return None


def default_basis_id(sensor: str) -> str | None:
    for suf, _label, _func, default in BUILTIN_BY_SENSOR.get(sensor, []):
        if default:
            return f'builtin:{sensor}:{suf}'
    items = BUILTIN_BY_SENSOR.get(sensor, [])
    if items:
        return f'builtin:{sensor}:{items[0][0]}'
    return None
