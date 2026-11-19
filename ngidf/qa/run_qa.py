"""Science QA of a set of production runs and their coverage (pipeline stage `qa`).

Writes <out>/qa.json and <out>/figures/*.png:

  fidelity    Every run's adaptations.diff (what our per-run copy changes in the app) is reduced to a
              signature (seed, coordinates and dataset names masked). All runs should share one or two
              signatures (Daymet vs WRF/CESM coordinate file); each is checked line by line.
              config_vs_template.diff: which DHSVM config keys the app filled in, and how many values.
  fits        From each run's result.npz: annual maxima per fit (the app drops the first), quantiles
              non-decreasing in probability, CI brackets the fitted value, no missing values.
  science     From the coverage: 100-yr 24-h depths, NG/P ratio by land cover, rain/snowmelt/rain-on-snow
              mix of the W_veg annual maxima, CESM future change; maps and community curves.
"""
import argparse
import ast
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from netCDF4 import Dataset  # noqa: E402

# reference palette (dataviz skill, references/palette.md), light mode
SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']
TEXT, TEXT2, GRID, SURFACE = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
SEQ = LinearSegmentedColormap.from_list('seq', ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'])
DIV = LinearSegmentedColormap.from_list('div', ['#1c5cab', '#86b6ef', '#f0efec', '#f1a3a2', '#b02a2a'])
COMMUNITIES = ['AK124', 'AK62', 'AK15', 'AK172', 'AK142', 'AK36', 'AK418', 'AK22']  # as in the PDF report
CURVE_SETS = [('Daymet_historical', 'Daymet historical'), ('WRF_historical', 'WRF historical'),
              ('CESM_hist_ensemble_mean', 'CESM historical (ens. mean)'),
              ('CESM_futu_ensemble_mean', 'CESM future (ens. mean)')]
I100 = 49  # p = 0.99 -> 100-year
ARI = [1 / (1 - p) for p in [round(0.50 + 0.01 * i, 2) for i in range(50)] + [0.998]]

plt.rcParams.update({'font.size': 9, 'axes.edgecolor': GRID, 'axes.labelcolor': TEXT2, 'xtick.color': TEXT2,
                     'ytick.color': TEXT2, 'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6,
                     'axes.spines.top': False, 'axes.spines.right': False, 'figure.facecolor': SURFACE,
                     'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE, 'axes.titlecolor': TEXT,
                     'axes.titlesize': 9, 'legend.frameon': False, 'lines.linewidth': 2})


# ---------------------------------------------------------------------------------------- fidelity
def diff_signature(text):
    t = re.sub(r'set\.seed\(\d+\)', 'set.seed(<seed>)', text)
    t = re.sub(r'-?\d+\.\d{5}', '<coord>', t)
    t = re.sub(r'met/[A-Za-z0-9_]+/', 'met/<dataset>/', t)
    t = re.sub(r' -> \S+', ' -> <path>', t)
    t = re.sub(r'@@[^@]*@@', '@@', t)
    return t


def check_adaptation(text):
    """The changes we allow, and nothing else."""
    problems = []
    blocks = re.split(r'(?m)^--- ', text)
    for b in blocks[1:]:
        name = b.split('\n', 1)[0].strip()
        added = [l[1:] for l in b.splitlines() if l.startswith('+') and not l.startswith('+++')]
        removed = [l[1:] for l in b.splitlines() if l.startswith('-') and not l.startswith('---')]
        if name == 'app/get_IDF.R':
            ok_add = all(re.fullmatch(r'set\.seed\(\d+\)  # ngidf batch adaptation', l) or l == 'library(lmom)'
                         for l in added)
            ok_rm = removed == ["library(lmom, lib.loc='/hongxiang/app/Rlibrary')"]
            if not (ok_add and ok_rm and len(added) == 2):
                problems.append('get_IDF.R: unexpected change')
        elif name.startswith('app/example_config/param_5cluster'):
            if removed or len(added) != 1:
                problems.append('snow parameter table: expected exactly one added row')
        elif name.startswith('app/static/'):
            if len(added) != 1:
                problems.append(f'{name}: expected one coordinate line')
    return problems


def fidelity(runs_root, manifest):
    sigs, examples, problems, n = Counter(), {}, [], 0
    keys = defaultdict(set)
    key_runs = Counter()
    for r in manifest.itertuples(index=False):
        d = runs_root / r.place_id / r.dataset
        f = d / 'adaptations.diff'
        if not f.exists():
            continue
        n += 1
        t = f.read_text()
        s = diff_signature(t)
        sigs[s] += 1
        examples.setdefault(s, dict(run=f'{r.place_id}/{r.dataset}', diff=t))
        p = check_adaptation(t)
        if p:
            problems.append(dict(run=f'{r.place_id}/{r.dataset}', problems=p))
        c = d / 'config_vs_template.diff'
        if c.exists():
            for line in c.read_text().splitlines():
                if line.startswith('+') and not line.startswith('+++') and '=' in line:
                    k, v = line[1:].split('=', 1)
                    k = re.sub(r'\s+', ' ', k.strip())
                    keys[k].add(v.split('#')[0].strip())
                    key_runs[k] += 1
    cfg = sorted([dict(key=k, runs=key_runs[k], distinct_values=len(v),
                       example=sorted(v)[0][:60] if len(v) == 1 else f'{len(v)} values') for k, v in keys.items()],
                 key=lambda x: x['key'])
    ex_cfg = None
    for pid, ds in (('AK124', 'WRF_historical'), ('AK124', 'Daymet')):
        c = runs_root / pid / ds / 'config_vs_template.diff'
        if c.exists():
            ex_cfg = dict(run=f'{pid}/{ds}', diff=c.read_text())
            break
    return dict(runs_with_diff=n, signatures=[dict(count=c, **examples[s]) for s, c in sigs.most_common()],
                runs_with_unexpected_changes=len(problems), unexpected=problems[:20], config_keys=cfg,
                config_example=ex_cfg)


# -------------------------------------------------------------------------------------------- fits
def fits(runs_root, manifest):
    rows = []
    for r in manifest.itertuples(index=False):
        d = runs_root / r.place_id / r.dataset
        rj = d / 'run.json'
        if not rj.exists() or json.loads(rj.read_text()).get('status') != 'ok':
            continue
        z = np.load(d / 'result.npz')
        for k in z.files:
            m = re.fullmatch(r'(full|near)/IDF_(\d+h)_(P|W_veg)', k)
            if not m:
                continue
            win, dur, var = m.groups()
            a = z[k]
            am = z[f'{win}/am_{dur}_{var}']
            mag, lo, hi = a
            rows.append(dict(dataset=r.dataset, window=win, var=var, dur=dur, am=len(am),
                             finite=bool(np.isfinite(a).all()),
                             monotonic=bool(np.all(np.diff(mag) >= -0.01)),
                             ci_brackets=bool(np.all((lo <= mag + 0.01) & (mag <= hi + 0.01)))))
    df = pd.DataFrame(rows)
    if df.empty:
        return dict(fits=0), df
    am = df.groupby(['dataset', 'window']).am.agg(lambda s: dict(Counter(s))).reset_index()
    am['used_in_fit'] = am.am.map(lambda c: {int(k) - 1: v for k, v in c.items()})
    out = dict(fits=len(df), all_finite=int(df.finite.sum()), monotonic=int(df.monotonic.sum()),
               ci_brackets=int(df.ci_brackets.sum()),
               am_counts=[dict(dataset=r.dataset, window=r.window, used_in_fit=r.used_in_fit) for r in am.itertuples()])
    return out, df


# ----------------------------------------------------------------------------------------- science
def enc(nc, name):
    return ast.literal_eval(nc[name].encoding)


def load_cov(cov_dir):
    with Dataset(Path(cov_dir) / 'ngidf_places.nc') as nc:
        loc, ds, var, dur = enc(nc, 'location'), enc(nc, 'dataset'), enc(nc, 'variable'), enc(nc, 'duration')
        mag = np.ma.filled(nc['magnitude'][:].astype(float), np.nan)
        lo = np.ma.filled(nc['ci_lower'][:].astype(float), np.nan)
        hi = np.ma.filled(nc['ci_upper'][:].astype(float), np.nan)
        attrs = {k: nc.getncattr(k) for k in nc.ncattrs()}
    mech = None
    am_path = Path(cov_dir) / 'ngidf_places_am.nc'
    if am_path.exists():
        with Dataset(am_path) as nc:
            mech = dict(ds=enc(nc, 'dataset'), dur=enc(nc, 'duration'),
                        mech=np.ma.filled(nc['mechanism'][:], -9999), used=np.ma.filled(nc['used_in_fit'][:], -9999))
    inv = lambda e: {v: k for k, v in e.items()}  # noqa: E731
    return dict(loc=[loc[i] for i in range(len(loc))], ds=inv(ds), var=inv(var), dur=inv(dur), mag=mag, lo=lo, hi=hi,
                attrs=attrs, am=mech)


def science(cov, places, defaults, fig_dir):
    out, figs = {}, {}
    pl = places.set_index('id').loc[cov['loc']]
    lc = defaults.set_index('id').reindex(cov['loc']).land_cover.fillna('none').values
    d24 = cov['dur'][24]
    P, NG = cov['var']['P'], cov['var']['W_veg']
    v100 = lambda key, v: cov['mag'][:, cov['ds'][key], v, d24, I100]  # noqa: E731

    rows = []
    for key in ['Daymet_historical', 'WRF_historical', 'WRF_high', 'CESM_hist_ensemble_mean', 'CESM_futu_ensemble_mean']:
        p, g = v100(key, P), v100(key, NG)
        rows.append(dict(dataset=key, places=int(np.isfinite(g).sum()), P_median_mm=round(float(np.nanmedian(p)), 1),
                         NG_median_mm=round(float(np.nanmedian(g)), 1),
                         NG_over_P_median=round(float(np.nanmedian(g / p)), 3)))
    out['depth_100yr_24h'] = rows

    ratio = v100('WRF_historical', NG) / v100('WRF_historical', P)
    out['ng_over_p_by_cover'] = [dict(land_cover=c, places=int(np.isfinite(ratio[lc == c]).sum()),
                                      median=round(float(np.nanmedian(ratio[lc == c])), 3),
                                      p10=round(float(np.nanpercentile(ratio[lc == c], 10)), 3),
                                      p90=round(float(np.nanpercentile(ratio[lc == c], 90)), 3))
                                 for c in sorted(set(lc)) if np.isfinite(ratio[lc == c]).any()]

    if cov['am'] is not None:
        a = cov['am']
        inv = {v: k for k, v in a['ds'].items()}
        dd = {v: k for k, v in a['dur'].items()}[24]
        mix = []
        for name, i in inv.items():
            m = a['mech'][:, i, NG, dd, :]
            u = a['used'][:, i, NG, dd, :] == 1
            vals = m[u & (m > 0)]
            if vals.size:
                mix.append(dict(dataset=name, rain=round(float((vals == 1).mean()), 3),
                                snowmelt=round(float((vals == 2).mean()), 3),
                                rain_on_snow=round(float((vals == 3).mean()), 3), maxima=int(vals.size)))
        out['mechanism_24h'] = mix

    fut, hist = v100('CESM_futu_ensemble_mean', NG), v100('CESM_hist_ensemble_mean', NG)
    chg = 100 * (fut - hist) / hist
    out['cesm_change_ng_100yr_24h_pct'] = dict(median=round(float(np.nanmedian(chg)), 1),
                                               p10=round(float(np.nanpercentile(chg, 10)), 1),
                                               p90=round(float(np.nanpercentile(chg, 90)), 1))

    lon = pl.longitude.values.astype(float)
    lon = np.where(lon > 0, lon - 360, lon)
    lat = pl.latitude.values.astype(float)

    def amap(vals, title, cmap, norm, label, name):
        f, ax = plt.subplots(figsize=(6.4, 4.2))
        ok = np.isfinite(vals)
        ax.scatter(lon[~ok], lat[~ok], s=10, facecolor='none', edgecolor='#a9a8a2', linewidth=0.8, label='nodata')
        sc = ax.scatter(lon[ok], lat[ok], c=vals[ok], s=16, cmap=cmap, norm=norm, edgecolor=SURFACE, linewidth=0.4)
        cb = f.colorbar(sc, ax=ax, shrink=0.8)
        cb.set_label(label, color=TEXT2)
        cb.outline.set_visible(False)
        ax.set_title(title, loc='left')
        ax.set_xlabel('longitude')
        ax.set_ylabel('latitude')
        ax.set_aspect(1 / np.cos(np.radians(62)))
        ax.legend(loc='lower left', fontsize=8)
        f.tight_layout()
        f.savefig(fig_dir / f'{name}.png', dpi=130)
        plt.close(f)
        figs[name] = title

    g = v100('WRF_historical', NG)
    amap(g, '100-year 24-hour NG (W_veg), WRF historical', SEQ, plt.Normalize(np.nanpercentile(g, 2),
                                                                             np.nanpercentile(g, 98)), 'mm', 'map_ng_wrf_hist')
    amap(ratio, 'NG / precipitation, 100-year 24-hour, WRF historical', DIV, TwoSlopeNorm(1.0, np.nanmin(ratio),
                                                                                       max(np.nanmax(ratio), 1.01)),
         'ratio (1 = same as precipitation)', 'map_ng_over_p')
    lim = float(np.nanpercentile(np.abs(chg), 98)) or 1
    amap(chg, '100-year 24-hour NG: CESM future vs historical (ensemble means)', DIV, TwoSlopeNorm(0, -lim, lim),
         '% change', 'map_cesm_change')

    # community curves (small multiples: one row per community, P | NG)
    ids = [i for i in COMMUNITIES if i in cov['loc']]
    f, axes = plt.subplots(len(ids), 2, figsize=(7.2, 2.0 * len(ids)), sharex=True)
    for r, pid in enumerate(ids):
        li = cov['loc'].index(pid)
        for c, (v, vname) in enumerate([(P, 'Precipitation (P)'), (NG, 'NG (W_veg)')]):
            ax = axes[r, c]
            for k, (key, lab) in enumerate(CURVE_SETS):
                y = cov['mag'][li, cov['ds'][key], v, d24]
                if np.isfinite(y).any():
                    ax.plot(ARI, y, color=SERIES[k], label=lab)
                    lo, hi = cov['lo'][li, cov['ds'][key], v, d24], cov['hi'][li, cov['ds'][key], v, d24]
                    if np.isfinite(lo).any():
                        ax.fill_between(ARI, lo, hi, color=SERIES[k], alpha=0.12, linewidth=0)
            ax.set_xscale('log')
            ax.set_xticks([2, 5, 10, 25, 50, 100, 500], ['2', '5', '10', '25', '50', '100', '500'])
            ax.set_title(f"{pid} {pl.loc[pid, 'name']}: {vname}", loc='left')
            if c == 0:
                ax.set_ylabel('24-h depth (mm)')
    for ax in axes[-1]:
        ax.set_xlabel('return period (years)')
    h, l_ = axes[0, 0].get_legend_handles_labels()
    f.legend(h, l_, loc='upper center', ncol=2, bbox_to_anchor=(0.5, 1.0))
    f.tight_layout(rect=(0, 0, 1, 1 - 0.5 / len(ids) / 2.0))
    f.savefig(fig_dir / 'community_curves.png', dpi=120)
    plt.close(f)
    figs['community_curves'] = ('24-hour IDF curves for the communities in the PDF report; shading = CI of single '
                                'runs (none for ensemble means, as in the app)')
    return out, figs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs-root', required=True)
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--coverage-dir', required=True)
    ap.add_argument('--places', required=True)
    ap.add_argument('--defaults', required=True)
    ap.add_argument('--out-dir', required=True)
    a = ap.parse_args()
    out = Path(a.out_dir)
    (out / 'figures').mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(a.manifest)
    runs_root = Path(a.runs_root)
    fid = fidelity(runs_root, manifest)
    fit, _ = fits(runs_root, manifest)
    cov = load_cov(a.coverage_dir)
    sci, figs = science(cov, pd.read_csv(a.places), pd.read_csv(a.defaults), out / 'figures')
    res = dict(fidelity=fid, fits=fit, science=sci, figures=figs, coverage_dir=a.coverage_dir)
    (out / 'qa.json').write_text(json.dumps(res, indent=1, default=str) + '\n')
    print(json.dumps(dict(fits=fit, signatures=[s['count'] for s in fid['signatures']],
                          unexpected=fid['runs_with_unexpected_changes']), indent=1, default=str))


if __name__ == '__main__':
    main()
