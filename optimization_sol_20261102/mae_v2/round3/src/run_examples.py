#!/usr/bin/env python3
"""G: immutable, resumable four-example development experiment; no validation."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import fcntl
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

import numpy as np

sys.dont_write_bytecode = True
ROUND = Path(__file__).resolve().parents[1]
ROOT = ROUND.parent
sys.path.insert(0, str(ROOT / 'src'))
from opt_provider import Provider, ProviderStop, atomic_json, fingerprint, sha, stamp, usage
import opt_metrics as metrics
import study
from examples import select_examples
from example_estimator import infer

REVIEW = 'evidence/review-one-completion.json'
METRIC_REVIEW = 'evidence/R-M2-4-1.json'
TRUSTED_EVIDENCE = {
    REVIEW: 'd80987a08b81b6f1bb042260d78ee19053ad7140de5c18bb03eca6ecef1c8fce',
    METRIC_REVIEW: 'c742414a52f1b57a0bfe1273f973194736d28986210f067c4e28ef9f7096aa46',
}
ROUND_SOURCES = ('run_examples.py', 'examples.py', 'example_estimator.py', 'direct_estimator.py')
FINAL_FILES = ('records_sealed.json', 'predictions.json', 'metrics.json', 'usage.json',
               'binding.json', 'example_assignments.json')


def decode(raw):
    def pairs(values):
        result = {}
        for k, v in values:
            if k in result:
                raise ValueError('Duplicate JSON key')
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def safe_file(path):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('Expected a canonical regular file')
    return path


def load(path):
    return decode(safe_file(path).read_bytes())


def event(**value):
    print(json.dumps(value, allow_nan=False), flush=True)


def write_once(path, value):
    """Private, no-replace artifact creation; equal existing JSON is read-only."""
    path = Path(path)
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('Unsafe output path')
    if path.exists():
        if fingerprint(load(path)) != fingerprint(value):
            raise ValueError('Immutable artifact differs; preserve the original')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.G-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
        os.chmod(temporary, 0o600)
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Reader:
    def __init__(self):
        self.hashes = {}

    def bytes(self, relative):
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe input path')
        path = safe_file(ROOT / relative)
        raw = path.read_bytes()
        import hashlib
        value = hashlib.sha256(raw).hexdigest()
        name = relative.as_posix()
        if name in self.hashes and self.hashes[name] != value:
            raise ValueError('Source changed while preparing examples')
        self.hashes[name] = value
        return raw

    def json(self, relative):
        return decode(self.bytes(relative))

    def unchanged(self):
        if any(sha(safe_file(ROOT / name)) != value for name, value in self.hashes.items()):
            raise ValueError('Source changed while preparing examples')


def validate_population(all_rows, labels):
    metrics._training(all_rows, labels)
    rows = [r for r in all_rows if r['dataset'] == 'nutrition5k']
    asa = [r for r in all_rows if r['dataset'] == 'asa24']
    if (len(all_rows) != 183 or len(rows) != 84 or len(asa) != 99
            or len({r['group_id'] for r in rows}) != 78
            or len({r['group_id'] for r in asa}) != 23
            or {r['fold'] for r in rows} != set(range(5))
            or any(r.get('split') != 'dev' for r in all_rows)):
        raise ValueError('Registered 84/78 N5 and 99/23 ASA development population differs')
    return rows


def validate_review(reader, current_sources):
    reviewed, correction = reader.json(REVIEW), reader.json(METRIC_REVIEW)
    if any(reader.hashes[name] != value for name, value in TRUSTED_EVIDENCE.items()):
        raise ValueError('Trusted review evidence changed')
    if (reviewed.get('status') != 'approved_or_fixed'
            or type(reviewed.get('unresolved_p1_p2')) is not int or reviewed['unresolved_p1_p2'] != 0
            or reviewed.get('code_sha256') != current_sources
            or correction.get('finding') != 'R-M2-4-1'
            or correction.get('source_sha256_after') != current_sources['opt_metrics.py']
            or reviewed.get('evidence_sha256', {}).get('R-M2-4-1.json') != reader.hashes[METRIC_REVIEW]):
        raise ValueError('Reviewed source compatibility is not confirmed')
    proof = correction.get('actual_development_recalculation', {})
    if any(proof.get(key) is not True for key in (
            'complete_metrics_object_equals_checkpoint', 'complete_metrics_object_equals_saved_selection',
            'existing_structure_and_all_intervals_unchanged')):
        raise ValueError('Preserved metric equivalence is not confirmed')
    for name in ('data/cohorts/dev.jsonl', 'data/cohorts/dev_labels.json',
                 'data/cohorts/dev_freeze.json', 'runs/development/selected_oof_predictions.json',
                 'runs/development/selection.json'):
        reader.bytes(name)
        if reader.hashes[name] != correction.get('input_sha256', {}).get(name):
            raise ValueError('Reviewed development or preserved prediction source changed')
    for field, name in (('dev_freeze_sha256', 'data/cohorts/dev_freeze.json'),
                        ('selection_sha256', 'runs/development/selection.json'),
                        ('protocol_sha256', 'PROTOCOL.md'), ('catalog_sha256', 'data/catalog.json')):
        reader.bytes(name)
        if reviewed.get(field) != reader.hashes[name]:
            raise ValueError('Review artifact binding changed')
    return reviewed


def make_assignments(rows, labels, rawpreds, codes, vectors):
    index = {r['sample_id']: r for r in rows}
    assignments = {}
    for query in rows:
        ids = select_examples(rows, rawpreds, codes, vectors, query['sample_id'], count=4)
        if not isinstance(ids, list) or len(ids) != 4 or len(set(ids)) != 4 or any(i not in index for i in ids):
            raise ValueError('Exactly four distinct development examples are required')
        examples = [index[i] for i in ids]
        if (len({r['group_id'] for r in examples}) != 4
                or any(r['fold'] == query['fold'] or r['group_id'] == query['group_id'] for r in examples)):
            raise ValueError('Training example fold or group isolation failed')
        proof = []
        for r in examples:
            reference = metrics._vector(labels[r['sample_id']]['truth'], 'training example reference')
            proof.append({k: r[k] for k in ('sample_id', 'group_id', 'fold', 'image_sha256')})
            proof[-1]['reference_sha256'] = fingerprint(reference)
        assignments[query['sample_id']] = {
            'query_group_id': query['group_id'], 'query_fold': query['fold'],
            'query_image_sha256': query['image_sha256'], 'examples': proof}
    return assignments


def prepare_context(rows, labels):
    """Read only explicit development inputs; selection never receives labels."""
    reader = Reader()
    current = study.source_hashes()
    reviewed = validate_review(reader, current)
    selection = reader.json('runs/development/selection.json')
    fixed = reader.json('runs/development/selected_oof_predictions.json')
    asa = [p for p in fixed if p['dataset'] == 'asa24']
    cdir = 'runs/development/C/'
    config = reader.json(cdir + 'run_config.json')
    if (config.get('name') != 'C' or config.get('code_sha256') != reviewed.get('original_code_sha256')
            or config.get('manifest_sha256') != fingerprint(rows)
            or config.get('protocol_sha256') != reviewed['protocol_sha256']
            or fingerprint(config.get('config')) != fingerprint(selection['profiles']['nutrition5k']['config'])
            or selection['profiles']['nutrition5k']['name'] != 'C'):
        raise ValueError('Raw C reference binding differs from the reviewed selected route')
    seal = reader.json(cdir + 'records_sealed.json')
    if not isinstance(seal, dict) or set(seal) != {r['sample_id'] for r in rows}:
        raise ValueError('Raw C seal population differs')
    raw = []
    for row in rows:
        name = cdir + 'records/' + study.artifact(row)
        record = reader.json(name)
        if reader.hashes[name] != seal[row['sample_id']]:
            raise ValueError('Raw C record differs from its external seal')
        if any(record.get(k) != row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')):
            raise ValueError('Raw C record identity differs')
        raw.append(record)
    original_raw = reader.json(cdir + 'predictions.json')
    if (len(original_raw) != len(rows)
            or {p['sample_id']: p for p in original_raw} != {p['sample_id']: p for p in raw}
            or any(p.get('prediction') != p.get('raw_prediction') for p in raw)):
        raise ValueError('Raw C aggregate differs or contains calibrated features')
    vector_manifest = reader.json('data/vectors/manifest.json')
    if set(vector_manifest.get('files', {})) != {'embeddings.npy', 'codes.json', 'collection.json'}:
        raise ValueError('Frozen vector file inventory differs')
    vector_raw = {}
    for name, expected in vector_manifest['files'].items():
        relative = 'data/vectors/' + name
        vector_raw[name] = reader.bytes(relative)
        if reader.hashes[relative] != expected:
            raise ValueError('Frozen vector file checksum differs')
    codes = decode(vector_raw['codes.json'])
    vectors = np.load(io.BytesIO(vector_raw['embeddings.npy']), allow_pickle=False)
    if vectors.shape != (vector_manifest['vectors'], vector_manifest['dimensions']):
        raise ValueError('Frozen vector shape differs')
    if config.get('vector_sha256') != reader.hashes['data/vectors/manifest.json']:
        raise ValueError('C and G vector manifests differ')
    assignments = make_assignments(rows, labels, raw, codes, vectors)
    fmetrics = reader.json('round3/runs/F/metrics.json')
    fcompletion = reader.json('round3/runs/F/completion.json')
    reader.bytes('round3/runs/F/records_sealed.json')
    if (fmetrics.get('candidate') != 'F' or fmetrics.get('validation_opened') is not False
            or fcompletion.get('n') != 84 or fcompletion.get('groups') != 78
            or fcompletion.get('validation_opened') is not False
            or fmetrics['nutrition5k']['n'] != 84):
        raise ValueError('Completed F reference aggregate differs')
    faudit = reader.json('round3/evidence/F_audit.json')
    if (faudit.get('status') != 'PASS' or faudit.get('candidate') != 'F'
            or faudit.get('metrics_match') is not True
            or faudit.get('metrics_sha256') != fingerprint(fmetrics)
            or any(faudit.get('input_sha256', {}).get(name) != reader.hashes[name] for name in (
                'round3/runs/F/metrics.json', 'round3/runs/F/completion.json',
                'round3/runs/F/records_sealed.json'))):
        raise ValueError('F reference no longer matches its completed offline audit')
    reader.bytes('config/experiment.json')
    reader.bytes('config/candidates.json')
    for name in ROUND_SOURCES:
        reader.bytes('round3/src/' + name)
    reader.bytes('round3/G_PROTOCOL.md')
    for name in study.INFERENCE_FILES:
        reader.bytes('src/' + name)
        if reader.hashes['src/' + name] != current[name]:
            raise ValueError('Core source changed during preparation')
    reader.unchanged()
    return {'input_sha256': reader.hashes, 'source_sha256': current,
            'assignments': assignments, 'asa_predictions': asa,
            'selected_C_reference': selection['metrics']['datasets']['nutrition5k'],
            'raw_C_reference': metrics.evaluate(rows, labels, raw)['datasets']['nutrition5k'],
            'F_reference': fmetrics['nutrition5k']}


def binding(rows, context):
    return {'candidate': 'G', 'scope': 'development_only', 'model': 'gpt-6.1-sol',
            'route': 'zicc', 'temperature': 1, 'max_completion_tokens': 8192,
            'provider_namespace': 'mae-v2-round3-G', 'example_count': 4,
            'calibration': 'none', 'manifest_sha256': fingerprint(rows),
            'input_sha256': context['input_sha256'],
            'example_assignments_sha256': fingerprint(context['assignments']),
            'validation_access': False}


def record_path(directory, row):
    return directory / 'records' / study.artifact(row)


def read_record(directory, row, expected, assignment):
    envelope = load(record_path(directory, row))
    record = envelope['record']
    if (set(envelope) != {'binding_sha256', 'record_sha256', 'record'}
            or envelope['binding_sha256'] != fingerprint(expected)
            or envelope['record_sha256'] != fingerprint(record)
            or any(record.get(k) != row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold'))
            or record.get('example_assignment_sha256') != fingerprint(assignment)
            or fingerprint(record.get('example_proof')) != fingerprint(assignment)):
        raise ValueError('Saved G record identity, assignment or checksum differs')
    return record


def verify_external_seal(directory, rows):
    """Check external file hashes before trusting any in-record self-checksum."""
    seal = load(directory / 'records_sealed.json')
    if not isinstance(seal, dict) or set(seal) != {r['sample_id'] for r in rows}:
        raise ValueError('External G record seal population differs')
    names = {p.name for p in (directory / 'records').iterdir()}
    if names != {study.artifact(r) for r in rows}:
        raise ValueError('Completed record file inventory differs')
    for row in rows:
        if sha(safe_file(record_path(directory, row))) != seal[row['sample_id']]:
            raise ValueError('Record differs from external G seal')
    return seal


def prediction_record(row, answer, fallback, assignment):
    raw = answer['prediction']
    failed = raw is None
    record = {k: row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')}
    record.update({'prediction': deepcopy(fallback if failed else raw),
        'raw_prediction': deepcopy(raw), 'fallback': failed,
        'fallback_reason': answer['failure'] if failed else None,
        'native_complete': not failed and not answer['repair_used'],
        'repair_used': answer['repair_used'], 'final_codes': [], 'primary_code': None,
        'items': answer.get('items', []), 'raw_outputs': answer['raw_outputs'],
        'audit': answer.get('audit', {}), 'method': 'G_four_training_images_direct_nutrients',
        'example_assignment_sha256': fingerprint(assignment), 'example_proof': deepcopy(assignment)})
    return record


def example_inputs(query, assignment, rows_by_id, labels):
    """Narrow inference boundary: only support pixels and five support totals."""
    refs = assignment['examples']
    if len(refs) != 4 or len({r['group_id'] for r in refs}) != 4:
        raise ValueError('Four distinct example groups are required')
    out = []
    for proof in refs:
        row = rows_by_id[proof['sample_id']]
        if (row['fold'] == query['fold'] or row['group_id'] == query['group_id']
                or any(row[k] != proof[k] for k in ('group_id', 'fold', 'image_sha256'))):
            raise ValueError('Example isolation changed before inference')
        reference = metrics._vector(labels[row['sample_id']]['truth'], 'training example reference')
        if fingerprint(reference) != proof['reference_sha256']:
            raise ValueError('Example labels changed after binding')
        out.append({'image_path': ROOT / row['image_path'], 'reference': reference})
    return out


def score(rows, labels, records, all_rows, context):
    n5 = metrics.evaluate(rows, labels, records)
    joint = metrics.evaluate(all_rows, labels, context['asa_predictions'] + records)
    return {'scope': 'development_not_independent_validation', 'candidate': 'G',
            'nutrition5k': n5['datasets']['nutrition5k'],
            'joint_metrics_with_preserved_asa': joint,
            'selected_C_reference': context['selected_C_reference'],
            'raw_C_reference': context['raw_C_reference'], 'F_reference': context['F_reference'],
            'calibration_applied': False, 'validation_opened': False}


def verify_completed(directory, rows, labels, all_rows, expected, context):
    verify_external_seal(directory, rows)
    completion = load(directory / 'completion.json')
    if (completion.get('candidate') != 'G' or completion.get('n') != 84 or completion.get('groups') != 78
            or completion.get('binding_sha256') != fingerprint(expected)
            or completion.get('validation_opened') is not False
            or set(completion.get('artifact_sha256', {})) != set(FINAL_FILES)):
        raise ValueError('Completed G marker differs')
    for name, value in completion['artifact_sha256'].items():
        if sha(safe_file(directory / name)) != value:
            raise ValueError('Completed G artifact changed')
    records = [read_record(directory, r, expected, context['assignments'][r['sample_id']]) for r in rows]
    if fingerprint(load(directory / 'predictions.json')) != fingerprint(records):
        raise ValueError('Completed prediction aggregate differs from sealed records')
    result = score(rows, labels, records, all_rows, context)
    if fingerprint(load(directory / 'metrics.json')) != fingerprint(result):
        raise ValueError('Completed metrics differ from full-population recomputation')
    return result


def run(*, allow_paid=False, workers=4, evaluate_only=False):
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('Use one through four workers')
    directory = ROUND / 'runs/G'
    if directory.is_symlink() or directory.resolve() != directory:
        raise ValueError('Unsafe G run directory')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    completed_before = (directory / 'completion.json').exists()
    lock_path = directory / '.job.lock'
    with lock_path.open('rb' if completed_before else 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        all_rows, labels, _ = study.dev_inputs()
        rows = validate_population(all_rows, labels)
        context = prepare_context(rows, labels)
        expected = binding(rows, context)
        if completed_before or (directory / 'records_sealed.json').exists():
            # Never manufacture missing bindings or assignments for sealed data.
            if (fingerprint(load(directory / 'binding.json')) != fingerprint(expected)
                    or fingerprint(load(directory / 'example_assignments.json')) != fingerprint(context['assignments'])):
                raise ValueError('Sealed G source or example assignments changed')
            verify_external_seal(directory, rows)
        else:
            write_once(directory / 'binding.json', expected)
            write_once(directory / 'example_assignments.json', context['assignments'])
        if completed_before:
            guarded = {name: sha(safe_file(directory / name)) for name in (*FINAL_FILES, 'completion.json')}
            result = verify_completed(directory, rows, labels, all_rows, expected, context)
            final_rows, final_labels, _ = study.dev_inputs()
            if (final_rows != all_rows or final_labels != labels
                    or binding(rows, prepare_context(rows, labels)) != expected):
                raise ValueError('Inputs changed during completed G verification')
            verify_external_seal(directory, rows)
            if any(sha(safe_file(directory / name)) != value for name, value in guarded.items()):
                raise ValueError('Completed G artifacts changed during read-only verification')
            event(candidate='G', status='completed_verified_read_only', api_calls=0)
            return result
        pending = []
        for row in rows:
            if record_path(directory, row).exists():
                read_record(directory, row, expected, context['assignments'][row['sample_id']])
            else:
                pending.append(row)
        if pending and evaluate_only:
            raise ValueError('Full registered prediction population is incomplete')
        if pending:
            provider = Provider(directory, allow_paid=allow_paid, namespace='mae-v2-round3-G')
            stop = threading.Event()
            by_id = {r['sample_id']: r for r in rows}
            fallbacks = {fold: metrics.fold_medians(rows, labels, fold) for fold in range(5)}

            def worker(row):
                if stop.is_set():
                    return None
                try:
                    assignment = context['assignments'][row['sample_id']]
                    examples = example_inputs(row, assignment, by_id, labels)
                    answer = infer(provider, ROOT / row['image_path'], examples)
                    record = prediction_record(row, answer, fallbacks[row['fold']], assignment)
                    write_once(record_path(directory, row), {'binding_sha256': fingerprint(expected),
                        'record': record, 'record_sha256': fingerprint(record)})
                    return record
                except BaseException:
                    # Stop before this worker can dequeue another query; waiting
                    # for the coordinator leaves a scheduling race after faults.
                    stop.set()
                    raise

            completed = len(rows) - len(pending)
            try:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(worker, row) for row in pending]
                    try:
                        for future in as_completed(futures):
                            record = future.result()
                            if record is not None:
                                completed += 1
                                event(candidate='G', completed=completed, total=len(rows), fallback=record['fallback'])
                    except BaseException:
                        stop.set()
                        for future in futures:
                            future.cancel()
                        raise
            finally:
                provider.close()
                atomic_json(directory / 'usage.json', usage(directory))
        final_rows, final_labels, _ = study.dev_inputs()
        if (final_rows != all_rows or final_labels != labels
                or binding(rows, prepare_context(rows, labels)) != expected):
            raise ValueError('Source or development data changed; retained but unscored')
        records = [read_record(directory, r, expected, context['assignments'][r['sample_id']]) for r in rows]
        seal = {r['sample_id']: sha(record_path(directory, r)) for r in rows}
        write_once(directory / 'records_sealed.json', seal)
        verify_external_seal(directory, rows)
        write_once(directory / 'predictions.json', records)
        result = score(rows, labels, records, all_rows, context)
        write_once(directory / 'metrics.json', result)
        if not (directory / 'usage.json').exists():
            write_once(directory / 'usage.json', usage(directory))
        completion = {'candidate': 'G', 'completed': stamp(), 'n': len(rows),
            'groups': len({r['group_id'] for r in rows}), 'binding_sha256': fingerprint(expected),
            'artifact_sha256': {name: sha(safe_file(directory / name)) for name in FINAL_FILES},
            'validation_opened': False}
        write_once(directory / 'completion.json', completion)
        event(candidate='G', status='completed', metrics=result['nutrition5k']['primary']['metrics'], validation_opened=False)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--evaluate-only', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args(argv)
    try:
        run(allow_paid=args.allow_paid, workers=args.workers, evaluate_only=args.evaluate_only)
    except ProviderStop:
        event(candidate='G', status='provider_stopped', resume_retained=True)
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        event(candidate='G', status='integrity_or_configuration_failure', resume_retained=True)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
