"""궤도별 지점 입사각: sentinel-1-grd annotation(schema-product-vv) geolocationGrid 보간."""
import json, numpy as np, requests, pystac_client, planetary_computer as pc, xml.etree.ElementTree as ET
from scipy.interpolate import griddata
SITES = {"CHIMN": (51.7080, -1.4788), "SHEEP": (51.5303, -1.4819), "WADDN": (51.8395, -0.9484)}
cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
out = {}
for orb in (30, 132):
    for s, (la, lo) in SITES.items():
        its = list(cat.search(collections=["sentinel-1-grd"], intersects={"type": "Point", "coordinates": [lo, la]},
                              datetime="2018-01-01/2018-12-31", query={"sat:relative_orbit": {"eq": orb}, "sat:orbit_state": {"eq": "ascending"}}, max_items=2).items())
        if not its: continue
        x = ET.fromstring(requests.get(its[0].assets["schema-product-vv"].href).content)
        pts = [(float(p.find("latitude").text), float(p.find("longitude").text), float(p.find("incidenceAngle").text))
               for p in x.iter("geolocationGridPoint")]
        P = np.array(pts); th = float(griddata(P[:, :2], P[:, 2], [(la, lo)], method="linear")[0])
        out.setdefault(s, {})[str(orb)] = th; print(orb, s, its[0].id, round(th, 2), flush=True)
json.dump(out, open("<WORK_ROOT>/case_UK_Maslanka2022/data/incidence_angles.json", "w"), indent=1)
