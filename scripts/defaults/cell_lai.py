"""max_LAI for arbitrary Daymet 1 km cells from GLASS LAI 2016 (V60, 500 m, 8-day).

Rule L2 from infer_lai.py (best match to the author's table, r = 0.968, +0.10 bias):
for each 8-day date, average the 500 m pixels whose centres fall in the 1 km cell,
then take the annual maximum. Cells can straddle MODIS tiles, so per-date sums and
counts are accumulated over all tiles before averaging.

Usage: cell_lai.py <glass_dir> <cells_csv (latitude, longitude)> <out_csv>
"""
import glob
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

DAYMET_LCC = ("+proj=lcc +lat_1=25 +lat_2=60 +lat_0=42.5 +lon_0=-100 "
              "+x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs")

glass_dir, cells_csv, out_csv = sys.argv[1:4]
cells = pd.read_csv(cells_csv)
n = len(cells)
ll2lcc = Transformer.from_crs("EPSG:4326", DAYMET_LCC, always_xy=True)
cx, cy = ll2lcc.transform(cells.longitude.values, cells.latitude.values)
cx = np.round((cx - 750) / 1000) * 1000 + 750
cy = np.round(cy / 1000) * 1000
lookup = {(int(x), int(y)): k for k, (x, y) in enumerate(zip(cx, cy))}

files = sorted(glob.glob(f"{glass_dir}/GLASS01E01.V60.A2016*.hdf"))
by_tile = defaultdict(list)
for f in files:
    m = re.search(r"\.A2016(\d{3})\.(h\d\dv\d\d)\.", f)
    by_tile[m[2]].append((int(m[1]), f))
doys = sorted({d for v in by_tile.values() for d, _ in v})
S = np.zeros((len(doys), n))
C = np.zeros((len(doys), n))
for tile, items in sorted(by_tile.items()):
    items.sort()
    with rasterio.open(f'HDF4_EOS:EOS_GRID:"{items[0][1]}":GLASS01E01:LAI_500M') as src:
        tr, crs, H, W = src.transform, src.crs, src.height, src.width
    rr, cc = np.meshgrid(np.arange(H) + 0.5, np.arange(W) + 0.5, indexing="ij")
    px, py = tr * (cc.ravel(), rr.ravel())
    lx, ly = Transformer.from_crs(crs, DAYMET_LCC, always_xy=True).transform(px, py)
    ok = np.isfinite(lx) & np.isfinite(ly)
    # centre of the 1 km cell containing each pixel centre
    gx = np.floor((lx[ok] - 250) / 1000) * 1000 + 750
    gy = np.round(ly[ok] / 1000) * 1000
    idx = np.flatnonzero(ok)
    cid = np.array([lookup.get((int(a), int(b)), -1) for a, b in zip(gx, gy)])
    keep, c = idx[cid >= 0], cid[cid >= 0]
    print(tile, "pixels in target cells:", len(keep), "cells:", len(np.unique(c)), flush=True)
    if len(keep) == 0:
        continue
    for doy, f in items:
        with rasterio.open(f'HDF4_EOS:EOS_GRID:"{f}":GLASS01E01:LAI_500M') as src:
            a = src.read(1).ravel()[keep].astype(np.float64)
        good = a != 255
        t = doys.index(doy)
        S[t] += np.bincount(c[good], a[good] * 0.1, minlength=n)
        C[t] += np.bincount(c[good], minlength=n)
with np.errstate(invalid="ignore", divide="ignore"):
    mean = np.where(C > 0, S / C, np.nan)
lai = np.nanmax(np.where(np.isnan(mean), -np.inf, mean), axis=0)
lai[np.isinf(lai)] = np.nan
out = cells[["latitude", "longitude"]].copy()
out["lai_L2"] = lai
out["n_pixels_max"] = C.max(axis=0).astype(int)
out.to_csv(out_csv, index=False)
print("cells with LAI:", int(np.isfinite(lai).sum()), "of", n)
