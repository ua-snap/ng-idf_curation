"""Pull curves, future changes and model inputs for a few communities out of the place coverage.

This regenerates the data behind the "NG-IDF curves for selected Alaska communities" document.

Writes these files to <out_dir>:
  curves.csv        depth at return periods 2, 5, 10, 25, 50, 100, 500 yr for each community x dataset x variable x duration,
                    with the 90% CI (single runs) or the member min/max (ensemble means)
  future_change.csv 100-year NG change, future vs historical: CESM ensemble mean, the range of the 4 members' own
                    changes, and WRF high vs WRF historical (duration set by --duration)
  inputs.csv        per-community run inputs (ngidf_places_inputs.csv) plus the vegetation and snow settings
                    written into each community's DHSVM configuration
  summary.json      everything above in one file

Usage:
  python -I community_summary.py --coverage-dir <dir with ngidf_places.nc> --runs-root <runs dir> \
      --out-dir <dir> [--ids AK124 AK62 ...] [--duration 24]
"""
import argparse
import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
from netCDF4 import Dataset

DEFAULT_IDS = ['AK124', 'AK62', 'AK15', 'AK172', 'AK142', 'AK36', 'AK418', 'AK22']
ARIS = [2, 5, 10, 25, 50, 100, 500]
CURVE_DATASETS = ['Daymet_historical', 'WRF_historical', 'WRF_high', 'CESM_hist_ensemble_mean', 'CESM_futu_ensemble_mean']
MEMBERS = [2, 4, 7, 9]
CONFIG_KEYS = ['Vegetation Description', 'Overstory Present', 'Understory Present', 'Fractional Coverage',
               'Trunk Space', 'Height', 'Overstory Monthly LAI', 'Understory Monthly LAI', 'Max Snow Int Capacity',
               'Snow Interception Eff', 'Rain LAI Multiplier', 'Snow LAI Multiplier', 'Rain Threshold',
               'Snow Threshold', 'Fresh Snow Albedo', 'Albedo Accumulation Lambda', 'Albedo Melting Lambda',
               'Reference Height']


def value(x):
    return None if np.ma.is_masked(x) else round(float(x), 2)


def read_config(path):
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        for k in CONFIG_KEYS:
            if line.strip().startswith(k) and '=' in line:
                out[k] = line.split('=', 1)[1].split('#')[0].strip()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--coverage-dir', type=Path, required=True)
    ap.add_argument('--runs-root', type=Path, required=True)
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--ids', nargs='+', default=DEFAULT_IDS)
    ap.add_argument('--duration', type=int, default=24, help='duration (h) for future_change.csv')
    args = ap.parse_args()

    nc = Dataset(args.coverage_dir / 'ngidf_places.nc')
    loc = {v: k for k, v in ast.literal_eval(nc['location'].encoding).items()}
    ds = {v: k for k, v in ast.literal_eval(nc['dataset'].encoding).items()}
    var = ast.literal_eval(nc['variable'].encoding)
    dur = ast.literal_eval(nc['duration'].encoding)
    probs = ast.literal_eval(nc['exceedance'].encoding)
    ari_index = {a: min(probs, key=lambda i: abs(1 / (1 - probs[i]) - a)) for a in ARIS}
    mag, lo, hi, mn, mx = (nc[v][:] for v in ['magnitude', 'ci_lower', 'ci_upper', 'member_min', 'member_max'])
    inputs = pd.read_csv(args.coverage_dir / 'ngidf_places_inputs.csv')
    names = inputs.set_index('id').name

    curves = []
    for pid in args.ids:
        li = loc[pid]
        for key in CURVE_DATASETS:
            j = ds[key]
            ens = 'ensemble' in key
            for vi, vname in var.items():
                for di, hours in dur.items():
                    for a, ei in ari_index.items():
                        m = value(mag[li, j, vi, di, ei])
                        if m is None:
                            continue
                        low, high = (mn, mx) if ens else (lo, hi)
                        curves.append(dict(id=pid, place=names[pid], dataset=key, variable=vname, duration_h=hours,
                                           return_period_yr=a, depth_mm=m, low_mm=value(low[li, j, vi, di, ei]),
                                           high_mm=value(high[li, j, vi, di, ei]),
                                           band='member min/max' if ens else '90% CI'))

    di = next(k for k, h in dur.items() if h == args.duration)
    ng = next(k for k, v in var.items() if v == 'W_veg')
    e100 = ari_index[100]
    change = []
    for pid in args.ids:
        li = loc[pid]
        g = lambda key: float(mag[li, ds[key], ng, di, e100])
        hist, fut = g('CESM_hist_ensemble_mean'), g('CESM_futu_ensemble_mean')
        members = [(g(f'CESM_futu_LE{m}') / g(f'CESM_hist_LE{m}') - 1) * 100 for m in MEMBERS]
        change.append(dict(id=pid, place=names[pid], duration_h=args.duration,
                           cesm_hist_mm=round(hist, 2), cesm_futu_mm=round(fut, 2),
                           cesm_change_pct=round((fut / hist - 1) * 100, 1),
                           member_change_min_pct=round(min(members), 1), member_change_max_pct=round(max(members), 1),
                           wrf_hist_mm=round(g('WRF_historical'), 2), wrf_high_mm=round(g('WRF_high'), 2),
                           wrf_change_pct=round((g('WRF_high') / g('WRF_historical') - 1) * 100, 1)))

    inp = inputs[inputs.id.isin(args.ids)].copy()
    cfg = pd.DataFrame([dict(id=pid, **{f'dhsvm: {k}': v for k, v in
                                        read_config(args.runs_root / pid / 'WRF_historical' / 'Input.Snotel.T4').items()})
                        for pid in args.ids])
    inp = inp.merge(cfg, on='id', how='left')

    args.out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(curves).to_csv(args.out_dir / 'curves.csv', index=False)
    pd.DataFrame(change).to_csv(args.out_dir / 'future_change.csv', index=False)
    inp.to_csv(args.out_dir / 'inputs.csv', index=False)
    (args.out_dir / 'summary.json').write_text(json.dumps(
        dict(source=str(args.coverage_dir), ids=args.ids, curves=curves, future_change=change,
             inputs=inp.to_dict('records')), indent=1, default=str) + '\n')
    print(f'{len(curves)} curve rows, {len(change)} change rows, {len(inp)} input rows -> {args.out_dir}')


if __name__ == '__main__':
    main()
