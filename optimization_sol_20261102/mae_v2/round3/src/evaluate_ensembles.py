#!/usr/bin/env python3
"""Offline, preregistered whole-vector ensembles; seal before decoding labels.

No provider, image loader, validation loader or inference driver is imported.
Frozen transitive provenance files are hashed, never used as new predictions.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import opt_metrics as metrics

METHODS = {'HI_mean': ('H', 'I'), 'CHI_median': ('C', 'H', 'I')}
BOOTSTRAP = 10000
CORE = ('cohorts_v2.py', 'legacy_adapter.py', 'opt_provider.py', 'opt_pipeline.py',
        'pipeline_v2.py', 'opt_metrics.py', 'metrics_v2.py', 'study.py', 'validation_adapter.py')
REVIEW = 'evidence/review-one-completion.json'
CORRECTION = 'evidence/R-M2-4-1.json'
TRUSTED_EVIDENCE = {
    REVIEW: 'd80987a08b81b6f1bb042260d78ee19053ad7140de5c18bb03eca6ecef1c8fce',
    CORRECTION: 'c742414a52f1b57a0bfe1273f973194736d28986210f067c4e28ef9f7096aa46',
}
MEMBER_FINAL = ('records_sealed.json', 'predictions.json', 'metrics.json', 'usage.json',
                'binding.json', 'example_assignments.json')
FINAL = ('binding.json', 'records_sealed.json', 'predictions.json', 'metrics.json')
LABELS = 'data/cohorts/dev_labels.json'
MANIFEST = 'data/cohorts/dev.jsonl'
SELECTED = 'runs/development/selected_oof_predictions.json'
SELECTION = 'runs/development/selection.json'
PROTOCOL = 'round3/ENSEMBLE_PROTOCOL.md'
SELF = 'round3/src/evaluate_ensembles.py'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(safe_file(path).read_bytes()).hexdigest()


def decode(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def safe_file(path):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('Expected canonical regular file')
    return path


def artifact(row):
    return fingerprint(row['sample_id'])[:24] + '.json'


def load(path):
    return decode(safe_file(path).read_bytes())


def write_once(path, value):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('Unsafe output path')
    if path.exists():
        if load(path) != value:
            raise ValueError('Immutable artifact differs')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.ensemble-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        os.chmod(temporary, 0o600)
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Reader:
    def __init__(self):
        self.allowed = {MANIFEST}
        self.hashes = {}
        self.labels_allowed = False

    def bytes(self, name):
        if name not in self.allowed:
            raise ValueError('Input outside exact development allowlist')
        raw = safe_file(ROOT / name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if name in self.hashes and self.hashes[name] != digest:
            raise ValueError('Input changed during offline evaluation')
        self.hashes[name] = digest
        return raw

    def json(self, name):
        if name == LABELS and not self.labels_allowed:
            raise ValueError('Decode labels only after both ensembles are sealed')
        return decode(self.bytes(name))

    def unchanged(self):
        if any(sha(ROOT / name) != digest for name, digest in self.hashes.items()):
            raise ValueError('Input changed during offline evaluation')


def population(rows):
    indexed = metrics._index(rows, 'development manifest')
    n5 = [r for r in rows if r.get('dataset') == 'nutrition5k']
    asa = [r for r in rows if r.get('dataset') == 'asa24']
    if (len(indexed) != 183 or len(n5) != 84 or len(asa) != 99
            or len({r['group_id'] for r in n5}) != 78
            or len({r['group_id'] for r in asa}) != 23
            or any(r.get('split') != 'dev' for r in rows)
            or any(type(r.get('fold')) is not int or r['fold'] not in range(5) for r in rows)
            or any(r.get(k) is not None and str(r[k]).lower() not in {'dev', 'development', 'train', 'training'}
                   for r in rows for k in ('partition', 'cohort'))
            or any(r.get(k) for r in rows for k in ('sealed', 'validation', 'is_validation'))):
        raise ValueError('Registered 84/78 and 99/23 development population differs')
    seen = {}
    for row in rows:
        key = row['dataset'], row['group_id']
        if key in seen and seen[key] != row['fold']:
            raise ValueError('Group crosses folds')
        seen[key] = row['fold']
    return n5, asa


def source_sets(rows):
    """Exact as-run H/I transitive inventories; no glob or arbitrary binding path."""
    common = {REVIEW, CORRECTION, MANIFEST, LABELS, 'data/cohorts/dev_freeze.json',
              SELECTED, SELECTION, 'PROTOCOL.md', 'data/catalog.json',
              'runs/development/C/run_config.json', 'runs/development/C/records_sealed.json',
              'runs/development/C/predictions.json', 'data/vectors/manifest.json',
              'data/vectors/embeddings.npy', 'data/vectors/codes.json', 'data/vectors/collection.json',
              'round3/runs/F/metrics.json', 'round3/runs/F/completion.json',
              'round3/runs/F/records_sealed.json', 'round3/evidence/F_audit.json',
              'config/experiment.json', 'config/candidates.json', 'round3/src/examples.py',
              'round3/src/dev_ingredients.py', 'round3/data/dev_ingredients.json',
              'round3/runs/G/binding.json', 'round3/runs/G/example_assignments.json'}
    common |= {'src/' + name for name in CORE}
    common |= {'runs/development/C/records/' + artifact(row) for row in rows}
    common |= {f'round3/data/train_catalogs/fold_{fold}.json' for fold in range(5)}
    h = common | {'round3/src/run_catalog.py', 'round3/src/catalog_estimator.py', 'round3/H_PROTOCOL.md'}
    i = h | {'round3/runs/H/' + name for name in (*MEMBER_FINAL, 'completion.json')}
    i |= {'round3/runs/H/records/' + artifact(row) for row in rows}
    i |= {'round3/src/run_visual.py', 'round3/src/visual_estimator.py', 'round3/I_PROTOCOL.md'}
    return h, i


def verify_review(reader):
    reviewed, correction = reader.json(REVIEW), reader.json(CORRECTION)
    current = {name: hashlib.sha256(reader.bytes('src/' + name)).hexdigest() for name in CORE}
    if (any(reader.hashes[name] != value for name, value in TRUSTED_EVIDENCE.items())
            or reviewed.get('status') != 'approved_or_fixed'
            or type(reviewed.get('unresolved_p1_p2')) is not int or reviewed['unresolved_p1_p2'] != 0
            or reviewed.get('code_sha256') != current
            or correction.get('finding') != 'R-M2-4-1'
            or correction.get('source_sha256_after') != current['opt_metrics.py']
            or reviewed.get('evidence_sha256', {}).get('R-M2-4-1.json') != reader.hashes[CORRECTION]):
        raise ValueError('Reviewed source compatibility differs')
    proof = correction.get('actual_development_recalculation', {})
    if any(proof.get(k) is not True for k in ('complete_metrics_object_equals_checkpoint',
            'complete_metrics_object_equals_saved_selection', 'existing_structure_and_all_intervals_unchanged')):
        raise ValueError('Reviewed metric equivalence is unconfirmed')
    for name in (MANIFEST, LABELS, 'data/cohorts/dev_freeze.json', SELECTED, SELECTION):
        reader.bytes(name)
        if reader.hashes[name] != correction.get('input_sha256', {}).get(name):
            raise ValueError('Reviewed development data changed')
    for field, name in (('dev_freeze_sha256', 'data/cohorts/dev_freeze.json'),
                        ('selection_sha256', SELECTION), ('protocol_sha256', 'PROTOCOL.md'),
                        ('catalog_sha256', 'data/catalog.json')):
        reader.bytes(name)
        if reviewed.get(field) != reader.hashes[name]:
            raise ValueError('Review artifact binding differs')
    return reviewed


def validate_record(row, record):
    if any(record.get(k) != row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')):
        raise ValueError('Member identity differs')
    metrics._vector(record.get('prediction'), 'member prediction')
    for key in ('fallback', 'native_complete'):
        if type(record.get(key)) is not bool:
            raise ValueError('Member failure state is missing')
    for key in ('repair_used', 'repaired', 'method_fallback'):
        if key in record and type(record[key]) is not bool:
            raise ValueError('Member failure state must be boolean')
    if not record['fallback'] and record.get('raw_prediction') != record['prediction']:
        raise ValueError('Member is not raw')


def verify_inventory(directory, rows):
    if directory.is_symlink() or directory.resolve() != directory or not directory.is_dir():
        raise ValueError('Unsafe record directory')
    if {p.name for p in directory.iterdir()} != {artifact(r) for r in rows}:
        raise ValueError('Record inventory differs')


def load_c(reader, rows, reviewed):
    prefix = 'runs/development/C/'
    config = reader.json(prefix + 'run_config.json')
    selection = reader.json(SELECTION)
    status = reader.json(prefix + 'status.json')
    profile = selection.get('profiles', {}).get('nutrition5k', {})
    if (status.get('status') != 'completed' or config.get('name') != 'C'
            or config.get('code_sha256') != reviewed.get('original_code_sha256')
            or config.get('manifest_sha256') != fingerprint(rows)
            or config.get('protocol_sha256') != reviewed['protocol_sha256']
            or config.get('config') != profile.get('config') or profile.get('name') != 'C'):
        raise ValueError('Raw C reviewed binding or completion differs')
    reader.bytes('data/vectors/manifest.json')
    if config.get('vector_sha256') != reader.hashes['data/vectors/manifest.json']:
        raise ValueError('Raw C vector binding differs')
    seal = reader.json(prefix + 'records_sealed.json')
    if set(seal) != {r['sample_id'] for r in rows}:
        raise ValueError('Raw C external seal population differs')
    verify_inventory(ROOT / prefix / 'records', rows)
    records = []
    for row in rows:
        name = prefix + 'records/' + artifact(row)
        raw = reader.bytes(name)
        if reader.hashes[name] != seal[row['sample_id']]:
            raise ValueError('Raw C record external seal differs')
        record = decode(raw)
        validate_record(row, record)
        if record.get('prediction') != record.get('raw_prediction'):
            raise ValueError('C must retain its complete-population raw vector')
        records.append(record)
    saved = reader.json(prefix + 'predictions.json')
    if metrics._index(saved, 'C aggregate') != {r['sample_id']: r for r in records}:
        raise ValueError('Raw C aggregate differs from sealed records')
    return records, seal


def validate_assignments(rows, assignments, binding):
    index = {r['sample_id']: r for r in rows}
    if set(assignments) != set(index) or binding.get('example_assignments_sha256') != fingerprint(assignments):
        raise ValueError('Member assignment population or binding differs')
    proofs = binding.get('fold_catalog_proofs', {})
    if set(proofs) != {str(f) for f in range(5)}:
        raise ValueError('Training catalog folds differ')
    for fold in range(5):
        proof = proofs[str(fold)]
        if (proof.get('heldout_fold') != fold
                or proof.get('catalog_file_sha256') != binding['input_sha256'].get(f'round3/data/train_catalogs/fold_{fold}.json')
                or proof.get('training_group_count') != len({r['group_id'] for r in rows if r['fold'] != fold})):
            raise ValueError('Training catalog isolation proof differs')
    for row in rows:
        value = assignments[row['sample_id']]
        examples = value.get('examples', [])
        if (value.get('query_group_id') != row['group_id'] or value.get('query_fold') != row['fold']
                or value.get('query_image_sha256') != row['image_sha256']
                or value.get('catalog_sha256') != proofs[str(row['fold'])]['inference_catalog_sha256']
                or len(examples) != 4 or len({e.get('sample_id') for e in examples}) != 4
                or len({e.get('group_id') for e in examples}) != 4):
            raise ValueError('Member query/example binding differs')
        for example in examples:
            source = index.get(example.get('sample_id'))
            if (source is None or any(example.get(k) != source[k] for k in ('sample_id', 'group_id', 'fold', 'image_sha256'))
                    or source['fold'] == row['fold'] or source['group_id'] == row['group_id']):
                raise ValueError('Member example fold/group leakage')


def load_member(reader, rows, candidate, expected_sources):
    prefix = 'round3/runs/' + candidate + '/'
    completion = reader.json(prefix + 'completion.json')
    binding = reader.json(prefix + 'binding.json')
    if (completion.get('candidate') != candidate or completion.get('n') != 84
            or completion.get('groups') != 78 or completion.get('validation_opened') is not False
            or completion.get('binding_sha256') != fingerprint(binding)
            or set(completion.get('artifact_sha256', {})) != set(MEMBER_FINAL)
            or binding.get('candidate') != candidate or binding.get('scope') != 'development_only'
            or binding.get('validation_access') is not False or binding.get('example_count') != 4
            or binding.get('manifest_sha256') != fingerprint(rows)
            or binding.get('calibration') != 'none'
            or set(binding.get('input_sha256', {})) != expected_sources):
        raise ValueError('Member completion/binding/source inventory differs')
    for name in sorted(expected_sources):
        reader.bytes(name)
        if reader.hashes[name] != binding['input_sha256'][name]:
            raise ValueError('Member as-run source or development data changed')
    for name in MEMBER_FINAL:
        reader.bytes(prefix + name)
        if reader.hashes[prefix + name] != completion['artifact_sha256'][name]:
            raise ValueError('Member completed artifact hash differs')
    assignments = reader.json(prefix + 'example_assignments.json')
    validate_assignments(rows, assignments, binding)
    seal = reader.json(prefix + 'records_sealed.json')
    if set(seal) != {r['sample_id'] for r in rows}:
        raise ValueError('Member external seal population differs')
    verify_inventory(ROOT / prefix / 'records', rows)
    records = []
    for row in rows:
        name = prefix + 'records/' + artifact(row)
        raw = reader.bytes(name)
        if reader.hashes[name] != seal[row['sample_id']]:
            raise ValueError('Member record external seal differs')
        envelope = decode(raw)
        if set(envelope) != {'binding_sha256', 'record_sha256', 'record'}:
            raise ValueError('Member record envelope differs')
        record = envelope['record']
        if (envelope['binding_sha256'] != fingerprint(binding)
                or envelope['record_sha256'] != fingerprint(record)
                or record.get('example_assignment_sha256') != fingerprint(assignments[row['sample_id']])
                or record.get('example_proof') != assignments[row['sample_id']]):
            raise ValueError('Member record/assignment checksum differs')
        validate_record(row, record)
        records.append(record)
    saved = reader.json(prefix + 'predictions.json')
    if metrics._index(saved, candidate + ' aggregate') != {r['sample_id']: r for r in records}:
        raise ValueError('Member aggregate differs from sealed records')
    return records, seal, assignments


def prepare_context():
    reader = Reader()
    all_rows = [decode(line) for line in reader.bytes(MANIFEST).splitlines() if line]
    rows, asa_rows = population(all_rows)
    h_sources, i_sources = source_sets(rows)
    reader.allowed |= h_sources | i_sources | {PROTOCOL, SELF, 'runs/development/C/status.json'}
    reader.allowed |= {'round3/runs/I/' + name for name in (*MEMBER_FINAL, 'completion.json')}
    reader.allowed |= {'round3/runs/I/records/' + artifact(r) for r in rows}
    reviewed = verify_review(reader)
    c, c_seal = load_c(reader, rows, reviewed)
    h, h_seal, h_assignments = load_member(reader, rows, 'H', h_sources)
    i, i_seal, i_assignments = load_member(reader, rows, 'I', i_sources)
    if h_assignments != i_assignments:
        raise ValueError('H/I fixed gallery assignments differ')
    fixed = reader.json(SELECTED)
    metrics._index(fixed, 'preserved predictions')
    asa = [p for p in fixed if p.get('dataset') == 'asa24']
    if set(metrics._index(asa, 'ASA predictions')) != {r['sample_id'] for r in asa_rows}:
        raise ValueError('Preserved 99-row ASA population differs')
    for name in (PROTOCOL, SELF):
        reader.bytes(name)
    reader.unchanged()
    return {'reader': reader, 'all_rows': all_rows, 'rows': rows, 'asa_predictions': asa,
            'members': {'C': c, 'H': h, 'I': i}, 'member_seals': {'C': c_seal, 'H': h_seal, 'I': i_seal}}


def combine(rows, members, seals, method):
    """Pure arithmetic: labels and catalogs cannot enter this interface."""
    if method not in METHODS:
        raise ValueError('Unregistered combiner')
    indices = {name: metrics._index(members[name], name) for name in METHODS[method]}
    ids = {r['sample_id'] for r in rows}
    if any(set(index) != ids or set(seals[name]) != ids for name, index in indices.items()):
        raise ValueError('Combiner member population differs')
    out = []
    for row in rows:
        sid = row['sample_id']
        quantities, states = {}, {}
        for name, index in indices.items():
            record = index[sid]
            validate_record(row, record)
            quantities[name] = metrics._vector(record['prediction'], name)
            states[name] = {k: deepcopy(record.get(k)) for k in (
                'fallback', 'fallback_reason', 'native_complete', 'repair_used', 'repaired', 'method_fallback')}
        values = {key: (math.fsum(v[key] / 2 for v in quantities.values()) if method == 'HI_mean'
                        else float(median(v[key] for v in quantities.values()))) for key in metrics.KEYS}
        values = metrics._vector(values, 'combined prediction')
        failed = any(s['fallback'] for s in states.values())
        repaired = any(s['repair_used'] or s['repaired'] for s in states.values())
        method_failed = any(s['method_fallback'] for s in states.values())
        out.append({**{k: row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')},
                    'method': method, 'prediction': values, 'raw_prediction': deepcopy(values),
                    'final_codes': [], 'primary_code': None, 'fallback': failed,
                    'fallback_reason': 'constituent_fallback_retained' if failed else None,
                    'repair_used': repaired, 'method_fallback': method_failed,
                    'native_complete': all(s['native_complete'] for s in states.values())
                                       and not (failed or repaired or method_failed),
                    'member_predictions': quantities, 'member_failure_states': states,
                    'member_record_sha256': {name: seals[name][sid] for name in indices}})
    return out


def make_binding(context, method):
    return {'candidate': method, 'scope': 'development_only_fixed_whole_vector_ensemble',
            'namespace': 'mae-v2-round3-ensemble-' + method,
            'members': list(METHODS[method]), 'calibration': 'none', 'fit_parameters': False,
            'manifest_sha256': fingerprint(context['rows']),
            'input_sha256': deepcopy(context['reader'].hashes),
            'prediction_source': 'raw_complete_population_members_with_fallbacks',
            'preserved_asa_sha256': fingerprint(context['asa_predictions']),
            'validation_access': False, 'new_api_calls': 0, 'bootstrap_replicates': BOOTSTRAP}


def verify_sealed(directory, rows, expected, records):
    """External seal is verified before accepting any self-checksum or resume."""
    seal = load(directory / 'records_sealed.json')
    if set(seal) != {r['sample_id'] for r in rows}:
        raise ValueError('Ensemble external seal population differs')
    verify_inventory(directory / 'records', rows)
    for row, record in zip(rows, records):
        path = directory / 'records' / artifact(row)
        if sha(path) != seal[row['sample_id']]:
            raise ValueError('Ensemble record external seal differs')
        envelope = load(path)
        if envelope != {'binding_sha256': fingerprint(expected),
                        'record_sha256': fingerprint(record), 'record': record}:
            raise ValueError('Ensemble record differs from fixed arithmetic')
    if load(directory / 'binding.json') != expected or load(directory / 'predictions.json') != records:
        raise ValueError('Ensemble binding or aggregate differs')


def seal_predictions(directory, rows, expected, records):
    if (directory / 'completion.json').exists() or (directory / 'records_sealed.json').exists():
        verify_sealed(directory, rows, expected, records)
        return
    write_once(directory / 'binding.json', expected)
    for row, record in zip(rows, records):
        write_once(directory / 'records' / artifact(row), {'binding_sha256': fingerprint(expected),
                   'record_sha256': fingerprint(record), 'record': record})
    verify_inventory(directory / 'records', rows)
    # Aggregate first, seal last: an interrupted pre-seal write can only be
    # resumed if deterministic recomputation matches every existing artifact.
    write_once(directory / 'predictions.json', records)
    write_once(directory / 'records_sealed.json', {r['sample_id']: sha(directory / 'records' / artifact(r)) for r in rows})
    verify_sealed(directory, rows, expected, records)


def verify_complete(directory, expected):
    complete = load(directory / 'completion.json')
    if (complete.get('candidate') != expected['candidate'] or complete.get('n') != 84
            or complete.get('groups') != 78 or complete.get('validation_opened') is not False
            or complete.get('binding_sha256') != fingerprint(expected)
            or set(complete.get('artifact_sha256', {})) != set(FINAL)):
        raise ValueError('Ensemble completion differs')
    if {p.name for p in directory.iterdir()} != {*FINAL, 'completion.json', 'records'}:
        raise ValueError('Completed ensemble inventory differs')
    for name, value in complete['artifact_sha256'].items():
        if sha(directory / name) != value:
            raise ValueError('Completed ensemble artifact changed')
    return load(directory / 'metrics.json')


def score(context, labels, records, method):
    metrics._training(context['all_rows'], labels)
    if set(labels) != {r['sample_id'] for r in context['all_rows']}:
        raise ValueError('Development labels must have exactly 183 registered rows')
    joint = metrics.evaluate(context['all_rows'], labels,
                             context['asa_predictions'] + records, bootstrap=BOOTSTRAP)
    members = METHODS[method]
    counts = {name: {field: sum(bool(p.get(field)) for p in context['members'][name])
                    for field in ('fallback', 'native_complete', 'repair_used', 'repaired', 'method_fallback')}
              for name in members}
    return {'scope': 'development_not_independent_validation', 'candidate': method,
            'nutrition5k': joint['datasets']['nutrition5k'], 'joint_metrics_with_preserved_asa': joint,
            'member_state_counts': counts, 'calibration_applied': False, 'validation_opened': False,
            'new_api_calls': 0, 'deployment_dependencies': ['raw_C_with_official_embeddings', 'H', 'I'],
            'completeness_definition': 'Any constituent fallback excludes a row from the complete subset; every row remains in primary scoring.'}


def comparison(results):
    values = []
    for order, method in enumerate(METHODS):
        result = results[method]
        checks = [c for c in result['joint_metrics_with_preserved_asa']['checks'] if c['dataset'] == 'nutrition5k']
        ratios = [c['value'] / c['threshold'] if c['value'] is not None else float('inf') for c in checks]
        worst, mean = max(ratios), math.fsum(ratios) / len(ratios)
        values.append({'candidate': method, 'passed_n5_checks': sum(c['pass'] for c in checks),
                       'passed_joint_checks': result['joint_metrics_with_preserved_asa']['passed_checks'],
                       'worst_ratio': worst if math.isfinite(worst) else None,
                       'mean_ratio': mean if math.isfinite(mean) else None, 'registration_index': order})
    ordered = sorted(values, key=lambda x: (float('inf') if x['worst_ratio'] is None else x['worst_ratio'],
                                            float('inf') if x['mean_ratio'] is None else x['mean_ratio'],
                                            x['registration_index']))
    return {'scope': 'two_preregistered_development_ensembles_only_not_formal_selection',
            'candidates': values, 'preferred_whole_method': ordered[0]['candidate'],
            'ranking': [v['candidate'] for v in ordered],
            'ranking_rule': 'N5 worst ratio, mean ratio, equal shared C/H/I upstream requests, registration order',
            'new_api_calls': 0, 'validation_opened': False}


def run():
    context = prepare_context()
    parent = ROOT / 'round3/runs/ensembles'
    if parent.is_symlink() or parent.resolve() != parent:
        raise ValueError('Unsafe ensemble directory')
    parent.mkdir(parents=True, exist_ok=True)
    lock = parent / '.lock'
    if lock.is_symlink():
        raise ValueError('Unsafe lock')
    if not lock.exists() and any((parent / method / 'completion.json').exists() for method in METHODS):
        raise ValueError('Completed ensemble lock is missing; do not recreate artifacts on resume')
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prepared = {}
        for method in METHODS:
            records = combine(context['rows'], context['members'], context['member_seals'], method)
            expected = make_binding(context, method)
            directory = parent / method
            seal_predictions(directory, context['rows'], expected, records)
            completed = verify_complete(directory, expected) if (directory / 'completion.json').exists() else None
            prepared[method] = records, expected, completed
        # This is the first point at which development target values are decoded.
        context['reader'].unchanged()
        context['reader'].labels_allowed = True
        labels = context['reader'].json(LABELS)
        results = {}
        for method, (records, expected, completed) in prepared.items():
            result = score(context, labels, records, method)
            context['reader'].unchanged()
            directory = parent / method
            if completed is not None:
                if completed != result:
                    raise ValueError('Completed metrics differ from offline recomputation')
            else:
                write_once(directory / 'metrics.json', result)
                write_once(directory / 'completion.json', {
                    'candidate': method, 'completed': datetime.now(timezone.utc).isoformat(),
                    'n': 84, 'groups': 78, 'binding_sha256': fingerprint(expected),
                    'artifact_sha256': {name: sha(directory / name) for name in FINAL},
                    'validation_opened': False, 'new_api_calls': 0})
            results[method] = result
        summary = comparison(results)
        write_once(parent / 'comparison.json', summary)
        context['reader'].unchanged()
        return summary


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(run(), ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
