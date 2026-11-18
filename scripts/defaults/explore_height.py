import sys, numpy as np, pandas as pd
d = np.load(sys.argv[1]); cells = pd.read_csv(sys.argv[2])
t = cells.mean_height_m.values; lab = cells.dominant_LULC.values
v, c = d["values"], d["counts"].astype(float)
def comp(lo, hi, f):
    m = (v >= lo) & (v <= hi); return (c[:, m] * f(v[m])).sum(1), c[:, m].sum(1)
St, Nt = comp(101, 199, lambda x: x - 100.)
Ss, Ns = comp(201, 299, lambda x: (x - 200) / 10.)
Sh, Nh = comp(301, 399, lambda x: (x - 300) / 10.)
N = c.sum(1)
ok = ~np.isnan(t)
tm = np.where(Nt > 0, St / np.maximum(Nt, 1), np.nan); sm = np.where(Ns > 0, Ss / np.maximum(Ns, 1), np.nan)
df = pd.DataFrame(dict(t=t, tree_mean=tm, shrub_mean=sm, ftree=Nt / N, fshrub=Ns / N, fherb=Nh / N, lab=lab))
print(df[ok].groupby("lab")[["t", "tree_mean", "shrub_mean", "ftree", "fshrub", "fherb"]].mean().round(2))
print(df[ok][["t", "tree_mean", "shrub_mean", "ftree", "fshrub"]].corr().round(3))
print("max code present", v.max(), "codes:", v[v > 100].tolist())
# cells that are pure tree (>95% tree px): compare t vs tree mean
p = ok & (Nt / N > 0.95)
print("pure-tree cells", p.sum(), "t vs tree_mean slope/int", np.polyfit(tm[p], t[p], 1).round(3), "corr", np.corrcoef(tm[p], t[p])[0,1].round(3))
p = ok & (Ns / N > 0.95)
print("pure-shrub cells", p.sum(), "t vs shrub_mean slope/int", np.polyfit(sm[p], t[p], 1).round(3) if p.sum()>2 else None,
      "t quantiles", np.percentile(t[p], [5,50,95]).round(2) if p.sum() else None, "shrub_mean q", np.percentile(sm[p],[5,50,95]).round(2) if p.sum() else None)
