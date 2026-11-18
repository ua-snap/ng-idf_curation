"""Count categorical/integer raster values inside each 1 km Daymet cell of the
NG-IDF defaults table (static/gridcell_current_lulc.csv).

Used to reverse-engineer how the app author derived dominant_LULC (NLCD 2016)
and mean_height_m (LANDFIRE EVH) for each cell. Each source pixel is assigned
to the Daymet cell containing the pixel centre.

Output: .npz with cell lat/lon (CSV order), `values` (unique raster codes) and
`counts` [ncell, nvalues].
"""
import argparse

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds

DAYMET_LCC = ("+proj=lcc +lat_1=25 +lat_2=60 +lat_0=42.5 +lon_0=-100 "
              "+x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs")
CELL = 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raster")
    ap.add_argument("cells_csv")
    ap.add_argument("out_npz")
    ap.add_argument("--block-rows", type=int, default=512)
    a = ap.parse_args()

    cells = pd.read_csv(a.cells_csv)
    to_lcc = Transformer.from_crs("EPSG:4326", DAYMET_LCC, always_xy=True)
    cx, cy = to_lcc.transform(cells.longitude.values, cells.latitude.values)
    # snap to the exact Daymet lattice (x centres = 750 mod 1000, y = 0 mod 1000)
    cx = np.round((cx - 750) / CELL) * CELL + 750
    cy = np.round(cy / CELL) * CELL
    x0, y1 = cx.min() - CELL / 2, cy.max() + CELL / 2
    nx = int(round((cx.max() - cx.min()) / CELL)) + 1
    ny = int(round((cy.max() - cy.min()) / CELL)) + 1
    grid_id = np.full(nx * ny, -1, dtype=np.int64)
    gi = ((y1 - cy - CELL / 2) / CELL).round().astype(int)
    gj = ((cx - x0 - CELL / 2) / CELL).round().astype(int)
    grid_id[gi * nx + gj] = np.arange(len(cells))

    with rasterio.open(a.raster) as src:
        lcc_to_src = Transformer.from_crs(DAYMET_LCC, src.crs, always_xy=True)
        ex = np.linspace(x0, x0 + nx * CELL, 200)
        ey = np.linspace(y1 - ny * CELL, y1, 200)
        bx = np.r_[ex, ex, np.full(200, ex[0]), np.full(200, ex[-1])]
        by = np.r_[np.full(200, ey[0]), np.full(200, ey[-1]), ey, ey]
        sx, sy = lcc_to_src.transform(bx, by)
        pad = 5 * abs(src.res[0])
        win = from_bounds(sx.min() - pad, sy.min() - pad, sx.max() + pad,
                          sy.max() + pad, src.transform).round_offsets().round_lengths()
        src_to_lcc = Transformer.from_crs(src.crs, DAYMET_LCC, always_xy=True)
        wt = src.window_transform(win)
        print("window", win, "crs", src.crs, "nodata", src.nodata, flush=True)
        acc = {}
        cols = np.arange(int(win.width)) + 0.5
        for r0 in range(0, int(win.height), a.block_rows):
            h = min(a.block_rows, int(win.height) - r0)
            sub = rasterio.windows.Window(win.col_off, win.row_off + r0, win.width, h)
            arr = src.read(1, window=sub)
            rr, cc = np.meshgrid(np.arange(h) + r0 + 0.5, cols, indexing="ij")
            px, py = wt * (cc.ravel(), rr.ravel())
            lx, ly = src_to_lcc.transform(px, py)
            j = np.floor((lx - x0) / CELL).astype(np.int64)
            i = np.floor((y1 - ly) / CELL).astype(np.int64)
            ok = (i >= 0) & (i < ny) & (j >= 0) & (j < nx)
            cid = np.full(ok.shape, -1, dtype=np.int64)
            cid[ok] = grid_id[i[ok] * nx + j[ok]]
            keep = cid >= 0
            v = arr.ravel()[keep].astype(np.int64)
            c = cid[keep]
            for val in np.unique(v):
                m = v == val
                acc.setdefault(int(val), np.zeros(len(cells), np.int64))
                acc[int(val)] += np.bincount(c[m], minlength=len(cells))
            if (r0 // a.block_rows) % 10 == 0:
                print(f"row {r0}/{int(win.height)}", flush=True)
    values = np.array(sorted(acc))
    counts = np.stack([acc[k] for k in values], axis=1)
    np.savez_compressed(a.out_npz, lat=cells.latitude.values, lon=cells.longitude.values,
                        values=values, counts=counts)
    print("cells with zero pixels:", int((counts.sum(1) == 0).sum()))
    print("median pixels/cell:", np.median(counts.sum(1)))


if __name__ == "__main__":
    main()
