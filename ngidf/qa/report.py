"""Self-contained HTML report of a pipeline release (pipeline stage `qa`).

One file, figures embedded, nothing loaded from the network, so it can be emailed (e.g. to H. Yan)
or attached to the Prefect run. Sections:

  1. Summary            every stage: what it does (plain language), pass / warning / fail, key result
  2. Method             the settings read from the author's code; what changed since the baseline version
  3. Faithfulness       what our batch wrapper changes in each run's copy of the app (diffs), and the
                        DHSVM configuration the app wrote vs its template
  4. Validation         forcing vs the author's files, defaults vs his table, reference runs
  5. Runs and fits      run outcomes, failures by cause, checks on every fitted curve
  6. Results            100-year depths, NG/P, rain/snowmelt mix, maps, community curves
  7. Version change     current vs baseline release
  8. Provenance         fingerprints, commits, environments, checksums, Slurm job ids

    python -I ngidf/qa/report.py --stages <stages.json> --qa <qa dir> [--compare <dir>] \
        [--model-change <json>] --title T --out report.html
"""
import argparse
import base64
import datetime as dt
import html
import json
from pathlib import Path

GOOD, WARN, BAD = '#0ca30c', '#fab219', '#d03b3b'
ICON = {'pass': ('✓', 'Pass', GOOD), 'warn': ('!', 'Warning', WARN), 'fail': ('✕', 'Fail', BAD)}

CSS = """
:root { --surface:#fcfcfb; --text:#0b0b0b; --text2:#52514e; --muted:#7a7974; --rule:#e4e3df; --tint:#f4f3f0; }
* { box-sizing: border-box; }
body { margin:0; background:var(--surface); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 20px; margin: 40px 0 8px; padding-top: 8px; border-top: 1px solid var(--rule); }
h3 { font-size: 16px; margin: 24px 0 6px; } p, li { color: var(--text); max-width: 75ch; }
.sub { color: var(--text2); margin: 0 0 16px; } .small { font-size: 13px; color: var(--text2); }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0 12px; display: block; overflow-x: auto; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { color: var(--text2); font-weight: 600; background: var(--tint); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.badge { display:inline-flex; align-items:center; gap:4px; font-weight:600; font-size:12px; white-space:nowrap; }
.dot { display:inline-grid; place-items:center; width:16px; height:16px; border-radius:50%; color:#fff; font-size:11px; }
pre { background: var(--tint); padding: 10px; overflow-x: auto; font-size: 12px; line-height: 1.35; border-radius: 4px; }
pre .add { color: #0a6b0a; } pre .del { color: #a42525; } pre .hunk { color: var(--muted); }
details { margin: 6px 0; } summary { cursor: pointer; color: var(--text2); }
figure { margin: 12px 0 20px; } figure img { max-width: 100%; height: auto; border: 1px solid var(--rule); }
figcaption { font-size: 13px; color: var(--text2); }
.kv { display:grid; grid-template-columns: max-content 1fr; gap: 2px 16px; font-size: 14px; }
.kv div:nth-child(odd) { color: var(--text2); }
nav a { color: var(--text2); margin-right: 12px; font-size: 13px; }
"""


def esc(x):
    return html.escape('' if x is None else str(x))


def badge(status):
    i, label, col = ICON.get(status, ('?', status, '#7a7974'))
    return f'<span class="badge"><span class="dot" style="background:{col}">{i}</span>{label}</span>'


def fmt(v):
    if isinstance(v, float):
        return f'{v:.6g}'
    if isinstance(v, (list, dict)):
        return esc(json.dumps(v, default=str))
    return esc(v)


def tbl(rows, cols=None, labels=None):
    rows = list(rows or [])
    if not rows:
        return '<p class="small">(none)</p>'
    cols = cols or list(rows[0].keys())
    labels = labels or {}
    h = ''.join(f'<th>{esc(labels.get(c, c))}</th>' for c in cols)
    body = ''
    for r in rows:
        body += '<tr>' + ''.join(
            f'<td class="num">{fmt(r.get(c))}</td>' if isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool)
            else f'<td>{badge(r[c]) if c == "status" else fmt(r.get(c))}</td>' for c in cols) + '</tr>'
    return f'<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>'


def diff_block(text, limit=200):
    out = []
    for line in (text or '').splitlines()[:limit]:
        cls = 'hunk' if line.startswith('@@') else 'add' if line.startswith('+') else 'del' if line.startswith('-') else ''
        out.append(f'<span class="{cls}">{esc(line)}</span>' if cls else esc(line))
    return '<pre>' + '\n'.join(out) + '</pre>'


def img(path, caption):
    p = Path(path)
    if not p.exists():
        return ''
    b64 = base64.b64encode(p.read_bytes()).decode()
    return (f'<figure><img alt="{esc(caption)}" src="data:image/png;base64,{b64}">'
            f'<figcaption>{esc(caption)}</figcaption></figure>')


def checks_tbl(rep):
    return tbl([dict(status=c['status'], check=c['name'], detail=c['detail']) for c in rep['checks']])


def build(a):
    stages = json.loads(Path(a.stages).read_text())
    reps = {}
    for s in stages:
        f = Path(s['dir']) / 'report.json'
        if f.exists():
            reps[s['stage']] = json.loads(f.read_text())
    qa = json.loads((Path(a.qa) / 'qa.json').read_text())
    cmp_ = json.loads((Path(a.compare) / 'compare.json').read_text()) if a.compare and (Path(a.compare) / 'compare.json').exists() else None
    mc = json.loads(Path(a.model_change).read_text()) if a.model_change and Path(a.model_change).exists() else None
    app = reps.get('app', {})
    order = {'fail': 2, 'warn': 1, 'pass': 0}
    overall = max((r['status'] for r in reps.values()), key=lambda s: order.get(s, 0), default='warn')
    any_rep = next(iter(reps.values()), {})

    H = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
         f'content="width=device-width,initial-scale=1"><title>NG-IDF run report</title><style>{CSS}</style></head><body><main>']
    H.append(f'<h1>{esc(a.title)}</h1><p class="sub">Generated {dt.datetime.now():%Y-%m-%d %H:%M} · overall {badge(overall)}</p>')
    H.append('<div class="kv">'
             f'<div>Model version</div><div>{esc(any_rep.get("model_label"))}</div>'
             f'<div>Author\'s app commit</div><div><code>{esc(any_rep.get("app_commit"))}</code></div>'
             f'<div>SNAP processing code</div><div>ua-snap/ng-idf_curation <code>{esc(any_rep.get("curation_commit"))}</code></div>'
             '</div>')
    H.append('<nav><a href="#summary">Summary</a><a href="#method">Method</a><a href="#fidelity">Faithfulness</a>'
             '<a href="#validation">Validation</a><a href="#runs">Runs</a><a href="#results">Results</a>'
             '<a href="#change">Version change</a><a href="#provenance">Provenance</a></nav>')

    # 1 summary
    H.append('<h2 id="summary">1. Summary</h2><p>Each row is one step of the pipeline. A warning marks something '
             'known and explained in the detail (for example, inputs reused from an earlier run, or a documented '
             'difference from the author\'s files). A failure stops the release.</p>')
    rows = []
    for s in stages:
        r = reps.get(s['stage'])
        if not r:
            rows.append(dict(status='fail', step=s['stage'], what='', result='no report'))
            continue
        worst = next((c for c in r['checks'] if c['status'] == 'fail'), None) or \
            next((c for c in r['checks'] if c['status'] == 'warn' and 'committed' not in c['name']), None) or \
            next((c for c in r['checks'] if c['status'] == 'warn'), None)
        rows.append(dict(status=r['status'], step=r['title'] or r['stage'], what=r.get('explain', ''),
                         result=(f"{worst['name']}: {worst['detail']}" if worst else
                                 f"all {len(r['checks'])} checks passed")[:300]))
    H.append(tbl(rows, ['status', 'step', 'what', 'result']))

    # 2 method
    H.append('<h2 id="method">2. Method, read from the author\'s code</h2><p>These settings are parsed from '
             'the app files at the pinned commit (they are not typed in by us), so a change in a new version '
             'shows up here and in the coverage metadata.</p>')
    H.append(tbl(app.get('tables', {}).get('method')))
    H.append('<h3>Model output columns read by extract_AM.py</h3>' + tbl(app.get('tables', {}).get('pixel_columns')))
    ref = reps.get('reference', {})
    if ref.get('tables', {}).get('pixel_header'):
        H.append('<p class="small">Checked against the header DHSVM wrote in a reference run:</p>'
                 + tbl(ref['tables']['pixel_header']))
    if mc:
        H.append(f"<h3>What changed since the baseline version ({esc((mc['old']['commit'] or '')[:7])} → "
                 f"{esc((mc['new']['commit'] or '')[:7])})</h3>")
        H.append(tbl([dict(setting=r['setting'], old=r['old'], new=r['new'], changed='yes' if r['changed'] else '')
                      for r in mc['method']]))
        H.append(f"<p class='small'>DHSVM config keys added: {esc(mc['config_keys']['added'])}; removed: "
                 f"{esc(mc['config_keys']['removed'])}. DHSVM source: {len(mc['dhsvm_source']['added'])} files added, "
                 f"{len(mc['dhsvm_source']['removed'])} removed, {len(mc['dhsvm_source']['modified'])} modified.</p>")
        H.append(tbl([{k: f[k] for k in ('file', 'status')} | dict(lines=f"+{f.get('lines_added', 0)} / -{f.get('lines_removed', 0)}")
                      for f in mc['files']]))
        for f in mc['files']:
            if f.get('diff'):
                H.append(f"<details><summary>diff {esc(f['file'])}</summary>{diff_block(f['diff'], 400)}</details>")
    else:
        H.append('<p class="small">No baseline model version set: this is the first release of this model.</p>')

    # 3 fidelity
    fid = qa['fidelity']
    H.append('<h2 id="fidelity">3. Faithfulness to the author\'s code</h2>'
             '<p>Each run imports the app\'s own modules and runs them in a private copy of the app directory. '
             'The copy differs from the app only where a batch run needs it to. Every run saved the exact '
             f'difference. Across {fid["runs_with_diff"]} runs there are {len(fid["signatures"])} distinct patterns '
             '(differing only in seed, coordinates and dataset name), and '
             f'{fid["runs_with_unexpected_changes"]} runs with any other change.</p>')
    for s in fid['signatures']:
        H.append(f"<details open><summary>{s['count']} runs, e.g. {esc(s['run'])}</summary>{diff_block(s['diff'])}</details>")
    if fid['unexpected']:
        H.append('<h3>Runs with unexpected changes</h3>' + tbl(fid['unexpected']))
    H.append('<h3>DHSVM configuration written by the app</h3><p>The app fills its configuration template per run '
             '(vegetation, snow parameters, station file, dates). Keys it changed, over all runs:</p>')
    H.append(tbl(fid['config_keys'], ['key', 'runs', 'distinct_values', 'example']))
    if fid.get('config_example'):
        H.append(f"<details><summary>Full difference from the template for {esc(fid['config_example']['run'])}</summary>"
                 f"{diff_block(fid['config_example']['diff'], 300)}</details>")

    # 4 validation
    H.append('<h2 id="validation">4. Validation against the author\'s own files</h2>')
    frows = []
    for name, r in reps.items():
        if name.startswith('forcing_'):
            v = {c['name']: c for c in r['checks']}
            frows.append(dict(status=r['status'], dataset=name[8:], cells_compared=r['metrics'].get('shared_cells'),
                              detail='; '.join(f"{c['name']}: {c['detail']}" for c in r['checks']
                                               if c['status'] != 'pass' and 'committed' not in c['name'])[:400] or
                              'every variable equal to the printed precision'))
    H.append('<h3>Meteorological forcing</h3><p>Our station files compared line by line with the author\'s '
             'NG-IDL files for every cell both have.</p>' + tbl(frows))
    d = reps.get('defaults', {})
    H.append('<h3>Default land cover, LAI, height</h3>' + checks_tbl(d) if d else '')
    if d:
        H.append(tbl([dict(metric=k, value=v) for k, v in d.get('metrics', {}).items()]))
        H.append(tbl(d.get('tables', {}).get('cover_by_source')))
    if ref:
        H.append('<h3>Reference runs</h3><p>Five Interior places run on the author\'s own forcing and defaults. '
                 'When his app output for these points is available, our fitted values must equal his to 0.01 mm.</p>')
        H.append(checks_tbl(ref))
        H.append(tbl(ref.get('tables', {}).get('runs'), ['place_id', 'name', 'dataset', 'cover', 'status',
                                                          'p100_24h_P_mm', 'p100_24h_W_veg_mm', 'am_years_used', 'compare']))

    # 5 runs and fits
    runs = reps.get('runs', {})
    H.append('<h2 id="runs">5. Model runs and fits</h2>')
    if runs:
        H.append(checks_tbl(runs) + tbl(runs.get('tables', {}).get('status')))
        if runs.get('tables', {}).get('failures'):
            H.append('<h3>Runs where DHSVM stopped</h3><p>The app stops the same way for these inputs; the '
                     'entries are nodata in the coverage.</p>' + tbl(runs['tables']['failures']))
    f = qa['fits']
    H.append('<h3>Checks on every fitted curve</h3>' + tbl([
        dict(check='fitted curves (place x dataset x window x variable x duration)', value=f.get('fits')),
        dict(check='no missing values', value=f.get('all_finite')),
        dict(check='depth never decreases with return period', value=f.get('monotonic')),
        dict(check='confidence interval contains the fitted value', value=f.get('ci_brackets'))]))
    H.append('<p class="small">Annual maxima used per fit (the app drops the first):</p>' + tbl(f.get('am_counts')))

    # 6 results
    sci = qa['science']
    H.append('<h2 id="results">6. Results at a glance</h2>')
    H.append('<h3>100-year 24-hour depth, median over places</h3>' + tbl(sci['depth_100yr_24h']))
    H.append('<h3>NG / precipitation by land cover (100-year 24-hour, WRF historical)</h3>' + tbl(sci['ng_over_p_by_cover']))
    if sci.get('mechanism_24h'):
        H.append('<h3>What produced the 24-hour NG annual maxima</h3>' + tbl(sci['mechanism_24h']))
    H.append(f"<p>CESM future vs historical, 100-year 24-hour NG: median change "
             f"{sci['cesm_change_ng_100yr_24h_pct']['median']}% (10th-90th percentile over places "
             f"{sci['cesm_change_ng_100yr_24h_pct']['p10']}% to {sci['cesm_change_ng_100yr_24h_pct']['p90']}%).</p>")
    for name, cap in qa['figures'].items():
        H.append(img(Path(a.qa) / 'figures' / f'{name}.png', cap))

    # 7 version change
    H.append('<h2 id="change">7. Change from the baseline release</h2>')
    if cmp_:
        H.append(f"<p>{esc(cmp_['label_current'])} vs {esc(cmp_['label_baseline'])}: {cmp_['compared']} values compared; "
                 f"largest absolute difference {cmp_['max_abs_diff_mm']} mm"
                 f"{' (identical)' if cmp_['identical'] else ''}; {cmp_['new_values']} values new, "
                 f"{cmp_['lost_values']} values no longer present.</p>")
        H.append(tbl([r for r in cmp_['summary'] if r['duration'] == 24]))
        H.append('<h3>By land cover (24 h)</h3>' + tbl(cmp_['by_cover']))
        H.append('<h3>Largest changes, 100-year 24-hour NG</h3>' + tbl(cmp_['movers']))
        for name, cap in cmp_['figures'].items():
            H.append(img(Path(a.compare) / 'figures' / f'{name}.png', cap))
        if cmp_['lost_examples']:
            H.append('<details><summary>Examples of values no longer present</summary>' + tbl(cmp_['lost_examples']) + '</details>')
    else:
        H.append('<p class="small">No baseline release to compare with.</p>')

    # 8 provenance
    H.append('<h2 id="provenance">8. Provenance</h2>'
             '<p>Each stage has a <b>fingerprint</b>: a SHA-256 hash of everything the stage uses to make its '
             'outputs. That is the exact contents of its scripts, the contents of its input files (or the '
             'fingerprints of the earlier stages it reads from), its settings, and the fingerprint of its '
             'software environment. Any change, even one character of a script or a new model version, gives '
             'a new fingerprint. A stage\'s outputs live in a folder named after its fingerprint, so a stage runs '
             'again only when something it uses has changed, and earlier results are never overwritten. '
             'Because a stage\'s fingerprint includes those of the stages it reads from, a change re-runs '
             'exactly the stages downstream of it.</p>'
             '<p>Not included, because they cannot change the results: where the code was checked out, who ran it '
             'and when, and the checks themselves. One shortcut: the 86 TB WRF/CESM archive is identified by its '
             'path rather than by hashing its contents. It is SNAP\'s read-only archive, and its file counts '
             'and sizes are listed under "Source data" below. "Adopted" marks outputs made before the pipeline '
             'existed; they were checked again like any other.</p>'
             '<p>Each stage\'s full list of fingerprinted items is under "all checks and fingerprint inputs" at '
             'the end.</p>')
    H.append(tbl([dict(stage=r['stage'], status=r['status'], fingerprint=r['fingerprint'][:16], adopted=r['adopted'],
                       slurm_jobs=', '.join(r.get('job_ids') or []), finalized=r['finalized'], dir=r['dir'])
                  for r in reps.values()]))
    dh = reps.get('dhsvm', {}).get('tables', {}).get('build')
    if dh:
        H.append('<h3>DHSVM build</h3>' + tbl(dh))
    inp = reps.get('inputs', {}).get('tables', {})
    if inp:
        H.append('<h3>Source data</h3>' + tbl(inp.get('checksums'), ['dir', 'files', 'ok', 'failed', 'bytes'])
                 + tbl(inp.get('raw_forcing'), ['dataset', 'files', 'bytes', 'first', 'last', 'dir']))
    for r in reps.values():
        H.append(f"<details><summary>{esc(r['stage'])}: all checks and fingerprint inputs</summary>{checks_tbl(r)}"
                 f"<pre>{esc(json.dumps(r['components'], indent=1, default=str))}</pre></details>")
    H.append('</main></body></html>')
    Path(a.out).write_text('\n'.join(H))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--stages', required=True, help='JSON list of {stage, dir}')
    ap.add_argument('--qa', required=True)
    ap.add_argument('--compare')
    ap.add_argument('--model-change')
    ap.add_argument('--title', default='NG-IDF run report')
    ap.add_argument('--out', required=True)
    build(ap.parse_args())


if __name__ == '__main__':
    main()
