"""What changed in the author's app between two versions (model-change report).

Compares two app checkouts:
  * the method settings parsed from the code (ngidf/appinfo.py): distribution, bootstrap size, CI
    quantiles, the Pixel.CENTER columns extract_AM.py reads, the DHSVM config keys;
  * every science file (get_IDF.R, extract_AM.py, dhsvm_idf.py, app.py, the config template and
    parameter tables): unified diffs;
  * the DHSVM source tree and the fixed model inputs (input/, example_config/): files added,
    removed, modified.

    python -I ngidf/qa/model_change.py <old_app> <new_app> --json out.json --md out.md
"""
import argparse
import difflib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appinfo  # noqa: E402

MAX_DIFF_LINES = 400


def method_rows(old, new):
    rows = []
    for k in ('distribution', 'lmoments', 'drops_first_am', 'bootstrap_samples', 'ci_quantiles', 'ci_level_percent',
              'probabilities_expr'):
        a, b = old['get_idf'].get(k), new['get_idf'].get(k)
        rows.append(dict(setting=f'get_IDF.R {k}', old=a, new=b, changed=a != b))
    a, b = old['extract_am']['pixel_columns'], new['extract_am']['pixel_columns']
    for f in sorted(set(a) | set(b)):
        rows.append(dict(setting=f'extract_AM.py reads {f} from Pixel.CENTER column', old=a.get(f), new=b.get(f),
                         changed=a.get(f) != b.get(f)))
    fa, fb = old['extract_am']['functions'], new['extract_am']['functions']
    rows.append(dict(setting='extract_AM.py functions', old=fa, new=fb, changed=fa != fb))
    return rows


def file_diff(old_dir, new_dir, rel):
    a, b = Path(old_dir) / rel, Path(new_dir) / rel
    ta = a.read_text(errors='replace') if a.exists() else ''
    tb = b.read_text(errors='replace') if b.exists() else ''
    if ta == tb:
        return dict(file=rel, status='unchanged')
    status = 'added' if not a.exists() else 'removed' if not b.exists() else 'modified'
    lines = list(difflib.unified_diff(ta.splitlines(True), tb.splitlines(True), f'old/{rel}', f'new/{rel}', n=2))
    plus = sum(1 for l in lines if l.startswith('+') and not l.startswith('+++'))
    minus = sum(1 for l in lines if l.startswith('-') and not l.startswith('---'))
    text = ''.join(lines[:MAX_DIFF_LINES]) + (f'... ({len(lines) - MAX_DIFF_LINES} more diff lines)\n'
                                              if len(lines) > MAX_DIFF_LINES else '')
    return dict(file=rel, status=status, lines_added=plus, lines_removed=minus, diff=text)


def tree_changes(old, new, prefix):
    a = {k: v for k, v in old['tree'].items() if k.startswith(prefix)}
    b = {k: v for k, v in new['tree'].items() if k.startswith(prefix)}
    return dict(added=sorted(set(b) - set(a)), removed=sorted(set(a) - set(b)),
                modified=sorted(k for k in set(a) & set(b) if a[k] != b[k]))


def compare(old_dir, new_dir):
    old, new = appinfo.app_info(old_dir), appinfo.app_info(new_dir)
    keys_a, keys_b = set(old['config_keys'] or []), set(new['config_keys'] or [])
    out = dict(old=dict(dir=str(old_dir), commit=old['commit']), new=dict(dir=str(new_dir), commit=new['commit']),
               method=method_rows(old, new),
               config_keys=dict(added=sorted(keys_b - keys_a), removed=sorted(keys_a - keys_b)),
               files=[file_diff(old_dir, new_dir, rel) for rel in appinfo.SCIENCE_FILES],
               dhsvm_source=tree_changes(old, new, 'dhsvm/'),
               model_inputs=tree_changes(old, new, 'input/'),
               example_config=tree_changes(old, new, 'example_config/'),
               compatibility_problems=appinfo.compatibility_problems(new))
    out['method_changed'] = [r['setting'] for r in out['method'] if r['changed']]
    out['science_files_changed'] = [f['file'] for f in out['files'] if f['status'] != 'unchanged']
    return out


def render_md(c):
    L = [f"### Model change: `{(c['old']['commit'] or '?')[:7]}` → `{(c['new']['commit'] or '?')[:7]}`", '']
    if c['compatibility_problems']:
        L += ['**The batch wrapper cannot run the new version unchanged:**', '']
        L += [f'- {p}' for p in c['compatibility_problems']] + ['']
    L += ['**Method settings read from the code**', '', '| Setting | Old | New |', '|---|---|---|']
    for r in c['method']:
        mark = ' **(changed)**' if r['changed'] else ''
        L.append(f"| {r['setting']} | `{r['old']}` | `{r['new']}`{mark} |")
    k = c['config_keys']
    L += ['', f"**DHSVM config template keys:** added {k['added'] or 'none'}; removed {k['removed'] or 'none'}", '']
    L += ['**Science files**', '', '| File | Status | +/- lines |', '|---|---|---|']
    for f in c['files']:
        L.append(f"| `{f['file']}` | {f['status']} | {f.get('lines_added', '')}/{f.get('lines_removed', '')} |")
    for name, t in (('DHSVM source', c['dhsvm_source']), ('Fixed model inputs (input/)', c['model_inputs']),
                    ('example_config/', c['example_config'])):
        L += ['', f"**{name}:** {len(t['added'])} added, {len(t['removed'])} removed, {len(t['modified'])} modified"]
        for kind in ('added', 'removed', 'modified'):
            if t[kind]:
                L.append(f"- {kind}: " + ', '.join(f'`{x}`' for x in t[kind][:40]))
    for f in c['files']:
        if f.get('diff') and f['file'] in ('get_IDF.R', 'extract_AM.py', 'example_config/Input.Snotel.T4',
                                           'dhsvm_idf.py'):
            L += ['', f"<details><summary>diff {f['file']}</summary>", '', '```diff', f['diff'].rstrip(), '```',
                  '', '</details>']
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('old_app')
    ap.add_argument('new_app')
    ap.add_argument('--json')
    ap.add_argument('--md')
    a = ap.parse_args()
    c = compare(a.old_app, a.new_app)
    if a.json:
        Path(a.json).write_text(json.dumps(c, indent=1, default=str) + '\n')
    md = render_md(c)
    if a.md:
        Path(a.md).write_text(md)
    else:
        print(md)


if __name__ == '__main__':
    main()
