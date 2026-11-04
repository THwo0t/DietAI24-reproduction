"""Direct development scoring, without repeated provenance/runner replay.

Reads only complete direct-run outputs and the fixed development cohort. Uses
the existing four-profile OOF scorer unchanged. No provider or acceptance set.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), *(str(BASE / p) for p in
    ('src', 'round7/src', 'round8/src', 'round10', 'round11'))]
from opt_provider import ROOT
import scoring_p

MODE = 'user_requested_direct_scoring_without_repeated_provenance_replay'


def _read(path):
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _complete_inputs(rows, records, identities, expected=843):
    """Cheap completeness/schema checks before opening development labels."""
    _require(type(rows) is list and len(rows) == expected, 'direct_complete_manifest_required')
    indexed = {row['sample_id']: row for row in rows}
    _require(len(indexed) == expected, 'direct_unique_manifest_required')
    _require(type(identities) is dict and set(identities) == set(indexed),
             'direct_complete_identities_required')
    if type(records) is dict:
        _require(set(records) == set(indexed), 'direct_complete_records_required')
        _require(all(record['row']['sample_id'] == key for key, record in records.items()),
                 'direct_record_keys_changed')
        records = list(records.values())
    _require(type(records) is list and len(records) == expected, 'direct_complete_records_required')
    by_id = {record['row']['sample_id']: record for record in records}
    _require(len(by_id) == expected and set(by_id) == set(indexed),
             'direct_unique_complete_records_required')
    for sid, row in indexed.items():
        record = by_id[sid]
        _require(record['row'] == row and set(record['profiles']) == set(scoring_p.PROFILES),
                 'direct_record_manifest_or_profiles_changed')
        identity = identities[sid]
        _require(type(identity) is dict, 'direct_identity_object_required')
        identity = identity.get('result', identity)
        _require(identity.get('status') in ('ok', 'failed') and
                 identity.get('final_codes') == record['coding']['final_codes'],
                 'direct_identity_record_codes_changed')
    return [by_id[row['sample_id']] for row in rows]


def _aggregate(scored, row_count):
    profiles = {}
    for profile, report in scored['profiles'].items():
        selected = report['selected']
        asa = selected['datasets']['asa24']
        recognition = {key: asa.get(key) for key in (
            'n', 'exact_n', 'exact_rate', 'first_n', 'first_rate',
            'exact_groups', 'retrieval_exact_n', 'retrieval_exact_rate', 'recognition_pass')}
        value = {'postprocessor': report['selected_postprocessor'],
                 'calibration_retained': report['calibration_retained'],
                 'checks': selected['checks'], 'passed_checks': selected['passed_checks'],
                 'total_checks': selected['total_checks'], 'decision': report['decision'],
                 'asa_recognition': recognition, 'conditional_success': report['conditional_success']}
        density = report.get('density_selected_primary_recognition')
        if density is not None:
            value['density_selected_primary_recognition'] = {
                key: density.get(key) for key in ('n', 'first_n', 'first_rate',
                    'available_n', 'unavailable_n', 'unavailable_rate',
                    'common_Exact_n', 'changed_primary_n')}
        profiles[profile] = value
    return {'mode': MODE, 'scope': scored['scope'], 'rows': row_count,
            'selected_profile': scored['selected_profile'],
            'gap_ranked_profile': scored['gap_ranked_profile'], 'profiles': profiles,
            'api_calls': 0, 'validation_opened': False,
            'independent_acceptance_success': False, 'bootstrap_replicates': 0}


def _write_private(path, value):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
            prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, sort_keys=True, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def _score_at(root, *, expected=843):
    directory = root / 'round11/direct_run'
    rows = _read(root / 'round11/prepared/cohort/dev.json')
    records = _complete_inputs(rows, _read(directory / 'records.json'),
                              _read(directory / 'identities.json'), expected)
    # Completeness above is the sole precondition; no source census, provider,
    # ledger replay, acceptance labels, or run_p verifier is invoked.
    labels = _read(root / 'round11/prepared/cohort/dev_labels.json')
    catalog = _read(root / 'round11/prepared/catalog.json')
    strata = _read(root / 'round11/prepared/cohort/source_closure.json')['strata_private']
    scored = scoring_p.score(rows, labels, records, catalog, strata=strata, bootstrap=0)
    private = {'mode': MODE, 'rows': len(rows), 'api_calls': 0,
               'validation_opened': False, 'bootstrap_replicates': 0, 'scoring': scored}
    summary = _aggregate(scored, len(rows))
    _write_private(directory / 'scoring.json', private)
    _write_private(directory / 'summary.json', summary)
    return summary


def run():
    return _score_at(ROOT)


if __name__ == '__main__':
    try:
        summary = run()
        print(json.dumps({'status': 'direct_development_scoring_complete',
            'mode': MODE, 'rows': summary['rows'],
            'selected_profile': summary['selected_profile'],
            'gap_ranked_profile': summary['gap_ranked_profile'], 'api_calls': 0,
            'validation_opened': False}, sort_keys=True), flush=True)
    except BaseException as error:
        print(json.dumps({'status': 'direct_development_scoring_failed',
                          'error_type': type(error).__name__}), flush=True)
        raise SystemExit(1) from None
