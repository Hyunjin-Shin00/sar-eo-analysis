#!/usr/bin/env python3
# 일반화 PS/SBAS 클릭맵. OSM/Esri, 빨강=침하 파랑=융기, 클릭→시계열, 기준영역 마커, POI(선택).
import os, sys
os.environ.pop('PYTHONPATH', None)
import argparse, json
import numpy as np
import geopandas as gpd

def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--shp", required=True)
    p.add_argument("--ref", default=None)
    p.add_argument("--poi", nargs=2, type=float, default=None, metavar=("LAT","LON"))
    p.add_argument("--poi_label", default="싱크홀 발생지점")
    p.add_argument("--no_poi", action="store_true")
    p.add_argument("--out", required=True)
    p.add_argument("--title", default="PS-InSAR (LOS 변위)")
    return p.parse_args()

def main():
    a = parse()
    g = gpd.read_file(a.shp)
    lon = g["Longitude"].to_numpy(float); lat = g["Latitude"].to_numpy(float)
    vel = g["velocity"].to_numpy(float)
    dcols = [c for c in g.columns if len(c)==9 and c[0]=="D" and c[1:].isdigit()]; dcols.sort(key=lambda c:c[1:])
    disp = g[dcols].to_numpy(float); dates=[f"{c[1:5]}-{c[5:7]}-{c[7:9]}" for c in dcols]; n=len(g)
    vmax=float(np.nanpercentile(np.abs(vel),95)) if n else 5.0; vmax=max(vmax,1e-6)
    # 통일(고정) y스케일: 전체 변위의 로버스트 대칭 범위 ±gyabs (다른 점과 비교용, nice 반올림)
    _fin=disp[np.isfinite(disp)]
    _gm=float(np.nanpercentile(np.abs(_fin),98)) if _fin.size else 5.0; _gm=max(_gm,1.0)
    _e=np.floor(np.log10(_gm)); _base=_gm/10**_e
    _b=1 if _base<=1 else (2 if _base<=2 else (5 if _base<=5 else 10))
    gyabs=round(float(_b*10**_e),3)
    pts=[]
    for i in range(n):
        row=[round(float(lon[i]),6),round(float(lat[i]),6),round(float(vel[i]),3)]
        row+=[None if not np.isfinite(disp[i,j]) else round(float(disp[i,j]),1) for j in range(disp.shape[1])]
        pts.append(row)
    ref=None
    if a.ref and os.path.isfile(a.ref):
        rj=json.load(open(a.ref))
        if rj.get("ok"):
            rlon,rlat,rr=rj["ref_lon"],rj["ref_lat"],rj["ref_radius_m"]
            lat0=float(np.nanmean(lat)); dx=(lon-rlon)*111320.0*np.cos(np.deg2rad(lat0)); dy=(lat-rlat)*111320.0
            ins=(dx*dx+dy*dy)<=(rr*rr); n_in=int(ins.sum())
            ats=np.nanmean(disp[ins,:],axis=0) if n_in>0 else np.full(disp.shape[1],np.nan)
            av=float(np.nanmean(vel[ins])) if n_in>0 else float('nan')
            ref={"lon":rlon,"lat":rlat,"r":rr,"n":rj.get("n_ps_in_ref"),"n_in":n_in,
                 "avg_v":av,"ts":[None if not np.isfinite(v) else round(float(v),2) for v in ats]}
    poi=None
    if not a.no_poi and a.poi is not None:
        poi={"lat":a.poi[0],"lon":a.poi[1],"label":a.poi_label}
    data={"dates":dates,"pts":pts,"vmax":vmax,"gyabs":gyabs,"ref":ref,"poi":poi,
          "center":[float(np.nanmean(lat)),float(np.nanmean(lon))],"title":a.title,"n":n}
    payload=json.dumps(data,ensure_ascii=False,separators=(",",":"))
    html=r"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>__TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
html,body,#map{height:100%;margin:0}
.info{background:#fff;padding:8px 10px;border-radius:6px;font:12px/1.4 sans-serif;box-shadow:0 1px 6px rgba(0,0,0,.35);max-width:300px}
.lg{line-height:18px}.lg i{width:16px;height:12px;float:left;margin-right:6px;opacity:.95}
.cbar{height:12px;width:230px;background:linear-gradient(to right,#b2182b,#ef8a62,#fddbc7,#f7f7f7,#d1e5f0,#67a9cf,#2166ac);border:1px solid #999}
.ttl{font-weight:700;margin-bottom:4px}
.poi-lbl{background:#c0392b;color:#fff;border:none;font-weight:700;font-size:12px;padding:2px 6px;border-radius:3px}
.ref-lbl{background:#1e8449;color:#fff;border:none;font-weight:700;font-size:12px;padding:2px 6px;border-radius:3px}
.pop{font:12px sans-serif}.leaflet-popup-content{margin:10px 12px}
</style></head><body><div id="map"></div><script>
var D=__PAYLOAD__;
var map=L.map('map',{preferCanvas:true}).setView(D.center,13);
var osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'});
var esri=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles &copy; Esri'});
osm.addTo(map);
function clamp(x,a,b){return x<a?a:(x>b?b:x);} function lerp(a,b,t){return a+(b-a)*t;}
var STOPS=[[178,24,43],[239,138,98],[253,219,199],[247,247,247],[209,229,240],[103,169,207],[33,102,172]];
function colorFor(v){var t=clamp((v/D.vmax+1)/2,0,1);var s=t*(STOPS.length-1);var i=Math.floor(s);var f=s-i;
 if(i>=STOPS.length-1){i=STOPS.length-2;f=1;}var c0=STOPS[i],c1=STOPS[i+1];
 return 'rgb('+Math.round(lerp(c0[0],c1[0],f))+','+Math.round(lerp(c0[1],c1[1],f))+','+Math.round(lerp(c0[2],c1[2],f))+')';}
function tsSVG(dv,stroke,fixed,W,cap){stroke=stroke||'#1a5276';W=W||440;var H=236,mL=50,mR=16,mT=28,mB=64;var ys=[],idx=[];
 for(var i=0;i<dv.length;i++){if(dv[i]!=null){idx.push(i);ys.push(dv[i]);}} if(ys.length<2)return '<div class="pop" style="width:'+W+'px;padding-top:20px;color:#888">시계열 없음</div>';
 var ymin,ymax;
 if(fixed){ymin=fixed[0];ymax=fixed[1];}
 else{ymin=Math.min.apply(null,ys);ymax=Math.max.apply(null,ys);if(ymin===ymax){ymin-=1;ymax+=1;}var pad=(ymax-ymin)*0.12;ymin-=pad;ymax+=pad;}
 var n=D.dates.length;function X(i){return mL+(W-mL-mR)*(i/(n-1));}function Y(v){return clamp(mT+(H-mT-mB)*(1-(v-ymin)/(ymax-ymin)),mT,H-mB);}
 var pl='';for(var k=0;k<idx.length;k++){pl+=(k?' ':'')+X(idx[k]).toFixed(1)+','+Y(ys[k]).toFixed(1);}
 var dots='';for(var k=0;k<idx.length;k++){dots+='<circle cx="'+X(idx[k]).toFixed(1)+'" cy="'+Y(ys[k]).toFixed(1)+'" r="2" fill="'+stroke+'"/>';}
 var yt='';for(var t=0;t<=4;t++){var vv=ymin+(ymax-ymin)*t/4;var yy=Y(vv);
  yt+='<line x1="'+mL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-mR)+'" y2="'+yy.toFixed(1)+'" stroke="#eee"/>';
  yt+='<text x="'+(mL-6)+'" y="'+(yy+3).toFixed(1)+'" font-size="10" text-anchor="end" fill="#555">'+vv.toFixed(1)+'</text>';}
 var zl='';if(ymin<0&&ymax>0){var z=Y(0);zl='<line x1="'+mL+'" y1="'+z.toFixed(1)+'" x2="'+(W-mR)+'" y2="'+z.toFixed(1)+'" stroke="#c0392b" stroke-dasharray="4,3"/>';}
 var ax='<line x1="'+mL+'" y1="'+mT+'" x2="'+mL+'" y2="'+(H-mB)+'" stroke="#999"/><line x1="'+mL+'" y1="'+(H-mB)+'" x2="'+(W-mR)+'" y2="'+(H-mB)+'" stroke="#999"/>';
 var xt='';var NT=6;for(var q=0;q<NT;q++){var ii=Math.round((n-1)*q/(NT-1));var xx=X(ii);
  xt+='<text x="'+xx.toFixed(1)+'" y="'+(H-mB+8)+'" font-size="9.5" fill="#555" text-anchor="end" transform="rotate(-40 '+xx.toFixed(1)+' '+(H-mB+8)+')">'+D.dates[ii]+'</text>';}
 var cp=cap?'<text x="'+mL+'" y="15" font-size="11" font-weight="700" fill="#333">'+cap+'</text>':'';
 return '<svg width="'+W+'" height="'+H+'" style="background:#fff;display:block">'+cp+yt+ax+zl
  +'<polyline points="'+pl+'" fill="none" stroke="'+stroke+'" stroke-width="1.5"/>'+dots
  +'<text x="'+(W-mR)+'" y="15" font-size="9.5" fill="#888" text-anchor="end">누적 LOS(mm)</text>'+xt+'</svg>';}
var layer=L.layerGroup().addTo(map);
for(var i=0;i<D.pts.length;i++){var p=D.pts[i];var lo=p[0],la=p[1],v=p[2];var dv=p.slice(3);
 var m=L.circleMarker([la,lo],{radius:3,stroke:false,fillColor:colorFor(v),fillOpacity:0.85});
 (function(la,lo,v,dv){m.on('click',function(e){
   var h='<div class="pop"><b>PS</b> · 위도 '+la.toFixed(5)+', 경도 '+lo.toFixed(5)+' · 속도 <b>'+v.toFixed(2)+' mm/yr</b> '+(v<0?'(침하)':'(융기)')
    +'<div style="display:flex;gap:6px;margin-top:4px">'+tsSVG(dv,null,null,370,'개별 스케일(자동)')+tsSVG(dv,null,[-D.gyabs,D.gyabs],370,'통일 스케일(±'+D.gyabs+'mm)')+'</div></div>';
   L.popup({maxWidth:820,minWidth:790}).setLatLng([la,lo]).setContent(h).openOn(map);L.DomEvent.stopPropagation(e);});})(la,lo,v,dv);
 m.addTo(layer);}
L.control.layers({'OpenStreetMap':osm,'Esri 위성영상':esri},{'결과 포인트':layer},{collapsed:false}).addTo(map);
if(D.poi){var poi=D.poi;
 L.circleMarker([poi.lat,poi.lon],{radius:9,color:'#c0392b',weight:3,fill:false,interactive:false}).addTo(map);
 L.marker([poi.lat,poi.lon],{opacity:0,interactive:false}).addTo(map).bindTooltip(poi.label,{permanent:true,direction:'top',className:'poi-lbl',offset:[0,-6]});}
if(D.ref){var r=D.ref;
 L.circle([r.lat,r.lon],{radius:r.r,color:'#1e8449',weight:2,fillColor:'#2ecc71',fillOpacity:0.15,interactive:false}).addTo(map);
 L.marker([r.lat,r.lon],{opacity:0,interactive:false}).addTo(map).bindTooltip('기준(안정)영역',{permanent:true,direction:'bottom',className:'ref-lbl',offset:[0,6]});
 var rd=L.circleMarker([r.lat,r.lon],{radius:6,color:'#145a32',weight:2,fillColor:'#27ae60',fillOpacity:0.9}).addTo(map);
 rd.on('click',function(e){var h='<div class="pop"><b>기준(안정)영역 평균 시계열</b> · 중심 '+r.lat.toFixed(5)+', '+r.lon.toFixed(5)+' · 반경 '+r.r+'m · 영역내 '+(r.n_in||r.n)+'점 · 평균속도 <b>'+(r.avg_v!=null?r.avg_v.toFixed(2):'-')+' mm/yr</b>'
   +'<div style="display:flex;gap:6px;margin-top:4px">'+tsSVG(r.ts,'#1e8449',null,370,'개별 스케일(자동)')+tsSVG(r.ts,'#1e8449',[-D.gyabs,D.gyabs],370,'통일 스케일(±'+D.gyabs+'mm)')+'</div></div>';
  L.popup({maxWidth:820,minWidth:790}).setLatLng([r.lat,r.lon]).setContent(h).openOn(map);L.DomEvent.stopPropagation(e);});}
var lg=L.control({position:'bottomright'});
lg.onAdd=function(){var d=L.DomUtil.create('div','info lg');var vm=D.vmax.toFixed(1);
 d.innerHTML='<div class="ttl">'+D.title+'</div>포인트: <b>'+D.n+'</b> · 클릭→시계열<br>'
 +'<div style="margin:5px 0 2px">LOS velocity (mm/yr)</div><div class="cbar"></div>'
 +'<div style="display:flex;justify-content:space-between;width:230px"><span>-'+vm+'</span><span>0</span><span>+'+vm+'</span></div>'
 +'<div style="margin-top:2px"><b style="color:#b2182b">빨강=침하(-)</b> · <b style="color:#2166ac">파랑=융기(+)</b></div>'
 +(D.ref?'<div style="margin-top:6px"><i style="background:#27ae60;border:1px solid #145a32;border-radius:50%"></i> 기준(안정)영역</div>':'')
 +(D.poi?'<div style="margin-top:3px"><i style="background:none;border:2px solid #c0392b;border-radius:50%"></i> '+D.poi.label+'</div>':'');
 return d;};lg.addTo(map);
var b=L.latLngBounds(D.pts.map(function(p){return [p[1],p[0]];}));
if(D.poi)b.extend([D.poi.lat,D.poi.lon]); if(D.pts.length)map.fitBounds(b.pad(0.05));
</script></body></html>"""
    html=html.replace("__TITLE__",a.title).replace("__PAYLOAD__",payload)
    open(a.out,"w").write(html)
    print(f"wrote {a.out} ({n} pts, {len(dates)} dates, vmax={vmax:.2f}, ref={'y' if ref else 'n'}, poi={'y' if poi else 'n'})")

if __name__=="__main__": main()
