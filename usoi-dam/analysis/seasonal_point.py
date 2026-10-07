#!/usr/bin/env python3
# Extract the seasonal cycle at the requested point: remove the linear trend, then
# (a) fit annual+semiannual sinusoids and report the peak month, and (b) stack the
# detrended residual by month across all years to show the mean seasonal shape.
import os
ROOT=os.environ.get('DATA_ROOT','<DATA_ROOT>')  # dir containing SBAS/ and sentinel1/
import json, numpy as np, datetime
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
m=json.load(open(ROOT+'/SBAS/DECOMP/dsc_corr_meta.json'))
t=np.array(m['ts']['year'],float); d=np.array(m['ts']['disp'],float)
dates=m['ts']['date']
mon=np.array([int(s[4:6]) for s in dates])
doy=np.array([datetime.datetime.strptime(s,'%Y%m%d').timetuple().tm_yday for s in dates])

# linear detrend
t0=t-t[0]; A=np.vstack([t0,np.ones_like(t0)]).T
c,*_=np.linalg.lstsq(A,d,rcond=None); vel=c[0]; r=d-A@c   # residual (mm), trend removed

# annual + semiannual fit on residual
w=2*np.pi
B=np.vstack([np.sin(w*t),np.cos(w*t),np.sin(2*w*t),np.cos(2*w*t),np.ones_like(t)]).T
k,*_=np.linalg.lstsq(B,r,rcond=None)
amp1=np.hypot(k[0],k[1]); amp2=np.hypot(k[2],k[3])
# peak day-of-year of the annual component: a*sin+b*cos = A*cos(wt-phi), phi=atan2(a,b)
phi=np.arctan2(k[0],k[1]); peak_frac=(phi/w)%1.0; peak_doy=peak_frac*365.25
peak_date=(datetime.date(2024,1,1)+datetime.timedelta(days=peak_frac*365.25))
tr=r-B@k
print("linear vel = %.1f mm/yr"%vel)
print("annual amplitude   = %.1f mm   peak ~ day %.0f (%s)"%(amp1,peak_doy,peak_date.strftime('%m-%d')))
print("semiannual amplitude = %.1f mm"%amp2)
print("RMSE  linear-only=%.2f  linear+seasonal=%.2f mm"%(np.sqrt(np.mean(r**2)),np.sqrt(np.mean(tr**2))))

# monthly stack of residual
mm=np.arange(1,13); mean=[]; sd=[]; nn=[]
for M in mm:
    x=r[mon==M]; mean.append(np.mean(x) if x.size else np.nan); sd.append(np.std(x) if x.size else 0); nn.append(x.size)
mean=np.array(mean); sd=np.array(sd)
print("\nmonth  n   mean_resid(mm)")
for M in mm: print("  %2d  %3d   %+6.1f"%(M,nn[M-1],mean[M-1]))

# ---- figure ----
fig,ax=plt.subplots(1,2,figsize=(12,4.2))
# smooth annual model over one year
tg=np.linspace(0,1,200); model=amp1*np.cos(w*tg-phi)
ax[0].scatter((t%1.0),r,s=14,c='#3a7',alpha=.5,label='detrended obs')
ax[0].plot(tg,model,'r-',lw=2,label='annual fit (%.1f mm)'%amp1)
ax[0].axhline(0,color='#888',lw=.8); ax[0].axvline(peak_frac,color='r',ls='--',lw=1)
ax[0].set_xlabel('fraction of year (0=Jan 1)'); ax[0].set_ylabel('residual after trend (mm)')
ax[0].set_title('Detrended residual folded into one year'); ax[0].legend(fontsize=9)
mlab=['J','F','M','A','M','J','J','A','S','O','N','D']
ax[0].set_xticks((np.arange(12)+0.5)/12); ax[0].set_xticklabels(mlab)
ax[1].bar(mm,mean,yerr=sd,color='#2a7fb8',alpha=.85,capsize=3)
ax[1].axhline(0,color='#888',lw=.8)
ax[1].set_xticks(mm); ax[1].set_xticklabels(mlab)
ax[1].set_xlabel('month'); ax[1].set_ylabel('mean residual (mm)')
ax[1].set_title('Mean seasonal cycle (residual stacked by month)')
plt.tight_layout(); plt.savefig(ROOT+'/SBAS/DECOMP/Usoi_point_seasonal.png',dpi=130)
print("\nwrote Usoi_point_seasonal.png")
