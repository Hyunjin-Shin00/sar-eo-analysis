import os
import warnings; warnings.filterwarnings("ignore")
import numpy as np, rasterio, geopandas as gpd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
V=os.environ.get("DATA_ROOT", "<DATA_ROOT>")+"/"; lam=0.0554658
with rasterio.open(V+"Venezuela/left/subset_1_of_2026062320260624_Orb_Stack_Ifg_Deb_Flt_unw_TC.tif") as s:
    f=6; ph=s.read(1,out_shape=(s.height//f,s.width//f)); b=s.bounds
ph[(ph==0)|~np.isfinite(ph)]=np.nan; d=-ph*lam/(4*np.pi)*100
m=np.isfinite(d); yy,xx=np.mgrid[0:d.shape[0],0:d.shape[1]]
A=np.c_[xx[m],yy[m],np.ones(m.sum())]; c,*_=np.linalg.lstsq(A,d[m],rcond=None); dd=np.full(d.shape,np.nan); dd[m]=d[m]-A@c
print("deramped p2/p98",np.nanpercentile(dd,[2,98]))
ep=gpd.read_file(V+"epicenters/epicenters_2026.shp").to_crs(4326); print(ep.drop(columns="geometry").to_string()[:800])
fig,ax=plt.subplots(figsize=(7,10),facecolor="#fcfcfb"); ax.set_facecolor("#e6e6e3")
im=ax.imshow(dd,extent=(b.left,b.right,b.bottom,b.top),cmap="RdBu_r",vmin=-25,vmax=25,interpolation="nearest")
try:
    fl=gpd.read_file(V+"fault/gem-global-active-faults/geojson/gem_active_faults_harmonized.geojson",bbox=(b.left,b.bottom,b.right,b.top)); fl.plot(ax=ax,color="#0b0b0b",lw=0.8)
except Exception as ex: print("fault skip",ex)
ax.scatter(ep.geometry.x,ep.geometry.y,marker="*",s=260,c="#eda100",edgecolors="#0b0b0b",zorder=5,label="M7.2 / M7.5 epicenters (2026-06-24)")
ax.set_xlim(b.left,b.right); ax.set_ylim(b.bottom,b.top)
cb=fig.colorbar(im,ax=ax,shrink=0.6,pad=0.02); cb.set_label("LOS displacement (cm), planar ramp removed")
ax.set_title("Sentinel-1 1-day pair 2026-06-23 → 06-24 (VH, unwrapped)\nsecond image acquired ~45 min after the mainshock",loc="left",fontsize=11)
ax.legend(loc="lower left",fontsize=9); ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
fig.tight_layout(); fig.savefig("left_dinsar.png",dpi=120,facecolor=fig.get_facecolor())
