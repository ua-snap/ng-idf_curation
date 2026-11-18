"""Neighbourhood pilot: NG-IDF for the land around a place, and land-cover scenarios at the place.

A place's own 1 km cell is often "open" (developed land or water), while the land around it is forest,
shrub or wetland, and in coastal mountains it can rise hundreds of metres within a few kilometres.
This pilot runs the app's method in two ways:

  A. neighbourhood   Every Daymet land 1 km cell whose centre is within --radius-km of the place is
                     treated as if a user had clicked its centre: its own land cover, LAI and height
                     (author's table, else the statewide rebuild), its own Daymet forcing (built with
                     the Phase 1 MetSim recipe at that cell's Daymet elevation) and its own WRF/CESM
                     4 km cell (app rule). Differences between cells combine vegetation and weather
                     (elevation, exposure).
  B. scenario        The place's own point and forcing (the Phase 1 files), run once per vegetated
                     land cover. LAI and height for a class are the medians over the neighbourhood
                     cells of that class; if the class is absent, the medians over the author's table.
                     Differences between scenarios are vegetation only.

Both use the app's own code through run_point.py; only the inputs are chosen here.

Subcommands:
  cells      enumerate the neighbourhood cells (Daymet land check via the single-pixel API, cached)
  manifest   write a run_batch.py manifest for A and B, plus scenarios.csv
  summarize  collect results into one long table (depth by place, run, dataset, variable, duration, ARI)
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ngidf'))
sys.path.insert(0, str(REPO / 'scripts/places'))

WRF_CESM = ['WRF_historical', 'WRF_medium', 'WRF_high'] + [
    f'CESM_{p}_LE{m}' for p in ('hist', 'futu') for m in (2, 4, 7, 9)]
SCENARIO_CLASSES = {'evergreen': 2, 'deciduous': 3, 'mixed': 4, 'grass': 6, 'shrub': 7, 'wetland': 9}
ARIS = [2, 5, 10, 25, 50, 100, 500]


def cmd_cells(args):
    from netCDF4 import Dataset
    from pyproj import Transformer
    from daymet_land import LandChecker
    from build_place_table import (DAYMET_LCC, app_degree_sq, daymet_candidates, haversine_km)

    places = pd.read_csv(args.places, dtype={'wrf_key': str, 'daymet_key': str}).set_index('id')
    with Dataset(args.wrf_file) as d:
        wlat = np.asarray(d['XLAT'][0], float)
        wlon = np.asarray(d['XLONG'][0], float)
        whgt = np.asarray(d['HGT'][0], float)
    ny, nx = wlat.shape
    r_lat, r_lon = np.round(wlat.ravel(), 5), np.round(wlon.ravel(), 5)
    fwd = Transformer.from_crs('EPSG:4326', DAYMET_LCC, always_xy=True)
    inv = Transformer.from_crs(DAYMET_LCC, 'EPSG:4326', always_xy=True)
    land = LandChecker(args.land_cache, args.pixel_dir, online=not args.offline)
    rows = []
    for pid in args.ids:
        p = places.loc[pid]
        n = int(np.ceil(args.radius_km)) + 1
        dlat, dlon, xs, ys = daymet_candidates(p.latitude, p.longitude, fwd, inv, radius=n)
        dist = haversine_km(p.latitude, p.longitude, dlat, dlon)
        keep = 0
        for la, lo, x, y, d in sorted(zip(dlat, dlon, xs, ys, dist), key=lambda t: t[4]):
            if d > args.radius_km:
                continue
            key = f'{la:.5f}_{lo:.5f}'
            if not land(key):
                continue
            k = int(np.argmin(app_degree_sq(la, lo, r_lat, r_lon)))
            wy, wx = map(int, np.unravel_index(k, (ny, nx)))
            rows.append(dict(id=f'{pid}_{key}', place_id=pid, place=p['name'], latitude=la, longitude=lo,
                             lcc_x=x, lcc_y=y, dist_km=round(float(d), 3),
                             dx_km=round((x - fwd.transform(p.longitude, p.latitude)[0]) / 1000, 3),
                             dy_km=round((y - fwd.transform(p.longitude, p.latitude)[1]) / 1000, 3),
                             is_place_defaults_cell=bool(np.isclose(la, p.defaults_lat) and np.isclose(lo, p.defaults_lon)),
                             is_place_daymet_cell=key == p.daymet_key,
                             daymet_key=key, daymet_status='ok', defaults_lat=la, defaults_lon=lo, defaults_status='ok',
                             wrf_y=wy, wrf_x=wx, wrf_key=f'{r_lat[k]:.5f}_{r_lon[k]:.5f}',
                             wrf_hgt_m=round(float(whgt[wy, wx]), 1)))
            keep += 1
        land.save()
        print(f'{pid} {p["name"]}: {keep} land cells within {args.radius_km} km', flush=True)
    df = pd.DataFrame(rows)
    cells = df[['wrf_y', 'wrf_x']].drop_duplicates().sort_values(['wrf_y', 'wrf_x']).reset_index(drop=True)
    cells['forcing_cell_index'] = np.arange(len(cells))
    df = df.merge(cells, on=['wrf_y', 'wrf_x'], how='left')
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / 'cells.csv', index=False)
    print(f'{len(df)} cells, {df.wrf_key.nunique()} WRF cells, {land.queries} land queries -> {out}/cells.csv')


def daymet_elevation(pixel_csv):
    with open(pixel_csv) as f:
        for line in f:
            if line.startswith('Elevation'):
                return float(line.split()[1])
    return np.nan


def cmd_manifest(args):
    cells = pd.read_csv(args.cells, dtype={'wrf_key': str, 'daymet_key': str})
    cdef = pd.read_csv(args.cell_defaults)
    places = pd.read_csv(args.places, dtype={'wrf_key': str, 'daymet_key': str}).set_index('id')
    pdef = pd.read_csv(args.place_defaults).set_index('id')
    table = pd.read_csv(args.author_table)
    table['dominant_LULC'] = table.dominant_LULC.str.strip().str.lower()
    c = cells.merge(cdef, on='id', how='left')
    c['daymet_elev_m'] = [daymet_elevation(Path(args.pixel_dir) / f'pix_{k}.csv') for k in c.daymet_key]
    c.to_csv(Path(args.out_dir) / 'cells_with_defaults.csv', index=False)

    rows = []
    # A. neighbourhood cells, each with its own inputs
    for r in c.itertuples(index=False):
        if r.cover_code < 0:
            continue
        common = dict(experiment='neighbourhood', place=r.place_id, member=r.daymet_key, lat=r.latitude,
                      lon=r.longitude, cover=int(r.cover_code), lai=float(r.lai), height=float(r.height_m),
                      defaults_source=r.defaults_source)
        rows.append(dict(place_id=f'{r.place_id}/cells/{r.daymet_key}', dataset='Daymet', cell_key=r.daymet_key,
                         forcing_file=str(Path(args.pilot_forcing) / 'Daymet' / f'data_{r.daymet_key}'), **common))
        for ds in WRF_CESM:
            rows.append(dict(place_id=f'{r.place_id}/cells/{r.daymet_key}', dataset=ds, cell_key=r.wrf_key,
                             forcing_file=str(Path(args.pilot_forcing) / ds / f'data_{r.wrf_key}'), **common))

    # B. land-cover scenarios at the place's own point and forcing
    scen = []
    for pid in cells.place_id.unique():
        p = places.loc[pid]
        nb = c[(c.place_id == pid) & (c.cover_code > 1)]
        for cls, code in SCENARIO_CLASSES.items():
            s = nb[nb.land_cover == cls]
            if len(s):
                lai, h, src = float(s.lai.median()), float(s.height_m.median()), f'neighbourhood median ({len(s)} cells)'
            else:
                t = table[table.dominant_LULC == cls]
                lai, h, src = float(t.max_LAI.median()), float(t.mean_height_m.median()), \
                    f"author's table median ({len(t)} Interior cells)"
            scen.append(dict(place_id=pid, scenario=cls, cover=code, lai=round(lai, 2), height_m=round(h, 2),
                             n_cells=len(s), source=src))
            common = dict(experiment='scenario', place=pid, member=cls, lat=p.latitude, lon=p.longitude, cover=code,
                          lai=round(lai, 2), height=round(h, 2), defaults_source=src)
            rows.append(dict(place_id=f'{pid}/scenario/{cls}', dataset='Daymet', cell_key=p.daymet_key,
                             forcing_file=str(Path(args.phase1_forcing) / 'Daymet' / f'data_{p.daymet_key}'), **common))
            for ds in WRF_CESM:
                rows.append(dict(place_id=f'{pid}/scenario/{cls}', dataset=ds, cell_key=p.wrf_key,
                                 forcing_file=str(Path(args.phase1_forcing) / ds / f'data_{p.wrf_key}'), **common))
    pd.DataFrame(scen).to_csv(Path(args.out_dir) / 'scenarios.csv', index=False)
    m = pd.DataFrame(rows)
    missing = [f for f in m.forcing_file.unique() if not Path(f).exists()]
    if missing and not args.allow_missing_forcing:
        raise ValueError(f'{len(missing)} forcing files missing, e.g. {missing[:3]}')
    m.to_csv(args.out, index=False)
    print(f'{len(m)} runs -> {args.out}')
    print(m.groupby(['experiment', 'place']).size().unstack(0).to_string())


def cmd_summarize(args):
    m = pd.read_csv(args.manifest, dtype={'cell_key': str})
    rows, status = [], []
    for r in m.itertuples(index=False):
        d = Path(args.runs_root) / r.place_id / r.dataset
        rj = d / 'run.json'
        st = json.loads(rj.read_text()).get('status', '?') if rj.exists() else 'missing'
        err = ''
        if st != 'ok':
            log = d / 'dhsvm.log'
            if log.exists():
                err = next((l.strip() for l in log.read_text().splitlines() if 'error' in l.lower()), '')
        status.append(dict(experiment=r.experiment, place=r.place, member=r.member, dataset=r.dataset, status=st,
                           error=err))
        if st != 'ok':
            continue
        z = np.load(d / 'result.npz')
        for key in z.files:
            if not key.startswith('full/IDF_'):
                continue
            _, name = key.split('/')
            _, dur, var = name.split('_', 2)
            mag = z[key][0]
            for a in ARIS:
                rows.append(dict(experiment=r.experiment, place=r.place, member=r.member, dataset=r.dataset,
                                 variable=var, duration_h=int(dur[:-1]), return_period_yr=a,
                                 depth_mm=float(mag[args.prob_index[a]])))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res = pd.DataFrame(rows)
    # CESM ensemble means (mean of the four members' fitted depths, as the app does)
    ens = []
    for period in ('hist', 'futu'):
        sub = res[res.dataset.str.startswith(f'CESM_{period}_LE')]
        g = sub.groupby(['experiment', 'place', 'member', 'variable', 'duration_h', 'return_period_yr'])
        e = g.depth_mm.agg(['mean', 'count']).reset_index()
        e = e[e['count'] == 4].drop(columns='count').rename(columns={'mean': 'depth_mm'})
        e['dataset'] = f'CESM_{period}_ensemble_mean'
        ens.append(e)
    res = pd.concat([res] + ens, ignore_index=True)
    res['depth_mm'] = res.depth_mm.round(2)
    res.to_csv(out / 'depths.csv', index=False)
    st = pd.DataFrame(status)
    st.to_csv(out / 'run_status.csv', index=False)
    print(st.groupby(['experiment', 'dataset', 'status']).size().unstack(fill_value=0).to_string())
    print(f'{len(res)} depth rows -> {out}/depths.csv')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('cells')
    a.add_argument('--places', default=str(REPO / 'data/places/places_ak.csv'))
    a.add_argument('--ids', nargs='+', required=True)
    a.add_argument('--radius-km', type=float, default=5.0)
    a.add_argument('--wrf-file', required=True, help='any NNA 4 km WRF file (XLAT, XLONG, HGT)')
    a.add_argument('--land-cache', required=True)
    a.add_argument('--pixel-dir')
    a.add_argument('--offline', action='store_true')
    a.add_argument('--out-dir', required=True)
    a.set_defaults(func=cmd_cells)
    b = sub.add_parser('manifest')
    b.add_argument('--cells', required=True)
    b.add_argument('--cell-defaults', required=True, help='build_place_defaults.py output for cells.csv')
    b.add_argument('--places', default=str(REPO / 'data/places/places_ak.csv'))
    b.add_argument('--place-defaults', default=str(REPO / 'data/places/place_defaults.csv'))
    b.add_argument('--author-table', required=True, help="app's static/gridcell_current_lulc.csv")
    b.add_argument('--pixel-dir', required=True)
    b.add_argument('--pilot-forcing', required=True, help='forcing root for the neighbourhood cells')
    b.add_argument('--phase1-forcing', required=True, help='Phase 1 forcing root (place cells)')
    b.add_argument('--allow-missing-forcing', action='store_true')
    b.add_argument('--out-dir', required=True)
    b.add_argument('--out', required=True)
    b.set_defaults(func=cmd_manifest)
    c = sub.add_parser('summarize')
    c.add_argument('--manifest', required=True)
    c.add_argument('--runs-root', required=True)
    c.add_argument('--coverage-dir', required=True, help='Phase 1 coverage (exceedance probabilities)')
    c.add_argument('--out-dir', required=True)
    c.set_defaults(func=cmd_summarize)
    args = ap.parse_args()
    if args.cmd == 'summarize':
        import ast
        from netCDF4 import Dataset
        with Dataset(Path(args.coverage_dir) / 'ngidf_places.nc') as nc:
            probs = ast.literal_eval(nc['exceedance'].encoding)
        args.prob_index = {a: min(probs, key=lambda i: abs(1 / (1 - probs[i]) - a)) for a in ARIS}
    args.func(args)


if __name__ == '__main__':
    main()
