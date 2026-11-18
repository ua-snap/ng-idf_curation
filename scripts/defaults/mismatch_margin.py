"""Diagnose land-cover mismatches: are they near-ties between groups?"""
import sys
import numpy as np, pandas as pd
XW = {11:'open',12:'open',21:'open',22:'open',23:'open',24:'open',31:'open',41:'deciduous',42:'evergreen',
      43:'mixed',51:'shrub',52:'shrub',71:'grass',72:'grass',74:'grass',81:'pasture',82:'crop',90:'wetland',95:'wetland'}
d = np.load(sys.argv[1]); cells = pd.read_csv(sys.argv[2])
lab = cells.dominant_LULC.str.strip().str.lower().values
groups = sorted(set(XW.values()))
g = np.zeros((len(cells), len(groups)))
for k, v in enumerate(d["values"]):
    g[:, groups.index(XW[int(v)])] += d["counts"][:, k]
frac = g / g.sum(1, keepdims=True)
pred = np.array(groups)[frac.argmax(1)]
srt = np.sort(frac, 1)
margin = srt[:, -1] - srt[:, -2]
ok = pred == lab
li = np.array([groups.index(l) for l in lab])
lab_frac = frac[np.arange(len(lab)), li]
print("agreement %.4f" % ok.mean())
print("margin (top1-top2) quantiles, matches   :", np.percentile(margin[ok], [5, 25, 50]).round(3))
print("margin (top1-top2) quantiles, mismatches:", np.percentile(margin[~ok], [5, 25, 50, 75, 95]).round(3))
print("label's own fraction in mismatches      :", np.percentile(lab_frac[~ok], [5, 25, 50, 75, 95]).round(3))
print("label is 2nd-ranked in mismatches: %.3f" % (srt[~ok, -2] == lab_frac[~ok]).mean())
# spatial pattern of mismatches
print(pd.crosstab(pd.cut(cells.latitude[~ok], 6), pd.cut(cells.longitude[~ok], 6)).to_string())
