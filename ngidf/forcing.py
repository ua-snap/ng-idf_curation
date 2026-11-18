"""Extract WRF/CESM hourly forcing for the Phase 1 cells without writing per-cell files
for the whole grid.

Two steps:

  block     One Slurm array task per (dataset, calendar year of files). Reads each
            daily file once (each variable is stored as one full-grid chunk per hour,
            so we decompress the whole slab anyway) and keeps only the selected cells.
            Writes raw values, float32 as stored, to a small .npz.
  assemble  Per dataset: concatenates the blocks, converts to DHSVM units the way
            H. Yan did for NG-IDL/dhsvm_{wrf,cesm}_1hour, and writes one station file
            per cell in his format ("MM/DD/YYYY-HH T wind RH SW LW P", AK local time).

Conversions (validated against the author's NG-IDL station files with `validate`):
  T   = T2 - 273.15                                   (C)
  W   = hypot(U10, V10)                               (m/s)
  RH  = min(100 e/es, 99.99), e = Q2*PSFC/(0.622 + 0.378*Q2), es = 611.2 exp(17.67 T/(T+243.5))  (%)
  SW  = SWDNB, LW = GLW                               (W/m2)
  P   = hourly diff of RAINC + RAINNC + 100*(I_RAINC + I_RAINNC), mm -> m
  time = UTC - 9 h. CESM (no-leap): Feb 29 UTC is inserted before the shift (details in assemble).
"""
import argparse
import datetime as dt
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import re

import numpy as np

RAW_ROOT = Path('/import/beegfs/CMIP6/arctic-cmip6/NG-IDL-Full-Forcing/whole_AK_forcing')
DATASETS = {
    'WRF_historical': 'WRF/historical/hsf',
    'WRF_medium': 'WRF/pgw_medium/hsf',
    'WRF_high': 'WRF/pgw_high/hsf',
    **{f'CESM_{period}_LE{m}': f'CESM2-LE/cesm2le/{p}C2LE{m}/hsf'
       for period, p in [('hist', 'h'), ('futu', 'f')] for m in (2, 4, 7, 9)},
}
VARS = ['T2', 'U10', 'V10', 'Q2', 'PSFC', 'SWDNB', 'GLW', 'RAINC', 'RAINNC', 'I_RAINC', 'I_RAINNC']
UTC_OFFSET_H = -9
BUCKET_MM = 100.0


def daily_files(dataset):
    d = RAW_ROOT / DATASETS[dataset]
    out = []
    for name in os.listdir(d):
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})\.nc$', name)
        if m:
            out.append((dt.date(*map(int, m.groups())), d / name))
    out.sort()
    return out


def read_file(args):
    path, ys, xs = args
    from netCDF4 import Dataset, chartostring
    with Dataset(path) as ds:
        times = [str(t) for t in chartostring(ds['Times'][:])]
        vals = np.empty((len(VARS), len(times), len(ys)), dtype=np.float32)
        for i, v in enumerate(VARS):
            a = ds[v][:]
            if np.ma.isMaskedArray(a):
                a = a.filled(np.nan)
            vals[i] = a[:, ys, xs]
    return times, vals


def cmd_block(args):
    import pandas as pd
    places = pd.read_csv(args.places)
    cells = (places.dropna(subset=['forcing_cell_index'])
             .drop_duplicates('forcing_cell_index').sort_values('forcing_cell_index'))
    ys, xs = cells.wrf_y.to_numpy(int), cells.wrf_x.to_numpy(int)
    files = daily_files(args.dataset)
    years = sorted({d.year for d, _ in files})
    year = years[args.index]
    sel = [p for d, p in files if d.year == year]
    # The last file of the previous year supplies the accumulated precip before this block.
    prev = [p for d, p in files if d.year == year - 1][-1:]
    jobs = [(p, ys, xs) for p in prev + sel]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        res = list(ex.map(read_file, jobs, chunksize=1))
    times = [t for r in res for t in r[0]]
    vals = np.concatenate([r[1] for r in res], axis=1)
    out = Path(args.out_dir) / args.dataset
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f'block_{year}.tmp.npz'
    # Source variables are float32; the int32 bucket counters are small (<2**24), so float32 holds them exactly.
    np.savez(tmp, times=np.array(times), vals=vals, n_prev=len(res[0][0]) if prev else 0,
             cell_index=cells.forcing_cell_index.to_numpy(int), ys=ys, xs=xs)
    os.replace(tmp, out / f'block_{year}.npz')
    print(f'{args.dataset} {year}: {len(sel)} files, {len(times)} hours, {len(ys)} cells')


def n_blocks(dataset):
    return len({d.year for d, _ in daily_files(dataset)})


# ----------------------------------------------------------------------------- assemble

def load_blocks(block_dir, years=None):
    """Concatenate block files in time order. Drops each block's look-back hours
    (they duplicate the previous block), so the series is continuous."""
    files = sorted(Path(block_dir).glob('block_*.npz'), key=lambda p: int(p.stem.split('_')[1]))
    if years is not None:
        files = [f for f in files if int(f.stem.split('_')[1]) in years]
    times, vals, meta = [], [], None
    for i, f in enumerate(files):
        z = np.load(f)
        k = int(z['n_prev']) if i > 0 else 0
        times.append(z['times'][k:])
        vals.append(z['vals'][:, k:, :])
        if meta is None:
            meta = dict(cell_index=z['cell_index'], ys=z['ys'], xs=z['xs'])
    times = np.concatenate(times)
    vals = np.concatenate(vals, axis=1)
    return times, vals, meta


def convert(vals):
    """Raw float32 values [var, hour, cell] -> DHSVM fields [hour, cell, 6], float32
    arithmetic as in the author's files, rounded to 4 dp (T, W, RH, SW, LW).
    Precipitation (m) is returned unrounded; the first hour has P = 0."""
    v = {name: vals[i] for i, name in enumerate(VARS)}
    f32 = np.float32
    t = v['T2'] - f32(273.15)
    w = np.hypot(v['U10'], v['V10'])
    q, ps = v['Q2'], v['PSFC']
    e = q * ps / (f32(0.622) + f32(0.378) * q)
    es = f32(611.2) * np.exp(f32(17.67) * t / (t + f32(243.5)))
    rh = np.minimum(f32(100.0) * e / es, f32(99.99))  # the author's files cap RH at 99.99
    acc = (v['RAINC'].astype(np.float64) + v['RAINNC'] + BUCKET_MM * (v['I_RAINC'] + v['I_RAINNC']))
    p = np.diff(acc, axis=0, prepend=acc[:1]) / 1000.0
    out = np.empty(t.shape + (6,), dtype=np.float64)
    for j, a in enumerate([t, w, rh, v['SWDNB'], v['GLW']]):
        out[..., j] = np.round(a.astype(np.float64), 4)
    out[..., 5] = p
    return out


def to_gregorian_local(times, fields, noleap):
    """UTC strings + fields -> (local datetimes, fields). For CESM (no-leap), insert
    Feb 29 00..23 UTC as the mean of the rounded Feb 28 and Mar 1 values at the same
    hour, with zero precipitation, then shift to AK local time (UTC-9)."""
    utc = [dt.datetime.strptime(s, '%Y-%m-%d_%H:%M:%S') for s in times]
    if noleap:
        pieces, stamps = [], []
        idx = {s: i for i, s in enumerate(utc)}
        start = 0
        for year in sorted({u.year for u in utc}):
            if not (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
                continue
            f28 = [idx.get(dt.datetime(year, 2, 28, h)) for h in range(24)]
            m01 = [idx.get(dt.datetime(year, 3, 1, h)) for h in range(24)]
            if None in f28 or None in m01:
                continue
            cut = f28[-1] + 1  # first record after Feb 28 23 UTC
            pieces.append(fields[start:cut]); stamps.extend(utc[start:cut])
            ins = (fields[f28] + fields[m01]) / 2.0
            ins[..., 5] = 0.0
            pieces.append(ins); stamps.extend(dt.datetime(year, 2, 29, h) for h in range(24))
            start = cut
        pieces.append(fields[start:]); stamps.extend(utc[start:])
        fields = np.concatenate(pieces, axis=0)
        utc = stamps
    local = [u + dt.timedelta(hours=UTC_OFFSET_H) for u in utc]
    steps = np.diff(np.array(local, dtype='datetime64[h]')).astype(int)
    if not (steps == 1).all():
        bad = np.nonzero(steps != 1)[0][:5]
        raise ValueError(f'non-hourly series after calendar handling at {[local[i] for i in bad]}')
    return local, fields


def write_station(path, local, fields):
    stamps = [t.strftime('%m/%d/%Y-%H') for t in local]
    tmp = Path(str(path) + '.tmp')
    with open(tmp, 'w') as f:
        for s, row in zip(stamps, fields):
            f.write(f'{s} {row[0]:.6f} {row[1]:.6f} {row[2]:.6f} {row[3]:.6f} {row[4]:.6f} {row[5]:.6f}\n')
    os.replace(tmp, path)


def _write_one(args):
    path, local, fields = args
    write_station(path, local, fields)
    return str(path)


def cmd_assemble(args):
    import pandas as pd
    places = pd.read_csv(args.places, dtype={'wrf_key': str})
    keys = (places.dropna(subset=['forcing_cell_index']).drop_duplicates('forcing_cell_index')
            .set_index('forcing_cell_index').wrf_key)
    times, vals, meta = load_blocks(Path(args.block_dir) / args.dataset)
    fields = convert(vals)
    del vals
    local, fields = to_gregorian_local(times, fields, args.dataset.startswith('CESM_'))
    out = Path(args.out_dir) / args.dataset
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(out / f'data_{keys[int(ci)]}', local, fields[:, j, :]) for j, ci in enumerate(meta['cell_index'])]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for _ in ex.map(_write_one, jobs, chunksize=4):
            pass
    summary = dict(dataset=args.dataset, cells=len(jobs), hours=len(local),
                   first=local[0].strftime('%m/%d/%Y-%H'), last=local[-1].strftime('%m/%d/%Y-%H'))
    (out / 'SUCCESS.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(summary)


def cmd_validate(args):
    """Compare our station files against the author's NG-IDL files for shared cells."""
    import pandas as pd
    ref_dir = Path(args.ref_dir)
    ours = sorted(Path(args.ours_dir).glob('data_*'))
    shared = [p for p in ours if (ref_dir / p.name).exists()]
    cols = ['t', 'T', 'W', 'RH', 'SW', 'LW', 'P']
    rows = []
    for p in shared[:args.max_cells]:
        a = pd.read_csv(p, sep=' ', header=None, names=cols, dtype={'t': str})
        b = pd.read_csv(ref_dir / p.name, sep=r'\s+', header=None, names=cols, dtype={'t': str})
        m = a.merge(b, on='t', suffixes=('', '_ref'))
        r = dict(cell=p.name, n_ours=len(a), n_ref=len(b), n_shared=len(m))
        for c in cols[1:]:
            d = (m[c] - m[c + '_ref']).abs()
            r[f'{c}_max'] = float(d.max())
            r[f'{c}_n_gt_1e-4'] = int((d > 1.01e-4).sum()) if c != 'P' else int((d > 1.01e-6).sum())
        rows.append(r)
    df = pd.DataFrame(rows)
    pd.set_option('display.width', 250)
    print(df.to_string())
    print(df.drop(columns='cell').agg(['max']).to_string())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('block')
    b.add_argument('--dataset', required=True, choices=list(DATASETS))
    b.add_argument('--index', type=int, required=True, help='0-based year index (Slurm array id)')
    b.add_argument('--places', required=True)
    b.add_argument('--out-dir', required=True)
    b.add_argument('--workers', type=int, default=8)
    b.set_defaults(func=cmd_block)
    n = sub.add_parser('nblocks')
    n.add_argument('--dataset', required=True, choices=list(DATASETS))
    n.set_defaults(func=lambda a: print(n_blocks(a.dataset)))
    s = sub.add_parser('assemble')
    s.add_argument('--dataset', required=True, choices=list(DATASETS))
    s.add_argument('--places', required=True)
    s.add_argument('--block-dir', required=True)
    s.add_argument('--out-dir', required=True)
    s.add_argument('--workers', type=int, default=8)
    s.set_defaults(func=cmd_assemble)
    v = sub.add_parser('validate')
    v.add_argument('--ours-dir', required=True)
    v.add_argument('--ref-dir', required=True)
    v.add_argument('--max-cells', type=int, default=1000)
    v.set_defaults(func=cmd_validate)
    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
