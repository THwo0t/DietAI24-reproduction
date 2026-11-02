"""Synthetic sealed-boundary tests; never open real validation or make requests."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import opt_provider
import validation_adapter as adapter

REAL_EVALUATE = adapter.metrics.evaluate
CODE = '12345678'
VECTOR = {'weight': 100.0, 'energy': 200.0, 'fat': 10.0, 'carbs': 20.0, 'protein': 10.0}


def prediction(row):
    result = {'sample_id': row['sample_id'], 'dataset': row['dataset'], 'group_id': row['group_id'],
              'fold': row.get('fold'), 'final_codes': [], 'primary_code': None,
              'prediction': deepcopy(VECTOR), 'raw_prediction': deepcopy(VECTOR),
              'fallback': False, 'native_complete': True}
    if row['dataset'] == 'asa24':
        branch = {'code': CODE, 'prediction': deepcopy(VECTOR), 'option_id': 'one',
                  'continuous_grams': 100, 'fallback': False}
        result.update(final_codes=[CODE], primary_code=CODE,
                      conditional=deepcopy(branch), e2e=deepcopy(branch))
    return result


class ValidationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mae-v2-adapter-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trace = []
        self.source_hashes = {'study.py': '1' * 64, 'validation_adapter.py': '2' * 64}
        self.catalog = {'foods': {CODE: {'description': 'synthetic food', 'density':
                        {'energy': 200, 'fat': 10, 'carbs': 20, 'protein': 10}}},
                        'asa_options': {CODE: [{'option_id': 'one', 'description': '1 cup', 'grams': 100}]}}
        self.dev_rows = [{'sample_id': f'{dataset}-dev-{i}', 'dataset': dataset, 'split': 'dev',
                          'group_id': f'{dataset}-dev-group-{i}', 'fold': i}
                         for dataset in ('asa24', 'nutrition5k') for i in range(2)]
        self.dev_labels = {r['sample_id']: {'truth': deepcopy(VECTOR), 'food_code': CODE, 'size': 'medium'}
                           for r in self.dev_rows}
        self.rows = []
        self.labels = {}
        for dataset, count in (('asa24', 78), ('nutrition5k', 200)):
            for i in range(count):
                sid = f'{dataset}-validation-synthetic-{i}'
                name = hashlib.sha256(sid.encode()).hexdigest() + '.png'
                relative = f'data/{dataset}/validation/images/{name}'
                output = BytesIO()
                Image.new('RGB', (2, 2), (i % 256, i // 256, 30 if dataset == 'asa24' else 90)).save(output, 'PNG')
                self.write_bytes(relative, output.getvalue())
                row = {'sample_id': sid, 'dataset': dataset, 'split': 'validation', 'fold': None,
                       'group_id': f'{dataset}-association-{i // 2}', 'image_path': relative,
                       'image_sha256': adapter.sha(self.root / relative)}
                self.rows.append(row)
                self.labels[sid] = {'food_code': CODE, 'size': 'DO_NOT_PASS_SIZE',
                                    'Portion': 'DO_NOT_PASS_PORTION', 'LabelUnit': 'DO_NOT_PASS_UNIT',
                                    'truth': deepcopy(VECTOR), 'ingredient_list': ['DO_NOT_PASS_INGREDIENT']}
        self.manifest_path = self.root / 'data/cohorts/sealed/validation.jsonl'
        self.labels_path = self.root / 'data/cohorts/sealed/validation_labels.json'
        self.seal_path = self.root / 'data/freeze/validation_freeze.json'
        self.review_path = self.root / 'evidence/review-one-completion.json'
        self.selection_path = self.root / 'runs/development/selection.json'
        self.method_path = self.root / 'runs/frozen/method.json'
        self.write_bytes('PROTOCOL.md', b'synthetic preregistered protocol\n')
        self.write_json('config/experiment.json', {'model': 'synthetic-model'})
        self.write_json('config/candidates.json', {'profiles': ['A', 'B', 'C', 'D', 'E']})
        self.write_json('data/cohorts/dev_freeze.json', {'synthetic': True})
        self.write_json('data/catalog.json', self.catalog)
        self.write_json('data/vectors/manifest.json', {'synthetic': True})
        self.reseal()
        score = REAL_EVALUATE(self.dev_rows, self.dev_labels, [prediction(r) for r in self.dev_rows])
        self.selected = {'joint_pass': True, 'metrics': score, 'profiles': {
            'asa24': {'directory': 'runs/development/asa-retrieval-portion', 'config': {'variant': 'optimized'}},
            'nutrition5k': {'directory': 'runs/development/A', 'config': {'profile': 'A', 'portion_mode': 'direct'}}}}
        self.write_json(self.selection_path, self.selected)
        self.write_review()

        self.fake_study = types.ModuleType('study')
        self.fake_study.BASE = {'variant': 'baseline'}
        self.fake_study.dev_inputs = Mock(return_value=(self.dev_rows, self.dev_labels, self.catalog))
        self.fake_study.source_hashes = Mock(return_value=deepcopy(self.source_hashes))
        self.fake_study.stage_dir = Mock(side_effect=lambda name, phase='development': self.root / 'runs' / phase / name)
        self.fake_study.completed_records = Mock(side_effect=self.complete_records)
        self.fake_study.run_legacy = Mock(side_effect=self.run_mock)
        self.fake_study.run_component = Mock(side_effect=self.run_mock)
        self.fake_study.event = Mock()
        self.start_patch(patch.object(adapter, 'ROOT', self.root))
        self.start_patch(patch.object(opt_provider, 'ROOT', self.root))
        self.start_patch(patch.dict(sys.modules, {'study': self.fake_study}))
        self.fit = self.start_patch(patch.object(adapter.metrics, 'fit_final', side_effect=lambda *a, **kw:
            {'dataset': kw['dataset'], 'fallback': deepcopy(VECTOR), 'mass_factor': 1.0, 'asa_factor': 1.0}))
        self.apply = self.start_patch(patch.object(adapter.metrics, 'apply_parameters', side_effect=lambda p, *a, **kw: deepcopy(p)))
        self.score = self.start_patch(patch.object(adapter.metrics, 'evaluate', return_value={'joint_pass': True}))
        self.args = types.SimpleNamespace(review=str(self.review_path), allow_paid=True, workers=1)

    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def write_bytes(self, relative, data):
        path = Path(relative)
        if not path.is_absolute():
            path = self.root / path
        self.assertTrue(path.is_relative_to(self.root))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def write_json(self, relative, value):
        return self.write_bytes(relative, (json.dumps(value, allow_nan=False) + '\n').encode())

    def reseal(self):
        self.write_bytes(self.manifest_path, ''.join(json.dumps(r) + '\n' for r in self.rows).encode())
        self.write_json(self.labels_path, self.labels)
        artifacts = {r['image_path']: adapter.sha(self.root / r['image_path']) for r in self.rows}
        artifacts.update({str(p.relative_to(self.root)): adapter.sha(p) for p in (self.manifest_path, self.labels_path)})
        self.seal = {'images': 200, 'groups': 100, 'artifacts': artifacts}
        self.write_json(self.seal_path, self.seal)

    def write_review(self):
        review = {'status': 'approved_or_fixed', 'unresolved_p1_p2': 0, 'code_sha256': self.source_hashes,
                  'protocol_sha256': adapter.sha(self.root / 'PROTOCOL.md'),
                  'selection_sha256': adapter.sha(self.selection_path),
                  'dev_freeze_sha256': adapter.sha(self.root / 'data/cohorts/dev_freeze.json'),
                  'validation_freeze_sha256': adapter.sha(self.seal_path),
                  'catalog_sha256': adapter.sha(self.root / 'data/catalog.json')}
        self.write_json(self.review_path, review)

    def complete_records(self, directory, rows, **kwargs):
        self.trace.append(('complete', Path(directory).name, len(rows)))
        return [prediction(r) for r in rows]

    def run_mock(self, name, config, rows, contexts, catalog, allow_paid, workers, **kwargs):
        self.trace.append(('run', name, len(rows)))
        # The invocation is synthetic and NEVER instantiates the provider.
        for sid, context in contexts.items():
            self.assertTrue(sid.startswith('asa24-'))
            self.assertEqual(context, {'food_code': CODE})
        return self.root / 'runs' / kwargs.get('phase', 'development') / name

    def freeze(self):
        adapter.freeze(self.args)
        self.assertTrue(self.method_path.is_file())
        self.trace.clear()

    def tracked_load(self):
        original = adapter.load
        def load(path):
            if Path(path) == self.labels_path:
                self.trace.append(('label_load', len([x for x in self.trace if x[0] == 'label_load']) + 1))
            return original(path)
        return patch.object(adapter, 'load', side_effect=load)

    def assert_no_paid_run(self):
        self.fake_study.run_legacy.assert_not_called()
        self.fake_study.run_component.assert_not_called()

    def test_failed_development_gate_never_opens_validation(self):
        mutations = [lambda s: s.update(joint_pass=False),
                     lambda s: s['metrics'].update(joint_pass=False),
                     lambda s: s['metrics']['checks'].pop(),
                     lambda s: s['metrics']['checks'][0].update(value=s['metrics']['checks'][0]['threshold'] + 1e-12),
                     lambda s: s['metrics']['datasets']['asa24'].update(n=99, exact_n=14)]
        for mutate in mutations:
            selected = deepcopy(self.selected)
            mutate(selected)
            self.write_json(self.selection_path, selected)
            with self.subTest(selected=selected['metrics'].get('passed_checks')), \
                 patch.object(adapter, '_sealed_manifest', side_effect=AssertionError('validation opened')) as sealed, \
                 patch.object(adapter, '_conditional_codes', side_effect=AssertionError('labels opened')) as labels:
                with self.assertRaises(ValueError):
                    adapter.freeze(self.args)
                sealed.assert_not_called()
                labels.assert_not_called()
                self.assertFalse(self.method_path.exists())
        self.assert_no_paid_run()

    def test_gate_recomputes_fixed_limits_and_integer_recognition_floor(self):
        selected = deepcopy(self.selected)
        selected['metrics']['datasets']['asa24'].update(n=99, exact_n=15)
        adapter._require_development_gate(selected)
        for mutate in (
            lambda s: s['metrics']['checks'][0].update(value=True),
            lambda s: s['metrics']['checks'][0].update(value=float('nan')),
            lambda s: s['metrics']['checks'][0].update(threshold=999999),
            lambda s: s['metrics']['checks'].__setitem__(0, deepcopy(s['metrics']['checks'][1])),
            lambda s: s['metrics']['datasets']['asa24'].update(exact_n=14),
        ):
            bad = deepcopy(selected)
            mutate(bad)
            with self.subTest(bad=bad['metrics']['checks'][0]), self.assertRaises(ValueError):
                adapter._require_development_gate(bad)

    def test_missing_or_unapproved_review_stops_before_validation(self):
        self.review_path.unlink()
        with patch.object(adapter, '_sealed_manifest', side_effect=AssertionError('validation opened')) as sealed:
            with self.assertRaisesRegex(ValueError, 'completion evidence'):
                adapter.freeze(self.args)
            sealed.assert_not_called()
        self.write_review()
        review = adapter.load(self.review_path)
        for status, unresolved in (('pending', 0), ('approved_or_fixed', 1)):
            self.write_json(self.review_path, {**review, 'status': status, 'unresolved_p1_p2': unresolved})
            with patch.object(adapter, '_sealed_manifest', side_effect=AssertionError('validation opened')) as sealed:
                with self.assertRaisesRegex(ValueError, 'review is incomplete'):
                    adapter.freeze(self.args)
                sealed.assert_not_called()

    def test_review_requires_exact_path_and_all_provenance_bindings(self):
        other = self.write_json('evidence/same-content-other-name.json', adapter.load(self.review_path))
        with self.assertRaises(ValueError):
            adapter._review_gate(other, self.source_hashes)
        original = adapter.load(self.review_path)
        for field in ('code_sha256', 'protocol_sha256', 'selection_sha256', 'dev_freeze_sha256',
                      'validation_freeze_sha256', 'catalog_sha256'):
            bad = deepcopy(original)
            bad[field] = {} if field == 'code_sha256' else '0' * 64
            self.write_json(self.review_path, bad)
            with self.subTest(field=field), self.assertRaises(ValueError):
                adapter._review_gate(self.review_path, self.source_hashes)

    def test_sealed_population_is_exactly_200_plus_78_with_linked_groups_allowed(self):
        rows = adapter._sealed_manifest()
        self.assertEqual(rows, self.rows)
        self.assertEqual(len(rows), 278)
        self.assertEqual(len({r['group_id'] for r in rows if r['dataset'] == 'nutrition5k'}), 100)
        for dataset in ('asa24', 'nutrition5k'):
            original = deepcopy(self.rows)
            self.rows = [r for r in original if r['sample_id'] != next(x['sample_id'] for x in original if x['dataset'] == dataset)]
            self.reseal()
            with self.subTest(dataset=dataset), self.assertRaisesRegex(ValueError, 'count/identity'):
                adapter._sealed_manifest()
            self.rows = original
            self.reseal()

    def test_invalid_split_fold_and_duplicate_sample_are_rejected(self):
        original = deepcopy(self.rows)
        for field, value in (('split', 'dev'), ('fold', 0), ('sample_id', self.rows[1]['sample_id'])):
            self.rows = deepcopy(original)
            self.rows[0][field] = value
            self.reseal()
            with self.subTest(field=field), self.assertRaises(ValueError):
                adapter._sealed_manifest()

    def test_extra_unknown_dataset_cannot_hide_outside_the_two_counts(self):
        extra = deepcopy(self.rows[0])
        extra.update(sample_id='unexpected-extra-record', dataset='other')
        self.rows.append(extra)
        self.reseal()
        with self.assertRaises(ValueError):
            adapter._sealed_manifest()

    def test_corrupted_image_is_rejected_before_any_run(self):
        image = self.root / self.rows[0]['image_path']
        image.write_bytes(image.read_bytes() + b'corruption')
        with self.assertRaisesRegex(ValueError, 'artifact mismatch'):
            adapter._sealed_manifest()
        self.assert_no_paid_run()

    def test_seal_must_cover_manifest_labels_and_every_declared_image(self):
        original = deepcopy(self.seal)
        for relative in ('data/cohorts/sealed/validation.jsonl',
                         'data/cohorts/sealed/validation_labels.json', self.rows[0]['image_path']):
            bad = deepcopy(original)
            bad['artifacts'].pop(relative)
            self.write_json(self.seal_path, bad)
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                adapter._sealed_manifest()

    def test_manifest_image_hash_must_match_sealed_file_hash(self):
        self.rows[0]['image_sha256'] = '0' * 64
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'not bound'):
            adapter._sealed_manifest()

    def test_forbidden_path_in_seal_is_not_read(self):
        relative = 'data/not-validation.txt'
        self.write_bytes(relative, b'synthetic outside allowed seal paths')
        self.seal['artifacts'][relative] = adapter.sha(self.root / relative)
        self.write_json(self.seal_path, self.seal)
        original_sha = adapter.sha
        def guarded_sha(path):
            if Path(path) == self.root / relative:
                raise AssertionError('forbidden seal path read')
            return original_sha(path)
        with patch.object(adapter, 'sha', side_effect=guarded_sha), self.assertRaisesRegex(ValueError, 'Forbidden path'):
            adapter._sealed_manifest()

    def test_conditional_context_contains_only_asa_code(self):
        contexts = adapter._conditional_codes(self.rows)
        self.assertEqual(len(contexts), 78)
        for sid, context in contexts.items():
            self.assertTrue(sid.startswith('asa24-'))
            self.assertEqual(context, {'food_code': CODE})
        encoded = json.dumps(contexts)
        for forbidden in ('DO_NOT_PASS', 'truth', 'LabelUnit', 'size', 'ingredient_list', 'nutrition5k'):
            self.assertNotIn(forbidden, encoded)

    def test_conditional_context_rejects_reference_population_mismatch(self):
        self.labels.pop(self.rows[-1]['sample_id'])
        self.write_json(self.labels_path, self.labels)
        with self.assertRaisesRegex(ValueError, 'population differs'):
            adapter._conditional_codes(self.rows)

    def test_conditional_code_cannot_be_a_nested_label_payload(self):
        first = next(r for r in self.rows if r['dataset'] == 'asa24')['sample_id']
        for invalid in ({'size': 'medium', 'truth': VECTOR}, 12345678, '1234', 'abcdefgh'):
            self.labels[first]['food_code'] = invalid
            self.write_json(self.labels_path, self.labels)
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                adapter._conditional_codes(self.rows)

    def test_successful_freeze_binds_inputs_and_never_parses_validation_labels(self):
        original_load = adapter.load
        def guard(path):
            if Path(path) == self.labels_path:
                raise AssertionError('freeze parsed validation labels')
            return original_load(path)
        with patch.object(adapter, 'load', side_effect=guard):
            self.freeze()
        frozen = adapter.load(self.method_path)
        self.assertEqual(frozen['validation_manifest_fingerprint'], adapter.fingerprint(self.rows))
        self.assertEqual(frozen['code_sha256'], self.source_hashes)
        self.assertEqual(frozen['bootstrap_resamples'], 10000)
        self.assertEqual(set(frozen['profiles']), {'asa24', 'nutrition5k'})
        self.assert_no_paid_run()
        before = self.method_path.read_bytes()
        adapter.freeze(self.args)
        self.assertEqual(self.method_path.read_bytes(), before)

    def test_different_existing_method_is_not_overwritten(self):
        self.freeze()
        frozen = adapter.load(self.method_path)
        frozen['bootstrap_resamples'] = 5
        self.write_json(self.method_path, frozen)
        before = self.method_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'different method'):
            adapter.freeze(self.args)
        self.assertEqual(self.method_path.read_bytes(), before)

    def test_incomplete_either_arm_never_reads_scoring_labels(self):
        self.freeze()
        for arm in ('baseline', 'optimized-asa24', 'optimized-nutrition5k'):
            self.trace.clear()
            def incomplete(directory, rows, **kwargs):
                result = self.complete_records(directory, rows, **kwargs)
                return result[:-1] if Path(directory).name == arm else result
            self.fake_study.completed_records.side_effect = incomplete
            with self.subTest(arm=arm), self.tracked_load(), self.assertRaisesRegex(ValueError, 'complete populations'):
                adapter.validate(self.args)
            self.assertEqual([x for x in self.trace if x[0] == 'label_load'], [('label_load', 1)])
            self.score.assert_not_called()
            self.assertFalse((self.root / 'runs/validation/completion.json').exists())

    def test_unsealed_arm_exception_never_reads_scoring_labels(self):
        self.freeze()
        self.fake_study.completed_records.side_effect = ValueError('Source records have not been sealed')
        with self.tracked_load(), self.assertRaisesRegex(ValueError, 'not been sealed'):
            adapter.validate(self.args)
        self.assertEqual([x for x in self.trace if x[0] == 'label_load'], [('label_load', 1)])
        self.score.assert_not_called()

    def test_equal_length_duplicate_ids_or_wrong_dataset_are_incomplete_arms(self):
        self.freeze()
        for arm in ('baseline', 'optimized-nutrition5k'):
            for defect in ('duplicate', 'wrong_dataset'):
                self.trace.clear()
                def invalid_records(directory, rows, **kwargs):
                    result = self.complete_records(directory, rows, **kwargs)
                    if Path(directory).name == arm:
                        if defect == 'duplicate':
                            result[0]['sample_id'] = result[1]['sample_id']
                        else:
                            result[0]['dataset'] = 'other'
                    return result
                self.fake_study.completed_records.side_effect = invalid_records
                with self.subTest(arm=arm, defect=defect), self.tracked_load(), self.assertRaises(ValueError):
                    adapter.validate(self.args)
                self.assertEqual([x for x in self.trace if x[0] == 'label_load'], [('label_load', 1)])
                self.score.assert_not_called()
                self.assertFalse((self.root / 'runs/validation/completion.json').exists())

    def test_complete_batch_reads_scoring_labels_only_after_both_arms(self):
        self.freeze()
        with self.tracked_load():
            adapter.validate(self.args)
        loads = [i for i, item in enumerate(self.trace) if item[0] == 'label_load']
        self.assertEqual(len(loads), 2)
        completions = [i for i, item in enumerate(self.trace) if item[0] == 'complete']
        self.assertEqual(len(completions), 3)
        self.assertLess(max(completions), loads[1])
        self.assertEqual(self.score.call_count, 2)
        for call in self.score.call_args_list:
            self.assertEqual(len(call.args[0]), 278)
            self.assertEqual(set(call.args[1]), set(self.labels))
            self.assertEqual(len(call.args[2]), 278)
            self.assertEqual(call.kwargs['bootstrap'], 10000)
        self.assertTrue((self.root / 'runs/validation/completion.json').is_file())

    def test_completed_batch_does_not_run_or_parse_conditional_labels_again(self):
        self.freeze()
        adapter.validate(self.args)
        self.fake_study.run_legacy.reset_mock()
        self.fake_study.run_component.reset_mock()
        self.fake_study.dev_inputs.reset_mock()
        self.score.reset_mock()
        self.trace.clear()
        with patch.object(adapter, '_conditional_codes', side_effect=AssertionError('conditional reopened')), self.tracked_load():
            adapter.validate(self.args)
        self.assert_no_paid_run()
        self.fake_study.dev_inputs.assert_not_called()
        self.score.assert_not_called()
        self.assertFalse(any(item[0] == 'label_load' for item in self.trace))
        self.fake_study.event.assert_called_with(status='already_completed', new_api_calls=0)

    def test_validation_requires_paid_flag_before_any_file_boundary(self):
        args = types.SimpleNamespace(allow_paid=False, workers=1)
        with patch.object(adapter, '_verify_method', side_effect=AssertionError('method read')) as verify, \
             self.assertRaises(opt_provider.ProviderStop):
            adapter.validate(args)
        verify.assert_not_called()
        self.assert_no_paid_run()

    def test_source_and_configuration_drift_reject_validation_before_run(self):
        self.freeze()
        self.fake_study.source_hashes.return_value = {'study.py': 'changed'}
        with self.assertRaisesRegex(ValueError, 'source drift'):
            adapter.validate(self.args)
        self.fake_study.source_hashes.return_value = self.source_hashes
        self.write_json('config/experiment.json', {'model': 'changed'})
        with self.assertRaisesRegex(ValueError, 'configuration drift'):
            adapter.validate(self.args)
        self.assert_no_paid_run()

    def test_method_change_after_batch_start_is_rejected(self):
        self.freeze()
        self.write_json('runs/validation/batch.json', {'method_sha256': adapter.sha(self.method_path)})
        frozen = adapter.load(self.method_path)
        frozen['profiles']['nutrition5k']['config']['profile'] = 'E'
        self.write_json(self.method_path, frozen)
        with self.assertRaisesRegex(ValueError, 'another method|method.*drift|integrity|independent seal'):
            adapter.validate(self.args)
        self.assert_no_paid_run()

    def test_method_change_before_first_batch_is_rejected(self):
        self.freeze()
        frozen = adapter.load(self.method_path)
        frozen['profiles']['nutrition5k']['parameters']['mass_factor'] = 1.125
        self.write_json(self.method_path, frozen)
        self.assertFalse((self.root / 'runs/validation/batch.json').exists())
        with self.assertRaisesRegex(ValueError, 'independent seal'):
            adapter.validate(self.args)
        self.assert_no_paid_run()

    def test_method_without_independent_seal_is_rejected(self):
        self.freeze()
        (self.root / 'runs/frozen/method_seal.json').unlink()
        with self.assertRaisesRegex(ValueError, 'independent seal'):
            adapter.validate(self.args)
        self.assert_no_paid_run()

    def test_post_inference_drift_blocks_second_label_read_and_scoring(self):
        self.freeze()
        def drift(directory, rows, **kwargs):
            result = self.complete_records(directory, rows, **kwargs)
            if Path(directory).name == 'baseline':
                self.write_bytes('PROTOCOL.md', b'drift during synthetic inference')
            return result
        self.fake_study.completed_records.side_effect = drift
        with self.tracked_load(), self.assertRaisesRegex(ValueError, 'artifact drift'):
            adapter.validate(self.args)
        self.assertEqual([x for x in self.trace if x[0] == 'label_load'], [('label_load', 1)])
        self.score.assert_not_called()


if __name__ == '__main__':
    unittest.main()
