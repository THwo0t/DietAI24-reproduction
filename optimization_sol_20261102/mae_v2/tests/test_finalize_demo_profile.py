"""Synthetic completion/source binding and dev-only profile finalization."""
from contextlib import ExitStack
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))
import demo
import finalize_demo_profile as finalizer
import metrics_v2 as metrics
import study
from test_demo_v2 import fixture, write

CODE = '10000000'
DENSITY = {'energy': 200, 'fat': 10, 'carbs': 20, 'protein': 10}


def vector():
    return {'weight': 100, **DENSITY}


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mae-v2-profile-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture(self.root)
        (self.root / 'reports/demo_profile.json').unlink()
        self.rows, self.labels, self.predictions = [], {}, []
        for dataset in finalizer.DATASETS:
            for i in range(5):
                sid = dataset + '-synthetic-' + str(i)
                row = dict(sample_id=sid, dataset=dataset, split='dev', group_id=dataset + '-group-' + str(i), fold=i)
                self.rows.append(row)
                self.labels[sid] = {'truth': vector(), 'food_code': CODE, 'size': 'medium', 'split': 'dev'}
                pred = {**row, 'prediction': vector(), 'raw_prediction': vector(), 'fallback': False,
                    'native_complete': True, 'final_codes': [CODE], 'primary_code': CODE,
                    'raw_leaves': [{'component_id': 'leaf', 'parent_id': 'plate', 'code': CODE, 'grams': 100, 'density': DENSITY}]}
                if dataset == 'asa24':
                    pred.update(conditional={'code': CODE, 'prediction': vector(), 'continuous_grams': 100,
                        'option_id': 'one', 'fallback': False}, e2e={'code': CODE, 'prediction': vector(), 'option_id': 'one', 'fallback': False})
                self.predictions.append(pred)
        self.catalog = json.loads((self.root / 'data/catalog.json').read_text())
        self.catalog['foods'] = {code: {'density': DENSITY} for code in self.catalog['foods']}
        self.catalog['asa_options'] = {CODE: [{'option_id': 'one', 'grams': 100}]}
        self.dump('data/catalog.json', self.catalog)
        self.dump('data/cohorts/dev_freeze.json', {'synthetic': True})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(study, 'ROOT', self.root))
        self.stack.enter_context(patch.object(study, 'dev_inputs', return_value=(self.rows, self.labels, self.catalog)))
        self.stack.enter_context(patch.object(study, 'Provider', side_effect=AssertionError('No provider construction')))
        self.stack.enter_context(patch.object(finalizer, '_backend', return_value=(study, metrics)))
        write(self.root, 'runs/development/.job.lock', b'')
        configs = {'baseline': study.BASE, 'asa-retrieval-portion': study.ASA, 'examples-2': study.EXAMPLES,
            'A': {'profile': 'A', 'crop_review': False, 'portion_mode': 'direct'},
            'B': {'profile': 'B', 'crop_review': True, 'portion_mode': 'direct'},
            'C': {'profile': 'C', 'crop_review': False, 'portion_mode': 'total_ratio', 'identity_profile': 'A'}}
        self.candidates = []
        for index, name in enumerate(study.ORDER[:6]):
            rows = self.rows if name == 'baseline' else [row for row in self.rows if row['dataset'] == ('asa24' if name == 'asa-retrieval-portion' else 'nutrition5k')]
            predictions = [pred for pred in self.predictions if pred['sample_id'] in {row['sample_id'] for row in rows}]
            directory = 'runs/development/' + name
            self.dump(directory + '/run_config.json', {'name': name, 'config': configs[name],
                'manifest_sha256': study.fingerprint(rows), 'code_sha256': study.source_hashes(),
                'catalog_sha256': demo.sha256(self.root / 'data/catalog.json'),
                'protocol_sha256': demo.sha256(self.root / 'PROTOCOL.md'),
                'experiment_sha256': demo.sha256(self.root / 'config/experiment.json'),
                'candidate_sha256': demo.sha256(self.root / 'config/candidates.json'),
                'vector_sha256': demo.sha256(self.root / 'data/vectors/manifest.json'), 'source': None})
            self.dump(directory + '/status.json', {'status': 'completed'})
            seal = {}
            for row, pred in zip(rows, predictions):
                path = self.dump(directory + '/records/' + study.artifact(row), pred)
                seal[row['sample_id']] = demo.sha256(path)
            self.dump(directory + '/records_sealed.json', seal)
            self.candidates.append({'name': name, 'directory': directory, 'config': configs[name],
                'metrics': metrics.evaluate(rows, self.labels, predictions), 'registration_index': index,
                'estimated_chat_calls': 3 if name in ('A', 'C') else 4, 'examples': name == 'examples-2', 'calibrated': False})
        self.save_selection()

    def dump(self, relative, value):
        return write(self.root, relative, json.dumps(value))

    def load(self, relative):
        return json.loads((self.root / relative).read_text())

    def save_selection(self):
        selection = {'status': 'development_selection', 'scope': 'development_not_independent_validation',
            'profiles': {dataset: metrics.select_profile(self.candidates, dataset) for dataset in finalizer.DATASETS},
            'metrics': metrics.evaluate(self.rows, self.labels, self.predictions), 'joint_pass': True,
            'candidate_names': [candidate['name'] for candidate in self.candidates],
            'validation_opened_for_inference_or_scoring': False}
        self.dump('runs/development/selection.json', selection)
        self.dump('runs/development/candidates.json', self.candidates)
        self.dump('runs/development/round2_decision.json', {'D': False, 'E': False})
        self.dump('runs/development/completion.json', {'status': 'ready_for_review', 'completed': 'synthetic',
            'registered_candidates_exhausted': False, 'joint_pass': True, 'active_development_rows': len(self.rows),
            'validation_opened_for_inference_or_scoring': False})
        return selection

    def prepare_review_bridge(self, *, evidence=True):
        for candidate in self.candidates:
            if candidate['name'] in ('asa-retrieval-portion', 'C'):
                candidate['estimated_chat_calls'] = 1
        self.save_selection()
        original = study.source_hashes()
        reference = self.load('runs/development/A/run_config.json')
        reference['name'] = 'reference-identities'
        self.dump('runs/development/reference-identities/run_config.json', reference)
        self.dump('runs/development/reference-identities/status.json', {'status': 'completed'})
        for name in ('opt_metrics.py', 'pipeline_v2.py'):
            path = self.root / 'src' / name
            path.write_bytes(path.read_bytes() + ('# reviewed fix: ' + name + '\n').encode())
        review = {'status': 'approved_or_fixed', 'unresolved_p1_p2': 0,
            'code_sha256': study.source_hashes(), 'original_code_sha256': original,
            'protocol_sha256': demo.sha256(self.root / 'PROTOCOL.md'),
            'dev_freeze_sha256': demo.sha256(self.root / 'data/cohorts/dev_freeze.json'),
            'selection_sha256': demo.sha256(self.root / 'runs/development/selection.json'),
            'catalog_sha256': demo.sha256(self.root / 'data/catalog.json'),
            'review_source_compatibility': {'raw_run_bindings_preserved': True,
                'selected_inference_path_unchanged': True, 'complete_metrics_unchanged': True,
                'findings': ['R-M2-3-1', 'R-M2-4-1']}}
        if evidence:
            self.dump(finalizer.REVIEW_BRIDGE, review)
        return review

    def test_review_bridge_preserves_old_runs_and_binds_current_public_profile(self):
        review = self.prepare_review_bridge()
        before = {str(path.relative_to(self.root)): demo.sha256(path)
                  for path in (self.root / 'runs/development').rglob('*') if path.is_file()}
        result = finalizer.finalize(self.root, write=True)
        self.assertEqual(result['status'], 'WRITTEN')
        self.assertTrue(result['review_source_compatibility_applied'])
        self.assertEqual(result['review_evidence_sha256'], demo.sha256(self.root / finalizer.REVIEW_BRIDGE))
        profile = self.load(finalizer.OUTPUT)
        self.assertEqual(result['selected_profiles'], {'asa24': 'asa-retrieval-portion', 'nutrition5k': 'C'})
        for relative, value in profile['source_sha256'].items():
            self.assertEqual(value, demo.sha256(self.root / relative))
        self.assertNotEqual(profile['source_sha256']['src/opt_metrics.py'], review['original_code_sha256']['opt_metrics.py'])
        self.assertEqual(before, {str(path.relative_to(self.root)): demo.sha256(path)
                                for path in (self.root / 'runs/development').rglob('*') if path.is_file()})
        self.assertEqual(finalizer.finalize(self.root, write=True)['status'], 'VERIFIED_EXISTING')

    def test_review_bridge_missing_evidence_refuses_source_drift(self):
        self.prepare_review_bridge(evidence=False)
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root, write=True)
        self.assertFalse((self.root / finalizer.OUTPUT).exists())

    def test_review_bridge_rejects_hash_status_flag_and_finding_drift(self):
        original = self.prepare_review_bridge()
        cases = [('status', 'pending'), ('unresolved_p1_p2', 1), ('unresolved_p1_p2', False)]
        cases += [(key, '0' * 64) for key in ('protocol_sha256', 'dev_freeze_sha256', 'selection_sha256', 'catalog_sha256')]
        for key, value in cases:
            self.dump(finalizer.REVIEW_BRIDGE, {**original, key: value})
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                finalizer.finalize(self.root, write=True)
        for flag in ('raw_run_bindings_preserved', 'selected_inference_path_unchanged', 'complete_metrics_unchanged'):
            for value in (False, 1, None):
                bad = deepcopy(original)
                bad['review_source_compatibility'][flag] = value
                self.dump(finalizer.REVIEW_BRIDGE, bad)
                with self.subTest(flag=flag, value=value), self.assertRaises(ValueError):
                    finalizer.finalize(self.root, write=True)
        for findings in (['R-M2-4-1'], ['R-M2-3-1', 'R-M2-4-1', 'another-fix']):
            bad = deepcopy(original)
            bad['review_source_compatibility']['findings'] = findings
            self.dump(finalizer.REVIEW_BRIDGE, bad)
            with self.subTest(findings=findings), self.assertRaises(ValueError):
                finalizer.finalize(self.root, write=True)
        for field in ('code_sha256', 'original_code_sha256'):
            bad = deepcopy(original)
            bad[field]['study.py'] = '0' * 64
            self.dump(finalizer.REVIEW_BRIDGE, bad)
            with self.subTest(field=field), self.assertRaises(ValueError):
                finalizer.finalize(self.root, write=True)
        self.assertFalse((self.root / finalizer.OUTPUT).exists())

    def test_review_bridge_rejects_extra_changed_or_declared_source_even_if_evidence_refreshed(self):
        review = self.prepare_review_bridge()
        path = self.root / 'src/opt_provider.py'
        path.write_bytes(path.read_bytes() + b'# an unrelated source change\n')
        review['code_sha256'] = study.source_hashes()
        self.dump(finalizer.REVIEW_BRIDGE, review)
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root, write=True)
        review['original_code_sha256']['opt_provider.py'] = review['code_sha256']['opt_provider.py']
        review['original_code_sha256']['extra.py'] = '0' * 64
        self.dump(finalizer.REVIEW_BRIDGE, review)
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root, write=True)

    def test_review_bridge_requires_every_stage_to_keep_exact_original_code_and_common_binding(self):
        review = self.prepare_review_bridge()
        for stage in ('baseline', 'B', 'reference-identities'):
            path = 'runs/development/' + stage + '/run_config.json'
            before = self.load(path)
            for key, value in (('code_sha256', review['code_sha256']), ('protocol_sha256', '0' * 64),
                               ('experiment_sha256', '0' * 64), ('candidate_sha256', '0' * 64),
                               ('vector_sha256', '0' * 64)):
                self.dump(path, {**before, key: value})
                with self.subTest(stage=stage, key=key), self.assertRaises(ValueError):
                    finalizer.finalize(self.root, write=True)
            self.dump(path, before)
        self.assertFalse((self.root / finalizer.OUTPUT).exists())

    def test_review_bridge_rejects_missing_support_stage_and_changing_review_evidence(self):
        review = self.prepare_review_bridge()
        path = 'runs/development/reference-identities/run_config.json'
        binding = self.load(path)
        (self.root / path).unlink()
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root, write=True)
        self.dump(path, binding)
        original = demo.make_demo_profile
        def drift(*args, **kwargs):
            result = original(*args, **kwargs)
            self.dump(finalizer.REVIEW_BRIDGE, {**review, 'status': 'pending'})
            return result
        with patch.object(demo, 'make_demo_profile', side_effect=drift):
            with self.assertRaisesRegex(ValueError, 'input changed'):
                finalizer.finalize(self.root, write=True)
        self.assertFalse((self.root / finalizer.OUTPUT).exists())

    def test_review_bridge_rejects_selected_B_and_C_with_B_identity(self):
        review = self.prepare_review_bridge()
        candidate = next(c for c in self.candidates if c['name'] == 'B')
        candidate['estimated_chat_calls'] = 0
        self.save_selection()
        review['selection_sha256'] = demo.sha256(self.root / 'runs/development/selection.json')
        self.dump(finalizer.REVIEW_BRIDGE, review)
        with self.assertRaisesRegex(ValueError, 'noncrop route'):
            finalizer.finalize(self.root, write=True)
        candidate['estimated_chat_calls'] = 4
        candidate = next(c for c in self.candidates if c['name'] == 'C')
        candidate['config'].update(identity_profile='B', crop_review=True)
        path = 'runs/development/C/run_config.json'
        binding = self.load(path)
        self.dump(path, {**binding, 'config': candidate['config']})
        self.save_selection()
        review['selection_sha256'] = demo.sha256(self.root / 'runs/development/selection.json')
        self.dump(finalizer.REVIEW_BRIDGE, review)
        with self.assertRaisesRegex(ValueError, 'noncrop route'):
            finalizer.finalize(self.root, write=True)

    def test_review_bridge_does_not_relax_selected_ASA_route_or_scalar_types(self):
        review = self.prepare_review_bridge()
        candidate = next(c for c in self.candidates if c['name'] == 'asa-retrieval-portion')
        original = deepcopy(candidate['config'])
        for key, value in (('image_mode', 'native'), ('candidate_cap', 32.0), ('examples', True)):
            candidate['config'] = {**original, key: value}
            path = 'runs/development/asa-retrieval-portion/run_config.json'
            binding = self.load(path)
            self.dump(path, {**binding, 'config': candidate['config']})
            self.save_selection()
            review['selection_sha256'] = demo.sha256(self.root / 'runs/development/selection.json')
            self.dump(finalizer.REVIEW_BRIDGE, review)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'noncrop route'):
                finalizer.finalize(self.root, write=True)
        self.assertFalse((self.root / finalizer.OUTPUT).exists())

    def test_missing_completion_stops_before_development_reads(self):
        (self.root / 'runs/development/completion.json').unlink()
        with patch.object(finalizer, '_backend', side_effect=AssertionError('premature source/data loading')):
            result = finalizer.finalize(self.root, write=True)
        self.assertEqual(result['status'], 'NOT_READY')
        self.assertFalse((self.root / finalizer.OUTPUT).exists())

    def test_active_development_lock_stops_without_write(self):
        with (self.root / 'runs/development/.job.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(finalizer.finalize(self.root, write=True)['reason'], 'research_job_still_running')
        self.assertFalse((self.root / finalizer.OUTPUT).exists())

    def test_readiness_and_write_are_dev_only_and_idempotent(self):
        original = Path.open
        def guard(path, *args, **kwargs):
            if path.name == '.env' or 'sealed' in path.parts or 'validation' in path.parts:
                raise AssertionError('private validation/credential read')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guard):
            result = finalizer.finalize(self.root)
            self.assertEqual(result['status'], 'READY')
            self.assertFalse(result['review_source_compatibility_applied'])
            self.assertIsNone(result['review_evidence_sha256'])
            self.assertFalse((self.root / finalizer.OUTPUT).exists())
            result = finalizer.finalize(self.root, write=True)
            self.assertEqual(result['status'], 'WRITTEN')
            self.assertEqual(finalizer.finalize(self.root, write=True)['status'], 'VERIFIED_EXISTING')
        profile = self.load(finalizer.OUTPUT)
        self.assertNotIn('training_ids', json.dumps(profile))
        self.assertNotIn('synthetic-', json.dumps(profile))
        self.assertNotIn('synthetic-', json.dumps(result))
        self.assertEqual(profile['profiles']['nutrition5k']['parameters']['fallback'], vector())
        self.assertFalse(profile['profiles']['nutrition5k']['parameters']['enabled'])

    def test_completion_candidate_selection_and_source_drift_are_rejected(self):
        cases = [('runs/development/completion.json', 'active_development_rows', 11),
                 ('runs/development/selection.json', 'candidate_names', ['A']),
                 ('runs/development/A/run_config.json', 'catalog_sha256', 'changed'),
                 ('runs/development/B/run_config.json', 'code_sha256', {'changed': 'source'}),
                 ('runs/development/C/status.json', 'status', 'running')]
        for path, key, value in cases:
            original = self.load(path)
            self.dump(path, {**original, key: value})
            with self.assertRaises(ValueError, msg=path):
                finalizer.finalize(self.root, write=True)
            self.dump(path, original)
        self.assertFalse((self.root / finalizer.OUTPUT).exists())

    def test_selected_profile_cannot_be_hand_changed(self):
        selection = self.load('runs/development/selection.json')
        selection['profiles']['nutrition5k']['config']['crop_review'] = True
        self.dump('runs/development/selection.json', selection)
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root, write=True)

    def test_saved_calibration_parameters_are_refit_verified(self):
        candidate = next(c for c in self.candidates if c['name'] == 'A')
        candidate.update(calibrated=True, calibration_enabled=True,
                         calibration_artifact='runs/development/A/calibration-round1.json')
        rows = [row for row in self.rows if row['dataset'] == 'nutrition5k']
        raw = study.completed_records(self.root / candidate['directory'], rows)
        params = metrics.fit_final(rows, self.labels, raw, self.catalog['asa_options'],
            {code: DENSITY for code in self.catalog['foods']}, dataset='nutrition5k', enabled=True)
        self.dump(candidate['calibration_artifact'], {'selected_parameters': params, 'calibration_enabled': True})
        self.save_selection()
        self.assertEqual(finalizer.finalize(self.root)['parameter_origin']['nutrition5k'], 'loaded_and_refit_verified')
        params['training_ids'] = []
        self.dump(candidate['calibration_artifact'], {'selected_parameters': params, 'calibration_enabled': True})
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root, write=True)

    def test_record_tampering_and_symlinks_fail_before_profile_write(self):
        row = next(row for row in self.rows if row['dataset'] == 'nutrition5k')
        path = self.root / 'runs/development/A/records' / study.artifact(row)
        original = path.read_bytes()
        path.write_text('{}')
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root, write=True)
        path.unlink()
        target = write(self.root, 'private-record', original)
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root, write=True)

    def test_existing_different_profile_is_not_overwritten(self):
        self.dump(finalizer.OUTPUT, {'unrelated': True})
        before = (self.root / finalizer.OUTPUT).read_bytes()
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root, write=True)
        self.assertEqual((self.root / finalizer.OUTPUT).read_bytes(), before)

    def test_input_drift_during_generation_prevents_write(self):
        original = demo.make_demo_profile
        def drift(*args, **kwargs):
            result = original(*args, **kwargs)
            write(self.root, 'src/study.py', '# changed during finalization')
            return result
        with patch.object(demo, 'make_demo_profile', side_effect=drift):
            with self.assertRaises(ValueError):
                finalizer.finalize(self.root, write=True)
        self.assertFalse((self.root / finalizer.OUTPUT).exists())

    def test_validation_status_uses_only_bound_neutral_metadata(self):
        finalizer.finalize(self.root, write=True)
        public = self.load(finalizer.OUTPUT)
        (self.root / finalizer.OUTPUT).unlink()
        method = {'selection_sha256': demo.sha256(self.root / 'runs/development/selection.json'),
            'code_sha256': study.source_hashes(), 'profiles': public['profiles']}
        self.dump('runs/frozen/method.json', method)
        digest = demo.sha256(self.root / 'runs/frozen/method.json')
        self.dump('runs/frozen/method_seal.json', {'method_sha256': digest})
        self.dump('runs/validation/batch.json', {'method_sha256': digest})
        self.dump('runs/validation/completion.json', {'status': 'completed', 'method_sha256': digest, 'no_post_validation_tuning': True})
        original = Path.open
        def guard(path, *args, **kwargs):
            if 'validation' in path.parts and path.name not in ('batch.json', 'completion.json') or 'sealed' in path.parts:
                raise AssertionError('validation targets opened')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guard):
            self.assertEqual(finalizer.finalize(self.root)['independent_validation_status'], 'completed')
        method['selection_sha256'] = 'different'
        self.dump('runs/frozen/method.json', method)
        with self.assertRaises(ValueError):
            finalizer.finalize(self.root)


if __name__ == '__main__':
    unittest.main()
