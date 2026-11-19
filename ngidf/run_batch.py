"""Batch driver for ngidf/run_point.py (Phase 1: places × datasets).

  manifest  Build runs.csv: one row per (place, dataset) with every input the run needs.
  run       Execute a slice of the manifest (Slurm array task), N runs in parallel.
            Each run is a separate process (run_point.py) working in node-local /tmp.
            Runs whose run.json says status=ok are skipped, so the job can be resubmitted.
            A run where the model itself stops (run.json status=failed, e.g. DHSVM error 48) is a
            result, as it would be in the app: the task still exits 0. A task exits 1 only when a
            run left no run.json (infrastructure problem), so retrying the task makes sense.
  status    Summarise run outcomes.
"""
import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
WRF_CESM = ['WRF_historical', 'WRF_medium', 'WRF_high'] + [
    f'CESM_{p}_LE{m}' for p in ('hist', 'futu') for m in (2, 4, 7, 9)]
DAYMET = 'Daymet'


def cmd_manifest(args):
    places = pd.read_csv(args.places, dtype={'wrf_key': str, 'daymet_key': str})
    defaults = pd.read_csv(args.defaults)
    df = places.merge(defaults[['id', 'cover_code', 'lai', 'height_m', 'defaults_source']], on='id', how='left')
    if df.cover_code.isna().any():
        raise ValueError(f"missing defaults for {df.loc[df.cover_code.isna(), 'id'].tolist()}")
    rows = []
    skipped = df.loc[df.cover_code < 0, 'id'].tolist()
    if skipped:
        print(f'no land-cover defaults (nodata): {skipped}')
    for _, p in df[df.cover_code >= 0].iterrows():
        for ds in args.datasets:
            if ds == DAYMET:
                if p.daymet_status != 'ok':
                    continue
                key = p.daymet_key
            else:
                if p.wrf_cesm_status != 'ok':
                    continue
                key = p.wrf_key
            forcing = Path(args.forcing_root) / ds / f'data_{key}'
            rows.append(dict(place_id=p.id, dataset=ds, cell_key=key, forcing_file=str(forcing),
                             lat=p.latitude, lon=p.longitude, cover=int(p.cover_code), lai=float(p.lai),
                             height=float(p.height_m), defaults_source=p.defaults_source))
    m = pd.DataFrame(rows)
    missing = [f for f in m.forcing_file.unique() if not Path(f).exists()]
    if missing and not args.allow_missing_forcing:
        raise ValueError(f'{len(missing)} forcing files missing, e.g. {missing[:3]}')
    m.to_csv(args.out, index=False)
    print(f'{len(m)} runs -> {args.out}; datasets: {m.dataset.value_counts().to_dict()}')


def run_one(row, args):
    out = Path(args.out_root) / row.place_id / row.dataset
    rj = out / 'run.json'
    if rj.exists():
        try:
            if json.loads(rj.read_text()).get('status') == 'ok':
                return row.place_id, row.dataset, 'skipped'
        except json.JSONDecodeError:
            pass
    cmd = [sys.executable, '-I', str(REPO / 'ngidf/run_point.py'), '--app-dir', args.app_dir,
           '--dhsvm-bin', args.dhsvm_bin, '--forcing-type', row.dataset, '--forcing-file', row.forcing_file,
           '--cell-key', row.cell_key, '--place-id', row.place_id, '--lat', repr(row.lat), '--lon', repr(row.lon),
           '--cover', str(row.cover), '--lai', repr(row.lai), '--height', repr(row.height), '--out', str(out),
           '--work-root', args.work_root]
    if args.keep_pixel:
        cmd.append('--keep-pixel')
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        return row.place_id, row.dataset, 'ok'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'stderr.log').write_text(r.stderr[-20000:])
    try:
        recorded = json.loads(rj.read_text()).get('status') == 'failed'
    except (OSError, json.JSONDecodeError):
        recorded = False
    return row.place_id, row.dataset, 'model-failed (recorded)' if recorded else f'FAILED rc={r.returncode}'


def cmd_run(args):
    m = pd.read_csv(args.manifest, dtype={'cell_key': str})
    part = m.iloc[args.task::args.ntasks]
    print(f'task {args.task}/{args.ntasks}: {len(part)} runs, {args.workers} workers', flush=True)
    fails = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for pid, ds, st in ex.map(lambda r: run_one(r, args), part.itertuples(index=False)):
            print(pid, ds, st, flush=True)
            fails += st.startswith('FAILED')
    print(f'done; {fails} runs without a result', flush=True)
    sys.exit(1 if fails else 0)


def cmd_status(args):
    m = pd.read_csv(args.manifest)
    st = []
    for r in m.itertuples(index=False):
        rj = Path(args.out_root) / r.place_id / r.dataset / 'run.json'
        st.append(json.loads(rj.read_text()).get('status', '?') if rj.exists() else 'missing')
    m['status'] = st
    print(m.groupby(['dataset', 'status']).size().unstack(fill_value=0).to_string())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('manifest')
    a.add_argument('--places', default=str(REPO / 'data/places/places_ak.csv'))
    a.add_argument('--defaults', default=str(REPO / 'data/places/place_defaults.csv'))
    a.add_argument('--forcing-root', required=True)
    a.add_argument('--datasets', nargs='+', default=WRF_CESM, choices=WRF_CESM + [DAYMET])
    a.add_argument('--allow-missing-forcing', action='store_true')
    a.add_argument('--out', required=True)
    a.set_defaults(func=cmd_manifest)
    b = sub.add_parser('run')
    b.add_argument('--manifest', required=True)
    b.add_argument('--task', type=int, required=True)
    b.add_argument('--ntasks', type=int, required=True)
    b.add_argument('--workers', type=int, default=8)
    b.add_argument('--app-dir', required=True)
    b.add_argument('--dhsvm-bin', required=True)
    b.add_argument('--out-root', required=True)
    b.add_argument('--work-root', default=os.environ.get('TMPDIR', '/tmp'))
    b.add_argument('--keep-pixel', action='store_true')
    b.set_defaults(func=cmd_run)
    c = sub.add_parser('status')
    c.add_argument('--manifest', required=True)
    c.add_argument('--out-root', required=True)
    c.set_defaults(func=cmd_status)
    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
