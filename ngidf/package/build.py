"""The NG-IDF QC package: one PDF that documents a pipeline run for readers outside SNAP.

Built at the end of every flow run (`pipeline.py package`), from what is on disk at that moment:
the stage reports, the QA stage's figures and tables, the model version, and the flow run's own
parameters. Nothing in it is typed in by hand except the prose in content/, which is versioned with
the code it describes.

    1. Overview          what the pipeline makes and how (flowchart; no results)
    2. This run          model version, code versions, flow run and its parameters, what ran
    3. Results           each step's checks, results at a glance, change from the previous release
    4. Known issues      content/known_issues.md, each tied to the check that detects it
    A. Inputs            content/appendix_inputs.md, plus tables read from the code
    B. Method            settings read from the author's code; what each run changes in it
    C. Provenance        fingerprints, environments, source data, the DHSVM build
    D. Every check       every check of every stage

    python -I ngidf/package/build.py --input package_input.json --out-dir DIR

package_input.json (written by pipeline.py package): {info, plan, stages: [{stage, dir}], qa_out,
compare_dir, flow_run, created}. Writes <out-dir>/<name>.pdf and the same document as .html.
"""
import argparse
import base64
import datetime as dt
import html
import json
from pathlib import Path
import re
import sys

import markdown

HERE = Path(__file__).resolve().parent
CONTENT = HERE / 'content'

GOOD, WARN, BAD, GREY = '#0ca30c', '#fab219', '#d03b3b', '#7a7974'
STATUS = {'pass': ('✓', 'Pass', GOOD), 'warn': ('!', 'Pass with warnings', WARN), 'fail': ('✕', 'Fail', BAD),
          'todo': ('–', 'Not run', GREY), 'waiting': ('–', 'Not run', GREY), 'prepared': ('…', 'Unfinished', GREY)}
CHECK_STATUS = {'pass': ('✓', 'Pass', GOOD), 'warn': ('!', 'Warning', WARN), 'fail': ('✕', 'Fail', BAD)}
ROUTINE = ('outputs produced by this pipeline (not adopted)', 'curation code committed')

# The pipeline in six steps. The flowchart, the step list of section 1 and the results of section 3
# are all drawn from this, so they cannot disagree. `inputs` link to sections of Appendix A.
STEPS = [
    dict(id='places', title='Describe each place',
         what='Each community gets a model location and a description of its ground cover: the kind of '
              'vegetation, how much leaf area it has, and how tall it is. These control how much rain and snow '
              'the canopy intercepts and how the snowpack melts.',
         inputs=[('Alaska community list', 'in-places'), ('Land cover map (NLCD)', 'in-landcover'),
                 ('Leaf area (GLASS LAI)', 'in-lai'), ('Canopy height (LANDFIRE)', 'in-height')],
         output='Place table', stages=['places', 'defaults']),
    dict(id='weather', title="Build each place's weather",
         what='For every place and every climate dataset, an hourly (Daymet: 3-hourly) series of temperature, '
              'wind, humidity, radiation and precipitation, in the format the model reads. Where the author made '
              'the same files, ours are compared with his line by line.',
         inputs=[('WRF climate simulations (4 km)', 'in-wrf'), ('CESM large-ensemble members', 'in-wrf'),
                 ('Daymet observations (1 km)', 'in-daymet')],
         output='Weather series', stages=None),   # every forcing_* stage
    dict(id='model', title='Prepare and check the model',
         what="Download the author's NG-IDF app at the exact version named in this run, read its method "
              'settings from the code, compile the DHSVM model, and rerun a few places on the author\'s own '
              'inputs to confirm that our setup reproduces his.',
         inputs=[("Author's NG-IDF app (DHSVM + scripts)", 'in-app')],
         output='Checked model', stages=['app', 'dhsvm', 'reference']),
    dict(id='runs', title='Run the model',
         what='One model run per place and dataset. DHSVM simulates the snowpack and the water that reaches '
              'the ground (rain plus snowmelt) hour by hour; the largest amount in each year is taken for each '
              'duration (1 hour to 3 days); a curve is fitted to those yearly maxima to estimate the 2- to '
              '100-year events, with a confidence interval.',
         inputs=[], output='Curves for every place', stages=['runs']),
    dict(id='coverage', title='Package the results',
         what='All curves go into one netCDF file per product, in the layout the SNAP data API (Rasdaman) '
              'serves, with the method described in the file metadata.',
         inputs=[], output='Data files for the API', stages=['coverage']),
    dict(id='qa', title='Check and report',
         what="Every run is checked against the author's code, every fitted curve is checked, the results "
              'are summarised in maps and curves, compared with the previous release, and documented here.',
         inputs=[], output='This document', stages=['qa']),
]
BEHIND = ['env_ngidf', 'env_msim', 'env_geo', 'env_report', 'inputs']

CSS = """
@font-face { font-family: Body; src: url("{fonts}/Ubuntu-R.ttf"); }
@font-face { font-family: Body; font-weight: bold; src: url("{fonts}/Ubuntu-B.ttf"); }
@font-face { font-family: Body; font-style: italic; src: url("{fonts}/Ubuntu-RI.ttf"); }
@font-face { font-family: Body; font-weight: 500; src: url("{fonts}/Ubuntu-M.ttf"); }
@font-face { font-family: Mono; src: url("{fonts}/SourceCodePro-Regular.ttf"); }
@page { size: Letter; margin: 2cm 1.9cm 2.2cm;
  @top-left { content: string(doctitle); font: 8pt Body; color: #7a7974; }
  @top-right { content: string(section); font: 8pt Body; color: #7a7974; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 8pt Body; color: #7a7974; } }
@page :first { @top-left { content: none; } @top-right { content: none; } }
html { font: 10pt/1.45 Body; color: #1d1d1b; }
.doctitle { string-set: doctitle content(); }
h1 { font-size: 19pt; font-weight: 500; margin: 0 0 8pt; break-before: page; string-set: section content(); color: #0d366b; }
h1.nobreak { break-before: auto; }
h2 { font-size: 13pt; font-weight: 500; margin: 18pt 0 5pt; color: #0d366b; break-after: avoid; }
h3 { font-size: 10.5pt; font-weight: bold; margin: 12pt 0 4pt; break-after: avoid; }
p, li { margin: 0 0 6pt; } ul, ol { margin: 0 0 6pt; padding-left: 16pt; }
a { color: #2a78d6; text-decoration: none; }
code, pre { font-family: Mono; font-size: 8pt; }
pre { background: #f4f3f0; padding: 6pt 8pt; white-space: pre-wrap; word-break: break-all; border-radius: 3pt; }
pre .add { color: #0a6b0a; } pre .del { color: #a42525; } pre .hunk { color: #7a7974; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 10pt; font-size: 8.5pt; }
th, td { text-align: left; padding: 3pt 5pt; border-bottom: 0.5pt solid #d9d8d3; vertical-align: top; }
th { color: #52514e; font-weight: 500; background: #f4f3f0; }
td.num { text-align: right; } tr { break-inside: avoid; }
table.checks { table-layout: fixed; } table.checks th:nth-child(1) { width: 17%; }
table.checks th:nth-child(2) { width: 33%; } table.checks th:nth-child(3) { width: 50%; }
.kv td:first-child { color: #52514e; width: 32%; }
.badge { font-weight: 500; white-space: nowrap; }
.dot { display: inline-block; width: 11pt; height: 11pt; line-height: 11pt; border-radius: 6pt; color: #fff;
  text-align: center; font-size: 7.5pt; font-weight: bold; margin-right: 3pt; }
.small { font-size: 8.5pt; color: #52514e; }
.lead { font-size: 11pt; }
.box { border-left: 3pt solid #2a78d6; background: #f2f7fd; padding: 6pt 10pt; margin: 8pt 0 10pt; }
.issue { border-left: 3pt solid #fab219; background: #fffaf0; padding: 6pt 10pt; margin: 8pt 0 10pt; break-inside: avoid; }
.issue.resolved { border-left-color: #0ca30c; background: #f3faf3; }
figure { margin: 6pt 0 10pt; break-inside: avoid; text-align: center; } figure img { width: 88%; }
figcaption { font-size: 8.5pt; color: #52514e; margin-top: 3pt; text-align: left; }
.cover { height: 23cm; display: flex; flex-direction: column; }
.cover .t { font-size: 26pt; font-weight: 500; color: #0d366b; margin-top: 3cm; line-height: 1.15; }
.cover .s { font-size: 13pt; color: #52514e; margin: 8pt 0 24pt; }
.toc { list-style: none; padding: 0; margin: 0; }
.toc li { margin: 2pt 0; } .toc li.l2 { padding-left: 14pt; font-size: 9pt; }
.toc a { color: #1d1d1b; } .toc a::after { content: leader('.') target-counter(attr(href), page); color: #7a7974; }
.stepnum { display: inline-block; width: 15pt; height: 15pt; line-height: 15pt; border-radius: 8pt; background: #2a78d6;
  color: #fff; text-align: center; font-size: 9pt; margin-right: 5pt; }
"""


# ----------------------------------------------------------------------------------------- helpers
def esc(x):
    return html.escape('' if x is None else str(x))


def badge(status, table=STATUS):
    i, label, col = table.get(status, ('?', status, GREY))
    return f'<span class="badge"><span class="dot" style="background:{col}">{i}</span>{label}</span>'


def size(n):
    for unit in ('bytes', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if abs(n) < 1024 or unit == 'PB':
            return f'{n:.0f} {unit}' if unit == 'bytes' else f'{n:.1f} {unit}'
        n /= 1024


def fmt(v):
    if isinstance(v, bool):
        return 'yes' if v else 'no'
    if isinstance(v, float):
        return f'{v:.4g}'
    if isinstance(v, (list, dict)):
        return esc(json.dumps(v, default=str))
    return esc(v)


def tbl(rows, cols=None, labels=None, status_col='status', table=CHECK_STATUS, cls=''):
    rows = list(rows or [])
    if not rows:
        return '<p class="small">(none)</p>'
    cols = cols or list(rows[0].keys())
    labels = labels or {}
    head = ''.join(f'<th>{esc(labels.get(c, c.replace("_", " ")))}</th>' for c in cols)
    body = []
    for r in rows:
        tds = []
        for c in cols:
            v = r.get(c)
            if c == status_col:
                tds.append(f'<td>{badge(v, table)}</td>')
            elif c == 'bytes' and isinstance(v, (int, float)):
                tds.append(f'<td class="num">{size(v)}</td>')
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                tds.append(f'<td class="num">{fmt(v)}</td>')
            else:
                tds.append(f'<td>{fmt(v)}</td>')
        body.append('<tr>' + ''.join(tds) + '</tr>')
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def kv(pairs):
    return '<table class="kv">' + ''.join(f'<tr><td>{esc(k)}</td><td>{v}</td></tr>' for k, v in pairs) + '</table>'


def checks_tbl(rep):
    return tbl([dict(status=c['status'], check=c['name'], detail=c['detail']) for c in rep.get('checks', [])], cls='checks')


def img(path, caption):
    p = Path(path)
    if not p.exists():
        return ''
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f'<figure><img src="data:image/png;base64,{b64}"><figcaption>{esc(caption)}</figcaption></figure>'


def diff_block(text, limit=120):
    out = []
    for line in (text or '').splitlines()[:limit]:
        cls = 'hunk' if line.startswith('@@') else 'add' if line.startswith('+') else 'del' if line.startswith('-') else ''
        out.append(f'<span class="{cls}">{esc(line)}</span>' if cls else esc(line))
    return '<pre>' + '\n'.join(out) + '</pre>'


def md(text, facts=None):
    """Markdown from content/, with HTML comments (editing notes) removed and {{name}} placeholders
    filled from the run (see facts())."""
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    for k, v in (facts or {}).items():
        text = text.replace('{{' + k + '}}', str(v))
    return markdown.markdown(text, extensions=['tables', 'attr_list'])


def return_periods(expr):
    """Return periods from the app's probability expression, e.g. 'c(seq(0.50, 0.99, by = 0.01), 0.998)'
    -> '2 to 100, and 500'."""
    ps = []
    for a, b, step in re.findall(r'seq\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*by\s*=\s*([\d.]+)\s*\)', expr):
        n = round((float(b) - float(a)) / float(step))
        ps += [float(a) + i * float(step) for i in range(n + 1)]
    rest = re.sub(r'seq\([^)]*\)', '', expr)
    ps += [float(x) for x in re.findall(r'(?<![\w.])(0?\.\d+)', rest)]
    ts = sorted({round(1 / (1 - p)) for p in ps if 0 < p < 1})
    if not ts:
        return '(not read)'
    run, groups = [ts[0]], []
    for t in ts[1:]:
        if t - run[-1] <= 1 or (t <= 100 and run[-1] < 100 and len(run) > 3):
            run.append(t)
        else:
            groups.append(run)
            run = [t]
    groups.append(run)
    parts = [f'{g[0]} to {g[-1]}' if len(g) > 2 else ', '.join(map(str, g)) for g in groups]
    return parts[0] if len(parts) == 1 else ', '.join(parts[:-1]) + ', and ' + parts[-1]


def facts(reps, inp):
    """Values the prose quotes, read from this run."""
    out = {}
    method = {r['setting']: r['value'] for r in reps.get('app', {}).get('tables', {}).get('method', [])}
    out['return_periods'] = return_periods(str(method.get('probabilities', '')))
    durs = None
    ref = next((s['dir'] for s in inp['stages'] if s['stage'] == 'reference'), None)
    if ref:
        rj = next(Path(ref, 'out', 'runs').glob('*/*/run.json'), None)
        if rj:
            durs = json.loads(rj.read_text()).get('durations')
    if durs:
        def words(d):
            h = int(d.rstrip('h'))
            return f'{h} hour' + ('s' if h > 1 else '') if h < 24 or h % 24 else f'{h // 24} day' + ('s' if h > 24 else '')
        out['durations'] = ', '.join(words(d) for d in durs)
    else:
        out['durations'] = '(not read)'
    return out


def worst(statuses):
    order = {'fail': 3, 'todo': 2, 'waiting': 2, 'prepared': 2, 'warn': 1, 'pass': 0}
    return max(statuses, key=lambda s: order.get(s, 2), default='todo')


def step_stages(step, reps, plan):
    if step['stages'] is None:
        return [s['stage'] for s in plan if s['stage'].startswith('forcing_')]
    return step['stages']


# --------------------------------------------------------------------------------------- flowchart
def wrap(text, n):
    words, lines, cur = text.split(), [], ''
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f'{cur} {w}'.strip()
    return lines + [cur] if cur else lines


def flowchart():
    """SVG: inputs (left) feed the six steps (centre), each step's product on the right."""
    W, XI, WI, XS, WS, XO, WO = 760, 0, 205, 262, 250, 562, 198
    IH, GAP, PAD = 24, 6, 12
    rows, y = [], 40
    for st in STEPS:
        h = max(56, len(st['inputs']) * (IH + GAP) - GAP)
        rows.append((st, y, h))
        y += h + 30
    H = y - 10
    S = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" font-family="Body">',
         '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
         '<path d="M0,0 L10,5 L0,10 z" fill="#7a7974"/></marker></defs>']
    for x, w, t in ((XI, WI, 'INPUTS'), (XS, WS, 'STEPS'), (XO, WO, 'PRODUCTS')):
        S.append(f'<text x="{x + w / 2}" y="18" text-anchor="middle" font-size="11" fill="#7a7974" '
                 f'letter-spacing="1.5">{t}</text>')
    for i, (st, y0, h) in enumerate(rows):
        cy = y0 + h / 2
        # inputs
        n = len(st['inputs'])
        top = cy - (n * (IH + GAP) - GAP) / 2
        for j, (name, anchor) in enumerate(st['inputs']):
            iy = top + j * (IH + GAP)
            S.append(f'<a href="#{anchor}"><rect x="{XI}" y="{iy}" width="{WI}" height="{IH}" rx="4" fill="#f4f3f0" '
                     f'stroke="#b5b3ad"/><text x="{XI + 8}" y="{iy + 16}" font-size="10.5" fill="#1d1d1b">{esc(name)}</text></a>')
            S.append(f'<path d="M{XI + WI},{iy + IH / 2} C{XI + WI + 30},{iy + IH / 2} {XS - 30},{cy} {XS - 2},{cy}" '
                     f'fill="none" stroke="#9c9a94" stroke-width="1.2" marker-end="url(#ah)"/>')
        # step
        S.append(f'<a href="#res-{st["id"]}"><rect x="{XS}" y="{y0}" width="{WS}" height="{h}" rx="7" fill="#cde2fb" stroke="#2a78d6" stroke-width="1.5"/>')
        S.append(f'<circle cx="{XS + 18}" cy="{cy}" r="10" fill="#2a78d6"/><text x="{XS + 18}" y="{cy + 4}" '
                 f'text-anchor="middle" font-size="11" fill="#fff" font-weight="bold">{i + 1}</text>')
        lines = wrap(st['title'], 26)
        for k, line in enumerate(lines):
            S.append(f'<text x="{XS + 36}" y="{cy + 5 + (k - (len(lines) - 1) / 2) * 15}" font-size="12.5" '
                     f'font-weight="500" fill="#0d366b">{esc(line)}</text>')
        S.append('</a>')
        # product
        S.append(f'<path d="M{XS + WS},{cy} L{XO - 2},{cy}" stroke="#9c9a94" stroke-width="1.2" marker-end="url(#ah)"/>')
        S.append(f'<rect x="{XO}" y="{cy - 14}" width="{WO}" height="28" rx="14" fill="#d9f2e8" stroke="#1baf7a"/>'
                 f'<text x="{XO + WO / 2}" y="{cy + 4}" text-anchor="middle" font-size="10.5" fill="#0b5a3d">{esc(st["output"])}</text>')
        # down arrow to the next step
        if i < len(rows) - 1:
            S.append(f'<path d="M{XS + WS / 2},{y0 + h} L{XS + WS / 2},{rows[i + 1][1] - 2}" stroke="#2a78d6" '
                     f'stroke-width="1.5" marker-end="url(#ah)"/>')
    S.append('</svg>')
    return '\n'.join(S)


# ------------------------------------------------------------------------------------------ sections
def known_issues(reps):
    """content/known_issues.md: '## Title' sections; a line 'Check: <stage> / <check name>' ties an issue
    to a check, whose result in this run is shown with it."""
    text = (CONTENT / 'known_issues.md').read_text()
    intro, *parts = re.split(r'^## ', text, flags=re.M)
    out = [md(intro)]
    for part in parts:
        title, _, body = part.partition('\n')
        m = re.search(r'^Check:\s*(\S+)\s*/\s*(.+?)\s*$', body, flags=re.M)
        body = re.sub(r'^Check:.*$', '', body, flags=re.M)
        status_html, resolved = '', False
        if m:
            stage, name = m.group(1), m.group(2)
            c = next((c for c in reps.get(stage, {}).get('checks', []) if c['name'] == name), None)
            if c is None:
                status_html = f'<p class="small">In this run: check "{esc(name)}" ({esc(stage)}) was not run.</p>'
            else:
                resolved = c['status'] == 'pass'
                status_html = (f'<p class="small">In this run ({esc(stage)}): {badge(c["status"])} '
                               f'{esc(c["detail"])}</p>')
        out.append(f'<div class="issue{" resolved" if resolved else ""}"><h3>{esc(title.strip())}'
                   f'{" (resolved in this run)" if resolved else ""}</h3>{md(body)}{status_html}</div>')
    return '\n'.join(out)


def build(inp, out_dir):
    info, plan, flow_run = inp['info'], inp['plan'], inp.get('flow_run') or {}
    reps = {}
    for s in inp['stages']:
        f = Path(s['dir']) / 'report.json'
        if f.exists():
            reps[s['stage']] = json.loads(f.read_text())
    status = {s['stage']: s['status'] for s in plan}
    qa_out = Path(inp['qa_out']) if inp.get('qa_out') else None
    qa = json.loads((qa_out / 'qa.json').read_text()) if qa_out and (qa_out / 'qa.json').exists() else None
    cmp_dir = Path(inp['compare_dir']) if inp.get('compare_dir') else None
    cmp_ = json.loads((cmp_dir / 'compare.json').read_text()) if cmp_dir and (cmp_dir / 'compare.json').exists() else None
    m = info['model']
    created = inp.get('created') or dt.datetime.now().astimezone().isoformat(timespec='minutes')
    title = f"NG-IDF quality-control package: model {m['MODEL_LABEL']}"
    fonts = Path(sys.prefix) / 'fonts'

    H = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{esc(title)}</title>'
         f'<style>{CSS.replace("{fonts}", fonts.as_uri())}</style></head><body>']

    # cover + contents
    run_label = f"flow run {flow_run['name']}" if flow_run.get('name') else 'built by hand'
    H.append('<section class="cover">'
             f'<div class="t doctitle">NG-IDF quality-control package</div>'
             f'<div class="s">Model version {esc(m["MODEL_LABEL"])} · {esc(run_label)} · {esc(created[:16].replace("T", " "))}</div>'
             '<p class="lead">This document describes how SNAP produced next-generation intensity-duration-frequency '
             '(NG-IDF) curves for Alaska communities with the NG-IDF app by H. Yan (Pacific Northwest National '
             'Laboratory), and what was checked. It is generated by the processing pipeline itself at the end of '
             'each run, from the results of that run.</p>'
             '<h2>Contents</h2><ul class="toc">'
             '<li><a href="#overview">1. Overview</a></li><li><a href="#run">2. This run</a></li>'
             '<li><a href="#results">3. Results</a></li>'
             + ''.join(f'<li class="l2"><a href="#res-{st["id"]}">3.{i + 1} {esc(st["title"])}</a></li>' for i, st in enumerate(STEPS))
             + '<li class="l2"><a href="#glance">3.7 Results at a glance</a></li>'
             '<li class="l2"><a href="#change">3.8 Change from the previous release</a></li>'
             '<li><a href="#issues">4. Known issues</a></li><li><a href="#app-inputs">Appendix A. Inputs and how they were prepared</a></li>'
             '<li><a href="#app-method">Appendix B. Method read from the author\'s code</a></li>'
             '<li><a href="#app-prov">Appendix C. Provenance</a></li><li><a href="#app-checks">Appendix D. Every check</a></li>'
             '</ul></section>')

    # 1 overview
    H.append('<h1 id="overview">1. Overview</h1>' + md((CONTENT / 'overview.md').read_text(), facts(reps, inp)))
    H.append('<h2>The pipeline</h2><p>Inputs on the left are described in <a href="#app-inputs">Appendix A</a>; '
             'each step links to its results in section 3.</p>' + flowchart())
    for i, st in enumerate(STEPS):
        ins = ', '.join(f'<a href="#{a}">{esc(n)}</a>' for n, a in st['inputs'])
        H.append(f'<h3><span class="stepnum">{i + 1}</span>{esc(st["title"])}</h3><p>{esc(st["what"])}'
                 + (f' <span class="small">Inputs: {ins}.</span>' if ins else '') + '</p>')
    H.append('<p class="small">Behind the scenes: the software environments are rebuilt from exact package lists, and '
             'the source data are verified against their checksums before use (<a href="#app-prov">Appendix C</a>).</p>')

    # 2 this run
    remote = (info.get('curation_remote') or '').removesuffix('.git')
    commit = info.get('curation_commit') or ''
    H.append('<h1 id="run">2. This run</h1>')
    H.append('<h2>Model version</h2>' + kv([
        ('Label', esc(m['MODEL_LABEL'])), ('Description', esc(m.get('MODEL_DESCRIPTION'))),
        ("Author's repository", f"{esc(m.get('UPSTREAM_REPO'))}, branch {esc(m.get('UPSTREAM_BRANCH'))}"),
        ('Commit', f"<code>{esc(m.get('APP_COMMIT'))}</code>"),
        ('Copy used by the pipeline', f"{esc(m.get('APP_REPO'))}, tag <code>{esc(m.get('APP_REF'))}</code>"),
        ('Previous release compared with', esc(
            f"the release made with model version {m['BASELINE_MODEL']}" if m.get('BASELINE_MODEL') else
            (f"the coverage files in {m['BASELINE_COVERAGE_DIR']} (under the data directory below)"
             if m.get('BASELINE_COVERAGE_DIR') else 'none')))]))
    H.append('<h2>Processing code</h2>' + kv([
        ('Repository', esc(remote)), ('Branch', esc(info.get('curation_branch'))),
        ('Commit', f'<a href="{esc(remote)}/commit/{esc(commit)}"><code>{esc(commit)}</code></a>'),
        ('Uncommitted changes', 'yes' if info.get('curation_dirty') else 'none'),
        ('Data directory', f"<code>{esc(info.get('data_root'))}</code>")]))
    H.append('<h2>Flow run</h2>')
    if flow_run:
        pairs = [('Name', esc(flow_run.get('name'))), ('ID', f"<code>{esc(flow_run.get('id'))}</code>"),
                 ('Started', esc(flow_run.get('started'))), ('Run as', esc(flow_run.get('user')))]
        if flow_run.get('ui_url'):
            pairs.append(('In Prefect', f'<a href="{esc(flow_run["ui_url"])}">{esc(flow_run["ui_url"])}</a>'))
        H.append(kv(pairs))
        H.append('<h3>Parameters</h3>' + tbl([dict(parameter=k, value=v) for k, v in (flow_run.get('parameters') or {}).items()]))
    else:
        H.append('<p>Built by hand with <code>pipeline.py package</code>, not by a flow run.</p>')
    ran = set(flow_run.get('ran_now') or [])
    rows = []
    for i, st in enumerate(STEPS):
        names = step_stages(st, reps, plan)
        rows.append(dict(step=f'{i + 1}. {st["title"]}', status=worst([status.get(n, 'todo') for n in names]),
                         stages=len(names), ran_in_this_flow_run=sum(n in ran for n in names) if flow_run else '–',
                         last_finished=max((reps[n]['finalized'][:16].replace('T', ' ') for n in names if n in reps), default='')))
    H.append('<h2>What ran</h2><p>A step runs only when something it uses has changed since it last passed '
             '(code, inputs, settings or model version); otherwise its earlier result, still on disk, is used. '
             'How this is decided is described under <a href="#fingerprint">fingerprints</a> in Appendix C.</p>'
             + tbl(rows, table=STATUS))

    # 3 results
    H.append('<h1 id="results">3. Results</h1><p>Each step ends with checks. '
             f'{badge("pass", CHECK_STATUS)} means the check passed. {badge("warn", CHECK_STATUS)} means the outputs '
             'can be used but something should be known; each warning explains itself, and the ones that need '
             f'more work are in <a href="#issues">section 4</a>. {badge("fail", CHECK_STATUS)} stops the steps after it.</p>')
    for i, st in enumerate(STEPS):
        names = step_stages(st, reps, plan)
        H.append(f'<h2 id="res-{st["id"]}">3.{i + 1} {esc(st["title"])} {badge(worst([status.get(n, "todo") for n in names]), STATUS)}</h2>')
        H.append(results_for_step(st, names, reps, qa))
    H.append('<h2 id="glance">3.7 Results at a glance</h2>' + glance(qa, qa_out))
    H.append('<h2 id="change">3.8 Change from the previous release</h2>' + change(cmp_, cmp_dir))

    # 4 known issues
    H.append('<h1 id="issues">4. Known issues</h1>' + known_issues(reps))

    # appendices
    H.append('<h1 id="app-inputs">Appendix A. Inputs and how they were prepared</h1>'
             + md((CONTENT / 'appendix_inputs.md').read_text()))
    H.append('<h1 id="app-method">Appendix B. Method read from the author\'s code</h1>' + method(reps, qa))
    H.append('<h1 id="app-prov">Appendix C. Provenance</h1>' + provenance(reps, plan))
    H.append('<h1 id="app-checks">Appendix D. Every check</h1><p>Every check of every stage in this run, grouped by step.</p>')
    for i, st in enumerate(STEPS):
        for n in step_stages(st, reps, plan):
            if n in reps:
                H.append(f'<h3>{i + 1}. {esc(reps[n]["title"])} <span class="small">({esc(n)})</span></h3>' + checks_tbl(reps[n]))
    for n in BEHIND:
        if n in reps:
            H.append(f'<h3>Behind the scenes: {esc(reps[n]["title"])} <span class="small">({esc(n)})</span></h3>' + checks_tbl(reps[n]))
    H.append('</body></html>')

    doc = '\n'.join(H)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"ngidf_qc_{m['MODEL_LABEL']}_{created[:16].replace(':', '').replace('-', '').replace('T', '_')}"
    (out_dir / f'{name}.html').write_text(doc)
    import weasyprint
    weasyprint.HTML(string=doc, base_url=str(out_dir)).write_pdf(out_dir / f'{name}.pdf')
    return out_dir / f'{name}.pdf'


def plain_checks(rep):
    """Checks with the bookkeeping ones last."""
    cs = rep.get('checks', [])
    return [c for c in cs if c['name'] not in ROUTINE] + [c for c in cs if c['name'] in ROUTINE]


def results_for_step(st, names, reps, qa):
    H = [f'<p>{esc(st["what"])}</p>']
    if st['id'] == 'weather':
        rows = []
        for n in names:
            r = reps.get(n)
            if not r:
                rows.append(dict(status='todo', dataset=n[8:]))
                continue
            notes = [f"{c['name']}: {c['detail']}" for c in plain_checks(r) if c['status'] != 'pass' and c['name'] not in ROUTINE]
            text = '; '.join(notes) or "every variable equal to the author's files at their printed precision"
            if r.get('adopted'):
                text += ' (series made on an earlier run and checked again here)'
            rows.append(dict(status=r['status'], dataset=n[8:], cells_compared_with_author=r['metrics'].get('shared_cells'),
                             notes=text))
        H.append('<p>One row per climate dataset. "Cells compared" counts the weather series that the author '
                 'also made, which are compared value by value.</p>' + tbl(rows, table=STATUS))
        return '\n'.join(H)
    for n in names:
        r = reps.get(n)
        if not r:
            H.append(f'<h3>{esc(n)}</h3><p class="small">Not run.</p>')
            continue
        H.append(f'<h3>{esc(r["title"])}</h3><p class="small">{esc(r.get("explain"))}</p>'
                 + tbl([dict(status=c['status'], check=c['name'], detail=c['detail']) for c in plain_checks(r)], cls='checks'))
        if n == 'runs' and r.get('tables', {}).get('status'):
            H.append('<p class="small">Runs by dataset:</p>' + tbl(r['tables']['status']))
    if st['id'] == 'runs' and qa:
        f = qa['fits']
        fid = qa['fidelity']
        H.append('<h3>Checks on every fitted curve</h3>' + tbl([
            dict(check='fitted curves (place × dataset × variable × duration)', value=f.get('fits')),
            dict(check='with no missing values', value=f.get('all_finite')),
            dict(check='whose depth never decreases with return period', value=f.get('monotonic')),
            dict(check='whose confidence interval contains the fitted value', value=f.get('ci_brackets'))]))
        H.append(f'<h3>Faithfulness to the author\'s code</h3><p>Each run works in its own copy of the author\'s app and '
                 f'records how that copy differs from the original. Over {fid["runs_with_diff"]} runs there are '
                 f'{len(fid["signatures"])} patterns of difference (they differ only in random seed, coordinates and '
                 f'dataset name) and {fid["runs_with_unexpected_changes"]} runs with any other change. The patterns are '
                 'shown in <a href="#app-method">Appendix B</a>.</p>')
    return '\n'.join(H)


def glance(qa, qa_out):
    if not qa:
        return '<p class="small">The quality-check step has not run, so there are no summary results.</p>'
    sci = qa['science']
    H = ['<p>NG is the water reaching the ground (rain plus snowmelt, "W_veg" in the app); P is precipitation. '
         'Depths in mm.</p>',
         '<h3>100-year 24-hour depth, median over places</h3>' + tbl(sci['depth_100yr_24h']),
         '<h3>NG / precipitation by land cover (100-year 24-hour, WRF historical)</h3>' + tbl(sci['ng_over_p_by_cover'])]
    if sci.get('mechanism_24h'):
        H.append('<h3>What produced the 24-hour NG annual maxima</h3>' + tbl(sci['mechanism_24h']))
    c = sci['cesm_change_ng_100yr_24h_pct']
    H.append(f'<p>CESM future vs historical, 100-year 24-hour NG: median change {c["median"]}% '
             f'(10th–90th percentile over places {c["p10"]}% to {c["p90"]}%).</p>')
    for name, cap in qa['figures'].items():
        H.append(img(qa_out / 'figures' / f'{name}.png', cap))
    return '\n'.join(H)


def change(cmp_, cmp_dir):
    if not cmp_:
        return '<p class="small">No previous release to compare with.</p>'
    H = [f"<p>{esc(cmp_['label_current'])} compared with {esc(cmp_['label_baseline'])}: {cmp_['compared']} values; "
         f"largest absolute difference {cmp_['max_abs_diff_mm']} mm{' (identical)' if cmp_['identical'] else ''}; "
         f"{cmp_['new_values']} values new, {cmp_['lost_values']} no longer present.</p>"]
    if not cmp_['identical']:
        H.append('<h3>100-year change by dataset, 24 hours</h3>' + tbl([r for r in cmp_['summary'] if r['duration'] == 24]))
        H.append('<h3>By land cover</h3>' + tbl(cmp_['by_cover']))
        H.append('<h3>Largest changes</h3>' + tbl(cmp_['movers']))
        for name, cap in cmp_['figures'].items():
            H.append(img(cmp_dir / 'figures' / f'{name}.png', cap))
    return '\n'.join(H)


def method(reps, qa):
    app = reps.get('app', {})
    H = ['<p>These settings are parsed from the author\'s code at the pinned commit, not typed in, so a change in a '
         'new model version shows up here.</p>', tbl(app.get('tables', {}).get('method')),
         '<h2>Model output columns read by extract_AM.py</h2>', tbl(app.get('tables', {}).get('pixel_columns'))]
    ref = reps.get('reference', {})
    if ref.get('tables', {}).get('pixel_header'):
        H.append('<p class="small">Checked against the header DHSVM wrote in a reference run:</p>' + tbl(ref['tables']['pixel_header']))
    if qa:
        fid = qa['fidelity']
        H.append('<h2>What each run changes in its copy of the app</h2><p>Every pattern of difference between a '
                 "run's copy of the app and the author's original, with the number of runs that have it.</p>")
        for s in fid['signatures']:
            H.append(f"<h3>{s['count']} runs, for example {esc(s['run'])}</h3>{diff_block(s['diff'])}")
        H.append('<h2>DHSVM settings the app writes for each run</h2>' + tbl(fid['config_keys'], ['key', 'runs', 'distinct_values', 'example']))
    return '\n'.join(H)


def provenance(reps, plan):
    H = [f'<h2 id="fingerprint">Fingerprints</h2>{md((CONTENT / "fingerprints.md").read_text())}',
         tbl([dict(stage=s['stage'], status=s['status'], fingerprint=(s.get('fingerprint') or '')[:16],
                   adopted=reps.get(s['stage'], {}).get('adopted'), finished=reps.get(s['stage'], {}).get('finalized', '')[:16].replace('T', ' '),
                   slurm_jobs=', '.join(reps.get(s['stage'], {}).get('job_ids') or []))
              for s in plan], table=STATUS)]
    dh = reps.get('dhsvm', {}).get('tables', {}).get('build')
    if dh:
        H.append('<h2>DHSVM build</h2>' + ''.join(kv([(k, f'<code>{fmt(v)}</code>') for k, v in row.items()]) for row in dh))
    inp = reps.get('inputs', {}).get('tables', {})
    if inp:
        H.append('<h2>Source data</h2><p>Files verified against their checksums:</p>'
                 + tbl(inp.get('checksums'), ['dir', 'files', 'ok', 'failed', 'bytes'])
                 + '<p>Climate simulation archive (read-only; identified by path, counted here):</p>'
                 + tbl(inp.get('raw_forcing'), ['dataset', 'files', 'bytes', 'first', 'last']))
    H.append('<h2>Software environments</h2><p>Each environment is built from an exact package list stored with the code; '
             'the check "packages match the lock file" confirms it.</p>')
    for n in ('env_ngidf', 'env_msim', 'env_geo', 'env_report'):
        if n in reps:
            H.append(f'<h3>{esc(reps[n]["title"])}</h3>' + checks_tbl(reps[n]))
    return '\n'.join(H)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', required=True)
    ap.add_argument('--out-dir', required=True)
    a = ap.parse_args()
    print(build(json.loads(Path(a.input).read_text()), Path(a.out_dir)))


if __name__ == '__main__':
    main()
