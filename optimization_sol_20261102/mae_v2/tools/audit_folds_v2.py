#!/usr/bin/env python3
"""R-M2-2-1: read-only audit of both executed development fold policies.

ASA24 retained v1 folds; Nutrition5k used the registered v2 seed. This tool
compares assignment metadata only. It does not create a replacement manifest,
fit parameters, calculate predictions or scores, or open labels/images/validation.
--write-evidence saves only aggregate counts and hashes, without row identities.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 'dietai24-mae-v2-20261102'
DATASETS = ('asa24', 'nutrition5k')
EVIDENCE = 'evidence/R-M2-2-1_fold_audit.json'
# Explicit originals whose bytes must remain unchanged during the audit. Files
# containing predictions are hashed without parsing or emitting their contents.
ORIGINALS = {
    'registered_protocol': 'PROTOCOL.md',
    'development_manifest': 'data/cohorts/dev.jsonl',
    'development_freeze': 'data/cohorts/dev_freeze.json',
    'completion': 'runs/development/completion.json',
    'selection': 'runs/development/selection.json',
    'selected_oof_predictions': 'runs/development/selected_oof_predictions.json',
    'asa_raw_predictions': 'runs/development/asa-retrieval-portion/predictions.json',
    'asa_raw_oof_predictions': 'runs/development/asa-retrieval-portion/oof_predictions.json',
    'asa_raw_fold_parameters': 'runs/development/asa-retrieval-portion/fold_parameters.json',
    'asa_calibration': 'runs/development/asa-retrieval-portion/calibration-asa.json',
    'asa_raw_record_seal': 'runs/development/asa-retrieval-portion/records_sealed.json',
    'asa_run_binding': 'runs/development/asa-retrieval-portion/run_config.json',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def safe_file(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Unexpected audit path')
    for item in (path, *path.parents):
        if item == root:
            break
        if item.is_symlink():
            raise ValueError('Audit input uses a symlink')
    if not path.is_file():
        raise ValueError('Required audit input is missing')
    return path


def registered_folds(groups):
    groups = set(groups)
    if len(groups) < 5 or any(not isinstance(group, str) or not group for group in groups):
        raise ValueError('At least five nonempty development groups are required')
    ordered = sorted(groups, key=lambda group: (sha((SEED + '|fold|' + group).encode()), group))
    return {group: index % 5 for index, group in enumerate(ordered)}


def _validate(rows, datasets=DATASETS):
    seen, groups = set(), {}
    for row in rows:
        if (row.get('split') != 'dev' or row.get('dataset') not in datasets
                or not isinstance(row.get('sample_id'), str) or not row['sample_id']
                or row['sample_id'] in seen or not isinstance(row.get('group_id'), str) or not row['group_id']
                or type(row.get('fold')) is not int or row['fold'] not in range(5)):
            raise ValueError('Invalid development assignment metadata')
        seen.add(row['sample_id'])
        key = (row['dataset'], row['group_id'])
        if key in groups and groups[key] != row['fold']:
            raise ValueError('A development group spans folds')
        groups[key] = row['fold']
    if any(len({r['group_id'] for r in rows if r['dataset'] == dataset}) < 5 for dataset in datasets):
        raise ValueError('Both development datasets require at least five groups')


def compare_assignments(rows, legacy_rows):
    """Return aggregate deviations, never a row-level derived cohort."""
    _validate(rows)
    legacy = [r for r in legacy_rows if r.get('dataset') == 'asa24']
    _validate(legacy, ('asa24',))
    old = {r['sample_id']: r for r in legacy}
    asa = [r for r in rows if r['dataset'] == 'asa24']
    if set(old) != {r['sample_id'] for r in asa} or any(
            (old[r['sample_id']]['group_id'], old[r['sample_id']]['fold']) != (r['group_id'], r['fold'])
            for r in asa):
        raise ValueError('ASA24 no longer matches its archived v1 groups and folds')
    result = {}
    for dataset in DATASETS:
        subset = [r for r in rows if r['dataset'] == dataset]
        actual = {r['group_id']: r['fold'] for r in subset}
        expected = registered_folds(actual)
        mismatch = {group for group in actual if actual[group] != expected[group]}
        if dataset == 'nutrition5k' and mismatch:
            raise ValueError('Nutrition5k does not follow the registered v2 seed')
        group_counts, image_counts = Counter(actual.values()), Counter(r['fold'] for r in subset)
        result[dataset] = {
            'images': len(subset), 'groups': len(actual),
            'as_run_policy': 'retained_v1_groups_and_folds' if dataset == 'asa24' else 'registered_v2_seed',
            'as_run_policy_verified': True,
            'registered_seed_mismatch_groups': len(mismatch),
            'registered_seed_mismatch_images': sum(r['group_id'] in mismatch for r in subset),
            'registered_seed_matches': not mismatch,
            'as_run_assignment_sha256': sha(canonical(sorted(
                (r['sample_id'], r['group_id'], r['fold']) for r in subset))),
            'as_run_fold_counts': [{'fold': fold, 'groups': group_counts[fold], 'images': image_counts[fold]}
                                   for fold in range(5)],
        }
    return result


def audit(root=ROOT, v1_root=None):
    root = Path(root).resolve()
    v1_root = Path(v1_root or root.parent).resolve()
    payloads = {alias: safe_file(root, relative).read_bytes() for alias, relative in ORIGINALS.items()}
    old_path = safe_file(v1_root, 'data/cohorts/dev.jsonl')
    old_bytes = old_path.read_bytes()
    before = {alias: sha(data) for alias, data in payloads.items()}
    freeze = json.loads(payloads['development_freeze'])
    if (freeze.get('seed') != SEED
            or freeze.get('artifacts', {}).get('data/cohorts/dev.jsonl') != before['development_manifest']):
        raise ValueError('The development manifest differs from its original freeze')
    binding = json.loads(payloads['asa_run_binding'])
    if binding.get('protocol_sha256') != before['registered_protocol']:
        raise ValueError('The protocol differs from the ASA as-run binding')
    rows = [json.loads(line) for line in payloads['development_manifest'].splitlines() if line.strip()]
    legacy = [json.loads(line) for line in old_bytes.splitlines() if line.strip()]
    summary = compare_assignments(rows, legacy)
    completion = json.loads(payloads['completion'])
    if (completion.get('status') not in ('ready_for_review', 'development_targets_not_met')
            or completion.get('active_development_rows') != len(rows)):
        raise ValueError('Development completion does not match the audited population')
    after = {alias: sha(safe_file(root, relative).read_bytes()) for alias, relative in ORIGINALS.items()}
    if before != after or sha(old_path.read_bytes()) != sha(old_bytes):
        raise ValueError('An original artifact changed during the audit')
    return {'schema_version': 1, 'review_id': 'R-M2-2-1',
        'status': 'VERIFIED_AS_RUN_WITH_REGISTERED_ASA_DEVIATION' if
                  summary['asa24']['registered_seed_mismatch_groups'] else 'VERIFIED_AS_RUN',
        'scope': 'development_assignment_metadata_only', 'registered_seed': SEED,
        'registered_rule': 'SHA256(seed|fold|group), group tie-break, sorted index modulo five; per dataset',
        'datasets': summary, 'original_artifact_sha256': before,
        'legacy_development_manifest_sha256': sha(old_bytes), 'original_artifacts_unchanged': True,
        'audit_source_sha256': sha(Path(__file__).read_bytes()),
        'prediction_or_metric_recomputation_performed': False,
        'replacement_manifest_created': False, 'selection_or_acceptance_result': False,
        'labels_read': False, 'images_read': False, 'validation_read': False, 'api_calls': 0}


def write_evidence(root, result):
    root = Path(root).resolve()
    target = root / EVIDENCE
    for path in (target, target.parent):
        if path.is_symlink():
            raise ValueError('Evidence cannot use a symlink')
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if target.exists():
        if target.read_text() != payload:
            raise ValueError('Existing fold evidence differs; no overwrite allowed')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x') as handle:
        handle.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-evidence', action='store_true')
    args = parser.parse_args()
    try:
        result = audit()
        if args.write_evidence:
            write_evidence(ROOT, result)
    except Exception as error:
        result = {'status': 'STOPPED', 'error_type': type(error).__name__, 'api_calls': 0,
                  'notice': 'Fold provenance check failed; original artifacts were not changed.'}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result['status'] == 'STOPPED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
