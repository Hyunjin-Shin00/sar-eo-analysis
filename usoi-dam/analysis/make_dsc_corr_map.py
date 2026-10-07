#!/usr/bin/env python3
# Standalone HTML: Esri imagery + water-masked, AOI-cropped DSC LOS velocity.
# The RAW velocity field (float32) is embedded and colour-mapped live in JS, so the
# user can set the colourbar min/max interactively (symmetric or free). Includes a
# layer toggle, opacity slider, and an interactive displacement time-series chart.
import os
ROOT=os.environ.get('DATA_ROOT','<DATA_ROOT>')  # dir containing SBAS/ and sentinel1/
import base64, json, os
D=ROOT+'/SBAS/DECOMP'
m=json.load(open(f'{D}/dsc_corr_meta.json'))
fb64=base64.b64encode(open(f'{D}/Usoi_DSC_corr_field.bin','rb').read()).decode()
(S,W),(N,E)=m['bounds']; PLAT,PLON=m['point']
SNX,SNY=m['snx'],m['sny']
LUT=json.dumps(m['lut'])
VMIN0,VMAX0=m['vmin_default'],m['vmax_default']
VDMIN,VDMAX=m['vdata_min'],m['vdata_max']
ts=json.dumps(m['ts']['year']); ds=json.dumps(m['ts']['disp']); dd=json.dumps(m['ts']['date'])

HTML=f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Usoi Dam — DSC land-only LOS velocity + time series</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body{{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
  #map{{position:absolute;inset:0}}
  .panel{{background:rgba(16,25,35,.93);color:#e7eef5;border:1px solid #2a3a4a;border-radius:11px;
    padding:12px 14px;font-size:13px;box-shadow:0 6px 22px rgba(0,0,0,.45);backdrop-filter:blur(5px)}}
  .panel h3{{margin:0 0 8px;font-size:13px}}
  .sub{{color:#93a6b7;font-size:11.5px;font-family:ui-monospace,Menlo,monospace;margin:0 0 8px;line-height:1.5}}
  .row{{display:flex;align-items:center;gap:8px;margin-top:8px}}
  .row label{{font-size:12px;color:#cdd8e2;min-width:50px}}
  input[type=range]{{flex:1;accent-color:#3fb9c9}}
  input[type=number]{{width:70px;background:#0c141d;border:1px solid #2a3a4a;color:#e7eef5;border-radius:6px;
    padding:4px 6px;font-family:ui-monospace,Menlo,monospace;font-size:12px}}
  button{{background:#1d2b3a;border:1px solid #3fb9c9;color:#7fd6e1;border-radius:6px;padding:4px 10px;
    font-size:12px;cursor:pointer}}
  button:hover{{background:#254056}}
  .toggle{{display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;user-select:none;margin-top:8px}}
  .toggle input{{width:16px;height:16px;accent-color:#3fb9c9}}
  .val{{font-family:ui-monospace,Menlo,monospace;color:#7fd6e1;font-size:11.5px}}
  .bar{{height:12px;border-radius:3px;margin:6px 0 4px;
    background:linear-gradient(90deg,
      rgb(5,48,97),rgb(33,102,172),rgb(103,169,207),rgb(209,229,240),
      rgb(247,247,247),rgb(253,219,199),rgb(239,138,98),rgb(178,24,43),rgb(103,0,31))}}
  .ticks{{display:flex;justify-content:space-between;font-family:ui-monospace,Menlo,monospace;font-size:10.5px;color:#93a6b7}}
  #ctl{{position:absolute;top:12px;left:12px;z-index:1000;width:262px}}
  #leg{{position:absolute;bottom:12px;right:12px;z-index:1000;width:220px}}
  #ts{{position:absolute;bottom:12px;left:12px;z-index:1000;width:468px;max-width:calc(100vw - 24px)}}
  #tsc{{width:100%;height:210px;display:block;cursor:crosshair}}
  .tip{{position:absolute;pointer-events:none;background:#0c141d;border:1px solid #3fb9c9;border-radius:6px;
    padding:4px 7px;font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#e7eef5;opacity:0;transition:opacity .08s;white-space:nowrap;z-index:1100}}
</style></head>
<body>
<div id="map"></div>

<div id="ctl" class="panel">
  <h3>DSC LOS — tropo-corrected (ERA5+detrend)</h3>
  <div class="sub">Sentinel-1 descending · 2019–2026<br>{m['n_land']:,} land px ({m['pct']}%) · water removed<br>AOI 38.156–38.341N, 72.516–72.717E</div>
  <label class="toggle"><input type="checkbox" id="onoff" checked> Show velocity layer</label>
  <div class="row"><label>Opacity</label><input type="range" id="op" min="0" max="100" value="80"><span class="val" id="opv">80%</span></div>
  <div class="row"><label>Min</label><input type="number" id="vmin" step="1" value="{VMIN0}"><span class="val">mm/yr</span></div>
  <div class="row"><label>Max</label><input type="number" id="vmax" step="1" value="{VMAX0}"><span class="val">mm/yr</span></div>
  <label class="toggle"><input type="checkbox" id="sym" checked> 0 중심 대칭 (Max = −Min)</label>
  <div class="row"><button id="apply">적용</button><button id="reset">기본값 (±{VMAX0:g})</button></div>
  <div class="sub" style="margin:8px 0 0">데이터 범위(1–99%): {VDMIN:g} ~ {VDMAX:g} mm/yr</div>
</div>

<div id="leg" class="panel">
  <h3 style="margin-bottom:4px">LOS velocity (mm/yr)</h3>
  <div class="bar"></div>
  <div class="ticks"><span id="t0">-{VMAX0:g}</span><span id="tm">0</span><span id="t1">+{VMAX0:g}</span></div>
  <div class="sub" style="margin:6px 0 0">blue = away/subsidence · red = toward/uplift<br>water bodies masked (DEM flatness)</div>
</div>

<div id="ts" class="panel">
  <h3 style="margin-bottom:2px">Displacement time series</h3>
  <div class="sub" style="margin-bottom:6px">@ {PLAT:.4f}N, {PLON:.4f}E · coh {m['point_tcoh']} · rate <b style="color:#7fd6e1">{m['fit_vel']:+.1f} mm/yr</b> · RMSE {m['fit_rmse']} mm</div>
  <canvas id="tsc"></canvas>
</div>
<div class="tip" id="tip"></div>

<script>
  var SNX={SNX}, SNY={SNY}, LUT={LUT};
  var VMIN0={VMIN0}, VMAX0={VMAX0};
  // ---- decode raw float32 velocity field (little-endian) ----
  function b64ToF32(b){{var s=atob(b),n=s.length,u=new Uint8Array(n);for(var i=0;i<n;i++)u[i]=s.charCodeAt(i);return new Float32Array(u.buffer);}}
  var FIELD=b64ToF32("{fb64}");
  var off=document.createElement('canvas'); off.width=SNX; off.height=SNY;
  var octx=off.getContext('2d'); var IMG=octx.createImageData(SNX,SNY);

  var map=L.map('map',{{zoomControl:true}});
  var esriImg=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{maxZoom:19,attribution:'Imagery &copy; Esri, Maxar'}}).addTo(map);
  var esriTopo=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}});
  var bounds=[[{S:.6f},{W:.6f}],[{N:.6f},{E:.6f}]];
  var dsc=L.imageOverlay('',bounds,{{opacity:0.80,interactive:false}}).addTo(map);
  L.control.layers({{'Esri Imagery':esriImg,'Esri Topographic':esriTopo}},{{'DSC velocity (land)':dsc}},{{position:'topright'}}).addTo(map);
  map.fitBounds(bounds);
  var pt=L.circleMarker([{PLAT},{PLON}],{{radius:7,color:'#ffd400',weight:2,fillColor:'#ffd400',fillOpacity:.6}})
    .addTo(map).bindPopup('<b>Time-series point</b><br>{PLAT:.4f}N, {PLON:.4f}E<br>rate {m['fit_vel']:+.1f} mm/yr');

  function render(vmin,vmax){{
    var d=IMG.data, span=(vmax-vmin)||1;
    for(var i=0,j=0;i<FIELD.length;i++,j+=4){{
      var v=FIELD[i];
      if(v!==v){{d[j+3]=0;continue;}}          // NaN = transparent
      var t=(v-vmin)/span; t=t<0?0:(t>1?1:t);
      var c=LUT[(t*255)|0];
      d[j]=c[0]; d[j+1]=c[1]; d[j+2]=c[2]; d[j+3]=255;
    }}
    octx.putImageData(IMG,0,0);
    dsc.setUrl(off.toDataURL('image/png'));
    // legend labels
    document.getElementById('t0').textContent=(vmin>0?'+':'')+(+vmin.toFixed(0));
    document.getElementById('tm').textContent=(+((vmin+vmax)/2).toFixed(0));
    document.getElementById('t1').textContent=(vmax>0?'+':'')+(+vmax.toFixed(0));
  }}
  function apply(){{
    var lo=parseFloat(document.getElementById('vmin').value);
    var hi=parseFloat(document.getElementById('vmax').value);
    if(!isFinite(lo)||!isFinite(hi)||hi<=lo) return;
    render(lo,hi);
  }}
  // symmetric coupling
  var vminEl=document.getElementById('vmin'), vmaxEl=document.getElementById('vmax'), symEl=document.getElementById('sym');
  vminEl.oninput=function(){{if(symEl.checked){{vmaxEl.value=(-parseFloat(vminEl.value)||0);}}apply();}};
  vmaxEl.oninput=function(){{if(symEl.checked){{vminEl.value=(-parseFloat(vmaxEl.value)||0);}}apply();}};
  symEl.onchange=function(){{if(symEl.checked){{vmaxEl.value=(-parseFloat(vminEl.value)||0);}}apply();}};
  document.getElementById('apply').onclick=apply;
  document.getElementById('reset').onclick=function(){{vminEl.value=VMIN0;vmaxEl.value=VMAX0;apply();}};

  document.getElementById('onoff').onchange=function(e){{e.target.checked?dsc.addTo(map):map.removeLayer(dsc);}};
  document.getElementById('op').oninput=function(e){{dsc.setOpacity(e.target.value/100);document.getElementById('opv').textContent=e.target.value+'%';}};

  render(VMIN0,VMAX0);  // initial

  // ---- time series chart (Canvas) ----
  var YR={ts}, DS={ds}, DT={dd};
  var cv=document.getElementById('tsc'), tip=document.getElementById('tip');
  function niceTicks(a,bb,k){{var s=(bb-a)/k,p=Math.pow(10,Math.floor(Math.log10(s))),n=s/p;
    n=n<1.5?1:n<3?2:n<7?5:10;s=n*p;var t=[],st=Math.ceil(a/s)*s;for(var v=st;v<=bb;v+=s)t.push(v);return t;}}
  function draw(){{
    var dpr=window.devicePixelRatio||1, W=cv.clientWidth, H=cv.clientHeight;
    cv.width=W*dpr; cv.height=H*dpr; var x=cv.getContext('2d'); x.scale(dpr,dpr);
    x.clearRect(0,0,W,H);
    var mL=46,mR=12,mT=10,mB=24, pw=W-mL-mR, ph=H-mT-mB;
    var x0=Math.min.apply(null,YR), x1=Math.max.apply(null,YR);
    var y0=Math.min.apply(null,DS), y1=Math.max.apply(null,DS); var pad=(y1-y0)*0.1||1; y0-=pad;y1+=pad;
    var X=function(v){{return mL+(v-x0)/(x1-x0)*pw;}}, Y=function(v){{return mT+(1-(v-y0)/(y1-y0))*ph;}};
    x.font='10px ui-monospace,Menlo,monospace'; x.textBaseline='middle';
    niceTicks(y0,y1,5).forEach(function(t){{var yy=Y(t); x.strokeStyle='rgba(147,166,183,.18)';x.beginPath();x.moveTo(mL,yy);x.lineTo(W-mR,yy);x.stroke();
      x.fillStyle='#93a6b7';x.textAlign='right';x.fillText(t.toFixed(0),mL-6,yy);}});
    x.textAlign='center';x.textBaseline='top';
    for(var yr=Math.ceil(x0);yr<=Math.floor(x1);yr++){{var xx=X(yr);x.strokeStyle='rgba(147,166,183,.12)';x.beginPath();x.moveTo(xx,mT);x.lineTo(xx,H-mB);x.stroke();x.fillStyle='#93a6b7';x.fillText(yr,xx,H-mB+5);}}
    if(y0<0&&y1>0){{x.strokeStyle='rgba(231,238,245,.4)';x.setLineDash([3,3]);x.beginPath();x.moveTo(mL,Y(0));x.lineTo(W-mR,Y(0));x.stroke();x.setLineDash([]);}}
    var n=YR.length,sx=0,sy=0,sxx=0,sxy=0;
    for(var i=0;i<n;i++){{sx+=YR[i];sy+=DS[i];sxx+=YR[i]*YR[i];sxy+=YR[i]*DS[i];}}
    var b=(n*sxy-sx*sy)/(n*sxx-sx*sx), aa=(sy-b*sx)/n;
    x.strokeStyle='#ff8a5c';x.lineWidth=2;x.beginPath();x.moveTo(X(x0),Y(aa+b*x0));x.lineTo(X(x1),Y(aa+b*x1));x.stroke();
    x.fillStyle='#3fb9c9';
    for(var i=0;i<n;i++){{x.beginPath();x.arc(X(YR[i]),Y(DS[i]),2.6,0,6.283);x.fill();}}
    x.fillStyle='#93a6b7';x.textAlign='left';x.textBaseline='top';x.fillText('mm',4,mT-2);
    cv._X=X;
  }}
  cv.addEventListener('mousemove',function(e){{
    var rc=cv.getBoundingClientRect(),mx=e.clientX-rc.left;
    var best=-1,bd=1e9;for(var i=0;i<YR.length;i++){{var d=Math.abs(cv._X(YR[i])-mx);if(d<bd){{bd=d;best=i;}}}}
    if(best>=0&&bd<14){{tip.style.opacity=1;tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY-10)+'px';
      tip.textContent=DT[best].slice(0,4)+'-'+DT[best].slice(4,6)+'-'+DT[best].slice(6,8)+'  '+DS[best].toFixed(1)+' mm';}}
    else tip.style.opacity=0;
  }});
  cv.addEventListener('mouseleave',function(){{tip.style.opacity=0;}});
  window.addEventListener('resize',draw); draw();
</script>
</body></html>'''
out=f'{D}/Usoi_DSC_corrected_webmap.html'
open(out,'w').write(HTML)
print("wrote",out,"(%.2f MB)"%(os.path.getsize(out)/1048576))
