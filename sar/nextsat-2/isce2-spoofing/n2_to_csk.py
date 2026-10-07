import xml.etree.ElementTree as ET
import numpy as np
import h5py
import os
from datetime import datetime, timedelta
from scipy.spatial.transform import Rotation as R

# --- 물리 상수 ---
C = 299792458.0

def parse_n2_xml(xml_path):
    if not os.path.exists(xml_path):
        print(f"[Error] 파일을 찾을 수 없습니다: {xml_path}")
        return None
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"[Error] XML 파싱 실패: {e}")
        return None
    
    data = {}
    def get_str(key):
        n = root.find(f".//MDI[@key='{key}']")
        return n.text if n is not None else "UNKNOWN"
        
    def get_val(key, dtype=float):
        text = root.find(f".//MDI[@key='{key}']")
        return dtype(text.text) if text is not None and text.text else 0
        
    def get_arr(key):
        text = root.find(f".//MDI[@key='{key}']")
        return np.fromstring(text.text, sep=' ') if text is not None and text.text else np.array([])

    # --- 1. N2 고유 정보 추출 ---
    data['mission'] = get_str('Mission_ID')       # NEXTSat-2
    data['mode'] = get_str('Acquisition_Mode')    # StripMap
    data['orbit_dir'] = get_str('Orbit_Direction')# ASCENDING
    data['look_side'] = get_str('Look_Side').upper()
    data['orbit_num'] = get_val('Orbit_Number', int) # 9894
    data['sat_height'] = get_val('Satellite_Height')
    
    # --- 2. 레이더/영상 파라미터 ---
    data['freq'] = get_val('Radar_Frequency')
    if data['freq'] == 0: data['freq'] = 9.65e9
    data['wvl'] = C / data['freq']
    data['prf'] = get_val('S01_PRF')
    
    # --- 3. 궤도/자세/시간 ---
    data['sv_times'] = get_arr('State_Vectors_Times')
    data['pos'] = get_arr('ECEF_Satellite_Position').reshape(-1, 3)
    data['vel'] = get_arr('ECEF_Satellite_Velocity').reshape(-1, 3)
    data['yaw'] = get_arr('Yaw_Angle')
    data['pitch'] = get_arr('Pitch_Angle')
    data['roll'] = get_arr('Roll_Angle')
    
    data['t_az_first'] = get_val('Zero_Doppler_Azimuth_First_Time')
    data['t_az_last'] = get_val('Zero_Doppler_Azimuth_Last_Time')
    data['tau0'] = get_val('Zero_Doppler_Range_First_Time') 
    
    # --- 4. 이미지 구조 ---
    data['lines'] = int(get_val('Line_Samples'))
    data['samples'] = int(get_val('Column_Samples'))
    data['line_spacing'] = get_val('Line_Spacing')
    data['col_spacing'] = get_val('Column_Spacing')
    data['lin_time_int'] = get_val('Line_Time_Interval')
    data['col_time_int'] = get_val('Column_Time_Interval')
    
    # --- 5. 도플러 (N2 상수값) ---
    data['dc_const'] = get_val('Doppler_Centroid') # 32.925...
    
    return data

def create_csk_h5(n2, output_path):
    print(f"Generating HDF5 with N2 Data: {output_path}")
    
    with h5py.File(output_path, 'w') as f:
        # Reference Time: 첫번째 State Vector 시간
        ref_epoch = n2['sv_times'][0]
        ref_dt = datetime.fromtimestamp(ref_epoch)
        ref_utc_str = ref_dt.strftime('%Y-%m-%d %H:%M:%S.%f')
        
        start_dt = datetime.fromtimestamp(n2['t_az_first'])
        stop_dt = datetime.fromtimestamp(n2['t_az_last'])
        
        # =========================================================
        # [수정됨] 헤더 정보를 N2 값으로 직접 매핑
        # =========================================================
        attrs = f.attrs
        attrs['Mission ID'] = np.string_(n2['mission'])      # NEXTSat-2
        attrs['Satellite ID'] = np.string_(n2['mission'])    # NEXTSat-2
        attrs['Product Type'] = np.string_("SCS_B")          # 포맷 유지를 위해 SCS_B 사용
        attrs['Acquisition Mode'] = np.string_(n2['mode'])   # StripMap
        attrs['Look Side'] = np.string_(n2['look_side'])     # RIGHT
        attrs['Orbit Direction'] = np.string_(n2['orbit_dir'])
        attrs['Orbit Number'] = n2['orbit_num']              # 9894
        
        # 시간 및 좌표계
        attrs['Reference UTC'] = np.string_(ref_utc_str)
        attrs['Scene Sensing Start UTC'] = np.string_(start_dt.strftime('%Y-%m-%d %H:%M:%S.%f'))
        attrs['Scene Sensing Stop UTC'] = np.string_(stop_dt.strftime('%Y-%m-%d %H:%M:%S.%f'))
        attrs['Projection ID'] = np.string_("SLANT RANGE/AZIMUTH")
        attrs['Ellipsoid Designator'] = np.string_("WGS84")
        attrs['Ellipsoid Semimajor Axis'] = 6378137.0
        attrs['Ellipsoid Semiminor Axis'] = 6356752.314
        
        # 시스템 파라미터
        attrs['Radar Frequency'] = n2['freq']
        attrs['Radar Wavelength'] = n2['wvl']
        attrs['Satellite Height'] = n2['sat_height']
        attrs['Light Speed'] = C

        # =========================================================
        # 궤도 및 자세 (N2 데이터)
        # =========================================================
        rel_times = n2['sv_times'] - ref_epoch
        attrs['State Vectors Times'] = rel_times
        attrs['ECEF Satellite Position'] = n2['pos']
        attrs['ECEF Satellite Velocity'] = n2['vel']
        
        # 가속도 계산
        if len(rel_times) > 1:
            acc = np.gradient(n2['vel'], rel_times, axis=0)
        else:
            acc = np.zeros_like(n2['vel'])
        attrs['ECEF Satellite Acceleration'] = acc
        
        # 자세 (Euler -> Quaternion 변환)
        quats = []
        min_len = min(len(n2['yaw']), len(n2['pitch']), len(n2['roll']))
        for i in range(min_len):
            r = R.from_euler('zyx', [n2['yaw'][i], n2['pitch'][i], n2['roll'][i]], degrees=True)
            quats.append(r.as_quat())
        attrs['Attitude Quaternions'] = np.array(quats)
        attrs['Attitude Times'] = rel_times[:min_len]

        # =========================================================
        # 도플러 다항식 (N2 값 적용)
        # =========================================================
        # 1. Centroid (N2 값)
        d0 = n2['dc_const']
        attrs['Centroid vs Azimuth Time Polynomial'] = np.array([d0, 0., 0., 0., 0., 0.])
        attrs['Centroid vs Range Time Polynomial'] = np.array([d0, 0., 0., 0., 0., 0.])
        
        # 2. Rate (물리적 계산값)
        vel_mag = np.linalg.norm(n2['vel'][len(n2['vel'])//2])
        slant_r = n2['tau0'] * C / 2.0
        ka = - (2 * vel_mag**2) / (n2['wvl'] * slant_r)
        attrs['Doppler Rate vs Azimuth Time Polynomial'] = np.array([ka, 0., 0., 0., 0., 0.])
        attrs['Doppler Rate vs Range Time Polynomial'] = np.array([ka, 0., 0., 0., 0., 0.])
        
        # 필수 더미 속성
        attrs['Range Focusing Weighting Function'] = np.string_("HAMMING")
        attrs['Azimuth Focusing Weighting Function'] = np.string_("HAMMING")
        attrs['Range Polynomial Reference Time'] = n2['tau0']
        attrs['Azimuth Polynomial Reference Time'] = n2['t_az_first'] - ref_epoch

        # =========================================================
        # 그룹 S01 (빔 정보)
        # =========================================================
        g_s01 = f.create_group("S01")
        # [수정] Beam ID를 N2 빔으로 변경 (없으면 S01)
        g_s01.attrs['Beam ID'] = np.string_("S01") 
        g_s01.attrs['Polarisation'] = np.string_("HH")
        g_s01.attrs['PRF'] = n2['prf']
        
        fs = 1.0 / n2['col_time_int'] if n2['col_time_int'] > 0 else 1.6e8
        g_s01.attrs['Sampling Rate'] = fs
        g_s01.attrs['Range Focusing Bandwidth'] = 9.68e7 # Default or calc
        g_s01.attrs['Azimuth Focusing Bandwidth'] = n2['prf'] * 0.8
        g_s01.attrs['Reference Slant Range'] = slant_r
        # Chirp parameters (dummy if not in N2)
        g_s01.attrs['Range Chirp Rate'] = 4.84e12 
        g_s01.attrs['Range Chirp Length'] = 4e-5

        # =========================================================
        # 그룹 B001 (Burst 정보)
        # =========================================================
        g_b001 = g_s01.create_group("B001")
        az_start_rel = n2['t_az_first'] - ref_epoch
        az_end_rel = n2['t_az_last'] - ref_epoch
        g_b001.attrs['Azimuth First Time'] = az_start_rel
        g_b001.attrs['Azimuth Last Time'] = az_end_rel
        g_b001.attrs['Range First Times'] = n2['tau0']
        g_b001.attrs['Raw Missing Lines Percentage'] = 0.0
        g_b001.attrs['Raw OverSaturated Percentage'] = np.array([0.0, 0.0])

        # =========================================================
        # 데이터셋 SBI (영상 데이터)
        # =========================================================
        shape = (n2['lines'], n2['samples'])
        dset = g_s01.create_dataset("SBI", shape, dtype='int16')
        
        dset.attrs['Line Spacing'] = n2['line_spacing']
        dset.attrs['Column Spacing'] = n2['col_spacing']
        dset.attrs['Line Time Interval'] = n2['lin_time_int']
        dset.attrs['Column Time Interval'] = n2['col_time_int']
        
        dset.attrs['Zero Doppler Azimuth First Time'] = az_start_rel
        dset.attrs['Zero Doppler Azimuth Last Time'] = az_end_rel
        dset.attrs['Zero Doppler Range First Time'] = n2['tau0']
        
        rg_last = n2['tau0'] + (n2['samples'] * n2['col_time_int'])
        dset.attrs['Zero Doppler Range Last Time'] = rg_last
        
        # 좌표 (Geocoding 전에는 0)
        zero_coord = np.array([0., 0., 0.])
        dset.attrs['Top Left Geodetic Coordinates'] = zero_coord
        dset.attrs['Top Right Geodetic Coordinates'] = zero_coord
        dset.attrs['Bottom Left Geodetic Coordinates'] = zero_coord
        dset.attrs['Bottom Right Geodetic Coordinates'] = zero_coord

        # Quicklook
        qlk_shape = (int(n2['lines']//10), int(n2['samples']//10))
        if qlk_shape[0] > 0:
            dset_qlk = g_s01.create_dataset("QLK", qlk_shape, dtype='uint8')
            dset_qlk.attrs['Quick Look Projection ID'] = np.string_("SLANT RANGE/AZIMUTH")

    print(f"[Success] Created {output_path}")
    print(f"Mission: {n2['mission']}, Orbit: {n2['orbit_num']}, Doppler: {d0}")

if __name__ == "__main__":
    input_xml = "structure_with_tiny_data_n2.h5.aux.xml"
    output_h5 = "FAKE_CSK_N2.h5"
    
    print(f"Reading {input_xml}...")
    n2_data = parse_n2_xml(input_xml)
    
    if n2_data:
        create_csk_h5(n2_data, output_h5)
    else:
        print("[Fail] 데이터 로드 실패")
