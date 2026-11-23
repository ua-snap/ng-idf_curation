"""Per-place DHSVM defaults (land cover, LAI, canopy height) for the Phase 1 runs.

The author's rules (H. Yan, email of 18 Nov 2026), applied to each place's Daymet 1 km cell:
  land cover  NLCD 2016 AK: count the 30 m pixels in the cell, group them into the app's 10
              classes (73 lichens and 74 moss form "moss"), and take the most common class
  LAI         GLASS LAI 2016 V60 500 m: largest monthly mean of the 4-pixel cell sample
              (cell_lai.py)
  height      LANDFIRE 2016 Remap EVH, by the dominant class: forest (evergreen, deciduous,
              mixed) = mean height of the tree pixels; other vegetated classes = mean height
              of the shrub and herb pixels; open = none
  Rounded to 2 dp like the author's table.

Sources (defaults_source):
  author_table         the place's cell is in the author's table (static/gridcell_current_lulc.csv):
                       land cover and LAI from the table, as the app fills them in; height from the
                       rule above, because the table's heights were made by his earlier rule (mean of
                       the tree mean and the shrub mean) and he will republish them
  rebuilt_provisional  all other places: everything from the rules above. Provisional until his
                       republished table confirms them; moss runs as DHSVM code 6 (grass), the code
                       the app's Moss card sends, which he has not confirmed
Then the app's own rules (app.py /api/gridcell-lulc): missing LAI or height -> open; open -> LAI = height = 0.

Usage: build_place_defaults.py <places_csv> <author_table_csv> <work_dir> <out_csv>
"""
import sys

import numpy as np
import pandas as pd

# app.py LULC_TO_DHSVM_CODE, plus moss as the app's Moss card sends it (data-dhsvm-code="6")
LULC_TO_DHSVM_CODE = dict(open=1, evergreen=2, deciduous=3, mixed=4, crop=5, grass=6, shrub=7, pasture=8, wetland=9,
                          moss=6)
NLCD_TO_LABEL = {11: 'open', 12: 'open', 21: 'open', 22: 'open', 23: 'open', 24: 'open', 31: 'open',
                 41: 'deciduous', 42: 'evergreen', 43: 'mixed', 51: 'shrub', 52: 'shrub',
                 71: 'grass', 72: 'grass', 73: 'moss', 74: 'moss', 81: 'pasture', 82: 'crop', 90: 'wetland', 95: 'wetland'}
FOREST = {'evergreen', 'deciduous', 'mixed'}


def evh_lifeform(code):
    """LANDFIRE EVH code -> (lifeform, height m). Sparse (100) and non-vegetated codes -> (None, nan)."""
    if 101 <= code <= 199:
        return 'tree', code - 100.0
    if 201 <= code <= 299:
        return 'shrub', (code - 200) / 10.0  # 230 (>= 3.0 m) -> 3.0
    if 301 <= code <= 399:
        return 'herb', (code - 300) / 10.0  # 310 (>= 1.0 m) -> 1.0
    return None, np.nan


def height_for(cover, counts):
    """Mean EVH height of the lifeforms the dominant class uses; nan when it has none of them."""
    if cover in FOREST:
        use = evh_life == 'tree'
    elif cover in ('open', 'unavailable'):
        return np.nan
    else:
        use = (evh_life == 'shrub') | (evh_life == 'herb')
    n = counts[use]
    return float((evh_h[use] * n).sum() / n.sum()) if n.sum() > 0 else np.nan


def r2(x):
    return round(x, 2) if np.isfinite(x) else np.nan


places_csv, table_csv, work, out_csv = sys.argv[1:5]
places = pd.read_csv(places_csv)
table = pd.read_csv(table_csv)
nlcd = np.load(f'{work}/nlcd2016_counts.npz')
evh = np.load(f'{work}/evh2016_counts.npz')
lai = pd.read_csv(f'{work}/glass_lai.csv')
key = lambda la, lo: (round(float(la), 5), round(float(lo), 5))
nlcd_idx = {key(a, b): i for i, (a, b) in enumerate(zip(nlcd['lat'], nlcd['lon']))}
evh_idx = {key(a, b): i for i, (a, b) in enumerate(zip(evh['lat'], evh['lon']))}
lai_map = {key(a, b): v for a, b, v in zip(lai.latitude, lai.longitude, lai.lai)}
tab = {key(a, b): r for a, b, r in zip(table.latitude, table.longitude, table.itertuples(index=False))}
labels = sorted(set(NLCD_TO_LABEL.values()))
nlcd_vals, nlcd_cnt = nlcd['values'], nlcd['counts']
evh_life, evh_h = map(np.array, zip(*[evh_lifeform(int(v)) for v in evh['values']]))
evh_h = evh_h.astype(float)
evh_cnt = evh['counts']

rows = []
for p in places.itertuples(index=False):
    r = dict(id=p.id)
    if getattr(p, 'defaults_status', 'ok') != 'ok':
        # no Daymet land cell within 1.5 km: the app treats the point as outside its boundary
        r.update(nlcd_pixels=np.nan, nlcd_top_share=np.nan, nlcd_margin=np.nan, moss_share=np.nan,
                 rebuilt_land_cover='unavailable', rebuilt_lai=np.nan, rebuilt_height_m=np.nan,
                 source_land_cover='unavailable', source_lai=np.nan, source_height_m=np.nan,
                 land_cover='unavailable', cover_code=-1, lai=np.nan, height_m=np.nan, defaults_source='none')
        rows.append(r)
        continue
    k = key(p.defaults_lat, p.defaults_lon)
    # Rebuild every cell, including cells in the author's table: there the rebuilt cover and LAI are only a
    # check (rebuilt_* columns) and the table's values are used.
    rb_cover, rb_l, rb_h = 'unavailable', np.nan, np.nan
    tot, top_share, margin, moss = 0, np.nan, np.nan, 0
    e = np.zeros(len(evh_h))
    if k in nlcd_idx:
        lab_counts = {lb: 0 for lb in labels}
        for v, n in zip(nlcd_vals, nlcd_cnt[nlcd_idx[k]]):
            if int(v) in NLCD_TO_LABEL:
                lab_counts[NLCD_TO_LABEL[int(v)]] += n
        tot = sum(lab_counts.values())
        moss = lab_counts['moss']
        if tot:
            ranked = sorted(lab_counts.items(), key=lambda kv: (-kv[1], labels.index(kv[0])))
            rb_cover = ranked[0][0]
            top_share = ranked[0][1] / tot
            margin = (ranked[0][1] - ranked[1][1]) / tot
        e = evh_cnt[evh_idx[k]]
        rb_h = r2(height_for(rb_cover, e))
        rb_l = r2(float(lai_map.get(k, np.nan)))
    r.update(nlcd_pixels=int(tot), nlcd_top_share=round(top_share, 3) if tot else np.nan,
             nlcd_margin=round(margin, 3) if tot else np.nan, moss_share=round(moss / tot, 3) if tot else np.nan,
             rebuilt_land_cover=rb_cover, rebuilt_lai=rb_l, rebuilt_height_m=rb_h)
    if k in tab:
        t = tab[k]
        cover, l, src = str(t.dominant_LULC).strip().lower(), float(t.max_LAI), 'author_table'
        h = r2(height_for(cover, e))
        r.update(table_height_m=float(t.mean_height_m))
    else:
        src = 'rebuilt_provisional'
        cover, l, h = rb_cover, rb_l, rb_h
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
print('run as open for lack of a height or LAI:',
      df.loc[(df.land_cover == 'open') & (df.source_land_cover != 'open'), 'id'].tolist())
print('moss:', df.loc[df.land_cover == 'moss', 'id'].tolist())
print('near-tie land cover (margin < 0.05):', int((df.nlcd_margin < 0.05).sum()))
