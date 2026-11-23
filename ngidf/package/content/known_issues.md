<!-- Section 4 of the QC package. One "## " per issue. Checks named as `stage` / `check name` (exactly as in
     ngidf/pipeline.py) are shown with their result in this run. -->
Each issue says what it is, how it affects the results, and what is open or planned. Where a pipeline check detects the issue, the result of that check in this run is shown with it.

## Wetland canopies below DHSVM's 0.775 m limit

**What it is.** The app runs the Wetland cover as a tree overstory over an understory. For the Alaska vegetation cluster the understory is 0.51 m tall and the trunk space is 0.5 of the overstory height. DHSVM's wind-profile code then needs an overstory at least (0.13 + 0.63) × 0.51 m / 0.5 = 0.775 m tall. Below that, DHSVM stops with error 48 ("Trunk space height below 'center' of lower boundary") and no curve is produced. The author's app behaves the same way: 54 of the 4,509 wetland cells in its own defaults table are below 0.775 m.

**Impact.** The places below the limit have no curves for any dataset; they are named in the check results below. The coverage holds nodata for them, and the file metadata names them with the reason. Under the author's height rule, wetland heights come from shrub and herb pixels only, so many wetland places are affected, including places inside the author's own table.

**Open.**
- The fix is the author's to choose. Two workarounds were tested at a few places:
  - raising the height to 0.78 m gives results close to neighbouring taller wetland cells;
  - running the place as Open gives much higher NG: 5–55% higher at Bethel and 28–150% higher at Utqiaġvik (100-year, 24-hour NG).
- It is also open whether the Wetland class (trees over shrubs) is meant to represent treeless tundra wetland.
- The author's republished table will show how many of his own wetland cells fall below the limit under his height rule.

**Detected by.**
- `defaults` / `wetland canopies tall enough for DHSVM (0.775 m or more)`
- `runs` / `runs completed`
- `runs` / `every failure has a known cause`: this check fails if any run stops for another reason.

## Provisional defaults: heights and moss not yet confirmed by the author

**What it is.** Land cover, LAI and canopy height follow the rules the author described (H. Yan, Nov 2026); Appendix A.2 to A.4 give them in full. Places inside the author's Interior table take his land cover and LAI; all others are rebuilt (`defaults_source = rebuilt_provisional`). Three parts are not yet confirmed against the author's own output:

| Input | Status |
|---|---|
| Land cover | The author's rule. Agrees with his table at 97.8% of his 72,406 cells |
| LAI | The author's rule. Reproduces his table's `max_LAI` exactly at 98% of his cells (check below) |
| Height | The author's new rule (forest: tree pixels; other vegetated covers: shrub and herb pixels). His current table was made with an earlier rule, so the new heights can be checked only against the table he will republish. Applied to every place, including those inside his table |
| Moss (NLCD 73, 74) | A class of its own, as the author confirmed. Run as DHSVM code 6 (grass), the code the app's Moss card sends; the author has not confirmed the code, LAI or height for moss. Lichen and moss rarely dominate a cell near a community |

**Impact.**
- **Precipitation curves:** none. Land-cover parameters do not enter them.
- **NG curves:** the new height rule changes heights by several metres in places (forest canopies taller, shrub and wetland canopies shorter), much more than the ±2 m that changed the 100-year NG depth by at most 1.5% in a sensitivity test. Its effect is shown by the comparison with the previous release ([section 3.8](#change)). Wetland places below 0.775 m get no curves (see the first issue).
- **Land cover:** places whose top two classes differ by less than 5% of the cell (`nlcd_margin`) could change class under a small change in method.

**Planned.** Check the heights against the author's republished table, and the moss settings against his answer.

**Detected by.**
- `defaults` / `LAI rule reproduces the author's table (max_LAI, all cells)`
- `defaults` / `rebuilt land cover matches the author's table at his places`
- `defaults` / `moss places run with the DHSVM class the app's Moss card sends (6, grass)`: shown only when a place is moss-dominated.
- `defaults` / `every vegetated place has a canopy height`: shown only when a vegetated place has no EVH pixel of the life forms its cover uses, so that the app runs it as Open.

## Daymet: wind cell rule

**What it is.** Daymet has no wind, so the author takes daily wind from the nearest WRF_historical 4 km cell. His script finds that cell by great-circle distance on the full WRF grid. Our pipeline uses the app's forcing-cell rule (nearest by unscaled degrees of latitude and longitude). For 48 of our 561 Daymet cells (48 places) the two rules pick different WRF cells.

**Impact.**
- Affects the Daymet curves of those 48 places only.
- At the 50 cells shared with the author's files, the daily wind differs at 5 cells, all among the 48. On single days the difference is up to 7.6 m/s.
- Wind does not change precipitation, so P curves are unaffected.
- The effect on NG curves has not been measured.

**Planned.** Switch to the author's great-circle rule, then rerun the Daymet validation against his files.

**Detected by.** `forcing_Daymet` / `wind matches the author's files`

## Daymet: elevation used for radiation and humidity

**What it is.** MetSim computes shortwave and longwave radiation and humidity using the cell's elevation. The author uses the mean elevation of each 1 km cell, from a file we do not have (`daymet_1km_mean_elevation.csv`; its DEM is not known to us). We use the Daymet pixel elevation that the Daymet single-pixel service reports.

**Impact.**
- Affects all Daymet curves, slightly.
- At the 50 shared cells, the largest differences from the author's files are 2.04 W/m² for SW, 0.12 W/m² for LW and 0.33 percentage points for RH.
- The SW bias per cell is between −0.43 and +0.31 W/m², at most 0.3%.
- The SW differences correspond to elevation differences of −60 to +90 m.
- Precipitation and temperature are not affected.
- The effect on NG curves has not been measured. It is expected to be small next to the defaults effects above.

**Planned.** Use the cell-mean elevation once the file, or the DEM and method behind it, is available. Then rerun the Daymet validation.

**Detected by.** `forcing_Daymet` / `SW/LW/RH match the author's files`

## Daymet: temperature residual and the tmax/tmin swap

**What it is.**
- On days when Daymet's maximum temperature is below its minimum, the author's script swaps the two before MetSim. Our pipeline does not.
- None of the 561 Daymet series we use has such a day between 3 March 1989 and 30 September 2021, so the swap would not change our inputs.
- Separately, temperature differs from the author's files at 3 of the 50 shared cells, by at most 0.026 °C. Its cause has not been identified.

**Impact.** Negligible. At most 0.026 °C at 3 Interior cells; the other 47 shared cells match to 0.0001 °C.

**Planned.** Add the swap so the code matches the author's script.

**Detected by.** `forcing_Daymet` / `T matches the author's files (within 0.03 C)`. The check warns above 0.03 °C.

## Daymet: the author's validation files predate his patch

**What it is.** The author has patched about 120 Interior cells of his Daymet station files that had missing forcing. Our local copy of his files, which we use only to validate our own Daymet files, is from before the patch.

**Impact.** None on our results: our Daymet files are built from Daymet itself. If any of the 50 shared cells were among the patched cells, the validation would compare against the old version.

**Detected by.** None.

## The author's WRF/CESM rain on bucket-reset hours

**What it is.** WRF stores accumulated rain and empties its 100 mm "bucket" when it fills, counting each reset in `I_RAINC` and `I_RAINNC`.
- **The author's scripts** compute hourly rain separately for each rain component. Where the hourly difference is below −50 mm they add 100 mm, and they set any remaining negative value to 0. On a reset hour the difference is (rain − 100 mm). So on an hour with 50 mm or more of rain in one component, the reset is not detected and the hour is set to 0.
- **Example:** cell `65.05018_-145.92638`, CESM future LE2, 19 Jul 2038 03:00 local. The author's file has P = 0. The archive gives 54.26 mm: `RAINNC` falls from 73.79 to 28.05 mm while `I_RAINNC` goes from 36 to 37.
- **Our extraction** uses the bucket counters, P = hourly difference of RAINC + RAINNC + 100 · (I_RAINC + I_RAINNC). This gives the true amount.

**Impact.**
- Our results are not affected; our rain is correct.
- The author's own station files, and so his live app, lose the rain of such hours. These hours are rare but among the largest, which matters most for IDF curves.
- For places in his domain, our curves can therefore be higher than his app's where his files contain such hours.
- The cell in the example is not one of our places' cells. None of the 49 cells we share with his files has such an hour in any of the 11 datasets.
- The number of affected hours across all our 546 cells has not been counted.

**Planned.** Report the bug to the author. Count the affected hours in our cells.

**Detected by.** `forcing_<dataset>` / `P matches the author to the printed precision`, for each of the 11 WRF/CESM datasets. Hours where the author's file has 0 and ours has 50 mm or more are counted separately (`P_known_bucket_reset`), and they turn the check into a warning with an explanation. Only cells shared with the author's files are checked.

## WRF humidity formula (reproduced)

**What it is.** The archive labels `Q2` "QV at 2 M" (kg/kg), a water-vapour mixing ratio. The author's RH formula, e = Q2 · PSFC / (0.622 + 0.378 · Q2), is the form for specific humidity. For a mixing ratio the denominator would be 0.622 + Q2. We reproduce the author's formula, so our files match his.

**Impact.** RH can be lower than with the mixing-ratio form, by up to about 1 percentage point. Applies to all WRF and CESM datasets. Precipitation is not affected.

**Open.** Whether the author intends the specific-humidity form.

**Detected by.** None. The forcing checks confirm that we match the author.

## The coming soil-temperature version of DHSVM

**What it is.** The author is releasing a DHSVM version with soil temperature and updated snow parameters, planned for the end of 2026. It needs a 30-year spin-up. It is developed on the `add_Tsoil` branch of his repository. Compared with the pinned commit `a582a5c`, that branch also changes:
- `get_IDF.R`: the confidence interval goes from **90% (5th–95th percentiles) to 95% (2.5th–97.5th percentiles)**;
- the DHSVM configuration template: new keys `SOIL TEMPERATURE MODEL = TRUE` and `Surface Emissivity`;
- `extract_AM.py`: adds active-layer depth for Daymet.

**Impact.**
- All current results are provisional. The author expects them to shift with the new version.
- The meaning of `ci_lower` and `ci_upper` changes from a 90% to a 95% interval. The coverage metadata reads the level from `get_IDF.R`, so it will state the new level.

**Planned.** Rerun every place and dataset on the new version as a new model version (`config/model_versions/`), with a comparison against this release.

**Detected by.**
- `app` / `method settings unchanged since <baseline model>`, together with the model-change report (CI level, output columns, configuration keys, DHSVM source files). This check appears once a baseline model is set.
- `reference` / `model output columns are the ones extract_AM.py expects`
- `qa` / `identical to the baseline release`

## Rasdaman metadata check not run

**What it is.** The coverage stage runs SNAP's Rasdaman metadata check (`rasdaman_metadata_check.py` from `ua-snap/rasdaman-audit`) only when the `RASDAMAN_AUDIT` path is set. It was not set for this release.

**Impact.** None on the values. The metadata of this release's coverage files has not been checked against SNAP's Rasdaman conventions. The coverage is not ingested; only the `wcst_import` recipes are delivered.

**Planned.** Set `RASDAMAN_AUDIT` and re-finalize the coverage stage.

**Detected by.** `coverage` / `rasdaman metadata check`

## Outputs adopted from before the pipeline

**What it is.** Some stage outputs were made on 17–19 November 2026, before the pipeline existed. The pipeline registered (adopted) them instead of producing them again, then re-ran each stage's checks on them.

| Stage(s) | Adopted output | Made | Re-checked |
|---|---|---|---|
| `app` | App checkout, from `hydro-yan/NG_IDF_AWS` | 17 Nov 2026, before the `ua-snap/NG_IDF` mirror existed | Commit equals `a582a5c`; no local changes; wrapper assumptions hold |
| `env_ngidf`, `env_msim` | Run and MetSim environments | 17 Nov 2026 | Package lists equal the lock files |
| `env_geo`, `env_report` | Raster and report environments | 19 Nov 2026 | Package lists equal the lock files |
| `forcing_<dataset>` (12) | WRF, CESM and Daymet station files | 17 Nov 2026, curation commit `6822576`; the assemble code is unchanged since | WRF/CESM re-validated to the printed digit; Daymet with the differences above |

**Impact.** No known effect on values. The adopted outputs pass the same checks as new ones. What is missing is that this pipeline did not itself produce them.

**Open.** Whether to regenerate them. Regenerating the WRF/CESM forcing means reading about 30 TB from the archive.

**Detected by.** `<stage>` / `outputs produced by this pipeline (not adopted)`, on each stage listed above.

## Places without curves

**What it is.** Some places lack an input, so some or all of their datasets are nodata in the coverage. The file metadata lists them.

| Place | Datasets without curves | Reason |
|---|---|---|
| Shemya Station (AK357), Eareckson Air Station (AK441) | All | About 583 km west of the WRF and Daymet grids |
| Hazen Bay Refuge (AK472), Nunivak Island Refuge (AK479) | All | No Daymet land cell within 1.5 km, so the app has no defaults for them |
| Bogoslof Island Refuge (AK466) | All | Its land cell lies outside NLCD coverage, so it has no land cover |
| Wetland places named by the check `wetland canopies tall enough for DHSVM` | All | Wetland canopy below 0.775 m (above) |
| Hyder (AK160) | WRF and CESM (Daymet available) | Just east of the WRF grid's last column (4.0 km to the edge cell) |

**Impact.** All other places have curves for every dataset; Hyder has Daymet curves only.

**Detected by.** No check. The `places` stage report lists them in the `places_with_nodata` table, and the `defaults` stage counts places without defaults.

## App behaviours reproduced, not corrected

We reproduce the following behaviours of the app because the curves must be the app's. None is flagged by a check; they are listed so they are not mistaken for errors.

- **Forcing cell by unscaled degrees.** The app picks the nearest cell by (Δlat)² + (Δlon)². For 53 of the 562 places in the WRF/CESM domain this is not the closest cell on the ground. All are within 3.6 km. The great-circle nearest cell is recorded in the place table.
- **Different rules for defaults and Daymet forcing.** The defaults cell is chosen by distance in km, the Daymet cell by degrees. For 107 places they are different 1 km cells.
- **First annual maximum dropped.** `get_IDF.R` drops the first annual maximum. Full-period fits therefore use 31 water years. CESM near-term fits use 15: `extract_AM.py` returns 16 annual maxima for that window, and R drops the first.
- **Template location settings.** The DHSVM basin centre (37.97° N, 119.48° W) and time-zone meridian (−120°) keep the app's template values for every place. So do the 3 × 3 point domain and its soils.
- **Daymet durations.** Daymet curves exist for 24, 48 and 72 h only.
- **One snow parameter set for Alaska.** All Alaska rows of the app's snow-parameter table are identical, so every place uses the same values.
- **No CI for the CESM ensemble mean.** The ensemble mean is the mean of the 4 members' fitted depths, with the member range, and has no confidence interval, as in the app.

## Open question: forest canopy and snowmelt

**What it is.** In a separate test of the land around Juneau (not part of the delivered results; Juneau itself is Open), the 100-year, 24-hour NG depth from Daymet was:
- under evergreen forest: 88–98 mm at every elevation;
- on open and shrub ground: from about 130 mm at low elevation to 270–310 mm higher up.

**Impact.** It is not known whether this canopy damping of snowmelt extremes is realistic for coastal forest or comes from the parameters. It bears on the 96 places whose land cover is evergreen.

**Open.** The author's view on whether this behaviour is expected and validated.

**Detected by.** None.
