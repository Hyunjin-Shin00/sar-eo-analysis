"""Result 폴더 산출물을 하나의 인터랙티브 HTML(result.html)로. Leaflet+ESRI basemap,
   래스터 레이어 ON/OFF, 레이어별 MIN/MAX·컬러맵, 폴리곤 오버레이, 분석표+갤러리."""
import numpy as np, json, base64, os
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
from osgeo import ogr
R="<DATA_ROOT>/N2_InSAR/Result/"; INS=R+"taean_InSAR/"; CCD=R+"taean_CCD/"; OT=R+"taean_OT/"
W,E,S,Nn=126.3548,126.4107,36.3899,36.4350; res=0.00027778
nx=int(round((E-W)/res)); ny=int(round((Nn-S)/res)); dst_tr=from_origin(W,Nn,res,res)
south=Nn-ny*res; east=W+nx*res; BOUNDS=[[south,W],[Nn,east]]
DEMf="<DATA_ROOT>/N2_InSAR/DEM/cop_dem_N36E126.tif"
# 폴리곤
ds=ogr.Open("<DATA_ROOT>/N2_InSAR/shp/Taean.shp"); ly=ds.GetLayer(); f=ly.GetNextFeature()
gj=json.loads(f.GetGeometryRef().ExportToJson()); PCOORDS=gj["coordinates"][0]
from rasterio.features import rasterize
POLY=rasterize([(gj,1)],out_shape=(ny,nx),transform=dst_tr,fill=0,all_touched=True).astype(bool)

def grid(path,band,resamp,zeronan=False):
    d=rasterio.open(path); a=d.read(band).astype("float32")
    if np.iscomplexobj(a): a=np.angle(a).astype("float32")
    src_nd=d.nodata
    if src_nd is not None and not np.isnan(src_nd): a[a==src_nd]=np.nan
    out=np.full((ny,nx),np.nan,"float32")
    rs=Resampling.nearest if resamp=="nearest" else Resampling.bilinear
    reproject(a,out,src_transform=d.transform,src_crs=d.crs,dst_transform=dst_tr,dst_crs="EPSG:4326",
              resampling=rs,src_nodata=np.nan,dst_nodata=np.nan)
    if zeronan: out[out==0]=np.nan
    return out

# 레이어 정의: (id, group, name, path, band, cmap, resamp, unit, dmin, dmax, zeronan)
A="auto"
GC="CCD (Coherence Change Detection)"; GI="InSAR (Interferometric SAR)"; GO="OT (Offset Tracking)"; GIS="InSAR (ISCE2)"; GA="ACD (Amplitude Change Detection)"; GAMP="SLC amplitude (실제 SAR 영상)"
LAYERS=[
 ("amp_n2_0515",GAMP,"N2 20260515 (A_L 32°)",INS+"N2_AL_20260515_20260614_insar_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("amp_n2_0614",GAMP,"N2 20260614 (A_L 32°)",CCD+"N2_AL_20260614_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("amp_n2_0511",GAMP,"N2 20260511 (A_L 20°)",CCD+"N2_AL_20260511_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("amp_n2_0706",GAMP,"N2 20260706 (A_L 20°)",CCD+"N2_AL_20260706_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("amp_n2_0402",GAMP,"N2 20260402 (A_R)",CCD+"N2_AR_20260402_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("amp_n2_0529",GAMP,"N2 20260529 (A_R)",CCD+"N2_AR_20260529_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("amp_n2_0613",GAMP,"N2 20260613 (A_R)",CCD+"N2_AR_20260613_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("amp_s1_0519",GAMP,"S1 20260519",CCD+"s1_20260519_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("amp_s1_0531",GAMP,"S1 20260531",CCD+"s1_20260531_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("amp_s1_0613",GAMP,"S1 20260613",CCD+"s1_20260613_amplitude.tif",1,"gray","bilinear","",A,A,0),
 ("n2acd_ll32","N2 "+GA,"log-ratio 0515x0614 (A_L 32°)",CCD+"N2_AL_20260515_20260614_logratio_dB.tif",1,"rdbu","bilinear","dB",-6,6,0),
 ("n2acd_ll20","N2 "+GA,"log-ratio 0511x0706 (A_L 20°)",CCD+"N2_AL_20260511_20260706_logratio_dB.tif",1,"rdbu","bilinear","dB",-6,6,0),
 ("n2acd_ar1","N2 "+GA,"log-ratio 0402x0613 (A_R)",CCD+"N2_AR_20260402_20260613_logratio_dB.tif",1,"rdbu","bilinear","dB",-6,6,0),
 ("n2acd_ar2","N2 "+GA,"log-ratio 0529x0613 (A_R)",CCD+"N2_AR_20260529_20260613_logratio_dB.tif",1,"rdbu","bilinear","dB",-6,6,0),
 ("n2ins_coh","N2 "+GI,"Coherence",INS+"N2_AL_20260515_20260614_insar_coherence.tif",1,"viridis","bilinear","coh",0,0.4,0),
 ("n2ins_wrap","N2 "+GI,"Wrapped phase",INS+"N2_AL_20260515_20260614_insar_wrapped.tif",1,"hsv","nearest","rad",-3.1416,3.1416,0),
 ("n2ins_unw","N2 "+GI,"Unwrapped phase",INS+"N2_AL_20260515_20260614_insar_unwrapped.tif",1,"rainbow","bilinear","rad",A,A,0),
 ("n2ins_los","N2 "+GI,"LOS displacement (cm)",INS+"N2_AL_20260515_20260614_insar_los_cm.tif",1,"rdbu","bilinear","cm",A,A,0),
 ("n2ot_az","N2 "+GO,"Azimuth offset (m)",OT+"N2_AL_20260515_20260614_OT_azimuth_m.tif",1,"rdbu","bilinear","m",-6,6,0),
 ("n2ot_rg","N2 "+GO,"Range offset (m)",OT+"N2_AL_20260515_20260614_OT_range_m.tif",1,"rdbu","bilinear","m",-4,4,0),
 ("n2ot_cc","N2 "+GO,"NCC correlation",OT+"N2_AL_20260515_20260614_OT_correlation.tif",1,"viridis","bilinear","",0,0.3,0),
 ("s1acd_lr","S1 "+GA,"Amplitude log-ratio (dB)",CCD+"s1_20260519_20260613_logratio_dB.tif",1,"rdbu","bilinear","dB",-6,6,0),
 ("s1ins_coh","S1 "+GIS,"Coherence",INS+"s1_20260519_20260531_insar_coherence.tif",1,"viridis","bilinear","coh",0,0.6,0),
 ("s1ins_wrap","S1 "+GIS,"Wrapped phase",INS+"s1_20260519_20260531_insar_wrapped.tif",1,"hsv","nearest","rad",-3.1416,3.1416,0),
 ("s1ins_unw","S1 "+GIS,"Unwrapped phase",INS+"s1_20260519_20260531_insar_unwrapped.tif",1,"rainbow","bilinear","rad",A,A,0),
 ("s1ins_los","S1 "+GIS,"LOS displacement (cm)",INS+"s1_20260519_20260531_insar_los_cm.tif",1,"rdbu","bilinear","cm",-3,3,0),
 ("s1ot_az","S1 "+GO,"Azimuth offset (m)",OT+"s1_20260519_20260613_OT_azimuth_m.tif",1,"rdbu","bilinear","m",-15,15,0),
 ("s1ot_rg","S1 "+GO,"Range offset (m)",OT+"s1_20260519_20260613_OT_range_m.tif",1,"rdbu","bilinear","m",-3,3,0),
 ("s1ot_cc","S1 "+GO,"NCC correlation",OT+"s1_20260519_20260613_OT_correlation.tif",1,"viridis","bilinear","",0,0.5,0),
]
# --- 지오이드 수직기준 보정 시프트 (DEM 정표고 -> 타원체고, 룩사이드별 range방향 Δx=N/tanθ) ---
import math as _m
GEOID_N=24.5; _clat=math.cos(math.radians(0.5*(S+Nn))) if False else _m.cos(_m.radians(0.5*(S+Nn)))
_AL20={"amp_n2_0511","amp_n2_0706","n2acd_ll20"}
_AR={"amp_n2_0402","amp_n2_0529","amp_n2_0613","n2acd_ar1","n2acd_ar2"}
def _geom(lid):
    if lid in _AL20: return (256.0,20.1)       # A_L 20° (range 256°)
    if lid in _AR: return (79.0,30.5)          # A_R (range 79°)
    if lid.startswith("amp_s1") or lid.startswith("s1"): return (281.0,34.0)  # S1 (range 281°)
    return (256.0,32.3)                        # 기본 N2 A_L 32°
def _shift(lid):
    brg,th=_geom(lid); dx=GEOID_N/_m.tan(_m.radians(th))
    dN=dx*_m.cos(_m.radians(brg)); dE=dx*_m.sin(_m.radians(brg))
    return dN/111320.0, dE/(111320.0*_clat)    # dlat, dlon (range +방향으로 이동해 보정)
manifest=[]
for lid,grp,name,path,band,cmap,resamp,unit,dmin,dmax,zn in LAYERS:
    if not os.path.exists(path): print("MISSING",path); continue
    a=grid(path,band,resamp,bool(zn)); fin=np.isfinite(a)
    if dmin==A: dmin=float(np.nanpercentile(a,2)); dmax=float(np.nanpercentile(a,98))
    aoimean=float(np.nanmean(a[fin])) if fin.any() else float("nan")
    pm=POLY&fin; polymean=float(np.nanmean(a[pm])) if pm.any() else float("nan")
    b64=base64.b64encode(a.astype("<f4").tobytes()).decode("ascii")
    dlat,dlon=_shift(lid); bnds=[[round(south+dlat,7),round(W+dlon,7)],[round(Nn+dlat,7),round(east+dlon,7)]]
    manifest.append(dict(id=lid,group=grp,name=name,unit=unit,cmap=cmap,vmin=round(dmin,4),vmax=round(dmax,4),
        w=nx,h=ny,bounds=bnds,aoiMean=round(aoimean,3),polyMean=round(polymean,3),data=b64))
    print("layer %-11s AOI %.3f POLY %.3f"%(lid,aoimean,polymean))

# SLC 진폭: 센서별(N2끼리, S1끼리) 기본 min/max 통일 (사용자가 입력창에서 수정 가능)
def _amparr(lid):
    m=[x for x in manifest if x["id"]==lid][0]
    return np.frombuffer(base64.b64decode(m["data"]),"<f4").reshape(m["h"],m["w"])
for sensor,ids in {"N2":["amp_n2_0515","amp_n2_0614","amp_n2_0511","amp_n2_0706","amp_n2_0402","amp_n2_0529","amp_n2_0613"],"S1":["amp_s1_0519","amp_s1_0531","amp_s1_0613"]}.items():
    ids=[i for i in ids if any(x["id"]==i for x in manifest)]
    if not ids: continue
    allv=np.concatenate([_amparr(i).ravel() for i in ids]); allv=allv[np.isfinite(allv)]
    vmn=float(np.percentile(allv,2)); vmx=float(np.percentile(allv,98))
    for i in ids:
        mm=[x for x in manifest if x["id"]==i][0]; mm["vmin"]=round(vmn,3); mm["vmax"]=round(vmx,3)
    print("amp %s unified vmin=%.1f vmax=%.1f"%(sensor,vmn,vmx))

# 갤러리(요약 그림, <=1.6MB)
GAL=[]  # 요약 그림 섹션 제거

# 분석표 HTML
def rowspan_group(g): return sum(1 for m in manifest if m["group"]==g)
groups=[GAMP,"N2 "+GI,"N2 "+GA,"N2 "+GO,"S1 "+GIS,"S1 "+GA,"S1 "+GO]
GDATES={"N2 "+GI:"20260515 × 20260614","N2 "+GO:"20260515 × 20260614",
        "S1 "+GIS:"20260519 x 20260531",
        "S1 "+GA:"20260519 → 20260613","S1 "+GO:"20260519 × 20260613"}
rows=""
for g in groups:
    first=True
    for m in [x for x in manifest if x["group"]==g]:
        gc=('<td rowspan="%d" class="gcell">%s</td>'%(rowspan_group(g),g)) if first else ""
        u=m["unit"]
        rows+='<tr>%s<td>%s</td><td>%s</td></tr>'%(gc,m["name"],u); first=False
DIRS={"n2":{"az":346,"rg":256},"s1":{"az":191,"rg":281}}
defrows=[
 ("Coherence (0~1)","두 시점 SAR 위상의 상관도","높음: 두 시점 표면이 안정·일관","낮음: 표면이 변함"),
 ("Amplitude log-ratio (dB)","두 시점 후방산란 세기비 20·log₁₀(A₂/A₁)","양(+): 나중 영상이 밝아짐(거칠어짐·건조)","음(−): 어두워짐(매끈·습윤)"),
 ("Wrapped phase (rad, −π~π)","−π~π로 접은 간섭 위상","프린지 조밀: 변위·지형차 큼","프린지 성김: 변화 적음"),
 ("Unwrapped phase (rad)","정수배를 더해 이어붙인 연속 위상(상대값)","값 클수록 기준점 대비 위상차 큼","작을수록 위상차 작음"),
 ("LOS (Line of Sight) displacement (cm)","언래핑 위상을 시선방향(LOS) 변위로 환산(상대값)","양(+): 위성에 가까워짐","음(−): 위성에서 멀어짐"),
 ("Azimuth / Range offset (m)","진폭 정합으로 구한 화소 이동량(방향=나침반)","절대값 큼: 이동/오정합 큼","0 근처: 이동 거의 없음"),
 ("NCC (Normalized Cross-Correlation, 0~1)","진폭 정합의 품질","높음: 정합 신뢰 높음","낮음: 정합 신뢰 낮음"),
]
defbody="".join("<tr><td class='dt'>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"%r for r in defrows)
techniques=('<div class="defs"><p><b>기법 개요</b></p><ul class="tech">'
 '<li><b>InSAR (간섭)</b>: 두 시점 위상차로 지표 변위를 cm급으로 측정(코히런스 높아야 유효).</li>'
 '<li><b>ACD (진폭 변화탐지)</b>: 두 시점 후방산란(진폭) 비교로 표면상태 변화를 탐지 - baseline 무관·같은 기하면 가능 → N2·S1 모두.</li>'
 '<li><b>OT (오프셋 트래킹)</b>: 진폭 패턴 정합으로 화소단위 이동을 측정. <b>방위+거리 오프셋을 합치면 실제 이동 벡터(방향+크기)</b> - 지도의 "OT displacement vectors" 레이어로 화살표 표시.</li>'
 '</ul>'
 '<table class="tbl"><thead><tr><th>분석 기법</th><th>의미</th><th>값이 크면(양)</th><th>값이 작으면(음)</th></tr></thead><tbody>'
 +defbody+'</tbody></table></div>')
results=('<table class="tbl"><thead><tr><th>그룹</th><th>레이어</th><th>단위</th></tr></thead><tbody>'
         +rows+'</tbody></table>')

# --- OT 이동벡터: 편집본 GeoJSON에서 재구성 (표시 전용) ---
import math, json as _json
GEOJSON=R+"taean_OT/ot_vectors_edited.geojson"
LAB2KEY={"N2 OT 0515×0614":("n2ot",346,256,"#ffd24d"),"S1 OT 0519×0613":("s1ot",191,281,"#4da3ff")}
pts={}; meta={}
for f in _json.load(open(GEOJSON,encoding="utf-8"))["features"]:
    p=f["properties"]; lab=p.get("sensor")
    if lab not in LAB2KEY: continue
    key,thaz,thrg,col=LAB2KEY[lab]; lon0,lat0=f["geometry"]["coordinates"]
    pts.setdefault(key,[]).append((lat0,lon0,p["azimuth_offset_m"],p["range_offset_m"],p["magnitude_m"]))
    meta[key]=(thaz,thrg,col,lab)
def build_from_pts(key):
    lst=pts.get(key,[]); thaz,thrg,col,lab=meta.get(key,(0,0,"#fff",key))
    if not lst: return dict(arrows=[],med=0,n=0,color=col,label=lab)
    ta=math.radians(thaz); trr=math.radians(thrg); mags=[m for *_,m in lst]
    p90=float(np.percentile(mags,90)) or 1.0; Sm=(1.4*3*res*111320.0)/(p90+1e-9); arrows=[]
    sla,slo=_shift(key)   # 지오이드 보정 시프트 (n2ot=A_L32°, s1ot=S1)
    for lat0,lon0,az,rg,mg in lst:
        lat0+=sla; lon0+=slo
        E=az*math.sin(ta)+rg*math.sin(trr); Nc=az*math.cos(ta)+rg*math.cos(trr)
        dEm=E*Sm; dNm=Nc*Sm; L=math.hypot(dEm,dNm)
        if L<1e-6: continue
        mlat=111320.0; mlon=111320.0*math.cos(math.radians(lat0))
        lat1=lat0+dNm/mlat; lon1=lon0+dEm/mlon; bx=-dEm/L; by=-dNm/L; hl=0.28*L; hh={}
        for ang in (25,-25):
            a=math.radians(ang); rx=bx*math.cos(a)-by*math.sin(a); ry=bx*math.sin(a)+by*math.cos(a)
            hh[ang]=(lat1+hl*ry/mlat, lon1+hl*rx/mlon)
        arrows.append([round(lat0,6),round(lon0,6),round(lat1,6),round(lon1,6),
                       round(hh[25][0],6),round(hh[25][1],6),round(hh[-25][0],6),round(hh[-25][1],6),round(float(mg),2)])
    return dict(arrows=arrows,med=round(float(np.median(mags)),2),n=len(arrows),color=col,label=lab)
VECTORS={k:build_from_pts(k) for k in ["n2ot","s1ot"]}
print("vectors from geojson N2=%d S1=%d"%(VECTORS["n2ot"]["n"],VECTORS["s1ot"]["n"]))

TPL=open(R+"_template.html",encoding="utf-8").read()
html=TPL.replace("__MANIFEST__",json.dumps(manifest)).replace("__POLYGON__",json.dumps(PCOORDS))\
    .replace("__TECHNIQUES__",techniques).replace("__RESULTS__",results).replace("__VECTORS__",json.dumps(VECTORS))\
    .replace("__BOUNDS__",json.dumps(BOUNDS)).replace("__DIRS__",json.dumps(DIRS)).replace("__GDATES__",json.dumps(GDATES))
open(R+"result.html","w",encoding="utf-8").write(html)
print("saved result.html  size %.2f MB  layers=%d gallery=%d"%(os.path.getsize(R+"result.html")/1e6,len(manifest),len(GAL)))
