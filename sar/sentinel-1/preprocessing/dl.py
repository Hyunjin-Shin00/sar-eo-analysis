import os, sys, json, netrc, time
os.environ.pop('PYTHONPATH', None)
import asf_search as asf

ROOT=os.path.join(os.environ.get('DATA_ROOT', '<DATA_ROOT>'), 'SLC')
WANT={  # path -> (dir, burstIDs, dates)
 85:('ASC_085', {'085_180588_IW2','085_180589_IW2','085_180590_IW2'}, {'2026-08-04','2026-08-16','2026-08-28'}),
 19:('DSC_019', {'019_039570_IW1','019_039571_IW1','019_039572_IW1','019_039573_IW1'}, {'2026-08-12','2026-08-24'}),
 121:('DSC_121',{'121_258660_IW3'}, {'2026-08-07','2026-08-19'}),
}
rows=json.load(open('bursts_all.json'))
sel={p:[] for p in WANT}
for r in rows:
    p=r['path']
    if p not in WANT: continue
    _,bids,dates=WANT[p]
    if r['fullBurstID'] in bids and r['date'] in dates:
        sel[p].append(r)

tot=0
for p,(d,_,_) in WANT.items():
    n=len(sel[p]); sz=sum(float(x['size']) if str(x['size']).replace('.','',1).isdigit() else 0 for x in sel[p]); tot+=sz
    print(f"path{p:>4} -> {d}: {n}개, {sz/1e9:.2f} GB")
print(f"합계 {tot/1e9:.2f} GB\n")
if '--dry' in sys.argv: sys.exit()

n=netrc.netrc(os.path.expanduser('~/.netrc'))
login,_,pw = n.authenticators('urs.earthdata.nasa.gov')
sess = asf.ASFSession().auth_with_creds(login, pw)
print("auth OK", flush=True)

for p,(d,_,_) in WANT.items():
    outdir=os.path.join(ROOT,d); os.makedirs(outdir, exist_ok=True)
    todo=[x for x in sel[p] if not os.path.exists(os.path.join(outdir, x['name']+'.zip'))]
    print(f"\n[path{p}] {len(todo)}/{len(sel[p])} 다운로드 -> {outdir}", flush=True)
    for i,x in enumerate(todo,1):
        t0=time.time()
        asf.download_url(url=x['url'], path=outdir, filename=x['name']+'.zip', session=sess)
        fp=os.path.join(outdir,x['name']+'.zip')
        print(f"  [{i}/{len(todo)}] {x['name']}  {os.path.getsize(fp)/1e6:.1f}MB  {time.time()-t0:.1f}s", flush=True)
print("\nDONE")
