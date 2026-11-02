#!/usr/bin/env python3
"""Portable aggregate-only display and explicitly authorized two-image demo."""
from __future__ import annotations

import argparse
import csv
from copy import deepcopy
import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path, PurePosixPath
import sys
from urllib.parse import unquote, urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
REPORT_STEM = 'reports/DietAI24_MAE_v2_Report'
REPORTS = tuple(REPORT_STEM + suffix for suffix in ('.md', '.pdf', '.docx'))
DISPLAY_FILES = REPORTS + (REPORT_STEM + '.json', 'reports/metrics.json', 'reports/metrics.csv',
    'reports/ablation.csv', 'reports/summary.json', 'reports/demo_profile.json')
INFERENCE_FILES = tuple('src/' + name for name in ('legacy_adapter.py', 'opt_provider.py',
    'opt_pipeline.py', 'pipeline_v2.py', 'opt_metrics.py', 'metrics_v2.py'))
RUNTIME_FILES = ('data/catalog.json', 'data/vectors/manifest.json',
    'data/vectors/embeddings.npy', 'data/vectors/collection.json', 'data/vectors/codes.json')
APPROVED_IMAGES = {
    'asa24': 'eb63c3c47075ceda6084188016d2d958cada70af8db92f1747202fc79a9cfb88',
    'nutrition5k': '9cb3264142a8d9fc89d7b5dad482bde2d1acd857e2dd7107709b6620308d94ae'}
TARGETS = ('weight', 'energy', 'fat', 'carbs', 'protein')
FORBIDDEN_AGGREGATE_KEYS = {'sample_id', 'dish_id', 'group_id', 'training_ids', 'labels',
    'truth', 'predictions', 'records', 'oof_predictions', 'example_sources', 'image_path', 'raw_response'}
MIME = {'.md': 'text/plain; charset=utf-8', '.json': 'application/json; charset=utf-8',
    '.csv': 'text/csv; charset=utf-8', '.pdf': 'application/pdf', '.png': 'image/png',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_file(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or any(c in relative for c in ('\\', '%', '\0')):
        raise ValueError('Unsafe relative path')
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(p in ('', '.', '..') for p in relative.split('/')):
        raise ValueError('Unsafe relative path')
    path = root
    for part in pure.parts:
        path /= part
        if path.is_symlink():
            raise ValueError('Symlinks are not permitted')
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('Required package member is missing')
    return path


def aggregate_only(value):
    if isinstance(value, dict):
        if FORBIDDEN_AGGREGATE_KEYS & set(value):
            raise ValueError('Row-level research data is not a public aggregate')
        for item in value.values():
            aggregate_only(item)
    elif isinstance(value, list):
        for item in value:
            aggregate_only(item)


def demo_inputs(root=ROOT):
    descriptor = json.loads(safe_file(root, 'tools/demo_inputs.json').read_text())
    rows = descriptor.get('manifest', [])
    if descriptor.get('formal_test') is not False or len(rows) != 2:
        raise ValueError('Exactly two fixed historical demo inputs are required')
    if set(descriptor) != {'schema_version', 'formal_test', 'provenance', 'manifest'}:
        raise ValueError('Demo descriptor cannot contain reference labels')
    if {r['dataset'] for r in rows} != set(APPROVED_IMAGES):
        raise ValueError('Demo dataset inventory differs')
    for row in rows:
        if set(row) != {'sample_id', 'dataset', 'split', 'group_id', 'fold', 'image_path', 'image_sha256'}:
            raise ValueError('Unexpected demo input metadata')
        dataset = row['dataset']
        if (row['image_path'] != f'tools/demo_images/{dataset}.png'
                or row['image_sha256'] != APPROVED_IMAGES[dataset]
                or sha256(safe_file(root, row['image_path'])) != APPROVED_IMAGES[dataset]):
            raise ValueError('Historical demo image mismatch')
        if (row['sample_id'] != 'historical-' + dataset or row['group_id'] != row['sample_id']
                or row['split'] != 'demo' or row['fold'] is not None):
            raise ValueError('Demo rows must use neutral identities')
    return rows


def _parameters(value, dataset):
    if value.get('dataset') != dataset:
        raise ValueError('Profile parameter dataset differs')
    factor = value.get('mass_factor')
    if type(factor) not in (int, float) or not math.isfinite(factor) or not .9 <= factor <= 1.125:
        raise ValueError('Invalid final mass factor')
    fallback = value.get('fallback', {})
    if set(fallback) != set(TARGETS) or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in fallback.values()):
        raise ValueError('A complete finite fitted fallback is required')
    if type(value.get('enabled', False)) is not bool:
        raise ValueError('Calibration enabled flag must be boolean')
    if not value.get('enabled', False) and factor != 1.0:
        raise ValueError('Disabled calibration must retain unit mass factor')
    return {'dataset': dataset, 'mass_factor': factor, 'enabled': value.get('enabled', False),
            'fallback': {key: fallback[key] for key in TARGETS}}


def make_demo_profile(selection, parameters_by_dataset, root=ROOT, *, validation_status='not_run'):
    """Return a public profile from completed selection + externally fitted params.

    This helper never reads dev/validation inputs, fits parameters or copies
    training IDs. The report writer supplies the exact chosen fitted parameters.
    """
    if validation_status not in ('not_run', 'completed', 'incomplete'):
        raise ValueError('Unknown independent validation status')
    profiles = {}
    for dataset in APPROVED_IMAGES:
        selected = selection['profiles'][dataset]
        profiles[dataset] = {'name': selected['name'], 'config': deepcopy(selected['config']),
            'parameters': _parameters(parameters_by_dataset[dataset], dataset)}
    result = {'schema_version': 2, 'status': 'final', 'profiles': profiles,
        'selection_scope': 'development_not_independent_validation',
        'development_joint_pass': bool(selection.get('joint_pass', False)),
        'independent_validation_status': validation_status,
        'source_sha256': {name: sha256(safe_file(root, name)) for name in INFERENCE_FILES},
        'runtime_sha256': {name: sha256(safe_file(root, name)) for name in RUNTIME_FILES}}
    validate_profile(result, root)
    return result


def validate_profile(profile, root=ROOT):
    aggregate_only(profile)
    if set(profile) != {'schema_version', 'status', 'profiles', 'selection_scope',
                       'development_joint_pass', 'independent_validation_status', 'source_sha256', 'runtime_sha256'}:
        raise ValueError('Unexpected public profile metadata')
    if (profile.get('schema_version') != 2 or profile.get('status') != 'final'
            or set(profile.get('profiles', {})) != set(APPROVED_IMAGES)
            or profile.get('selection_scope') != 'development_not_independent_validation'
            or type(profile.get('development_joint_pass')) is not bool
            or profile.get('independent_validation_status') not in ('not_run', 'completed', 'incomplete')):
        raise ValueError('A completed final demo profile is required')
    if set(profile.get('source_sha256', {})) != set(INFERENCE_FILES):
        raise ValueError('Profile must bind the exact portable inference sources')
    for relative, expected in profile['source_sha256'].items():
        if sha256(safe_file(root, relative)) != expected:
            raise ValueError('Demo inference source differs from selected profile')
    if set(profile.get('runtime_sha256', {})) != set(RUNTIME_FILES):
        raise ValueError('Profile must bind the exact saved runtime')
    if any(not isinstance(value, str) or len(value) != 64 or set(value) - set('0123456789abcdef')
           for value in profile['runtime_sha256'].values()):
        raise ValueError('Invalid frozen runtime checksum')
    for dataset, selected in profile['profiles'].items():
        if set(selected) != {'name', 'config', 'parameters'} or set(selected['parameters']) != {'dataset', 'mass_factor', 'enabled', 'fallback'}:
            raise ValueError('Unexpected public selected-profile metadata')
        _parameters(selected['parameters'], dataset)
        cfg, name = selected['config'], selected['name']
        if dataset == 'nutrition5k' and name in ('A', 'B', 'C', 'D', 'E'):
            if set(cfg) - {'profile', 'portion_mode', 'crop_review', 'base_profile', 'identity_profile', 'image_mode', 'candidate_cap'}:
                raise ValueError('Unexpected component configuration')
            if cfg.get('image_mode', 'native') != 'native' or cfg.get('candidate_cap', 32) != 32:
                raise ValueError('Unsupported component image/retrieval configuration')
            if cfg.get('profile') != name or cfg.get('portion_mode') not in ('direct', 'total_ratio'):
                raise ValueError('Component profile/config mismatch')
            base = cfg.get('base_profile') if name in ('D', 'E') else name
            if base not in ('A', 'B', 'C'):
                raise ValueError('Invalid component base profile')
            identity = cfg.get('identity_profile') if base == 'C' else base
            if identity not in ('A', 'B') or cfg.get('crop_review') is not (identity == 'B'):
                raise ValueError('Component identity ancestry mismatch')
            if cfg['portion_mode'] != ('total_ratio' if base == 'C' else 'direct'):
                raise ValueError('Component portion ancestry mismatch')
        else:
            allowed = ('baseline', 'asa-retrieval-portion') if dataset == 'asa24' else ('baseline', 'examples-2')
            if name not in allowed or dataset not in cfg.get('portion_modes', {}):
                raise ValueError('Invalid legacy profile')
            if set(cfg) - {'variant', 'image_mode', 'candidate_cap', 'portion_modes', 'examples'}:
                raise ValueError('Unexpected legacy configuration')
            if cfg.get('variant', 'baseline') not in ('baseline', 'optimized') or cfg.get('image_mode', 'square256') not in ('square256', 'native'):
                raise ValueError('Unsupported legacy configuration')
            if cfg.get('candidate_cap', 32) != 32 or type(cfg.get('examples', False)) is not bool:
                raise ValueError('Unsupported legacy retrieval configuration')
            modes = cfg['portion_modes']
            if set(modes) - set(APPROVED_IMAGES) or any(mode not in ('direct', 'continuous_option') if ds == 'asa24' else mode not in ('direct', 'total_ratio') for ds, mode in modes.items()):
                raise ValueError('Unsupported legacy portion configuration')
    return profile


def check_runtime(root=ROOT, profile=None):
    manifest = json.loads(safe_file(root, 'data/vectors/manifest.json').read_text())
    if (set(manifest.get('files', {})) != {'embeddings.npy', 'collection.json', 'codes.json'}
            or manifest.get('vectors') != 5624 or manifest.get('dimensions') != 3072
            or manifest.get('embedding_model') != 'text-embedding-3-large'):
        raise ValueError('Saved vector inventory differs')
    for name, expected in manifest['files'].items():
        if sha256(safe_file(root, 'data/vectors/' + name)) != expected:
            raise ValueError('Saved vector checksum mismatch')
    catalog = json.loads(safe_file(root, 'data/catalog.json').read_text())
    codes = json.loads(safe_file(root, 'data/vectors/codes.json').read_text())
    if len(catalog.get('foods', {})) != 5624 or set(codes) != set(catalog['foods']):
        raise ValueError('Saved catalog/vector codes differ')
    if profile:
        for name, expected in profile['runtime_sha256'].items():
            if sha256(safe_file(root, name)) != expected:
                raise ValueError('Runtime differs from the selected profile')
    return {'available': True, 'vectors': 5624, 'dimensions': 3072, 'index_rebuild': False,
            'corpus_embedding_calls': 0}


def public_files(root=ROOT):
    files = {}
    for relative in DISPLAY_FILES:
        if (Path(root) / relative).exists():
            path = safe_file(root, relative)
            if path.suffix == '.json':
                aggregate_only(json.loads(path.read_text()))
            elif path.suffix == '.csv':
                with path.open(newline='') as handle:
                    fields = next(csv.reader(handle), [])
                if FORBIDDEN_AGGREGATE_KEYS & {name.strip().lower() for name in fields}:
                    raise ValueError('Row-level CSV is not a public aggregate')
            files[relative] = path
    for row in demo_inputs(root):
        files[row['image_path']] = safe_file(root, row['image_path'])
    return files


def check(root=ROOT, require_runtime=False):
    files = public_files(root)
    missing = [name for name in REPORTS + ('reports/demo_profile.json',) if name not in files]
    if not any(name in files for name in (REPORT_STEM + '.json', 'reports/metrics.json', 'reports/metrics.csv')):
        missing.append(REPORT_STEM + '.json or reports/metrics.json or reports/metrics.csv')
    profile = None
    if 'reports/demo_profile.json' in files:
        profile = validate_profile(json.loads(files['reports/demo_profile.json'].read_text()), root)
    runtime = {'available': (Path(root) / 'data/vectors/manifest.json').is_file(), 'checked': False}
    if require_runtime:
        runtime = check_runtime(root, profile)
    return {'status': 'PASS' if not missing else 'INCOMPLETE', 'missing': missing,
        'api_calls': 0, 'credentials_read': False, 'research_cohorts_read': False,
        'runtime': runtime, 'checked_platform': sys.platform,
        'mac_execution': 'not_verified' if sys.platform != 'darwin' else 'offline_check_only',
        'formal_validation_replayed': False}


def _presentation_text(value):
    """Escape every external string before inserting it into markup or attributes."""
    return html.escape(str(value), quote=True)


def _presentation_number(value, *, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    if integer and int(value) != value:
        return None
    return int(value) if integer else value


def _presentation_format(value, precision=3):
    if value is None:
        return 'Not available'
    rendered = f'{value:,.{precision}f}'
    return rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered


def _presentation_status(value):
    labels = {
        'development_not_started': 'Not started', 'development_in_progress': 'In progress',
        'ready_for_review': 'Development gates met', 'development_targets_not_met': 'Targets not met',
        'not_run_or_not_completed': 'Not run or not completed', 'not_run': 'Not run',
        'partial_aggregates_without_completion': 'Incomplete aggregate evidence',
        'aggregate_integrity_failed': 'Aggregate checks failed', 'completed': 'Completed',
    }
    return labels.get(value, str(value).replace('_', ' ') if value else 'Not available')


def _presentation_metrics(snapshot):
    """Choose an explicitly completed formal arm, otherwise label development."""
    development = snapshot.get('development') or {}
    validation = snapshot.get('validation') or {}
    formal = (validation.get('metrics') or {}).get('optimized')
    if validation.get('status') == 'completed' and isinstance(formal, dict):
        return formal, 'Formal validation', True
    metrics = development.get('metrics')
    return metrics if isinstance(metrics, dict) else {}, 'Development selection', False


def _presentation_checks(snapshot, metrics):
    """Recalculate display decisions from finite values, never from stored flags."""
    rows = {}
    for dataset in ('asa24', 'nutrition5k'):
        source = ((metrics.get('datasets') or {}).get(dataset) or {}).get('primary') or {}
        cells = []
        for key in TARGETS:
            metric = (source.get('metrics') or {}).get(key) or {}
            threshold = ((snapshot.get('thresholds') or {}).get(dataset) or {}).get(key) or {}
            checks = {}
            for statistic in ('mae', 'per_unit'):
                value = _presentation_number(metric.get(statistic))
                cap = _presentation_number(threshold.get(statistic, metric.get('threshold_' + statistic)))
                cap = cap if cap is not None and cap > 0 else None
                checks[statistic] = {'value': value, 'cap': cap,
                    'passed': value <= cap if value is not None and cap is not None else None}
            cells.append((key, checks))
        rows[dataset] = cells
    return rows


def _presentation_table(dataset, data, checks, profile=None):
    labels = {'weight': 'Weight (g)', 'energy': 'Energy (kcal)', 'fat': 'Fat (g)',
              'carbs': 'Carbohydrate (g)', 'protein': 'Protein (g)'}
    rows = []
    for key, measures in checks:
        values = []
        for statistic in ('mae', 'per_unit'):
            measure = measures[statistic]
            precision = 4 if statistic == 'per_unit' else 3
            value, cap = measure['value'], measure['cap']
            result = measure['passed']
            label, style = ('Pass', 'pass') if result is True else ('Above cap', 'fail') if result is False else ('Unavailable', 'unknown')
            exact = f'Value: {value}; cap: {cap}. Status uses unrounded values.'
            values.append('<td><span class="numeric" title="' + _presentation_text(exact) + '">' +
                _presentation_text(_presentation_format(value, precision)) + ' <span class="slash">/</span> ' +
                _presentation_text(_presentation_format(cap, precision)) + '</span><span class="metric-state ' + style + '">' + label + '</span></td>')
        results = [v['passed'] for v in measures.values()]
        outcome = 'Within both caps' if all(v is True for v in results) else 'Incomplete' if any(v is None for v in results) else 'Needs improvement'
        rows.append('<tr><th scope="row">' + labels[key] + '</th>' + ''.join(values) + '<td class="outcome">' + outcome + '</td></tr>')
    title = 'ASA24' if dataset == 'asa24' else 'Nutrition5k'
    primary = data.get('primary') or {}
    count, groups = _presentation_number(data.get('n'), integer=True), _presentation_number(data.get('groups'), integer=True)
    scored = _presentation_number(primary.get('n'), integer=True)
    subtitle = ('Exact-conditioned legal-option task' if dataset == 'asa24' else 'All-image nutrient estimation')
    subtitle += ' · ' + _presentation_format(count, 0) + ' images · ' + _presentation_format(groups, 0) + ' association groups'
    if scored is not None:
        subtitle += ' · ' + _presentation_format(scored, 0) + ' primary observations'
    selected = '<span class="profile">Selected: ' + _presentation_text(profile) + '</span>' if profile else ''
    return '<section class="panel metric-panel"><div class="section-heading"><div><h2>' + title + '</h2><p>' + _presentation_text(subtitle) + '</p></div>' + selected + '</div>' + \
        '<div class="table-scroll"><table><thead><tr><th scope="col">Target</th><th scope="col">Absolute MAE / cap</th><th scope="col">Per-unit MAE / cap</th><th scope="col">Result</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div></section>'


def render_page(root=ROOT):
    files = public_files(root)
    snapshot_path = files.get(REPORT_STEM + '.json')
    snapshot = json.loads(snapshot_path.read_text()) if snapshot_path else {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    development, validation = snapshot.get('development') or {}, snapshot.get('validation') or {}
    metrics, scope, formal = _presentation_metrics(snapshot)
    checks = _presentation_checks(snapshot, metrics)
    outcomes = [v['passed'] for rows in checks.values() for _, pair in rows for v in pair.values()]
    available = sum(v is not None for v in outcomes)
    passing = sum(v is True for v in outcomes)
    pass_value = str(passing) + ' / 20' if available == 20 else '— / 20'
    pass_note = 'MAE checks within registered caps' if available == 20 else str(available) + ' of 20 checks have complete evidence'
    datasets = metrics.get('datasets') or {}
    asa = datasets.get('asa24') or {}
    n, exact = _presentation_number(asa.get('n'), integer=True), _presentation_number(asa.get('exact_n'), integer=True)
    known_recognition = n is not None and n > 0 and exact is not None and exact <= n
    recognition = f'{exact} / {n}' if known_recognition else 'Not available'
    recognition_note = (f'{100 * exact / n:.2f}% Exact · 15% floor requires {(15 * n + 99) // 100} hits' if known_recognition else 'Exact recognition evidence is incomplete')
    gate = ('Recognition floor met' if exact >= (15 * n + 99) // 100 else 'Below recognition floor') if known_recognition else 'Recognition not assessed'
    independent = _presentation_status(validation.get('status'))
    if validation.get('status') == 'completed' and not formal:
        independent = 'Incomplete aggregate evidence'
    dev_state = _presentation_status(development.get('status'))
    profile_names = development.get('profiles') or {}
    tables = ''.join(_presentation_table(dataset, datasets.get(dataset) or {}, checks[dataset], profile_names.get(dataset))
                     for dataset in ('asa24', 'nutrition5k'))
    report_links = []
    for suffix, label in (('.pdf', 'Read PDF'), ('.docx', 'Download Word'), ('.md', 'View Markdown')):
        name = REPORT_STEM + suffix
        if name in files:
            report_links.append('<a class="button" href="/files/' + _presentation_text(name) + '">' + label + '<span aria-hidden="true"> ↗</span></a>')
        else:
            report_links.append('<span class="button unavailable">' + label + ' · unavailable</span>')
    audit = ('<a class="audit-link" href="/files/' + _presentation_text(REPORT_STEM + '.json') + '" download>Download full aggregate JSON</a>'
             if snapshot_path else '<span class="muted">Aggregate JSON has not been supplied.</span>')
    images = ''.join('<figure><div class="image-frame"><img src="/files/' + _presentation_text(row['image_path']) +
                    '" alt="' + _presentation_text(row['dataset'] + ' historical demonstration image') + '"></div><figcaption><strong>' +
                    _presentation_text('ASA24' if row['dataset'] == 'asa24' else 'Nutrition5k' if row['dataset'] == 'nutrition5k' else row['dataset']) +
                    '</strong><span>Historical demonstration input</span></figcaption></figure>' for row in demo_inputs(root))
    generated = _presentation_text(snapshot.get('generated_utc') or 'Timestamp not supplied')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DietAI24 · Performance overview</title>
<style>
:root{{color-scheme:light;--ink:#182f39;--muted:#5c6d74;--line:#dce3e4;--paper:#f4f6f4;--teal:#176759;--fail:#884624}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{max-width:1160px;margin:auto;padding:40px 28px 30px}}a{{color:var(--teal)}}.eyebrow{{font-size:12px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--teal)}}header{{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;margin-bottom:26px}}h1{{font-size:clamp(30px,4vw,43px);line-height:1.12;letter-spacing:-.035em;margin:10px 0 12px;font-weight:650}}header p{{margin:0;color:var(--muted);max-width:680px}}.offline{{white-space:nowrap;background:#e2eee7;border:1px solid #cadfd2;border-radius:24px;padding:8px 14px;color:#245b45;font-size:12px;font-weight:650}}.offline::before{{content:"●";margin-right:7px;font-size:9px}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:24px 0}}.card,.panel{{background:white;border:1px solid var(--line);border-radius:12px}}.card{{padding:20px;min-height:150px}}.card-label{{font-size:12px;font-weight:650;color:var(--muted);margin-bottom:10px}}.card-value{{font-size:29px;line-height:1.2;letter-spacing:-.02em;font-weight:650}}.card-value.status{{font-size:20px;line-height:1.3}}.card p{{font-size:12px;line-height:1.5;color:var(--muted);margin:10px 0 0}}.scope-line{{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:28px 0 12px}}.scope-line h2{{font-size:20px;margin:0}}.scope-badge{{font-size:12px;border:1px solid #c7dcd5;background:#eaf3ef;color:#285e50;padding:5px 10px;border-radius:20px}}.panel{{margin-bottom:18px;overflow:hidden}}.section-heading{{display:flex;justify-content:space-between;align-items:center;gap:15px;padding:21px 24px 17px;border-bottom:1px solid var(--line)}}h2{{font-size:21px;letter-spacing:-.02em;margin:0 0 7px}}.section-heading p{{font-size:12px;margin:0;color:var(--muted)}}.profile{{font-size:12px;color:var(--muted);white-space:nowrap}}.table-scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;text-align:left;font-variant-numeric:tabular-nums}}thead{{background:#f9faf9}}th,td{{padding:13px 24px;border-bottom:1px solid #e8ecec;vertical-align:middle}}thead th{{font-size:11px;text-transform:uppercase;letter-spacing:.045em;color:var(--muted);font-weight:650}}tbody th{{font-weight:550;font-size:14px;width:24%}}tbody tr:last-child th,tbody tr:last-child td{{border:0}}.numeric{{white-space:nowrap;font-size:15px;font-weight:550}}.slash{{color:#9ca9ae;margin:0 5px}}.metric-state{{display:block;font-size:11px;margin-top:2px}}.pass{{color:#27674e}}.fail{{color:var(--fail)}}.unknown{{color:var(--muted)}}.outcome{{font-size:12px;color:var(--muted)}}.reading{{padding:22px 24px;background:#eaf0ed;border:1px solid #d7e2dc;border-radius:12px;margin:20px 0 26px}}.reading h2{{font-size:17px}}.reading p{{font-size:13px;margin:7px 0;color:#41564f}}.reading strong{{color:#243f35}}.downloads{{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:22px 24px}}.downloads h2{{font-size:18px}}.downloads p{{font-size:12px;color:var(--muted);margin:0}}.download-buttons{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}.button{{display:inline-block;text-decoration:none;border:1px solid #cbdad4;color:#245e4d;border-radius:7px;padding:8px 13px;font-size:13px;background:#f8fbf9}}.button:hover{{background:#eaf3ee}}.button.unavailable{{color:#7b878b;background:#f5f6f5;border-color:#e1e5e4}}.audit-link{{font-size:12px;white-space:nowrap}}.muted{{font-size:12px;color:var(--muted)}}.examples{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}figure{{margin:0;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:white}}.image-frame{{height:240px;display:flex;align-items:center;justify-content:center;background:#e9ede9;padding:14px}}img{{display:block;max-width:100%;max-height:100%;object-fit:contain;border-radius:3px}}figcaption{{padding:15px 20px;display:flex;justify-content:space-between;gap:12px;font-size:13px}}figcaption span{{font-size:12px;color:var(--muted)}}.examples-heading{{margin-top:28px}}.examples-note{{font-size:12px;color:var(--muted);margin:11px 0}}footer{{margin-top:30px;padding-top:15px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;font-size:11px;color:var(--muted);overflow-wrap:anywhere}}@media(max-width:800px){{.cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}.downloads{{display:block}}.audit-link{{display:inline-block;margin-top:15px}}th,td{{padding:12px 16px}}}}@media(max-width:520px){{main{{padding:25px 16px}}header{{display:block}}.offline{{display:inline-block;margin-top:16px}}.card{{padding:15px;min-height:140px}}.card-value{{font-size:25px}}.card-value.status{{font-size:18px}}.section-heading{{display:block;padding:18px}}.profile{{display:block;margin-top:8px}}table{{min-width:660px}}.examples{{grid-template-columns:1fr}}.scope-line{{align-items:flex-start}}footer{{display:block}}footer span{{display:block;margin-top:5px}}}}
</style></head><body><main>
<header><div><div class="eyebrow">DietAI24 · MAE first study · Version 2</div><h1>Performance overview</h1><p>Single-image food recognition and nutrition estimation. Saved results from the bounded Sol optimization study.</p></div><span class="offline">Offline evidence · 0 API calls</span></header>
<section class="cards" aria-label="Study overview">
<div class="card"><div class="card-label">DEVELOPMENT</div><div class="card-value status">{_presentation_text(dev_state)}</div><p>Candidate selection and calibration</p></div>
<div class="card"><div class="card-label">FORMAL VALIDATION</div><div class="card-value status">{_presentation_text(independent)}</div><p>Independent acceptance stage</p></div>
<div class="card"><div class="card-label">MAE CHECKS</div><div class="card-value">{_presentation_text(pass_value)}</div><p>{_presentation_text(pass_note)}</p></div>
<div class="card"><div class="card-label">ASA24 EXACT RECOGNITION</div><div class="card-value">{_presentation_text(recognition)}</div><p>{_presentation_text(recognition_note)}<br>{_presentation_text(gate)}</p></div>
</section>
<div class="scope-line"><h2>Primary results</h2><span class="scope-badge">{_presentation_text(scope)}</span></div>
{tables}
<section class="reading"><h2>How to read these results</h2><p><strong>ASA24:</strong> Exact-conditioned means portion errors are scored only when the correct food code is recognized; legal portion options are then supplied. This is distinct from image-only end-to-end prediction.</p><p><strong>Nutrition5k:</strong> Primary errors include every active image, including whole-dish fallback. Per-unit MAE is absolute MAE divided by the reference mean, not average per-image percentage error. Caps are 1.3 times the paper values; decisions use full precision.</p><p><strong>Development reference:</strong> The original baseline uses the same active development cohort. Selected development results include model selection and calibration and are not independent validation. Archived Sol and v1 references keep their original populations and are not paired improvements over this cohort.</p></section>
<section class="panel downloads"><div><h2>Report and evidence</h2><p>Full methods, confidence intervals, historical comparisons, and remaining gaps.</p><div class="download-buttons">{''.join(report_links)}</div></div>{audit}</section>
<h2 class="examples-heading">Two historical demonstration images</h2><div class="examples">{images}</div><p class="examples-note">These fixed inputs illustrate the portable demo. They are not a new validation set. Optional live ASA24 inference is image-only E2E and does not reproduce the report's conditional portion task.</p>
<footer><span>Saved aggregate display · no experiment is rerun</span><span>Snapshot: {generated}</span></footer>
</main></body></html>'''.encode()

def server(root=ROOT, port=8765):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('Invalid port')
    files = public_files(root)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path == '/':
                body, mime = render_page(root), 'text/html; charset=utf-8'
            elif path.startswith('/files/') and path[7:] in files:
                relative = path[7:]
                try:
                    # Revalidate allowlisted JSON/CSV and image hashes on every request.
                    file = public_files(root)[relative]
                    body, mime = file.read_bytes(), MIME.get(file.suffix, 'application/octet-stream')
                except (ValueError, KeyError):
                    self.send_error(404)
                    return
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def component_inference(pipeline, picture, config):
    """Run the selected ancestry on a new image, without any target metadata."""
    cfg = deepcopy(config)
    identity = pipeline.identify(picture, cfg)
    result = pipeline.portion(picture, identity, cfg)
    if cfg['profile'] in ('D', 'E'):
        if result.get('status') != 'ok' or result.get('prediction') is None:
            result = {**result, 'method_fallback': True, 'method_fallback_reason': 'base_incomplete'}
        elif cfg['profile'] == 'D':
            identity, result = pipeline.review_codes(picture, identity, result, cfg)
        else:
            result = pipeline.standard_portions(picture, identity, result, cfg)
    return identity, result


def legacy_inference(adapter, pipeline, row, config, catalog, parameters):
    """Explicit image-only interface: never accept a label or example bank."""
    cfg = deepcopy(config)
    deviation = None
    if cfg.get('examples'):
        cfg['examples'] = False
        deviation = ('Selected legacy examples profile: development example bank omitted; '
                     'examples disabled. This is a method deviation, not a replay of reported accuracy.')
    picture = adapter.image_path(row)
    identity = pipeline.identify_select(picture, row['dataset'], adapter.per_dataset(cfg, row['dataset']))
    pred = adapter.infer_portions(pipeline, row, identity, cfg, catalog,
                                 label=None, fallback_vector=parameters['fallback'], examples=())
    return pred, deviation


def _local_keys(root):
    from dotenv import dotenv_values
    path = safe_file(root, '.env')  # strictly local: no provider parent fallback
    if path.stat().st_mode & 0o077:
        raise ValueError('The local credential file must have mode 0600')
    values = dotenv_values(path, interpolate=False)
    expected = {'OPENAI_BASE_URL': 'https://api.zicc.cc/v1', 'EMBEDDING_BASE_URL': 'https://api.openai.com/v1',
        'CHAT_MODEL': 'gpt-6.1-sol', 'VISION_MODEL': 'gpt-6.1-sol'}
    if any(values.get(key) != value for key, value in expected.items()):
        raise ValueError('Local fixed provider routes differ')
    keys = (values.get('OPENAI_API_KEY'), values.get('EMBEDDING_API_KEY'))
    if any(not key or '$' in key or key.startswith('replace_') for key in keys) or keys[0] == keys[1]:
        raise ValueError('Two distinct local credentials are required')
    return keys


def live(root=ROOT, allow_paid=False):
    result = check(root, require_runtime=True)
    if result['status'] != 'PASS':
        return result
    profile = validate_profile(json.loads(safe_file(root, 'reports/demo_profile.json').read_text()), root)
    if not allow_paid:
        return {**result, 'status': 'READY_DRY_RUN', 'images': 2,
                'notice': 'A current user authorization and --allow-paid are required.'}
    # Nothing above imports the provider or opens credentials/research inputs.
    keys = _local_keys(root)
    sys.path.insert(0, str(Path(root) / 'src'))
    from opt_provider import Provider, ProviderStop, atomic_json, stamp, usage, ROOT as PROVIDER_ROOT
    if Path(root).resolve() != PROVIDER_ROOT.resolve():
        raise ValueError('Loaded inference module belongs to a different package')
    import legacy_adapter as legacy
    import metrics_v2
    from pipeline_v2 import ComponentPipeline
    catalog = json.loads(safe_file(root, 'data/catalog.json').read_text())
    name = stamp().replace(':', '').replace('+', '_')
    run = Path(root) / 'runs/demo' / name
    run.mkdir(parents=True, exist_ok=False)
    provider = Provider(run, allow_paid=True, namespace='mae-v2-demo-' + name, keys=keys)
    deviations = ['ASA24 is image-only E2E; the report primary task uses Exact-conditioned legal options.']
    predictions = []
    try:
        legacy_pipeline = legacy.make_pipeline(provider, catalog)
        components = ComponentPipeline(lambda messages: provider.chat(messages, max_completion_tokens=8192),
                                       provider.embed, catalog, legacy_pipeline.retriever)
        for row in demo_inputs(root):
            dataset = row['dataset']
            chosen = profile['profiles'][dataset]
            cfg, params = deepcopy(chosen['config']), chosen['parameters']
            picture = safe_file(root, row['image_path'])
            if dataset == 'nutrition5k' and chosen['name'] in ('A', 'B', 'C', 'D', 'E'):
                identity, portion = component_inference(components, picture, cfg)
                valid = portion.get('status') == 'ok' and portion.get('prediction') is not None
                pred = {'dataset': dataset, 'raw_prediction': portion.get('prediction') if valid else None,
                    'prediction': portion['prediction'] if valid else dict(params['fallback']),
                    'raw_leaves': portion.get('raw_leaves', []) if valid else [], 'portion_result': portion,
                    'fallback': not valid, 'native_complete': valid and not identity.get('repaired') and not portion.get('repaired') and not portion.get('method_fallback'),
                    'method_fallback': bool(portion.get('method_fallback')),
                    'final_codes': identity.get('final_codes', []), 'conditional': None, 'e2e': None}
            else:
                pred, deviation = legacy_inference(legacy, legacy_pipeline, row, cfg, catalog, params)
                if deviation:
                    deviations.append(deviation)
            pred = metrics_v2.apply_parameters(pred, params, catalog['asa_options'],
                                               {code: food['density'] for code, food in catalog['foods'].items()})
            predictions.append({'dataset': dataset, 'profile': chosen['name'], 'prediction': pred['prediction'],
                'fallback': pred.get('fallback', False), 'native_complete': pred.get('native_complete', False),
                'method_fallback': pred.get('method_fallback', False), 'final_codes': pred.get('final_codes', []),
                'conditional_reference_used': False})
        summary = {'status': 'completed', 'formal_validation': False, 'research_cohorts_read': False,
            'profile_sha256': sha256(safe_file(root, 'reports/demo_profile.json')),
            'predictions': predictions, 'deviations': deviations, 'usage': usage(run)}
        atomic_json(run / 'summary.json', summary)
        return summary
    except ProviderStop:
        raise ValueError('Live provider stopped; preserve the local demo artifacts and inspect sanitized usage') from None
    finally:
        atomic_json(run / 'usage.json', usage(run))
        provider.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--serve', action='store_true')
    modes.add_argument('--live', action='store_true')
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--require-runtime', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    try:
        if args.serve:
            httpd = server(port=args.port)
            address = f'http://127.0.0.1:{httpd.server_port}'
            print(address + ' (saved aggregate display; API calls: 0)', flush=True)
            if args.open:
                webbrowser.open(address)
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                httpd.server_close()
            return 0
        result = live(allow_paid=args.allow_paid) if args.live else check(require_runtime=args.require_runtime)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result['status'] == 'INCOMPLETE' else 0
    except Exception as error:
        # Never echo provider exceptions, credential values or source row text.
        print(json.dumps({'status': 'STOPPED', 'error_type': type(error).__name__,
                          'notice': 'Package, runtime or local authorization check failed; no settings were substituted.'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
