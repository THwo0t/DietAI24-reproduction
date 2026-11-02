#!/usr/bin/env python3
"""Resumable development-only independent visual nutrient candidate."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import sys
import threading

sys.dont_write_bytecode = True
ROUND = Path(__file__).resolve().parents[1]
ROOT = ROUND.parent
sys.path.insert(0, str(ROOT / 'src'))
from opt_provider import Provider, ProviderStop, atomic_json, fingerprint, sha, stamp, usage
import opt_metrics as metrics
import study
from direct_estimator import infer


def load(path):
    return json.loads(Path(path).read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def event(**value):
    print(json.dumps(value, allow_nan=False), flush=True)


def binding(rows):
    return {'candidate': 'F', 'scope': 'development_only',
        'model': 'gpt-6.1-sol', 'temperature': 1, 'max_completion_tokens': 8192,
        'protocol_sha256': sha(ROUND / 'PROTOCOL.md'),
        'source_sha256': {**study.source_hashes(),
            'round3/run_round3.py': sha(Path(__file__)),
            'round3/direct_estimator.py': sha(ROUND / 'src/direct_estimator.py')},
        'dev_freeze_sha256': sha(ROOT / 'data/cohorts/dev_freeze.json'),
        'manifest_sha256': fingerprint(rows),
        'validation_access': False}


def bind_once(directory, expected):
    path = directory / 'binding.json'
    if path.exists():
        if load(path) != expected:
            raise ValueError('Round source or cohort drift; preserve existing results')
    else:
        atomic_json(path, expected)


def record_path(directory, row):
    return directory / 'records' / study.artifact(row)


def read_record(directory, row, expected):
    envelope = load(record_path(directory, row))
    record = envelope['record']
    if (envelope.get('binding_sha256') != fingerprint(expected)
            or envelope.get('record_sha256') != fingerprint(record)
            or any(record.get(k) != row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold'))):
        raise ValueError('Saved result identity or checksum differs')
    return record


def prediction_record(row, answer, fallback):
    raw = answer['prediction']
    failed = raw is None
    result = {k: row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')}
    result.update({'prediction': deepcopy(fallback if failed else raw),
        'raw_prediction': deepcopy(raw), 'fallback': failed,
        'fallback_reason': answer['failure'] if failed else None,
        'native_complete': not failed and not answer['repair_used'],
        'repair_used': answer['repair_used'], 'final_codes': [], 'primary_code': None,
        'items': answer.get('items', []), 'raw_outputs': answer['raw_outputs'],
        'audit': answer.get('audit', {}), 'method': 'F_direct_visual_nutrients'})
    return result


def score(rows, labels, records, all_rows):
    n5_metrics = metrics.evaluate(rows, labels, records)
    # Keep the already selected ASA branch exactly as recorded; never rerun it.
    fixed = load(ROOT / 'runs/development/selected_oof_predictions.json')
    asa = [p for p in fixed if p['dataset'] == 'asa24']
    joint = metrics.evaluate(all_rows, labels, asa + records)
    return {'scope': 'development_not_independent_validation', 'candidate': 'F',
        'nutrition5k': n5_metrics['datasets']['nutrition5k'],
        'joint_metrics_with_preserved_asa': joint,
        'selected_C_reference': load(ROOT / 'runs/development/selection.json')['metrics']['datasets']['nutrition5k'],
        'validation_opened': False}


def run(*, allow_paid=False, workers=4, evaluate_only=False):
    if not 1 <= workers <= 4:
        raise ValueError('Use one through four workers')
    directory = ROUND / 'runs/F'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.job.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        all_rows, labels, _ = study.dev_inputs()  # verified development files only
        rows = [r for r in all_rows if r['dataset'] == 'nutrition5k']
        if len(rows) != 84 or len({r['group_id'] for r in rows}) != 78:
            raise ValueError('Registered development population differs')
        expected = binding(rows)
        bind_once(directory, expected)
        pending = []
        for row in rows:
            if record_path(directory, row).exists():
                read_record(directory, row, expected)
            else:
                pending.append(row)
        if pending and evaluate_only:
            raise ValueError('Full registered prediction population is incomplete')
        if pending:
            provider = Provider(directory, allow_paid=allow_paid, namespace='mae-v2-round3-F')
            stop = threading.Event()
            fallbacks = {fold: metrics.fold_medians(rows, labels, fold) for fold in {r['fold'] for r in rows}}

            def worker(row):
                if stop.is_set():
                    return None
                # Only pixels reach infer: no labels, row metadata or previous prediction.
                answer = infer(provider, ROOT / row['image_path'])
                record = prediction_record(row, answer, fallbacks[row['fold']])
                atomic_json(record_path(directory, row), {'binding_sha256': fingerprint(expected),
                    'record': record, 'record_sha256': fingerprint(record)})
                return record

            completed = len(rows) - len(pending)
            try:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(worker, row) for row in pending]
                    try:
                        for future in as_completed(futures):
                            record = future.result()
                            if record is not None:
                                completed += 1
                                event(candidate='F', completed=completed, total=len(rows),
                                      fallback=record['fallback'])
                    except BaseException:
                        stop.set()
                        for future in futures:
                            future.cancel()
                        raise
            finally:
                provider.close()
                atomic_json(directory / 'usage.json', usage(directory))
        final_rows, final_labels, _ = study.dev_inputs()
        if final_rows != all_rows or final_labels != labels or binding(rows) != expected:
            raise ValueError('Source changed during inference; retained but unscored')
        records = [read_record(directory, r, expected) for r in rows]
        atomic_json(directory / 'records_sealed.json', {r['sample_id']: sha(record_path(directory, r)) for r in rows})
        atomic_json(directory / 'predictions.json', records)
        result = score(rows, labels, records, all_rows)
        atomic_json(directory / 'metrics.json', result)
        atomic_json(directory / 'completion.json', {'completed': stamp(), 'n': len(rows),
            'groups': len({r['group_id'] for r in rows}), 'binding_sha256': fingerprint(expected),
            'validation_opened': False})
        event(candidate='F', status='completed',
            metrics=result['nutrition5k']['primary']['metrics'], validation_opened=False)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--evaluate-only', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    try:
        run(allow_paid=args.allow_paid, workers=args.workers, evaluate_only=args.evaluate_only)
    except ProviderStop:
        event(status='provider_stopped', resume_retained=True)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
