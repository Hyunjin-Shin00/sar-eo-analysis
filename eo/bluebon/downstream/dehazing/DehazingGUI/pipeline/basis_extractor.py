"""폴리라인 정점 → 픽셀 좌표 → basis vectors 추출."""
import numpy as np


def polyline_pixel_coords(
    vertices: list,
    max_samples: int = 500,
) -> tuple:
    """모든 선분에 대해 Bresenham-like 정수 픽셀 좌표 수집.

    vertices: [(x0, y0), (x1, y1), ...]  영상 좌표계 (x=col, y=row)
    max_samples 초과 시 균등 서브샘플.

    Returns: (ys, xs)  각 shape (N,) int32
    """
    if len(vertices) < 2:
        raise ValueError(f'폴리라인 정점이 최소 2개 필요 (현재 {len(vertices)})')

    xs_all, ys_all = [], []
    for (x1, y1), (x2, y2) in zip(vertices[:-1], vertices[1:]):
        n = max(abs(x2 - x1), abs(y2 - y1)) + 1
        if n == 1:
            xs_all.append(int(round(x1)))
            ys_all.append(int(round(y1)))
            continue
        t = np.linspace(0.0, 1.0, n)
        xs_all.extend((x1 + (x2 - x1) * t).round().astype(int).tolist())
        ys_all.extend((y1 + (y2 - y1) * t).round().astype(int).tolist())

    xs = np.array(xs_all, dtype=np.int32)
    ys = np.array(ys_all, dtype=np.int32)

    if len(xs) > max_samples:
        idx = np.linspace(0, len(xs) - 1, max_samples).astype(int)
        xs = xs[idx]
        ys = ys[idx]

    return ys, xs


def build_basis_from_polyline(
    img: np.ndarray,
    vertices: list,
    max_samples: int = 500,
) -> np.ndarray:
    """img (nb, rows, cols)에서 폴리라인 픽셀 스펙트럼을 추출하여 basis (N, nb) 반환.

    영상 범위 밖 좌표는 자동으로 필터링.
    """
    if img.ndim != 3:
        raise ValueError(f'img shape (nb, rows, cols) 기대, 실제: {img.shape}')

    nb, nrows, ncols = img.shape
    ys, xs = polyline_pixel_coords(vertices, max_samples=max_samples)

    valid = (ys >= 0) & (ys < nrows) & (xs >= 0) & (xs < ncols)
    if not np.any(valid):
        raise ValueError('폴리라인 정점이 모두 영상 범위 밖입니다')
    ys = ys[valid]
    xs = xs[valid]

    # (nb, N) → (N, nb)
    basis = img[:, ys, xs].T.astype(np.float32, copy=False)

    if len(basis) < 2:
        raise ValueError(f'유효 basis 픽셀이 너무 적음: {len(basis)}')

    return basis


def extract_user_basis_payload(
    img: np.ndarray,
    clear_verts: list,
    hazy_verts: list | None = None,
    max_samples: int = 500,
) -> dict:
    """Clear (+ 선택적 hazy) polyline → bases + u_h/u_l/u_norm.

    Returns dict:
        bases  : (K, nb) float32  — clear polyline 픽셀 스펙트럼들
        u_l    : (nb,)   float32  — clear pixels 평균
        u_h    : (nb,)   float32 | None
        u_norm : (nb,)   float32 | None — (u_h - u_l) / (u_h - u_l)[0]
    hazy_verts 가 None / 길이<2 면 u_h, u_norm 은 None.
    """
    bases = build_basis_from_polyline(img, clear_verts, max_samples=max_samples)
    u_l = bases.mean(axis=0).astype(np.float32)

    u_h = None
    u_norm = None
    if hazy_verts and len(hazy_verts) >= 2:
        hazy_pixels = build_basis_from_polyline(img, hazy_verts, max_samples=max_samples)
        u_h = hazy_pixels.mean(axis=0).astype(np.float32)
        diff = u_h - u_l
        if abs(float(diff[0])) < 1e-9:
            raise ValueError('u_h-u_l 의 첫 채널이 0 에 가까워 정규화 불가')
        u_norm = (diff / diff[0]).astype(np.float32)

    return {'bases': bases, 'u_l': u_l, 'u_h': u_h, 'u_norm': u_norm}
