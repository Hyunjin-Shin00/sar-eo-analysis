"""N2/S1 페어별 기하 조건 계산: Bperp, 입사각(master/secondary), dinc, h_amb, Bperp/Bcrit.
   InSAR/CCD/OT 조건 점검용."""
import numpy as np, n2insar as N, s1insar as S1
C0=299792458.0; S,Nn,W,E=36.3899,36.4350,126.3548,126.4107
LAT,LON=0.5*(S+Nn),0.5*(W+E)
def geom(sc):  # scene at AOI center -> P,R,look,inc(deg),ground T
    T=N.geo2ecef(np.array([LAT]),np.array([LON]),np.array([15.]))
    nl = sc.nlines
    t,R=N.geo2rdr(sc,T,t_guess=sc.line_to_t(nl//2)); P,_=sc.orbit(t)
    P=P.reshape(3); T=T.reshape(3); los=(T-P)/np.linalg.norm(T-P); up=T/np.linalg.norm(T)
    inc=np.degrees(np.arccos(np.clip(np.dot(-los,up),-1,1)))  # 지상 입사각
    return P,float(R),T,inc
def pair(m,s,lam,Bw,tag):
    Pm,Rm,T,incm=geom(m); Ps,Rs,_,incs=geom(s)
    B=Ps-Pm; look=(T-Pm)/np.linalg.norm(T-Pm)
    Bperp=np.sqrt(max(np.dot(B,B)-np.dot(B,look)**2,0))
    hamb=lam*Rm*np.sin(np.radians(incm))/(2*Bperp+1e-9)
    Bcrit=lam*Rm*Bw*np.tan(np.radians(incm))/C0
    print("%-22s Bperp=%8.0f m | inc %.1f/%.1f° dinc=%.2f° | h_amb=%.2f m | Bcrit≈%.0f m | Bperp/Bcrit=%.1f"%(
        tag,Bperp,incm,incs,abs(incm-incs),hamb,Bcrit,Bperp/Bcrit))
R="/mnt/c/N2_InSAR/N2/Taean_recent/"; Z="/mnt/c/N2_InSAR/sentinel1/"
def n2(d,dd):
    import glob; return N.Scene(glob.glob(R+"2026%s/*/Distribution/*_SSC_*.h5"%d)[0])
mA={ "0515":"0515","0614":"0614","0511":"0511" }
def n2s(d):
    import glob; f=glob.glob(R+"2026%s/*/Distribution/*_SSC_*.h5"%d)[0]; return N.Scene(f)
print("=== N2 (X-band λ=3.1cm, Bw≈150MHz) ===")
for a,b,t in [("0511","0515","N2 CCD coh 0511×0515"),("0515","0614","N2 InSAR/OT 0515×0614")]:
    m=n2s(a); s=n2s(b); N.calibrate_side(m,36.41,126.38); N.calibrate_side(s,36.41,126.38)
    pair(m,s,m.wavelength,150e6,t)
print("=== S1 (C-band λ=5.5cm, Bw≈56MHz) ===")
SP={"0519":"S1C_IW_SLC__1SDV_20260519T214004_20260519T214028_007728_00FB4A_A82C.zip",
    "0531":"S1C_IW_SLC__1SDV_20260531T214004_20260531T214029_007903_010126_2310.zip",
    "0613":"S1D_IW_SLC__1SDV_20260613T214015_20260613T214042_003223_0059FE_D74F.zip"}
for a,b,t in [("0519","0531","S1 InSAR/CCD 0519×0531"),("0519","0613","S1 OT 0519×0613"),("0531","0613","S1 CCD 0531×0613")]:
    m=S1.S1Scene(Z+SP[a],"iw1","vv",0); s=S1.S1Scene(Z+SP[b],"iw1","vv",0)
    N.calibrate_side(m,36.41,126.38); N.calibrate_side(s,36.41,126.38)
    pair(m,s,m.wavelength,56e6,t)
