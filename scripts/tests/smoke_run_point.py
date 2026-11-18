"""Smoke test: run a few Interior places through ngidf/run_point.py on H. Yan's own forcing files
(NG-IDL), using H. Yan's own defaults table. Usage: smoke_run_point.py <out_root> <dhsvm_bin> [ids...]"""
import subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DATA = Path('/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data')
APP = DATA / 'app/NG_IDF_AWS'
NGIDL = Path('/import/beegfs/CMIP6/arctic-cmip6/NG-IDL')
AUTHOR_FORCING = {
    'Daymet': ('daymet_key', NGIDL / 'dhsvm_daymet_3hour'),
    'WRF_historical': ('wrf_key', NGIDL / 'dhsvm_wrf_1hour/hist'),
    'CESM_hist_LE2': ('wrf_key', NGIDL / 'dhsvm_cesm_1hour/hC2LE2'),
}
CODES = dict(open=1, evergreen=2, deciduous=3, mixed=4, crop=5, grass=6, shrub=7, pasture=8, wetland=9)

out_root, dhsvm_bin = Path(sys.argv[1]), sys.argv[2]
ids = sys.argv[3:] or ['AK62', 'AK563', 'AK124']
places = pd.read_csv(REPO / 'data/places/places_ak.csv', dtype={'wrf_key': str, 'daymet_key': str})
table = pd.read_csv(APP / 'static/gridcell_current_lulc.csv')
fails = 0
for pid in ids:
    p = places.set_index('id').loc[pid]
    cell = table[(table.latitude == p.defaults_lat) & (table.longitude == p.defaults_lon)].iloc[0]
    cover, lai, h = str(cell.dominant_LULC).strip().lower(), float(cell.max_LAI), float(cell.mean_height_m)
    if not np.isfinite(lai) or not np.isfinite(h):
        cover = 'open'
    for ft, (keycol, d) in AUTHOR_FORCING.items():
        key = p[keycol]
        cmd = [sys.executable, '-I', str(REPO / 'ngidf/run_point.py'), '--app-dir', str(APP), '--dhsvm-bin', dhsvm_bin,
               '--forcing-type', ft, '--forcing-file', str(d / f'data_{key}'), '--cell-key', key,
               '--place-id', pid, '--lat', str(p.latitude), '--lon', str(p.longitude), '--cover', str(CODES[cover]),
               '--lai', str(0 if cover == 'open' else lai), '--height', str(0 if cover == 'open' else h),
               '--out', str(out_root / pid / ft), '--keep-pixel']
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(pid, ft, cover, 'rc', r.returncode, r.stderr[-1500:] if r.returncode else '', flush=True)
        fails += r.returncode != 0
sys.exit(1 if fails else 0)
