"""Run one place × forcing dataset through H. Yan's NG-IDF app code (pinned commit).

This mirrors the non-UI path of `app.py:get_NG_IDF` line by line:

    generate_ng_idf(bas_par, adv_par, td, met_path, forcing_type)   # dhsvm_idf.py
    dos2unix <config>; ./dhsvm/no_sat_dump/DHSVM3.2 <config>
    copy get_IDF.R -> td
    extract_AM_data(pixel_file, am_files_dict, r_file, td, forcing_type, year_range)   # runs R
    read IDF_<dur>_{P,W_veg} (3 x 51), np.round(..., 2)

We do not reimplement any of the science. The app modules are imported from the
pinned checkout and run with a per-run "shim" working directory, because they
read their inputs from relative paths (./example_config, ./static, ./met, ./input).
The shim differs from the app's own directory in these batch adaptations only:

* static/{wrf_cesm,daymet}_coordinates.txt holds the one cell already chosen by the
  app's own nearest-cell rule (scripts/places/build_place_table.py), so
  find_lat_lon() returns it.
* example_config/param_5cluster_ensembleMean_CONUS.csv gets one extra row for that
  cell with the Alaska snow parameters, so find_snow_param()'s exact-match lookup
  succeeds. All Alaska rows in the shipped file are identical.
* met/<forcing_type>/data_<lat>_<lon> links to our forcing file.
* dhsvm/no_sat_dump/DHSVM3.2 links to DHSVM built from the pinned source.
* get_IDF.R: the hard-coded `lib.loc='/hongxiang/app/Rlibrary'` is dropped (lmom is
  in the R library of our environment) and `set.seed(<seed>)` is prepended so the
  bootstrap CI is reproducible. Nothing else in the script changes.

The UI round-trip is reproduced too: the form holds lat/lon to 5 dp, LAI to 2 dp, and
height in feet to 2 dp, which app.py converts back with * 0.3048.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

import numpy as np

ADVANCED_DEFAULTS = [0.001, 0.005, 0.02, 0.6]  # NG_IDF.html applyGridcellDefaults
NUM_PROB = 51
HOURLY_DURATIONS = ['1h', '3h', '6h', '12h', '24h', '48h', '72h']
DAYMET_DURATIONS = ['24h', '48h', '72h']
# CESM near-term windows, app.py (CESM Near-Term branch)
NEAR_TERM = {'hist': ((2005, 1, 1), (2021, 9, 30)), 'futu': ((2033, 1, 1), (2049, 9, 30))}


def ui_round_trip(lat, lon, lai, height_m, cover_code):
    """Values exactly as the app's form would submit them for a clicked point."""
    lat, lon = float(f'{lat:.5f}'), float(f'{lon:.5f}')
    if cover_code == 1:
        lai, height_m = 0.0, 0.0
    lai = round(lai, 2)  # /api/gridcell-lulc returns round(lai, 2)
    height_ft = float(f'{round(height_m, 2) * 3.28084:.2f}')  # (gridcell.height * 3.28084).toFixed(2)
    return lat, lon, lai, height_ft * 0.3048  # app.py: input_data['value4'] *= 0.3048


def seed_for(*parts):
    return zlib.crc32('|'.join(map(str, parts)).encode()) & 0x7FFFFFFF


def alaska_snow_values(app_dir):
    """Text of the snow-parameter columns shared by every Alaska row (lat >= 50)."""
    rows = set()
    for line in (app_dir / 'example_config/param_5cluster_ensembleMean_CONUS.csv').read_text().splitlines():
        parts = line.strip().split(',')
        if len(parts) == 8 and float(parts[0]) >= 50:
            rows.add(','.join(parts[2:]))
    if len(rows) != 1:
        raise ValueError(f'Alaska snow rows are not unique: {rows}')
    return rows.pop()


def build_shim(shim, app_dir, dhsvm_bin, forcing_type, cell_key, forcing_file, seed):
    (shim / 'dhsvm/no_sat_dump').mkdir(parents=True)
    os.symlink(dhsvm_bin, shim / 'dhsvm/no_sat_dump/DHSVM3.2')
    shutil.copytree(app_dir / 'input', shim / 'input')
    shutil.copytree(app_dir / 'example_config', shim / 'example_config')
    lat_s, lon_s = cell_key.split('_')
    snow_csv = shim / 'example_config/param_5cluster_ensembleMean_CONUS.csv'
    text = snow_csv.read_text()
    with open(snow_csv, 'a') as f:
        f.write(('' if text.endswith('\n') else '\n') + f'{lat_s},{lon_s},{alaska_snow_values(app_dir)}\n')
    (shim / 'static').mkdir()
    coord_name = 'daymet_coordinates.txt' if forcing_type == 'Daymet' else 'wrf_cesm_coordinates.txt'
    (shim / 'static' / coord_name).write_text(f'{lat_s}, {lon_s}\n')
    met_dir = shim / 'met' / forcing_type
    met_dir.mkdir(parents=True)
    os.symlink(Path(forcing_file).resolve(), met_dir / f'data_{cell_key}')
    r = (app_dir / 'get_IDF.R').read_text()
    pattern = "library(lmom, lib.loc='/hongxiang/app/Rlibrary')"
    if r.count(pattern) != 1:
        raise ValueError('get_IDF.R lib.loc line not found; app version changed?')
    r = r.replace(pattern, 'library(lmom)')
    (shim / 'get_IDF.R').write_text(f'set.seed({seed})  # ngidf batch adaptation\n' + r)


def read_idf(path):
    """app.py read_idf + np.round(…, 2)."""
    data = np.full((3, NUM_PROB), np.nan)
    if path.exists():
        for i, line in enumerate(path.read_text().splitlines()):
            for k, v in enumerate(line.split()):
                data[i, k] = float(v)
    return np.round(data, 2)


def run(args):
    app_dir = Path(args.app_dir).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    forcing_type = args.forcing_type
    durations = DAYMET_DURATIONS if forcing_type == 'Daymet' else HOURLY_DURATIONS
    lat, lon, lai, height = ui_round_trip(args.lat, args.lon, args.lai, args.height, args.cover)
    bas_par = np.array([lat, lon, lai, height, 1.0, float(args.cover)])
    adv_par = np.array(ADVANCED_DEFAULTS)

    windows = {'full': None}
    if forcing_type.startswith('CESM_'):
        windows['near'] = NEAR_TERM['hist' if '_hist_' in forcing_type else 'futu']

    work_root = Path(args.work_root or os.environ.get('TMPDIR', '/tmp'))
    shim = Path(tempfile.mkdtemp(prefix='ngidf_', dir=work_root))
    log = io.StringIO()
    t0 = time.time()
    result = dict(place_id=args.place_id, forcing_type=forcing_type, cell_key=args.cell_key,
                  bas_par=bas_par.tolist(), adv_par=adv_par.tolist(), durations=durations)
    try:
        seeds = {w: seed_for(args.place_id, forcing_type, w) for w in windows}
        build_shim(shim, app_dir, Path(args.dhsvm_bin).resolve(), forcing_type, args.cell_key, args.forcing_file,
                   seeds['full'])
        sys.path.insert(0, str(app_dir))
        os.chdir(shim)
        import dhsvm_idf
        import extract_AM
        met_path = f'./met/{forcing_type}/'
        td = shim / 'td'
        td.mkdir()
        with contextlib.redirect_stdout(log):
            config_file = dhsvm_idf.generate_ng_idf(bas_par, adv_par, str(td), met_path, forcing_type)
        if not os.path.exists(config_file):
            raise FileNotFoundError(config_file)
        subprocess.run(['dos2unix', config_file], check=True, capture_output=True)
        proc = subprocess.run(['./dhsvm/no_sat_dump/DHSVM3.2', config_file], capture_output=True, text=True)
        (out / 'dhsvm.log').write_text(proc.stdout[-20000:] + '\n--- stderr ---\n' + proc.stderr[-20000:])
        shutil.copy2(config_file, out / 'Input.Snotel.T4')
        pixel_file = td / 'Pixel.CENTER'
        if proc.returncode != 0 or not pixel_file.exists():
            raise RuntimeError(f'DHSVM failed (exit {proc.returncode}); see {out}/dhsvm.log')
        if args.keep_pixel:
            with open(pixel_file, 'rb') as src, open(out / 'Pixel.CENTER.gz', 'wb') as dst:
                subprocess.run(['gzip', '-c'], stdin=src, stdout=dst, check=True)

        arrays = {}
        for wname, year_range in windows.items():
            r_file = td / 'get_IDF.R'
            r_src = (shim / 'get_IDF.R').read_text()
            r_src = re.sub(r'^set\.seed\(\d+\)', f'set.seed({seeds[wname]})', r_src, count=1)
            r_file.write_text(r_src)
            am_files_dict = {}
            for dur in durations:
                am_files_dict[f'am_{dur}_W_veg'] = str(td / f'am_{dur}_W_veg')
                am_files_dict[f'am_{dur}_P'] = str(td / f'am_{dur}_P')
            for f in td.glob('IDF_*'):
                f.unlink()
            with contextlib.redirect_stdout(log):
                am_results = extract_AM.extract_AM_data(str(pixel_file), am_files_dict, str(r_file), str(td),
                                                        forcing_type, year_range)
            for dur in durations:
                arrays[f'{wname}/IDF_{dur}_P'] = read_idf(td / f'IDF_{dur}_P')
                arrays[f'{wname}/IDF_{dur}_W_veg'] = read_idf(td / f'IDF_{dur}_W_veg')
                arrays[f'{wname}/am_{dur}_P'] = np.asarray(am_results[dur]['P'], dtype=float)
                arrays[f'{wname}/am_{dur}_W_veg'] = np.asarray(am_results[dur]['W_veg'], dtype=float)
            for key, val in am_results.items():
                if not key.endswith('h'):
                    with contextlib.suppress(Exception):
                        arrays[f'{wname}/{key}'] = np.asarray(val, dtype=float)
        np.savez_compressed(out / 'result.npz', **arrays)
        result.update(status='ok', windows={w: (None if r is None else [list(r[0]), list(r[1])]) for w, r in windows.items()},
                      seeds=seeds, seconds=round(time.time() - t0, 1))
    except Exception as exc:  # record and re-raise
        result.update(status='failed', error=repr(exc), seconds=round(time.time() - t0, 1))
        raise
    finally:
        (out / 'app_stdout.log').write_text(log.getvalue()[-200000:])
        (out / 'run.json').write_text(json.dumps(result, indent=2) + '\n')
        os.chdir('/')
        if not args.keep_work:
            shutil.rmtree(shim, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--app-dir', required=True)
    ap.add_argument('--dhsvm-bin', required=True)
    ap.add_argument('--forcing-type', required=True,
                    help='Daymet, WRF_historical, WRF_medium, WRF_high, CESM_{hist,futu}_LE{2,4,7,9}')
    ap.add_argument('--forcing-file', required=True)
    ap.add_argument('--cell-key', required=True, help='forcing cell as <lat5>_<lon5>')
    ap.add_argument('--place-id', required=True)
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--cover', type=int, required=True, help='DHSVM land cover code 1-9')
    ap.add_argument('--lai', type=float, required=True)
    ap.add_argument('--height', type=float, required=True, help='canopy height (m)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--work-root')
    ap.add_argument('--keep-pixel', action='store_true')
    ap.add_argument('--keep-work', action='store_true')
    run(ap.parse_args())


if __name__ == '__main__':
    main()
