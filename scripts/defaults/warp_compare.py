"""Warp a categorical raster to the Daymet 1 km grid of the defaults table with
gdalwarp (several resampling methods) and compare against dominant_LULC."""
import subprocess, sys, os
import numpy as np, pandas as pd, rasterio
from pyproj import Transformer
LCC = "+proj=lcc +lat_1=25 +lat_2=60 +lat_0=42.5 +lon_0=-100 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"
XW = {11:'open',12:'open',21:'open',22:'open',23:'open',24:'open',31:'open',41:'deciduous',42:'evergreen',
      43:'mixed',51:'shrub',52:'shrub',71:'grass',72:'grass',74:'grass',81:'pasture',82:'crop',90:'wetland',95:'wetland'}
src, cells_csv, outdir = sys.argv[1:4]
cells = pd.read_csv(cells_csv); lab = cells.dominant_LULC.str.lower().values
cx, cy = Transformer.from_crs("EPSG:4326", LCC, always_xy=True).transform(cells.longitude.values, cells.latitude.values)
cx = np.round((cx - 750) / 1000) * 1000 + 750; cy = np.round(cy / 1000) * 1000
te = [cx.min() - 500, cy.min() - 500, cx.max() + 500, cy.max() + 500]
for method in ["mode", "nearest"]:
    out = os.path.join(outdir, f"nlcd_daymet1km_{method}.tif")
    subprocess.run(["gdalwarp", "-overwrite", "-q", "-t_srs", LCC, "-tr", "1000", "1000", "-te", *map(str, te),
                    "-r", method, "-ot", "Byte", src, out], check=True)
    with rasterio.open(out) as r:
        a = r.read(1); rows, cols = r.index(cx, cy)
    v = a[rows, cols]
    pred = np.array([XW.get(int(x), "?") for x in v])
    print(f"gdalwarp -r {method:8s}: agreement {np.mean(pred == lab):.4f}")
