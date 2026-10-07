import os, json
os.environ.pop('PYTHONPATH', None)
import asf_search as asf
from shapely.geometry import shape, Point

PTS = {
 'SRC(붕괴원점)': Point(85.5194, 28.2765),
 'Rasuwagadhi':   Point(85.3792, 28.2810),
 'Syabrubesi':    Point(85.3336, 28.1622),
 'Dhunche':       Point(85.2971, 28.1004),
 'Betrawati':     Point(85.1836, 27.9704),
 'Bidur/Devighat':Point(85.1500, 27.8700),
}
wkt = "POLYGON((85.05 27.80, 85.60 27.80, 85.60 28.45, 85.05 28.45, 85.05 27.80))"
r = asf.search(intersectsWith=wkt, dataset='SLC-BURST', start='2026-08-01', end='2026-09-01', maxResults=3000)
rows=[]
for p in r:
    pr=p.properties; g=shape(p.geometry)
    b=pr.get('burst',{})
    cov=[n for n,pt in PTS.items() if g.contains(pt)]
    rows.append(dict(date=pr['startTime'][:10], t=pr['startTime'][11:19], dirn=pr['flightDirection'][:4],
                     path=pr['pathNumber'], subswath=b.get('subswath'), fullBurstID=b.get('fullBurstID'),
                     pol=pr.get('polarization'), name=pr['sceneName'], url=pr['url'],
                     size=pr.get('bytes'), cov=cov))
rows.sort(key=lambda x:(x['path'],x['date'],str(x['subswath']),x['name']))
print(f"총 {len(rows)} 버스트\n")
for path in sorted({x['path'] for x in rows}):
    sub=[x for x in rows if x['path']==path]
    print(f"===== path {path} ({sub[0]['dirn']}) =====")
    ids=sorted({x['fullBurstID'] for x in sub if x['cov']})
    print(f"  대상지점 포함 burstID: {ids}")
    for d in sorted({x['date'] for x in sub}):
        dd=[x for x in sub if x['date']==d and x['cov']]
        print(f"   {d}: 관련버스트 {len(dd)}건 (VV+VH), 지점={sorted({c for x in dd for c in x['cov']})}")
    print()
json.dump(rows, open('bursts_all.json','w'), ensure_ascii=False, indent=1)
print("saved -> bursts_all.json")
