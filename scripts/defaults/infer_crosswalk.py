"""Infer the land-cover-class -> NG-IDF dominant_LULC crosswalk used to build
static/gridcell_current_lulc.csv, from per-cell class counts (zonal_counts.py).

Tests two aggregation orders:
  B: take the modal source class in each 1 km cell, then map it to a label.
  A: map every pixel to a label first, then take the modal label.
"""
import sys

import numpy as np
import pandas as pd

counts_npz, cells_csv = sys.argv[1], sys.argv[2]
d = np.load(counts_npz)
cells = pd.read_csv(cells_csv)
lab = cells.dominant_LULC.str.strip().str.lower().values
vals, cnt = d["values"], d["counts"]
print("source values:", vals.tolist())
print("pixel totals per value:", dict(zip(vals.tolist(), cnt.sum(0).tolist())))

# ---- B: modal source class -> label
mode_cls = vals[np.argmax(cnt, axis=1)]
ct = pd.crosstab(pd.Series(mode_cls, name="modal_class"), pd.Series(lab, name="label"))
print("\nB: modal source class vs label\n", ct.to_string())
xw = ct.idxmax(axis=1).to_dict()
pred_b = np.array([xw[c] for c in mode_cls])
print("\nB crosswalk:", xw)
print("B agreement: %.4f" % (pred_b == lab).mean())

# ---- A: map pixels to labels using the B crosswalk, then mode
groups = sorted(set(xw.values()))
gcnt = np.zeros((len(cells), len(groups)), np.int64)
for k, v in enumerate(vals):
    if v in xw:
        gcnt[:, groups.index(xw[v])] += cnt[:, k]
pred_a = np.array(groups)[np.argmax(gcnt, axis=1)]
print("A agreement (same crosswalk, map-then-mode): %.4f" % (pred_a == lab).mean())

# disagreements summary for the better hypothesis
best = pred_a if (pred_a == lab).mean() > (pred_b == lab).mean() else pred_b
bad = best != lab
print("\nremaining mismatches:", int(bad.sum()))
print(pd.crosstab(pd.Series(lab[bad], name="label"), pd.Series(best[bad], name="pred")).to_string())
