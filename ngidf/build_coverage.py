"""Assemble the Phase 1 place-indexed NG-IDF coverages from per-run results.

Outputs (netCDF4, ready for wcst_import general_coverage):
  ngidf_places.nc     location x dataset x variable x duration x exceedance
                      bands: magnitude, ci_lower, ci_upper, member_min, member_max (mm)
  ngidf_places_am.nc  location x dataset x variable x duration x am_index
                      bands: am_depth (mm), water_year, peak_date, mechanism, used_in_fit

Every axis is an integer index with an `encoding` attribute (a Python-literal dict
from index to label), the convention the SNAP data API decodes.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
from netCDF4 import Dataset

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ngidf'))
import appinfo  # noqa: E402  (method settings read from the app's own code)
FILL = -9999.0
DURATIONS = [1, 3, 6, 12, 24, 48, 72]
PROBS = [round(0.50 + 0.01 * i, 2) for i in range(50)] + [0.998]
VARIABLES = {0: ('P', 'PREC-IDF: precipitation'), 1: ('W_veg', 'NG-IDF: next-generation (rain + snowmelt reaching the ground, W_veg)')}
MEMBERS = [2, 4, 7, 9]

# (key, source run dataset, window, description)
DATASETS = [('Daymet_historical', 'Daymet', 'full', 'Daymet 1 km daily, MetSim 3-hourly; historical; AM WY1990-2021, fit WY1991-2021; 24/48/72 h only')]
DATASETS += [(k, k, 'full', d) for k, d in [
    ('WRF_historical', 'WRF 4 km hourly, ERA5-driven historical; AM WY1990-2021, fit WY1991-2021'),
    ('WRF_medium', 'WRF 4 km hourly, pseudo-global-warming medium; AM WY2034-2065, fit WY2035-2065'),
    ('WRF_high', 'WRF 4 km hourly, pseudo-global-warming high; AM WY2034-2065, fit WY2035-2065')]]
for period, wy in [('hist', ('1990-2021', '1991-2021')), ('futu', ('2034-2065', '2035-2065'))]:
    for m in MEMBERS:
        DATASETS.append((f'CESM_{period}_LE{m}', f'CESM_{period}_LE{m}', 'full',
                         f'WRF 4 km hourly driven by CESM2-LE member {m}, {"historical" if period == "hist" else "future"}; '
                         f'full period; AM WY{wy[0]}, fit WY{wy[1]}'))
for period, wy in [('hist', ('2006-2021', '2007-2021')), ('futu', ('2034-2049', '2035-2049'))]:
    for m in MEMBERS:
        DATASETS.append((f'CESM_{period}_LE{m}_nearterm', f'CESM_{period}_LE{m}', 'near',
                         f'WRF 4 km hourly driven by CESM2-LE member {m}, {"historical" if period == "hist" else "future"}; '
                         f'near-term window (app year_range); AM WY{wy[0]}, fit WY{wy[1]}'))
ENSEMBLES = [('CESM_hist_ensemble_mean', 'hist', 'full'), ('CESM_futu_ensemble_mean', 'futu', 'full'),
             ('CESM_hist_ensemble_mean_nearterm', 'hist', 'near'), ('CESM_futu_ensemble_mean_nearterm', 'futu', 'near')]
for key, period, win in ENSEMBLES:
    DATASETS.append((key, None, win, f'Mean of the 4 CESM2-LE members ({period}, {"full period" if win == "full" else "near-term window"}) '
                     'fitted magnitudes, as the app computes it; member_min/member_max give the member range; no CI'))
AM_DATASETS = [d for d in DATASETS if d[2] == 'full' and d[1] is not None]

METHOD = (
    "These curves reproduce the NG-IDF web application of Hongxiang Yan (PNNL), "
    "{upstream}, branch {branch}, commit {commit}, exactly as implemented. "
    "SNAP did not change any scientific choice: we are not hydrologists, so the author's method is used 100 percent. "
    "For each place and forcing dataset the app's own code was run: dhsvm_idf.generate_ng_idf writes the DHSVM 3.2 "
    "configuration for a 3x3 point domain, DHSVM 3.2 (built from the app's source) simulates the full period, "
    "extract_AM.extract_AM_data computes water-year annual maxima of moving-window sums for 1, 3, 6, 12, 24, 48 and 72 hours "
    "for precipitation (P) and water reaching the ground (W_veg), and get_IDF.R (R package lmom) drops the first annual "
    "maximum, fits a Gumbel distribution by L-moments, and reports quantiles at 51 non-exceedance probabilities "
    "(0.50 to 0.99 by 0.01, plus 0.998) with a {ci:g} percent confidence interval from {nsim} parametric bootstrap samples. "
    "Values are depths in millimetres over the duration, rounded to 0.01 mm as in the app (divide by 25.4 for inches)."
)
ADAPTATIONS = (
    "Batch adaptations (no effect on the method): "
    "(1) a wrapper calls the app functions directly instead of the web form, reproducing the form's rounding of inputs; "
    "(2) land cover, LAI and canopy height come from the author's Interior Alaska table where a place is inside it, "
    "and otherwise from a statewide rebuild of that table from the same sources (NLCD 2016, GLASS LAI 2016, LANDFIRE 2016 EVH) "
    "on the same Daymet 1 km grid; see defaults_source per location; "
    "(3) WRF and CESM forcing was extracted for each 4 km cell from the NNA archive with the author's conversions, "
    "validated against the author's own station files to their text precision; "
    "(4) snow parameters are the single Alaska parameter set in the app's table; "
    "(5) a fixed random seed per run before get_IDF.R makes the bootstrap confidence interval reproducible; "
    "(6) the forcing cell is chosen with the app's own nearest-cell rule over the full 4 km grid."
)
QUIRKS = (
    "Behaviours of the app that are reproduced, not corrected: the first annual maximum is dropped although the series "
    "already starts on 1 October, so fits use 31 water years for full periods and 15 for the near-term window; "
    "the DHSVM basin centre and time-zone meridian keep the template values; the forcing cell is the nearest by unscaled "
    "degrees of latitude and longitude; Daymet runs report only 24, 48 and 72 hour durations."
)


def git_rev():
    try:
        return subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    except Exception:
        return 'unknown'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_run(runs_root, pid, ds):
    p = Path(runs_root) / pid / ds / 'result.npz'
    rj = Path(runs_root) / pid / ds / 'run.json'
    if not p.exists() or not rj.exists() or json.loads(rj.read_text()).get('status') != 'ok':
        return None
    return np.load(p)


def failed_runs(runs_root, places):
    """Places whose DHSVM runs failed, with the DHSVM error line (the app would fail the same way)."""
    out = {}
    for pid in places.id:
        d = Path(runs_root) / pid
        if not d.exists():
            continue
        for rj in d.glob('*/run.json'):
            if json.loads(rj.read_text()).get('status') == 'failed':
                log = rj.parent / 'dhsvm.log'
                msg = next((l.strip() for l in log.read_text().splitlines() if 'error' in l.lower()), 'DHSVM failed') \
                    if log.exists() else 'run failed'
                out.setdefault(pid, {}).setdefault(msg, []).append(rj.parent.name)
    return out


def nodata_text(places, defaults, failures=None):
    def names(df):
        return ', '.join(f'{r.id} {r.name}' for r in df.itertuples())
    parts, listed = [], set()
    nod = places.merge(defaults[['id', 'cover_code']], on='id') if defaults is not None else places.iloc[:0]
    far = nod[(nod.cover_code < 0) & (nod.defaults_status != 'ok')] if 'defaults_status' in nod else nod.iloc[:0]
    if len(far):
        parts.append(f'All entries are nodata for {names(far)}: no Daymet land cell lies within 1.5 km '
                     '(the app boundary rule), so the app would not run there.')
        listed |= set(far.id)
    nolc = nod[(nod.cover_code < 0) & ~nod.id.isin(listed)]
    if len(nolc):
        parts.append(f'All entries are nodata for {names(nolc)}: the 1 km cell has no NLCD land cover, '
                     'so the app has no default inputs.')
        listed |= set(nolc.id)
    off = places[(places.wrf_cesm_status != 'ok') & ~places.id.isin(listed)]
    if len(off):
        parts.append(f'WRF and CESM entries are nodata for {names(off)}: the place lies outside the 4 km grid.')
    for pid, msgs in (failures or {}).items():
        name = places.loc[places.id == pid, 'name'].iloc[0]
        for msg, dss in msgs.items():
            msg = msg.replace('"', "'")
            parts.append(f'{pid} {name}: DHSVM stopped for {len(dss)} dataset(s) with the message: {msg}. '
                         'The app would stop the same way for these inputs, so those entries are nodata.')
    parts.append('Daymet entries are nodata wherever Daymet forcing is unavailable, and for 1 to 12 hour durations.')
    return ' '.join(parts)


def axis_var(nc, name, values, encoding, long_name, dtype='i4'):
    v = nc.createVariable(name, dtype, (name,))
    v[:] = values
    v.long_name = long_name
    v.encoding = repr(encoding)
    return v


def build(args):
    places = pd.read_csv(args.places)
    defaults = pd.read_csv(args.defaults) if Path(args.defaults).exists() else None
    model = dict(l.split('=', 1) for l in Path(args.model_file).read_text().splitlines()
                 if '=' in l and not l.lstrip().startswith('#'))
    commit = model['APP_COMMIT']
    info = appinfo.app_info(args.app_dir)
    if info['commit'] != commit:
        raise SystemExit(f"app checkout is at {info['commit']}, model file says {commit}")
    g = info['get_idf']
    if g['distribution'].split()[0] != 'Gumbel' or not g['drops_first_am'] or len(g['ci_quantiles'] or []) != 2:
        raise SystemExit(f'app method differs from what the metadata text describes: {g}')
    ci, (qlo, qhi), nsim = g['ci_level_percent'], g['ci_quantiles'], g['bootstrap_samples']
    L, D, V, T, E = len(places), len(DATASETS), 2, len(DURATIONS), len(PROBS)
    mag = np.full((L, D, V, T, E), FILL, np.float32)
    lo, hi, mn, mx = (np.full_like(mag, FILL) for _ in range(4))
    NAM = 33
    A = len(AM_DATASETS)
    am_depth = np.full((L, A, V, T, NAM), FILL, np.float32)
    am_wy = np.full((L, A, V, T, NAM), -9999, np.int16)
    am_date = np.full((L, A, V, T, NAM), -9999, np.int32)
    am_mech = np.full((L, A, V, T, NAM), -9999, np.int16)
    am_used = np.full((L, A, V, T, NAM), -9999, np.int16)
    di = {k: i for i, (k, *_) in enumerate(DATASETS)}
    ai = {k: i for i, (k, *_) in enumerate(AM_DATASETS)}
    epoch = dt.date(1970, 1, 1)
    counts = {}
    for li, pid in enumerate(places.id):
        cache = {}
        for key, src, win, _ in DATASETS:
            if src is None:
                continue
            if src not in cache:
                cache[src] = load_run(args.runs_root, pid, src)
            r = cache[src]
            if r is None:
                continue
            counts[key] = counts.get(key, 0) + 1
            for vi, (vname, _) in VARIABLES.items():
                for ti, d in enumerate(DURATIONS):
                    k = f'{win}/IDF_{d}h_{vname}'
                    if k not in r.files:
                        continue
                    a = r[k]
                    ok = np.isfinite(a)
                    mag[li, di[key], vi, ti] = np.where(ok[0], a[0], FILL)
                    lo[li, di[key], vi, ti] = np.where(ok[1], a[1], FILL)
                    hi[li, di[key], vi, ti] = np.where(ok[2], a[2], FILL)
                    if key in ai:
                        am = r[f'{win}/am_{d}h_{vname}']
                        n = len(am)
                        am_depth[li, ai[key], vi, ti, :n] = am[:, 3]
                        for j in range(n):
                            y, m_, dd = int(am[j, 0]), int(am[j, 1]), int(am[j, 2])
                            am_date[li, ai[key], vi, ti, j] = (dt.date(y, m_, dd) - epoch).days
                            am_wy[li, ai[key], vi, ti, j] = y + 1 if m_ >= 10 else y
                            am_used[li, ai[key], vi, ti, j] = 0 if j == 0 else 1
                            if vname == 'W_veg':
                                am_mech[li, ai[key], vi, ti, j] = int(am[j, 7])
        # ensemble means (app: mean of member magnitudes, shading = member min/max)
        for key, period, win in ENSEMBLES:
            members = [di[f'CESM_{period}_LE{m}' + ('' if win == 'full' else '_nearterm')] for m in MEMBERS]
            stack = mag[li, members]  # (4, V, T, E)
            valid = (stack != FILL).all(axis=0)
            mean = stack.astype(np.float64).mean(axis=0)
            mag[li, di[key]] = np.where(valid, mean, FILL)
            mn[li, di[key]] = np.where(valid, stack.min(axis=0), FILL)
            mx[li, di[key]] = np.where(valid, stack.max(axis=0), FILL)
            if valid.any():
                counts[key] = counts.get(key, 0) + 1

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    loc_enc = {i: p for i, p in enumerate(places.id)}
    common = dict(
        method=METHOD.format(commit=commit, upstream=model['UPSTREAM_REPO'].removesuffix('.git'),
                             branch=model['UPSTREAM_BRANCH'], ci=ci, nsim=nsim),
        batch_adaptations=ADAPTATIONS, reproduced_app_behaviours=QUIRKS,
        app_source=(f"{model['UPSTREAM_REPO']} branch {model['UPSTREAM_BRANCH']} commit {commit} "
                    f"(fetched from the SNAP mirror {model['APP_REPO']} tag {model['APP_REF']}); "
                    f"model version {model['MODEL_LABEL']}: {model.get('MODEL_DESCRIPTION', '')}"),
        processing_code=f'github.com/ua-snap ng-idf_curation commit {git_rev()}',
        places_source='SNAP API, https://earthmaps.io/places/communities, region Alaska (565 places), snapshot 2026-11-17',
        nodata_locations=nodata_text(places, defaults, failed_runs(args.runs_root, places)),
        units='mm (depth over the duration); inches = mm / 25.4',
        creator='Scenarios Network for Alaska and Arctic Planning (SNAP), University of Alaska Fairbanks',
        date_created=dt.date.today().isoformat(),
    )

    with Dataset(out / 'ngidf_places.nc', 'w') as nc:
        for name, n in [('location', L), ('dataset', D), ('variable', V), ('duration', T), ('exceedance', E)]:
            nc.createDimension(name, n)
        axis_var(nc, 'location', np.arange(L), loc_enc, 'SNAP API place id')
        axis_var(nc, 'dataset', np.arange(D), {i: k for i, (k, *_) in enumerate(DATASETS)}, 'forcing dataset and window')
        axis_var(nc, 'variable', np.arange(V), {k: v[0] for k, v in VARIABLES.items()}, 'IDF variable')
        axis_var(nc, 'duration', np.arange(T), {i: d for i, d in enumerate(DURATIONS)}, 'duration (hours)')
        axis_var(nc, 'exceedance', np.arange(E), {i: p for i, p in enumerate(PROBS)},
                 'non-exceedance probability (return period = 1/(1-p) years)')
        dims = ('location', 'dataset', 'variable', 'duration', 'exceedance')
        for name, arr, ln in [('magnitude', mag, 'fitted depth (Gumbel L-moments)'),
                              ('ci_lower', lo, f'lower bound of the {ci:g} percent CI ({100 * qlo:g}th percentile of {nsim} bootstrap fits)'),
                              ('ci_upper', hi, f'upper bound of the {ci:g} percent CI ({100 * qhi:g}th percentile of {nsim} bootstrap fits)'),
                              ('member_min', mn, 'CESM ensemble rows only: minimum of the 4 member magnitudes'),
                              ('member_max', mx, 'CESM ensemble rows only: maximum of the 4 member magnitudes')]:
            v = nc.createVariable(name, 'f4', dims, zlib=True, complevel=4, fill_value=np.float32(FILL),
                                  chunksizes=(1, D, V, T, E))
            v[:] = arr
            v.long_name, v.units = ln, 'mm'
        nc.setncatts(dict(title='NG-IDF and precipitation IDF curves for Alaska places',
                          dataset_descriptions=json.dumps({k: d for k, _, _, d in DATASETS}),
                          variable_descriptions=json.dumps({v[0]: v[1] for v in VARIABLES.values()}),
                          **common))
        if defaults is not None:
            nc.setncattr('location_inputs', 'see ngidf_places_inputs.csv (lat, lon, forcing cells, land cover, LAI, height, defaults_source)')

    with Dataset(out / 'ngidf_places_am.nc', 'w') as nc:
        for name, n in [('location', L), ('dataset', A), ('variable', V), ('duration', T), ('am_index', NAM)]:
            nc.createDimension(name, n)
        axis_var(nc, 'location', np.arange(L), loc_enc, 'SNAP API place id')
        axis_var(nc, 'dataset', np.arange(A), {i: k for i, (k, *_) in enumerate(AM_DATASETS)}, 'forcing dataset (full period)')
        axis_var(nc, 'variable', np.arange(V), {k: v[0] for k, v in VARIABLES.items()}, 'IDF variable')
        axis_var(nc, 'duration', np.arange(T), {i: d for i, d in enumerate(DURATIONS)}, 'duration (hours)')
        axis_var(nc, 'am_index', np.arange(NAM), {i: i for i in range(NAM)}, 'position in the annual-maximum series')
        dims = ('location', 'dataset', 'variable', 'duration', 'am_index')
        for name, arr, typ, fill, ln, units in [
                ('am_depth', am_depth, 'f4', np.float32(FILL), 'water-year annual maximum depth', 'mm'),
                ('water_year', am_wy, 'i2', np.int16(-9999), 'water year of the annual maximum (Oct-Sep, labelled by the ending year)', '1'),
                ('peak_date', am_date, 'i4', np.int32(-9999), 'last day of the maximum window', 'days since 1970-01-01'),
                ('mechanism', am_mech, 'i2', np.int16(-9999), 'W_veg only: 1 rain, 2 snowmelt, 3 rain-on-snow (app classification)', '1'),
                ('used_in_fit', am_used, 'i2', np.int16(-9999), '1 if used in the Gumbel fit; the app drops the first value', '1')]:
            v = nc.createVariable(name, typ, dims, zlib=True, complevel=4, fill_value=fill, chunksizes=(1, A, V, T, NAM))
            v[:] = arr
            v.long_name, v.units = ln, units
        nc.setncatts(dict(title='Annual maxima behind the NG-IDF and precipitation IDF curves for Alaska places',
                          dataset_descriptions=json.dumps({k: d for k, _, _, d in AM_DATASETS}), **common))

    if defaults is not None:
        cols = ['id', 'name', 'latitude', 'longitude', 'wrf_key', 'wrf_dist_km', 'daymet_key', 'wrf_cesm_status', 'daymet_status']
        inp = places[[c for c in cols if c in places]].merge(defaults, on='id', how='left')
        inp.insert(0, 'location', np.arange(L))
        inp.to_csv(out / 'ngidf_places_inputs.csv', index=False)
    (out / 'build_summary.json').write_text(json.dumps(dict(counts=counts, commit=commit, ci_level_percent=ci,
                                                            ci_quantiles=[qlo, qhi], bootstrap_samples=nsim,
                                                            model_label=model['MODEL_LABEL'],
                                                            processing_commit=git_rev()), indent=2) + '\n')
    print(json.dumps(counts, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--places', default=str(REPO / 'data/places/places_ak.csv'))
    ap.add_argument('--defaults', default=str(REPO / 'data/places/place_defaults.csv'))
    ap.add_argument('--runs-root', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--app-dir', required=True, help='app checkout the runs used (method settings are read from it)')
    ap.add_argument('--model-file', default=str(REPO / 'config/model_versions/a582a5c.env'))
    build(ap.parse_args())


if __name__ == '__main__':
    main()
