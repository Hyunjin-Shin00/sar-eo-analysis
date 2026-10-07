PATCH_CONTENT = r'''
import os, sys, math
from datetime import datetime

TAG = "[N2->CSK_SPOOF_DYNAMIC]"
C0 = 299792458.0
RE_EARTH = 6371000.0  # mean Earth radius [m]

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _safe_str(x):
    try:
        if isinstance(x, (bytes, bytearray)):
            return x.decode("utf-8", "ignore")
        return str(x)
    except Exception:
        return "<unprintable>"

def _norm_key(k: str) -> str:
    return "".join(ch.lower() for ch in k if ch.isalnum())

def _find_attr(attrs, *candidates):
    """
    h5py attrs helper:
      - tries exact key
      - then tries normalized (case/space/underscore-insensitive) match
    """
    if attrs is None:
        return None, None
    # exact first
    for k in candidates:
        try:
            if k in attrs:
                return k, attrs.get(k)
        except Exception:
            pass

    # normalized lookup
    norm_map = {}
    try:
        for k in attrs.keys():
            norm_map[_norm_key(k)] = k
    except Exception:
        return None, None

    for k in candidates:
        nk = _norm_key(k)
        if nk in norm_map:
            real_k = norm_map[nk]
            try:
                return real_k, attrs.get(real_k)
            except Exception:
                return real_k, None
    return None, None

def _as_float(v):
    if v is None:
        return None
    try:
        import numpy as np
        if isinstance(v, np.ndarray):
            if v.size == 1:
                v = float(v.reshape(-1)[0])
            else:
                return None
        return float(v)
    except Exception:
        try:
            return float(_safe_str(v))
        except Exception:
            return None

def _as_int(v):
    f = _as_float(v)
    if f is None:
        return None
    try:
        return int(f)
    except Exception:
        return None

def calc_incidence_angle_from_look(look_angle_deg, sat_height_m):
    """
    Incidence angle using spherical geometry (law-of-sines style approximation):
      sin(inc) = ((Re + H) / Re) * sin(|look|)
    """
    if look_angle_deg is None or sat_height_m is None:
        return None
    try:
        import numpy as np
        look_rad = np.radians(abs(float(look_angle_deg)))
        ratio = (float(RE_EARTH) + float(sat_height_m)) / float(RE_EARTH)
        sin_inc = ratio * np.sin(look_rad)
        inc = np.degrees(np.arcsin(np.clip(sin_inc, -1.0, 1.0)))
        return float(inc)
    except Exception:
        return None

class _Report:
    def __init__(self, h5_path: str):
        base = os.path.basename(h5_path) if h5_path else "unknown"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.abspath(f"Mapping_Report_{base}_{ts}.txt")
        self._fh = None

    def open(self):
        self._fh = open(self.path, "w", encoding="utf-8", errors="ignore")
        self.write("=== N2 -> CSK spoof mapping report (dynamic) ===")
        self.write(f"Time: {_now()}")
        self.write(f"Workdir: {os.getcwd()}")
        self.write("-" * 70)

    def write(self, line: str):
        if not self._fh:
            self.open()
        self._fh.write(line.rstrip("\n") + "\n")
        self._fh.flush()  # immediate flush (requirement)

    def close(self):
        try:
            if self._fh:
                self._fh.flush()
                self._fh.close()
        except Exception:
            pass

def _h5_has_signature(path: str) -> bool:
    """
    Validate candidate HDF5 is the N2-like input by checking existence of S01/SBI group.
    """
    try:
        import h5py
        with h5py.File(path, "r") as f:
            return ("S01" in f) and ("S01/SBI" in f)
    except Exception:
        return False

def _resolve_h5_path(sensor_obj):
    """
    Robustly resolve the input HDF5 path from the COSMO_SkyMed_SLC sensor instance.

    Key fix:
      - previous resolver returned <unknown> and injection never ran
      - here we (1) check common attribute names, (2) fallback scan all attributes,
        and (3) validate by actually opening file and checking S01/SBI group.
    """
    # 1) common names
    common = (
        "hdf5name","_hdf5name","h5name","_h5name","filename","_filename","input","_input",
        "inputFile","_inputFile","hdf5","_hdf5","scene","_scene","reference","_reference",
        "secondary","_secondary","file","_file","dataFile","_dataFile"
    )
    for name in common:
        try:
            p = getattr(sensor_obj, name, None)
        except Exception:
            continue
        if isinstance(p, (bytes, bytearray)):
            p = p.decode("utf-8", "ignore")
        if isinstance(p, str) and p and os.path.exists(p):
            if p.endswith((".h5",".hdf5")) and _h5_has_signature(p):
                return p

    # 2) deep scan fallback: iterate all public attributes; accept list/tuple of paths too
    try:
        for name in dir(sensor_obj):
            if name.startswith("_"):
                continue
            try:
                v = getattr(sensor_obj, name)
            except Exception:
                continue

            # direct string path
            if isinstance(v, (bytes, bytearray)):
                v = v.decode("utf-8", "ignore")
            if isinstance(v, str) and v and os.path.exists(v):
                if v.endswith((".h5",".hdf5")) and _h5_has_signature(v):
                    return v

            # list/tuple of paths
            if isinstance(v, (list, tuple)) and v:
                for vv in v:
                    if isinstance(vv, (bytes, bytearray)):
                        vv = vv.decode("utf-8", "ignore")
                    if isinstance(vv, str) and vv and os.path.exists(vv):
                        if vv.endswith((".h5",".hdf5")) and _h5_has_signature(vv):
                            return vv
    except Exception:
        pass

    return None

class N2MetadataEngine:
    """
    Extract N2 metadata (ROOT, S01, S01/SBI) dynamically and inject into ISCE2 objects.
    """
    def __init__(self, h5_path: str):
        self.h5_path = h5_path
        self.report = _Report(h5_path)

    def _extract(self):
        import h5py
        with h5py.File(self.h5_path, "r") as f:
            root = f.attrs

            # Satellite ID mapping: Mission ID (e.g., "NEXTSat-2")
            k_mission, mission = _find_attr(root, "Mission ID", "Mission_ID", "Mission")
            mission_s = _safe_str(mission) if mission is not None else None

            # Satellite Height from root
            k_h, sat_h = _find_attr(root, "Satellite Height", "Satellite_Height", "Height")
            sat_h_f = _as_float(sat_h)

            # Look Angle from S01
            s01 = f.get("S01", None)
            s01_attrs = getattr(s01, "attrs", None)
            k_look, look = _find_attr(s01_attrs, "Look Angle", "Look_Angle", "LookAngle")
            look_f = _as_float(look)

            # Incidence angle (computed)
            inc = calc_incidence_angle_from_look(look_f, sat_h_f)

            # Radar frequency & wavelength (optional but useful)
            k_rf, rf = _find_attr(root, "Radar Frequency", "Radar_Frequency", "Frequency")
            rf_f = _as_float(rf)
            wl = (C0 / rf_f) if rf_f else None

            # PRF from S01
            k_prf, prf = _find_attr(s01_attrs, "PRF", "Pulse Repetition Frequency", "PRF (Hz)")
            prf_f = _as_float(prf)

            # Image size from S01/SBI attributes
            sbi = f.get("S01/SBI", None)
            sbi_attrs = getattr(sbi, "attrs", None)
            k_lines, lines = _find_attr(sbi_attrs, "Line Samples", "Lines", "Number of Lines", "Number_of_Lines", "Line_Samples")
            k_samps, samps = _find_attr(sbi_attrs, "Column Samples", "Samples", "Number of Samples", "Number_of_Samples", "Column_Samples")
            lines_i = _as_int(lines)
            samps_i = _as_int(samps)

            # Optional: dataset shape fallback if attrs absent
            try:
                if (lines_i is None or samps_i is None) and sbi is not None:
                    shp = getattr(sbi, "shape", None)
                    if shp and len(shp) >= 2:
                        # typical is (lines, cols) but your sample shows (1,1) for tiny; keep best-effort
                        # If attrs are missing and shape is tiny, cannot infer true dims; leave None.
                        pass
            except Exception:
                pass

            # Look Side (Right → -1, Left → 1)
            k_ls, ls = _find_attr(root, "Look Side", "Look_Side")
            ls_s = _safe_str(ls).strip().upper() if ls is not None else "RIGHT"
            look_side_int = -1 if ls_s == "RIGHT" else 1

            # Optional: Doppler centroid (root) if present
            k_dc, dc = _find_attr(root, "Doppler Centroid", "Doppler_Centroid")
            dc_f = _as_float(dc)

            # Azimuth timing (sensing start/stop)
            k_azt0, azt0 = _find_attr(sbi_attrs, "Zero Doppler Azimuth First Time", "Azimuth First Time")
            k_azt1, azt1 = _find_attr(sbi_attrs, "Zero Doppler Azimuth Last Time", "Azimuth Last Time")
            azt0_f = _as_float(azt0)
            azt1_f = _as_float(azt1)

            # Range timing from S01/SBI (required by extractDoppler)
            k_rft, rft = _find_attr(sbi_attrs, "Zero Doppler Range First Time", "Range First Time")
            k_rlt, rlt = _find_attr(sbi_attrs, "Zero Doppler Range Last Time", "Range Last Time")
            rft_f = _as_float(rft)
            rlt_f = _as_float(rlt)

            # Chirp parameters from S01 (required by runInterferogram numberOfLooks)
            k_crate, crate = _find_attr(s01_attrs, "Range Chirp Rate", "Chirp_Rate", "Chirp Rate")
            k_clen, clen = _find_attr(s01_attrs, "Range Chirp Length", "Chirp_Length", "Pulse Length")
            crate_f = _as_float(crate)
            clen_f = _as_float(clen)

            # Range pixel size from S01/SBI Column Spacing
            k_dr, dr = _find_attr(sbi_attrs, "Column Spacing", "Range Pixel Size")
            dr_f = _as_float(dr)

            # Starting range from rangeFirstTime
            r0_f = (C0 * rft_f / 2.0) if rft_f is not None else None
            # Far range: startingRange + (nSamples - 1) * rangePixelSize
            far_range_f = (r0_f + (samps_i - 1) * dr_f) if (r0_f and samps_i and dr_f) else None
            # Range sampling rate: derived from pixel size
            rsr_f = (C0 / (2.0 * dr_f)) if dr_f else None

            # Range Polynomial Reference Time: not in N2, use rangeFirstTime as reference
            # dopplerRangeTime: not in N2, use [dc_f] as constant polynomial (Hz)
            rref_f = rft_f
            doppler_poly = [dc_f] if dc_f is not None else [0.0]

        return {
            "H5_PATH": ("(resolved)", self.h5_path),
            "Mission_ID": (k_mission, mission_s),
            "Satellite_Height_m": (k_h, sat_h_f),
            "Look_Angle_deg": (k_look, look_f),
            "Incidence_Angle_deg": ("(computed)", inc),
            "Radar_Frequency_Hz": (k_rf, rf_f),
            "Radar_Wavelength_m": ("(computed)", wl),
            "PRF_Hz": (k_prf, prf_f),
            "Line_Samples": (k_lines, lines_i),
            "Column_Samples": (k_samps, samps_i),
            "Doppler_Centroid_Hz": (k_dc, dc_f),
            "Range_First_Time": (k_rft, rft_f),
            "Range_Last_Time": (k_rlt, rlt_f),
            "Range_Ref_Time": ("(=rangeFirstTime)", rref_f),
            "Doppler_Range_Time_Poly": ("(=[dc])", doppler_poly),
            "Range_Pixel_Size_m": (k_dr, dr_f),
            "Starting_Range_m": ("(=C*rft/2)", r0_f),
            "Far_Range_m": ("(=r0+(n-1)*dr)", far_range_f),
            "Range_Sampling_Rate_Hz": ("(=C/2dr)", rsr_f),
            "Chirp_Rate_Hz_per_s": (k_crate, crate_f),
            "Pulse_Length_s": (k_clen, clen_f),
            "Azimuth_First_Time_unix": (k_azt0, azt0_f),
            "Azimuth_Last_Time_unix": (k_azt1, azt1_f),
            "Look_Side_int": (k_ls, look_side_int),
        }

    def run_immediate_report(self):
        """
        Write mapping report ASAP (flush every line) so even later crashes leave evidence.
        """
        try:
            self.report.open()
            self.report.write(f"Source HDF5: {self.h5_path}")
            if not self.h5_path or not os.path.exists(self.h5_path):
                self.report.write("ERROR: HDF5 path does not exist or unresolved.")
                self.report.close()
                return None

            m = self._extract()

            self.report.write("[Extracted / Mapped values]")
            for k, (src_key, val) in m.items():
                self.report.write(f"- {k}: {val}    (source_key={src_key})")

            self.report.write("-" * 70)
            self.report.write("NOTE: Values marked None were missing/unusable; injection will skip those fields.")
            self.report.close()

            print(f"{TAG} mapping report saved: {self.report.path}")
            return m
        except Exception as e:
            try:
                self.report.write(f"REPORT FAILURE: {e}")
                self.report.close()
            except Exception:
                pass
            print(f"{TAG} report failed: {e}")
            return None

    def inject_to_product(self, sensor_obj, mapping: dict):
        """
        Inject mapping into ISCE2 sensor/product objects.
        Defensive: tries common setters/attributes and never raises.
        """
        def set_if(obj, attr, val):
            if obj is None or val is None:
                return False
            try:
                setattr(obj, attr, val)
                return True
            except Exception:
                return False

        def call_if(obj, method, *args):
            if obj is None:
                return False
            try:
                fn = getattr(obj, method, None)
                if callable(fn):
                    fn(*args)
                    return True
            except Exception:
                return False
            return False

        # Ensure frame exists (avoid AttributeError at creation mismatch)
        frame = getattr(sensor_obj, "frame", None)
        if frame is None:
            try:
                from isceobj.Scene.Frame import Frame
                frame = Frame()
                sensor_obj.frame = frame
            except Exception:
                frame = None

        # Ensure frame.image exists (renderVRT relies on this)
        img = None
        try:
            img = getattr(frame, "image", None) if frame else None
        except Exception:
            img = None

        # Try to obtain instrument/platform if possible
        inst = None
        plat = None
        try:
            inst = frame.getInstrument() if frame else getattr(sensor_obj, "instrument", None)
        except Exception:
            inst = getattr(frame, "instrument", None) if frame else None

        try:
            plat = inst.getPlatform() if inst else None
        except Exception:
            plat = getattr(inst, "platform", None) if inst else None

        # Values
        mission = mapping.get("Mission_ID", (None, None))[1]
        rf = mapping.get("Radar_Frequency_Hz", (None, None))[1]
        wl = mapping.get("Radar_Wavelength_m", (None, None))[1]
        inc = mapping.get("Incidence_Angle_deg", (None, None))[1]
        prf = mapping.get("PRF_Hz", (None, None))[1]
        nlines = mapping.get("Line_Samples", (None, None))[1]
        nsamps = mapping.get("Column_Samples", (None, None))[1]
        dc = mapping.get("Doppler_Centroid_Hz", (None, None))[1]

        # Satellite ID / mission mapping (avoid KeyError downstream expectations)
        if mission is not None:
            call_if(plat, "setMission", mission) or set_if(plat, "mission", mission) or set_if(sensor_obj, "mission", mission)
            # common spellings
            set_if(sensor_obj, "satelliteID", mission) or set_if(sensor_obj, "satelliteId", mission) or set_if(sensor_obj, "satellite", mission)

        # Radar frequency / wavelength
        if rf is not None:
            call_if(inst, "setRadarFrequency", rf) or set_if(inst, "radarFrequency", rf)
        if wl is not None:
            call_if(inst, "setRadarWavelength", wl) or set_if(inst, "radarWavelength", wl)

        # Incidence angle
        if inc is not None:
            set_if(frame, "incidenceAngle", inc) or set_if(sensor_obj, "incidenceAngle", inc)

        # PRF
        if prf is not None:
            call_if(inst, "setPulseRepetitionFrequency", prf) or set_if(inst, "PRF", prf) or set_if(inst, "prf", prf)

        # Image size: set on frame AND image to prevent renderVRT width/length None
        if nlines is not None:
            set_if(frame, "numberOfLines", nlines) or set_if(frame, "nLines", nlines) or set_if(sensor_obj, "numberOfLines", nlines)
        if nsamps is not None:
            set_if(frame, "numberOfSamples", nsamps) or set_if(frame, "nSamples", nsamps) or set_if(sensor_obj, "numberOfSamples", nsamps)

        # Critical: image object used by renderVRT()
        if img is not None:
            if nsamps is not None:
                set_if(img, "width", nsamps)
            if nlines is not None:
                set_if(img, "length", nlines)

        # Optional Doppler centroid (best-effort)
        if dc is not None:
            set_if(sensor_obj, "dopplerCentroid", dc) or set_if(frame, "dopplerCentroid", dc)

        # Range timing — required by extractDoppler()
        rft = mapping.get("Range_First_Time", (None, None))[1]
        rlt = mapping.get("Range_Last_Time", (None, None))[1]
        rref = mapping.get("Range_Ref_Time", (None, None))[1]
        dpoly = mapping.get("Doppler_Range_Time_Poly", (None, None))[1]
        if rft is not None:
            set_if(sensor_obj, "rangeFirstTime", rft)
        if rlt is not None:
            set_if(sensor_obj, "rangeLastTime", rlt)
        if rref is not None:
            set_if(sensor_obj, "rangeRefTime", rref)
        if dpoly is not None:
            set_if(sensor_obj, "dopplerRangeTime", dpoly)

        # Look side / pointing direction — required by rdr2geo()
        look_side = mapping.get("Look_Side_int", (None, None))[1]
        if look_side is not None:
            call_if(plat, "setPointingDirection", look_side) or set_if(plat, "pointingDirection", look_side)
            set_if(sensor_obj, "lookSide", look_side)

        # Range pixel size — required by extractDoppler() for norm calculation
        dr = mapping.get("Range_Pixel_Size_m", (None, None))[1]
        if dr is not None:
            call_if(inst, "setRangePixelSize", dr) or set_if(inst, "rangePixelSize", dr)

        # Range sampling rate — required by runTopo slantRangePixelSpacing
        rsr = mapping.get("Range_Sampling_Rate_Hz", (None, None))[1]
        if rsr is not None:
            call_if(inst, "setRangeSamplingRate", rsr) or set_if(inst, "rangeSamplingRate", rsr)

        # Chirp slope & pulse length — required by runInterferogram numberOfLooks
        crate = mapping.get("Chirp_Rate_Hz_per_s", (None, None))[1]
        clen = mapping.get("Pulse_Length_s", (None, None))[1]
        if crate is not None:
            call_if(inst, "setChirpSlope", crate) or set_if(inst, "chirpSlope", crate)
        if clen is not None:
            call_if(inst, "setPulseLength", clen) or set_if(inst, "pulseLength", clen)

        # Starting range — required by extractDoppler() poly.setMean()
        r0 = mapping.get("Starting_Range_m", (None, None))[1]
        if r0 is not None:
            call_if(frame, "setStartingRange", r0) or set_if(frame, "startingRange", r0)

        # Far range — required by getBbox() in runVerifyDEM
        far_range = mapping.get("Far_Range_m", (None, None))[1]
        if far_range is not None:
            call_if(frame, "setFarRange", far_range) or set_if(frame, "farRange", far_range)

        # Sensing start/stop — required for orbit interpolation in calculateHeightDt()
        import datetime as _dt
        azt0 = mapping.get("Azimuth_First_Time_unix", (None, None))[1]
        azt1 = mapping.get("Azimuth_Last_Time_unix", (None, None))[1]
        if azt0 is not None:
            call_if(frame, "setSensingStart", _dt.datetime.utcfromtimestamp(azt0))
        if azt1 is not None:
            call_if(frame, "setSensingStop", _dt.datetime.utcfromtimestamp(azt1))
        if azt0 is not None and azt1 is not None:
            azt_mid = (azt0 + azt1) * 0.5
            call_if(frame, "setSensingMid", _dt.datetime.utcfromtimestamp(azt_mid))

        # Orbit state vectors — required by calculateHeightDt()
        try:
            import h5py as _h5py, numpy as _np
            from isceobj.Orbit.Orbit import StateVector as _SV
            orbit = frame.getOrbit() if frame else None
            if orbit is not None and self.h5_path and os.path.exists(self.h5_path):
                with _h5py.File(self.h5_path, "r") as hf:
                    sv_t = _np.array(hf.attrs["State Vectors Times"])
                    sv_p = _np.array(hf.attrs["ECEF Satellite Position"]).reshape(-1, 3)
                    sv_v = _np.array(hf.attrs["ECEF Satellite Velocity"]).reshape(-1, 3)
                orbit.setReferenceFrame("ECR")
                orbit.setOrbitSource("Header")
                # addStateVector compares vtime > maxTime; must initialize sentinels first
                orbit.minTime = _dt.datetime(year=_dt.MAXYEAR, month=12, day=31)
                orbit.maxTime = _dt.datetime(year=_dt.MINYEAR, month=1, day=1)
                for i in range(len(sv_t)):
                    vec = _SV()
                    vec.setTime(_dt.datetime.utcfromtimestamp(float(sv_t[i])))
                    vec.setPosition([float(sv_p[i, 0]), float(sv_p[i, 1]), float(sv_p[i, 2])])
                    vec.setVelocity([float(sv_v[i, 0]), float(sv_v[i, 1]), float(sv_v[i, 2])])
                    orbit.addStateVector(vec)
                print(f"{TAG} orbit injected: {len(sv_t)} state vectors, minTime={orbit.minTime}, maxTime={orbit.maxTime}")
        except Exception as e:
            print(f"{TAG} orbit injection failed: {e}")

def _install_patch():
    try:
        from isceobj.Sensor.COSMO_SkyMed_SLC import COSMO_SkyMed_SLC

        _orig_parse = getattr(COSMO_SkyMed_SLC, "parse", None)
        _orig_pop = getattr(COSMO_SkyMed_SLC, "populateMetadata", None)

        def patched_populateMetadata(self, *args, **kwargs):
            h5_path = _resolve_h5_path(self)
            engine = N2MetadataEngine(h5_path) if h5_path else None
            mapping = engine.run_immediate_report() if engine else None

            if callable(_orig_pop):
                try:
                    ret = _orig_pop(self, *args, **kwargs)
                except KeyError as e:
                    print(f"{TAG} populateMetadata KeyError suppressed: {e}")
                    ret = None
                except AttributeError as e:
                    print(f"{TAG} populateMetadata AttributeError suppressed: {e}")
                    ret = None
                except Exception as e:
                    print(f"{TAG} populateMetadata suppressed (generic): {e}")
                    ret = None
            else:
                ret = None

            # Always attempt injection after original (or after suppression)
            if engine and mapping:
                try:
                    engine.inject_to_product(self, mapping)
                except Exception as e:
                    print(f"{TAG} populateMetadata inject failed: {e}")

            return ret

        def patched_parse(self, *args, **kwargs):
            _apply_runtime_patches()
            h5_path = _resolve_h5_path(self)
            print(f"{TAG} intercept parse: {os.path.basename(h5_path) if h5_path else '<unknown>'}")

            engine = N2MetadataEngine(h5_path) if h5_path else None
            mapping = engine.run_immediate_report() if engine else None

            if callable(_orig_parse):
                try:
                    out = _orig_parse(self, *args, **kwargs)
                except KeyError as e:
                    print(f"{TAG} parse KeyError suppressed: {e}")
                    out = None
                except AttributeError as e:
                    print(f"{TAG} parse AttributeError suppressed: {e}")
                    out = None
                except Exception as e:
                    print(f"{TAG} parse suppressed (generic): {e}")
                    out = None
            else:
                out = None

            # Ensure injection after parse as well
            if engine and mapping:
                try:
                    engine.inject_to_product(self, mapping)
                except Exception as e:
                    print(f"{TAG} parse inject failed: {e}")

            return out

        _orig_extractImage = getattr(COSMO_SkyMed_SLC, "extractImage", None)

        def patched_extractImage(self, *args, **kwargs):
            if callable(_orig_extractImage):
                try:
                    out = _orig_extractImage(self, *args, **kwargs)
                except Exception as e:
                    print(f"{TAG} extractImage suppressed: {e}")
                    out = None
            else:
                out = None

            # Fix image length — extractImage creates slcImage with width only (no length)
            frame = getattr(self, "frame", None)
            nlines = None
            nsamps = None
            if frame:
                img = getattr(frame, "image", None)
                try:
                    nlines = frame.getNumberOfLines()
                except Exception:
                    nlines = getattr(frame, "numberOfLines", None)
                try:
                    nsamps = frame.getNumberOfSamples()
                except Exception:
                    nsamps = getattr(frame, "numberOfSamples", None)
                if img is not None and nlines:
                    try:
                        img.setLength(int(nlines))
                    except Exception:
                        pass

            # Sparse-pad SLC file to expected size so GDAL VRT dimensions match
            # (Linux sparse file: seek to end byte, write 1 null — no real disk allocation)
            output = getattr(self, "output", None) or getattr(self, "_output", None)
            if output and os.path.exists(output) and nlines and nsamps:
                expected = int(nlines) * int(nsamps) * 8  # CFLOAT = 8 bytes/px
                actual = os.path.getsize(output)
                if expected > actual > 0:
                    try:
                        with open(output, "r+b") as fh:
                            fh.seek(expected - 1)
                            fh.write(b"\x00")
                        print(f"{TAG} SLC padded (sparse): {os.path.basename(output)} {actual}→{expected} bytes")
                    except Exception as e:
                        print(f"{TAG} SLC pad failed: {e}")

            return out

        COSMO_SkyMed_SLC.populateMetadata = patched_populateMetadata
        COSMO_SkyMed_SLC.parse = patched_parse
        COSMO_SkyMed_SLC.extractImage = patched_extractImage
        print(f"{TAG} COSMO_SkyMed_SLC patched (parse + populateMetadata + extractImage).")
    except Exception as e:
        print(f"{TAG} patch install failed: {e}")

# Runtime patches applied lazily on first parse() call (ISCE2 fully loaded at that point)
_runtime_patched = [False]

def _apply_runtime_patches():
    """
    Patches that require ISCE2 modules unavailable at sitecustomize time
    (e.g. mroipac). Called once from patched_parse() after ISCE2 is loaded.
    Wraps _RunWrapper.__call__ to silently skip runRefineSecondaryTiming when
    cross-correlation fails due to insufficient data (0 valid offsets).
    runResampleSlc('refined') handles missing misreg files with azpoly=None.
    """
    if _runtime_patched[0]:
        return
    _runtime_patched[0] = True
    try:
        from isceobj.StripmapProc.Factories import _RunWrapper
        _orig_wc = _RunWrapper.__call__

        def _safe_call(self_w, *args, **kwargs):
            step = getattr(self_w.method, '__name__', '')
            try:
                return _orig_wc(self_w, *args, **kwargs)
            except Exception as e:
                if step == 'runRefineSecondaryTiming':
                    print(f"{TAG} {step} skipped (no valid offsets): {e}")
                    return None
                raise

        _RunWrapper.__call__ = _safe_call
        print(f"{TAG} _RunWrapper patched: runRefineSecondaryTiming will skip on failure.")
    except Exception as e:
        print(f"{TAG} runtime patch failed: {e}")

    # Fix 2: DataAccessorPy.methodSelector doesn't recognize 'r' (only 'read')
    # COSMO_SkyMed_SLC.extractImage sets slcImage.setAccessMode('r'), causing
    # "Cannot select appropriate image API" in computeCoherence.
    try:
        from iscesys.ImageApi.DataAccessorPy import DataAccessor as DataAccessorPy
        _orig_selector = DataAccessorPy.methodSelector

        def _patched_selector(self_img):
            am = self_img.accessMode.lower()
            if am in ('r', 'ro'):
                self_img.accessMode = 'read'
            elif am in ('w', 'wo'):
                self_img.accessMode = 'write'
            return _orig_selector(self_img)

        DataAccessorPy.methodSelector = _patched_selector
        print(f"{TAG} DataAccessorPy.methodSelector patched: 'r'/'w' normalized to 'read'/'write'.")
    except Exception as e:
        print(f"{TAG} DataAccessorPy patch failed: {e}")

_install_patch()
'''
