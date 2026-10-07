import xml.etree.ElementTree as ET
import numpy as np

# 1. 상수 정의
C = 299792458.0  # 광속 (m/s)
OMEGA_EARTH = np.array([0, 0, 7.292115e-5])  # 지구 자전 각속도 (rad/s)

def get_all_mdi(root, subdataset_name):
    """XML 내 특정 서브데이터셋의 모든 Metadata 항목을 딕셔너리로 추출"""
    mdi_dict = {}
    sub = root.find(f".//Subdataset[@name='{subdataset_name}']/PAMDataset")
    if sub is not None:
        # 전역 메타데이터 및 밴드별 메타데이터 통합
        for mdi in sub.findall(".//MDI"):
            mdi_dict[mdi.get('key')] = mdi.text
    return mdi_dict

def get_rotation_matrix(yaw_deg, pitch_deg, roll_deg):
    """자세 각도를 이용한 회전 행렬 생성 (Tait-Bryan ZYX)"""
    y, p, r = np.radians([yaw_deg, pitch_deg, roll_deg])
    c1, s1 = np.cos(y), np.sin(y)
    c2, s2 = np.cos(p), np.sin(p)
    c3, s3 = np.cos(r), np.sin(r)
    
    R_z = np.array([[c1, -s1, 0], [s1, c1, 0], [0, 0, 1]])
    R_y = np.array([[c2, 0, s2], [0, 1, 0], [-s2, 0, c2]])
    R_x = np.array([[1, 0, 0], [0, c3, -s3], [0, s3, c3]])
    return R_z @ R_y @ R_x

# 2. 데이터 로드 및 파싱
xml_path = '/home/hyunjin/nas/nationalpark_SAR/SLC/structure_with_tiny_data_n2.h5.aux.xml'
tree = ET.parse(xml_path)
root = tree.getroot()
meta = get_all_mdi(root, "//S01/SBI")

# 리스트 데이터 변환 (문자열 -> 넘파이 배열)
times = np.fromstring(meta['State_Vectors_Times'], sep=' ')
pos = np.fromstring(meta['ECEF_Satellite_Position'], sep=' ').reshape(-1, 3)
vel = np.fromstring(meta['ECEF_Satellite_Velocity'], sep=' ').reshape(-1, 3)
yaw = np.fromstring(meta['Yaw_Angle'], sep=' ')
pitch = np.fromstring(meta['Pitch_Angle'], sep=' ')
roll = np.fromstring(meta['Roll_Angle'], sep=' ')

# 3. 주요 파라미터 설정
freq = float(meta.get('Radar_Frequency', 9.65e9))
lam = C / freq
look_angle_deg = float(meta.get('S01_Look_Angle', 0))
tau_start = float(meta.get('Zero_Doppler_Range_First_Time', 0))
slant_range = C * tau_start / 2.0  # 기준 거리
t_ref = float(meta.get('Zero_Doppler_Azimuth_First_Time', times[0]))

# 4. 시점별 기하학적 도플러 주파수 계산
dopplers = []
for i in range(len(times)):
    p_vec, v_vec = pos[i], vel[i]
    
    # 궤도 좌표계 (Orbit Frame) 정의: Nadir 방향 기준
    uz = -p_vec / np.linalg.norm(p_vec)
    uy = np.cross(uz, v_vec / np.linalg.norm(v_vec))
    uy /= np.linalg.norm(uy)
    ux = np.cross(uy, uz)
    R_orbit_to_ecef = np.stack([ux, uy, uz], axis=1)
    
    # 위성 자세 반영 (Attitude)
    R_att = get_rotation_matrix(yaw[i], pitch[i], roll[i])
    
    # 안테나 빔 방향 (Look Side: Right)
    look_rad = np.radians(abs(look_angle_deg))
    n_sat = np.array([0, np.sin(look_rad), np.cos(look_rad)])
    
    # ECEF 좌표계로 변환
    n_ecef = R_orbit_to_ecef @ R_att @ n_sat
    
    # 지표면 타겟 위치 및 속도 (지구 자전 포함)
    p_target = p_vec + slant_range * n_ecef
    v_target = np.cross(OMEGA_EARTH, p_target)
    v_rel = v_vec - v_target
    
    # 도플러 계산
    fdc = (2.0 / lam) * np.dot(v_rel, n_ecef)
    dopplers.append(fdc)

# 5. 다항식 피팅 (Least Squares Fitting)
t_rel = times - t_ref
coeffs = np.polyfit(t_rel, dopplers, 2)  # [d2, d1, d0] 순서로 반환됨

# 6. 결과 정리 및 출력 (d0는 메타데이터의 상수값을 우선 사용)
d0 = float(meta.get('Doppler_Centroid', coeffs[2]))
d1 = float(coeffs[1])
d2 = float(coeffs[0])

print(f"--- Doppler Centroid Polynomial Coefficients ---")
print(f"d0 (Constant): {d0}")
print(f"d1 (Linear):   {d1}")
print(f"d2 (Quadratic):{d2}")
print(f"Polynomial List for Processor: [{d0}, {d1}, {d2}, 0.0, 0.0, 0.0]")