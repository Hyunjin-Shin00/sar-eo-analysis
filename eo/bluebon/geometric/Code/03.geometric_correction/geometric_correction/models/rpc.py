"""
RPC/RFM Models Module

This module contains the RPC and RFM model classes for geometric correction.
"""

from typing import Dict, Any, List, Optional, Tuple
from config_example import VERBOSE
import json
import numpy as np
from rasterio.control import GroundControlPoint
from pyproj import CRS, Transformer
from sklearn.linear_model import Ridge


class RPCModel:
    """RPC 모델 파라미터를 저장하는 (단순) 클래스"""
    def __init__(self, rpc_dict: Dict[str, Any]):
        self.line_off = rpc_dict['LINE_OFF']
        self.samp_off = rpc_dict['SAMP_OFF']
        self.lat_off = rpc_dict['LAT_OFF']
        self.lon_off = rpc_dict['LONG_OFF']
        self.height_off = rpc_dict['HEIGHT_OFF']
        self.line_scale = rpc_dict['LINE_SCALE']
        self.samp_scale = rpc_dict['SAMP_SCALE']
        self.lat_scale = rpc_dict['LAT_SCALE']
        self.lon_scale = rpc_dict['LONG_SCALE']
        self.height_scale = rpc_dict['HEIGHT_SCALE']
        self.line_num = np.array(rpc_dict['LINE_NUM_COEFF'])
        self.line_den = np.array(rpc_dict['LINE_DEN_COEFF'])
        self.samp_num = np.array(rpc_dict['SAMP_NUM_COEFF'])
        self.samp_den = np.array(rpc_dict['SAMP_DEN_COEFF'])


class RPCGenerator:
    """
    [수정된] RPC 생성 클래스
    - ✅ (버그 수정) UTM -> 경위도 좌표 변환 기능 추가
    - ✅ (안정성) np.linalg.lstsq 대신 Ridge 회귀를 사용하여 수치적 안정성 확보
    """
    def __init__(self, source_crs: Any, min_gcps: int = 20, use_ransac: bool = False, ridge_alpha: float = 0.01, use_2d_mode: bool = False):
        """
        RPCGenerator를 초기화합니다.
        """
        self.min_gcps = min_gcps
        self.use_ransac = use_ransac
        self.source_crs = source_crs
        self.use_2d_mode = use_2d_mode  # 2D RFM 모드 추가
        self.rpc_params: Optional[Dict[str, Any]] = None
        self.inlier_gcps: Optional[List[GroundControlPoint]] = None
        
        # Ridge 회귀 모델 (수치적 안정성 확보용)
        self.ridge_solver = Ridge(alpha=ridge_alpha, fit_intercept=False, solver='auto')
        if VERBOSE:
            print(f"   ℹ️  RPCGenerator 초기화 (Ridge alpha={ridge_alpha})")
        
        if self.source_crs is None:
            print("⚠️ RPCGenerator: source_crs가 None입니다. GCP 좌표가 이미 경위도라고 가정합니다.")
            self.is_projected = False
        else:
            try:
                self.pyproj_crs = CRS.from_user_input(source_crs)
                self.is_projected = self.pyproj_crs.is_projected
                if self.is_projected:
                    if VERBOSE:
                        print(f"🌍 RPCGenerator: GCP 좌표계 {self.pyproj_crs.name} (투영) 감지. WGS84로 변환합니다.")
                    self.transformer = Transformer.from_crs(self.pyproj_crs, "EPSG:4326", always_xy=True)
                else:
                    if VERBOSE:
                        print(f"🌍 RPCGenerator: GCP 좌표계 {self.pyproj_crs.name} (지리) 감지. 변환하지 않습니다.")
                    self.transformer = None
            except Exception as e:
                print(f"❌ RPCGenerator: CRS 파싱 실패: {e}")
                self.is_projected = False
                self.transformer = None

    def _convert_to_lonlat(self, gcps: List[GroundControlPoint]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        GCP 좌표를 경위도로 변환합니다.
        
        Args:
            gcps: Ground Control Points
            
        Returns:
            Tuple[np.ndarray, np.ndarray, np.ndarray]: (lons, lats, heights)
        """
        if not self.is_projected or self.transformer is None:
            # 이미 경위도이거나 변환기가 없는 경우
            lons = np.array([gcp.x for gcp in gcps])
            lats = np.array([gcp.y for gcp in gcps])
            heights = np.array([gcp.z for gcp in gcps])
            if VERBOSE:
                print(f"   ℹ️  GCP 좌표 변환 생략 (이미 경위도 또는 변환기 없음)")
        else:
            # 투영 좌표를 경위도로 변환
            lons = np.array([gcp.x for gcp in gcps])
            lats = np.array([gcp.y for gcp in gcps])
            heights = np.array([gcp.z for gcp in gcps])
            
            if VERBOSE:
                print(f"   🔄 GCP 좌표 변환 중... ({len(gcps)}개 점)")
                print(f"      원본 범위: X[{lons.min():.2f}, {lons.max():.2f}], Y[{lats.min():.2f}, {lats.max():.2f}]")
            
            # 좌표 변환 (UTM -> WGS84)
            lons, lats = self.transformer.transform(lons, lats)
            
            if VERBOSE:
                print(f"      변환 후: Lon[{lons.min():.6f}, {lons.max():.6f}], Lat[{lats.min():.6f}, {lats.max():.6f}]")
                print(f"      고도 범위: [{heights.min():.2f}, {heights.max():.2f}] m")
        
        return lons, lats, heights

    def _poly(self, L: np.ndarray, P: np.ndarray, H: np.ndarray) -> np.ndarray:
        """
        3D RFM 다항식 항들을 생성합니다.
        
        Args:
            L: 정규화된 경도
            P: 정규화된 위도  
            H: 정규화된 고도
            
        Returns:
            np.ndarray: 다항식 항들 (20개)
        """
        if self.use_2d_mode:
            # 2D RFM 모드: H 항 제거
            return np.column_stack([
                np.ones_like(L), L, P, L*P, L*L, P*P, P*L, L*L*L, P*L*L, P*P*L, P*P*P, 
                L*L*L*L, P*L*L*L, P*P*L*L, P*P*P*L, P*P*P*P, L*L*L*L*L, P*L*L*L*L, P*P*L*L*L, P*P*P*L*L
            ])
        else:
            # 3D RFM 모드: 표준 20개 항
            return np.column_stack([
                np.ones_like(L), L, P, H, L*P, L*H, P*H, L*L, P*P, H*H,
                P*L, H*L*L, H*L*P, H*P*P, L*L*L, P*L*L, P*P*L, P*P*P, H*H*L, H*H*P
            ])

    def _estimate_rpc_coefficients(self, gcps: List[GroundControlPoint], img_width: int, img_height: int) -> Optional[Dict[str, Any]]:
        """
        RPC 계수를 추정합니다.
        
        Args:
            gcps: Ground Control Points
            img_width: 이미지 너비
            img_height: 이미지 높이
            
        Returns:
            Optional[Dict[str, Any]]: RPC 파라미터 딕셔너리
        """
        print(f"   🔧 RPC 계수 추정 중... ({len(gcps)}개 GCP)")
        
        # 1. 좌표 변환 (UTM -> 경위도)
        lons, lats, heights = self._convert_to_lonlat(gcps)
        
        # 2. 정규화 파라미터 계산
        rpc_params = {
            'LINE_OFF': img_height / 2.0,
            'SAMP_OFF': img_width / 2.0,
            'LAT_OFF': np.mean(lats),
            'LONG_OFF': np.mean(lons),
            'HEIGHT_OFF': np.mean(heights),
            'LINE_SCALE': max(img_height / 2.0, 1.0),
            'SAMP_SCALE': max(img_width / 2.0, 1.0),
            'LAT_SCALE': max(np.std(lats) * 2.0, 1e-10),
            'LONG_SCALE': max(np.std(lons) * 2.0, 1e-10),
            'HEIGHT_SCALE': max(np.std(heights) * 2.0, 1e-6)
        }
        
        # 2D 모드인 경우 HEIGHT_SCALE을 1로 설정
        if self.use_2d_mode:
            rpc_params['HEIGHT_OFF'] = 0.0
            rpc_params['HEIGHT_SCALE'] = 1.0
            print(f"   ℹ️  2D RFM 모드: HEIGHT_SCALE = 1.0")
        
        # 3. 좌표 정규화
        P = (lats - rpc_params['LAT_OFF']) / rpc_params['LAT_SCALE']
        L = (lons - rpc_params['LONG_OFF']) / rpc_params['LONG_SCALE']
        H = (heights - rpc_params['HEIGHT_OFF']) / rpc_params['HEIGHT_SCALE']
        
        # 픽셀 좌표 정규화
        rows = np.array([gcp.row for gcp in gcps])
        cols = np.array([gcp.col for gcp in gcps])
        R = (rows - rpc_params['LINE_OFF']) / rpc_params['LINE_SCALE']
        C = (cols - rpc_params['SAMP_OFF']) / rpc_params['SAMP_SCALE']
        
        if VERBOSE:
            print(f"   📊 정규화 파라미터:")
            print(f"      LAT_OFF: {rpc_params['LAT_OFF']:.6f}°, LONG_OFF: {rpc_params['LONG_OFF']:.6f}°")
            print(f"      LAT_SCALE: {rpc_params['LAT_SCALE']:.6f}°, LONG_SCALE: {rpc_params['LONG_SCALE']:.6f}°")
            print(f"      HEIGHT_SCALE: {rpc_params['HEIGHT_SCALE']:.2f}m")
        
        # 4. 다항식 행렬 구성
        poly = self._poly(L, P, H)  # shape: (n_gcps, 20)
        A = poly  # scikit-learn 입력 형식: (샘플 N, 특징 20)
        
        if VERBOSE:
            print(f"   📐 다항식 행렬: {A.shape}")
        
        # 5. Ridge 회귀로 계수 추정 (분모 상수 1 고정, 분자만 추정)
        try:
            # 분모는 상수 1로 고정하고 분자만 추정 (타깃 누수 방지)
            # R = num / 1, C = num / 1 형태로 단순화
            
            # Line (row) 계수 추정: A * num = R
            self.ridge_solver.fit(A, R)
            line_num_coeff = self.ridge_solver.coef_.copy()
            # 분모 계수는 첫 번째 항만 1, 나머지는 작은 값으로 설정
            line_den_coeff = np.array([1.0] + [0.001] * (len(line_num_coeff) - 1))

            # Sample (col) 계수 추정: A * num = C  
            self.ridge_solver.fit(A, C)
            samp_num_coeff = self.ridge_solver.coef_.copy()
            # 분모 계수는 첫 번째 항만 1, 나머지는 작은 값으로 설정
            samp_den_coeff = np.array([1.0] + [0.001] * (len(samp_num_coeff) - 1))

            if VERBOSE:
                print(f"   ✅ Ridge 회귀 성공 (분모 상수 1 고정)")
                print(f"      Line num 범위: [{line_num_coeff.min():.6f}, {line_num_coeff.max():.6f}]")
                print(f"      Samp num 범위: [{samp_num_coeff.min():.6f}, {samp_num_coeff.max():.6f}]")

        except Exception as e:
            print(f"   ❌ Ridge 회귀 실패: {e}")
            return None
        
        # 6. RPC 파라미터 완성
        rpc_params.update({
            'LINE_NUM_COEFF': line_num_coeff.tolist(),
            'LINE_DEN_COEFF': line_den_coeff.tolist(),
            'SAMP_NUM_COEFF': samp_num_coeff.tolist(),
            'SAMP_DEN_COEFF': samp_den_coeff.tolist()
        })
        
        return rpc_params

    def _ransac_rpc(self, gcps: List[GroundControlPoint], img_width: int, img_height: int, 
                    max_trials: int = 50, residual_threshold: float = 2.0) -> Tuple[Optional[Dict[str, Any]], List[GroundControlPoint]]:
        """
        RANSAC을 사용하여 RPC 모델을 생성합니다.
        
        Args:
            gcps: Ground Control Points
            img_width: 이미지 너비
            img_height: 이미지 높이
            max_trials: 최대 시도 횟수
            residual_threshold: 잔차 임계값 (픽셀)
            
        Returns:
            Tuple[Optional[Dict[str, Any]], List[GroundControlPoint]]: (RPC 파라미터, inlier GCPs)
        """
        import random
        
        n_gcps = len(gcps)
        min_samples = max(self.min_gcps, 20)  # 최소 샘플 수
        
        if n_gcps < min_samples:
            print(f"   ❌ RANSAC: GCP 개수 부족 {n_gcps} < {min_samples}")
            return None, []
        
        best_model = None
        best_inliers = []
        best_score = 0
        
        if VERBOSE:
            print(f"   🔄 RANSAC 시작: {n_gcps}개 GCP, 최소 {min_samples}개 샘플")
        
        for trial in range(max_trials):
            # 무작위 샘플 선택
            sample_indices = random.sample(range(n_gcps), min_samples)
            sample_gcps = [gcps[i] for i in sample_indices]
            
            try:
                # 샘플로 RPC 모델 생성
                model = self._estimate_rpc_coefficients(sample_gcps, img_width, img_height)
                if model is None:
                    continue
                
                # 모든 GCP에 대해 잔차 계산
                residuals = []
                for gcp in gcps:
                    try:
                        pred_row, pred_col = self._rpc_forward(
                            np.array([gcp.x]), np.array([gcp.y]), np.array([gcp.z])
                        )
                        residual = np.sqrt((pred_row[0] - gcp.row)**2 + (pred_col[0] - gcp.col)**2)
                        residuals.append(residual)
                    except:
                        residuals.append(float('inf'))
                
                # Inlier 판단
                inlier_mask = np.array(residuals) <= residual_threshold
                n_inliers = np.sum(inlier_mask)
                
                # 최고 모델 업데이트
                if n_inliers > best_score:
                    best_score = n_inliers
                    best_model = model
                    best_inliers = [gcps[i] for i in range(n_gcps) if inlier_mask[i]]
                    
                    if VERBOSE:
                        print(f"   📊 Trial {trial+1}: {n_inliers}/{n_gcps} inliers (잔차 ≤ {residual_threshold}px)")
                
                # 조기 종료 조건
                if n_inliers >= n_gcps * 0.95:  # 95% 이상 inlier
                    break
                    
            except Exception as e:
                continue
        
        if best_model is None or len(best_inliers) < min_samples:
            print(f"   ❌ RANSAC 실패: 최고 모델 없음 또는 inlier 부족")
            return None, []
        
        print(f"   ✅ RANSAC 완료: {len(best_inliers)}/{n_gcps} inliers ({len(best_inliers)/n_gcps*100:.1f}%)")
        
        # 최종 모델을 모든 inlier로 재생성
        final_model = self._estimate_rpc_coefficients(best_inliers, img_width, img_height)
        return final_model, best_inliers

    def generate_rpc(self, gcps: List[GroundControlPoint], img_width: int, img_height: int) -> Optional[Dict[str, Any]]:
        """
        RPC 모델을 생성합니다.
        
        Args:
            gcps: Ground Control Points
            img_width: 이미지 너비
            img_height: 이미지 높이
            
        Returns:
            Optional[Dict[str, Any]]: RPC 파라미터 딕셔너리
        """
        if len(gcps) < self.min_gcps:
            print(f"   ❌ GCP 개수 부족: {len(gcps)} < {self.min_gcps}")
            return None
        
        if False and self.use_ransac:
            if VERBOSE:
                print(f"   🔄 RANSAC RPC 생성 중...")
            rpc_params, inlier_gcps = self._ransac_rpc(gcps, img_width, img_height)
            if rpc_params is None:
                return None
            self.inlier_gcps = inlier_gcps
        else:
            if VERBOSE:
                print(f"   🔄 직접 RPC 생성 중...")
            rpc_params = self._estimate_rpc_coefficients(gcps, img_width, img_height)
            if rpc_params is None:
                return None
            self.inlier_gcps = gcps
        
        # RPC 파라미터 저장
        self.rpc_params = rpc_params
        
        print(f"   ✅ RPC 모델 생성 완료")
        return rpc_params

    def save_rpc(self, json_path: str) -> None:
        """RPC 파라미터를 JSON으로 저장"""
        if self.rpc_params is None:
            raise ValueError("RPC 파라미터가 없습니다. generate_rpc 후 저장하세요.")
        with open(json_path, 'w') as f:
            json.dump(self.rpc_params, f, indent=2)

    def _rpc_forward(self, lons: np.ndarray, lats: np.ndarray, heights: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        RPC 모델을 사용하여 지리 좌표를 픽셀 좌표로 변환합니다.
        
        Args:
            lons: 경도 배열
            lats: 위도 배열
            heights: 고도 배열
            
        Returns:
            Tuple[np.ndarray, np.ndarray]: (rows, cols)
        """
        if self.rpc_params is None:
            raise ValueError("RPC 모델이 생성되지 않았습니다.")
        
        # 좌표 정규화
        P = (lats - self.rpc_params['LAT_OFF']) / max(self.rpc_params['LAT_SCALE'], 1e-10)
        L = (lons - self.rpc_params['LONG_OFF']) / max(self.rpc_params['LONG_SCALE'], 1e-10)
        H = (heights - self.rpc_params['HEIGHT_OFF']) / max(self.rpc_params['HEIGHT_SCALE'], 1e-6)
        
        # RPC 계수 크기 확인 및 조정
        line_num_coeff = np.array(self.rpc_params['LINE_NUM_COEFF'])
        line_den_coeff = np.array(self.rpc_params['LINE_DEN_COEFF'])
        samp_num_coeff = np.array(self.rpc_params['SAMP_NUM_COEFF'])
        samp_den_coeff = np.array(self.rpc_params['SAMP_DEN_COEFF'])
        
        # 계수 크기에 맞춰 항 계산
        max_coeff_len = max(len(line_num_coeff), len(line_den_coeff), len(samp_num_coeff), len(samp_den_coeff))
        
        if max_coeff_len == 20:
            # 20개 항 계산 (3D RFM)
            poly = np.array(self._poly(L, P, H))
        elif max_coeff_len == 21:
            # 21개 항 계산 (추가 항 포함)
            poly = np.array(self._poly(L, P, H))
            if len(poly) < 21:
                poly = np.pad(poly, (0, 21 - len(poly)), 'constant')
        else:
            raise ValueError(f"지원되지 않는 RPC 계수 개수: {max_coeff_len}")
        
        # 계수 크기 맞춤
        if len(line_num_coeff) < max_coeff_len:
            line_num_coeff = np.pad(line_num_coeff, (0, max_coeff_len - len(line_num_coeff)), 'constant')
        if len(line_den_coeff) < max_coeff_len:
            line_den_coeff = np.pad(line_den_coeff, (0, max_coeff_len - len(line_den_coeff)), 'constant')
        if len(samp_num_coeff) < max_coeff_len:
            samp_num_coeff = np.pad(samp_num_coeff, (0, max_coeff_len - len(samp_num_coeff)), 'constant')
        if len(samp_den_coeff) < max_coeff_len:
            samp_den_coeff = np.pad(samp_den_coeff, (0, max_coeff_len - len(samp_den_coeff)), 'constant')
        
        # Line (row) 계산
        line_num = np.dot(poly, line_num_coeff)
        line_den = np.dot(poly, line_den_coeff)
        
        # Sample (col) 계산
        samp_num = np.dot(poly, samp_num_coeff)
        samp_den = np.dot(poly, samp_den_coeff)
        
        # 정규화 해제
        rows = line_num / line_den * self.rpc_params['LINE_SCALE'] + self.rpc_params['LINE_OFF']
        cols = samp_num / samp_den * self.rpc_params['SAMP_SCALE'] + self.rpc_params['SAMP_OFF']
        
        return rows, cols


# ==============================================================================
# RPCGeneratorV2: 표준화/안정화된 3D RFM(RPC) 추정기 (사용자 제안 사양)
#  - UTM → WGS84(경위도) 자동 변환
#  - 표준 20항 다항식
#  - 분자/분모 동시 추정(분모 상수항=1)
#  - 평탄 지형 시 2D RFM 전환 옵션
# ==============================================================================
class RPCGeneratorV2:
    def __init__(self,
                 source_crs: Any,
                 min_gcps: int = 20,
                 use_ransac: bool = False,
                 ridge_alpha: float = 1.0,
                 force_2d_rfm: bool = False,
                 flat_terrain_threshold_m: float = 5.0):
        self.min_gcps = min_gcps
        self.use_ransac = use_ransac
        self.source_crs = source_crs
        self.force_2d_rfm = force_2d_rfm
        self.flat_terrain_threshold_m = flat_terrain_threshold_m
        self.rpc_params: Optional[Dict[str, Any]] = None
        self.inlier_gcps: Optional[List[GroundControlPoint]] = None

        self.ridge_alpha = ridge_alpha
        self.ridge_solver = Ridge(alpha=ridge_alpha, fit_intercept=False, solver='auto')
        if VERBOSE:
            print(f"   ℹ️  RPCGeneratorV2 초기화 (Ridge alpha={ridge_alpha}, Force 2D={self.force_2d_rfm})")

        if self.source_crs is None:
            if VERBOSE:
                print("⚠️ RPCGeneratorV2: source_crs=None, 경위도 가정")
            self.is_projected = False
            self.transformer = None
        else:
            try:
                self.pyproj_crs = CRS.from_user_input(source_crs)
                self.is_projected = self.pyproj_crs.is_projected
                if self.is_projected:
                    if VERBOSE:
                        print(f"🌍 RPCGeneratorV2: {self.pyproj_crs.name} → WGS84 변환")
                    self.transformer = Transformer.from_crs(self.pyproj_crs, "EPSG:4326", always_xy=True)
                else:
                    if VERBOSE:
                        print(f"🌍 RPCGeneratorV2: 이미 지리좌표, 변환 생략")
                    self.transformer = None
            except Exception as e:
                print(f"❌ RPCGeneratorV2: CRS 처리 오류: {e}")
                self.is_projected = False
                self.transformer = None

    @staticmethod
    def _poly_terms(L: float, P: float, H: float) -> List[float]:
        return [
            1.0,
            L, P, H,
            L*P, L*H, P*H,
            L*L, P*P, H*H,
            L*P*H,
            L*L*L,
            L*(P*P),
            L*(H*H),
            (L*L)*P,
            P*P*P,
            P*(H*H),
            (L*L)*H,
            (P*P)*H,
            H*H*H,
        ]

    def _to_lonlat(self, gcps: List[GroundControlPoint], verbose: bool = False) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        xs = np.array([g.x for g in gcps])
        ys = np.array([g.y for g in gcps])
        hs = np.array([g.z for g in gcps])
        cs = np.array([g.col for g in gcps])
        rs = np.array([g.row for g in gcps])
        lons, lats = xs, ys
        if self.transformer is not None:
            try:
                if verbose and VERBOSE:
                    print("   🔄 (V2) UTM→WGS84 변환 중...")
                lons, lats = self.transformer.transform(xs, ys)
                lons = np.asarray(lons); lats = np.asarray(lats)
            except Exception as e:
                print(f"   ⚠️ (V2) 좌표 변환 실패: {e} → x,y를 경위도로 사용")
                lons, lats = xs, ys
        return lons, lats, hs, cs, rs

    def _estimate(self, lons: np.ndarray, lats: np.ndarray, hs: np.ndarray,
                  cs: np.ndarray, rs: np.ndarray, w: int, h: int) -> Dict[str, Any]:
        lat_min, lat_max = float(np.min(lats)), float(np.max(lats))
        lon_min, lon_max = float(np.min(lons)), float(np.max(lons))
        h_min, h_max = float(np.min(hs)), float(np.max(hs))
        LAT_OFF = (lat_min + lat_max) / 2.0
        LONG_OFF = (lon_min + lon_max) / 2.0
        HEIGHT_OFF = (h_min + h_max) / 2.0
        LAT_SCALE = max((lat_max - lat_min) / 2.0, 1e-6)
        LONG_SCALE = max((lon_max - lon_min) / 2.0, 1e-6)
        HEIGHT_SCALE = max((h_max - h_min) / 2.0, 1e-6)

        P = (lats - LAT_OFF) / LAT_SCALE
        L = (lons - LONG_OFF) / LONG_SCALE
        if self.force_2d_rfm or (HEIGHT_SCALE < self.flat_terrain_threshold_m):
            if VERBOSE:
                print(f"   ⚠️ (V2) 평탄 지형 감지 또는 강제 2D → 2D RFM 적용")
            H = np.zeros_like(hs)
            HEIGHT_OFF = 0.0
            HEIGHT_SCALE = 1.0
        else:
            H = (hs - HEIGHT_OFF) / HEIGHT_SCALE

        R = (rs - (h / 2.0)) / max(h / 2.0, 1.0)
        C = (cs - (w / 2.0)) / max(w / 2.0, 1.0)

        A = np.array([self._poly_terms(L[i], P[i], H[i]) for i in range(len(L))])
        n_feat = A.shape[1]
        A_rest = A[:, 1:]
        lam = max(self.ridge_alpha, 1e-6)

        # Line (row)
        M_line = np.hstack([-A, (R[:, None] * A_rest)])
        b_line = -A[:, 0]
        MtM = M_line.T @ M_line + lam * np.eye(M_line.shape[1])
        sol_line = np.linalg.lstsq(MtM, M_line.T @ b_line, rcond=None)[0]
        line_num = sol_line[:n_feat]
        line_den = np.concatenate([[1.0], sol_line[n_feat:]])

        # Sample (col)
        M_samp = np.hstack([-A, (C[:, None] * A_rest)])
        b_samp = -A[:, 0]
        MtM2 = M_samp.T @ M_samp + lam * np.eye(M_samp.shape[1])
        sol_samp = np.linalg.lstsq(MtM2, M_samp.T @ b_samp, rcond=None)[0]
        samp_num = sol_samp[:n_feat]
        samp_den = np.concatenate([[1.0], sol_samp[n_feat:]])

        rpc = {
            'LINE_OFF': h / 2.0,
            'SAMP_OFF': w / 2.0,
            'LAT_OFF': LAT_OFF,
            'LONG_OFF': LONG_OFF,
            'HEIGHT_OFF': HEIGHT_OFF,
            'LINE_SCALE': max(h / 2.0, 1.0),
            'SAMP_SCALE': max(w / 2.0, 1.0),
            'LAT_SCALE': LAT_SCALE,
            'LONG_SCALE': LONG_SCALE,
            'HEIGHT_SCALE': HEIGHT_SCALE,
            'LINE_NUM_COEFF': line_num.tolist(),
            'LINE_DEN_COEFF': line_den.tolist(),
            'SAMP_NUM_COEFF': samp_num.tolist(),
            'SAMP_DEN_COEFF': samp_den.tolist(),
        }

        # NaN 체크
        for k in ['LINE_NUM_COEFF', 'LINE_DEN_COEFF', 'SAMP_NUM_COEFF', 'SAMP_DEN_COEFF']:
            if np.isnan(np.asarray(rpc[k])).any():
                raise ValueError("RPCGeneratorV2: NaN 계수 발생")
        return rpc

    def generate_rpc(self, gcps: List[GroundControlPoint], image_width: int, image_height: int) -> Optional[Dict[str, Any]]:
        if len(gcps) < self.min_gcps:
            print(f"⚠️  RPC V2: 최소 {self.min_gcps}개 GCP 필요 (현재 {len(gcps)})")
            return None
        target_gcps = gcps
        if self.use_ransac and len(gcps) >= max(self.min_gcps, 30):
            if VERBOSE:
                print("   ℹ️  (V2) RANSAC 미구현: 전체 GCP 사용")
        lons, lats, hs, cs, rs = self._to_lonlat(target_gcps, verbose=True)
        self.rpc_params = self._estimate(lons, lats, hs, cs, rs, image_width, image_height)
        if VERBOSE:
            print("   ✅ RPCGeneratorV2: RPC 모델 생성 완료")
        return self.rpc_params