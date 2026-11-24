"""Draw one curve of ngidf_places_fit from its 3 stored numbers, for the docs.

Reads xi, alpha and n_fit for one place / dataset / variable / duration, and the k table from the file's
metadata, then draws the curve and its CI the way the SNAP API would compute them:
    depth(T) = xi - alpha * ln(-ln(1 - 1/T))        CI(T) = xi + alpha * k(T, n_fit)

    python -I scripts/reports/coverage_fit_figure.py <ngidf_places_fit.nc> <out.png> [--place AK124]
        [--dataset Daymet_historical] [--variable W_veg] [--duration 24]
"""
import argparse
import ast
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from netCDF4 import Dataset  # noqa: E402


def index(nc, axis, label):
    enc = ast.literal_eval(nc[axis].encoding)
    return next(int(i) for i, v in enc.items() if str(v) == str(label))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('fit_nc')
    ap.add_argument('out_png')
    ap.add_argument('--place', default='AK124')
    ap.add_argument('--place-name', default='Fairbanks')
    ap.add_argument('--dataset', default='Daymet_historical')
    ap.add_argument('--variable', default='W_veg')
    ap.add_argument('--duration', default=24, type=int)
    a = ap.parse_args()

    with Dataset(a.fit_nc, 'r') as nc:
        ix = (index(nc, 'location', a.place), index(nc, 'dataset', a.dataset),
              index(nc, 'variable', a.variable), index(nc, 'duration', a.duration))
        xi, alpha, n = float(nc['xi'][ix]), float(nc['alpha'][ix]), nc['n_fit'][ix]
        k = json.loads(nc.ci_k_table)
    probs = np.array(k['probabilities'])
    T_tab = 1 / (1 - probs)
    T = np.geomspace(2, 500, 300)
    depth = xi - alpha * np.log(-np.log(1 - 1 / T))

    fig, ax = plt.subplots(figsize=(7.5, 4.4), dpi=150)
    green = '#1d7454'
    if not np.ma.is_masked(n):
        lo = xi + alpha * np.array(k['k_lower'][str(int(n))])
        hi = xi + alpha * np.array(k['k_upper'][str(int(n))])
        ax.fill_between(T_tab, lo, hi, color=green, alpha=0.18, lw=0,
                        label=f"{k['ci_level_percent']:g}% band: ξ + α·k(T, n_fit)")
    ax.plot(T, depth, color=green, lw=2.4, label='depth(T) = ξ − α·ln(−ln(1 − 1/T))')
    for t in [2, 10, 25, 100, 500]:
        v = xi - alpha * np.log(-np.log(1 - 1 / t))
        ax.plot(t, v, 'o', color=green, ms=5, mec='white', mew=1)
        off, ha = ((6, -14), 'left') if t == 2 else ((-6, 7), 'right')   # keep the first label off the y axis
        ax.annotate(f'{v:.1f}', (t, v), textcoords='offset points', xytext=off, ha=ha, fontsize=9)
    ax.set_xscale('log')
    ax.set_xticks([2, 5, 10, 25, 50, 100, 200, 500])
    ax.set_xticklabels(['2', '5', '10', '25', '50', '100', '200', '500'])
    ax.set_xlim(2, 500)
    ax.set_ylim(0, max(70, float(np.nanmax(depth)) * 1.25))
    ax.grid(True, color='#d7dbe0', lw=0.8)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.set_xlabel('return period T (years)')
    ax.set_ylabel(f'{a.duration}-hour depth (mm)')
    var = 'NG-IDF' if a.variable == 'W_veg' else 'precipitation IDF'
    nfit = '–' if np.ma.is_masked(n) else int(n)
    ax.set_title(f'{a.place_name} ({a.place}), {a.dataset}, {var}, {a.duration} h:   '
                 f'ξ = {xi:.2f} mm,  α = {alpha:.2f} mm,  n_fit = {nfit}', fontsize=10, loc='left')
    ax.legend(loc='upper left', frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(a.out_png, facecolor='white')
    print(a.out_png)


if __name__ == '__main__':
    main()
