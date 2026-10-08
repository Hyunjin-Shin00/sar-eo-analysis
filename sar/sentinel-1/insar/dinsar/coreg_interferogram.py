"""
Stage 3: 코레지스트레이션 + 간섭도 + flat/topo 기준위상.
  - master/slave 복소 크롭 읽기
  - 서브샘플 기하(rdr2geo_dem + geo2rdr slave) → full-res 보간
  - 기하 기반 slave 리샘플(cubic 복소보간)
  - 진폭 상호상관으로 잔차 오프셋(궤도오차) 추정·보정
  - ifg = master·conj(slave_co),  기준위상 φ_ref = -4π/λ·(R_m-R_s)
  - 부호 자동판정(지형상관 최소) 후 차분간섭도
  체크포인트(.npy) 저장 + 진단 PNG.
"""
import numpy as np, json, time
from scipy.ndimage import zoom, map_coordinates
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import n2insar as N

WK = "<DATA_ROOT>/N2_InSAR/N2/taean_Insar/work/"
t_start = time.time()
def log(*a): print("[%6.1fs]"%(time.time()-t_start), *a, flush=True)

cr = json.load(open(WK+"crop.json"))
m = N.Scene(cr["master_path"]); s = N.Scene(cr["slave_path"])
m._side = cr["master_side"]; s._side = cr["slave_side"]
dem = N.DemInterp(cr["dem"])
lam = m.wavelength
mc = cr["master"]; sc = cr["slave"]
L0,L1,C0,C1 = mc["L0"],mc["L1"],mc["C0"],mc["C1"]
sL0,sL1,sC0,sC1 = sc["L0"],sc["L1"],sc["C0"],sc["C1"]
NL, NC = L1-L0, C1-C0
log("master crop lines[%d:%d] cols[%d:%d]  (%d x %d)"%(L0,L1,C0,C1,NL,NC))

# --- 복소 크롭 읽기 ---
mas, mret = m.read_slc(L0, L1, C0, C1)
log("master SLC read", mas.shape)
slv, sret = s.read_slc(sL0, sL1, sC0, sC1)
log("slave  SLC read", slv.shape)

# --- 서브샘플 기하 ---
SG = 5
sub_i = np.arange(L0, L1, SG); sub_j = np.arange(C0, C1, SG)
GI, GJ = np.meshgrid(sub_i, sub_j, indexing='ij')   # (nsi,nsj) 절대 인덱스
tm = m.line_to_t(GI); Rm = m.col_to_r(GJ)
log("rdr2geo_dem (subgrid %s)..."%(GI.shape,))
T, LATg, LONg, HGTg = N.rdr2geo_dem(m, tm, Rm, dem, h0=float(np.nanmedian(dem.arr)), n_iter=4)
log("geo2rdr slave (subgrid)...")
tguess = s.line_to_t(np.clip(m.t_to_line(tm)*0+ (GI-L0)/(L1-L0)*(sL1-sL0)+sL0, 0, s.nlines-1))
ts, Rs = N.geo2rdr(s, T, t_guess=s.line_to_t((GI-L0).astype(float)/max(1,(L1-L0))*(sL1-sL0)+sL0))
LINEs_g = s.t_to_line(ts); COLs_g = s.r_to_col(Rs)
DRg = (Rm - Rs)                       # float64, 평행 베이스라인성분
DR0 = float(np.nanmedian(DRg))
log("DR range: %.3f .. %.3f m (median %.3f)"%(DRg.min(),DRg.max(),DR0))

# --- full-res 로 업샘플(bilinear) ---
def up(a):
    return zoom(a.astype(np.float64), (NL/a.shape[0], NC/a.shape[1]), order=1).astype(np.float32)
LINEs = up(LINEs_g); COLs = up(COLs_g)
PHREF_dr = up(DRg - DR0)              # (R_m-R_s) - const, 미터
LAT = up(LATg); LON = up(LONg); HGT = up(HGTg)
log("upsampled geom to full res", LINEs.shape)
del LINEs_g, COLs_g, T, LATg, LONg, HGTg

# --- 기하 기반 slave 복소 리샘플 (cubic on re/im) ---
def resample_slave(src, line_abs, col_abs):
    yy = line_abs - sL0; xx = col_abs - sC0
    re = map_coordinates(src.real, [yy, xx], order=3, mode='constant', cval=0.0, prefilter=True)
    im = map_coordinates(src.imag, [yy, xx], order=3, mode='constant', cval=0.0, prefilter=True)
    return (re + 1j*im).astype(np.complex64)
slv_co = resample_slave(slv, LINEs, COLs)
log("slave geometric resample done")

# --- 잔차 오프셋(궤도오차) 추정: 진폭 NCC on patches ---
def subpix_ncc(A, B, maxs=4):
    A=A-A.mean(); B=B-B.mean()
    from numpy.fft import fft2, ifft2, fftshift
    F = ifft2(fft2(A)*np.conj(fft2(B)))
    F = fftshift(F).real
    cy,cx = np.array(F.shape)//2
    win = F[cy-maxs:cy+maxs+1, cx-maxs:cx+maxs+1]
    py,px = np.unravel_index(np.argmax(win), win.shape)
    yy = py-maxs; xx = px-maxs
    # parabolic subpixel
    def par(v):
        if 0<py<win.shape[0]-1: pass
        return 0.0
    # simple parabolic around peak in full F
    fy,fx = cy+yy, cx+xx
    dy=dx=0.0
    if 1<=fy<F.shape[0]-1:
        a0,a1,a2 = F[fy-1,fx],F[fy,fx],F[fy+1,fx]
        den=(a0-2*a1+a2); dy = 0.5*(a0-a2)/den if den!=0 else 0
    if 1<=fx<F.shape[1]-1:
        a0,a1,a2 = F[fy,fx-1],F[fy,fx],F[fy,fx+1]
        den=(a0-2*a1+a2); dx = 0.5*(a0-a2)/den if den!=0 else 0
    peak = F.max()/ (np.sqrt((A*A).sum()*(B*B).sum())+1e-9)
    return yy+dy, xx+dx, peak

mamp = np.abs(mas); samp = np.abs(slv_co)
ph=[]; win=96
for gi in np.linspace(win, NL-win, 9).astype(int):
    for gj in np.linspace(win, NC-win, 9).astype(int):
        A = mamp[gi-win//2:gi+win//2, gj-win//2:gj+win//2]
        B = samp[gi-win//2:gi+win//2, gj-win//2:gj+win//2]
        if A.mean()<1 or B.mean()<1 or (B>0).mean()<0.9: continue
        dy,dx,pk = subpix_ncc(A.astype(np.float64), B.astype(np.float64))
        if pk>0.06 and abs(dy)<3 and abs(dx)<3:
            ph.append((gi,gj,dy,dx,pk))
ph=np.array(ph)
if len(ph)>=6:
    dl_med=np.median(ph[:,2]); dc_med=np.median(ph[:,3])
    log("residual offset patches=%d  median dline=%.3f dcol=%.3f  (px)"%(len(ph),dl_med,dc_med))
else:
    dl_med=dc_med=0.0; log("residual: too few patches (%d), skip"%len(ph))
# 잔차 보정(상수) 후 재리샘플
if abs(dl_med)>0.02 or abs(dc_med)>0.02:
    slv_co = resample_slave(slv, LINEs+dl_med, COLs+dc_med)
    log("re-resampled slave with residual correction")

# --- 간섭도 + 기준위상 ---
phref = (-4.0*np.pi/lam) * PHREF_dr    # rad, (R_m-R_s - const) → flat+topo
ifg_raw = mas * np.conj(slv_co)
# 부호 자동판정: 지형 HGT 와 잔차위상 상관이 작아지는 부호 선택
def multilook_cpx(x, ay, ax):
    ny=(x.shape[0]//ay)*ay; nx=(x.shape[1]//ax)*ax
    return x[:ny,:nx].reshape(ny//ay,ay,nx//ax,ax).mean(axis=(1,3))
best=None
for sgn in (+1,-1):
    diff = ifg_raw * np.exp(1j*sgn*phref)
    d_ml = multilook_cpx(diff, 10, 10)
    h_ml = multilook_cpx(HGT.astype(np.complex64), 10,10).real
    # 잔차위상과 지형 상관(절대) — 작을수록 topo 제거 잘됨
    ph_ml = np.angle(d_ml)
    m2=np.isfinite(ph_ml)&(np.abs(d_ml)>0)
    c = abs(np.corrcoef(np.cos(ph_ml[m2]).ravel(), h_ml[m2].ravel())[0,1])
    # 코히런스 대체지표: |mean of unit phasors| 국소
    log("sign %+d: |corr(cos phase, height)|=%.3f"%(sgn,c))
    if best is None or c<best[0]: best=(c,sgn)
SGN=best[1]
log("chosen reference-phase sign: %+d"%SGN)
diff = (ifg_raw * np.exp(1j*SGN*phref)).astype(np.complex64)

# --- 저장 ---
np.save(WK+"mas.npy", mas)
np.save(WK+"slv_co.npy", slv_co)
np.save(WK+"ifg_diff.npy", diff)          # 차분(flat+topo 제거) 간섭도, full-res 복소
np.save(WK+"ifg_raw.npy", ifg_raw.astype(np.complex64))
np.save(WK+"LAT.npy", LAT); np.save(WK+"LON.npy", LON); np.save(WK+"HGT.npy", HGT)
np.save(WK+"phref.npy", phref.astype(np.float32))
json.dump(dict(NL=int(NL),NC=int(NC),L0=L0,C0=C0,lam=float(lam),sign=int(SGN),
               resid_dl=float(dl_med),resid_dc=float(dc_med),n_patch=int(len(ph))),
          open(WK+"stageA.json","w"), indent=2)
log("saved checkpoints")

# --- 진단 PNG: 진폭 / raw wrapped / diff wrapped / coherence(quick) / height ---
def ml_pow(x,ay,ax):
    p=x[:(x.shape[0]//ay)*ay, :(x.shape[1]//ax)*ax]
    return p.reshape(p.shape[0]//ay,ay,p.shape[1]//ax,ax)
AY,AX=10,10
def coh(mm,ss,ay,ax):
    num=multilook_cpx(mm*np.conj(ss),ay,ax)
    den=np.sqrt(multilook_cpx(np.abs(mm)**2,ay,ax)*multilook_cpx(np.abs(ss)**2,ay,ax))
    return np.abs(num)/(den+1e-9)
cohq = coh(mas, slv_co*np.exp(1j*SGN*phref), AY, AX)
amp_ml = np.sqrt(multilook_cpx(np.abs(mas)**2,AY,AX).real)
raw_ml = multilook_cpx(ifg_raw,AY,AX); diff_ml = multilook_cpx(diff,AY,AX)
h_ml = multilook_cpx(HGT.astype(np.complex64),AY,AX).real
log("quick coherence mean=%.3f  (land approx)"%np.nanmean(cohq[cohq>0]))
fig,ax=plt.subplots(1,5,figsize=(25,7))
ax[0].imshow(np.log1p(amp_ml),cmap='gray',aspect='auto'); ax[0].set_title("amplitude ML")
ax[1].imshow(np.angle(raw_ml),cmap='hsv',aspect='auto'); ax[1].set_title("raw wrapped (flat+topo+def)")
ax[2].imshow(np.angle(diff_ml),cmap='hsv',aspect='auto'); ax[2].set_title("diff wrapped (topo removed) sign%+d"%SGN)
im3=ax[3].imshow(cohq,cmap='viridis',aspect='auto',vmin=0,vmax=1); ax[3].set_title("coherence"); plt.colorbar(im3,ax=ax[3],fraction=0.04)
im4=ax[4].imshow(h_ml,cmap='terrain',aspect='auto'); ax[4].set_title("DEM height"); plt.colorbar(im4,ax=ax[4],fraction=0.04)
for a in ax: a.axis('off')
plt.tight_layout(); plt.savefig(WK+"diag_stageA.png",dpi=70); log("saved diag_stageA.png")
