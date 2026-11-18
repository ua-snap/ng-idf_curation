"""Fetch Daymet v4 (R1) daily series for each Phase 1 Daymet 1 km cell from the ORNL
single-pixel API (only cell-centre coordinates are sent). Resumable; one request at a time.

Usage: fetch_daymet_pixels.py <places_csv> <out_dir> [start_year end_year]
"""
import sys, time, urllib.request, urllib.error
from pathlib import Path
import pandas as pd

places, out = Path(sys.argv[1]), Path(sys.argv[2])
y0, y1 = (sys.argv[3], sys.argv[4]) if len(sys.argv) > 4 else ('1989', '2021')
out.mkdir(parents=True, exist_ok=True)
keys = pd.read_csv(places, dtype={'daymet_key': str}).daymet_key.dropna().unique()
URL = ('https://daymet.ornl.gov/single-pixel/api/data?lat={lat}&lon={lon}'
       '&vars=dayl,prcp,srad,swe,tmax,tmin,vp&start={y0}-01-01&end={y1}-12-31')
fails = []
for i, k in enumerate(sorted(keys)):
    f = out / f'pix_{k}.csv'
    if f.exists() and f.stat().st_size > 100000:
        continue
    lat, lon = k.split('_')
    req = urllib.request.Request(URL.format(lat=lat, lon=lon, y0=y0, y1=y1), headers={'User-Agent': 'ngidf-curation'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
            tmp = f.with_suffix('.part'); tmp.write_bytes(body); tmp.replace(f)
            break
        except urllib.error.HTTPError as e:
            msg = e.read()[:200]
            if e.code in (400, 404):
                (out / f'pix_{k}.error').write_bytes(msg); fails.append(k); break
            time.sleep(10 * (attempt + 1))
        except Exception:
            time.sleep(10 * (attempt + 1))
    else:
        fails.append(k)
    print(i, k, 'ok' if f.exists() else 'FAILED', flush=True)
    time.sleep(1)
print('failed:', fails)
