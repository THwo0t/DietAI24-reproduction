#!/usr/bin/env python3
"""Verify this exported backup without providers, credentials, or external data."""
from pathlib import Path
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parent
KEYS = ('weight', 'energy', 'fat', 'carbs', 'protein')

def read(name):
    return json.loads((ROOT / name).read_text())

def check_record(r):
    assert 'portion_result' not in r
    for b in ('e2e', 'conditional'):
        assert not isinstance(r.get(b), dict) or 'raw_result' not in r[b]
    assert all(isinstance(r['prediction'][k], (int, float)) and math.isfinite(r['prediction'][k]) and r['prediction'][k] >= 0 for k in KEYS)

def main():
    manifest = read('BACKUP_MANIFEST.json')
    for entry in manifest['files']:
        path = ROOT / entry['path']
        assert path.is_file() and not path.is_symlink(), entry['path']
        assert path.stat().st_size == entry['bytes'], entry['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], entry['path']
    expected = {e['path'] for e in manifest['files']} | {'BACKUP_MANIFEST.json'}
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()}
    assert actual == expected, sorted(actual ^ expected)
    for profile, size in [('N5', 314), ('ASA', 529)]:
        raw = read('results/run/' + profile + '/records.json')
        cal = read('results/' + profile + '_calibrated_oof.json')
        assert len(raw) == size and len(cal['predictions']) == size
        assert len({r['sample_id'] for r in raw}) == size
        assert {r['sample_id'] for r in raw} == {r['sample_id'] for r in cal['predictions']}
        for r in raw + cal['predictions']:
            check_record(r)
        for p in cal['fold_parameters']:
            assert not set(p['training_groups']) & set(p['heldout_groups'])
    summary = read('results/summary.json')
    assert summary['profiles']['retained']['passed_checks'] == 10
    print(json.dumps(dict(status='PASS', files=len(manifest['files']), development_predictions=843, external_api_calls=0)))

if __name__ == '__main__':
    main()
