#!/usr/bin/env python3
"""Create a public demo profile from completed, bound development artifacts.

Default is a read-only readiness check. --write creates reports/demo_profile.json
once; different existing content is never replaced. Reuses development-only
loaders, sealed record verification, profile selection and final-parameter APIs.
Validation targets, predictions and images are never read. Optional validation
status uses only batch/completion and frozen-method metadata, without scoring.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile

import demo

ROOT = demo.ROOT
DEV = 'runs/development/'
OUTPUT = 'reports/demo_profile.json'
DATASETS = ('asa24', 'nutrition5k')
REVIEW_BRIDGE = 'evidence/review-one-completion.json'
REVIEW_CORE_FILES = frozenset(('cohorts_v2.py', 'legacy_adapter.py', 'opt_provider.py',
    'opt_pipeline.py', 'pipeline_v2.py', 'opt_metrics.py', 'metrics_v2.py', 'study.py', 'validation_adapter.py'))
REVIEW_CHANGED_FILES = frozenset(('pipeline_v2.py', 'opt_metrics.py'))


class Reader:
    def __init__(self, root):
        self.root, self.hashes = root, {}

    def path(self, relative):
        path = demo.safe_file(self.root, relative)
        value = demo.sha256(path)
        if relative in self.hashes and self.hashes[relative] != value:
            raise ValueError('An input changed during finalization')
        self.hashes[relative] = value
        return path

    def read(self, relative):
        return json.loads(self.path(relative).read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))

    def unchanged(self):
        for relative, value in self.hashes.items():
            if demo.sha256(demo.safe_file(self.root, relative)) != value:
                raise ValueError('An input changed during finalization')


def _backend(root):
    sys.path.insert(0, str(root / 'src'))
    import study
    import metrics_v2
    if study.ROOT.resolve() != root or Path(study.__file__).resolve() != root / 'src/study.py':
        raise ValueError('Loaded research module belongs to another checkout')
    return study, metrics_v2


def _lock(stack, root, relative):
    handle = stack.enter_context(demo.safe_file(root, relative).open('rb'))
    fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)


def _review_source_bridge(reader, selected, current, common):
    """Permit only the two reviewed fixes on the recorded unaffected route.

    The review is an explicit bridge between preserved raw run bindings and
    current portable sources. It never rewrites or upgrades the raw evidence.
    """
    review = reader.read(REVIEW_BRIDGE)
    original = review.get('original_code_sha256')
    if (review.get('status') != 'approved_or_fixed'
            or type(review.get('unresolved_p1_p2')) is not int or review['unresolved_p1_p2'] != 0
            or review.get('code_sha256') != current
            or not isinstance(original, dict) or set(original) != REVIEW_CORE_FILES
            or set(current) != REVIEW_CORE_FILES
            or any(not isinstance(v, str) or len(v) != 64 or set(v) - set('0123456789abcdef')
                   for v in original.values())
            or {name for name in current if current[name] != original[name]} != REVIEW_CHANGED_FILES):
        raise ValueError('Review bridge does not bind the exact permitted source changes')
    compatibility = review.get('review_source_compatibility')
    expected = {'raw_run_bindings_preserved': True, 'selected_inference_path_unchanged': True,
                'complete_metrics_unchanged': True, 'findings': ['R-M2-3-1', 'R-M2-4-1']}
    if (not isinstance(compatibility, dict) or set(compatibility) != set(expected)
            or compatibility.get('findings') != expected['findings']
            or any(compatibility.get(k) is not True for k in expected if k != 'findings')):
        raise ValueError('Review source compatibility is not explicitly confirmed')
    for key, value in (('protocol_sha256', common['protocol_sha256']),
                       ('catalog_sha256', common['catalog_sha256']),
                       ('dev_freeze_sha256', reader.hashes['data/cohorts/dev_freeze.json']),
                       ('selection_sha256', reader.hashes[DEV + 'selection.json'])):
        if review.get(key) != value:
            raise ValueError('Review bridge artifact binding differs')
    expected_profiles = {
        'asa24': ('asa-retrieval-portion', {'variant': 'optimized', 'image_mode': 'square256',
            'candidate_cap': 32, 'portion_modes': {'asa24': 'continuous_option', 'nutrition5k': 'total_ratio'},
            'examples': False}),
        'nutrition5k': ('C', {'profile': 'C', 'crop_review': False, 'portion_mode': 'total_ratio', 'identity_profile': 'A'})}
    for dataset, (name, config) in expected_profiles.items():
        profile = selected['profiles'][dataset]
        if (profile.get('name') != name or profile.get('directory') != DEV + name
                or json.dumps(profile.get('config'), sort_keys=True) != json.dumps(config, sort_keys=True)
                or profile.get('examples') is not False):
            raise ValueError('Review compatibility is limited to the original ASA and C(A) noncrop route')
    return original


def _validation_status(reader, selected, parameters, code_hashes):
    completion = reader.root / 'runs/validation/completion.json'
    batch = reader.root / 'runs/validation/batch.json'
    if not completion.exists() and not batch.exists():
        return 'not_run'
    # These are neutral method/batch metadata, never validation target data.
    method = reader.read('runs/frozen/method.json')
    method_hash = reader.hashes['runs/frozen/method.json']
    if (reader.read('runs/frozen/method_seal.json').get('method_sha256') != method_hash
            or reader.read('runs/validation/batch.json').get('method_sha256') != method_hash
            or method.get('selection_sha256') != reader.hashes[DEV + 'selection.json']
            or method.get('code_sha256') != code_hashes):
        raise ValueError('Validation status refers to a different selected method')
    for dataset in DATASETS:
        frozen = method['profiles'][dataset]
        if (frozen['name'] != selected['profiles'][dataset]['name']
                or frozen['config'] != selected['profiles'][dataset]['config']
                or demo._parameters(frozen['parameters'], dataset) != demo._parameters(parameters[dataset], dataset)):
            raise ValueError('Frozen method differs from the development parameters')
    if not completion.exists():
        return 'incomplete'
    saved = reader.read('runs/validation/completion.json')
    if (saved.get('status') != 'completed' or saved.get('method_sha256') != method_hash
            or saved.get('no_post_validation_tuning') is not True):
        raise ValueError('Validation completion metadata is inconsistent')
    return 'completed'


def _write_once(root, profile):
    target = root / OUTPUT
    for parent in (target, *target.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Output cannot use a symbolic link')
    payload = (json.dumps(profile, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    if target.exists():
        if json.loads(demo.safe_file(root, OUTPUT).read_text()) != profile:
            raise ValueError('A different public profile already exists; no overwrite is allowed')
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.demo-profile-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.link(temporary, target)  # atomic publication without replacement
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def finalize(root=ROOT, *, write=False):
    root = Path(root).resolve()
    safe = {'api_calls': 0, 'credentials_read': False, 'validation_targets_read': False}
    if not (root / (DEV + 'completion.json')).is_file():
        return {**safe, 'status': 'NOT_READY', 'reason': 'development_completion_missing'}
    with ExitStack() as stack:
        try:
            _lock(stack, root, DEV + '.job.lock')
            if (root / 'runs/validation/.job.lock').exists():
                _lock(stack, root, 'runs/validation/.job.lock')
        except BlockingIOError:
            return {**safe, 'status': 'NOT_READY', 'reason': 'research_job_still_running'}
        reader = Reader(root)
        completion = reader.read(DEV + 'completion.json')
        selected = reader.read(DEV + 'selection.json')
        candidates = reader.read(DEV + 'candidates.json')
        decision = reader.read(DEV + 'round2_decision.json')
        joint = selected.get('joint_pass')
        if (type(joint) is not bool or completion.get('joint_pass') is not joint
                or selected.get('metrics', {}).get('joint_pass') is not joint
                or completion.get('status') != ('ready_for_review' if joint else 'development_targets_not_met')
                or completion.get('registered_candidates_exhausted') is not (not joint)
                or completion.get('validation_opened_for_inference_or_scoring') is not False
                or selected.get('validation_opened_for_inference_or_scoring') is not False
                or selected.get('status') != 'development_selection'
                or selected.get('scope') != 'development_not_independent_validation'
                or not isinstance(completion.get('completed'), str)):
            raise ValueError('Development completion and selection differ')
        study, metrics = _backend(root)
        if any(type(decision.get(name)) is not bool for name in ('D', 'E')):
            raise ValueError('Final registered expansion decision is missing')
        expected_names = list(study.ORDER[:6]) + [name for name in ('D', 'E') if decision[name]]
        if [c['name'] for c in candidates] != expected_names or selected.get('candidate_names') != expected_names:
            raise ValueError('Final candidate inventory differs from the completed registered tree')
        if set(selected.get('profiles', {})) != set(DATASETS):
            raise ValueError('Both selected dataset profiles are required')
        for dataset in DATASETS:
            if metrics.select_profile(candidates, dataset) != selected['profiles'][dataset]:
                raise ValueError('Selection differs from the completed candidate inventory')
        code_hashes = study.source_hashes()
        for name, value in code_hashes.items():
            reader.path('src/' + name)
            if reader.hashes['src/' + name] != value:
                raise ValueError('Core source binding differs')
        reader.path('data/cohorts/dev_freeze.json')
        rows, labels, catalog = study.dev_inputs()  # dev-only integrity API
        if (completion.get('active_development_rows') != len(rows)
                or any(r.get('split') != 'dev' for r in rows)):
            raise ValueError('Completed development population differs')
        common = {'code_sha256': code_hashes,
            'catalog_sha256': demo.sha256(reader.path('data/catalog.json')),
            'protocol_sha256': demo.sha256(reader.path('PROTOCOL.md')),
            'experiment_sha256': demo.sha256(reader.path('config/experiment.json')),
            'candidate_sha256': demo.sha256(reader.path('config/candidates.json')),
            'vector_sha256': demo.sha256(reader.path('data/vectors/manifest.json'))}
        bindings = {}
        for candidate in candidates:
            name = candidate['name']
            directory = DEV + name
            if candidate.get('directory') != directory or candidate.get('registration_index') != study.ORDER.index(name):
                raise ValueError('Candidate path or registration differs')
            bindings[name] = reader.read(directory + '/run_config.json')
        compatibility_applied = any(binding.get('code_sha256') != code_hashes for binding in bindings.values())
        if compatibility_applied:
            original = _review_source_bridge(reader, selected, code_hashes, common)
            common = {**common, 'code_sha256': original}
            reference = DEV + 'reference-identities/run_config.json'
            binding = reader.read(reference)
            n5 = [r for r in rows if r['dataset'] == 'nutrition5k']
            if (binding.get('name') != 'reference-identities'
                    or binding.get('manifest_sha256') != study.fingerprint(n5)
                    or any(binding.get(key) != value for key, value in common.items())
                    or reader.read(DEV + 'reference-identities/status.json').get('status') != 'completed'):
                raise ValueError('Historical reference stage differs from the reviewed original bindings')
        for candidate in candidates:
            name = candidate['name']
            directory = DEV + name
            binding = bindings[name]
            subset = rows if name == 'baseline' else [r for r in rows if r['dataset'] == ('asa24' if name == 'asa-retrieval-portion' else 'nutrition5k')]
            if (binding.get('name') != name or binding.get('config') != candidate['config']
                    or binding.get('manifest_sha256') != study.fingerprint(subset)
                    or any(binding.get(key) != value for key, value in common.items())
                    or reader.read(directory + '/status.json').get('status') != 'completed'):
                raise ValueError('A completed candidate has drifted from its source/config/population binding')
        density = {code: value['density'] for code, value in catalog['foods'].items()}
        parameters, origins = {}, {}
        for dataset in DATASETS:
            profile = selected['profiles'][dataset]
            directory = profile['directory']
            subset = [r for r in rows if r['dataset'] == dataset]
            reader.path(directory + '/records_sealed.json')
            for row in subset:
                demo.safe_file(root, directory + '/records/' + study.artifact(row))
            raw = study.completed_records(root / directory, subset, allow_subset=True)
            enabled = profile.get('calibration_enabled', False)
            if type(enabled) is not bool or bool(profile.get('calibrated')) != enabled:
                raise ValueError('Selected calibration flags differ')
            fitted = metrics.fit_final(subset, labels, raw, catalog['asa_options'], density,
                dataset=dataset, enabled=enabled, examples=profile.get('examples', False))
            calibration = profile.get('calibration_artifact')
            if calibration:
                suffix = 'asa' if dataset == 'asa24' else ('round1' if profile['name'] in ('A', 'B', 'C') else 'round2')
                if calibration != directory + '/calibration-' + suffix + '.json' or profile.get('examples'):
                    raise ValueError('Unexpected selected calibration artifact')
                saved = reader.read(calibration)
                if saved.get('selected_parameters') != fitted or saved.get('calibration_enabled') is not enabled:
                    raise ValueError('Saved selected parameters differ from the bound development fit')
                parameters[dataset], origins[dataset] = saved['selected_parameters'], 'loaded_and_refit_verified'
            else:
                if enabled:
                    raise ValueError('Enabled calibration has no selected artifact')
                parameters[dataset], origins[dataset] = fitted, 'fitted_disabled_calibration'
        validation_status = _validation_status(reader, selected, parameters, code_hashes)
        profile = demo.make_demo_profile(selected, parameters, root, validation_status=validation_status)
        demo.check_runtime(root, profile)
        reader.unchanged()
        created = _write_once(root, profile) if write else False
        return {**safe, 'status': 'WRITTEN' if created else ('VERIFIED_EXISTING' if write else 'READY'),
            'profile_path': OUTPUT, 'profile_sha256': demo.sha256(root / OUTPUT) if write else None,
            'selected_profiles': {dataset: selected['profiles'][dataset]['name'] for dataset in DATASETS},
            'parameter_origin': origins, 'independent_validation_status': validation_status,
            'review_source_compatibility_applied': compatibility_applied,
            'review_evidence_sha256': reader.hashes.get(REVIEW_BRIDGE) if compatibility_applied else None,
            'development_rows': len(rows), 'input_sha256': reader.hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Create the final profile only after every completion/binding check passes')
    args = parser.parse_args()
    try:
        result = finalize(write=args.write)
    except Exception as error:
        result = {'status': 'STOPPED', 'error_type': type(error).__name__, 'api_calls': 0,
                  'notice': 'Completion or binding checks failed; no final artifact was replaced.'}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['status'] in ('READY', 'WRITTEN', 'VERIFIED_EXISTING') else 1


if __name__ == '__main__':
    raise SystemExit(main())
