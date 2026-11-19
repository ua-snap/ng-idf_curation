"""Daymet 3-hourly DHSVM station files, reproducing the author's NG-IDL/dhsvm_daymet_3hour.

Recipe (reverse-engineered from the author's files; see scripts/daymet/metsim_probe.py):
  * Daymet v4 R1 daily prcp, tmax, tmin for the 1 km cell (ORNL single-pixel API).
    Daymet omits Dec 31 in leap years: that day gets P = 0 and Tmax/Tmin = mean of Dec 30 and Jan 1.
  * Daily wind: mean of hourly WRF-historical wind speed (hypot(U10, V10), rounded to 4 dp as in the
    author's hourly files) over the WRF daily file (01-00 UTC) dated that day, at the 4 km cell
    nearest the Daymet cell by the app's unscaled-degree rule.
  * MetSim (MTCLIM), 180-minute step, uniform precipitation, defaults otherwise (local solar time),
    elevation = Daymet pixel elevation. 90 days of Daymet before the start as state.
  * RH = min(100 * vapor_pressure / (611.2 exp(17.67 T / (T + 243.5))), 99.99) from MetSim T and
    vapour pressure (Bolton, as in the author's WRF files).
  * Text: "MM/DD/YYYY-HH T W RH SW LW P", values as Python floats rounded to 4 dp (P in m, 6 dp).

Subcommands:
  wind      one Slurm task per year of WRF-historical files -> daily wind for all wind cells
  run       one Slurm task per slice of Daymet cells -> station files
  validate  compare with the author's files for shared cells
"""
import argparse
import datetime as dt
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
import pandas as pd

WRF_HIST = Path(os.environ.get('RAW_FORCING_ROOT', '/import/beegfs/CMIP6/arctic-cmip6/NG-IDL-Full-Forcing/whole_AK_forcing'),
                'WRF/historical/hsf')
NGIDL_DAYMET = Path(os.environ.get('AUTHOR_FORCING_ROOT', '/import/beegfs/CMIP6/arctic-cmip6/NG-IDL'), 'dhsvm_daymet_3hour')
START, STOP = '1989-06-01', '2021-09-30'


def wrf_files():
    out = []
    for name in os.listdir(WRF_HIST):
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})\.nc$', name)
        if m:
            out.append((dt.date(*map(int, m.groups())), WRF_HIST / name))
    return sorted(out)


def wind_cells(places_csv):
    """Daymet cell -> nearest WRF cell (app rule: unscaled squared degrees, 5-dp coordinates)."""
    from netCDF4 import Dataset
    p = pd.read_csv(places_csv, dtype={'daymet_key': str})
    keys = sorted(p.loc[p.daymet_status == 'ok', 'daymet_key'].unique())
    with Dataset(wrf_files()[0][1]) as d:
        xl = np.round(np.asarray(d['XLAT'][0], float), 5)
        xo = np.round(np.asarray(d['XLONG'][0], float), 5)
    rows = []
    for k in keys:
        la, lo = map(float, k.split('_'))
        i = int(np.argmin((xl - la) ** 2 + (xo - lo) ** 2))
        y, x = np.unravel_index(i, xl.shape)
        rows.append(dict(daymet_key=k, wind_y=int(y), wind_x=int(x), wind_key=f'{xl[y, x]:.5f}_{xo[y, x]:.5f}'))
    return pd.DataFrame(rows)


def _file_wind(args):
    path, ys, xs = args
    from netCDF4 import Dataset
    with Dataset(path) as d:
        # read whole slabs and index pointwise (netCDF4 [:, ys, xs] would be an orthogonal, outer-product index)
        u = np.asarray(d['U10'][:], dtype=np.float32)[:, ys, xs]
        v = np.asarray(d['V10'][:], dtype=np.float32)[:, ys, xs]
    hourly = np.round(np.hypot(u, v).astype(np.float64), 4)
    return np.round(hourly.mean(axis=0), 4)


def cmd_wind(args):
    cells = wind_cells(args.places)
    uniq = cells[['wind_y', 'wind_x']].drop_duplicates().reset_index(drop=True)
    files = wrf_files()
    years = sorted({d.year for d, _ in files})
    year = years[args.index]
    sel = [(d, p) for d, p in files if d.year == year]
    with ProcessPoolExecutor(args.workers) as ex:
        res = list(ex.map(_file_wind, [(p, uniq.wind_y.values, uniq.wind_x.values) for _, p in sel]))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    np.savez(out / f'wind_{year}.npz', dates=np.array([d.isoformat() for d, _ in sel]), wind=np.stack(res),
             wind_y=uniq.wind_y.values, wind_x=uniq.wind_x.values)
    cells.to_csv(out / 'wind_cells.csv', index=False)
    print(year, len(sel), 'days', len(uniq), 'cells')


def cmd_compact_wind(args):
    """Rewrite wind files from the first version (outer-product blocks) to per-cell series."""
    for f in sorted(Path(args.wind_dir).glob('wind_*.npz')):
        z = np.load(f)
        if z['wind'].ndim != 3:
            continue
        tmp = f.with_name(f.stem + '.tmp.npz')
        np.savez(tmp, dates=z['dates'], wind=np.ascontiguousarray(np.diagonal(z['wind'], axis1=1, axis2=2)),
                 wind_y=z['wind_y'], wind_x=z['wind_x'])
        os.replace(tmp, f)
        print('compacted', f.name, flush=True)


def load_wind(wind_dir):
    dates, vals, yx = [], [], None
    for f in sorted(Path(wind_dir).glob('wind_*.npz')):
        z = np.load(f)
        dates += list(z['dates'])
        w = z['wind']
        if w.ndim == 3:  # files from the first version held an outer-product block; cell i is its diagonal
            w = np.diagonal(w, axis1=1, axis2=2)
        vals.append(w)
        yx = list(zip(z['wind_y'], z['wind_x']))
    return pd.DataFrame(np.concatenate(vals), index=pd.to_datetime(dates), columns=pd.MultiIndex.from_tuples(yx))


def read_daymet(pixel_csv):
    lines = Path(pixel_csv).read_text().splitlines()
    elev = float([l for l in lines if l.startswith('Elevation')][0].split()[1])
    hdr = next(i for i, l in enumerate(lines) if l.startswith('year,'))
    dm = pd.read_csv(pixel_csv, skiprows=hdr)
    dm.columns = ['year', 'yday', 'dayl', 'prcp', 'srad', 'swe', 'tmax', 'tmin', 'vp']
    dm.index = pd.to_datetime(dm.year.astype(str)) + pd.to_timedelta(dm.yday - 1, unit='D')
    full = pd.date_range(dm.index.min(), dm.index.max() + pd.Timedelta(days=1), freq='D')
    dm = dm.reindex(full)
    dm['prcp'] = dm.prcp.fillna(0.0)  # leap-year Dec 31
    dm[['tmax', 'tmin']] = dm[['tmax', 'tmin']].interpolate()
    return dm, elev


def fmt(x):
    return repr(float(x))  # Python float text, as in the author's files (e.g. 3.8765, 0.0, 5.1e-05)


def build_cell(key, pixel_csv, wind_series, out_path, work_root):
    import xarray as xr
    from metsim import MetSim
    lat, lon = map(float, key.split('_'))
    dm, elev = read_daymet(pixel_csv)
    dm['wind'] = wind_series.reindex(dm.index)
    t0, t1 = pd.Timestamp(START), pd.Timestamp(STOP)
    run_days = pd.date_range(t0, t1, freq='D')
    if dm.loc[run_days, 'wind'].isna().any():
        raise ValueError(f'{key}: missing wind days')
    work = Path(tempfile.mkdtemp(prefix='msim_', dir=work_root))
    try:
        def ds_for(idx, with_wind):
            d = dm.loc[idx]
            v = {'prec': d.prcp, 't_max': d.tmax, 't_min': d.tmin}
            if with_wind:
                v['wind'] = d.wind
            return xr.Dataset({k: (('time', 'lat', 'lon'), s.values.reshape(-1, 1, 1).astype('f8')) for k, s in v.items()},
                              coords={'time': idx, 'lat': [lat], 'lon': [lon]})
        ds_for(run_days, True).to_netcdf(work / 'forcing.nc')
        ds_for(pd.date_range(t0 - pd.Timedelta(days=90), t0 - pd.Timedelta(days=1), freq='D'), False).to_netcdf(work / 'state.nc')
        xr.Dataset({'elev': (('lat', 'lon'), [[elev]]), 'mask': (('lat', 'lon'), [[1]])},
                   coords={'lat': [lat], 'lon': [lon]}).to_netcdf(work / 'domain.nc')
        (work / 'out').mkdir()
        params = dict(time_step='180', start=START, stop=STOP, forcing=str(work / 'forcing.nc'),
                      domain=str(work / 'domain.nc'), state=str(work / 'state.nc'), forcing_fmt='netcdf',
                      out_dir=str(work / 'out'), out_prefix='ms', scheduler='synchronous', prec_type='uniform',
                      forcing_vars={'prec': 'prec', 't_max': 't_max', 't_min': 't_min', 'wind': 'wind'},
                      state_vars={'prec': 'prec', 't_max': 't_max', 't_min': 't_min'},
                      domain_vars={'lat': 'lat', 'lon': 'lon', 'mask': 'mask', 'elev': 'elev'},
                      out_vars={'temp': {'out_name': 'temp'}, 'prec': {'out_name': 'prec'},
                                'shortwave': {'out_name': 'shortwave'}, 'longwave': {'out_name': 'longwave'},
                                'wind': {'out_name': 'wind'}, 'vapor_pressure': {'out_name': 'vapor_pressure'}},
                      chunks={'lat': 1, 'lon': 1})
        MetSim(params).run()
        o = xr.open_mfdataset(str(work / 'out/*.nc')).isel(lat=0, lon=0).to_dataframe()
        t = o.temp.values.astype(np.float64)
        rh = np.minimum(100 * o.vapor_pressure.values * 1000 / (611.2 * np.exp(17.67 * t / (t + 243.5))), 99.99)
        tmp = Path(str(out_path) + '.tmp')
        with open(tmp, 'w') as f:
            f64 = lambda col: o[col].values.astype(np.float64)  # MetSim returns float32; round in float64
            for ts, a, w, r, sw, lw, p in zip(o.index, t, f64('wind'), rh, f64('shortwave'),
                                               f64('longwave'), f64('prec')):
                f.write(f"{ts.strftime('%m/%d/%Y-%H')} {fmt(round(a, 4))} {fmt(round(w, 4))} {fmt(round(r, 4))} "
                        f"{fmt(round(sw, 4))} {fmt(round(lw, 4))} {fmt(round(p / 1000.0, 6))}\n")
        os.replace(tmp, out_path)
        return dict(key=key, elev=elev, steps=len(o))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _build(a):
    try:
        return build_cell(*a)
    except Exception as e:
        return dict(key=a[0], error=repr(e))


def cmd_run(args):
    cells = pd.read_csv(Path(args.wind_dir) / 'wind_cells.csv')
    wind = load_wind(args.wind_dir)
    part = cells.iloc[args.task::args.ntasks]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for r in part.itertuples(index=False):
        dst = out / f'data_{r.daymet_key}'
        if dst.exists() and not args.overwrite:
            continue
        jobs.append((r.daymet_key, Path(args.pixel_dir) / f'pix_{r.daymet_key}.csv', wind[(r.wind_y, r.wind_x)],
                     dst, args.work_root))
    print(f'task {args.task}/{args.ntasks}: {len(jobs)} cells', flush=True)
    fails = 0
    with ProcessPoolExecutor(args.workers) as ex:
        for res in ex.map(_build, jobs):
            print(json.dumps(res), flush=True)
            fails += 'error' in res
    raise SystemExit(1 if fails else 0)


def cmd_validate(args):
    ours = sorted(Path(args.ours_dir).glob('data_*'))
    shared = [p for p in ours if (NGIDL_DAYMET / p.name).exists()]
    cols = ['t', 'T', 'W', 'RH', 'SW', 'LW', 'P']
    rows = []
    for p in shared:
        a_txt = p.read_text().splitlines()
        b_txt = (NGIDL_DAYMET / p.name).read_text().splitlines()
        a = pd.read_csv(p, sep=' ', header=None, names=cols)
        b = pd.read_csv(NGIDL_DAYMET / p.name, sep=r'\s+', header=None, names=cols)
        m = a.merge(b, on='t', suffixes=('', '_ref'))
        r = dict(cell=p.name, n=len(a), n_ref=len(b), text_identical_lines=float(np.mean([x == y for x, y in zip(a_txt, b_txt)])))
        for c in cols[1:]:
            r[f'{c}_max'] = float((m[c] - m[c + '_ref']).abs().max())
        rows.append(r)
    df = pd.DataFrame(rows)
    pd.set_option('display.width', 250)
    print(df.to_string())
    print(df.drop(columns='cell').agg(['min', 'median', 'max']).to_string())
    if args.json:
        expected = None
        if args.places:
            pl = pd.read_csv(args.places)
            expected = int(pl.loc[pl.daymet_status == 'ok', 'daymet_key'].nunique())
        summ = dict(cells=len(df))
        for c in cols[1:]:
            summ[f'{c}_max'] = float(df[f'{c}_max'].max()) if len(df) else None
            summ[f'{c}_median'] = float(df[f'{c}_max'].median()) if len(df) else None
            summ[f'{c}_cells_differ'] = int((df[f'{c}_max'] > (1.01e-6 if c == 'P' else 1.01e-4)).sum()) if len(df) else None
        Path(args.json).write_text(json.dumps(dict(ours_dir=str(args.ours_dir), ref_dir=str(NGIDL_DAYMET),
                                                   expected_cells=expected, summary=summ,
                                                   cells=df.to_dict('records')), indent=1) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    w = sub.add_parser('wind')
    w.add_argument('--places', required=True)
    w.add_argument('--index', type=int, required=True)
    w.add_argument('--out-dir', required=True)
    w.add_argument('--workers', type=int, default=8)
    w.set_defaults(func=cmd_wind)
    r = sub.add_parser('run')
    r.add_argument('--wind-dir', required=True)
    r.add_argument('--pixel-dir', required=True)
    r.add_argument('--out-dir', required=True)
    r.add_argument('--task', type=int, default=0)
    r.add_argument('--ntasks', type=int, default=1)
    r.add_argument('--workers', type=int, default=8)
    r.add_argument('--work-root', default=os.environ.get('TMPDIR', '/tmp'))
    r.add_argument('--overwrite', action='store_true')
    r.set_defaults(func=cmd_run)
    c = sub.add_parser('compact-wind')
    c.add_argument('--wind-dir', required=True)
    c.set_defaults(func=cmd_compact_wind)
    v = sub.add_parser('validate')
    v.add_argument('--ours-dir', required=True)
    v.add_argument('--json', help='also write the comparison as JSON (pipeline report)')
    v.add_argument('--places', help='place table, to record the expected number of station files')
    v.set_defaults(func=cmd_validate)
    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
