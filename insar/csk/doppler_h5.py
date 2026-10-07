import h5py
import numpy as np

# 1. 물리 상수
C = 299792458.0
OMEGA_EARTH = np.array([0, 0, 7.292115e-5])

def get_rotation_matrix(yaw, pitch, roll):
    """오일러 각도(Degree) -> 회전 행렬 변환 (순서: Z->Y->X 가정)"""
    # N2 데이터는 Degree 단위입니다.
    y_rad = np.radians(yaw)
    p_rad = np.radians(pitch)
    r_rad = np.radians(roll)
    
    cy, sy = np.cos(y_rad), np.sin(y_rad)
    cp, sp = np.cos(p_rad), np.sin(p_rad)
    cr, sr = np.cos(r_rad), np.sin(r_rad)
    
    # Rotation Matrix (Satellite Body to Orbit Frame)
    R_z = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    R_y = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    R_x = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    
    return R_z @ R_y @ R_x

def read_h5_data(h5_path):
    """HDF5 구조에 맞춰 데이터 추출"""
    data = {}
    try:
        with h5py.File(h5_path, 'r') as f:
            # 1. Root Attributes (공통 메타데이터)
            attrs = f.attrs
            data['times'] = attrs.get('State Vectors Times')
            data['pos'] = attrs.get('ECEF Satellite Position')
            data['vel'] = attrs.get('ECEF Satellite Velocity')
            
            # 자세 정보 (Euler Angles)
            data['yaw'] = attrs.get('Yaw Angle')
            data['pitch'] = attrs.get('Pitch Angle')
            data['roll'] = attrs.get('Roll Angle')
            
            data['freq'] = attrs.get('Radar Frequency')
            
            # 2. Group S01 Attributes
            if 'S01' in f:
                data['look_angle'] = f['S01'].attrs.get('Look Angle')
            
            # 3. Dataset SBI Attributes
            if 'S01/SBI' in f:
                sbi_attrs = f['S01/SBI'].attrs
                data['tau0'] = sbi_attrs.get('Zero Doppler Range First Time')
                data['t_ref'] = sbi_attrs.get('Zero Doppler Azimuth First Time')
                data['meta_d0'] = attrs.get('Doppler Centroid') # Root에 있는 경우
                if data['meta_d0'] is None:
                     data['meta_d0'] = sbi_attrs.get('Doppler Centroid')

    except Exception as e:
        print(f"[Error] 파일 읽기 실패: {e}")
        return None
        
    return data

# --- 실행 로직 ---
h5_path = '/home/hyunjin/nas/nationalpark_SAR/SLC/structure_with_tiny_data_n2.h5' # 파일명 확인 필요!
print(f"Reading: {h5_path}")

raw_data = read_h5_data(h5_path)

if raw_data and raw_data['times'] is not None:
    # 데이터 형변환 (numpy array로)
    times = np.array(raw_data['times'])
    pos = np.array(raw_data['pos']).reshape(-1, 3)
    vel = np.array(raw_data['vel']).reshape(-1, 3)
    
    yaw = np.array(raw_data['yaw'])
    pitch = np.array(raw_data['pitch'])
    roll = np.array(raw_data['roll'])
    
    # 데이터 개수 동기화
    n_points = min(len(times), len(pos), len(yaw))
    print(f"Data points found: {n_points}")
    
    # 파라미터 설정
    freq = float(raw_data.get('freq', 9.65e9))
    lam = C / freq
    look_angle = float(raw_data.get('look_angle', -28.489))
    tau0 = float(raw_data.get('tau0', 0))
    slant_range = tau0 * C / 2.0
    t_ref = float(raw_data.get('t_ref', times[0]))
    
    # 도플러 계산
    dopplers = []
    for i in range(n_points):
        p_vec = pos[i]
        v_vec = vel[i]
        
        # 1. Orbit Frame Basis (Nadir pointing)
        uz = -p_vec / np.linalg.norm(p_vec)
        uy = np.cross(uz, v_vec / np.linalg.norm(v_vec))
        uy /= np.linalg.norm(uy)
        ux = np.cross(uy, uz)
        R_orbit = np.stack([ux, uy, uz], axis=1)
        
        # 2. Attitude Rotation
        R_att = get_rotation_matrix(yaw[i], pitch[i], roll[i])
        
        # 3. Beam Vector (Right looking)
        look_rad = np.radians(abs(look_angle))
        n_sat = np.array([0, np.sin(look_rad), np.cos(look_rad)])
        
        # 4. Total Rotation (Sat Body -> Orbit -> ECEF)
        # N2 데이터의 Yaw/Pitch/Roll은 Orbit Frame에 대한 회전으로 가정
        n_ecef = R_orbit @ R_att @ n_sat
        
        # 5. Relative Velocity
        p_target = p_vec + slant_range * n_ecef
        v_target = np.cross(OMEGA_EARTH, p_target)
        v_rel = v_vec - v_target
        
        fdc = (2.0 / lam) * np.dot(v_rel, n_ecef)
        dopplers.append(fdc)
        
    # 다항식 피팅
    t_rel = times[:n_points] - t_ref
    coeffs = np.polyfit(t_rel, dopplers, 2)
    
    # 메타데이터 상수값(있으면 가져오기)
    meta_d0 = raw_data.get('meta_d0')
    
    print("\n=== Doppler Centroid Polynomial Coefficients ===")
    print(f"Calculated d0: {coeffs[2]:.6f}")
    print(f"Calculated d1: {coeffs[1]:.6f}")
    print(f"Calculated d2: {coeffs[0]:.6f}")
    
    if meta_d0 is not None:
        print(f"Metadata d0  : {float(meta_d0):.6f} (Reference)")
        # 최종 결과는 메타데이터의 d0를 신뢰하는 것이 일반적입니다.
        print(f"\nFinal Polynomial: [{float(meta_d0)}, {coeffs[1]}, {coeffs[0]}, 0.0, 0.0, 0.0]")
    else:
        print(f"\nFinal Polynomial: [{coeffs[2]}, {coeffs[1]}, {coeffs[0]}, 0.0, 0.0, 0.0]")

else:
    print("[Error] 필수 데이터를 찾을 수 없습니다. (State Vectors Times 등)")