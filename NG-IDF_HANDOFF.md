# NG-IDF curation: handoff

_Started 2026-11-23. Living document: update it as the work moves on. Covers the work from 2026-11-16 on._

## 1. What this project does

We precompute **NG-IDF curves** (next-generation intensity-duration-frequency: rain plus snowmelt reaching the ground) and precipitation-IDF curves for the **565 Alaska places** in the SNAP API (`https://earthmaps.io/places/communities`, `region == "Alaska"`). The results are Rasdaman coverages, so the SNAP data API can return a place's curves as numbers.

- **Phase 1 (now):** the 565 places, 12 climate datasets each (Daymet historical, WRF historical/medium/high, CESM2-LE historical and future members LE2/4/7/9), plus CESM near-term windows and ensemble means.
- **Phase 2 (later):** a wall-to-wall 4 km grid.

**Guiding rule: we copy the author's method exactly.** Every scientific choice follows H. Yan's NG-IDF app (PNNL; `hydro-yan/NG_IDF_AWS`, branch `feature/add_spatial_map`, pinned commit `a582a5c`). We call the app's own code (DHSVM, `extract_AM.py`, `get_IDF.R`) and change only what batch running needs. Each change is listed in the README and in the coverage metadata.

## 2. Where everything is

| What | Where |
|---|---|
| Curation code (all science, the pipeline, the QC package) | `github.com/ua-snap/ng-idf_curation`, branch **`prefect-flow`** (not merged to `main` yet) |
| Prefect flow (thin driver) | `github.com/ua-snap/prefect`, branch **`ng-idf-pipeline`**, folder `ng_idf/` |
| The author's app, SNAP mirror | `github.com/ua-snap/NG_IDF` (private), tag `app-a582a5c` |
| Data root (all inputs and outputs) | `/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/` |
| The flow's clone of the curation repo | `/import/beegfs/SNAP/jdpaul3/ng-idf_curation` (belongs to the flow; don't edit it) |
| Results of each flow run | `$DATA_ROOT/packages/<time>_<model>_<flow run>/`: the QC package (PDF and HTML) and `rasdaman/` (coverage files, inputs table, `wcst_import` recipes) |
| Stage outputs | `$DATA_ROOT/stages/<stage>/<fingerprint>/` |
| Prefect server | `https://prefect.earthmaps.io` (SNAP's production server, Prefect 2.14.13) |
| Raw forcing archive (read-only, 86 TB) | `/import/beegfs/CMIP6/arctic-cmip6/NG-IDL-Full-Forcing/whole_AK_forcing/` |
| The author's own forcing files (read-only; our validation reference) | `/import/beegfs/CMIP6/arctic-cmip6/NG-IDL/` |
| Rasdaman metadata check | clone of `github.com/ua-snap/rasdaman-audit` at `/import/home/jdpaul3/rasdaman-audit` (set in `config/paths.env`) |
| Earlier batch work by B. Torgerson | `/beegfs/SNAP/rltorgerson/Oct-NG-IDF/` (`HANDOFF_2026-11-16.md`); forcing extraction ideas reused, fitting not used |

## 3. Work so far (2026-11-16 to 2026-11-23)

- **Phase 1 built end to end:** place table with the app's own cell rules, forcing for all 12 datasets (WRF/CESM extracted from the 86 TB archive and matching the author's files to the last printed digit; Daymet rebuilt with MetSim), defaults, ~6,700 model runs with the app's code, coverage files and Rasdaman recipes.
- **Defaults follow H. Yan's rules** (his answers of 18 Nov 2026). LAI reproduces his table exactly at 98% of cells; land cover agrees at 97.8%; heights use his new rule and are provisional until he republishes his table.
- **Pipeline with a Prefect flow:** every stage is fingerprinted, so unchanged stages are reused and nothing is overwritten. Each run ends with a QC package (PDF) for H. Yan and colleagues and a `rasdaman/` delivery folder.
- **Findings raised with the author:** short wetland canopies stop DHSVM (15 of our 34 wetland places; 3,253 of the 4,509 wetland cells in his own table under his new height rule); his WRF/CESM script zeroes very wet hours on rain-bucket resets.
- **Pilots (not in production):** running all land within 5 km of a town, and anchoring NG to an observed baseline. Both open.
- Earlier batch work by B. Torgerson (2026-11-16) supplied the forcing-extraction approach; its fitting step differs from the app's and is not used.

## 4. State right now

- Code: curation `prefect-flow` at `3fa3049`; prefect `ng-idf-pipeline` at `91fca4b`. Both pushed.
- A flow run of the first draft release is running on Chinook (served from a tmux session on `chinook04`). It redoes the places, coverage and QA stages and builds the package; the ~6,700 model runs are reused.
- All results are **provisional** until H. Yan's soil-temperature DHSVM is out and run.
- The follow-up email to H. Yan is drafted but not sent (it includes a request for reference runs from his app at 5 points).

## 5. How to run the pipeline from Chinook and walk away

The flow runs on a Chinook login node inside tmux, registered with SNAP's Prefect server. Once it is started you can disconnect and close the laptop; it keeps running. You watch it at `https://prefect.earthmaps.io`.

### One-time setup

1. **SSH key the flow can use.** The flow logs in to `chinook04` over SSH, even when it already runs there. It needs an RSA private key without a passphrase whose public key is in your `~/.ssh/authorized_keys`. (Josh's is `~/.ssh/id_rsa_new`; his `~/.ssh/id_rsa` is **not** authorized.) To check which of your keys are authorized:
   ```
   cat ~/.ssh/authorized_keys
   ```
2. **Prefect environment** matching the server (Prefect 2.14.13). The two pins are required: newer `griffe` and `pydantic` break Prefect 2.14.
   ```
   conda create -y -n prefect2 -c conda-forge python=3.11 prefect=2.14.13 paramiko "griffe<1.0" "pydantic<2.11"
   ```
3. **Prefect repo** on the `ng-idf-pipeline` branch:
   ```
   cd ~
   git clone https://github.com/ua-snap/prefect.git
   cd ~/prefect
   git checkout ng-idf-pipeline
   ```
4. **Point Prefect at SNAP's server** (stored in `~/.prefect/profiles.toml`):
   ```
   conda activate prefect2
   prefect config set PREFECT_API_URL=https://prefect.earthmaps.io/api
   ```
5. **If you are not `jdpaul3`: commands to run once in your own account.** The data root and the flow's clone belong to `jdpaul3` and are shared with your group (group-writable; the pipeline keeps new files that way). Two things still have to be set on your side:
   ```
   git config --global --add safe.directory /import/beegfs/SNAP/jdpaul3/ng-idf_curation
   git config --global --add safe.directory /import/home/jdpaul3/rasdaman-audit
   ```
   - **Why the first:** the flow updates its clone of the curation repo with git at the start of every run. Git refuses to work in a repository owned by another user ("detected dubious ownership") unless you mark it as safe, so the flow would stop at its first step.
   - **Why the second:** the coverage stage reads the version (git commit) of the Rasdaman metadata check from that clone and makes it part of the stage's fingerprint. If git refuses, the version reads as "missing", the fingerprint changes, and the coverage stage reruns under your account even though nothing changed.
   - Also needed: your own SSH key (step 1), the `prefect2` environment (step 2), and the Prefect server setting (step 4). Set `ssh_username` and `ssh_private_key_path` to yours when you start a run.
   - Only if the app stage reruns (a new model version): a GitHub credential that can read the private `ua-snap/NG_IDF`.

### Each time

```
ssh <you>@chinook04.rcs.alaska.edu
tmux new -s ngidf
conda activate prefect2
cd ~/prefect
git pull
export PYTHONPATH=$PWD
python ng_idf/ngidf_pipeline.py
```

When it says the flow `ng-idf-pipeline` is being served, start a run from the Prefect web page: **Deployments → ng-idf-pipeline → Run → Custom run**. Name the run (the name appears on the PDF cover) and set:

| Parameter | Value |
|---|---|
| `branch_name` | `prefect-flow` (a branch of the **curation** repo, not the prefect repo) |
| `ssh_username` | your Chinook user |
| `ssh_private_key_path` | your key from step 1, as a full path |

Leave the others at their defaults unless you need them (see the table in `ng_idf/README.md`). Or start it from a second tmux window (Ctrl-b, then c):
```
conda activate prefect2
prefect deployment run 'ng-idf-pipeline/ng-idf-pipeline' --param branch_name=prefect-flow --param ssh_private_key_path=/home/<you>/.ssh/<key>
```

Then **detach with Ctrl-b, then d**, log out, and close the laptop.

### Coming back

```
ssh <you>@chinook04.rcs.alaska.edu
tmux attach -t ngidf
```
The tmux session exists on `chinook04` only, so log in to that node by name. Stop serving with Ctrl-c when you are done.

### What a run does and how long it takes

The flow clones or updates the curation repo, plans which stages need to run, submits them to Slurm, waits, checks each stage's results, and finally builds the QC package. Unchanged stages are reused in seconds. A full rerun of the ~6,700 model runs takes about an hour on 8 nodes when the queue is quiet; places, coverage and QA take a few minutes each. Results land in `$DATA_ROOT/packages/<time>_a582a5c_<run name>/`.

### Problems we hit, and the fixes

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'utils'` | `PYTHONPATH` set on its own line without `export` | `export PYTHONPATH=$HOME/prefect` before `python` |
| `422 Unprocessable Entity ... 'labels' ... extra fields not permitted` | Prefect 3 client talking to the Prefect 2.14 server | Use the `prefect2` environment |
| `No module named 'griffe.dataclasses'` | `griffe` 1.0 or later with Prefect 2.14 | Install `"griffe<1.0"` and `"pydantic<2.11"` |
| Run stops making progress after the laptop sleeps | The flow ran on the laptop | Run it from Chinook in tmux, as above |
| A stage's Slurm jobs finished but the flow never moved on | The flow lost its connection and kept waiting | Cancel the flow run and start a new one with the same parameters. It reuses everything finished and picks up the jobs already submitted; nothing is lost |
| `the clone has local edits` | Someone edited the flow's clone | Commit or discard the edits in `/import/beegfs/SNAP/jdpaul3/ng-idf_curation` |

## 6. The QC package (PDF)

Built at the end of every flow run. Its text lives in the curation repo:

| Section | Source |
|---|---|
| 1. Overview | `ngidf/package/content/overview.md` |
| 4. Known issues | `ngidf/package/content/known_issues.md` (one `## ` heading per issue; a check written as `` `stage` / `check name` `` shows its result from the run) |
| Appendix A. Inputs | `ngidf/package/content/appendix_inputs.md` |
| Appendix C. Fingerprints text | `ngidf/package/content/fingerprints.md` |
| Step descriptions, tables, layout | `ngidf/package/build.py` |
| Stage descriptions and check texts | `ngidf/pipeline.py` |

Editing the Markdown files or `build.py` re-runs nothing; changing a stage's checks re-runs QA only. To preview a PDF from your working tree:
```
python3 -I ngidf/pipeline.py package --out-dir ~/tmp/pkg --python /import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/envs/report_pdf/bin/python
```
A flow run uses the text only after it is committed and pushed.

**Comparison with a previous release.** Turned off for the first draft (`BASELINE_COVERAGE_DIR` is empty in `config/model_versions/a582a5c.env`); the PDF then has no section 3.8. Set a baseline for later model versions (for example the soil-temperature DHSVM) to get the comparison back.

## 7. Open items

**Waiting on H. Yan**
- Send the follow-up email (drafted; includes the wetland count, the bucket-reset bug, the WRF humidity question, moss, the elevation file, and a request for reference runs at 5 points).
- Wetland canopies below 0.775 m: his choice of fix (floor the height at 0.78 m, or run as open, or other).
- His republished defaults table: check our heights against it.
- Moss: DHSVM class, LAI and height.
- The soil-temperature DHSVM (end of 2026): add a model version, rerun everything, compare with the first draft.
- Reference outputs from his app: once they arrive, the reference stage compares them value by value (only that stage reruns).

**Ours**
- Ingest the delivered coverage into SNAP's Rasdaman server (separate step on that server).
- Count rain-bucket reset hours affected in our cells (optional Slurm job, about 76 GB of reads), if the email should give a number.
- Flow robustness: give up after repeated failed Slurm-queue checks instead of waiting forever.
- Merge `prefect-flow` and `ng-idf-pipeline` into `main` once the first draft is accepted.
- Open questions: running the land around each town (zones), forest damping of snowmelt at Juneau, anchoring to an observed baseline (delta method), Phase 2 wall-to-wall design.
