"""Reference runs (pipeline stage `reference`): a few Interior places run on H. Yan's own inputs.

For each place and dataset, run ngidf/run_point.py with
  * his forcing files (NG-IDL/dhsvm_*), and
  * the defaults of his table (static/gridcell_current_lulc.csv) at the place's 1 km cell, with the
    app's rules (missing LAI or height -> open; open -> LAI = height = 0),
so only our batch wrapper and our DHSVM build differ from his app. If he has sent output from his app
for these points (PLAN.md Appendix E/F), it is compared value by value:

  <hy_reference>/<place_id>/<dataset>/IDF_<dur>_P and IDF_<dur>_W_veg   (rows: magnitude, CI low, CI high)

The fitted magnitudes do not depend on the bootstrap seed, so they must agree to the 0.01 mm rounding.
The CI rows are compared too, but differ by Monte Carlo noise (different seeds).

Also reads the Pixel.CENTER header of one run and checks the columns extract_AM.py reads.
Writes <out>/reference.json.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'ngidf'))
import appinfo  # noqa: E402

FORCING = {  # dataset -> (place-table key column, author's directory under NG-IDL)
    'Daymet': ('daymet_key', 'dhsvm_daymet_3hour'),
    'WRF_historical': ('wrf_key', 'dhsvm_wrf_1hour/hist'),
    'WRF_medium': ('wrf_key', 'dhsvm_wrf_1hour/medium'),
    'WRF_high': ('wrf_key', 'dhsvm_wrf_1hour/high'),
    **{f'CESM_{p}_LE{m}': ('wrf_key', f'dhsvm_cesm_1hour/{p[0]}C2LE{m}') for p in ('hist', 'futu') for m in (2, 4, 7, 9)},
}
CODES = dict(open=1, evergreen=2, deciduous=3, mixed=4, crop=5, grass=6, shrub=7, pasture=8, wetland=9)


def author_defaults(table, lat, lon):
    cell = table[(table.latitude == lat) & (table.longitude == lon)]
    if cell.empty:
        raise ValueError(f'{lat},{lon} not in the author table')
    cell = cell.iloc[0]
    cover, lai, h = str(cell.dominant_LULC).strip().lower(), float(cell.max_LAI), float(cell.mean_height_m)
    if not np.isfinite(lai) or not np.isfinite(h):
        cover = 'open'
    if cover == 'open':
        lai = h = 0.0
    return cover, lai, h


def compare(npz, ref_dir, durations):
    """Max |difference| between our rounded IDF arrays and his IDF files."""
    worst_mag, worst_ci, n = 0.0, 0.0, 0
    for d in durations:
        for v in ('P', 'W_veg'):
            f = ref_dir / f'IDF_{d}_{v}'
            if not f.exists():
                continue
            ref = np.round(np.loadtxt(f, ndmin=2), 2)
            ours = npz[f'full/IDF_{d}_{v}']
            worst_mag = max(worst_mag, float(np.nanmax(np.abs(ours[0] - ref[0]))))
            worst_ci = max(worst_ci, float(np.nanmax(np.abs(ours[1:] - ref[1:]) / np.maximum(np.abs(ref[1:]), 1e-9))))
            n += 1
    return dict(files=n, magnitude_max_abs_mm=round(worst_mag, 4), ci_max_rel=round(worst_ci, 4)) if n else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--app-dir', required=True)
    ap.add_argument('--dhsvm-bin', required=True)
    ap.add_argument('--places', required=True)
    ap.add_argument('--author-forcing-root', required=True)
    ap.add_argument('--hy-reference', required=True)
    ap.add_argument('--ids', nargs='+', required=True)
    ap.add_argument('--datasets', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--work-root', default='/tmp')
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    out, app, hy = Path(a.out), Path(a.app_dir), Path(a.hy_reference)
    places = pd.read_csv(a.places, dtype={'wrf_key': str, 'daymet_key': str}).set_index('id')
    table = pd.read_csv(app / 'static/gridcell_current_lulc.csv')

    jobs = []
    for i, pid in enumerate(a.ids):
        p = places.loc[pid]
        cover, lai, h = author_defaults(table, p.defaults_lat, p.defaults_lon)
        for ds in a.datasets:
            keycol, sub = FORCING[ds]
            key = p[keycol]
            run_dir = out / 'runs' / pid / ds
            cmd = [sys.executable, '-I', str(REPO / 'ngidf/run_point.py'), '--app-dir', str(app),
                   '--dhsvm-bin', a.dhsvm_bin, '--forcing-type', ds,
                   '--forcing-file', str(Path(a.author_forcing_root) / sub / f'data_{key}'), '--cell-key', key,
                   '--place-id', pid, '--lat', repr(float(p.latitude)), '--lon', repr(float(p.longitude)),
                   '--cover', str(CODES[cover]), '--lai', repr(lai), '--height', repr(h), '--out', str(run_dir),
                   '--work-root', a.work_root]
            if i == 0:
                cmd.append('--keep-pixel')
            jobs.append((pid, str(p['name']), ds, cover, lai, h, key, run_dir, cmd))

    def run(job):
        pid, name, ds, cover, lai, h, key, run_dir, cmd = job
        r = subprocess.run(cmd, capture_output=True, text=True)
        res = dict(place_id=pid, name=name, dataset=ds, cover=cover, lai=lai, height_m=h, forcing_cell=key,
                   status='ok' if r.returncode == 0 else 'failed', dir=str(run_dir))
        if r.returncode:
            res['error'] = r.stderr[-1500:]
            return res
        z = np.load(run_dir / 'result.npz')
        rj = json.loads((run_dir / 'run.json').read_text())
        durs = rj['durations']
        res['seconds'] = rj.get('seconds')
        d24 = '24h'
        res['p100_24h_P_mm'] = float(z[f'full/IDF_{d24}_P'][0, 49])     # p = 0.99 -> 100 yr
        res['p100_24h_W_veg_mm'] = float(z[f'full/IDF_{d24}_W_veg'][0, 49])
        res['am_years_used'] = int(len(z[f'full/am_{d24}_P']) - 1)
        res['compare'] = compare(z, hy / pid / ds, durs)
        return res

    with ThreadPoolExecutor(a.workers) as ex:
        runs = list(ex.map(run, jobs))
    report = dict(places=a.ids, datasets=a.datasets, hy_reference=str(hy), hy_reference_present=hy.exists(),
                  runs=runs)
    pix = next((Path(j[7]) / 'Pixel.CENTER.gz' for j in jobs if (Path(j[7]) / 'Pixel.CENTER.gz').exists()), None)
    if pix:
        cols = appinfo.parse_extract_am((app / 'extract_AM.py').read_text())['pixel_columns']
        report['pixel_header_check'] = appinfo.check_pixel_header(appinfo.read_header(pix), cols)
    (out / 'reference.json').write_text(json.dumps(report, indent=1) + '\n')
    bad = [r for r in runs if r['status'] != 'ok']
    print(f'{len(runs) - len(bad)} of {len(runs)} reference runs ok')
    for r in runs:
        print(r['place_id'], r['dataset'], r['cover'], r['status'], r.get('p100_24h_W_veg_mm'), r.get('compare'))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
