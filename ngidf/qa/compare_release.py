"""How much the curves moved between two releases (e.g. old DHSVM vs new DHSVM).

Compares the 100-year magnitude (p = 0.99) of two ngidf_places.nc files, matched by place id and
dataset label: percent change per dataset x variable x duration, by land cover, the places that moved
most, and a map. Identical inputs and model give zero change everywhere (a regression test).

    python -I ngidf/qa/compare_release.py --current <cov dir> --baseline <cov dir> --defaults <csv> \
        --places <csv> --out-dir <dir> [--label-current X --label-baseline Y]
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_qa  # noqa: E402  (coverage reader, palette, plot style)
from run_qa import plt, TwoSlopeNorm, DIV, SERIES, I100  # noqa: E402


def table(cov):
    rows = []
    for di_name, di in cov['ds'].items():
        for vn, vi in cov['var'].items():
            for d, ti in cov['dur'].items():
                m = cov['mag'][:, di, vi, ti, I100]
                rows.append(pd.DataFrame(dict(id=cov['loc'], dataset=di_name, variable=vn, duration=d, value=m)))
    return pd.concat(rows, ignore_index=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--current', required=True)
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--defaults', required=True)
    ap.add_argument('--places', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--label-current', default='current')
    ap.add_argument('--label-baseline', default='baseline')
    a = ap.parse_args()
    out = Path(a.out_dir)
    (out / 'figures').mkdir(parents=True, exist_ok=True)
    cur, base = run_qa.load_cov(a.current), run_qa.load_cov(a.baseline)
    t = table(cur).merge(table(base), on=['id', 'dataset', 'variable', 'duration'], how='outer',
                         suffixes=('', '_base'))
    lc = pd.read_csv(a.defaults)[['id', 'land_cover']]
    t = t.merge(lc, on='id', how='left')
    both = t.dropna(subset=['value', 'value_base'])
    both = both.assign(diff=both.value - both.value_base, pct=100 * (both.value - both.value_base) / both.value_base)
    summary = (both.groupby(['dataset', 'variable', 'duration'])
               .agg(places=('pct', 'size'), median_pct=('pct', 'median'), p05_pct=('pct', lambda s: s.quantile(.05)),
                    p95_pct=('pct', lambda s: s.quantile(.95)), max_abs_mm=('diff', lambda s: s.abs().max()))
               .round(3).reset_index())
    by_cover = (both[both.duration == 24].groupby(['variable', 'land_cover']).pct.median().round(2)
                .reset_index(name='median_pct_24h'))
    movers = (both[(both.duration == 24) & (both.variable == 'W_veg')].assign(abs_pct=lambda d: d.pct.abs())
              .sort_values('abs_pct', ascending=False).head(15)[['id', 'dataset', 'land_cover', 'value_base', 'value', 'pct']])
    only_cur = t[t.value.notna() & t.value_base.isna()]
    only_base = t[t.value.isna() & t.value_base.notna()]
    res = dict(current=a.current, baseline=a.baseline, label_current=a.label_current, label_baseline=a.label_baseline,
               compared=len(both), max_abs_diff_mm=float(both['diff'].abs().max()) if len(both) else None,
               identical=bool(len(both) and both['diff'].abs().max() == 0),
               new_values=len(only_cur), lost_values=len(only_base),
               lost_examples=only_base.head(10).to_dict('records'),
               summary=summary.to_dict('records'), by_cover=by_cover.to_dict('records'),
               movers=movers.round(2).to_dict('records'), figures={})

    # map + histogram: NG, 24 h, WRF historical
    sel = both[(both.dataset == 'WRF_historical') & (both.variable == 'W_veg') & (both.duration == 24)]
    if len(sel):
        pl = pd.read_csv(a.places).set_index('id').loc[sel.id]
        lon = np.where(pl.longitude > 0, pl.longitude - 360, pl.longitude)
        f, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 3.8), gridspec_kw=dict(width_ratios=[1.6, 1]))
        lim = max(float(sel.pct.abs().max()), 0.01)
        sc = ax1.scatter(lon, pl.latitude, c=sel.pct, cmap=DIV, norm=TwoSlopeNorm(0, -lim, lim), s=16,
                         edgecolor='#fcfcfb', linewidth=0.4)
        cb = f.colorbar(sc, ax=ax1, shrink=0.85)
        cb.set_label('% change', color=run_qa.TEXT2)
        cb.outline.set_visible(False)
        ax1.set_aspect(1 / np.cos(np.radians(62)))
        ax1.set_title(f'100-yr 24-h NG, WRF historical: {a.label_current} vs {a.label_baseline}', loc='left')
        ax2.hist(sel.pct, bins=40, color=SERIES[0], edgecolor='#fcfcfb', linewidth=0.5)
        ax2.set_xlabel('% change')
        ax2.set_ylabel('places')
        ax2.set_title('distribution over places', loc='left')
        f.tight_layout()
        f.savefig(out / 'figures/release_change.png', dpi=130)
        plt.close(f)
        res['figures']['release_change'] = f'Change in the 100-year 24-hour NG value, {a.label_current} vs {a.label_baseline}'
    (out / 'compare.json').write_text(json.dumps(res, indent=1, default=str) + '\n')
    print(json.dumps({k: res[k] for k in ('compared', 'max_abs_diff_mm', 'identical', 'new_values', 'lost_values')}))


if __name__ == '__main__':
    main()
