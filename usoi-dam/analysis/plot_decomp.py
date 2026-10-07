#!/usr/bin/env python3
# Render ASC/DSC LOS + vertical/horizontal decomposition velocity maps to a PNG.
import os
ROOT=os.environ.get('DATA_ROOT','<DATA_ROOT>')  # dir containing SBAS/ and sentinel1/
import numpy as np, h5py
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

D=ROOT+'/SBAS/DECOMP'
def load(f):
    h=h5py.File(f,'r'); v=h['velocity'][:]*1000.0  # mm/yr
    a=h.attrs
    y0=float(a['Y_FIRST']); x0=float(a['X_FIRST']); dy=float(a['Y_STEP']); dx=float(a['X_STEP'])
    ny,nx=v.shape
    ext=[x0, x0+dx*nx, y0+dy*ny, y0]   # [W,E,S,N]
    v=np.where((v==0)|~np.isfinite(v), np.nan, v)
    return v, ext

panels=[('ASC LOS velocity','ASC_vel_geo.h5'),
        ('DSC LOS velocity','DSC_vel_geo.h5'),
        ('Vertical (Up +)','up.h5'),
        ('Horizontal (E–W, East +)','hz.h5')]

# robust symmetric color range from the decomposition products
allv=[]
for _,f in panels:
    v,_=load(f'{D}/{f}'); allv.append(v[np.isfinite(v)])
vmax=40.0  # clip to ±40 mm/yr so the deformation gradient is visible (noise saturates)
norm=TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)

fig,axes=plt.subplots(2,2,figsize=(13,11),constrained_layout=True)
DAM=(72.607,38.271)  # approx Usoi Dam / Lake Sarez outlet
for ax,(title,f) in zip(axes.ravel(),panels):
    v,ext=load(f'{D}/{f}')
    im=ax.imshow(v,extent=ext,origin='upper',cmap='RdBu_r',norm=norm,interpolation='nearest')
    ax.plot(*DAM,marker='v',ms=11,mfc='yellow',mec='k',mew=1.2,zorder=5)
    ax.annotate('Usoi Dam',DAM,textcoords='offset points',xytext=(8,4),fontsize=8,fontweight='bold')
    ax.set_title(title,fontsize=12,fontweight='bold')
    ax.set_xlabel('Longitude (°E)'); ax.set_ylabel('Latitude (°N)')
    ax.tick_params(labelsize=8)
    n=int(np.isfinite(v).sum())
    ax.text(0.02,0.02,f'{n:,} px',transform=ax.transAxes,fontsize=8,
            va='bottom',ha='left',bbox=dict(fc='white',alpha=0.7,lw=0))
cb=fig.colorbar(im,ax=axes,shrink=0.85,extend='both',location='right',pad=0.02)
cb.set_label('LOS / displacement velocity (mm/yr)  —  blue = subsidence/away, red = uplift/toward/east',fontsize=10)
fig.suptitle('Usoi Dam (Lake Sarez, Pamir) — Sentinel-1 SBAS 2019–2026\nASC+DSC LOS and vertical/horizontal decomposition  (masked to temporal coherence > 0.3)',
             fontsize=13,fontweight='bold')
out=f'{D}/Usoi_decomposition_maps.png'
fig.savefig(out,dpi=135,bbox_inches='tight')
print('wrote',out,'vmax=±%g mm/yr'%vmax)
