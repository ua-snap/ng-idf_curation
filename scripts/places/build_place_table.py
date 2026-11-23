"""Build the Phase 1 place table: each Alaska place → its defaults cell and forcing cells.

Cell selection copies the app (H. Yan, NG_IDF_AWS @ a582a5c) exactly:

* Defaults cell (land cover, LAI, height): app.py `lookup_gridcell_lulc` picks the
  nearest 1 km Daymet-grid cell by equirectangular distance
  (dlat*111.32, dlon*111.32*cos(lat)) km.
* WRF/CESM forcing cell: dhsvm_idf.py `find_nearest_coord` picks the nearest
  coordinate by *unscaled* squared degrees, (dlat)^2 + (dlon)^2, over the forcing
  coordinate list. The app ships the 4,225 Interior cells; we apply the same rule
  over the full 662 x 782 NNA 4 km grid.
* Daymet forcing cell: the same `find_nearest_coord` rule over the Daymet 1 km cells
  (the author's Daymet files use the same 72,406 cells as the defaults table).
* Both 1 km searches consider Daymet **land** cells only: the author's table and Daymet
  station files contain only cells where Daymet has data. The defaults cell must be within
  1.5 km (app.py MAX_GRIDCELL_DISTANCE_KM); otherwise the app treats the point as outside
  its boundary and the place is nodata.

We also record the geographically nearest 4 km cell (great-circle) and flag places
where the app's rule picks a different cell. A place is outside the WRF/CESM domain
(nodata for those datasets) if the great-circle distance to its selected 4 km cell
exceeds 4 km. Hyder (AK160) lies just east of the grid's last column, so it is outside.

Usage:
    python -I build_place_table.py --communities <SNAP API communities json> --wrf-file <NNA file> \
        --cesm-file <NNA file> --defaults-csv <gridcell_current_lulc.csv> --out <csv>
"""
import argparse
import sys
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from netCDF4 import Dataset
from pyproj import Transformer

DAYMET_LCC = ("+proj=lcc +lat_1=25 +lat_2=60 +lat_0=42.5 +lon_0=-100 +x_0=0 +y_0=0 "
              "+ellps=WGS84 +units=m +no_defs")
FORCING_DOMAIN_KM = 4.0
EARTH_RADIUS_KM = 6371.0
MAX_GRIDCELL_DISTANCE_KM = 1.5  # app.py: lookup_gridcell_lulc boundary


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def app_equirect_km(lat, lon, lats, lons):
    """app.py lookup_gridcell_lulc distance."""
    dlat = (lats - lat) * 111.32
    dlon = (lons - lon) * 111.32 * np.cos(np.deg2rad(lat))
    return np.hypot(dlat, dlon)


def app_degree_sq(lat, lon, lats, lons):
    """dhsvm_idf.py find_nearest_coord distance (unscaled degrees)."""
    return (lats - lat) ** 2 + (lons - lon) ** 2


def read_grid(path):
    with Dataset(path) as ds:
        return (np.asarray(ds['XLAT'][0], dtype=np.float64),
                np.asarray(ds['XLONG'][0], dtype=np.float64),
                np.asarray(ds['HGT'][0], dtype=np.float64))


def daymet_candidates(lat, lon, fwd, inv, radius=2):
    """Daymet 1 km cell centres (rounded to 5 dp, as in the author's files) around a point."""
    x, y = fwd.transform(lon, lat)
    i0, j0 = round((x - 750) / 1000), round(y / 1000)
    ii, jj = np.meshgrid(np.arange(i0 - radius, i0 + radius + 1), np.arange(j0 - radius, j0 + radius + 1))
    xs, ys = ii.ravel() * 1000.0 + 750, jj.ravel() * 1000.0
    lons, lats = inv.transform(xs, ys)
    return np.round(lats, 5), np.round(lons, 5), xs, ys


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--communities', type=Path, required=True)
    ap.add_argument('--wrf-file', type=Path, required=True)
    ap.add_argument('--cesm-file', type=Path, required=True)
    ap.add_argument('--defaults-csv', type=Path, required=True, help="app's static/gridcell_current_lulc.csv")
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--land-cache', type=Path, required=True, help='JSON cache of Daymet land status per cell')
    ap.add_argument('--daymet-pixel-dir', type=Path, help='downloaded single-pixel CSVs (count as land)')
    ap.add_argument('--offline', action='store_true', help='fail instead of querying the Daymet API')
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ngidf'))
    from daymet_land import LandChecker
    land = LandChecker(args.land_cache, args.daymet_pixel_dir, online=not args.offline)

    places = [p for p in json.loads(args.communities.read_text()) if p.get('region') == 'Alaska']
    places.sort(key=lambda p: int(p['id'][2:]))
    ids = [p['id'] for p in places]
    assert len(ids) == len(set(ids)), 'duplicate place ids'

    wlat, wlon, whgt = read_grid(args.wrf_file)
    clat, clon, chgt = read_grid(args.cesm_file)
    if not (np.array_equal(wlat, clat) and np.array_equal(wlon, clon)):
        raise ValueError('WRF and CESM grids differ')
    ny, nx = wlat.shape
    flat_lat, flat_lon = wlat.ravel(), wlon.ravel()
    # The app formats forcing coordinates to 5 dp (f"{lat:.5f}_{lon:.5f}").
    r_lat, r_lon = np.round(flat_lat, 5), np.round(flat_lon, 5)

    table = pd.read_csv(args.defaults_csv)
    t_lat, t_lon = table.latitude.to_numpy(float), table.longitude.to_numpy(float)
    for a_, b_ in zip(t_lat, t_lon):  # every cell of the author's table is a Daymet land cell
        land.cache.setdefault(f'{a_:.5f}_{b_:.5f}', True)

    fwd = Transformer.from_crs('EPSG:4326', DAYMET_LCC, always_xy=True)
    inv = Transformer.from_crs(DAYMET_LCC, 'EPSG:4326', always_xy=True)

    rows = []
    for p in places:
        lat, lon = float(p['latitude']), float(p['longitude'])
        row = dict(id=p['id'], name=p['name'], latitude=lat, longitude=lon)

        # --- WRF/CESM 4 km cell (app rule) ---
        k = int(np.argmin(app_degree_sq(lat, lon, r_lat, r_lon)))
        y, x = map(int, np.unravel_index(k, (ny, nx)))
        d_app = float(haversine_km(lat, lon, flat_lat[k], flat_lon[k]))
        gc = haversine_km(lat, lon, flat_lat, flat_lon)
        kg = int(np.argmin(gc))
        row.update(wrf_y=y, wrf_x=x, wrf_lat=r_lat[k], wrf_lon=r_lon[k],
                   wrf_key=f'{r_lat[k]:.5f}_{r_lon[k]:.5f}',
                   wrf_dist_km=round(d_app, 3), wrf_hgt_m=round(float(whgt.ravel()[k]), 1),
                   cesm_hgt_m=round(float(chgt.ravel()[k]), 1),
                   wrf_geo_nearest_differs=bool(kg != k),
                   wrf_on_grid_edge=bool(y in (0, ny - 1) or x in (0, nx - 1)))
        in_domain = d_app <= FORCING_DOMAIN_KM

        # --- Daymet 1 km cells: only Daymet land cells exist in the author's table and station files ---
        dlat, dlon, dxs, dys = daymet_candidates(lat, lon, fwd, inv, radius=4)
        keys = [f'{a:.5f}_{b:.5f}' for a, b in zip(dlat, dlon)]
        d_def = app_equirect_km(lat, lon, dlat, dlon)
        d_met = app_degree_sq(lat, lon, dlat, dlon)
        # the app ignores cells farther than 1.5 km, so only those need a land check
        i_def = next((int(i) for i in np.argsort(d_def, kind='stable')
                      if d_def[i] <= MAX_GRIDCELL_DISTANCE_KM and land(keys[i])), None)
        i_met = next((int(i) for i in np.argsort(d_met, kind='stable') if land(keys[i])), None)
        if i_def is not None:
            row.update(defaults_lat=dlat[i_def], defaults_lon=dlon[i_def],
                       defaults_lcc_x=dxs[i_def], defaults_lcc_y=dys[i_def],
                       defaults_dist_km=round(float(d_def[i_def]), 3), defaults_status='ok')
        else:
            row.update(defaults_lat=np.nan, defaults_lon=np.nan, defaults_lcc_x=np.nan, defaults_lcc_y=np.nan,
                       defaults_dist_km=np.nan,
                       defaults_status='no_land_cell_within_1.5km')
        if i_met is not None:
            row.update(daymet_lat=dlat[i_met], daymet_lon=dlon[i_met], daymet_key=keys[i_met], daymet_status='ok')
        else:
            row.update(daymet_lat=np.nan, daymet_lon=np.nan, daymet_key='', daymet_status='outside_daymet')
        row['daymet_differs_from_defaults'] = bool(row['defaults_status'] == 'ok' and i_met != i_def)
        # did the land restriction move the cell away from the unrestricted nearest?
        row['defaults_moved_off_water'] = bool(i_def is not None and i_def != int(np.argmin(d_def)))
        row['daymet_moved_off_water'] = bool(i_met is not None and i_met != int(np.argmin(d_met)))

        # --- Is the defaults cell in the author's Interior table? Cross-check with the app's lookup. ---
        in_table = row['defaults_status'] == 'ok' and bool(np.any((t_lat == dlat[i_def]) & (t_lon == dlon[i_def])))
        row['in_author_defaults_table'] = in_table
        if in_table:
            j = int(np.argmin(app_equirect_km(lat, lon, t_lat, t_lon)))
            if (t_lat[j], t_lon[j]) != (dlat[i_def], dlon[i_def]):
                raise ValueError(f"{p['id']}: lattice cell {dlat[i_def]},{dlon[i_def]} "
                                 f"!= app lookup {t_lat[j]},{t_lon[j]}")

        row['wrf_cesm_status'] = 'ok' if in_domain else 'outside_forcing_domain'
        rows.append(row)

    land.save()
    print(f'Daymet land checks: {land.queries} API queries', flush=True)
    df = pd.DataFrame(rows)
    df.insert(0, 'location_index', np.arange(len(df)))
    # Several places can share a 4 km cell; give each distinct cell an index for extraction.
    ok = df.wrf_cesm_status == 'ok'
    cells = df.loc[ok, ['wrf_y', 'wrf_x']].drop_duplicates().sort_values(['wrf_y', 'wrf_x']).reset_index(drop=True)
    cells['forcing_cell_index'] = np.arange(len(cells))
    df = df.merge(cells, on=['wrf_y', 'wrf_x'], how='left')
    df['forcing_cell_index'] = df.forcing_cell_index.astype('Int64')
    df = df.sort_values('location_index')

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    meta = dict(source_communities=str(args.communities), communities_sha256=sha256(args.communities),
                wrf_grid_file=str(args.wrf_file), cesm_grid_file=str(args.cesm_file),
                defaults_csv_sha256=sha256(args.defaults_csv), n_places=len(df),
                n_ok=int(ok.sum()), n_forcing_cells=len(cells),
                n_daymet_cells=int(df.loc[df.daymet_status == 'ok', 'daymet_key'].nunique()),
                defaults_status=df.defaults_status.value_counts().to_dict(),
                daymet_status=df.daymet_status.value_counts().to_dict(),
                no_defaults_cell=df.loc[df.defaults_status != 'ok', ['id', 'name', 'defaults_dist_km']].to_dict('records'),
                defaults_moved_off_water=df.loc[df.defaults_moved_off_water, 'id'].tolist(),
                daymet_moved_off_water=df.loc[df.daymet_moved_off_water, 'id'].tolist(),
                n_in_author_defaults_table=int(df.in_author_defaults_table.sum()),
                outside_forcing_domain=df.loc[~ok, ['id', 'name', 'wrf_dist_km']].to_dict('records'),
                on_grid_edge=df.loc[df.wrf_on_grid_edge, 'id'].tolist(),
                app_rule_not_geo_nearest=df.loc[df.wrf_geo_nearest_differs, 'id'].tolist(),
                daymet_cell_differs_from_defaults_cell=df.loc[df.daymet_differs_from_defaults, 'id'].tolist())
    args.out.with_suffix('.meta.json').write_text(json.dumps(meta, indent=2, default=str) + '\n')
    print(json.dumps({k: (v if not isinstance(v, list) or len(v) < 12 else f'{len(v)} items') for k, v in meta.items()},
                     indent=2, default=str))


if __name__ == '__main__':
    main()
