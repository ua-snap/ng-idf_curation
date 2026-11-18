"""Infer how mean_height_m in gridcell_current_lulc.csv was derived from
LANDFIRE 2016 Remap EVH (AK), using per-cell code counts from zonal_counts.py.

EVH codes: 101-199 tree (m = code-100); 201-230 shrub (m = (code-200)/10);
301-310 herb (m = (code-300)/10); everything else is non-vegetated/other.
"""
import sys

import numpy as np
import pandas as pd

d = np.load(sys.argv[1])
cells = pd.read_csv(sys.argv[2])
target = cells.mean_height_m.values
vals, cnt = d["values"], d["counts"].astype(float)

h = np.full(len(vals), np.nan)
life = np.full(len(vals), "", dtype=object)
for k, v in enumerate(vals):
    if 101 <= v <= 199:
        h[k], life[k] = v - 100, "tree"
    elif 201 <= v <= 299:
        h[k], life[k] = (v - 200) / 10, "shrub"
    elif 301 <= v <= 399:
        h[k], life[k] = (v - 300) / 10, "herb"
print("codes present:", vals.tolist())


def rule(lifeforms, denom_all=False):
    m = np.isin(life, lifeforms)
    num = (cnt[:, m] * h[m]).sum(1)
    den = cnt.sum(1) if denom_all else cnt[:, m].sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[den == 0] = np.nan
    return out


rules = {
    "mean tree+shrub+herb (veg px)": rule(["tree", "shrub", "herb"]),
    "mean tree+shrub (veg px)": rule(["tree", "shrub"]),
    "mean tree (tree px)": rule(["tree"]),
    "mean tree+shrub+herb (all px, nonveg=0)": rule(["tree", "shrub", "herb"], True),
}
both = ~np.isnan(target)
for name, est in rules.items():
    ok = both & ~np.isnan(est)
    err = np.abs(np.round(est[ok], 2) - target[ok])
    nan_agree = (np.isnan(est) == np.isnan(target)).mean()
    print(f"{name:45s} exact(2dp)={np.mean(err < 0.006):.3f} "
          f"MAE={err.mean():.3f} p99={np.percentile(err, 99):.3f} NaN-pattern-agree={nan_agree:.4f}")
