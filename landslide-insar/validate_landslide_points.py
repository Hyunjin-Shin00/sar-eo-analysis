"""Landslide-point validation of PyGMTSAR velocity maps (Gyeongju).

1) Extract mapped landslide locations (red markers) from a georeferenced map raster.
2) Sample SBAS / PS LOS velocity (3x3 mean) at each point for every processing window.
3) Compare against all valid pixels inside the points' bounding box (Mann-Whitney U).
Note: background includes nodata=0 pixels if the raster has no nodata tag; exclude them explicitly when needed.
"""
import os
import numpy as np, rasterio
DATA_ROOT=os.environ.get('DATA_ROOT','<DATA_ROOT>')
from rasterio.windows import from_bounds
from scipy import ndimage
r=rasterio.open(os.path.join(DATA_ROOT,'landslide_BK','landslide_points_map.tif')); a=r.read().astype(int)
red=(a[0]>170)&(a[1]<90)&(a[2]<90)
lab,n=ndimage.label(red); sizes=ndimage.sum(red,lab,range(1,n+1))
keep=[i+1 for i,s in enumerate(sizes) if s>=4]
cent=ndimage.center_of_mass(red,lab,keep)
pts=[r.xy(cy,cx) for cy,cx in cent]
print('red components',n,'kept(>=4px)',len(pts))
np.savetxt('ls_points_lonlat.csv',np.array(pts),delimiter=',',fmt='%.6f',header='lon,lat')
lons=np.array([p[0] for p in pts]); lats=np.array([p[1] for p in pts])
bb=(lons.min()-0.01,lats.min()-0.01,lons.max()+0.01,lats.max()+0.01)
rng=np.random.default_rng(0)
def sample(path,band=1,label=''):
    with rasterio.open(path) as s:
        arr=s.read(band).astype('f8')
        if s.nodata is not None: arr[arr==s.nodata]=np.nan
        vals=[]
        for lo,la in zip(lons,lats):
            row,col=s.index(lo,la)
            w=arr[max(row-1,0):row+2,max(col-1,0):col+2]
            vals.append(np.nanmean(w) if np.isfinite(w).any() else np.nan)
        vals=np.array(vals)
        # background: all valid pixels inside bbox of points
        r0,c0=s.index(bb[0],bb[1]); r1,c1=s.index(bb[2],bb[3])
        sub=arr[min(r0,r1):max(r0,r1),min(c0,c1):max(c0,c1)]; bg=sub[np.isfinite(sub)]
    f=vals[np.isfinite(vals)]
    from scipy.stats import mannwhitneyu
    p=mannwhitneyu(f,bg).pvalue if f.size>3 else np.nan
    print(f'{label:38s} pts valid {f.size}/{len(vals)}  pts median {np.median(f):7.2f} mean {f.mean():7.2f} | bg median {np.median(bg):7.2f} std {bg.std():6.2f} | |pts|>2σbg {np.mean(np.abs(f-np.median(bg))>2*bg.std())*100:4.1f}%  MWU p={p:.3g}')
L=os.path.join(DATA_ROOT,'landslide')
for d,lab in [('Gyeongju4','G4 pre-typhoon 2022.01-08 (17)'),('Gyeongju6','G6 post 2022.08-2023.03 (17)'),('Gyeongju5','G5 post 2022.08-2023.12 (29)'),('Gyeongju3','G3 2022-2023 (46)'),('Gyeongju7','G7 post 2022.09-2024.12 (52)')]:
    sample(f'{L}/{d}/output/velocity_sbas_los_mm_per_year.tif',1,lab+' SBAS')
    sample(f'{L}/{d}/output/velocity_ps_los_mm_per_year.tif',1,lab+' PS')
B=os.path.join(DATA_ROOT,'landslide_BK')
sample(f'{B}/20220828_20220909_displacement.tif',1,'disp 0828-0909 b1')
sample(f'{B}/20220828_20220909_displacement.tif',2,'disp 0828-0909 b2')
