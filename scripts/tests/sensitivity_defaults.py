"""How much do the curves move if LAI is off by ±0.1 or canopy height by ±2 m?
Runs a few Interior places on the author's own WRF_historical forcing with perturbed
defaults. Usage: sensitivity_defaults.py <out_root> <dhsvm_bin>"""
import itertools, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd
REPO = Path(__file__).resolve().parents[2]
DATA = Path('/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data'); APP = DATA / 'app/NG_IDF_AWS'
NGIDL = Path('/import/beegfs/CMIP6/arctic-cmip6/NG-IDL/dhsvm_wrf_1hour/hist')
CODES = dict(open=1, evergreen=2, deciduous=3, mixed=4, crop=5, grass=6, shrub=7, pasture=8, wetland=9)
out_root, dhsvm = Path(sys.argv[1]), sys.argv[2]
places = pd.read_csv(REPO / 'data/places/places_ak.csv', dtype={'wrf_key': str}).set_index('id')
table = pd.read_csv(APP / 'static/gridcell_current_lulc.csv')
cases = {'base': (0, 0), 'lai+0.1': (0.1, 0), 'lai-0.1': (-0.1, 0), 'h+2': (0, 2), 'h-2': (0, -2)}
jobs = []
for pid in ['AK62', 'AK563', 'AK100']:
    p = places.loc[pid]
    c = table[(table.latitude == p.defaults_lat) & (table.longitude == p.defaults_lon)].iloc[0]
    for name, (dl, dh) in cases.items():
        jobs.append((pid, name, [sys.executable, '-I', str(REPO / 'ngidf/run_point.py'), '--app-dir', str(APP), '--dhsvm-bin', dhsvm,
            '--forcing-type', 'WRF_historical', '--forcing-file', str(NGIDL / f'data_{p.wrf_key}'), '--cell-key', p.wrf_key,
            '--place-id', pid, '--lat', str(p.latitude), '--lon', str(p.longitude),
            '--cover', str(CODES[c.dominant_LULC.strip().lower()]), '--lai', str(c.max_LAI + dl),
            '--height', str(max(c.mean_height_m + dh, 0.1)), '--out', str(out_root / pid / name)]))
with ThreadPoolExecutor(8) as ex:
    for (pid, name, _), r in zip(jobs, ex.map(lambda j: subprocess.run(j[2], capture_output=True, text=True), jobs)):
        print(pid, name, r.returncode, r.stderr[-300:] if r.returncode else '', flush=True)
rows = []
for pid in ['AK62', 'AK563', 'AK100']:
    base = np.load(out_root / pid / 'base/result.npz')
    for name in cases:
        if name == 'base': continue
        r = np.load(out_root / pid / name / 'result.npz')
        for d, v in itertools.product(['1h', '24h', '72h'], ['P', 'W_veg']):
            b, x = base[f'full/IDF_{d}_{v}'][0], r[f'full/IDF_{d}_{v}'][0]
            rows.append(dict(place=pid, case=name, dur=d, var=v, pct_2yr=100 * (x[0] - b[0]) / b[0],
                             pct_100yr=100 * (x[49] - b[49]) / b[49]))
df = pd.DataFrame(rows)
pd.set_option('display.width', 200)
print(df.pivot_table(index=['place', 'case'], columns=['var', 'dur'], values='pct_100yr').round(2).to_string())
df.to_csv(out_root / 'sensitivity.csv', index=False)
