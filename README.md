# ng-idf_curation

Precomputed **NG-IDF** (next-generation intensity–duration–frequency) and precipitation-IDF curves for the 565 Alaska places listed at [earthmaps.io](https://earthmaps.io/places/communities). They are packaged as Rasdaman coverages, so the data API can return a place's curves as numbers ready for plotly.

Phase 1 (this repo, now) covers the places. Phase 2 (planned) will cover the 4 km grid wall to wall.

## Method: the author's app, 100%

We are not hydrologists. **Every scientific choice follows Hongxiang Yan's NG-IDF app**: [`hydro-yan/NG_IDF_AWS`](https://github.com/hydro-yan/NG_IDF_AWS), branch `feature/add_spatial_map`, commit `a582a5c` (pinned in [`config/app.env`](config/app.env)). For each place and forcing dataset we run the app's own code:

1. `dhsvm_idf.generate_ng_idf` writes the DHSVM 3.2 configuration for the app's 3×3 point domain.
2. DHSVM 3.2, built from the app's source, simulates the full period.
3. `extract_AM.extract_AM_data` computes water-year annual maxima of 1, 3, 6, 12, 24, 48 and 72 h moving sums. It does this for precipitation (P) and for water reaching the ground (W_veg, the "NG" variable).
4. `get_IDF.R` (R `lmom`) drops the first annual maximum and fits a Gumbel distribution by L-moments. It reports quantiles at 51 non-exceedance probabilities (0.50–0.99 by 0.01, plus 0.998), with a 90% CI from a 500-sample parametric bootstrap.
5. Values are rounded to 0.01 mm, as in the app. They are depths in mm over the duration.

Batch adaptations (none changes the method):

| Adaptation | Why |
|---|---|
| `ngidf/run_point.py` calls the app functions directly, the same path as `app.py:get_NG_IDF`, and reproduces the web form's rounding of inputs | Batch execution |
| Land cover, LAI and height come from the author's Interior table where it covers the place. Elsewhere they come from a statewide rebuild from the same sources (NLCD 2016, GLASS LAI 2016, LANDFIRE 2016 EVH) on the same Daymet 1 km grid | The shipped table covers Interior AK only |
| WRF/CESM station files are extracted from the NNA 4 km archive with the author's conversions | The app ships forcing for one cell. **Validated against the author's own station files to text precision** |
| Daymet station files are rebuilt with the author's recipe: Daymet v4 daily P/Tmax/Tmin, MetSim (MTCLIM, 3-hourly, uniform precipitation), daily WRF wind, Bolton RH | The author's Daymet files cover Interior AK only. **Validated against them:** wind and P exact, T to 1e-4. SW and RH are within 0.3% where elevation sources differ |
| The forcing cell is chosen with the app's own nearest-cell rule, applied over the full 4 km grid | Statewide coverage |
| Snow parameters: the single Alaska row of the app's table | It is the only Alaska parameter set |
| `set.seed()` per run before `get_IDF.R` | Reproducible bootstrap CI |
| `get_IDF.R`'s hard-coded `lib.loc` is dropped | Our R library location |

App behaviours we reproduce rather than correct:

- **First annual maximum dropped.** The first annual maximum is dropped even though the series already starts on 1 October. Full-period fits therefore use 31 water years, and near-term fits 15.
- **Template location settings.** The DHSVM basin centre and time-zone meridian keep the app's template values.
- **Nearest-cell rule.** The forcing cell is the nearest by unscaled degrees of latitude and longitude.
- **Daymet durations.** Daymet runs report only the 24, 48 and 72 h durations.

## Coverages

Both are place-indexed. All axes are integer indices with an `encoding` attribute, a Python-literal dict from index to label, which `ast.literal_eval` can read (the data-API convention).

### `ngidf_places`: the curves

| Axis | Size | Labels |
|---|---|---|
| `location` | 565 | earthmaps place id (`AK1` …) |
| `dataset` | 24 | `Daymet_historical`; `WRF_historical/medium/high`; `CESM_{hist,futu}_LE{2,4,7,9}` (full period); the same 8 with `_nearterm`; `CESM_{hist,futu}_ensemble_mean[_nearterm]` |
| `variable` | 2 | `P` (precipitation IDF), `W_veg` (NG-IDF) |
| `duration` | 7 | 1, 3, 6, 12, 24, 48, 72 h (Daymet: 24/48/72 only) |
| `exceedance` | 51 | non-exceedance probability p. Return period = 1/(1−p): 2 … 100, 500 yr |

Bands are float32, in mm, with nodata −9999:

| Band | Meaning |
|---|---|
| `magnitude` | Fitted depth |
| `ci_lower`, `ci_upper` | 90% CI. Nodata for the ensemble-mean rows; the app computes none |
| `member_min`, `member_max` | Ensemble-mean rows only: the range of the 4 CESM members, which the app shades |

The ensemble mean is the arithmetic mean of the 4 members' magnitudes, as in the app.

### `ngidf_places_am`: the annual maxima behind each curve

These let a plot show the empirical points.

- **Axes:** `location`, `dataset` (the 12 full-period runs), `variable`, `duration`, `am_index` (0–32).
- **Bands:**
  - `am_depth` (mm)
  - `water_year`
  - `peak_date` (days since 1970-01-01)
  - `mechanism` (W_veg: 1 rain, 2 snowmelt, 3 rain-on-snow)
  - `used_in_fit` (0 for the dropped first year)

Run inputs per place (forcing cells, land cover, LAI, height, and whether they came from the author's table) ship as `ngidf_places_inputs.csv`. Global metadata carries the method statement, the adaptations, provenance and the list of nodata places.

## Layout

```
config/            app pin (app.env), conda env spec + lock
data/places/       generated tables (not tracked): places_ak.csv, place_defaults.csv
ngidf/             forcing.py (extract/assemble/validate), run_point.py, run_batch.py, build_coverage.py
scripts/setup/     fetch_app.sh (pinned sparse clone), build_dhsvm.sh
scripts/places/    build_place_table.py
scripts/defaults/  reverse-engineering of the author's defaults table + per-place defaults
scripts/tests/     smoke test on the author's own forcing
recipes/           wcst_import recipes (not ingested)
slurm/             job scripts (t2small / tier2)
```

Large data lives outside the repo, in `/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/`:

| Directory | Contents |
|---|---|
| `raw/` | Downloaded inputs |
| `app/` | Pinned app checkout |
| `envs/` | Conda environments |
| `build/` | DHSVM build |
| `work/` | Intermediates |
| `runs/` | Per-run outputs |
| `output/` | Coverage files |

## Reproduce

```bash
source config/app.env
scripts/setup/fetch_app.sh                                   # pinned app → $DATA_ROOT/app/NG_IDF_AWS
CONDA_PKGS_DIRS=$DATA_ROOT/conda_pkgs conda env create -p $NGIDF_ENV -f config/environment.yml
# (DHSVM is built by the smoke-test job, or directly: conda activate $NGIDF_ENV && scripts/setup/build_dhsvm.sh)
python -I scripts/places/build_place_table.py ...            # see the script docstring
sbatch slurm/place_defaults_inputs.sbatch                    # NLCD/EVH/GLASS per defaults cell
python -I scripts/defaults/build_place_defaults.py data/places/places_ak.csv \
    $DATA_ROOT/app/NG_IDF_AWS/static/gridcell_current_lulc.csv $DATA_ROOT/work/place_defaults data/places/place_defaults.csv
# forcing: one array per dataset (33 one-year blocks), then assemble + validate against the author's files
sbatch --array=0-32%2 slurm/forcing_block.sbatch WRF_historical    # … for each of the 11 datasets
sbatch slurm/forcing_assemble.sbatch WRF_historical
# Daymet forcing (Daymet v4 1 km + MetSim 3-hourly + daily WRF wind, the author's recipe)
python3 -I scripts/daymet/fetch_daymet_pixels.py data/places/places_ak.csv $DATA_ROOT/raw/daymet_v4_pixels
sbatch --array=0-32%10 slurm/daymet_wind.sbatch                   # daily WRF-historical wind per Daymet cell
sbatch --array=0-7 slurm/daymet_run.sbatch 8                      # MetSim → station files (env: config/metsim_environment.yml)
$DATA_ROOT/envs/msim/bin/python -I ngidf/daymet_forcing.py validate --ours-dir $DATA_ROOT/work/forcing/Daymet
# model runs (repeat with --datasets Daymet for the Daymet runs)
python -I ngidf/run_batch.py manifest --forcing-root $DATA_ROOT/work/forcing --out $DATA_ROOT/work/runs.csv
sbatch --array=0-7 slurm/run_batch.sbatch $DATA_ROOT/work/runs.csv 8
# coverages
python -I ngidf/build_coverage.py --runs-root $DATA_ROOT/runs --out-dir $DATA_ROOT/output
```

Before ingesting, follow the `rasdaman-audit` checklist:

1. Run `wcst_import.sh recipes/ngidf_places.json --analyze`.
2. Check the metadata: `ncdump -h ngidf_places.nc | python3 rasdaman_metadata_check.py --text -`.

## Status

The forcing extraction, model runs and coverage assembly scripts are in place. Not yet known:

- the exact LAI and canopy-height products the author used;
- the author's mapping for NLCD lichen/moss;
- the elevation the author gave MetSim at some Interior cells. This causes a ≤ 0.3% shortwave difference.

Rebuilt defaults are therefore labelled `rebuilt_provisional`. Tests show that LAI ±0.1 and height ±2 m move the 100-year NG values by at most 1.5% and leave precipitation curves unchanged.
