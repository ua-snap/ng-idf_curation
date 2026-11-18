"""Per-place DHSVM defaults (land cover, LAI, canopy height) for the Phase 1 runs.

* Places whose 1 km cell is in the author's table (static/gridcell_current_lulc.csv):
  the table's values, verbatim (defaults_source = author_table).
* All other places: the statewide rebuild (defaults_source = rebuilt_provisional),
  using the rules inferred by comparison with the author's table (scripts/defaults/infer_*.py):
    land cover  NLCD 2016 AK; map each 30 m pixel to the app's labels, then take the
                most common label in the cell (97.8 % agreement with the author's table)
    LAI         GLASS LAI 2016 V60 500 m: per-date cell mean, annual max (r = 0.97, +0.10 bias)
    height      LANDFIRE 2016 EVH: mean height of tree/shrub/herb pixels (MAE 1.8 m; provisional:
                the author's exact product and rule are not known)
  Rounded to 2 dp like the author's table.
Then the app's own rules (app.py /api/gridcell-lulc): missing LAI or height -> open; open -> LAI = height = 0.

Usage: build_place_defaults.py <places_csv> <author_table_csv> <work_dir> <out_csv>
"""
import sys

import numpy as np
import pandas as pd

LULC_TO_DHSVM_CODE = dict(open=1, evergreen=2, deciduous=3, mixed=4, crop=5, grass=6, shrub=7, pasture=8, wetland=9)
NLCD_TO_LABEL = {11: 'open', 12: 'open', 21: 'open', 22: 'open', 23: 'open', 24: 'open', 31: 'open',
                 41: 'deciduous', 42: 'evergreen', 43: 'mixed', 51: 'shrub', 52: 'shrub',
                 71: 'grass', 72: 'grass', 81: 'pasture', 82: 'crop', 90: 'wetland', 95: 'wetland'}
# Not seen in the author's (Interior) table, so their mapping is unknown. Provisional:
# lichen and moss are low, non-woody cover; we group them with grass. Flagged per place.
PROVISIONAL_NLCD = {73: 'grass', 74: 'grass'}


def evh_height(code):
    if 101 <= code <= 199:
        return code - 100.0
    if 201 <= code <= 299:
        return (code - 200) / 10.0
    if 301 <= code <= 399:
        return (code - 300) / 10.0
    return np.nan


places_csv, table_csv, work, out_csv = sys.argv[1:5]
places = pd.read_csv(places_csv)
table = pd.read_csv(table_csv)
nlcd = np.load(f'{work}/nlcd2016_counts.npz')
evh = np.load(f'{work}/evh2016_counts.npz')
lai = pd.read_csv(f'{work}/glass_lai_L2.csv')
key = lambda la, lo: (round(float(la), 5), round(float(lo), 5))
nlcd_idx = {key(a, b): i for i, (a, b) in enumerate(zip(nlcd['lat'], nlcd['lon']))}
evh_idx = {key(a, b): i for i, (a, b) in enumerate(zip(evh['lat'], evh['lon']))}
lai_map = {key(a, b): v for a, b, v in zip(lai.latitude, lai.longitude, lai.lai_L2)}
tab = {key(a, b): r for a, b, r in zip(table.latitude, table.longitude, table.itertuples(index=False))}
labels = sorted(set(NLCD_TO_LABEL.values()))
nlcd_vals, nlcd_cnt = nlcd['values'], nlcd['counts']
evh_h = np.array([evh_height(int(v)) for v in evh['values']])
evh_cnt = evh['counts']

rows = []
for p in places.itertuples(index=False):
    r = dict(id=p.id)
    if getattr(p, 'defaults_status', 'ok') != 'ok':
        # no Daymet land cell within 1.5 km: the app treats the point as outside its boundary
        r.update(nlcd_pixels=np.nan, nlcd_top_share=np.nan, nlcd_margin=np.nan, uses_provisional_nlcd_class=False,
                 source_land_cover='unavailable', source_lai=np.nan, source_height_m=np.nan,
                 land_cover='unavailable', cover_code=-1, lai=np.nan, height_m=np.nan, defaults_source='none')
        rows.append(r)
        continue
    k = key(p.defaults_lat, p.defaults_lon)
    if k in tab:
        t = tab[k]
        cover, l, h, src = str(t.dominant_LULC).strip().lower(), float(t.max_LAI), float(t.mean_height_m), 'author_table'
        r.update(nlcd_pixels=np.nan, nlcd_top_share=np.nan, nlcd_margin=np.nan, uses_provisional_nlcd_class=False)
    else:
        src = 'rebuilt_provisional'
        c = nlcd_cnt[nlcd_idx[k]]
        lab_counts = {lb: 0 for lb in labels}
        prov = 0
        for v, n in zip(nlcd_vals, c):
            v = int(v)
            if v in NLCD_TO_LABEL:
                lab_counts[NLCD_TO_LABEL[v]] += n
            elif v in PROVISIONAL_NLCD:
                lab_counts[PROVISIONAL_NLCD[v]] += n
                prov += n
        tot = sum(lab_counts.values())
        if tot == 0:
            cover = 'unavailable'
            top_share = margin = np.nan
        else:
            ranked = sorted(lab_counts.items(), key=lambda kv: (-kv[1], labels.index(kv[0])))
            cover = ranked[0][0]
            top_share = ranked[0][1] / tot
            margin = (ranked[0][1] - ranked[1][1]) / tot
        e = evh_cnt[evh_idx[k]]
        veg = np.isfinite(evh_h) & (e > 0)
        h = float((evh_h[veg] * e[veg]).sum() / e[veg].sum()) if veg.any() else np.nan
        l = float(lai_map.get(k, np.nan))
        l, h = round(l, 2) if np.isfinite(l) else np.nan, round(h, 2) if np.isfinite(h) else np.nan
        r.update(nlcd_pixels=int(tot), nlcd_top_share=round(top_share, 3) if tot else np.nan,
                 nlcd_margin=round(margin, 3) if tot else np.nan,
                 uses_provisional_nlcd_class=bool(prov > 0 and cover == 'grass'))
    r.update(source_land_cover=cover, source_lai=l, source_height_m=h)
    # app.py /api/gridcell-lulc rules
    if not np.isfinite(l) or not np.isfinite(h):
        cover = 'open' if cover != 'unavailable' else cover
    if cover == 'open':
        l = h = 0.0
    r.update(land_cover=cover, cover_code=LULC_TO_DHSVM_CODE.get(cover, -1), lai=l, height_m=h, defaults_source=src)
    rows.append(r)
df = pd.DataFrame(rows)
df.to_csv(out_csv, index=False)
print(df.defaults_source.value_counts().to_dict())
print(df.groupby('defaults_source').land_cover.value_counts().unstack(fill_value=0).to_string())
print('unavailable:', df.loc[df.land_cover == 'unavailable', 'id'].tolist())
print('provisional lichen/moss decided cover:', df.loc[df.uses_provisional_nlcd_class, 'id'].tolist())
print('near-tie land cover (margin < 0.05):', int((df.nlcd_margin < 0.05).sum()))
