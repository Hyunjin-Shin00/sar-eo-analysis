import numpy as np

from skimage.registration import phase_cross_correlation
from skimage.filters import sobel, gaussian

# Initial try, Obsolete
def coreg_single_ref_initial(images, refband=None, upsample_f=10, bg=0.):
        
    if refband is None:
        refband=0

    #compute shift_arr
    ref = images[refband]
    H, W = ref.shape
    shifts = []
    for ib, im in enumerate(images):
        if ib==refband:
            (dy,dx)=(0.0,0.0)
        else:
            (dy, dx), _, _ = phase_cross_correlation(ref, im, upsample_factor=upsample_f)
        shifts.append((dy, dx))
    
    # Integer offsets for canvas sizing
    sh_int = np.array([(int(np.round(dy)), int(np.round(dx))) for dy, dx in shifts])
    ys, xs = sh_int[:,0], sh_int[:,1]
    
    y_min = int(np.minimum(0, ys.min()))
    x_min = int(np.minimum(0, xs.min()))
    y_max = int(np.maximum(H, (ys + H).max()))
    x_max = int(np.maximum(W, (xs + W).max()))
    out_shape = (y_max - y_min, x_max - x_min)
    
    stack = np.full((len(images),) + out_shape, bg, dtype=images[0].dtype)
    for k, (im, (dyi, dxi)) in enumerate(zip(images, sh_int)):
        oy = dyi - y_min   # top-left on the canvas
        ox = dxi - x_min
        stack[k, oy:oy+H, ox:ox+W] = im  # direct paste, no resampling
    
    return stack, sh_int





def coreg_two_refs(
    images, vis_idxs, ref_vis,
    nir_idxs=None, ref_nir=None,
    upsample_f=10, bg=0, verbose=True,
    use_gradient=False,
    valid_ranges=None,          # NEW: [[min0,max0],[min1,max1],...]
    roi=None,
    mask_soft_sigma=8.0,        # NEW: soften valid mask (reduces FFT ringing)
):
    """
    Phase-correlation coregistration with optional per-band valid_ranges masking.

    valid_ranges:
      - None: use all finite pixels
      - list of [vmin,vmax] per band index: valid = finite & (vmin<=im<=vmax)
    Masking is applied by zeroing invalid pixels and multiplying by a softened mask.
    """

    H, W = images[ref_vis].shape
    n_bands = len(images)
    shifts = [None] * n_bands

    # --- helper: build per-band valid mask ---
    def _valid_mask_from_range(im, vmin=None, vmax=None):
        im = np.asarray(im)
        m = np.isfinite(im)
        if vmin is not None:
            m &= (im >= vmin)
        if vmax is not None:
            m &= (im <= vmax)
        return m

    def get_valid_mask(band_idx):
        if valid_ranges is None:
            mask= np.isfinite(images[band_idx])
        else:
            if band_idx >= len(valid_ranges):
                raise ValueError(f"valid_ranges length ({len(valid_ranges)}) < band index ({band_idx})")
            vmin, vmax = valid_ranges[band_idx]
            mask= _valid_mask_from_range(images[band_idx], vmin, vmax)
            
        if roi is not None:
            y0, y1, x0, x1 = roi
            print(f'  -> ROI area: {(y1-y0)*(x1-x0)} pixels', flush=True)
            submask = np.zeros_like(mask, dtype=bool)
            submask[y0:y1, x0:x1] = True
            mask &= submask
            
        return mask

    # --- helper: choose raw or gradient image ---
    def _pcorr_img(im):
        if not use_gradient:
            return im.astype(np.float32)
        return sobel(im.astype(np.float32))

    # --- helper: apply (soft) valid mask for FFT stability ---
    def _apply_valid_mask(im_pc, valid_mask):
        if valid_mask is None:
            return im_pc
        vm = np.asarray(valid_mask, dtype=bool)
        w = gaussian(vm.astype(np.float32), sigma=mask_soft_sigma, preserve_range=True)
        w /= (w.max() + 1e-6)
        out = np.where(vm, im_pc, 0.0).astype(np.float32)
        out *= np.clip(w, 0.0, 1.0)
        return out

    # --- STEP 1: VIS -> ref_vis ---
    if verbose:
        print(f"\n[STEP 1] VIS bands -> ref_vis {ref_vis}")

    ref_vis_im = images[ref_vis]
    ref_vis_pc = _pcorr_img(ref_vis_im)
    ref_vis_pc = _apply_valid_mask(ref_vis_pc, get_valid_mask(ref_vis))

    shifts[ref_vis] = (0.0, 0.0)

    for ib in vis_idxs:
        if ib == ref_vis:
            continue

        if verbose:
            print(f"\n[VIS] Band {ib} -> ref_vis {ref_vis}")

        mov_pc = _pcorr_img(images[ib])
        mov_pc = _apply_valid_mask(mov_pc, get_valid_mask(ib))

        (dy, dx), error, phasediff = phase_cross_correlation(
            ref_vis_pc, mov_pc, upsample_factor=upsample_f
        )
        shifts[ib] = (dy, dx)

        if verbose:
            print(f"  shift(dy,dx)=({dy:.2f},{dx:.2f})  error={error:.4f}")

    # --- STEP 2/3: NIR optional ---
    if nir_idxs is not None and len(nir_idxs) > 0 and ref_nir is not None:

        # STEP 2: ref_nir -> ref_vis
        if verbose:
            print(f"\n[STEP 2] ref_nir {ref_nir} -> ref_vis {ref_vis}")

        ref_nir_pc = _pcorr_img(images[ref_nir])
        ref_nir_pc = _apply_valid_mask(ref_nir_pc, get_valid_mask(ref_nir))

        (dy_nref, dx_nref), error, phasediff = phase_cross_correlation(
            ref_vis_pc, ref_nir_pc, upsample_factor=upsample_f
        )
        shifts[ref_nir] = (dy_nref, dx_nref)

        if verbose:
            print(f"  ref_nir shift=({dy_nref:.2f},{dx_nref:.2f})  error={error:.4f}")

        # STEP 3: other NIR -> ref_nir then -> ref_vis
        if verbose:
            print(f"\n[STEP 3] NIR bands -> ref_nir {ref_nir}, composed -> ref_vis {ref_vis}")

        nir_ref_pc = _pcorr_img(images[ref_nir])
        nir_ref_pc = _apply_valid_mask(nir_ref_pc, get_valid_mask(ref_nir))

        for ib in nir_idxs:
            if ib == ref_nir:
                continue

            if verbose:
                print(f"\n[NIR] Band {ib} -> ref_nir {ref_nir} (local), then -> ref_vis {ref_vis}")

            mov_pc = _pcorr_img(images[ib])
            mov_pc = _apply_valid_mask(mov_pc, get_valid_mask(ib))

            (dy_local, dx_local), error, phasediff = phase_cross_correlation(
                nir_ref_pc, mov_pc, upsample_factor=upsample_f
            )

            if verbose:
                print(f"  [LOCAL SHIFT]  ({dy_local:.2f},{dx_local:.2f})  error={error:.4f}")

            dy_g = dy_nref + dy_local
            dx_g = dx_nref + dx_local
            shifts[ib] = (dy_g, dx_g)

            if verbose:
                print(f"  [GLOBAL SHIFT] ({dy_g:.2f},{dx_g:.2f})")

    # --- Fill missing shifts with (0,0) to avoid crash ---
    for k in range(n_bands):
        if shifts[k] is None:
            shifts[k] = (0.0, 0.0)
            if verbose:
                print(f"\n[INFO] Band {k} not registered (not in VIS/NIR groups). Using shift=(0,0).")

    # Convert to integer pixel offsets for canvas
    sh_int = np.array([(int(np.round(dy)), int(np.round(dx))) for (dy, dx) in shifts], dtype=int)
    ys, xs = sh_int[:, 0], sh_int[:, 1]

    y_min = int(np.minimum(0, ys.min()))
    x_min = int(np.minimum(0, xs.min()))
    y_max = int(np.maximum(H, (ys + H).max()))
    x_max = int(np.maximum(W, (xs + W).max()))
    out_shape = (y_max - y_min, x_max - x_min)

    # Paste onto common canvas
    stack = np.full((n_bands,) + out_shape, bg, dtype=images[0].dtype)
    for k, (im, (dyi, dxi)) in enumerate(zip(images, sh_int)):
        oy = dyi - y_min
        ox = dxi - x_min
        stack[k, oy:oy+H, ox:ox+W] = im

    return stack, shifts, sh_int, out_shape






from scipy.ndimage import gaussian_filter

# small angle rotation (brute force) & phase correlation
def coreg_single_ref_small_rotation(images, ref_idx, upsample_f=1, bg=0, use_gradient=True, blur_sigma=1.0,):
    """
    Coregister all bands to a single reference band using phase correlation on
    gradient images (good for VIS–NIR with opposite brightness response).

    Parameters
    ----------
    images : list or array-like of 2D arrays
        All bands, each shape (H, W).
    ref_idx : int
        Index of the chosen reference band in `images`.
    upsample_f : int or float
        Subpixel upsampling factor passed to phase_cross_correlation.
        (In skimage it is typically an integer >= 1.)
    bg : scalar
        Background fill value for the output canvas.
    use_gradient : bool
        If True, estimate shifts using gradient magnitude (Sobel) images.
        If False, use raw bands directly.
    blur_sigma : float
        Sigma for a light Gaussian blur before gradient (to reduce noise).

    Returns
    -------
    stack : np.ndarray
        Coregistered stack with shape (n_bands, H_out, W_out).
    shifts : list of (dy, dx) floats
        Subpixel shifts of each band relative to reference band.
    sh_int : np.ndarray of (dy, dx) ints
        Integer pixel shifts used on the output canvas.
    out_shape : tuple
        (H_out, W_out) of the common canvas.
    """
    H, W = images[ref_idx].shape
    n_bands = len(images)

    # Ensure float for registration operations
    imgs = [np.asarray(b, dtype=np.float32) for b in images]

    # --- Build registration image for the reference band ---
    ref_raw = imgs[ref_idx]
    if blur_sigma is not None and blur_sigma > 0:
        ref_proc = gaussian_filter(ref_raw, blur_sigma)
    else:
        ref_proc = ref_raw

    if use_gradient:
        ref_reg = sobel(ref_proc)
    else:
        ref_reg = ref_proc

    # Shifts relative to reference
    shifts = [None] * n_bands
    shifts[ref_idx] = (0.0, 0.0)

    # --- Register every band directly to the reference band ---
    for k in range(n_bands):
        if k == ref_idx:
            continue

        mov_raw = imgs[k]
        if blur_sigma is not None and blur_sigma > 0:
            mov_proc = gaussian_filter(mov_raw, blur_sigma)
        else:
            mov_proc = mov_raw

        if use_gradient:
            mov_reg = sobel(mov_proc)
        else:
            mov_reg = mov_proc
        
        #check if any rotation fits better
        (_dy, _dx, _angle_deg) = estimate_small_rotation_and_shift(ref_reg, mov_reg,
                                              angle_range=(-0.05, 0.05),
                                              n_angles=11,
                                              upsample_factor=upsample_f)
        print(f'Test rotation: band={k}, dy,dx,angle={_dy},{_dx},{_angle_deg}')
        if abs(_angle_deg)>0.0001:
            mov_reg = rotate(mov_reg, angle=_angle_deg, resize=False, preserve_range=True, order=1)

        (dy, dx), _, _ = phase_cross_correlation(
            ref_reg,
            mov_reg,
            upsample_factor=upsample_f,
        )
        shifts[k] = (float(dy), float(dx))

    # --- Convert to integer pixel offsets for the canvas ---
    sh_int = np.array(
        [(int(np.round(dy)), int(np.round(dx))) for (dy, dx) in shifts],
        dtype=int,
    )
    ys, xs = sh_int[:, 0], sh_int[:, 1]

    y_min = int(np.minimum(0, ys.min()))
    x_min = int(np.minimum(0, xs.min()))
    y_max = int(np.maximum(H, (ys + H).max()))
    x_max = int(np.maximum(W, (xs + W).max()))
    out_shape = (y_max - y_min, x_max - x_min)

    # --- Paste original (unfiltered) images onto common canvas ---
    stack = np.full((n_bands,) + out_shape, bg, dtype=images[0].dtype)

    for k, (im, (dyi, dxi)) in enumerate(zip(images, sh_int)):
        oy = dyi - y_min
        ox = dxi - x_min
        stack[k, oy:oy + H, ox:ox + W] = im

    return stack, shifts, sh_int, out_shape

from skimage.transform import rotate

def estimate_small_rotation_and_shift(ref, mov,
                                      angle_range=(-0.5, 0.5),
                                      n_angles=11,
                                      upsample_factor=10,
                                      use_gradient=True):
    ref = ref.astype('float32')
    mov = mov.astype('float32')

    if use_gradient:
        ref_reg = sobel(ref)
    else:
        ref_reg = ref


    best_err = np.inf
    best_params = (0.0, 0.0, 0.0)  # dy, dx, angle

    angles = np.linspace(angle_range[0], angle_range[1], n_angles)

    for ang in angles:
        mov_r = rotate(mov, angle=ang, resize=False,
                       preserve_range=True, order=1)
        mov_reg = sobel(mov_r) if use_gradient else mov_r

        (dy, dx), err, _ = phase_cross_correlation(
            ref_reg, mov_reg, upsample_factor=upsample_factor
        )

        if err < best_err:
            best_err = err
            best_params = (float(dy), float(dx), float(ang))

    return best_params  # (dy, dx, angle_deg)
    
def spatially_thin_matches(dst_points, matches, img_shape,
                           grid_rows=8, grid_cols=2, max_per_cell=50):
    """
    Thin matches so they are more evenly distributed in space.

    Parameters
    ----------
    dst_points : (N, 2) array
        Matched points in the reference image (x, y).
    matches : (N, 2) int array
        Match indices (as from match_descriptors).
    img_shape : tuple
        (H, W) of the reference image.
    grid_rows, grid_cols : int
        Number of grid cells in y and x directions.
    max_per_cell : int
        Maximum matches to keep per grid cell.

    Returns
    -------
    matches_thinned : (M, 2) int array
        Subset of matches after thinning.
    """

    H, W = img_shape
    cell_h = H / grid_rows
    cell_w = W / grid_cols

    # Cell index for each match based on reference point location
    xs = dst_points[:, 0]
    ys = dst_points[:, 1]

    cell_y = np.clip((ys / cell_h).astype(int), 0, grid_rows - 1)
    cell_x = np.clip((xs / cell_w).astype(int), 0, grid_cols - 1)
    cell_id = cell_y * grid_cols + cell_x

    # Collect indices per cell
    keep_indices = []
    for cid in np.unique(cell_id):
        idxs = np.where(cell_id == cid)[0]

        if idxs.size > max_per_cell:
            # You could choose best by descriptor distance, but random is OK as a first step
            chosen = np.random.choice(idxs, size=max_per_cell, replace=False)
        else:
            chosen = idxs

        keep_indices.append(chosen)

    keep_indices = np.concatenate(keep_indices)
    return matches[keep_indices]

# import numpy as np

# from skimage.filters import sobel
from skimage.feature import ORB, match_descriptors
from skimage.measure import ransac
from skimage.transform import AffineTransform, warp

def _indices_to_boolmask(indices, shape):
    """
    Convert (rows, cols) indices into boolean mask (shape).
    indices can be:
      - tuple (rows, cols)
      - Nx2 array of (row,col)
      - boolean mask already (returned unchanged)
    """
    if indices is None:
        return None

    if isinstance(indices, np.ndarray) and indices.dtype == bool:
        return indices

    mask = np.zeros(shape, dtype=bool)

    if isinstance(indices, tuple) and len(indices) == 2:
        rr, cc = indices
        mask[rr, cc] = True
    else:
        indices = np.asarray(indices)
        mask[indices[:, 0], indices[:, 1]] = True

    return mask

from skimage.transform import downscale_local_mean
def detect_orb(image, orb, scale=4):
    from skimage.transform import downscale_local_mean
    
    if scale == 1:
        small = image
    else:
        small = downscale_local_mean(image, (scale, scale)).astype(np.float32)
    
    try:
        orb.detect_and_extract(small)
        keypoints = orb.keypoints * scale
        descriptors = orb.descriptors
    except RuntimeError:
        keypoints = None
        descriptors = None
    
    return keypoints, descriptors
def estimate_affine_from_sobel_with_mask_saturation(
    ref,
    mov,
    valid_ref=None,
    valid_mov=None,
    n_keypoints=2000,
    fast_threshold=0.02,
    sat_threshold=0.98,
    verbose=True,
    # NEW:
    use_sobel=True,
    # spatial thinning:
    grid_rows=8,
    grid_cols=2,
    max_per_cell=40,
    # RANSAC + quality gating:
    residual_threshold=2.0,
    max_trials=1000,
    min_inlier_ratio=0.20,
    min_inliers=20,
):
    """
    Estimate affine transform mov -> ref using (optional) Sobel edges + ORB + RANSAC.
    """

    ref = np.asarray(ref, dtype=np.float32)
    mov = np.asarray(mov, dtype=np.float32)

    H, W = ref.shape
    if mov.shape != (H, W):
        raise ValueError("ref and mov must have same shape for this function.")

    # --- Convert valid masks to boolean masks ---
    valid_ref = _indices_to_boolmask(valid_ref, ref.shape)
    valid_mov = _indices_to_boolmask(valid_mov, mov.shape)

    if valid_ref is None:
        valid_ref = np.ones(ref.shape, dtype=bool)
    if valid_mov is None:
        valid_mov = np.ones(mov.shape, dtype=bool)

    # --- Saturation detection on MOV ---
    valid_mov2 = valid_mov.copy()

    if sat_threshold is not None:
        mov_norm = mov - np.nanmin(mov)
        rng = np.nanmax(mov_norm) - np.nanmin(mov_norm)

        if rng < 1e-9:
            if verbose:
                print("  [WARN] Moving image is flat. Cannot estimate affine.")
            return None

        mov_norm /= rng
        sat_mask_mov = mov_norm >= sat_threshold

        sat_count = int(np.count_nonzero(sat_mask_mov & valid_mov))
        sat_ratio = sat_count / max(1, np.count_nonzero(valid_mov))

        if sat_count > 0 and verbose:
            print(f"  [INFO] Saturated pixels in valid_mov: {sat_count} ({sat_ratio*100:.2f}%)")
            print("  [INFO] These pixels will be ignored for feature matching.")

        valid_mov2 &= ~sat_mask_mov

    if verbose:
        vr = np.count_nonzero(valid_ref)
        vm = np.count_nonzero(valid_mov2)
        print(f"  [INFO] valid_ref pixels: {vr} ({vr/ref.size*100:.2f}%)")
        print(f"  [INFO] valid_mov pixels (after saturation): {vm} ({vm/mov.size*100:.2f}%)")

    # --- Preprocessing: Sobel or raw ---
    if use_sobel:
        ref_feat = sobel(ref)
        mov_feat = sobel(mov)
        if verbose:
            print("  [INFO] Preprocess: Sobel")
    else:
        ref_feat = ref
        mov_feat = mov
        if verbose:
            print("  [INFO] Preprocess: Raw intensity")

    # Normalize feature images to [0,1] for ORB
    def _norm01(x):
        x = x.astype(np.float32)
        x = x - np.nanmin(x)
        r = np.nanmax(x) - np.nanmin(x)
        if r < 1e-9:
            return np.zeros_like(x)
        return x / r

    ref_n = _norm01(ref_feat)
    mov_n = _norm01(mov_feat)
    SCALE=1

    # --- ORB extraction ---
    orb = ORB(n_keypoints=n_keypoints, fast_threshold=fast_threshold)

    # Reference
    # orb.detect_and_extract(ref_n)
    # kpr = orb.keypoints
    kpr, descr = detect_orb(ref_n, orb, scale=SCALE)
    if kpr is None or len(kpr) == 0:
        if verbose:
            print("  [WARN] No keypoints found in reference.")
        return None

    # Moving

    # orb.detect_and_extract(mov_n)
    # kpm = orb.keypoints
    # descm = orb.descriptors
    kpm, descm = detect_orb(mov_n, orb, scale=SCALE)
    if kpm is None or len(kpm) == 0:
        if verbose:
            print("  [WARN] No keypoints found in moving image.")
        return None

    # --- Filter keypoints by valid masks ---
    def _filter_kp_desc(kp, desc, valid_mask, label=""):
        rr = kp[:, 0].astype(int)
        cc = kp[:, 1].astype(int)
        rr = np.clip(rr, 0, H - 1)
        cc = np.clip(cc, 0, W - 1)

        keep = valid_mask[rr, cc]
        removed = int(np.count_nonzero(~keep))

        if verbose and removed > 0:
            print(f"  [INFO] Removing {removed} / {len(kp)} keypoints outside valid_{label} region.")

        return kp[keep], desc[keep]

    kpr, descr = _filter_kp_desc(kpr, descr, valid_ref, label="ref")
    kpm, descm = _filter_kp_desc(kpm, descm, valid_mov2, label="mov")

    if len(kpr) < 3 or len(kpm) < 3:
        if verbose:
            print("  [WARN] Too few keypoints after validity filtering.")
        return None

    # --- Descriptor matching ---
    matches12 = match_descriptors(descr, descm, cross_check=True)
    if len(matches12) < 3:
        if verbose:
            print("  [WARN] Too few matches after descriptor matching.")
        return None

    src = kpm[matches12[:, 1]][:, ::-1]  # (x,y)
    dst = kpr[matches12[:, 0]][:, ::-1]  # (x,y)

    # --- Optional: spatial thinning of matches ---
    if grid_rows is not None and grid_cols is not None and max_per_cell is not None:
        matches12_thin = spatially_thin_matches(
            dst_points=dst,
            matches=matches12,
            img_shape=(H, W),
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            max_per_cell=max_per_cell,
        )
        if len(matches12_thin) < 3:
            if verbose:
                print("  [WARN] Too few matches after spatial thinning.")
            return None

        matches12 = matches12_thin
        src = kpm[matches12[:, 1]][:, ::-1]
        dst = kpr[matches12[:, 0]][:, ::-1]

        if verbose:
            print(f"  [INFO] Matches thinned to {len(matches12)}")

    # --- RANSAC affine ---
    model_robust, inliers = ransac(
        (src, dst),
        AffineTransform,
        min_samples=3,
        residual_threshold=residual_threshold,
        max_trials=max_trials,
    )

    if model_robust is None:
        if verbose:
            print("  [WARN] RANSAC failed to compute affine transform.")
        return None

    inlier_count = int(np.count_nonzero(inliers))
    inlier_ratio = inlier_count / len(inliers)

    if verbose:
        print(f"  [OK] Affine estimated. Matches: {len(matches12)}, "
              f"Inliers: {inlier_count}, Inlier ratio: {inlier_ratio*100:.1f}%")

    if (inlier_ratio < min_inlier_ratio) or (inlier_count < min_inliers):
        if verbose:
            print(f"  [WARN] Rejecting affine (too few inliers). "
                  f"Need ratio≥{min_inlier_ratio:.2f}, count≥{min_inliers}.")
        return None

    return model_robust


def decompose_affine(model):
    """
    Decompose a skimage AffineTransform into:
      rotation (rad + deg), scale_x, scale_y, shear, trans_x, trans_y
    Returns a dict with named fields for convenient printing.
    """

    # 3×3 matrix
    M = model.params
    
    # Extract 2×2 linear part
    a, b = M[0, 0], M[0, 1]
    c, d = M[1, 0], M[1, 1]

    # --- rotation ---
    theta = np.arctan2(c, a)        # radians
    theta_deg = np.degrees(theta)

    # --- scale ---
    sx = np.sqrt(a*a + c*c)
    
    # Avoid divide-by-zero:
    if sx < 1e-12:
        sy = 0.0
        shear = 0.0
    else:
        # scale y from determinant
        det = a*d - b*c
        sy = det / sx

        # shear component
        shear = (a*b + c*d) / sx

    # --- translation ---
    tx, ty = M[0, 2], M[1, 2]

    return {
        "theta_rad": float(theta),
        "theta_deg": float(theta_deg),
        "scale_x": float(sx),
        "scale_y": float(sy),
        "shear": float(shear),
        "trans_x": float(tx),
        "trans_y": float(ty),
    }


def _valid_mask_from_range(im, vmin=None, vmax=None):
    """
    Create boolean valid mask based on pixel range [vmin, vmax].
    If vmin or vmax is None, the corresponding bound is ignored.
    NaNs are always invalid.
    """
    im = np.asarray(im)
    mask = np.isfinite(im)
    if vmin is not None:
        mask &= (im >= vmin)
    if vmax is not None:
        mask &= (im <= vmax)
    return mask


def coreg_two_refs_affine_sobel_mask(
    images,
    vis_idxs,
    ref_vis,
    nir_idxs=None,
    ref_nir=None,
    upsample_f=10,           # kept for API compatibility; not used
    mode='edge',
    sat_threshold=0.98,
    n_keypoints=2000,
    fast_threshold=0.05,
    verbose=True,
    valid_ranges=None,       # <-- NEW: [[min0,max0],[min1,max1],...]
    roi=None, # [y0, y1, x0, x1] same for all bands
    use_sobel=True,
    # optional spatial thinning tuning forwarded to estimator:
    grid_rows=8,
    grid_cols=2,
    max_per_cell=40,
    # optional RANSAC quality gating forwarded to estimator:
    min_inlier_ratio=0.05,#0.20,
    min_inliers=5,#20,
):
    """
    Coregister VIS and NIR bands to ref_vis using affine transforms
    estimated on Sobel edge images with saturation masking + per-band valid range masks.

    valid_ranges: list of [min,max] per band
      - if None: uses full image (all finite pixels) for valid masks
      - if provided: creates masks as (min <= pixel <= max)

    Steps:
      1) VIS group: each VIS band -> ref_vis
      2) If NIR is provided:
          - ref_nir -> ref_vis
          - each other NIR band -> ref_nir, then composed into ref_vis frame

    Returns:
      stack : np.ndarray (n_bands, H, W), aligned to ref_vis
      models : list of AffineTransform, mov->ref_vis
      out_shape : (H, W)
    """

    H, W = images[ref_vis].shape
    n_bands = len(images)
    out_shape = (H, W)

    ref_vis_im = images[ref_vis]

    models = [None] * n_bands
    warped = [None] * n_bands

    print(f'roi={roi}')
    # ---------------------------
    # Helper: build valid mask for a band
    # ---------------------------
    def get_valid_mask_(band_idx):
        im = images[band_idx]
        if valid_ranges is None:
            # everything finite is valid
            mask= np.isfinite(im)
        else:
            if band_idx >= len(valid_ranges):
                raise ValueError(f"valid_ranges length ({len(valid_ranges)}) < band index ({band_idx})")

            vmin, vmax = valid_ranges[band_idx]
            mask = _valid_mask_from_range(im, vmin, vmax)
        
        # Apply ROI cropping mask if provided
        # if rois is not None and band_idx < len(rois) and rois[band_idx] is not None:
        
        if roi is not None:
            y0, y1, x0, x1 = roi
            print(f'  -> ROI area: {(y1-y0)*(x1-x0)} pixels', flush=True)
            submask = np.zeros_like(mask, dtype=bool)
            submask[y0:y1, x0:x1] = True
            mask &= submask
        return mask

    # Valid mask for ref_vis (used for all ref_vis registrations)
    valid_ref_vis = get_valid_mask_(ref_vis)

    # --- 1) VIS group: each VIS band -> ref_vis ---
    if verbose:
        print(f"\n[STEP 1] Register VIS bands to ref_vis = {ref_vis}")

    models[ref_vis] = AffineTransform()  # identity
    warped[ref_vis] = ref_vis_im

    for ib in vis_idxs:
        if ib == ref_vis:
            continue

        if verbose:
            print(f"\n[VIS] Band {ib} -> ref_vis {ref_vis}")

        valid_mov = get_valid_mask_(ib)

        model = estimate_affine_from_sobel_with_mask_saturation(
            ref=ref_vis_im,
            mov=images[ib],
            valid_ref=valid_ref_vis,
            valid_mov=valid_mov,
            n_keypoints=n_keypoints,
            fast_threshold=fast_threshold,
            sat_threshold=sat_threshold,
            verbose=verbose,
            use_sobel=use_sobel,          # <-- NEW
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            max_per_cell=max_per_cell,
            min_inlier_ratio=min_inlier_ratio,
            min_inliers=min_inliers,
        )

        if model is None:
            if verbose:
                print(f"  [WARN] Using identity transform for VIS band {ib}")
            model = AffineTransform()

        models[ib] = model

        if verbose:
            info = decompose_affine(model)
            print(f"  [AFFINE] rotation={info['theta_deg']:.3f} deg, "
                  f"scale=({info['scale_x']:.6f}, {info['scale_y']:.6f}), "
                  f"shear={info['shear']:.6f}, "
                  f"translation(dy,dx)=({info['trans_y']:.2f}, {info['trans_x']:.2f})")

        warped_band = warp(
            images[ib],
            inverse_map=model.inverse,
            output_shape=out_shape,
            order=1,
            mode=mode,
            preserve_range=True,
        )
        
        # 2. Create a grid of every integer pixel in the OUTPUT image
        rows, cols = np.indices(out_shape)
        out_coords = np.column_stack((cols.ravel(), rows.ravel()))
        
        # 3. Map every output pixel back to the ORIGINAL image space
        # This gives us the fractional [x, y] coordinates in the source image
        src_coords = model.inverse(out_coords)
        src_x = src_coords[:, 0].reshape(out_shape)
        src_y = src_coords[:, 1].reshape(out_shape)
        
        # 4. Define your "Half-Pixel" boundary logic
        # Original image bounds are [0, width-1] and [0, height-1]
        # h, w = images[ib].shape
        mask = (src_x >= -0.5) & (src_x < W - 0.5) & \
               (src_y >= -0.5) & (src_y < H - 0.5)
        
        # 5. Apply the zero-background to pixels outside the half-pixel range
        warped_band[~mask] = 0

        warped[ib] = warped_band.astype(images[0].dtype)

    # --- 2 & 3) NIR group (optional) ---
    if nir_idxs is not None and len(nir_idxs) > 0 and ref_nir is not None:

        # valid mask for ref_nir (for local registrations)
        valid_ref_nir = get_valid_mask_(ref_nir)

        if verbose:
            print(f"\n[STEP 2] Register ref_nir = {ref_nir} to ref_vis = {ref_vis}")

        # 2) ref_nir -> ref_vis
        if verbose:
            print(f"\n[NIR-REF] ref_nir {ref_nir} -> ref_vis {ref_vis}")

        model_nref_to_vis = estimate_affine_from_sobel_with_mask_saturation(
            ref=ref_vis_im,
            mov=images[ref_nir],
            valid_ref=valid_ref_vis,
            valid_mov=valid_ref_nir,
            n_keypoints=n_keypoints,
            fast_threshold=fast_threshold,
            sat_threshold=sat_threshold,
            verbose=verbose,
            use_sobel=use_sobel,          # <-- NEW
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            max_per_cell=max_per_cell,
            min_inlier_ratio=min_inlier_ratio,
            min_inliers=min_inliers,
        )

        if model_nref_to_vis is None:
            if verbose:
                print(f"  [WARN] Using identity transform for NIR ref {ref_nir}")
            model_nref_to_vis = AffineTransform()

        models[ref_nir] = model_nref_to_vis

        if verbose:
            info = decompose_affine(model_nref_to_vis)
            print(f"  [AFFINE] rotation={info['theta_deg']:.3f} deg, "
                  f"scale=({info['scale_x']:.6f}, {info['scale_y']:.6f}), "
                  f"shear={info['shear']:.6f}, "
                  f"translation(dy,dx)=({info['trans_y']:.3f}, {info['trans_x']:.3f})")

        warped_band = warp(
            images[ref_nir],
            inverse_map=model_nref_to_vis.inverse,
            output_shape=out_shape,
            order=1,
            mode=mode,
            preserve_range=True,
        )
        # 2. Create a grid of every integer pixel in the OUTPUT image
        rows, cols = np.indices(out_shape)
        out_coords = np.column_stack((cols.ravel(), rows.ravel()))
        
        # 3. Map every output pixel back to the ORIGINAL image space
        # This gives us the fractional [x, y] coordinates in the source image
        src_coords = model_nref_to_vis.inverse.inverse(out_coords)
        src_x = src_coords[:, 0].reshape(out_shape)
        src_y = src_coords[:, 1].reshape(out_shape)
        
        # 4. Define your "Half-Pixel" boundary logic
        # Original image bounds are [0, width-1] and [0, height-1]
        # h, w = images[ib].shape
        mask = (src_x >= -0.5) & (src_x < W - 0.5) & \
               (src_y >= -0.5) & (src_y < H - 0.5)
        
        # 5. Apply the zero-background to pixels outside the half-pixel range
        warped_band[~mask] = 0

        warped[ref_nir] = warped_band.astype(images[0].dtype)

        # 3) Other NIR bands: local -> ref_nir, then compose -> ref_vis
        nir_ref_im = images[ref_nir]

        if verbose:
            print(f"\n[STEP 3] Register remaining NIR bands to ref_nir = {ref_nir} "
                  "and compose into ref_vis frame")

        for ib in nir_idxs:
            if ib == ref_nir:
                continue

            if verbose:
                print(f"\n[NIR] Band {ib} -> ref_nir {ref_nir} (local), then -> ref_vis")

            valid_mov = get_valid_mask_(ib)

            # ---- local model: ib -> ref_nir ----
            model_local = estimate_affine_from_sobel_with_mask_saturation(
                ref=nir_ref_im,
                mov=images[ib],
                valid_ref=valid_ref_nir,
                valid_mov=valid_mov,
                n_keypoints=n_keypoints,
                fast_threshold=fast_threshold,
                sat_threshold=sat_threshold,
                verbose=verbose,
                use_sobel=use_sobel,          # <-- NEW
                grid_rows=grid_rows,
                grid_cols=grid_cols,
                max_per_cell=max_per_cell,
                min_inlier_ratio=min_inlier_ratio,
                min_inliers=min_inliers,
            )

            if model_local is None:
                if verbose:
                    print(f"  [WARN] Using identity (local) transform for NIR band {ib}")
                model_local = AffineTransform()

            # ---- Compose: ib -> ref_vis = (ref_nir -> ref_vis) ∘ (ib -> ref_nir) ----
            M_local  = model_local.params
            M_bridge = model_nref_to_vis.params
            M_global = M_bridge @ M_local
            model_global = AffineTransform(matrix=M_global)

            models[ib] = model_global

            if verbose:
                print("  [LOCAL AFFINE]   Band -> ref_nir")
                infoL = decompose_affine(model_local)
                print(f"    rotation={infoL['theta_deg']:.3f} deg, "
                      f"scale=({infoL['scale_x']:.6f}, {infoL['scale_y']:.6f}), "
                      f"shear={infoL['shear']:.6f}, "
                      f"translation(dy,dx)=({infoL['trans_y']:.3f}, {infoL['trans_x']:.3f})")

                print("  [BRIDGE AFFINE]  ref_nir -> ref_vis")
                infoB = decompose_affine(model_nref_to_vis)
                print(f"    rotation={infoB['theta_deg']:.3f} deg, "
                      f"scale=({infoB['scale_x']:.6f}, {infoB['scale_y']:.6f}), "
                      f"shear={infoB['shear']:.6f}, "
                      f"translation(dy,dx)=({infoB['trans_y']:.3f}, {infoB['trans_x']:.3f})")

                print("  [GLOBAL AFFINE]  Band -> ref_vis (BRIDGE ∘ LOCAL)")
                infoG = decompose_affine(model_global)
                print(f"    rotation={infoG['theta_deg']:.3f} deg, "
                      f"scale=({infoG['scale_x']:.6f}, {infoG['scale_y']:.6f}), "
                      f"shear={infoG['shear']:.6f}, "
                      f"translation(dy,dx)=({infoG['trans_y']:.3f}, {infoG['trans_x']:.3f})")

            warped_band = warp(
                images[ib],
                inverse_map=model_global.inverse,
                output_shape=out_shape,
                order=1,
                mode=mode,
                preserve_range=True,
            )
            # 2. Create a grid of every integer pixel in the OUTPUT image
            rows, cols = np.indices(out_shape)
            out_coords = np.column_stack((cols.ravel(), rows.ravel()))
            
            # 3. Map every output pixel back to the ORIGINAL image space
            # This gives us the fractional [x, y] coordinates in the source image
            src_coords = model_global.inverse(out_coords)
            src_x = src_coords[:, 0].reshape(out_shape)
            src_y = src_coords[:, 1].reshape(out_shape)
            
            # 4. Define your "Half-Pixel" boundary logic
            # Original image bounds are [0, width-1] and [0, height-1]
            # h, w = images[ib].shape
            mask = (src_x >= -0.5) & (src_x < W - 0.5) & \
                   (src_y >= -0.5) & (src_y < H - 0.5)
            
            # 5. Apply the zero-background to pixels outside the half-pixel range
            warped_band[~mask] = 0
            
            warped[ib] = warped_band.astype(images[0].dtype)


    # Any bands not in vis_idxs or nir_idxs and without model -> just copy as is
    for k in range(n_bands):
        if warped[k] is None:
            if verbose:
                print(f"\n[INFO] Band {k} not in VIS/NIR groups; copying without warp.")
            models[k] = AffineTransform()
            warped[k] = images[k]

    stack = np.stack(warped, axis=0)
    return stack, models, out_shape
