"""Which Daymet v4 1 km cells are land (have data)?

The author's defaults table and Daymet station files cover exactly the Daymet land
cells, so the app's nearest-cell searches only ever see land cells. We test a cell by
asking the ORNL single-pixel API for one day of tmax at the cell centre (only the
coordinates are sent). Results are cached in a JSON file; cells we already downloaded
(raw/daymet_v4_pixels/pix_<key>.csv) count as land.
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = ('https://daymet.ornl.gov/single-pixel/api/data?lat={lat}&lon={lon}'
       '&vars=tmax&start=2016-07-01&end=2016-07-01')


class LandChecker:
    def __init__(self, cache_path, pixel_dir=None, online=True):
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        self.online = online
        if pixel_dir:
            for f in Path(pixel_dir).glob('pix_*.csv'):
                if f.stat().st_size > 100000:
                    self.cache.setdefault(f.stem[4:], True)
        self.queries = 0

    def __call__(self, key):
        if key in self.cache:
            return self.cache[key]
        if not self.online:
            raise KeyError(f'land status unknown (offline): {key}')
        lat, lon = key.split('_')
        req = urllib.request.Request(URL.format(lat=lat, lon=lon), headers={'User-Agent': 'ngidf-curation'})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read().decode()
                land = 'tmax' in body and '2016' in body
                break
            except urllib.error.HTTPError as e:
                if e.code in (400, 404):
                    land = False
                    break
                time.sleep(5 * (attempt + 1))
            except Exception:
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f'Daymet API unreachable for {key}')
        self.cache[key] = land
        self.queries += 1
        time.sleep(0.5)
        return land

    def save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=0, sort_keys=True) + '\n')
