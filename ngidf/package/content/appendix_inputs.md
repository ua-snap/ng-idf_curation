<!-- Appendix A of the QC package. Prose about each input; anything that is a result of a run is filled in
     from that run ({{result:...}} and {{name}} placeholders, see build.py facts() and result_blocks()). -->

Each run of the author's NG-IDF app needs four kinds of input: a place (latitude and longitude), the land surface at that place (land cover, leaf area index, canopy height), a weather series (the "forcing"), and the model itself. This appendix describes where each input comes from and every step between the source and the model run.

Two rules guide all of it:

- **Copy the author.** Every scientific choice follows H. Yan's NG-IDF app ({{upstream_repo}}, branch `{{upstream_branch}}`, commit `{{app_commit7}}`). Where the app ships data only for Interior Alaska, we rebuild the same data statewide from the same sources with the same rules, and compare our rebuild with the author's files where both exist.
- **Record what differs.** Where we could not match the author exactly, the difference, its size and its cause are stated below and checked by the pipeline (see [section 4](#issues)).

Paths below are relative to the repository root, or to the data root `{{data_root}}` (`DATA_ROOT` in `config/paths.env`).

<!-- dynamic: app repo/branch/commit from config/model_versions/<CURRENT>.env (UPSTREAM_REPO, UPSTREAM_BRANCH, APP_COMMIT) -->

---

## A.1 The place list {#in-places}

### Source

| Item | Value |
|---|---|
| Name | SNAP API community list |
| URL | `https://earthmaps.io/places/communities` |
| Snapshot | `raw/earthmaps_places/communities_20261117.json`, downloaded 17 Nov 2026 |
| Checksum | SHA-256 `e2808b13…3bf66`, recorded in `raw/earthmaps_places/SHA256SUMS` and re-checked by the `inputs` stage |
| Size | 25,198 places in North America and northern Europe; 565 have `region == "Alaska"` |

<!-- dynamic: snapshot path from config/paths.env PLACES_SNAPSHOT; counts from the places stage report (metrics.places) -->

### What we use from it

For each Alaska place: the SNAP API place ID (for example `AK124`), the name, latitude and longitude. All 565 Alaska entries have `type == "community"`.

### How it is processed

1. Keep the entries with `region == "Alaska"` (565). Sort them by the number in the ID.
2. For each place, find three model cells, each with the rule the author's app uses. Two supply the place's weather. The third, the **defaults cell**, supplies its land cover, LAI and canopy height: the values the app's web page fills in when the point is clicked (A.2 to A.4).

   | Cell | Grid | Rule (copied from the app) | Used for |
   |---|---|---|---|
   | WRF/CESM forcing cell | NNA 4 km WRF grid, 662 × 782 cells (identical for WRF and CESM; the code stops if they differ) | Nearest cell by **unscaled** squared degrees, (Δlat)² + (Δlon)², with cell coordinates rounded to 5 decimals (`dhsvm_idf.py` `find_nearest_coord`) | The 11 WRF and CESM datasets |
   | Daymet forcing cell | Daymet v4 1 km grid (Lambert conformal conic, `lat_1=25 lat_2=60 lat_0=42.5 lon_0=-100`) | Same unscaled-degree rule, over Daymet **land** cells | The Daymet dataset |
   | Defaults cell | Same Daymet 1 km grid | Nearest by equirectangular distance in km (Δlat × 111.32, Δlon × 111.32 × cos(lat)), over Daymet **land** cells, and only if within 1.5 km (`app.py` `lookup_gridcell_lulc`, `MAX_GRIDCELL_DISTANCE_KM`) | Land cover, LAI and canopy height (A.2 to A.4) |

3. **Land or water.** The author's defaults table and his Daymet station files contain only cells where Daymet has data, which are land cells. So the app's 1 km searches never return a water cell. We reproduce this: a 1 km cell counts as land if Daymet returns data for it. Land status is taken from, in order: the author's table (every cell in it is land), the Daymet pixels we downloaded (A.6), or a one-day query (tmax, 1 Jul 2016) to the ORNL Daymet single-pixel API. Answers are cached in `work/daymet_land_cache.json`. The pipeline works on a copy of this cache and runs offline, so the stage reads a fixed input. The search covers the 9 × 9 Daymet cells around the place.
4. **Out of domain.** A place is outside the WRF/CESM domain if its selected 4 km cell is more than 4 km away (great-circle distance). A place has no defaults cell if no Daymet land cell lies within 1.5 km; the app treats such a point as outside its boundary.
5. Record, for checking: the great-circle nearest 4 km cell, whether it differs from the app's choice, the WRF and CESM terrain height of the cell, the distances, and whether the land restriction moved a cell off water.
6. For the 51 places whose defaults cell is in the author's table, check that our defaults cell is the one the app's own lookup returns. The code stops if any differs.
7. Give each distinct 4 km cell an index. Several places share a cell.

### Result in this run

{{result:places}}

### Decisions and why

- **Use the app's nearest-cell rules, even where they are not the geographic nearest.** The app picks the forcing cell by unscaled degrees. At Alaska latitudes a degree of longitude is much shorter than a degree of latitude, so for 53 places this is not the closest cell on the ground. All are within 3.6 km. We follow the app so that our curve for a place is the curve the app would draw for it. The great-circle nearest cell is recorded in the place table.
- **Different rules for defaults and Daymet forcing.** The app uses km for the defaults lookup and degrees for the Daymet forcing lookup. For 107 places the two pick different 1 km cells. We follow the app.
- **Search land cells only.** This matches what the app can return (the author's table and station files hold land cells only). Without it, 5 defaults cells and 7 Daymet cells would have been water.
- **Keep out-of-domain places as nodata.** They stay in the coverage with nodata values, and the file metadata names them, so the place list matches the SNAP API.

### Where in the code

`scripts/places/build_place_table.py`, `ngidf/daymet_land.py`, `slurm/stages/places.sbatch`; stage `places` in `ngidf/pipeline.py`.

---

## A.2 Land cover {#in-landcover}

### Source

| Item | Value |
|---|---|
| Name | National Land Cover Database (NLCD) 2016, Alaska, from MRLC |
| File | `raw/nlcd_2016_ak/NLCD_2016_Land_Cover_AK_20200724.img` (from `NLCD_2016_Land_Cover_AK_20200724.zip`) |
| Resolution | 30 m |
| Checksum | `raw/nlcd_2016_ak/SHA256SUMS`, re-checked by the `inputs` stage |
| Author's table | `static/gridcell_current_lulc.csv` in the app: 72,406 Interior Alaska 1 km cells, columns `dominant_LULC`, `max_LAI`, `mean_height_m` |

The author named NLCD 2016 as his land-cover source (H. Yan, Oct 2026).

### What we use from it

The NLCD class of every 30 m pixel whose centre falls inside a place's 1 km defaults cell (about 1,046 pixels per cell).

### How it is processed

1. Take the place's defaults cell (A.1), a 1 km × 1 km square on the Daymet grid.
2. Read a small window of the NLCD raster around it. Reproject each pixel centre to the Daymet grid. Keep the pixels whose centre lies inside the square.
3. Map each pixel's NLCD class to one of the app's labels (table below).
4. Count pixels per label. The label with the most pixels is the cell's land cover. Ties go to the label that comes first alphabetically.
5. Record the share of the winning label and the margin to the runner-up (as a fraction of the cell's pixels).
6. Convert the label to the DHSVM land-cover code with the app's `LULC_TO_DHSVM_CODE`.
7. Apply the app's own rules from `app.py` (`/api/gridcell-lulc`): if LAI or height is missing, the cover becomes Open; Open always has LAI = 0 and height = 0 m.

**Crosswalk** (confirmed by H. Yan, Nov 2026):

<!-- dynamic: crosswalk from scripts/defaults/build_place_defaults.py NLCD_TO_LABEL; DHSVM codes from LULC_TO_DHSVM_CODE -->

| NLCD class(es) | NLCD name(s) | App label | DHSVM code |
|---|---|---|---|
| 11, 12, 21, 22, 23, 24, 31 | Open water, perennial ice/snow, developed (4 classes), barren | open | 1 |
| 42 | Evergreen forest | evergreen | 2 |
| 41 | Deciduous forest | deciduous | 3 |
| 43 | Mixed forest | mixed | 4 |
| 82 | Cultivated crops | crop | 5 |
| 71, 72 | Grassland/herbaceous, sedge/herbaceous | grass | 6 |
| 51, 52 | Dwarf scrub, shrub/scrub | shrub | 7 |
| 81 | Pasture/hay | pasture | 8 |
| 90, 95 | Woody wetlands, emergent herbaceous wetlands | wetland | 9 |
| 73, 74 | Lichens, moss | moss | 6 (**provisional**) |

### When no land cover can be given

A place's land cover is **unavailable** when there is nothing to take it from. This happens in two cases:

- the place has no defaults cell, because no Daymet land cell lies within 1.5 km of it (A.1). The app treats such a point as outside its boundary. These places are counted under "No defaults" in the result below;
- the place has a defaults cell, but the cell lies outside the NLCD map, so it has no pixels to count.

A place with unavailable land cover has no LAI or canopy height either. It is not run, and it has no curves for any dataset ([section 4](#issues), "Places without curves").

### When the author's own table is used instead

If the place's defaults cell is one of the 72,406 cells of the author's table, we use his `dominant_LULC` and `max_LAI` for that cell unchanged, as the app fills them in (`defaults_source = author_table`). The height comes from the author's new height rule (A.4), not from his table: the table's heights were made with his earlier rule, and he will republish them. Our rebuilt land cover and LAI are still computed for these places, as a check only (`rebuilt_*` columns). All other places use the rebuild (`defaults_source = rebuilt_provisional`).

### Result in this run

{{result:defaults}}

### Decisions and why

- **NLCD 2016, not another land-cover map.** The author named it. We also tested NALCMS 2015. It fits about as well (97.7%), but it has no pasture class, and the author's table has pasture cells. NLCD is the source.
- **Map each pixel to a label first, then take the majority.** This matches the author's table at 97.8%. Taking the majority NLCD class first and mapping it afterwards matches at 97.1%. The author described his method as: count the 30 m pixels in the cell, group them into the app's classes, and take the dominant class (H. Yan, Nov 2026). That is the rule we use.
- **The Daymet 1 km grid.** The author's table lies on it exactly: every cell centre is on the Daymet lattice. For point runs the author uses this 1 km table for Daymet, WRF and CESM alike, so that differences between datasets come only from the weather (H. Yan, Nov 2026). We do the same.
- **Lichens and moss form the "Moss" class.** The author confirmed that NLCD classes 73 and 74 are grouped as "Moss", class 10 on the app's web page (H. Yan, Nov 2026). Moss competes for the majority like any other class. The app's `LULC_TO_DHSVM_CODE` has no moss entry; the web page's Moss card sends DHSVM code 6 (grass), so we use 6. Its LAI and height come from the same rules as other non-forest covers (A.3, A.4). The author has not confirmed the code, LAI or height for moss, so moss places are provisional and the `defaults` stage flags them (see [section 4](#issues)). Lichen and moss pixels are rare in the cells of the author's Interior table (at most 3% of a cell).

### Where in the code

`scripts/defaults/cell_counts.py` (pixel counts per cell), `scripts/defaults/build_place_defaults.py` (crosswalk, majority, the app's rules, author's table), `slurm/stages/defaults.sbatch`; stage `defaults` in `ngidf/pipeline.py`. The crosswalk was inferred with `scripts/defaults/zonal_counts.py` and `scripts/defaults/infer_crosswalk.py`.

---

## A.3 Leaf area index (LAI) {#in-lai}

### Source

| Item | Value |
|---|---|
| Name | GLASS LAI, version V60, from MODIS, 500 m, 8-day composites, year 2016 (product `GLASS01E01`) |
| URL | `https://glass.hku.hk/archive/LAI/MODIS/500M/2016/` |
| Files | `raw/glass_lai_2016_500m/`: 15 MODIS tiles covering Alaska × 46 dates (day of year 001 to 361) = 690 HDF files |
| Checksum | `raw/glass_lai_2016_500m/SHA256SUMS`, re-checked by the `inputs` stage |
| Scaling | Stored value × 0.1 = LAI (m²/m²); 255 = no data |

The author named GLASS LAI 2016 (Oct 2026) and then the exact product: MODIS V60, 500 m (H. Yan, Nov 2026).

### What we use from it

One number per place, `max_LAI`: the overstory LAI the app puts in the DHSVM configuration. It is used only for vegetated covers; Open has LAI = 0.

### How it is processed

<!-- dynamic: rule from scripts/defaults/cell_lai.py docstring -->

The author's method (H. Yan, Nov 2026):

1. Project the centre of the place's 1 km cell (its latitude and longitude) to the GLASS grid (MODIS sinusoidal projection).
2. Take the four points 250 m east or west and 250 m north or south of the centre, in that projection, and the 500 m pixel under each point.
3. For each 8-day composite, average the valid values of these four pixels.
4. Average the composites within each calendar month. A composite belongs to the month of its first day.
5. `max_LAI` is the largest of the 12 monthly means. Round to 2 decimals, as in the author's table.

No-data values (255) are skipped in both averages.

### Result in this run

The `defaults` stage applies this rule to every cell of the author's table and compares it with his `max_LAI`; the check `LAI rule reproduces the author's table (max_LAI, all cells)` in A.2's results gives the agreement.

### Decisions and why

- **The projection of the ±250 m offsets.** The author did not say in which projection the four points are placed. Placed in the GLASS projection, the rule reproduces his `max_LAI` exactly (to 2 decimals) at 98% of his 72,406 cells and within 0.01 at 99.99%. Placed in the Daymet projection, only 9% agree, although the mean is the same: points 250 m from the centre lie close to pixel edges, so the projection decides which pixels are picked. The remaining differences of 0.01 are values that fall exactly halfway (x.xx5), which rounding sends one way or the other depending on the order of the arithmetic. A handful of larger differences (up to 0.18) lie on one MODIS tile edge.
- **The month of a composite.** Not stated by the author. Assigning each composite to the month of its first day fits best. The month of its middle day fits almost as well. Splitting each composite between months by its days fits much worse (25% exact).
- **An earlier rule.** Before the author described his method we used the largest 8-day mean of all 500 m pixels in the cell. That rule ran about 0.10 high.
- **Why LAI matters little.** In a sensitivity test at 3 Interior places (evergreen, shrub, deciduous; WRF historical), changing LAI by ±0.1 changed the 100-year NG depth by at most 0.4% at every duration (1 to 72 h). Precipitation curves do not depend on LAI at all.

### Where in the code

`scripts/defaults/cell_lai.py` (LAI per cell, for the places and for the check over the author's table), `scripts/defaults/build_place_defaults.py`, `scripts/defaults/download_glass_lai.sh` (download), `slurm/stages/defaults.sbatch`; the check is in the `defaults` stage of `ngidf/pipeline.py`. The sensitivity test is `scripts/tests/sensitivity_defaults.py`.

---

## A.4 Canopy height {#in-height}

### Source

| Item | Value |
|---|---|
| Name | LANDFIRE 2016 Remap (LF 2.0.0) Existing Vegetation Height (EVH), Alaska |
| File | `raw/landfire_evh_2016_ak/LF2016_EVH_AK/Tif/LF2016_EVH_AK.tif` (from `LF2016_EVH_AK.zip`) |
| Resolution | 30 m |
| Checksum | `raw/landfire_evh_2016_ak/SHA256SUMS`, re-checked by the `inputs` stage |
| Code table | `LF2016_EVH_AK/CSV_Data/LF2016_EVH.csv` |

The author named LANDFIRE 2016 EVH (Oct 2026) and confirmed the exact product, LF 2016 Remap EVH, LF 2.0.0 (H. Yan, Nov 2026).

### What we use from it

One number per place, `mean_height_m`: the overstory height the app puts in the DHSVM configuration (Crop, Grass, Shrub and Pasture have a single vegetation layer, and the app uses this height for it). Open has height 0 m.

### How it is processed

<!-- dynamic: decoding from scripts/defaults/build_place_defaults.py evh_lifeform() and height_for() -->

1. Count the EVH pixels whose centre falls in the place's 1 km cell, as for land cover (A.2).
2. Convert each EVH code to metres:

   | EVH code | Life form | Height |
   |---|---|---|
   | 101–199 | Tree | code − 100 m |
   | 201–299 | Shrub | (code − 200) / 10 m; 230 ("≥ 3.0 m") gives 3.0 m |
   | 301–399 | Herb | (code − 300) / 10 m; 310 ("≥ 1 m") gives 1.0 m |
   | 100 (sparse vegetation) and all non-vegetated codes | | excluded |

3. Average the heights of the pixels of the life forms the cell's land cover uses. This is the author's **new rule** (H. Yan, Nov 2026); his current table was made with an **earlier rule**, described under "Decisions and why" below:
   - forest covers (evergreen, deciduous, mixed): the **tree** pixels;
   - all other vegetated covers (shrub, grass, moss, crop, pasture and **wetland**): the **shrub and herb** pixels;
   - Open: no height.

   If the cell has no pixel of those life forms, the height is missing, and the app's rule makes the place Open (A.2, step 7). The `defaults` stage flags such places.
4. Round to 2 decimals.
5. Before the run, the height goes through the same rounding as the app's web form: metres → feet at 2 decimals → back to metres (× 0.3048).

### Decisions and why

- **Decoding.** The author confirmed this decoding, including 230 → 3.0 m and 310 → 1.0 m, and the exclusion of sparse and non-vegetated codes (H. Yan, Nov 2026). The missing-height rule reproduces his table: a cell has no height exactly where it has no vegetated EVH pixel (99.6% agreement).
- **The author's earlier rule (used for his current table).** The heights in the table the app ships ignore the land cover: each cell's `mean_height_m` is the average of two numbers, the mean height of its tree pixels and the mean height of its shrub pixels. We reproduce his table with this earlier rule to a median difference of 0.06 m, with no bias where a cell has both life forms. This confirms that we decode EVH and count pixels the same way he does. We use the earlier rule only for this check.
- **The author's new rule (step 3, the one we use).** The author replaced the earlier rule because NLCD and LANDFIRE classify independently: an NLCD shrub pixel can be a LANDFIRE tree pixel, so the life forms averaged should follow the cell's land cover (H. Yan, Nov 2026). He will republish his table with the new rule. We apply it to all places, including those whose land cover and LAI come from his table. Until his republished table confirms it, the heights are provisional. Compared with his current table, the new rule makes forest canopies taller and shrub and wetland canopies shorter.
- **The DHSVM 0.775 m limit for wetland.** The app runs Wetland as a tree overstory over an understory. For the Alaska vegetation cluster the understory is 0.51 m tall and the trunk space is 0.5 of the overstory height. DHSVM's wind-profile code (`CalcAerodynamic.c`, error 48 "Trunk space height below 'center' of lower boundary") then needs an overstory height of at least (0.13 + 0.63) × 0.51 m / 0.5 = 0.775 m. Below that, DHSVM stops and the app returns no curve. This also happens in the author's app: 54 of the 4,509 wetland cells in his own table are below 0.775 m. Because wetland heights come from shrub and herb pixels only, many wetland places are below the limit and have no curves; the `defaults` check names them (see [section 4](#issues)).
- **Sensitivity.** In the sensitivity test (A.3), changing height by ±2 m changed the 100-year NG depth by at most 1.5% (1 to 72 h). The author's new rule changes some heights by much more than that (forest canopies become several metres taller), so its effect on NG can be larger. Precipitation curves do not depend on height.

### Where in the code

`scripts/defaults/cell_counts.py`, `scripts/defaults/build_place_defaults.py` (`evh_lifeform`, `height_for`), `slurm/stages/defaults.sbatch`; the 0.775 m check is in the `defaults` stage of `ngidf/pipeline.py`; the form rounding is `ui_round_trip` in `ngidf/run_point.py`. Height rules were explored with `scripts/defaults/infer_height.py` and `scripts/defaults/explore_height.py`.

---

## A.5 WRF and CESM weather (hourly) {#in-wrf}

### Source

| Item | Value |
|---|---|
| Archive | NNA 4 km WRF output, `/import/beegfs/CMIP6/arctic-cmip6/NG-IDL-Full-Forcing/whole_AK_forcing/` (read-only; about 86 TB; `RAW_FORCING_ROOT`) |
| Grid | 662 × 782 cells, 4 km, polar stereographic; the same grid for all datasets |
| Files | One netCDF file per day with 24 hourly records (UTC), for example `WRF/historical/hsf/NNA.4km.hERA5.1989.003.wrf.hsf.1989-06-01.nc` |
| Author's files | `/import/beegfs/CMIP6/arctic-cmip6/NG-IDL/dhsvm_wrf_1hour/`, `dhsvm_cesm_1hour/`: 4,225 Interior cells (`AUTHOR_FORCING_ROOT`); used only to validate ours |

| Dataset | Archive folder | Description | Period of files |
|---|---|---|---|
| WRF_historical | `WRF/historical/hsf` | WRF driven by ERA5 reanalysis | 1 Jun 1989 to 30 Sep 2021 |
| WRF_medium | `WRF/pgw_medium/hsf` | Pseudo-global-warming, medium scenario | 1 Jun 2033 to 30 Sep 2065 |
| WRF_high | `WRF/pgw_high/hsf` | Pseudo-global-warming, high scenario | 1 Jun 2033 to 30 Sep 2065 |
| CESM_hist_LE2, 4, 7, 9 | `CESM2-LE/cesm2le/hC2LE{2,4,7,9}/hsf` | WRF driven by CESM2 Large Ensemble members 2, 4, 7, 9, historical | 1 Jun 1989 to 30 Sep 2021 |
| CESM_futu_LE2, 4, 7, 9 | `CESM2-LE/cesm2le/fC2LE{2,4,7,9}/hsf` | Same members, future | 1 Jun 2033 to 30 Sep 2065 |

<!-- dynamic: dataset folders from ngidf/forcing.py DATASETS; periods from each forcing stage's SUCCESS.json (first/last) -->

### What we use from it

Eleven variables at each place's 4 km cell, every hour: `T2`, `U10`, `V10`, `Q2`, `PSFC`, `SWDNB`, `GLW`, `RAINC`, `RAINNC`, `I_RAINC`, `I_RAINNC`.

### How it is processed

1. **Read once.** One Slurm task per dataset and year reads each daily file once and keeps only the 546 cells of our places, as stored (float32). Each task also reads the last file of the year before, so the rain series is continuous across years.
2. **Convert to DHSVM fields** with the author's formulas, in float32 arithmetic as in his files:

   <!-- dynamic: formulas from ngidf/forcing.py module docstring and convert(); UTC_OFFSET_H, BUCKET_MM -->

   | Field | Formula | Unit |
   |---|---|---|
   | Air temperature T | T2 − 273.15 | °C |
   | Wind speed W | √(U10² + V10²) | m/s |
   | Relative humidity RH | min(100 · e / es, 99.99), with e = Q2 · PSFC / (0.622 + 0.378 · Q2) and es = 611.2 · exp(17.67 · T / (T + 243.5)) (Bolton) | % |
   | Shortwave SW | SWDNB | W/m² |
   | Longwave LW | GLW | W/m² |
   | Precipitation P | hourly difference of RAINC + RAINNC + 100 · (I_RAINC + I_RAINNC); mm → m | m per hour |

   T, W, RH, SW and LW are rounded to 4 decimals. The first hour of each series has P = 0.
3. **Leap days (CESM only).** CESM uses a 365-day calendar. For each leap year we insert 29 February, hours 00 to 23 **UTC**, as the mean of the rounded 28 February and 1 March values at the same hour, with P = 0. This is done before the time shift, as the author does.
4. **Time zone.** Shift UTC to Alaska local standard time, UTC − 9 h, with no daylight saving. Each series then runs from 31 May 16:00 to 30 Sep 15:00 local (283,440 hours). The DHSVM run starts on 1 June 00:00.
5. **Write** one text station file per cell in the author's format: `MM/DD/YYYY-HH T W RH SW LW P`, six decimals.
6. **Validate** against the author's station files for every cell both sets have (49 of our 546 cells; all 283,440 hours). Tolerance is the last printed digit: 0.0001 for T, W, RH, SW and LW, and 0.000001 m (0.001 mm) for P.

### Result in this run

{{result:wrf}}

### Decisions and why

- **Extract only the cells we need, in memory.** Writing station files for the whole grid would take about 10 TB. Each variable is stored as a full-grid slab per hour, so a file has to be read whole anyway; we keep only the 546 cells.
- **Humidity formula.** The author's RH treats `Q2` as specific humidity and uses the Bolton saturation formula, capped at 99.99%. We found this by matching his files, and then confirmed it in his scripts (Nov 2026). The archive labels `Q2` "QV at 2 M", a water-vapour mixing ratio. For a mixing ratio the denominator would be 0.622 + Q2. We keep the author's formula. The difference is up to about 1 percentage point of RH.
- **Leap-day order.** Inserting 29 February before the shift to local time reproduces the author's CESM files hour for hour. Doing it after the shift does not: then 28 and 29 February, 15:00 to 23:00 local, differ in every leap year.
- **Rain from the bucket counters.** WRF stores accumulated rain in mm and empties its 100 mm "bucket" when it fills, counting each reset in `I_RAINC`/`I_RAINNC`. Adding back 100 mm per counted reset gives the true accumulation, and its hourly difference is the true hourly rain. The author's scripts instead add 100 mm only when the hourly difference is below −50 mm, and set negative values to 0. On a reset hour with 50 mm or more of rain in one component this sets the hour to 0. We keep the bucket counters, which give the correct amount. This differs from the author's files on such hours only (see [section 4](#issues)). None of our 49 shared cells has such an hour.
- **Fixed UTC − 9 h.** As in the author's files.
- **The forcing cell's terrain height is not used.** WRF and CESM terrain heights differ by up to 88 m at our cells, but the app never uses the forcing cell's elevation, so this has no effect.

### Where in the code

`ngidf/forcing.py` (`block`, `assemble`, `validate`; formulas in the module docstring and `convert`), `slurm/stages/forcing_block.sbatch`, `slurm/stages/forcing_assemble.sbatch`; stages `forcing_<dataset>` in `ngidf/pipeline.py`. The station files in use were produced on 17 Nov 2026 and adopted by the pipeline (see [section 4](#issues)).

---

## A.6 Daymet weather (3-hourly) {#in-daymet}

### Source

| Item | Value |
|---|---|
| Name | Daymet Version 4 R1, daily surface weather on a 1 km grid (Thornton et al. 2022, ORNL DAAC, doi:10.3334/ORNLDAAC/2129) |
| Access | ORNL Daymet single-pixel API, `https://daymet.ornl.gov/single-pixel/api/data`, one request per cell centre, 1989 to 2021 |
| Files | `raw/daymet_v4_pixels/pix_<lat>_<lon>.csv`, one per Daymet forcing cell (561 used) |
| Wind | WRF_historical hourly `U10`, `V10` from the archive in A.5 |
| Author's files | `/import/beegfs/CMIP6/arctic-cmip6/NG-IDL/dhsvm_daymet_3hour/`: 72,406 Interior cells; used only to validate ours |
| Disaggregation | MetSim 2.4.4 (MTCLIM), conda env from `config/metsim_environment.lock.txt` |

### What we use from it

Daily precipitation (`prcp`), maximum and minimum temperature (`tmax`, `tmin`), and the cell elevation from the file header. The author uses only `prcp`, `tmax` and `tmin` (H. Yan, Nov 2026). The run period is 1 Jun 1989 00:00 to 30 Sep 2021 21:00, at 3-hour steps.

### How it is processed

<!-- dynamic: recipe from ngidf/daymet_forcing.py module docstring; START, STOP -->

1. **Download** the Daymet series for each place's Daymet cell (A.1).
2. **Fill missing days.** Daymet drops 31 December in leap years. That day gets P = 0, and tmax and tmin are interpolated (the mean of 30 December and 1 January).
3. **Daily wind.** Find the 4 km WRF cell nearest the Daymet cell with the app's unscaled-degree rule over the full WRF grid. For each day, average that cell's hourly wind speed (√(U10² + V10²), each hour rounded to 4 decimals) over the WRF_historical file of that date (01:00 to 00:00 UTC).
4. **Disaggregate with MetSim** to 3-hour steps. Settings: `time_step = 180` min, `prec_type = uniform` (daily rain spread evenly over the eight steps), all other settings at their defaults (local solar time). Elevation = the Daymet pixel elevation. The 90 days before 1 June 1989 are the MetSim state.
5. **Humidity.** RH = min(100 · e / es, 99.99), with e = MetSim vapour pressure and es from the Bolton formula as in A.5. MetSim's own RH is not used: it adds an ice correction below 0 °C and comes out about 5 points higher in winter.
6. **Write** station files in the author's format (`MM/DD/YYYY-HH T W RH SW LW P`), values rounded to 4 decimals (P in m, 6 decimals).
7. **Validate** against the author's files for the 50 cells both sets have (all 94,480 steps).

### Result in this run

{{result:daymet}}

### Decisions and why

- **Reproduce the author's recipe rather than use his files.** His files cover the 72,406 Interior cells only. We first rebuilt the recipe from his files, then checked it against the scripts he sent (Nov 2026). They agree on: Daymet `prcp`/`tmax`/`tmin` only; MetSim with a 180-minute step and default settings otherwise (uniform precipitation, no UTC offset); 90 days of state; daily wind as the mean of the hourly WRF file; missing Daymet days filled with P = 0 and interpolated temperature; RH from MetSim humidity with the Bolton formula, capped at 99.99%.
- **Three known differences from his scripts remain** (all in [section 4](#issues)):
  - *Wind cell.* His script picks the WRF cell that is nearest on the globe (great-circle). Ours uses the app's unscaled-degree rule. For 48 of our 561 Daymet cells the two rules pick different WRF cells. This explains all 5 wind mismatches among the 50 shared cells.
  - *Elevation.* MetSim computes radiation and humidity from elevation. His script uses the mean elevation of each 1 km cell from a file we do not have (`daymet_1km_mean_elevation.csv`). We use the Daymet pixel elevation. This explains the small SW, LW and RH differences: the SW difference at each shared cell corresponds to an elevation difference of −60 to +90 m.
  - *Days with tmax below tmin.* His script swaps tmax and tmin on such days before MetSim. Ours does not. None of the 561 Daymet series we downloaded has such a day between 3 Mar 1989 and 30 Sep 2021, so the swap would not change our inputs.
- **Wind from WRF_historical**, as the author does, because Daymet has no wind.
- **Durations.** The app fits only the 24, 48 and 72 h durations for Daymet, because sub-daily timing comes from MetSim's uniform spreading, not from observations. The 1 to 12 h durations are nodata for Daymet.

### Where in the code

`ngidf/daymet_forcing.py` (`wind`, `run`, `validate`), `scripts/daymet/fetch_daymet_pixels.py` (download), `slurm/stages/daymet_wind.sbatch`, `slurm/stages/daymet_run.sbatch`; stage `forcing_Daymet` in `ngidf/pipeline.py`. The recipe was worked out with `scripts/daymet/metsim_probe.py`.

---

## A.7 The author's model {#in-app}

### Source

| Item | Value |
|---|---|
| Name | NG-IDF app, H. Yan (PNNL) |
| Upstream | {{upstream_repo}}, branch `{{upstream_branch}}` |
| Commit | `{{app_commit}}` |
| Mirror | {{app_repo}}, tag `{{app_ref}}` (private; the same commit) |
| Version file | `config/model_versions/{{model_label}}.env` |
| Checkout | `$DATA_ROOT/app/NG_IDF_AWS` (sparse checkout without `spatial_map/`) |

<!-- dynamic: commit, repo, tag from config/model_versions/<CURRENT>.env; method settings from the app stage report (tables.method) -->

The upstream repository has no licence file, so we do not copy the app into our repository. The pipeline fetches the pinned commit and checks its hash.

### What we use from it

| Part | What it does |
|---|---|
| `dhsvm_idf.py` (`generate_ng_idf`) | Writes the DHSVM configuration for one point from the template `example_config/Input.Snotel.T4` |
| `dhsvm/no_sat_dump/` | DHSVM 3.2 source code and the author's makefile |
| `input/` | The app's 3 × 3 cell model domain (500 m DEM, fixed soils and initial state) |
| `example_config/param_5cluster_ensembleMean_CONUS.csv` | Snow parameters. All Alaska rows are identical: albedo decay parameters 0.93362 (accumulation) and 0.90294 (melt), maximum albedo 0.84932, snow threshold `TSnow` 3.25039 °C, rain threshold `Train` −1.50284 °C, cluster 1 |
| `example_config/veg_param_type_cluster.csv` | Vegetation parameters by land cover and cluster |
| `extract_AM.py` (`extract_AM_data`) | Water-year annual maxima of 1, 3, 6, 12, 24, 48 and 72 h moving sums of precipitation (P) and of water reaching the ground (W_veg, the "NG" variable), with the rain / snowmelt / rain-on-snow label of each W_veg maximum |
| `get_IDF.R` | Drops the first annual maximum; fits a Gumbel distribution by L-moments (R package `lmom`); quantiles at 51 non-exceedance probabilities (0.50 to 0.99 by 0.01, plus 0.998, that is 2 to 100 and 500 years); 90% confidence interval from 500 parametric bootstrap samples (5th and 95th percentiles) |
| `app.py` | The web app. We do not run it, but follow its code path (`get_NG_IDF`), its default inputs and its CESM near-term windows (1 Jan 2005 to 30 Sep 2021, and 1 Jan 2033 to 30 Sep 2049) |

The pipeline reads the method settings (distribution, bootstrap size, CI percentiles, probabilities, model output columns) from the app's code at run time, so a change in a new version is reported, not assumed.

### How each run uses it

`ngidf/run_point.py` calls the app's own functions in the same order as `app.py:get_NG_IDF`: `generate_ng_idf` → `dos2unix` on the configuration → DHSVM → `extract_AM_data` (full period; plus the near-term window for CESM) → `get_IDF.R` → read the IDF files and round to 0.01 mm. Inputs are what the app's web form would submit for the place: latitude and longitude to 5 decimals, LAI to 2 decimals, height via feet to 2 decimals, land-cover fraction 1, and the form's advanced defaults (rain LAI multiplier 0.001, snow LAI multiplier 0.005, maximum snow interception 0.02 m, interception efficiency 0.6).

<!-- dynamic: ADVANCED_DEFAULTS, NEAR_TERM, seed_for from ngidf/run_point.py -->

The app reads its inputs from fixed relative paths. Each run therefore works in its own temporary folder that holds copies of, or links to, the app's files. That folder differs from the app in these ways only:

| Change | Why |
|---|---|
| `static/wrf_cesm_coordinates.txt` (or `daymet_coordinates.txt`) lists one cell: the one chosen for the place with the app's own rule (A.1) | The app ships coordinates for its own cells. With one entry, its lookup returns the cell we chose |
| One row is added to `param_5cluster_ensembleMean_CONUS.csv`: the forcing cell's coordinates with the Alaska snow parameters | The app looks up snow parameters by an exact coordinate match. All Alaska rows are identical, and no other Alaska values exist, so the values are the ones the app uses anywhere in Alaska |
| `met/<dataset>/data_<lat>_<lon>` links to our station file (A.5, A.6) | The app ships weather for its own cells only |
| `dhsvm/no_sat_dump/DHSVM3.2` links to our build (below) | The shipped binary is a Cray build that does not run on Chinook |
| `get_IDF.R`: `library(lmom, lib.loc='/hongxiang/app/Rlibrary')` becomes `library(lmom)` | That library path exists only on the author's server; `lmom` 3.3 is in our R 4.5.3 environment |
| `get_IDF.R`: `set.seed(<seed>)` is added as the first line. Seed = CRC-32 of "place ID \| dataset \| window", one seed for the full period and one for the near-term window | Makes the bootstrap CI reproducible. The fitted values do not depend on the seed; the CI differs from any single app run only by Monte Carlo noise |

Every run saves `adaptations.diff` (each changed file against the app's original) and `config_vs_template.diff` (the DHSVM configuration the app wrote, against its template). The QA stage checks that all 6,709 runs differ from the app only in these ways.

The app also leaves some template settings unchanged for every point, and we keep them as they are: the basin centre (37.97° N, 119.48° W), the time-zone meridian (−120°), and the 3 × 3 DEM and soils.

### The DHSVM build

<!-- dynamic: sha256, compiler, warnings, errors from the dhsvm stage report (build.json) -->

| Item | Value |
|---|---|
| Source | `dhsvm/no_sat_dump/` of the pinned commit, built with the author's `makefile_for_binary` |
| Compiler | conda-forge GCC 15.3.0 |
| Flags | The makefile's own (`-g -Wall -DHAVE_X11`, no optimisation), plus `-fcommon -std=gnu17 -fpermissive` |
| Result | `DHSVM3.2`, SHA-256 `de917699…3c14ff`; 0 errors, 109 warnings |

The three added flags restore the behaviour of the older GCC versions the author built with. Newer GCC turns some old warnings into errors. The one place this hits (`DHSVMChannel.c:107`, a misplaced parenthesis in the road-network reader) is code the app never runs, because the point domain has no roads.

### Decisions and why

- **Run the app's code, do not rewrite it.** The wrapper imports the app's modules and calls them. It changes only what batch running requires (table above).
- **Reference runs before production.** The `reference` stage runs 5 Interior places (one per land cover: Chena Hot Springs, Central, Murphy Dome, Salcha, Fairbanks) for Daymet, WRF_historical and CESM_hist_LE2 on the author's own station files and his own defaults table. Then only the wrapper and the DHSVM build differ from his app. It also checks that the `Pixel.CENTER` columns `extract_AM.py` reads by position hold the expected fields (W_veg, Precip, P_int, deltaSWE, Swq). When output of the author's app for these points is supplied, the stage compares the fitted values with it to 0.01 mm.
- **Model versions as files.** A new app version is a new file in `config/model_versions/`, mirrored as a tag. Only the stages that read the app run again, and the app stage reports what changed in the method.

### Where in the code

`ngidf/run_point.py` (one run), `ngidf/run_batch.py` (batch driver), `ngidf/appinfo.py` (method settings read from the app), `scripts/setup/fetch_app.sh`, `scripts/setup/build_dhsvm.sh`, `scripts/tests/reference_runs.py`, `config/model_versions/{{model_label}}.env`; stages `app`, `dhsvm`, `reference`, `runs` in `ngidf/pipeline.py`.

---
