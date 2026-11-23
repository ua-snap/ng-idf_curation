# ng-idf_curation

Precomputed **NG-IDF** (next-generation intensity–duration–frequency) and precipitation-IDF curves for the 565 Alaska places listed at [earthmaps.io](https://earthmaps.io/places/communities). They are packaged as Rasdaman coverages, so the data API can return a place's curves as numbers ready for plotly.

Phase 1 (this repo, now) covers the places. Phase 2 (planned) will cover the 4 km grid wall to wall.

## Method: the author's app, 100%

We are not hydrologists. **Every scientific choice follows Hongxiang Yan's NG-IDF app**: [`hydro-yan/NG_IDF_AWS`](https://github.com/hydro-yan/NG_IDF_AWS), branch `feature/add_spatial_map`, commit `a582a5c` (pinned in [`config/model_versions/a582a5c.env`](config/model_versions/a582a5c.env)). For each place and forcing dataset we run the app's own code:

1. `dhsvm_idf.generate_ng_idf` writes the DHSVM 3.2 configuration for the app's 3×3 point domain.
2. DHSVM 3.2, built from the app's source, simulates the full period.
3. `extract_AM.extract_AM_data` computes water-year annual maxima of 1, 3, 6, 12, 24, 48 and 72 h moving sums. It does this for precipitation (P) and for water reaching the ground (W_veg, the "NG" variable).
4. `get_IDF.R` (R `lmom`) drops the first annual maximum and fits a Gumbel distribution by L-moments. It reports quantiles at 51 non-exceedance probabilities (0.50–0.99 by 0.01, plus 0.998), with a confidence interval from a 500-sample parametric bootstrap (90% at `a582a5c`; the level is read from `get_IDF.R`, and the author's next version uses 95%).
5. Values are rounded to 0.01 mm, as in the app. They are depths in mm over the duration.

Batch adaptations (none changes the method):

| Adaptation | Why |
|---|---|
| `ngidf/run_point.py` calls the app functions directly, the same path as `app.py:get_NG_IDF`, and reproduces the web form's rounding of inputs | Batch execution |
| Land cover and LAI come from the author's Interior table where it covers the place. Elsewhere they are rebuilt statewide with the author's rules from the same sources (NLCD 2016, GLASS LAI 2016 V60 500 m, LANDFIRE 2016 EVH) on the same Daymet 1 km grid. Height uses the author's current rule everywhere (forest: EVH tree pixels; other vegetated covers: shrub and herb pixels), because his table predates it. Moss (NLCD 73, 74) runs as DHSVM code 6, the code the app's Moss card sends | The shipped table covers Interior AK only |
| WRF/CESM station files are extracted from the NNA 4 km archive with the author's conversions | The app ships forcing for one cell. **Validated against the author's own station files to text precision** |
| Daymet station files are rebuilt with the author's recipe: Daymet v4 daily P/Tmax/Tmin, MetSim (MTCLIM, 3-hourly, uniform precipitation), daily WRF wind, Bolton RH | The author's Daymet files cover Interior AK only. **Validated against them:** P exact; T exact except at 3 of 50 cells (up to 0.026 °C, cause unknown); wind exact except where the author's great-circle wind-cell rule picks another cell. SW and RH are within 0.3%, because the author gave MetSim the 1 km cell-mean elevation and we use the Daymet pixel elevation |
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
| `ci_lower`, `ci_upper` | Confidence interval (level in the band metadata; 90% at `a582a5c`). Nodata for the ensemble-mean rows; the app computes none |
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
config/            model_versions/<label>.env (which app commit), paths.env (site paths), env.sh (job setup),
                   conda lock files: environment (runs), metsim, geo (rasters), report
data/places/       tables from the pre-pipeline runs (not tracked)
ngidf/             pipeline.py (stage runner), appinfo.py (method settings read from the app's code),
                   forcing.py, daymet_forcing.py, run_point.py, run_batch.py, build_coverage.py, inputs_audit.py
ngidf/qa/          model_change.py, run_qa.py, compare_release.py, report.py (HTML report)
scripts/setup/     fetch_app.sh (pinned app), build_dhsvm.sh, create_env.sh
scripts/places/    build_place_table.py
scripts/defaults/  defaults rebuild (cell_counts.py, cell_lai.py, build_place_defaults.py) + reverse-engineering
scripts/tests/     reference_runs.py (author's own inputs; comparison with his app output)
slurm/stages/      one job script per pipeline stage; slurm/*.sbatch are research jobs outside the pipeline
recipes/           wcst_import recipes (not ingested)
```

Large data lives outside the repo, in `DATA_ROOT` (`config/paths.env`):

| Directory | Contents |
|---|---|
| `raw/` | Downloaded inputs, with `SHA256SUMS` |
| `stages/<stage>/<fingerprint>/` | Pipeline stage outputs: `out/`, `logs/`, `job.env`, `stage.json`, `report.json` |
| `releases/<name>/` | `release.json`, all stage reports, `report.html`, link to the coverage |
| `envs/`, `app/`, `work/`, `runs/`, `output/` | From before the pipeline (2026-11-17); some are adopted by stages |

## Pipeline

`ngidf/pipeline.py` runs the work as stages:

1. Environments, app checkout and source-data checksums.
2. Places, defaults, and the forcing (11 WRF/CESM datasets and Daymet).
3. DHSVM build, then reference runs on the author's own inputs.
4. Production runs, then coverage, then QA and the HTML report.

Each stage writes into `stages/<stage>/<fingerprint>/`. The fingerprint is a hash of exactly what the stage reads: its code, input content, parameters and environment. A stage whose report passed is skipped, and nothing is overwritten. The Prefect flow (`ua-snap/prefect`, `ng_idf/`) drives the same commands and turns each stage's `report.json` into artifacts.

```bash
P="$NGIDF_ENV/bin/python -I ngidf/pipeline.py"        # any Python >= 3.9 works for the env stages
$P info                                               # model version, curation commit, data root
$P plan                                               # every stage: done / todo / waiting
$P submit --stage places --wait                       # prepare + sbatch + finalize (manual use)
$P submit --stage runs; $P finalize --stage runs      # what the Prefect flow calls, waiting in between
$P retire --stage runs                                # move a failed attempt aside to run it again
$P adopt --stage forcing_WRF_historical --source <dir> --note "..."   # reuse outputs made before the pipeline
$P release --name <name>                              # once every stage passed
```

Every command prints one JSON document on stdout. The Prefect flow parses those documents.

A stage's checks can be run again at any time with `finalize`, which leaves its outputs untouched.

The "curation code committed" check asks whether that stage's own code files, the ones in its fingerprint, are in `HEAD`. Edits elsewhere in the repo do not mark it.

The `qa` fingerprint includes every stage's check results, because the report shows them. Re-finalizing a stage whose checks change therefore rebuilds the report.

### A new model version

1. Mirror the upstream commit into `ua-snap/NG_IDF` as tag `app-<sha7>`.
2. Copy `config/model_versions/a582a5c.env` to `<sha7>.env` and set the commit. Set `BASELINE_MODEL` to the previous label.
3. Write the label to `config/model_versions/CURRENT`, or pass `--model-version`.
4. Run the pipeline.

Only the stages that read the app rerun: app, DHSVM build, reference, runs, coverage and QA. The app stage then reports what changed in the author's code, including method settings such as the CI level and the `Pixel.CENTER` columns. The QA report compares the new curves with the baseline release.

## Status

The forcing extraction, model runs and coverage assembly scripts are in place. Defaults follow the author's described rules: the LAI rule reproduces his table's `max_LAI` exactly at 98% of his 72,406 cells, and land cover agrees at 97.8%. Not yet confirmed:

- canopy heights under the author's new rule, until he republishes his table (`defaults_source = rebuilt_provisional` marks rebuilt places);
- the DHSVM class, LAI and height the author intends for moss;
- the elevation the author gave MetSim (the 1 km cell mean of an unknown DEM). This causes a ≤ 0.3% shortwave difference.

Tests show that LAI ±0.1 and height ±2 m move the 100-year NG values by at most 1.5% and leave precipitation curves unchanged.
