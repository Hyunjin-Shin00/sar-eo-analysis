# =============================================================================
# Sentinel-1 GRD 자동 전처리 및 수체·홍수 탐지
# ZIP(SAFE) 원본 + 전처리된 TIF(선형 σ0) 모두 지원 + 배치 모드
# 파일명: s1_processor6.py
# =============================================================================

import os
import sys
import gc
import re
import math
import argparse
import numpy as np
from pathlib import Path
from typing import Optional
import rasterio
from rasterio.mask import mask as rio_mask
from shapely.geometry import mapping as shp_mapping
import geopandas as gpd
from scipy.ndimage import binary_erosion, binary_dilation
from skimage.filters import threshold_otsu

# SNAP Python API (ZIP 전처리용; TIF만 쓰면 없어도 동작)
try:
    from esa_snappy import ProductIO, GPF, HashMap, jpy
    _SNAP_OK = True
except Exception:
    _SNAP_OK = False  # 전처리된 TIF만 쓸 땐 SNAP 없어도 동작


# =============================================================================
# Processor Class
# =============================================================================
class S1LocalProcessor:
    def __init__(self, output_dir):
        self.base_dir = Path(output_dir)
        self.preprocess_dir = self.base_dir / "01_preprocessed"
        self.watermask_dir = self.base_dir / "02_water_masks"
        self.floodmask_dir = self.base_dir / "03_flood_mask"

    # ---------- AOI → geometry (EPSG:4326) ----------
    def _load_aoi_geom(self, aoi_shp: Optional[str]):
        if not aoi_shp:
            return None
        gdf = gpd.read_file(aoi_shp).to_crs("EPSG:4326")
        return gdf.unary_union

    # ---------- AOI → WKT (SNAP용) ----------
    def _aoi_to_wkt(self, aoi_shp: Optional[str]):
        geom = self._load_aoi_geom(aoi_shp)
        return "" if geom is None else geom.wkt

    # ---------- ZIP → 전처리 파이프라인 (선형 σ0, dB도 추가 저장) ----------
    def _s1_grd_preprocessing_single(self, product_path, output_dir, polarization, dem_path=None, aoi_shp=None):
        if not _SNAP_OK:
            raise RuntimeError("SNAP이 필요합니다. (ZIP 입력 전처리)")
        Integer = jpy.get_type('java.lang.Integer')
        Double  = jpy.get_type('java.lang.Double')
        Boolean = jpy.get_type('java.lang.Boolean')

        short_name = Path(product_path).stem
        out_tif = Path(output_dir) / f"{short_name}_{polarization}_processed.tif"
        out_tif.parent.mkdir(parents=True, exist_ok=True)
        if out_tif.exists():
            print(f"   - 이미 처리됨: {out_tif.name}")
        else:
            print(f"\n[전처리 시작] {Path(product_path).name}")
            product = ProductIO.readProduct(str(product_path))
            params = HashMap()

            # 1) Apply-Orbit-File
            params.clear()
            params.put('Orbit State Vectors', 'Sentinel Precise (Auto Download)')
            params.put('Polynomial Degree', Integer(3))
            params.put('Continue on Failure', Boolean(True))
            product = GPF.createProduct('Apply-Orbit-File', params, product)

            # 2) Subset (AOI가 있으면)
            params.clear()
            wkt = self._aoi_to_wkt(aoi_shp) if aoi_shp else ''
            if wkt and wkt.strip():
                params.put('geoRegion', wkt)
            params.put('subSamplingX', Integer(1))
            params.put('subSamplingY', Integer(1))
            params.put('fullSwath', Boolean(False))
            params.put('copyMetadata', Boolean(True))
            product = GPF.createProduct('Subset', params, product)

            # 3) ThermalNoiseRemoval
            params.clear()
            params.put('selectedPolarisations', '')
            params.put('removeThermalNoise', Boolean(True))
            params.put('reIntroduceThermalNoise', Boolean(False))
            product = GPF.createProduct('ThermalNoiseRemoval', params, product)

            # 4) Remove-GRD-Border-Noise
            params.clear()
            params.put('selectedPolarisations', '')
            params.put('borderLimit', Integer(500))
            params.put('trimThreshold', Double(50.0))
            product = GPF.createProduct('Remove-GRD-Border-Noise', params, product)

            # 5) Land-Sea-Mask (옵션성 세팅; 여기선 DEM만 사용)
            params.clear()
            params.put('landMask', Boolean(False))
            params.put('useSRTM', Boolean(True))
            product = GPF.createProduct('Land-Sea-Mask', params, product)

            # 6) Calibration (linear σ0)
            params.clear()
            params.put('auxFile', 'Product Auxiliary File')
            params.put('outputImageInComplex', Boolean(False))
            params.put('outputImageScaleInDb', Boolean(False))
            params.put('createGammaBand', Boolean(False))
            params.put('createBetaBand', Boolean(False))
            params.put('selectedPolarisations', polarization)
            params.put('outputSigmaBand', Boolean(True))
            params.put('outputGammaBand', Boolean(False))
            params.put('outputBetaBand', Boolean(False))
            product = GPF.createProduct('Calibration', params, product)

            # 7) Speckle-Filter
            params.clear()
            params.put('filter', 'Lee Sigma')
            params.put('filterSizeX', Integer(3))
            params.put('filterSizeY', Integer(3))
            params.put('estimateENL', Boolean(True))
            params.put('enl', Double(1.0))
            params.put('numLooksStr', '1')
            params.put('windowSize', '7x7')
            params.put('targetWindowSizeStr', '3x3')
            params.put('sigmaStr', '0.9')
            product = GPF.createProduct('Speckle-Filter', params, product)

            # 8) Terrain-Correction
            params.clear()
            if dem_path:
                params.put('demName', 'External DEM')
                params.put('externalDEMFile', dem_path)
            else:
                params.put('demName', 'SRTM 1Sec HGT')
                params.put('externalDEMFile', '')
            params.put('externalDEMNoDataValue', Double(0.0))
            params.put('externalDEMApplyEGM', Boolean(True))
            params.put('demResamplingMethod', 'BILINEAR_INTERPOLATION')
            params.put('imgResamplingMethod', 'BILINEAR_INTERPOLATION')
            params.put('pixelSpacingInMeter', Double(10.0))
            params.put('mapProjection', 'EPSG:3857')
            params.put('alignToStandardGrid', Boolean(True))
            params.put('standardGridOriginX', Double(0.0))
            params.put('standardGridOriginY', Double(0.0))
            params.put('nodataValueAtSea', Boolean(True))
            params.put('saveSelectedSourceBand', Boolean(True))
            product = GPF.createProduct('Terrain-Correction', params, product)

            # 9) Write (linear σ0)
            ProductIO.writeProduct(product, str(out_tif), 'GeoTIFF')
            product.closeIO()
            gc.collect()
            print(f"   - 전처리 완료: {out_tif.name}")

        # dB GeoTIFF 동시 생성
        self._ensure_db_tif(out_tif)
        return out_tif

    # ---------- 전처리된 TIF(선형 σ0) → dB GeoTIFF 생성 (필수) ----------
    def _ensure_db_tif(self, linear_tif: Path):
        out_db_tif = linear_tif.with_name(linear_tif.stem + "_dB.tif")
        if out_db_tif.exists():
            return out_db_tif
        with rasterio.open(linear_tif) as src:
            prof = src.profile.copy()
            prof.update(dtype="float32", nodata=-9999.0, compress="LZW", tiled=False)
            with rasterio.open(out_db_tif, "w", **prof) as dst:
                for i in range(1, src.count + 1):
                    arr = src.read(i).astype("float32")
                    arr[arr <= 0] = np.nan
                    db = 10.0 * np.log10(arr)
                    db[~np.isfinite(db)] = -9999.0
                    dst.write(db.astype("float32"), i)
                dst.update_tags(0, UNIT="dB", DESCRIPTION="sigma0 in dB (10*log10(linear sigma0))")
        print(f"   - dB 영상 저장 완료: {out_db_tif.name}")
        return out_db_tif

    # ---------- 전처리된 TIF 입력 처리 (AOI 클립 + dB 생성) ----------
    def _prepare_from_preprocessed_tif(self, tif_path: str, aoi_shp: Optional[str]):
        in_path = Path(tif_path)
        # 필요 시 AOI로 클립
        if aoi_shp:
            aoi_geom = self._load_aoi_geom(aoi_shp)
            if aoi_geom is not None:
                clipped = self.preprocess_dir / f"{in_path.stem}_AOI.tif"
                clipped.parent.mkdir(parents=True, exist_ok=True)
                if not clipped.exists():
                    with rasterio.open(in_path) as src:
                        # AOI를 소스 CRS로 변환
                        aoi_gdf = gpd.GeoDataFrame(geometry=[aoi_geom], crs="EPSG:4326").to_crs(src.crs)
                        geoms = [shp_mapping(aoi_gdf.geometry.iloc[0])]
                        out_img, out_transform = rio_mask(src, geoms, crop=True, all_touched=False)
                        out_meta = src.meta.copy()
                        out_meta.update({
                            "driver": "GTiff",
                            "height": out_img.shape[1],
                            "width": out_img.shape[2],
                            "transform": out_transform,
                            "compress": "LZW"
                        })
                        with rasterio.open(clipped, "w", **out_meta) as dst:
                            dst.write(out_img)
                    print(f"   - AOI 클립 완료: {clipped.name}")
                in_path = clipped
        # dB 생성 보장
        db_path = self._ensure_db_tif(in_path)
        return str(in_path), str(db_path)

    # ---------- Edge Otsu ----------
    def _edge_otsu_thresholding(self, image_data, initial_threshold, iterations):
        valid = np.isfinite(image_data)
        if not np.any(valid):
            return np.zeros_like(image_data, dtype=bool), float(initial_threshold)
        water0 = np.zeros_like(image_data, dtype=bool)
        water0[valid] = image_data[valid] < initial_threshold
        erode = binary_erosion(water0, iterations=1)
        dilate = binary_dilation(water0, iterations=1)
        edges = np.logical_and(dilate, ~erode)
        samples = binary_dilation(edges, iterations=max(1, int(iterations)))
        samples &= valid
        th = threshold_otsu(image_data[samples].astype(np.float32)) if np.any(samples) else initial_threshold
        out = np.zeros_like(water0, dtype=bool)
        out[valid] = image_data[valid] < th
        return out, th

    # ---------- 수체 탐지 (dB 입력 권장; linear여도 내부에서 dB로 변환) ----------
    def _detect_water_body_single(self, tif_path, out_dir, initial_db_thresh=-20.0, edge_buffer=5):
        out_path = Path(out_dir) / f"{Path(tif_path).stem}_watermask.tif"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(tif_path) as src:
            band = src.read(1).astype(np.float32)
            # tif가 이미 dB인지 자동 판별
            is_db = False
            try:
                tags = src.tags(1)
                if "UNIT" in tags and "dB" in str(tags["UNIT"]).lower():
                    is_db = True
            except Exception:
                pass
            if is_db:
                db = band
                db[db <= -5000] = np.nan  # nodata 처리(-9999 등)
            else:
                band[band <= 0] = np.nan
                db = 10.0 * np.log10(band)
                db[~np.isfinite(db)] = np.nan

            msk, th = self._edge_otsu_thresholding(db, initial_db_thresh, edge_buffer)
            meta = src.meta.copy()
            meta.update({'driver': 'GTiff', 'dtype': 'uint8', 'nodata': 0, 'compress': 'LZW'})
            with rasterio.open(out_path, 'w', **meta) as dst:
                dst.write(msk.astype(np.uint8), 1)
        print(f"   - 수체 마스크 생성: {out_path.name} (Otsu={th:.3f} dB)")
        return str(out_path)

    # ---------- 홍수 변화 탐지 ----------
    def detect_flood_gain_loss(self, before_mask, after_mask, emit_stats=False):
        import rasterio
        import numpy as np
        from rasterio.warp import reproject, Resampling

        with rasterio.open(after_mask) as aft:
            after = aft.read(1).astype(np.uint8)
            meta  = aft.meta.copy()
            dst_crs = aft.crs
            dst_transform = aft.transform
            dst_height = aft.height
            dst_width  = aft.width

        with rasterio.open(before_mask) as bef:
            same_grid = (
                bef.crs == dst_crs and
                bef.transform == dst_transform and
                bef.width == dst_width and
                bef.height == dst_height
            )
            if same_grid:
                before = bef.read(1).astype(np.uint8)
            else:
                before = np.zeros((dst_height, dst_width), dtype=np.uint8)
                reproject(
                    source=rasterio.band(bef, 1),
                    destination=before,
                    src_transform=bef.transform, src_crs=bef.crs,
                    dst_transform=dst_transform, dst_crs=dst_crs,
                    resampling=Resampling.nearest
                )

        before_bin = before >= 1
        after_bin  = after  >= 1

        klass = np.zeros(after_bin.shape, dtype=np.uint8)
        klass[np.logical_and(after_bin, ~before_bin)] = 1  # GAIN
        klass[np.logical_and(before_bin, ~after_bin)] = 2  # LOSS

        out_tif = self.floodmask_dir / "flood_change.tif"
        out_tif.parent.mkdir(parents=True, exist_ok=True)
        meta.update({'dtype': 'uint8', 'nodata': 0, 'compress': 'LZW'})
        with rasterio.open(out_tif, 'w', **meta) as dst:
            dst.write(klass, 1)
            try:
                dst.write_colormap(1, {
                    0: (200,200,200,255),  # unchanged
                    1: (0,255,255,255),    # gain
                    2: (255,180,0,255),    # loss
                })
            except Exception:
                pass

        if emit_stats:
            gain_cnt = int((klass == 1).sum())
            loss_cnt = int((klass == 2).sum())
            print(f"[GAIN] pixels={gain_cnt:,}")
            print(f"[LOSS] pixels={loss_cnt:,}")
        print(f"   - 홍수 변화 저장: {out_tif}")
        return str(out_tif)

    # ---------- 날짜 숫자 추출 ----------
    def _extract_date_num(self, name: str) -> int:
        m = re.search(r'(\d{8})', name)
        return int(m.group(1)) if m else -1

    # ---------- 폴더에서 prefix*VV*.tif 중 '가장 최근 날짜' 파일 1장 ----------
    def _pick_file(self, d: Path, prefix: str) -> Optional[Path]:
        cands = list(d.glob(f"{prefix}*VV*.tif"))
        if not cands:
            return None
        cands.sort(key=lambda p: self._extract_date_num(p.name), reverse=True)
        return cands[0]

    # ---------- 배치: 하위 폴더별 SL2 / MS1 한 장씩 수체탐지 (폴더별 결과 분리) ----------
    def run_batch_pairs(self, root_dir: str, aoi_shp: Optional[str]):
        root = Path(root_dir)
        if not root.exists():
            print(f"[WARN] batch_root가 존재하지 않습니다: {root}")
            return
        subdirs = [d for d in sorted(root.iterdir()) if d.is_dir()]
        total = 0
        done = 0
        skipped = 0
        for d in subdirs:
            total += 1
            sl2 = self._pick_file(d, "SL2_")
            ms1 = self._pick_file(d, "MS1_")
            if not sl2 or not ms1:
                print(f"[SKIP] {d.name}: {'SL2 없음' if not sl2 else ''} {'MS1 없음' if not ms1 else ''}")
                skipped += 1
                continue

            # ▶ 출력 목적지: --output_dir/<원래_폴더명>/
            dest_dir = (self.base_dir / d.name)
            dest_dir.mkdir(parents=True, exist_ok=True)

            print(f"[PAIR] {d.name}")
            print(f"   - SL2: {sl2.name}")
            print(f"   - MS1: {ms1.name}")

            # 각 파일 개별 수체탐지 (선형→dB 자동 처리), 결과를 dest_dir에 저장
            for f in (sl2, ms1):
                lin_tif, _ = self._prepare_from_preprocessed_tif(str(f), aoi_shp)
                self._detect_water_body_single(lin_tif, dest_dir)  # ★ 여기서 per-folder 출력

            done += 1

        print(f"\n[배치 요약] 총 폴더: {total}, 처리: {done}, 건너뜀: {skipped}")


    # ---------- 일반 실행 ----------
    def run(self, args):
        aoi_shp = args.aoi_shp
        in_paths = []
        for p in (args.inputs or []):
            pth = Path(p)
            if pth.suffix.lower() == ".zip":
                # ZIP → 전처리 (linear σ0 + dB 생성)
                t = self._s1_grd_preprocessing_single(
                    p, self.preprocess_dir, args.polarization,
                    dem_path=args.dem_path, aoi_shp=aoi_shp
                )
                in_paths.append(str(t))
            else:
                # 전처리된 TIF(선형 σ0) → (AOI 클립 +) dB 생성
                lin_tif, _ = self._prepare_from_preprocessed_tif(p, aoi_shp)
                in_paths.append(lin_tif)

        if len(in_paths) == 0:
            print("입력 파일이 없습니다. (--inputs 또는 --batch_root 사용)")
            return

        # 모든 입력에 대해 개별 수체 탐지
        watermask_paths = []
        for tif in in_paths:
            wm = self._detect_water_body_single(tif, self.watermask_dir)
            watermask_paths.append(wm)

        # 홍수 변화는 옵션으로만 (yes 이고 2장 이상일 때)
        if (args.flood_detection or 'no').lower() == 'yes' and len(in_paths) >= 2:
            # before/after는 파일 수정시간 기준 정렬(파일명에 날짜 없을 수도 있으니)
            tifs_sorted = sorted(in_paths, key=lambda p: Path(p).stat().st_mtime)
            before, after = tifs_sorted[0], tifs_sorted[-1]
            wm_before = self._detect_water_body_single(before, self.watermask_dir)
            wm_after  = self._detect_water_body_single(after,  self.watermask_dir)
            self.detect_flood_gain_loss(
                wm_before, wm_after,
                emit_stats=((args.flood_stats or 'no').lower() == 'yes')
            )

        print("\n✅ 전체 작업 완료.")


# =============================================================================
# Main
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Sentinel-1 GRD 자동 전처리 및 홍수 탐지 (ZIP + 전처리 TIF 지원 + 배치 모드)")
    parser.add_argument('--inputs', nargs='+', required=False, help='ZIP(.SAFE.zip) 또는 전처리된 TIF(선형 σ0)')
    parser.add_argument('--batch_root', required=False, help='루트 폴더: 하위 폴더별로 SL2*VV*.tif + MS1*VV*.tif 한 쌍을 찾아 수체탐지만 수행')
    parser.add_argument('--output_dir', required=True)
    parser.add_argument('--polarization', default='VV', choices=['VV', 'VH'], help='ZIP 전처리시에만 사용')
    parser.add_argument('--aoi_shp', help='AOI shapefile (ZIP/전처리TIF 모두에 대해 클립)')
    parser.add_argument('--dem_path', help='External DEM (ZIP 전처리시에만 사용)')
    parser.add_argument('--flood_detection', choices=['yes', 'no'], default='yes')
    parser.add_argument('--flood_stats', choices=['yes', 'no'], default='yes')
    args = parser.parse_args()

    proc = S1LocalProcessor(args.output_dir)

    if args.batch_root:
        # 배치 모드: 폴더별로 SL2/MS1 한 장씩 찾아 '수체탐지만' 수행
        proc.run_batch_pairs(args.batch_root, args.aoi_shp)
    else:
        proc.run(args)


if __name__ == "__main__":
    main()
