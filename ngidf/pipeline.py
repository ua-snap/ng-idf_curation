"""Stage runner for the NG-IDF pipeline: fingerprints, stage directories, reports, releases.

Every stage writes into  $DATA_ROOT/stages/<stage>/<fingerprint>/  where the fingerprint is a hash
of exactly what the stage reads: the content of its code files, the content (or identity, for the
read-only 86 TB archive) of its inputs, its parameters and the fingerprints of the environments it
runs in. A stage whose directory already holds a passing report.json is skipped, so

  * a new model version (config/model_versions/<label>.env) reruns only the stages that read the
    app: app checkout -> DHSVM build -> reference runs -> production runs -> coverage -> QA;
  * nothing is ever overwritten: a changed stage gets a new directory.

The Prefect flow (ua-snap/prefect, ng_idf/) drives it over SSH: `plan`, then `submit` for every
stage that is ready, waits for the Slurm jobs, then `finalize`. Each command prints one JSON document
on stdout (progress goes to stderr), which the flow parses.

  python -I ngidf/pipeline.py info       [--model-version L]          # JSON: model, commit, paths
  python -I ngidf/pipeline.py plan       [--model-version L]          # JSON: all stages, status
  python -I ngidf/pipeline.py prepare    --stage S                    # create dir, job.env; JSON jobs
  python -I ngidf/pipeline.py finalize   --stage S                    # checks -> report.json
  python -I ngidf/pipeline.py submit     --stage S [--wait]           # prepare + sbatch (+ finalize)
  python -I ngidf/pipeline.py retire     --stage S                    # move a failed attempt aside
  python -I ngidf/pipeline.py adopt      --stage S --source DIR       # register outputs made before
  python -I ngidf/pipeline.py release    --name N                     # collect reports of all stages
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ngidf'))
import appinfo  # noqa: E402

# Bump when the meaning of a stage's outputs changes without a change in the files it hashes.
SCHEMA = 1
WRF_CESM = ['WRF_historical', 'WRF_medium', 'WRF_high'] + [
    f'CESM_{p}_LE{m}' for p in ('hist', 'futu') for m in (2, 4, 7, 9)]
FORCING_DATASETS = WRF_CESM + ['Daymet']
# Reference points (PLAN.md Appendix F): one per land cover, inside the author's Interior table and
# forcing domain, so his own defaults and forcing apply directly.
REFERENCE_PLACES = ['AK62', 'AK54', 'AK571', 'AK344', 'AK124']
REFERENCE_DATASETS = ['Daymet', 'WRF_historical', 'CESM_hist_LE2']


# ----------------------------------------------------------------------------------------- helpers
def load_kv(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    return appinfo.sha256_file(path)


def hash_obj(obj):
    return sha256_bytes(json.dumps(obj, sort_keys=True, default=str).encode())


def listing_hash(directory, pattern='*'):
    """Hash of (name, size) of the files in a directory: identity of a large read-only input."""
    d = Path(directory)
    if not d.exists():
        return None
    items = sorted((str(p.relative_to(d)), p.stat().st_size) for p in d.glob(pattern) if p.is_file())
    return hash_obj(items)


def csv_columns_hash(path, columns, dropna=None):
    import pandas as pd
    df = pd.read_csv(path, dtype=str)
    if dropna:
        df = df.dropna(subset=[dropna])
    return hash_obj(df[columns].sort_values(columns).values.tolist())


def now():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def git(*args, cwd=REPO):
    r = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def uncommitted(files):
    """The files whose content differs from the committed version at HEAD (or that are not committed)."""
    out = []
    for f in files:
        if git('rev-parse', '--verify', '-q', f'HEAD:{f}') != git('hash-object', str(REPO / f)):
            out.append(f)
    return out


class NotReady(Exception):
    """An upstream stage has no passing report yet, so this stage's fingerprint is unknown."""


# ----------------------------------------------------------------------------------------- context
class Context:
    def __init__(self, model_version=None, data_root=None):
        paths = load_kv(REPO / 'config/paths.env')
        for k in list(paths):
            paths[k] = os.environ.get(k, paths[k])
        if data_root:
            paths['DATA_ROOT'] = data_root
        self.paths = paths
        self.data_root = Path(paths['DATA_ROOT'])
        label = model_version or os.environ.get('MODEL_VERSION') or \
            (REPO / 'config/model_versions/CURRENT').read_text().strip()
        self.model_file = REPO / f'config/model_versions/{label}.env'
        if not self.model_file.exists():
            raise SystemExit(f'unknown model version {label!r}: {self.model_file} not found')
        self.model = load_kv(self.model_file)
        self.commit = git('rev-parse', 'HEAD')
        self.dirty = bool(git('status', '--porcelain', '--untracked-files=no'))
        self._fp = {}

    def raw(self, rel):
        return self.data_root / rel

    def stage_dir(self, name):
        return self.data_root / 'stages' / name / self.fingerprint(name)[:16]

    def out(self, name):
        return self.stage_dir(name) / 'out'

    def require(self, name):
        """Output dir of an upstream stage that must already have passed."""
        d = self.stage_dir(name)
        rep = d / 'report.json'
        if not rep.exists() or json.loads(rep.read_text()).get('status') not in ('pass', 'warn'):
            raise NotReady(f'{name} has not passed yet ({d})')
        return d / 'out'

    def fingerprint(self, name):
        if name not in self._fp:
            st = STAGES[name]
            comp = dict(stage=name, schema=SCHEMA, code=code_hashes(st.code), inputs=st.inputs(self))
            self._fp[name] = hash_obj(comp)
            self._fp[name + ':components'] = comp
        return self._fp[name]

    def components(self, name):
        self.fingerprint(name)
        return self._fp[name + ':components']


def code_hashes(patterns):
    out = {}
    for pat in patterns + ['config/env.sh']:
        for p in sorted(REPO.glob(pat)):
            if p.is_file():
                out[str(p.relative_to(REPO))] = sha256_file(p)
    return out


# ------------------------------------------------------------------------------------------ stages
class Job:
    def __init__(self, name, script, args=(), kind='sbatch', array=None, after=()):
        self.name, self.script, self.args, self.kind = name, script, list(args), kind
        self.array, self.after = array, list(after)

    def as_dict(self):
        return dict(name=self.name, kind=self.kind, script=self.script, args=self.args, array=self.array,
                    after=self.after)


class Stage:
    """A stage. Subclasses define code, inputs(ctx), env(ctx), jobs(ctx) and checks(ctx, out)."""
    name = None
    code = []
    needs = []
    title = ''
    explain = ''        # one paragraph, plain language, for the SNAP-facing summary

    def inputs(self, ctx):
        return {}

    def env(self, ctx):
        return {}

    def jobs(self, ctx):
        return []

    def adopted_jobs(self, ctx):
        """Jobs to run when the outputs were adopted (checks only)."""
        return []

    def prepare(self, ctx, d):
        pass

    def checks(self, ctx, out):
        """Return (checks, metrics, tables, summary_md)."""
        return [], {}, {}, ''


def num(x):
    """A measured difference for a check detail: 3 significant digits (0.0001, 7.6, 2.04), not 0.000100000000003."""
    return 'n/a' if x is None else f'{x:.3g}'


def check(name, ok, detail='', warn=False):
    status = 'pass' if ok else ('warn' if warn else 'fail')
    return dict(name=name, status=status, detail=detail)


def lock_inputs(ctx, lock, extra=()):
    return dict(lock=sha256_file(REPO / lock), extra=[sha256_file(REPO / e) for e in extra])


class EnvStage(Stage):
    lock, pip_lock = None, None
    needs = []

    def __init__(self, name, lock, pip_lock=None, title=''):
        self.name, self.lock, self.pip_lock, self.title = name, lock, pip_lock, title
        self.code = [lock, 'scripts/setup/create_env.sh'] + ([pip_lock] if pip_lock else [])
        self.explain = (f'Builds the software environment from the exact package list in {lock}, so every '
                        'job runs with the same versions of Python, R and libraries.')

    def inputs(self, ctx):
        return {}

    def jobs(self, ctx):
        args = ['$OUT/env', f'$REPO/{self.lock}'] + ([f'$REPO/{self.pip_lock}'] if self.pip_lock else [])
        return [Job('create', 'scripts/setup/create_env.sh', args, kind='login')]

    def checks(self, ctx, out):
        env = out / 'env'
        py = env / 'bin/python'
        c = [check('environment exists', py.exists(), str(env))]
        metrics = {}
        if py.exists():
            r = subprocess.run(['conda', 'list', '-p', str(env), '--explicit'], capture_output=True, text=True)
            if r.returncode == 0:
                have = sorted(l for l in r.stdout.splitlines() if l.startswith('http'))
                want = sorted(l for l in (REPO / self.lock).read_text().splitlines() if l.startswith('http'))
                missing, extra = sorted(set(want) - set(have)), sorted(set(have) - set(want))
                c.append(check('packages match the lock file', not missing and not extra,
                               f'{len(want)} packages; missing {missing[:3]}; extra {extra[:3]}'))
                metrics['packages'] = len(have)
            else:
                c.append(check('packages match the lock file', False, 'conda list failed: ' + r.stderr[-300:],
                               warn=True))
            if self.pip_lock:
                pins = [l.strip() for l in (REPO / self.pip_lock).read_text().splitlines()
                        if l.strip() and not l.startswith('#')]
                r = subprocess.run([str(py), '-m', 'pip', 'list', '--format=freeze'], capture_output=True, text=True)
                have = {l.split('==')[0].lower(): l for l in r.stdout.splitlines()}
                bad = [x for x in pins if have.get(x.split('==')[0].lower()) != x]
                c.append(check('pip packages match the pins', not bad, f'{pins}; mismatched {bad}'))
            v = subprocess.run([str(py), '-c', 'import sys; print(sys.version.split()[0])'], capture_output=True,
                               text=True)
            metrics['python'] = v.stdout.strip()
        return c, metrics, {}, ''


class AppStage(Stage):
    name = 'app'
    title = "Author's NG-IDF app (model code)"
    code = ['scripts/setup/fetch_app.sh', 'ngidf/appinfo.py']
    explain = ("Downloads H. Yan's NG-IDF app (DHSVM source, the annual-maximum and fitting scripts) at the exact "
               "commit named in the model version file, checks the commit hash, and reads the method settings "
               "(distribution, confidence interval, bootstrap size, model output columns) straight from his code.")

    def inputs(self, ctx):
        m = ctx.model
        return dict(commit=m['APP_COMMIT'])

    def env(self, ctx):
        m = ctx.model
        return dict(APP_REPO=m['APP_REPO'], APP_REF=m['APP_REF'], APP_COMMIT=m['APP_COMMIT'],
                    UPSTREAM_REPO=m.get('UPSTREAM_REPO', ''))

    def jobs(self, ctx):
        return [Job('fetch', 'scripts/setup/fetch_app.sh', ['$OUT/app'], kind='login')]

    def checks(self, ctx, out):
        app = out / 'app'
        info = appinfo.app_info(app)
        (out / 'appinfo.json').write_text(json.dumps(info, indent=1) + '\n')
        probs = appinfo.compatibility_problems(info)
        g = info['get_idf']
        c = [check('commit matches the model version file', info['commit'] == ctx.model['APP_COMMIT'],
                   f"checked out {info['commit']}, expected {ctx.model['APP_COMMIT']}"),
             check('checkout has no local modifications', not info['dirty']),
             check('compatible with the batch wrapper', not probs, '; '.join(probs) or 'all wrapper assumptions hold')]
        method = [dict(setting='distribution', value=g['distribution']),
                  dict(setting='parameter estimation', value='L-moments (lmom samlmu)' if g['lmoments'] else '?'),
                  dict(setting='first annual maximum dropped', value=g['drops_first_am']),
                  dict(setting='bootstrap samples', value=g['bootstrap_samples']),
                  dict(setting='CI quantiles', value=g['ci_quantiles']),
                  dict(setting='CI level (%)', value=g['ci_level_percent']),
                  dict(setting='probabilities', value=g['probabilities_expr'])]
        cols = [dict(field=k, column=v, expected_header=appinfo.EXPECTED_PIXEL_FIELDS.get(k))
                for k, v in info['extract_am']['pixel_columns'].items()]
        base = ctx.model.get('BASELINE_MODEL')
        if base:
            sys.path.insert(0, str(REPO / 'ngidf/qa'))
            import model_change
            try:
                old_app = Context(base, str(ctx.data_root)).require('app') / 'app'
                mc = model_change.compare(old_app, app)
                (out / 'model_change.json').write_text(json.dumps(mc, indent=1, default=str) + '\n')
                (out / 'model_change.md').write_text(model_change.render_md(mc))
                c.append(check(f'method settings unchanged since {base}', not mc['method_changed'],
                               'changed: ' + '; '.join(mc['method_changed']) + ' (review the model-change report)',
                               warn=True))
            except NotReady as e:
                c.append(check(f'compared with baseline model {base}', False, str(e), warn=True))
        md = (f"App `{ctx.model['APP_REPO']}` ref `{ctx.model['APP_REF']}` = commit `{info['commit']}`.\n\n"
              f"Method read from the code: {g['distribution']}, {g['bootstrap_samples']} bootstrap samples, "
              f"{g['ci_level_percent']}% CI ({g['ci_quantiles']}), first annual maximum dropped: {g['drops_first_am']}.")
        return c, dict(ci_level_percent=g['ci_level_percent']), dict(method=method, pixel_columns=cols), md


class InputsStage(Stage):
    name = 'inputs'
    title = 'Source data checksums'
    needs = ['env_ngidf']
    code = ['slurm/stages/inputs.sbatch', 'ngidf/inputs_audit.py']
    explain = ('Checks that every downloaded source dataset (place list, land cover, LAI, canopy height, Daymet '
               'pixels) is byte-for-byte what was downloaded, using the SHA-256 checksums recorded at download, '
               'and lists the read-only forcing archive.')
    RAW = ['raw/earthmaps_places', 'raw/nlcd_2016_ak', 'raw/landfire_evh_2016_ak', 'raw/glass_lai_2016_500m']

    def inputs(self, ctx):
        sums = {r: sha256_file(ctx.raw(r) / 'SHA256SUMS') for r in self.RAW}
        return dict(sums=sums, daymet_pixels=listing_hash(ctx.raw('raw/daymet_v4_pixels')),
                    land_cache=sha256_file(ctx.raw(ctx.paths['DAYMET_LAND_CACHE'])),
                    raw_forcing=ctx.paths['RAW_FORCING_ROOT'], author_forcing=ctx.paths['AUTHOR_FORCING_ROOT'],
                    env=ctx.fingerprint('env_ngidf'))

    def env(self, ctx):
        return dict(NGIDF_ENV=str(ctx.require('env_ngidf') / 'env'))

    def jobs(self, ctx):
        return [Job('audit', 'slurm/stages/inputs.sbatch', [' '.join(self.RAW)])]

    def checks(self, ctx, out):
        a = json.loads((out / 'inputs.json').read_text())
        c = [check(f"checksums {r['dir']}", r['failed'] == 0, f"{r['ok']} files OK, {r['failed']} failed")
             for r in a['checksums']]
        c.append(check('raw forcing archive readable', all(d['files'] > 0 for d in a['raw_forcing']),
                       f"{len(a['raw_forcing'])} datasets listed"))
        return c, {}, dict(checksums=a['checksums'], raw_forcing=a['raw_forcing'], daymet_pixels=[a['daymet_pixels']]), ''


class PlacesStage(Stage):
    name = 'places'
    title = 'Place table and model cells'
    needs = ['inputs', 'app', 'env_ngidf']
    code = ['scripts/places/build_place_table.py', 'ngidf/daymet_land.py', 'slurm/stages/places.sbatch']
    explain = ("For each of the 565 Alaska places, picks the 1 km defaults cell and the forcing cells with the "
               "app's own nearest-cell rules.")

    def inputs(self, ctx):
        app = ctx.require('app') / 'app'
        return dict(env=ctx.fingerprint('env_ngidf'), inputs=ctx.fingerprint('inputs'),
                    communities=sha256_file(ctx.raw(ctx.paths['PLACES_SNAPSHOT'])),
                    author_table=sha256_file(app / 'static/gridcell_current_lulc.csv'),
                    land_cache=sha256_file(ctx.raw(ctx.paths['DAYMET_LAND_CACHE'])),
                    daymet_pixels=listing_hash(ctx.raw('raw/daymet_v4_pixels')),
                    wrf_grid=ctx.paths['WRF_GRID_FILE'], cesm_grid=ctx.paths['CESM_GRID_FILE'])

    def env(self, ctx):
        return dict(NGIDF_ENV=str(ctx.require('env_ngidf') / 'env'), APP_DIR=str(ctx.require('app') / 'app'),
                    PLACES_SNAPSHOT=str(ctx.raw(ctx.paths['PLACES_SNAPSHOT'])),
                    DAYMET_LAND_CACHE=str(ctx.raw(ctx.paths['DAYMET_LAND_CACHE'])),
                    WRF_GRID_FILE=f"{ctx.paths['RAW_FORCING_ROOT']}/{ctx.paths['WRF_GRID_FILE']}",
                    CESM_GRID_FILE=f"{ctx.paths['RAW_FORCING_ROOT']}/{ctx.paths['CESM_GRID_FILE']}")

    def jobs(self, ctx):
        return [Job('build', 'slurm/stages/places.sbatch')]

    def checks(self, ctx, out):
        import pandas as pd
        p = pd.read_csv(out / 'places_ak.csv')
        n = len(p)
        c = [check('all earthmaps Alaska places present', n == 565, f'{n} places'),
             check('place ids unique', p.id.is_unique)]
        st = []
        for col in ('defaults_status', 'wrf_cesm_status', 'daymet_status'):
            for k, v in p[col].value_counts().items():
                st.append(dict(column=col, status=k, places=int(v)))
        nod = p[(p.defaults_status != 'ok') | (p.wrf_cesm_status != 'ok') | (p.daymet_status != 'ok')]
        tables = dict(status_counts=st,
                      places_with_nodata=nod[['id', 'name', 'defaults_status', 'wrf_cesm_status', 'daymet_status']]
                      .to_dict('records'))
        metrics = dict(places=n, forcing_cells=int(p.forcing_cell_index.nunique()),
                       daymet_cells=int(p.daymet_key.nunique()),
                       app_rule_differs_from_nearest=int(p.wrf_geo_nearest_differs.sum()))
        return c, metrics, tables, ''


class DefaultsStage(Stage):
    name = 'defaults'
    title = 'Default land cover, LAI and canopy height'
    needs = ['places', 'env_geo', 'app']
    code = ['scripts/defaults/cell_counts.py', 'scripts/defaults/cell_lai.py',
            'scripts/defaults/build_place_defaults.py', 'slurm/stages/defaults.sbatch']
    explain = ("Gives each place the land cover, leaf area index and canopy height the app would fill in: the "
               "author's own table where the place is inside it, otherwise a rebuild from the same source maps.")

    def inputs(self, ctx):
        places = ctx.require('places') / 'places_ak.csv'
        app = ctx.require('app') / 'app'
        return dict(env=ctx.fingerprint('env_geo'),
                    cells=csv_columns_hash(places, ['id', 'defaults_lat', 'defaults_lon', 'defaults_status']),
                    author_table=sha256_file(app / 'static/gridcell_current_lulc.csv'),
                    raw={r: sha256_file(ctx.raw(r) / 'SHA256SUMS') for r in
                         ['raw/nlcd_2016_ak', 'raw/landfire_evh_2016_ak', 'raw/glass_lai_2016_500m']})

    def env(self, ctx):
        return dict(GEO_ENV=str(ctx.require('env_geo') / 'env'), APP_DIR=str(ctx.require('app') / 'app'),
                    PLACES_CSV=str(ctx.require('places') / 'places_ak.csv'),
                    NLCD_RASTER=str(ctx.raw(ctx.paths['NLCD_RASTER'])), EVH_RASTER=str(ctx.raw(ctx.paths['EVH_RASTER'])),
                    GLASS_DIR=str(ctx.raw(ctx.paths['GLASS_DIR'])))

    def jobs(self, ctx):
        return [Job('build', 'slurm/stages/defaults.sbatch')]

    def checks(self, ctx, out):
        import pandas as pd
        d = pd.read_csv(out / 'place_defaults.csv')
        c = [check('one row per place', len(d) == 565 and d.id.is_unique, f'{len(d)} rows')]
        cover = d.groupby(['defaults_source', 'land_cover']).size().reset_index(name='places')
        metrics = dict(d.defaults_source.value_counts().to_dict())
        tables = dict(cover_by_source=cover.to_dict('records'))
        # wetland canopies below the DHSVM aerodynamic limit (PLAN.md section 8 Q1): the app fails there too
        wl = d[(d.land_cover == 'wetland') & (d.height_m < 0.775)]
        c.append(check('wetland heights above the DHSVM limit (0.775 m)', wl.empty,
                       f'{len(wl)} places below: DHSVM will stop for them (known issue, PLAN.md 8 Q1)', warn=True))
        if 'rebuilt_land_cover' in d:
            a = d[d.defaults_source == 'author_table'].dropna(subset=['rebuilt_land_cover'])
            if len(a):
                agree = float((a.rebuilt_land_cover == a.source_land_cover).mean())
                lai = (a.rebuilt_lai - a.source_lai).abs()
                hgt = (a.rebuilt_height_m - a.source_height_m).abs()
                metrics.update(rebuild_cover_agreement=round(agree, 3), rebuild_lai_mae=round(float(lai.mean()), 3),
                               rebuild_height_mae_m=round(float(hgt.mean()), 3), rebuild_compared=len(a))
                c.append(check("rebuild reproduces the author's table at his places", agree >= 0.95,
                               f'land cover agrees at {agree:.0%} of {len(a)} places; LAI MAE {lai.mean():.2f}, '
                               f'height MAE {hgt.mean():.2f} m (provisional until his republished table)', warn=True))
        return c, metrics, tables, ''


class ForcingStage(Stage):
    title_tmpl = 'Forcing: {ds}'
    needs = ['places', 'env_ngidf']

    def __init__(self, ds):
        self.ds, self.name = ds, f'forcing_{ds}'
        self.title = f'Meteorological forcing: {ds}'
        self.code = ['ngidf/forcing.py', 'slurm/stages/forcing_block.sbatch', 'slurm/stages/forcing_assemble.sbatch']
        self.explain = (f'Extracts the hourly {ds} weather series for every forcing cell from the 4 km archive with '
                        "the author's unit conversions, then compares them line by line with the author's own files "
                        'for the cells both have.')

    def inputs(self, ctx):
        places = ctx.require('places') / 'places_ak.csv'
        return dict(dataset=self.ds, env=ctx.fingerprint('env_ngidf'),
                    cells=csv_columns_hash(places, ['forcing_cell_index', 'wrf_y', 'wrf_x', 'wrf_key'],
                                           dropna='forcing_cell_index'),
                    raw=ctx.paths['RAW_FORCING_ROOT'], ref=ctx.paths['AUTHOR_FORCING_ROOT'])

    def env(self, ctx):
        return dict(NGIDF_ENV=str(ctx.require('env_ngidf') / 'env'), DATASET=self.ds,
                    PLACES_CSV=str(ctx.require('places') / 'places_ak.csv'))

    def prepare(self, ctx, d):
        nb = d / 'nblocks'
        if not nb.exists():
            env = dict(os.environ, RAW_FORCING_ROOT=ctx.paths['RAW_FORCING_ROOT'])
            r = subprocess.run([sys.executable, '-I', str(REPO / 'ngidf/forcing.py'), 'nblocks', '--dataset', self.ds],
                               capture_output=True, text=True, env=env, check=True)
            nb.write_text(r.stdout.strip() + '\n')

    def jobs(self, ctx):
        n = int((ctx.stage_dir(self.name) / 'nblocks').read_text())
        return [Job('blocks', 'slurm/stages/forcing_block.sbatch', array=f'0-{n - 1}%2'),
                Job('assemble', 'slurm/stages/forcing_assemble.sbatch', ['assemble'], after=['blocks'])]

    def adopted_jobs(self, ctx):
        return [Job('validate', 'slurm/stages/forcing_assemble.sbatch', ['validate'])]

    def checks(self, ctx, out):
        v = json.loads((out / 'validation.json').read_text())
        s = v['summary']
        files = list((out / self.ds).glob('data_*'))
        c = [check('one station file per forcing cell', len(files) == v['expected_cells'],
                   f"{len(files)} files, {v['expected_cells']} cells"),
             check("cells compared with the author's files", s['cells'] > 0, f"{s['cells']} shared cells", warn=True)]
        tol = dict(T=1.01e-4, W=1.01e-4, RH=1.01e-4, SW=1.01e-4, LW=1.01e-4, P=1.01e-6)
        for var, t in tol.items():
            m = s[f'{var}_max']
            known = s.get('P_known_bucket_reset', 0) if var == 'P' else 0
            c.append(check(f'{var} matches the author to the printed precision', m is not None and m <= t,
                           f'max |difference| {num(m)}' + (f'; {known} hours differ only by the bucket-reset bug in the '
                                                     "author's script (PLAN.md 9.3, Q12)" if known else ''),
                           warn=bool(known)))
        return c, dict(shared_cells=s['cells']), dict(validation=v['cells']), ''


class DaymetForcingStage(ForcingStage):
    needs = ['places', 'env_msim', 'inputs']

    def __init__(self):
        super().__init__('Daymet')
        self.code = ['ngidf/daymet_forcing.py', 'slurm/stages/daymet_wind.sbatch', 'slurm/stages/daymet_run.sbatch']
        self.explain = ("Rebuilds the author's 3-hourly Daymet weather series (Daymet daily data, MetSim, daily WRF "
                        "wind) for each place's 1 km cell, then compares them with the author's files where both exist.")

    def inputs(self, ctx):
        places = ctx.require('places') / 'places_ak.csv'
        return dict(env=ctx.fingerprint('env_msim'), cells=csv_columns_hash(places, ['daymet_key', 'daymet_status']),
                    pixels=listing_hash(ctx.raw('raw/daymet_v4_pixels')), raw=ctx.paths['RAW_FORCING_ROOT'],
                    ref=ctx.paths['AUTHOR_FORCING_ROOT'])

    def env(self, ctx):
        return dict(MSIM_ENV=str(ctx.require('env_msim') / 'env'), DATASET='Daymet',
                    PLACES_CSV=str(ctx.require('places') / 'places_ak.csv'),
                    PIXEL_DIR=str(ctx.raw('raw/daymet_v4_pixels')))

    def prepare(self, ctx, d):
        pass

    def jobs(self, ctx):
        return [Job('wind', 'slurm/stages/daymet_wind.sbatch', array='0-32%2'),
                Job('metsim', 'slurm/stages/daymet_run.sbatch', ['8'], array='0-7', after=['wind']),
                Job('validate', 'slurm/stages/daymet_run.sbatch', ['validate'], after=['metsim'])]

    def adopted_jobs(self, ctx):
        return [Job('validate', 'slurm/stages/daymet_run.sbatch', ['validate'])]

    def checks(self, ctx, out):
        v = json.loads((out / 'validation.json').read_text())
        s = v['summary']
        files = list((out / 'Daymet').glob('data_*'))
        c = [check('one station file per Daymet cell', len(files) == v['expected_cells'],
                   f"{len(files)} files, {v['expected_cells']} cells"),
             check("P matches the author's files exactly", s['P_max'] is not None and s['P_max'] <= 1.01e-6,
                   f"max |difference| {num(s['P_max'])} m"),
             check('T matches (known residual from the tmax/tmin swap, PLAN.md 9.3)', s['T_max'] <= 0.03,
                   f"max |difference| {num(s['T_max'])} C", warn=True),
             check('wind matches (known: wind-cell rule, PLAN.md 9.3)', s['W_max'] <= 1.01e-4,
                   f"max |difference| {num(s['W_max'])} m/s in {s['W_cells_differ']} of {s['cells']} cells", warn=True),
             check('SW/LW/RH match (known: MetSim elevation source, PLAN.md 9.3)',
                   max(s['SW_max'], s['LW_max'], s['RH_max']) <= 1.01e-4,
                   f"max |difference| SW {num(s['SW_max'])}, LW {num(s['LW_max'])}, RH {num(s['RH_max'])}", warn=True)]
        return c, dict(shared_cells=s['cells']), dict(validation=v['cells']), ''


class DhsvmStage(Stage):
    name = 'dhsvm'
    title = 'DHSVM build'
    needs = ['app', 'env_ngidf']
    code = ['scripts/setup/build_dhsvm.sh', 'slurm/stages/dhsvm.sbatch']
    explain = ("Compiles DHSVM from the author's source at the pinned commit with his makefile. The shipped binary "
               "is a Cray build that does not run on Chinook.")

    def inputs(self, ctx):
        return dict(app=ctx.model['APP_COMMIT'], env=ctx.fingerprint('env_ngidf'))

    def env(self, ctx):
        return dict(NGIDF_ENV=str(ctx.require('env_ngidf') / 'env'), APP_DIR=str(ctx.require('app') / 'app'))

    def jobs(self, ctx):
        return [Job('build', 'slurm/stages/dhsvm.sbatch')]

    def checks(self, ctx, out):
        b = json.loads((out / 'build.json').read_text())
        c = [check('DHSVM binary built', (out / 'DHSVM3.2').exists(), b.get('sha256', '')),
             check('no compiler errors', b['errors'] == 0, f"{b['warnings']} warnings, {b['errors']} errors")]
        return c, dict(sha256=b.get('sha256'), compiler=b.get('compiler')), dict(build=[b]), ''


class ReferenceStage(Stage):
    name = 'reference'
    title = "Reference runs on the author's own inputs"
    needs = ['app', 'dhsvm', 'places', 'env_ngidf']
    code = ['scripts/tests/reference_runs.py', 'ngidf/run_point.py', 'slurm/stages/reference.sbatch']
    explain = ("Runs five Interior places (one per land cover) on the author's own forcing files and his own "
               "defaults table, and compares the curves with output he produced with his app. Production runs "
               "start only if this passes.")

    def ref_dir(self, ctx):
        return ctx.raw(f"raw/hy_reference/{ctx.model['APP_COMMIT'][:7]}")

    def inputs(self, ctx):
        return dict(app=ctx.model['APP_COMMIT'], dhsvm=ctx.fingerprint('dhsvm'), env=ctx.fingerprint('env_ngidf'),
                    places=sha256_file(ctx.require('places') / 'places_ak.csv'), points=REFERENCE_PLACES,
                    datasets=REFERENCE_DATASETS, author_forcing=ctx.paths['AUTHOR_FORCING_ROOT'],
                    hy_reference=listing_hash(self.ref_dir(ctx), '**/*'))

    def env(self, ctx):
        return dict(NGIDF_ENV=str(ctx.require('env_ngidf') / 'env'), APP_DIR=str(ctx.require('app') / 'app'),
                    DHSVM_BIN=str(ctx.require('dhsvm') / 'DHSVM3.2'),
                    PLACES_CSV=str(ctx.require('places') / 'places_ak.csv'),
                    HY_REFERENCE=str(self.ref_dir(ctx)), REFERENCE_PLACES=' '.join(REFERENCE_PLACES),
                    REFERENCE_DATASETS=' '.join(REFERENCE_DATASETS))

    def jobs(self, ctx):
        return [Job('run', 'slurm/stages/reference.sbatch')]

    def checks(self, ctx, out):
        r = json.loads((out / 'reference.json').read_text())
        ok = [x for x in r['runs'] if x['status'] == 'ok']
        c = [check('all reference runs completed', len(ok) == len(r['runs']), f"{len(ok)} of {len(r['runs'])}")]
        hdr = r.get('pixel_header_check') or []
        c.append(check('model output columns are the ones extract_AM.py expects', hdr and all(h['ok'] for h in hdr),
                       '; '.join(f"col {h['index']} {h['found']!r}" for h in hdr)))
        cmp_ = [x for x in r['runs'] if x.get('compare')]
        if cmp_:
            worst = max(x['compare']['magnitude_max_abs_mm'] for x in cmp_)
            c.append(check("fitted values equal the author's app output (to 0.01 mm)", worst <= 0.0101,
                           f'{len(cmp_)} runs compared; largest difference {worst} mm'))
        else:
            c.append(check("compared with the author's app output", False,
                           f'no reference output from H. Yan yet (expected in {self.ref_dir(ctx)})', warn=True))
        return c, {}, dict(runs=r['runs'], pixel_header=hdr), ''


class RunsStage(Stage):
    name = 'runs'
    title = 'Production model runs'
    needs = ['reference', 'places', 'defaults', 'dhsvm', 'app', 'env_ngidf'] + [f'forcing_{d}' for d in FORCING_DATASETS]
    code = ['ngidf/run_point.py', 'ngidf/run_batch.py', 'slurm/stages/runs.sbatch']
    explain = ('Runs the app for every place and every forcing dataset (about 6,700 runs): DHSVM, annual maxima, '
               'Gumbel fit and bootstrap confidence interval, exactly as the app does for one clicked point.')
    NTASKS = 8

    def manifest_rows(self, ctx):
        import pandas as pd
        places = pd.read_csv(ctx.require('places') / 'places_ak.csv', dtype={'wrf_key': str, 'daymet_key': str})
        defaults = pd.read_csv(ctx.require('defaults') / 'place_defaults.csv')
        df = places.merge(defaults[['id', 'cover_code', 'lai', 'height_m', 'defaults_source']], on='id', how='left')
        rows = []
        for p in df[df.cover_code >= 0].itertuples(index=False):
            for ds in FORCING_DATASETS:
                daymet = ds == 'Daymet'
                if (p.daymet_status if daymet else p.wrf_cesm_status) != 'ok':
                    continue
                key = p.daymet_key if daymet else p.wrf_key
                f = ctx.require(f'forcing_{ds}') / ds / f'data_{key}'
                rows.append(dict(place_id=p.id, dataset=ds, cell_key=key, forcing_file=str(f), lat=p.latitude,
                                 lon=p.longitude, cover=int(p.cover_code), lai=float(p.lai), height=float(p.height_m),
                                 defaults_source=p.defaults_source))
        return pd.DataFrame(rows)

    def inputs(self, ctx):
        m = self.manifest_rows(ctx)
        # forcing files are named by the forcing stage's fingerprint (its directory), so the manifest
        # text covers the forcing content
        return dict(manifest=sha256_bytes(m.to_csv(index=False).encode()), app=ctx.model['APP_COMMIT'],
                    dhsvm=ctx.fingerprint('dhsvm'), env=ctx.fingerprint('env_ngidf'),
                    reference=ctx.fingerprint('reference'))

    def env(self, ctx):
        return dict(NGIDF_ENV=str(ctx.require('env_ngidf') / 'env'), APP_DIR=str(ctx.require('app') / 'app'),
                    DHSVM_BIN=str(ctx.require('dhsvm') / 'DHSVM3.2'))

    def prepare(self, ctx, d):
        m = d / 'manifest.csv'
        if not m.exists():
            self.manifest_rows(ctx).to_csv(m, index=False)

    def jobs(self, ctx):
        return [Job('run', 'slurm/stages/runs.sbatch', [str(self.NTASKS)], array=f'0-{self.NTASKS - 1}')]

    def checks(self, ctx, out):
        import pandas as pd
        m = pd.read_csv(ctx.stage_dir(self.name) / 'manifest.csv')
        st, errs = [], {}
        for r in m.itertuples(index=False):
            rj = out / r.place_id / r.dataset / 'run.json'
            j = json.loads(rj.read_text()) if rj.exists() else {}
            s = j.get('status', 'missing')
            st.append(s)
            if s == 'failed':
                log = rj.parent / 'dhsvm.log'
                msg = next((l.strip() for l in log.read_text().splitlines() if 'error' in l.lower()), j.get('error', '?')) \
                    if log.exists() else j.get('error', '?')
                errs.setdefault(msg[:200], []).append(f'{r.place_id}/{r.dataset}')
        m['status'] = st
        counts = m.groupby(['dataset', 'status']).size().unstack(fill_value=0).reset_index()
        n_ok, n = int((m.status == 'ok').sum()), len(m)
        unexplained = {k: v for k, v in errs.items() if 'Trunk space' not in k}
        c = [check('every run has a result', int((m.status == 'missing').sum()) == 0,
                   f"{int((m.status == 'missing').sum())} missing"),
             check('runs completed', n_ok == n, f'{n_ok} of {n} ok', warn=not unexplained),
             check('every failure has a known cause', not unexplained,
                   '; '.join(f'{len(v)}x {k}' for k, v in errs.items()) or 'no failures')]
        fails = [dict(message=k, runs=len(v), examples=', '.join(v[:5])) for k, v in errs.items()]
        return c, dict(runs=n, ok=n_ok), dict(status=counts.to_dict('records'), failures=fails), ''


class CoverageStage(Stage):
    name = 'coverage'
    title = 'Coverage files (netCDF for Rasdaman)'
    needs = ['runs', 'places', 'defaults', 'app', 'env_ngidf']
    code = ['ngidf/build_coverage.py', 'ngidf/appinfo.py', 'slurm/stages/coverage.sbatch', 'recipes/*.json']

    explain = ('Collects all runs into the two place-indexed netCDF files the data API will serve, with the method, '
               'versions and nodata places written into the file metadata.')

    def inputs(self, ctx):
        meta_keys = ['MODEL_LABEL', 'MODEL_DESCRIPTION', 'UPSTREAM_REPO', 'UPSTREAM_BRANCH', 'APP_REPO', 'APP_REF',
                     'APP_COMMIT']  # the model-file values written into the coverage metadata
        return dict(runs=ctx.fingerprint('runs'), model={k: ctx.model.get(k) for k in meta_keys},
                    places=sha256_file(ctx.require('places') / 'places_ak.csv'),
                    defaults=sha256_file(ctx.require('defaults') / 'place_defaults.csv'))

    def env(self, ctx):
        return dict(NGIDF_ENV=str(ctx.require('env_ngidf') / 'env'), APP_DIR=str(ctx.require('app') / 'app'),
                    RUNS_ROOT=str(ctx.require('runs')), PLACES_CSV=str(ctx.require('places') / 'places_ak.csv'),
                    DEFAULTS_CSV=str(ctx.require('defaults') / 'place_defaults.csv'),
                    MODEL_FILE=str(ctx.model_file), RASDAMAN_AUDIT=os.environ.get('RASDAMAN_AUDIT', ''))

    def jobs(self, ctx):
        return [Job('build', 'slurm/stages/coverage.sbatch')]

    def checks(self, ctx, out):
        s = json.loads((out / 'build_summary.json').read_text())
        c = [check('coverage files written', all((out / f).exists() for f in ('ngidf_places.nc', 'ngidf_places_am.nc')))]
        mc = out / 'metadata_check.txt'
        if mc.exists():
            txt = mc.read_text()
            c.append(check('rasdaman metadata check', 'FAIL' not in txt.upper(), txt.strip()[-300:]))
        else:
            c.append(check('rasdaman metadata check', False, 'RASDAMAN_AUDIT not set: not run', warn=True))
        counts = [dict(dataset=k, places=v) for k, v in s['counts'].items()]
        return c, dict(ci_level_percent=s.get('ci_level_percent')), dict(places_per_dataset=counts), ''


def report_checks(ctx, name):
    rep = ctx.stage_dir(name) / 'report.json'
    if not rep.exists():
        return None
    r = json.loads(rep.read_text())
    return [r['status'], [[c['name'], c['status'], c['detail']] for c in r['checks']]]


class QaStage(Stage):
    name = 'qa'
    title = 'Quality checks and report'
    needs = ['coverage', 'runs', 'env_report']
    code = ['ngidf/qa/*.py', 'slurm/stages/qa.sbatch']
    explain = ('Checks every run against the author\'s code (what our wrapper changed, run by run), checks every '
               'fitted curve, summarises the results with maps and community curves, compares them with the '
               'baseline release, and writes the self-contained HTML report.')

    def baseline_coverage(self, ctx):
        if ctx.model.get('BASELINE_MODEL'):
            return Context(ctx.model['BASELINE_MODEL'], str(ctx.data_root)).require('coverage')
        if ctx.model.get('BASELINE_COVERAGE_DIR'):
            return ctx.raw(ctx.model['BASELINE_COVERAGE_DIR'])
        return None

    def inputs(self, ctx):
        b = self.baseline_coverage(ctx)
        return dict(coverage=ctx.fingerprint('coverage'), env=ctx.fingerprint('env_report'),
                    baseline=str(b) if b else None,
                    baseline_hash=sha256_file(b / 'ngidf_places.nc') if b else None,
                    stages={s.name: ctx.fingerprint(s.name) for s in STAGE_LIST if s.name != self.name},
                    # the report shows every stage's checks, so it is rebuilt when they change
                    reports=hash_obj({s.name: report_checks(ctx, s.name) for s in STAGE_LIST if s.name != self.name}))

    def env(self, ctx):
        b = self.baseline_coverage(ctx)
        mc = ctx.require('app') / 'model_change.json'
        return dict(REPORT_ENV=str(ctx.require('env_report') / 'env'), RUNS_ROOT=str(ctx.require('runs')),
                    MANIFEST=str(ctx.stage_dir('runs') / 'manifest.csv'), COVERAGE_DIR=str(ctx.require('coverage')),
                    PLACES_CSV=str(ctx.require('places') / 'places_ak.csv'),
                    DEFAULTS_CSV=str(ctx.require('defaults') / 'place_defaults.csv'),
                    BASELINE_COVERAGE=str(b) if b else '', BASELINE_LABEL=ctx.model.get('BASELINE_MODEL') or
                    (ctx.model.get('BASELINE_COVERAGE_DIR') or ''), MODEL_CHANGE_JSON=str(mc) if mc.exists() else '',
                    REPORT_TITLE=f"NG-IDF run report: model {ctx.model['MODEL_LABEL']}")

    def prepare(self, ctx, d):
        stages = [dict(stage=s.name, dir=str(ctx.stage_dir(s.name))) for s in STAGE_LIST if s.name != self.name]
        (d / 'stages.json').write_text(json.dumps(stages, indent=1) + '\n')

    def jobs(self, ctx):
        return [Job('report', 'slurm/stages/qa.sbatch')]

    def checks(self, ctx, out):
        q = json.loads((out / 'qa.json').read_text())
        fid, fit = q['fidelity'], q['fits']
        c = [check('report written', (out / 'report.html').exists()),
             check('every run changes the app only in the allowed ways', fid['runs_with_unexpected_changes'] == 0
                   and fid['runs_with_diff'] > 0,
                   f"{fid['runs_with_diff']} runs, {len(fid['signatures'])} patterns, "
                   f"{fid['runs_with_unexpected_changes']} unexpected"),
             check('no missing values in fitted curves', fit['all_finite'] == fit['fits'],
                   f"{fit['all_finite']} of {fit['fits']}"),
             check('depth never decreases with return period', fit['monotonic'] == fit['fits'],
                   f"{fit['monotonic']} of {fit['fits']}"),
             check('CI contains the fitted value', fit['ci_brackets'] == fit['fits'],
                   f"{fit['ci_brackets']} of {fit['fits']}")]
        cmp_f = out / 'compare/compare.json'
        if cmp_f.exists():
            k = json.loads(cmp_f.read_text())
            c.append(check('identical to the baseline release', k['identical'] and not k['lost_values'],
                           f"{k['compared']} values; max |difference| {num(k['max_abs_diff_mm'])} mm; "
                           f"{k['new_values']} new, {k['lost_values']} no longer present (review section 7)", warn=True))
        return c, dict(fits=fit['fits']), {}, ''


STAGE_LIST = [
    EnvStage('env_ngidf', 'config/environment.lock.txt', title='Software environment (runs)'),
    EnvStage('env_msim', 'config/metsim_environment.lock.txt', 'config/metsim_pip.lock.txt',
             title='Software environment (MetSim)'),
    EnvStage('env_geo', 'config/geo_environment.lock.txt', title='Software environment (raster processing)'),
    AppStage(), InputsStage(), PlacesStage(), DefaultsStage(),
    *[ForcingStage(d) for d in WRF_CESM], DaymetForcingStage(),
    EnvStage('env_report', 'config/report_environment.lock.txt', title='Software environment (report)'),
    DhsvmStage(), ReferenceStage(), RunsStage(), CoverageStage(), QaStage(),
]
STAGES = {s.name: s for s in STAGE_LIST}
for _s in STAGE_LIST:
    if isinstance(_s, EnvStage):
        _s.needs = []


# ----------------------------------------------------------------------------------- stage actions
def status(ctx, name):
    try:
        d = ctx.stage_dir(name)
    except NotReady as e:
        return dict(stage=name, status='waiting', reason=str(e))
    rep = d / 'report.json'
    st = json.loads(rep.read_text())['status'] if rep.exists() else ('prepared' if (d / 'stage.json').exists() else 'todo')
    res = dict(stage=name, status=st, fingerprint=ctx.fingerprint(name), dir=str(d),
               needs=list(STAGES[name].needs))
    if st == 'prepared':    # submitted by an earlier run that did not finalize; its jobs may still be running
        res['job_ids'] = json.loads((d / 'stage.json').read_text()).get('job_ids', [])
    return res


def job_env(ctx, st, d):
    env = dict(REPO=str(REPO), CURATION_COMMIT=ctx.commit or 'unknown', DATA_ROOT=str(ctx.data_root),
               STAGE_NAME=st.name, STAGE_DIR=str(d), OUT=str(d / 'out'), FINGERPRINT=ctx.fingerprint(st.name),
               MODEL_LABEL=ctx.model['MODEL_LABEL'], RAW_FORCING_ROOT=ctx.paths['RAW_FORCING_ROOT'],
               AUTHOR_FORCING_ROOT=ctx.paths['AUTHOR_FORCING_ROOT'])
    env.update(st.env(ctx))
    return env


def prepare(ctx, name):
    st = STAGES[name]
    d = ctx.stage_dir(name)
    (d / 'out').mkdir(parents=True, exist_ok=True)
    (d / 'logs').mkdir(exist_ok=True)
    env = job_env(ctx, st, d)
    (d / 'job.env').write_text(''.join(f'{k}={shlex.quote(str(v))}\n' for k, v in env.items()))
    st.prepare(ctx, d)
    adopted = (d / 'adopted.json').exists()
    jobs = st.adopted_jobs(ctx) if adopted else st.jobs(ctx)
    meta = dict(stage=name, title=st.title, fingerprint=ctx.fingerprint(name), components=ctx.components(name),
                curation_commit=ctx.commit, curation_dirty=ctx.dirty, model=ctx.model, prepared=now(),
                adopted=adopted, jobs=[j.as_dict() for j in jobs])
    (d / 'stage.json').write_text(json.dumps(meta, indent=1) + '\n')
    return dict(stage=name, dir=str(d), job_env=str(d / 'job.env'), logs=str(d / 'logs'), adopted=adopted,
                jobs=[j.as_dict() for j in jobs], partition=ctx.paths['SLURM_PARTITION'], qos=ctx.paths['SLURM_QOS'])


def finalize(ctx, name, job_ids=None):
    st = STAGES[name]
    d = ctx.stage_dir(name)
    meta = json.loads((d / 'stage.json').read_text())
    try:
        checks, metrics, tables, md = st.checks(ctx, d / 'out')
    except Exception as e:  # missing outputs etc.
        checks, metrics, tables, md = [check('stage outputs readable', False, repr(e))], {}, {}, ''
    if meta.get('adopted'):
        a = json.loads((d / 'adopted.json').read_text())
        checks.insert(0, check('outputs produced by this pipeline (not adopted)', False,
                               f"adopted from {a['source']} ({a['note']}); checked again now", warn=True))
    # The fingerprint pins the content of the stage's code files, so if HEAD holds that content the
    # outputs are reproducible from this commit, whatever else in the repo is being edited.
    loose = uncommitted(sorted(meta['components']['code']))
    checks.append(check('curation code committed', not loose,
                        f"the stage's code is in commit {(ctx.commit or '?')[:7]}" if not loose else
                        'not committed: ' + ', '.join(loose), warn=True))
    order = {'fail': 2, 'warn': 1, 'pass': 0}
    worst = max((order[c['status']] for c in checks), default=0)
    report = dict(stage=name, title=st.title, explain=st.explain, status={0: 'pass', 1: 'warn', 2: 'fail'}[worst],
                  fingerprint=ctx.fingerprint(name), components=meta['components'], dir=str(d),
                  curation_commit=meta['curation_commit'], model_label=ctx.model['MODEL_LABEL'],
                  app_commit=ctx.model['APP_COMMIT'], adopted=meta.get('adopted', False),
                  prepared=meta['prepared'], finalized=now(), job_ids=job_ids or meta.get('job_ids', []),
                  checks=checks, metrics=metrics, tables=tables, summary_md=md)
    (d / 'report.json').write_text(json.dumps(report, indent=1, default=str) + '\n')
    return report


def adopt(ctx, name, source, note):
    """Register outputs produced before this pipeline existed (e.g. the 2026-11-17 forcing extraction,
    ~30 TB of reads). The outputs are linked, not copied, and the stage's validation jobs still run."""
    st = STAGES[name]
    d = ctx.stage_dir(name)
    out = d / 'out'
    out.mkdir(parents=True, exist_ok=True)
    src = Path(source).resolve()
    if isinstance(st, ForcingStage):
        link = out / st.ds
    elif isinstance(st, EnvStage):
        link = out / 'env'
    elif isinstance(st, AppStage):
        link = out / 'app'
    else:
        raise SystemExit(f'adopt is not supported for {name}')
    if link.exists() or link.is_symlink():
        raise SystemExit(f'{link} exists')
    link.symlink_to(src)
    (d / 'adopted.json').write_text(json.dumps(dict(source=str(src), note=note, adopted=now(),
                                                    curation_commit=ctx.commit), indent=1) + '\n')
    return str(link)


def sbatch(ctx, prep, job, deps):
    d = Path(prep['dir'])
    out = d / 'logs' / (f'{job["name"]}_%A_%a.out' if job['array'] else f'{job["name"]}_%j.out')
    cmd = ['sbatch', '--parsable', f'--job-name=ngidf-{prep["stage"]}-{job["name"]}', f'--output={out}',
           f'--partition={prep["partition"]}', f'--qos={prep["qos"]}', f'--chdir={REPO}']
    if job['array']:
        cmd.append(f'--array={job["array"]}')
    if deps:
        cmd.append('--dependency=afterok:' + ':'.join(deps))
    cmd += [str(REPO / job['script']), prep['job_env']] + job['args']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'sbatch failed: {r.stderr}')
    return r.stdout.strip().split(';')[0]


def run_login(prep, job):
    env = load_kv(prep['job_env'])
    args = [os.path.expandvars(a.replace('$OUT', env['OUT']).replace('$REPO', env['REPO'])) for a in job['args']]
    log = Path(prep['logs']) / f"{job['name']}_login.out"
    with open(log, 'w') as f:
        r = subprocess.run(['bash', str(REPO / job['script']), prep['job_env'], *args], stdout=f, stderr=subprocess.STDOUT)
    if r.returncode:
        raise SystemExit(f"{job['name']} failed; see {log}")


def wait(job_ids, poll=30):
    # List the user's own jobs rather than `squeue -j <ids>`: once a finished job has aged out of
    # Slurm's memory, -j fails with "Invalid job id" and the wait would never end.
    pending = set(job_ids)
    user = os.environ.get('USER') or subprocess.run(['whoami'], capture_output=True, text=True).stdout.strip()
    while pending:
        r = subprocess.run(['squeue', '-h', '-o', '%A', '-u', user], capture_output=True, text=True)
        if r.returncode == 0:   # a failed squeue (transient) keeps everything pending
            pending &= set(r.stdout.split())
        if pending:
            time.sleep(poll)


def submit(ctx, name, do_wait):
    prep = prepare(ctx, name)
    ids = {}
    for job in prep['jobs']:
        if job['kind'] == 'login':
            run_login(prep, job)
            continue
        ids[job['name']] = sbatch(ctx, prep, job, [ids[a] for a in job['after'] if a in ids])
        print(f"submitted {name}/{job['name']} as job {ids[job['name']]}", file=sys.stderr, flush=True)
    meta_p = Path(prep['dir']) / 'stage.json'
    meta = json.loads(meta_p.read_text())
    meta['job_ids'] = list(ids.values())
    meta_p.write_text(json.dumps(meta, indent=1) + '\n')
    res = dict(stage=name, dir=prep['dir'], job_ids=list(ids.values()), finalized=False, status='submitted')
    if do_wait or not ids:      # login-only stages are finished when submit returns
        wait(list(ids.values()))
        rep = finalize(ctx, name, list(ids.values()))
        res.update(finalized=True, status=rep['status'],
                   checks=[f"{c['status']}: {c['name']} {c['detail']}" for c in rep['checks']])
    return res


def retire(ctx, name):
    """Move a failed or interrupted attempt to <dir>.retired-<time> so the stage can run again from an
    empty directory. The old attempt (logs, report) is kept for the record; passing stages are refused."""
    d = ctx.stage_dir(name)
    st = status(ctx, name)['status']
    if st in ('pass', 'warn'):
        raise SystemExit(f'{name} has passed ({d}); passing stages are never retired')
    if not d.exists():
        return dict(stage=name, retired=None)
    dest = d.with_name(d.name + '.retired-' + dt.datetime.now().strftime('%Y%m%dT%H%M%S'))
    d.rename(dest)
    return dict(stage=name, status_was=st, retired=str(dest))


def release(ctx, name):
    rel = ctx.data_root / 'releases' / name
    if rel.exists():
        raise SystemExit(f'{rel} exists: releases are never overwritten')
    stages = []
    for s in STAGE_LIST:
        st = status(ctx, s.name)
        if st['status'] not in ('pass', 'warn'):
            raise SystemExit(f"{s.name} is {st['status']}: cannot release")
        stages.append(dict(stage=s.name, fingerprint=st['fingerprint'], dir=st['dir'], status=st['status']))
    rel.mkdir(parents=True)
    (rel / 'reports').mkdir()
    for s in stages:
        shutil.copy2(Path(s['dir']) / 'report.json', rel / 'reports' / f"{s['stage']}.json")
    cov = ctx.require('coverage')
    (rel / 'coverage').symlink_to(cov)
    shutil.copy2(ctx.require('qa') / 'report.html', rel / 'report.html')
    info = dict(release=name, created=now(), model=ctx.model, curation_commit=ctx.commit, curation_dirty=ctx.dirty,
                stages=stages)
    (rel / 'release.json').write_text(json.dumps(info, indent=1) + '\n')
    return info


# ---------------------------------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model-version')
    ap.add_argument('--data-root')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('plan')
    sub.add_parser('info')
    for c in ('prepare', 'finalize', 'submit', 'adopt', 'fingerprint', 'retire'):
        p = sub.add_parser(c)
        p.add_argument('--stage', required=True, choices=list(STAGES))
        if c == 'submit':
            p.add_argument('--wait', action='store_true')
        if c == 'finalize':
            p.add_argument('--job-ids', nargs='*')
        if c == 'adopt':
            p.add_argument('--source', required=True)
            p.add_argument('--note', required=True)
    r = sub.add_parser('release')
    r.add_argument('--name', required=True)
    a = ap.parse_args()
    ctx = Context(a.model_version, a.data_root)
    if a.cmd == 'info':
        print(json.dumps(dict(model_file=str(ctx.model_file.relative_to(REPO)), model=ctx.model,
                              curation_commit=ctx.commit, curation_dirty=ctx.dirty,
                              curation_branch=git('rev-parse', '--abbrev-ref', 'HEAD'),
                              curation_remote=git('remote', 'get-url', 'origin'), data_root=str(ctx.data_root),
                              slurm=dict(partition=ctx.paths['SLURM_PARTITION'], qos=ctx.paths['SLURM_QOS'])),
                         indent=1))
    elif a.cmd == 'plan':
        print(json.dumps([status(ctx, s.name) | dict(title=s.title) for s in STAGE_LIST], indent=1))
    elif a.cmd == 'fingerprint':
        print(json.dumps(dict(fingerprint=ctx.fingerprint(a.stage), components=ctx.components(a.stage)), indent=1))
    elif a.cmd == 'prepare':
        print(json.dumps(prepare(ctx, a.stage), indent=1))
    elif a.cmd == 'finalize':
        rep = finalize(ctx, a.stage, a.job_ids)
        print(json.dumps({k: rep[k] for k in ('stage', 'status', 'checks', 'metrics')}, indent=1, default=str))
        sys.exit(1 if rep['status'] == 'fail' else 0)
    elif a.cmd == 'submit':
        res = submit(ctx, a.stage, a.wait)
        print(json.dumps(res, indent=1))
        sys.exit(1 if res['status'] == 'fail' else 0)
    elif a.cmd == 'retire':
        print(json.dumps(retire(ctx, a.stage), indent=1))
    elif a.cmd == 'adopt':
        print(adopt(ctx, a.stage, a.source, a.note))
    elif a.cmd == 'release':
        print(json.dumps(release(ctx, a.name), indent=1))


if __name__ == '__main__':
    main()
