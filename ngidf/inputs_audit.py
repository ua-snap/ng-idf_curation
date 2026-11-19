"""Audit the pipeline's source data (pipeline stage `inputs`).

* Downloaded inputs: verify every file listed in each raw directory's SHA256SUMS (written at download).
* Daymet single-pixel downloads: count files, and the cells Daymet does not cover (.error files).
* Read-only archives (WRF/CESM 4 km forcing, the author's NG-IDL station files): list file counts,
  sizes and date span. They are too large to hash; their identity is their path, and they are read only.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forcing  # noqa: E402  (dataset -> archive directory map)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


def verify(args):
    path, want = args
    if not path.exists():
        return str(path), 'missing'
    return str(path), 'ok' if sha256(path) == want else 'mismatch'


def checksums(raw_dir, workers):
    sums = raw_dir / 'SHA256SUMS'
    jobs = []
    for line in sums.read_text().splitlines():
        if line.strip():
            want, name = line.split(maxsplit=1)
            name = name.lstrip('*').strip()
            p = Path(name) if Path(name).is_absolute() else raw_dir / name
            jobs.append((p, want))
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(verify, jobs))
    bad = [dict(file=f, problem=s) for f, s in res if s != 'ok']
    size = sum(p.stat().st_size for p, _ in jobs if p.exists())
    return dict(dir=str(raw_dir), files=len(jobs), ok=len(jobs) - len(bad), failed=len(bad), bytes=size,
                problems=bad[:20])


def listing(directory, date_re=r'(\d{4})-(\d{2})-(\d{2})\.nc$'):
    d = Path(directory)
    n = size = 0
    dates = []
    with os.scandir(d) as it:
        for e in it:
            if e.is_file():
                n += 1
                size += e.stat().st_size
                m = re.search(date_re, e.name)
                if m:
                    dates.append(m.group(0)[:10])
    return dict(files=n, bytes=size, first=min(dates) if dates else None, last=max(dates) if dates else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-root', required=True)
    ap.add_argument('--raw-dirs', nargs='+', required=True)
    ap.add_argument('--pixel-dir', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    root = Path(a.data_root)
    out = dict(checksums=[checksums(root / r, a.workers) for r in a.raw_dirs])
    pix = Path(a.pixel_dir)
    out['daymet_pixels'] = dict(dir=str(pix), csv=len(list(pix.glob('pix_*.csv'))),
                                outside_daymet=sorted(p.stem[4:] for p in pix.glob('pix_*.error')))
    raw = []
    for ds, rel in forcing.DATASETS.items():
        raw.append(dict(dataset=ds, dir=str(forcing.RAW_ROOT / rel), **listing(forcing.RAW_ROOT / rel)))
    out['raw_forcing'] = raw
    ref = Path(os.environ.get('AUTHOR_FORCING_ROOT', '/import/beegfs/CMIP6/arctic-cmip6/NG-IDL'))
    out['author_forcing'] = [dict(dir=str(p), **listing(p, r'^data_')) for p in sorted(ref.glob('dhsvm_*/*'))
                             if p.is_dir()] + [dict(dir=str(p), **listing(p, r'^data_'))
                                               for p in sorted(ref.glob('dhsvm_daymet_*')) if p.is_dir()]
    Path(a.out).write_text(json.dumps(out, indent=1) + '\n')
    for c in out['checksums']:
        print(c['dir'], c['ok'], '/', c['files'], 'ok')


if __name__ == '__main__':
    main()
