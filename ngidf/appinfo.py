"""Read the scientific settings of an NG-IDF app checkout directly from its code.

Nothing here is configured by hand: every value is parsed from the author's files, so a new app
version that changes the method (e.g. the 90 % -> 95 % CI change on hydro-yan `add_Tsoil`) shows
up in the model-change report and in the coverage metadata automatically, and the pipeline stops
if a change would break our wrapper.

    python -I ngidf/appinfo.py <app_dir> [--pixel-header <Pixel.CENTER or .gz>]   # prints JSON
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

# Files whose content defines the method. Diffed between model versions in the change report.
SCIENCE_FILES = [
    'get_IDF.R', 'extract_AM.py', 'dhsvm_idf.py', 'app.py',
    'example_config/Input.Snotel.T4',
    'example_config/param_5cluster_ensembleMean_CONUS.csv',
    'example_config/veg_param_type_cluster.csv',
    'static/gridcell_current_lulc.csv',
]
SCIENCE_DIRS = ['dhsvm/no_sat_dump', 'input', 'example_config']

# extract_AM.py reads Pixel.CENTER fields by position; these are the header names they must have.
EXPECTED_PIXEL_FIELDS = {'W_veg': 'W_veg(mm)', 'Precip': 'Precip(m)', 'P_int': 'P_int(m)',
                         'deltaSWE': 'deltaSWE(m)', 'SWE': 'Swq'}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def git_commit(app_dir):
    r = subprocess.run(['git', '-C', str(app_dir), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def git_dirty(app_dir):
    """Tracked files modified, ignoring the __pycache__/*.pyc files the upstream repo tracks (importing
    the modules can rewrite them; they never affect a run because the .py sources are what we hash)."""
    r = subprocess.run(['git', '-C', str(app_dir), 'status', '--porcelain', '--untracked-files=no'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return any('__pycache__/' not in line for line in r.stdout.splitlines())


def parse_get_idf(text):
    """Distribution, bootstrap size, CI percentiles, probabilities and the first-year drop."""
    q = [float(x) for x in re.findall(r'quantile\(\s*flow\[\s*,\s*k\s*\]\s*,\s*([0-9.]+)', text)]
    nsim = re.search(r'flow\s*<-\s*matrix\(\s*0\s*,\s*nrow\s*=\s*(\d+)', text)
    probs = re.search(r'probs\s*<-\s*(c\([^\n]*\))', text)
    info = dict(
        distribution=('Gumbel (lmom pelgum/quagum)' if 'pelgum' in text and 'quagum' in text
                      else 'GEV (lmom pelgev/quagev)' if 'pelgev' in text else 'unknown'),
        lmoments='samlmu' in text,
        bootstrap_samples=int(nsim.group(1)) if nsim else None,
        ci_quantiles=sorted(q) if q else None,
        probabilities_expr=probs.group(1) if probs else None,
        lmom_libloc_line="library(lmom, lib.loc='/hongxiang/app/Rlibrary')" in text,
        drops_first_am=bool(re.search(r'data\s*\[\s*-\s*1\s*,\s*\]', text)),
    )
    if info['ci_quantiles'] and len(info['ci_quantiles']) == 2:
        lo, hi = info['ci_quantiles']
        info['ci_level_percent'] = round(100 * (hi - lo), 6)
    else:
        info['ci_level_percent'] = None
    return info


def parse_extract_am(text):
    """Map of Pixel.CENTER field -> column index read by extract_AM.py (`float(item[N])  # name`)."""
    cols = {}
    for idx, name in re.findall(r'float\(item\[(\d+)\]\)[^#\n]*#\s*([A-Za-z_]+)', text):
        cols[name] = int(idx)
    funcs = re.findall(r'^def (\w+)\(', text, flags=re.M)
    return dict(pixel_columns=cols, functions=funcs)


def parse_config_template(text):
    keys = []
    for line in text.splitlines():
        line = line.split('#', 1)[0]
        if '=' in line:
            keys.append(re.sub(r'\s+', ' ', line.split('=', 1)[0].strip()))
    return keys


def read_header(pixel_file):
    p = Path(pixel_file)
    opener = gzip.open if p.suffix == '.gz' else open
    with opener(p, 'rt') as f:
        return f.readline().split()


def check_pixel_header(header, pixel_columns):
    """Compare the names at the indices extract_AM.py reads with the expected names."""
    out = []
    for field, expected in EXPECTED_PIXEL_FIELDS.items():
        idx = pixel_columns.get(field)
        got = header[idx] if idx is not None and idx < len(header) else None
        out.append(dict(field=field, index=idx, expected=expected, found=got, ok=got == expected))
    return out


def app_info(app_dir, pixel_header=None):
    app = Path(app_dir)
    idf = parse_get_idf((app / 'get_IDF.R').read_text())
    am = parse_extract_am((app / 'extract_AM.py').read_text())
    tmpl = app / 'example_config/Input.Snotel.T4'
    files = {}
    for rel in SCIENCE_FILES:
        f = app / rel
        files[rel] = sha256_file(f) if f.exists() else None
    tree = {}
    for d in SCIENCE_DIRS:
        for f in sorted((app / d).rglob('*')):
            if f.is_file() and '__pycache__' not in f.parts:
                tree[str(f.relative_to(app))] = sha256_file(f)
    info = dict(app_dir=str(app), commit=git_commit(app), dirty=git_dirty(app), get_idf=idf, extract_am=am,
                config_keys=parse_config_template(tmpl.read_text()) if tmpl.exists() else None,
                science_files=files, tree=tree)
    if pixel_header:
        info['pixel_header_check'] = check_pixel_header(read_header(pixel_header), am['pixel_columns'])
    return info


def compatibility_problems(info):
    """Reasons our batch wrapper cannot run this app version unchanged (empty list = compatible)."""
    p = []
    g = info['get_idf']
    if not g['lmom_libloc_line']:
        p.append("get_IDF.R: the hard-coded lib.loc line our wrapper removes was not found")
    if g['ci_level_percent'] is None:
        p.append('get_IDF.R: could not read the CI quantiles')
    if g['bootstrap_samples'] is None:
        p.append('get_IDF.R: could not read the bootstrap sample count')
    cols = info['extract_am']['pixel_columns']
    for field in EXPECTED_PIXEL_FIELDS:
        if field not in cols:
            p.append(f'extract_AM.py: no column read for {field}')
    if 'extract_AM_data' not in info['extract_am']['functions']:
        p.append('extract_AM.py: extract_AM_data() not found')
    for c in info.get('pixel_header_check') or []:
        if not c['ok']:
            p.append(f"Pixel.CENTER column {c['index']} is {c['found']!r}, extract_AM.py reads it as {c['field']} "
                     f"(expected {c['expected']!r})")
    if info.get('dirty'):
        p.append('app checkout has local modifications')
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('app_dir')
    ap.add_argument('--pixel-header')
    ap.add_argument('--no-tree', action='store_true')
    a = ap.parse_args()
    info = app_info(a.app_dir, a.pixel_header)
    info['compatibility_problems'] = compatibility_problems(info)
    if a.no_tree:
        info.pop('tree')
    print(json.dumps(info, indent=1))


if __name__ == '__main__':
    main()
