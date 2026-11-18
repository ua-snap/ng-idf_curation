"""Per-cell version of zonal_counts.py for scattered cells (e.g. the Phase 1 places).

Counts raster values whose pixel centres fall inside each Daymet 1 km cell, reading
a small window per cell. Same pixel-assignment rule as zonal_counts.py.
Cells outside the raster get zero counts.

Usage: cell_counts.py <raster> <cells_csv (latitude, longitude)> <out_npz>
"""
import sys

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.windows import Window, from_bounds

DAYMET_LCC = ("+proj=lcc +lat_1=25 +lat_2=60 +lat_0=42.5 +lon_0=-100 "
              "+x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs")

raster, cells_csv, out_npz = sys.argv[1:4]
cells = pd.read_csv(cells_csv)
ll2lcc = Transformer.from_crs("EPSG:4326", DAYMET_LCC, always_xy=True)
cx, cy = ll2lcc.transform(cells.longitude.values, cells.latitude.values)
cx = np.round((cx - 750) / 1000) * 1000 + 750
cy = np.round(cy / 1000) * 1000
acc = {}
with rasterio.open(raster) as src:
    lcc2src = Transformer.from_crs(DAYMET_LCC, src.crs, always_xy=True)
    src2lcc = Transformer.from_crs(src.crs, DAYMET_LCC, always_xy=True)
    full = Window(0, 0, src.width, src.height)
    pad = 3 * abs(src.res[0])
    for k, (x, y) in enumerate(zip(cx, cy)):
        bx = np.array([x - 500, x + 500, x + 500, x - 500])
        by = np.array([y - 500, y - 500, y + 500, y + 500])
        sx, sy = lcc2src.transform(bx, by)
        if not (np.isfinite(sx).all() and np.isfinite(sy).all()):
            continue
        try:
            win = from_bounds(sx.min() - pad, sy.min() - pad, sx.max() + pad, sy.max() + pad, src.transform)
            win = win.round_offsets().round_lengths().intersection(full)
        except rasterio.errors.WindowError:
            continue
        if win.width <= 0 or win.height <= 0:
            continue
        arr = src.read(1, window=win)
        wt = src.window_transform(win)
        rr, cc = np.meshgrid(np.arange(arr.shape[0]) + 0.5, np.arange(arr.shape[1]) + 0.5, indexing="ij")
        px, py = wt * (cc.ravel(), rr.ravel())
        lx, ly = src2lcc.transform(px, py)
        inside = (lx >= x - 500) & (lx < x + 500) & (ly >= y - 500) & (ly < y + 500)
        vals, n = np.unique(arr.ravel()[inside].astype(np.int64), return_counts=True)
        for v, c in zip(vals, n):
            acc.setdefault(int(v), np.zeros(len(cells), np.int64))[k] += c
values = np.array(sorted(acc))
counts = np.stack([acc[v] for v in values], axis=1) if len(values) else np.zeros((len(cells), 0), np.int64)
np.savez_compressed(out_npz, lat=cells.latitude.values, lon=cells.longitude.values, values=values, counts=counts)
print(raster, "cells with zero pixels:", int((counts.sum(1) == 0).sum()), "median pixels/cell:", np.median(counts.sum(1)))
