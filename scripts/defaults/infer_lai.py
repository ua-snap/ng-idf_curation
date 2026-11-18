"""Infer how max_LAI in gridcell_current_lulc.csv was derived from GLASS LAI
2016 (V60, 500 m, 8-day, MODIS sinusoidal tiles).

Candidate rules tested against the table:
  L1 per-pixel annual max, then mean of 500 m pixels whose centres fall in the 1 km cell
  L2 per-date cell mean, then annual max
  L3 annual max of the 500 m pixel nearest the cell centre
  L4 per-pixel annual max, then max over pixels in the cell
"""
import glob
import sys

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

DAYMET_LCC = ("+proj=lcc +lat_1=25 +lat_2=60 +lat_0=42.5 +lon_0=-100 "
              "+x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs")
glass_dir, cells_csv, tile = sys.argv[1], sys.argv[2], sys.argv[3]
cells = pd.read_csv(cells_csv)
target = cells.max_LAI.values

files = sorted(glob.glob(f"{glass_dir}/GLASS01E01.V60.A2016*.{tile}.*.hdf"))
print(len(files), "dates for", tile)
stack = []
for f in files:
    with rasterio.open(f'HDF4_EOS:EOS_GRID:"{f}":GLASS01E01:LAI_500M') as src:
        a = src.read(1).astype(np.float32)
        tr, crs = src.transform, src.crs
    a[a == 255] = np.nan
    stack.append(a * 0.1)
stack = np.stack(stack)  # (date, row, col)
H, W = stack.shape[1:]
rr, cc = np.meshgrid(np.arange(H) + 0.5, np.arange(W) + 0.5, indexing="ij")
px, py = tr * (cc.ravel(), rr.ravel())
to_lcc = Transformer.from_crs(crs, DAYMET_LCC, always_xy=True)
lx, ly = to_lcc.transform(px, py)

ll2lcc = Transformer.from_crs("EPSG:4326", DAYMET_LCC, always_xy=True)
cx, cy = ll2lcc.transform(cells.longitude.values, cells.latitude.values)
cx = np.round((cx - 750) / 1000) * 1000 + 750
cy = np.round(cy / 1000) * 1000
x0, y1 = cx.min() - 500, cy.max() + 500
nx = int(round((cx.max() - cx.min()) / 1000)) + 1
ny = int(round((cy.max() - cy.min()) / 1000)) + 1
grid = np.full(nx * ny, -1, np.int64)
grid[(((y1 - cy - 500) / 1000).round().astype(int)) * nx + ((cx - x0 - 500) / 1000).round().astype(int)] = np.arange(len(cells))
j = np.floor((lx - x0) / 1000).astype(np.int64)
i = np.floor((y1 - ly) / 1000).astype(np.int64)
ok = (i >= 0) & (i < ny) & (j >= 0) & (j < nx)
cid = np.full(ok.shape, -1, np.int64)
cid[ok] = grid[i[ok] * nx + j[ok]]
keep = np.where(cid >= 0)[0]
c = cid[keep]
n = len(cells)
print("cells with >=1 pixel:", len(np.unique(c)), "of", n)

flat = stack.reshape(stack.shape[0], -1)[:, keep]          # (date, kept px)
pix_max = np.nanmax(flat, axis=0)


def cell_mean(v):
    good = ~np.isnan(v)
    s = np.bincount(c[good], v[good], minlength=n)
    k = np.bincount(c[good], minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(k > 0, s / k, np.nan)


L1 = cell_mean(pix_max)
L2 = np.nanmax(np.stack([cell_mean(flat[t]) for t in range(flat.shape[0])]), axis=0)
L4 = np.full(n, -np.inf)
np.maximum.at(L4, c, np.nan_to_num(pix_max, nan=-np.inf))
L4[np.isinf(L4)] = np.nan
# nearest pixel to cell centre
from scipy.spatial import cKDTree
t = cKDTree(np.c_[lx[keep], ly[keep]])
_, nn = t.query(np.c_[cx, cy])
L3 = pix_max[nn]

for name, est in [("L1 pixmax->cellmean", L1), ("L2 cellmean->max", L2),
                  ("L3 nearest pixel max", L3), ("L4 pixmax->cellmax", L4)]:
    m = ~np.isnan(est)
    err = np.abs(np.round(est[m], 2) - target[m])
    print(f"{name:24s} n={m.sum()} exact(2dp)={np.mean(err < 0.006):.3f} MAE={err.mean():.3f} "
          f"p99={np.percentile(err, 99):.3f}")

# ---- bias diagnostics
m = ~np.isnan(L2) & (target > 0)
print("bias (L2 - target): mean %.3f median %.3f; corr %.3f; slope/int %s" % (
    np.mean(L2[m] - target[m]), np.median(L2[m] - target[m]), np.corrcoef(L2[m], target[m])[0, 1],
    np.polyfit(L2[m], target[m], 1).round(3)))
z = target == 0
print("target==0 cells:", z.sum(), "labels:", pd.Series(cells.dominant_LULC[z]).value_counts().to_dict())
print("our L2 at target==0 quantiles:", np.nanpercentile(L2[z], [5, 50, 95]).round(2))
print("our pixel all-NaN (fill) share at target==0: %.3f" % np.mean(np.isnan(L2[z])))
