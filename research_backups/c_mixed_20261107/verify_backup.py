#!/usr/bin/env python3
"""Verify the public export using only the Python standard library."""

import csv
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
TARGETS = {'weight', 'energy', 'fat', 'carbs', 'protein'}
PROFILES = {'ASA': 529, 'N5': 314}
RECORD_FIELDS = {
    'dataset', 'fold', 'prediction', 'raw_prediction', 'native_complete',
    'fallback', 'fallback_reason', 'repair_used', 'method_fallback', 'mass_factor',
    'sample_id', 'group_id', 'conditional', 'e2e',
}
BRANCH_FIELDS = {
    'prediction', 'continuous_grams', 'fallback', 'fallback_reason', 'calibration_factor',
}
CREDENTIAL_PATTERN = re.compile(
    rb'\b(?:sk-(?:proj-)?[\w-]{20,}|AIza[\w-]{35}|'
    rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[\w]{40,}|'
    rb'(?:AKIA|ASIA)[A-Z0-9]{16}|xox[baprs]-[\w-]{20,})\b'
    rb'|-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----'
)
RESULT_PRIVATE_PATTERN = re.compile(
    rb'/home/|/tmp/|/mnt/|/run/user/|data:image/|'
    rb'asa24-[0-9]{8}-|nutrition5k-dish_'
)


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def read(path):
    return json.loads((ROOT / path).read_text())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def vector(value):
    return (
        isinstance(value, dict) and set(value) == TARGETS
        and all(type(v) in (int, float) and isfinite(v) and v >= 0 for v in value.values())
    )


def verify_inventory(manifest):
    entries = {entry['path']: entry for entry in manifest['files']}
    require(len(entries) == len(manifest['files']), 'duplicate inventory entry')
    paths = list(ROOT.rglob('*'))
    require(not any(path.is_symlink() for path in paths), 'symlink in backup')
    actual = {path.relative_to(ROOT).as_posix() for path in paths if path.is_file()}
    require(actual == entries.keys() | {'BACKUP_MANIFEST.json'}, 'inventory mismatch')
    for name, entry in entries.items():
        path = ROOT / name
        require(path.stat().st_size == entry['bytes'] and digest(path) == entry['sha256'],
                f'file checksum mismatch in {name}')
    files = [ROOT / name for name in actual]
    hits = sum(bool(CREDENTIAL_PATTERN.search(path.read_bytes())) for path in files)
    require(hits == 0, f'credential pattern matched {hits} files')
    private = sum(bool(RESULT_PRIVATE_PATTERN.search(path.read_bytes()))
                  for path in files if path.relative_to(ROOT).parts[0] == 'results')
    require(private == 0, f'private result pattern matched {private} files')
    allowed_suffixes = {'.py', '.txt', '.json', '.csv', '.md'}
    require(all(path.suffix in allowed_suffixes and not path.name.startswith('.')
                for path in files), 'unexpected file type')
    return len(files), sum(path.stat().st_size for path in files), hits, private


def verify_frozen_sources(summary, manifest):
    freeze = read('results/freeze.json')
    canonical = json.dumps(freeze, sort_keys=True, ensure_ascii=False,
                           allow_nan=False, separators=(',', ':')).encode()
    frozen = sha256(canonical).hexdigest()
    require(frozen == summary['freeze_sha256'], 'historical freeze binding mismatch')
    expected = {k: v for k, v in freeze['files'].items() if k.endswith('.py')}
    actual = {item['path'].removeprefix('source/') for item in manifest['files']
              if item['path'].startswith('source/') and item['path'].endswith('.py')}
    require(len(expected) == 28 and actual == expected.keys(), 'frozen source inventory mismatch')
    for name, checksum in expected.items():
        require(digest(ROOT / 'source' / name) == checksum, f'frozen source mismatch in {name}')
    require(freeze['models']['stages'] == {
        'recognition': 'gemini-3.8-flash', 'selection': 'gemini-3.8-flash',
        'portion': {'nutrition5k': 'gemini-3.8-flash', 'asa24': 'gpt-6.1-sol'},
    }, 'stage routes mismatch')
    return frozen, len(expected)


def verify_prediction(profile, row):
    require(row.keys() <= RECORD_FIELDS, 'unexpected prediction field')
    require(re.fullmatch(profile + r'-[0-9]{4}', row['sample_id']), 'sample alias invalid')
    require(re.fullmatch(profile + r'-group-[0-9]{3}', row['group_id']), 'group alias invalid')
    require(vector(row['prediction']), 'invalid prediction')
    require(row['raw_prediction'] is None or vector(row['raw_prediction']), 'invalid raw prediction')
    for key in ('conditional', 'e2e'):
        data = row[key]
        require(data is None or (data.keys() <= BRANCH_FIELDS and vector(data['prediction'])),
                'invalid branch prediction')


def verify_predictions(frozen):
    all_rows = {}
    original = read('results/independent_metric_check.json')['source_sha256']
    for profile, count in PROFILES.items():
        base = 'results/run/' + profile
        raw = read(base + '/records.json')
        cal = read('results/' + profile + '_calibrated_oof.json')
        require(len(raw) == len(cal['predictions']) == count, 'prediction count mismatch')
        ids = {row['sample_id']: row for row in raw}
        require(len(ids) == count and ids.keys() == {r['sample_id'] for r in cal['predictions']},
                'prediction identity mismatch')
        for row in raw + cal['predictions']:
            verify_prediction(profile, row)
        for row in cal['predictions']:
            base_row = ids[row['sample_id']]
            require(all(row[key] == base_row[key] for key in ('group_id', 'fold', 'raw_prediction')),
                    'historical raw field mismatch')
        for fold in cal['fold_parameters']:
            require(not set(fold['training_groups']) & set(fold['heldout_groups']),
                    'fold training and holdout groups overlap')
            heldout = {key for key, row in ids.items() if row['fold'] == fold['fold']}
            require(set(fold['heldout_ids']) == heldout and not set(fold['training_ids']) & heldout,
                    'fold training and holdout IDs mismatch')
        complete = read(base + '/completion.json')
        require(complete['records'] == count and complete['freeze_sha256'] == frozen,
                'historical completion binding mismatch')
        require(complete['records_sha256'] == original[f'run/{profile}/records.json'],
                'historical record digests disagree')
        all_rows[profile] = ids
    require(sum(row['conditional'] is not None for row in all_rows['ASA'].values()) == 176,
            'ASA conditional count mismatch')
    return all_rows


def verify_summaries(summary, all_rows):
    checks = {}
    for profile, data in summary['profiles'].items():
        for item in data['checks']:
            checks[profile, item['dataset'], item['target'], item['statistic']] = item
    with (ROOT / 'results/results.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            for key in ('mae', 'per_unit'):
                check = checks.pop((row['profile'], row['dataset'], row['target'], key))
                require(float(row[key]) == check['value']
                        and float(row[key + '_limit']) == check['threshold']
                        and (row['pass_' + key] == 'True') == check['pass'],
                        'CSV and summary disagree')
    require(not checks, 'CSV omitted summary checks')
    require(read('results/comparison.json')['summaries']['new'] == summary, 'comparison summary mismatch')

    raw = summary['profiles']['raw']['datasets']['nutrition5k']
    result = read('results/n5_313_no_fallback/results.json')
    failures = read('results/n5_313_no_fallback/failed_records.json')
    require(failures == result['failures'] and len(failures) == result['failed_n'] == 1,
            'failure count mismatch')
    n5 = all_rows['N5']
    scored = {key for key, row in n5.items() if row['raw_prediction'] is not None}
    require(len(scored) == result['scored_n'] == 313 and len(n5) == result['population_n'] == 314,
            'N5 recomputation population mismatch')
    require(set(result['scored_ids']) == scored and {r['sample_id'] for r in failures} == n5.keys() - scored,
            'N5 recomputation IDs mismatch')
    require(not result['correction_applied'] and not result['fallback_imputation_applied'],
            'N5 recomputation includes correction or imputation')
    for key, new in result['metrics'].items():
        for statistic in ('mae', 'per_unit', 'reference_mean'):
            require(isclose(new[statistic], raw['complete_subset']['metrics'][key][statistic],
                            rel_tol=0, abs_tol=2e-13), 'N5 complete subset statistic mismatch')
            require(isclose(result['historical_314_with_imputation'][key][statistic],
                            raw['primary']['metrics'][key][statistic], rel_tol=0, abs_tol=2e-13),
                    'N5 historical statistic mismatch')
        require(isclose(new['mae'], new['absolute_error_sum'] / 313, rel_tol=1e-14)
                and isclose(new['per_unit'], new['absolute_error_sum'] / new['reference_sum'],
                            rel_tol=1e-14),
                'N5 recomputation arithmetic mismatch')


def main():
    manifest = read('BACKUP_MANIFEST.json')
    files, size, hits, private = verify_inventory(manifest)
    summary = read('results/summary.json')
    frozen, source_count = verify_frozen_sources(summary, manifest)
    rows = verify_predictions(frozen)
    verify_summaries(summary, rows)
    print(json.dumps({
        'status': 'PASS', 'files': files, 'bytes': size, 'frozen_sources': source_count,
        'records': sum(map(len, rows.values())), 'N5_scored_no_fallback': 313,
        'credential_pattern_matched_files': hits, 'private_result_pattern_matched_files': private,
        'external_api_calls': 0,
    }))


if __name__ == '__main__':
    main()
