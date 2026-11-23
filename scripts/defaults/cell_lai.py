"""max_LAI for arbitrary Daymet 1 km cells from GLASS LAI 2016 (V60, MODIS, 500 m, 8-day).

The author's method (H. Yan, email of 18 Nov 2026):
  1. for each 8-day composite, average the four 500 m pixels sampled at +-250 m from the
     1 km cell centre. The offsets are in the GLASS (MODIS sinusoidal) projection: the cell
     centre's latitude and longitude are projected, then (x +- 250, y +- 250) picks the pixels.
     This reproduces his max_LAI exactly at 98% of his 72,406 cells; offsets in the Daymet
     projection agree at only 9%, because points 250 m from the centre lie near pixel edges;
  2. average the composites within each calendar month;
  3. max_LAI = the largest of the 12 monthly means.
Fill values (255) are skipped in both averages.

Which month an 8-day composite belongs to is not stated. Three readings are written:
  lai_start  composite in the month of its first day (the default, `lai`)
  lai_mid    composite in the month of its middle day (first day + 3.5 days)
  lai_days   each composite weighted by its days in each month
The per-composite cell means are saved too (<out_csv>.composites.npz) for checking.

Usage: cell_lai.py <glass_dir> <cells_csv (latitude, longitude)> <out_csv>
"""
import datetime as dt
import glob
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

YEAR = 2016
SUBDATASET = 'HDF4_EOS:EOS_GRID:"{}":GLASS01E01:LAI_500M'

glass_dir, cells_csv, out_csv = sys.argv[1:4]
cells = pd.read_csv(cells_csv)
n = len(cells)
OFFSET_X = np.array([-250, 250, -250, 250])
OFFSET_Y = np.array([-250, -250, 250, 250])

files = sorted(glob.glob(f"{glass_dir}/GLASS01E01.V60.A{YEAR}*.hdf"))
by_tile = defaultdict(list)
for f in files:
    m = re.search(rf"\.A{YEAR}(\d{{3}})\.(h\d\dv\d\d)\.", f)
    by_tile[m[2]].append((int(m[1]), f))
doys = sorted({d for v in by_tile.values() for d, _ in v})
S = np.zeros((len(doys), n))
C = np.zeros((len(doys), n))
found = np.zeros((n, 4), bool)
for tile, items in sorted(by_tile.items()):
    items.sort()
    with rasterio.open(SUBDATASET.format(items[0][1])) as src:
        tr, crs, H, W = src.transform, src.crs, src.height, src.width
    # cell centres (the cells' latitude, longitude) in the tile's projection, then the four points
    sx, sy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(cells.longitude.values,
                                                                              cells.latitude.values)
    sx, sy = (sx[:, None] + OFFSET_X).ravel(), (sy[:, None] + OFFSET_Y).ravel()
    col, row = ~tr * (sx, sy)
    col, row = np.floor(col).astype(np.int64), np.floor(row).astype(np.int64)
    inside = np.isfinite(sx) & (col >= 0) & (col < W) & (row >= 0) & (row < H)
    inside &= ~found.ravel()  # a point on a tile edge is taken from the first tile only
    if not inside.any():
        continue
    found.ravel()[inside] = True
    pts = np.flatnonzero(inside)
    cid = pts // 4
    flat = row[pts] * W + col[pts]
    print(tile, "sample points:", len(pts), "cells:", len(np.unique(cid)), flush=True)
    for doy, f in items:
        with rasterio.open(SUBDATASET.format(f)) as src:
            a = src.read(1).ravel()[flat].astype(np.float64)
        good = a != 255
        t = doys.index(doy)
        S[t] += np.bincount(cid[good], a[good] * 0.1, minlength=n)
        C[t] += np.bincount(cid[good], minlength=n)
with np.errstate(invalid="ignore", divide="ignore"):
    comp = np.where(C > 0, S / C, np.nan)  # (composite, cell)

# month membership of each composite, (composite, 12) weights
start = [dt.date(YEAR, 1, 1) + dt.timedelta(days=d - 1) for d in doys]
end_of_year = dt.date(YEAR, 12, 31)
w_start = np.zeros((len(doys), 12))
w_mid = np.zeros((len(doys), 12))
w_days = np.zeros((len(doys), 12))
for t, s in enumerate(start):
    w_start[t, s.month - 1] = 1
    w_mid[t, (s + dt.timedelta(days=3.5)).month - 1] = 1  # 3.5 days on: the middle of 8 days
    for k in range(8):
        day = s + dt.timedelta(days=k)
        if day <= end_of_year:
            w_days[t, day.month - 1] += 1


def max_monthly(w):
    ok = np.isfinite(comp)
    num = w.T @ np.where(ok, comp, 0.0)  # (12, cell)
    den = w.T @ ok.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        monthly = np.where(den > 0, num / den, np.nan)
    out = np.full(n, np.nan)
    has = np.isfinite(monthly).any(axis=0)
    out[has] = np.nanmax(monthly[:, has], axis=0)
    return out


out = cells[["latitude", "longitude"]].copy()
out["lai_start"] = max_monthly(w_start)
out["lai_mid"] = max_monthly(w_mid)
out["lai_days"] = max_monthly(w_days)
out["lai"] = out.lai_start
out["sample_points_found"] = found.sum(axis=1)
out["composites_with_data"] = np.isfinite(comp).sum(axis=0)
out.to_csv(out_csv, index=False)
np.savez_compressed(f"{out_csv}.composites.npz", doy=np.array(doys), lai=comp.astype(np.float32),
                    lat=cells.latitude.values, lon=cells.longitude.values)
print("cells with LAI:", int(np.isfinite(out.lai).sum()), "of", n)
