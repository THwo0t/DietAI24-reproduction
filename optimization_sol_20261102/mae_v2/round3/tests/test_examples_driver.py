"""Synthetic G driver integrity tests. No real images, credentials or APIs."""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import run_examples as driver


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))


def fixture():
    n5 = [{'sample_id': f'n5-{i}', 'dataset': 'nutrition5k', 'group_id': f'n5g{i % 78}',
           'fold': (i % 78) % 5, 'split': 'dev', 'image_path': f'images/n5-{i}.png',
           'image_sha256': driver.fingerprint(['n5', i])} for i in range(84)]
    asa = [{'sample_id': f'asa-{i}', 'dataset': 'asa24', 'group_id': f'asag{i % 23}',
            'fold': (i % 23) % 5, 'split': 'dev', 'image_path': f'images/asa-{i}.png',
            'image_sha256': driver.fingerprint(['asa', i])} for i in range(99)]
    labels = {r['sample_id']: {'truth': dict.fromkeys(driver.metrics.KEYS, 1000. if r['dataset'] == 'nutrition5k'
                 and r['fold'] == 0 else 2.), 'split': 'dev', 'food_code': '12345678', 'size': 'medium'}
              for r in n5 + asa}
    asa_predictions = [{'sample_id': r['sample_id'], 'dataset': 'asa24',
        'prediction': dict.fromkeys(driver.metrics.KEYS, 2.), 'final_codes': ['12345678'],
        'primary_code': '12345678', 'retrieved_codes': ['12345678'], 'native_complete': True, 'fallback': False,
        'conditional': {'prediction': dict.fromkeys(driver.metrics.KEYS, 2.)},
        'e2e': {'prediction': dict.fromkeys(driver.metrics.KEYS, 2.)}} for r in asa]
    return n5 + asa, labels, asa_predictions


def choose(rows, raw, codes, vectors, query_id, count=4):
    query = next(r for r in rows if r['sample_id'] == query_id)
    selected, groups = [], set()
    for row in rows:
        if row['fold'] != query['fold'] and row['group_id'] != query['group_id'] and row['group_id'] not in groups:
            selected.append(row['sample_id'])
            groups.add(row['group_id'])
        if len(selected) == count:
            return selected


def file_snapshot(directory):
    return {p.relative_to(directory).as_posix(): (driver.sha(p), p.stat().st_mtime_ns)
            for p in directory.rglob('*') if p.is_file()}


class GDriverTests(unittest.TestCase):
    @contextmanager
    def source_fixture(self):
        """Small on-disk synthetic source graph exercises the real context reader."""
        rows, labels, asa = fixture()
        n5 = rows[:84]
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            root = Path(temp)
            stack.enter_context(patch.object(driver, 'ROOT', root))
            stack.enter_context(patch.object(driver, 'ROUND', root / 'round3'))
            def data(name, value):
                save(root / name, value)
            data('src/opt_metrics.py', {'synthetic': True})
            core = {'opt_metrics.py': driver.sha(root / 'src/opt_metrics.py')}
            reviewed = {'original_code_sha256': {'opt_metrics.py': 'old-synthetic'}, 'protocol_sha256': 'old-protocol'}
            stack.enter_context(patch.object(driver.study, 'source_hashes', return_value=core))
            stack.enter_context(patch.object(driver.study, 'INFERENCE_FILES', ('opt_metrics.py',)))
            stack.enter_context(patch.object(driver, 'validate_review', return_value=reviewed))
            config = {'profile': 'C', 'identity_profile': 'A', 'crop_review': False, 'portion_mode': 'total_ratio'}
            data('runs/development/selection.json', {'profiles': {'nutrition5k': {'name': 'C', 'config': config}},
                 'metrics': {'datasets': {'nutrition5k': {'n': 84}}}})
            data('runs/development/selected_oof_predictions.json', asa)
            raw, seal = [], {}
            for row in n5:
                vector = {'weight': 10., 'energy': 10., 'fat': 1., 'carbs': 1., 'protein': 1.}
                record = {k: row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')}
                record.update({'raw_prediction': vector, 'prediction': deepcopy(vector), 'final_codes': [],
                    'primary_code': None, 'raw_leaves': [{'code': '12345678', 'grams': 10.}],
                    'fallback': False, 'native_complete': True})
                path = root / 'runs/development/C/records' / driver.study.artifact(row)
                save(path, record)
                seal[row['sample_id']] = driver.sha(path)
                raw.append(record)
            data('runs/development/C/records_sealed.json', seal)
            data('runs/development/C/predictions.json', raw)
            data('data/vectors/codes.json', ['12345678'])
            data('data/vectors/collection.json', {})
            driver.np.save(root / 'data/vectors/embeddings.npy', driver.np.array([[1., 2.]]), allow_pickle=False)
            data('data/vectors/manifest.json', {'vectors': 1, 'dimensions': 2,
                 'files': {name: driver.sha(root / 'data/vectors' / name)
                           for name in ('codes.json', 'collection.json', 'embeddings.npy')}})
            data('runs/development/C/run_config.json', {'name': 'C', 'code_sha256': reviewed['original_code_sha256'],
                 'manifest_sha256': driver.fingerprint(n5), 'protocol_sha256': 'old-protocol', 'config': config,
                 'vector_sha256': driver.sha(root / 'data/vectors/manifest.json')})
            fmetrics = {'candidate': 'F', 'validation_opened': False, 'nutrition5k': {'n': 84}}
            data('round3/runs/F/metrics.json', fmetrics)
            data('round3/runs/F/completion.json', {'n': 84, 'groups': 78, 'validation_opened': False})
            data('round3/runs/F/records_sealed.json', {})
            data('round3/evidence/F_audit.json', {'status': 'PASS', 'candidate': 'F', 'metrics_match': True,
                 'metrics_sha256': driver.fingerprint(fmetrics), 'input_sha256': {
                     path: driver.sha(root / path) for path in ('round3/runs/F/metrics.json',
                         'round3/runs/F/completion.json', 'round3/runs/F/records_sealed.json')}})
            for path in ('config/experiment.json', 'config/candidates.json', 'round3/G_PROTOCOL.md',
                         *('round3/src/' + name for name in driver.ROUND_SOURCES)):
                data(path, {'synthetic': path})
            yield root, n5, labels

    @contextmanager
    def environment(self, *, answer=None):
        rows, labels, asa = fixture()
        n5 = rows[:84]
        with patch.object(driver, 'select_examples', side_effect=choose):
            assignments = driver.make_assignments(n5, labels, [], [], [])
        context = {'input_sha256': {'synthetic-source': 'a' * 64}, 'source_sha256': {},
                   'assignments': assignments, 'asa_predictions': asa,
                   'selected_C_reference': {'n': 84, 'source': 'preserved_C'},
                   'raw_C_reference': {'n': 84, 'source': 'raw_C'},
                   'F_reference': {'n': 84, 'source': 'F'}}
        if answer is None:
            answer = {'prediction': None, 'failure': 'invalid', 'repair_used': True,
                      'raw_outputs': ['bad', 'still bad'], 'items': [], 'audit': {}}
        calls, providers = [], []

        class FakeProvider:
            def __init__(self, directory, **kwargs):
                providers.append(kwargs)
                if kwargs['allow_paid'] is not True:
                    raise driver.ProviderStop('permission required')
            def close(self):
                pass

        def infer(provider, query, examples):
            self.assertIsInstance(query, Path)
            self.assertEqual(len(examples), 4)
            query_row = next(r for r in n5 if query.as_posix().endswith(r['image_path']))
            groups = set()
            for example in examples:
                self.assertEqual(set(example), {'image_path', 'reference'})
                self.assertEqual(set(example['reference']), set(driver.metrics.KEYS))
                support = next(r for r in n5 if example['image_path'].as_posix().endswith(r['image_path']))
                self.assertNotEqual(support['fold'], query_row['fold'])
                self.assertNotEqual(support['group_id'], query_row['group_id'])
                self.assertEqual(example['reference'], labels[support['sample_id']]['truth'])
                groups.add(support['group_id'])
            self.assertEqual(len(groups), 4)
            calls.append(query)
            return deepcopy(answer)

        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            root = Path(temp)
            stack.enter_context(patch.object(driver, 'ROOT', root))
            stack.enter_context(patch.object(driver, 'ROUND', root / 'round3'))
            stack.enter_context(patch.object(driver.study, 'dev_inputs', side_effect=lambda: (deepcopy(rows), deepcopy(labels), {})))
            prepare = stack.enter_context(patch.object(driver, 'prepare_context', side_effect=lambda *_: deepcopy(context)))
            stack.enter_context(patch.object(driver, 'Provider', FakeProvider))
            inference = stack.enter_context(patch.object(driver, 'infer', side_effect=infer))
            stack.enter_context(patch.object(driver, 'usage', side_effect=lambda _: {'http_requests': len(calls)}))
            stack.enter_context(patch.object(driver, 'atomic_json', side_effect=save))
            stack.enter_context(patch.object(driver, 'event'))
            yield {'root': root, 'directory': root / 'round3/runs/G', 'rows': rows, 'n5': n5,
                   'labels': labels, 'context': context, 'calls': calls, 'providers': providers,
                   'prepare': prepare, 'infer': inference, 'infer_impl': infer}

    def test_full_population_fallback_support_isolation_and_readonly_completion(self):
        with self.environment() as env:
            result = driver.run(allow_paid=True, workers=2)
            self.assertEqual(len(env['calls']), 84)
            self.assertEqual(env['providers'][0]['namespace'], 'mae-v2-round3-G')
            self.assertEqual(result['candidate'], 'G')
            self.assertEqual(result['nutrition5k']['n'], 84)
            self.assertEqual(result['nutrition5k']['fallback_n'], 84)
            joint = result['joint_metrics_with_preserved_asa']
            self.assertEqual(joint['datasets']['asa24']['n'], 99)
            self.assertEqual(joint['datasets']['asa24']['exact_n'], 99)
            self.assertEqual(len(joint['checks']), 20)
            expected = driver.binding(env['n5'], env['context'])
            record = driver.read_record(env['directory'], env['n5'][0], expected,
                                        env['context']['assignments'][env['n5'][0]['sample_id']])
            self.assertEqual(record['prediction']['weight'], 2.)
            self.assertIsNone(record['raw_prediction'])
            self.assertEqual(len(record['example_proof']['examples']), 4)
            before = file_snapshot(env['directory'])
            again = driver.run(evaluate_only=True)
            self.assertEqual(again, result)
            self.assertEqual(len(env['calls']), 84)
            self.assertEqual(len(env['providers']), 1)
            self.assertEqual(file_snapshot(env['directory']), before)

    def test_record_self_checksum_rewrite_does_not_bypass_external_seal(self):
        with self.environment() as env:
            driver.run(allow_paid=True)
            path = driver.record_path(env['directory'], env['n5'][0])
            envelope = driver.load(path)
            envelope['record']['prediction']['weight'] = 0
            envelope['record_sha256'] = driver.fingerprint(envelope['record'])
            save(path, envelope)
            before = file_snapshot(env['directory'])
            with self.assertRaisesRegex(ValueError, 'external G seal'):
                driver.run(evaluate_only=True)
            self.assertEqual(file_snapshot(env['directory']), before)
            self.assertEqual(len(env['calls']), 84)

    def test_completed_seal_metrics_predictions_usage_and_completion_tampering_fail(self):
        for name in ['records_sealed.json', 'metrics.json', 'predictions.json', 'usage.json', 'completion.json']:
            with self.subTest(artifact=name), self.environment() as env:
                driver.run(allow_paid=True)
                path = env['directory'] / name
                original = driver.load(path)
                if isinstance(original, list):
                    original[0]['prediction']['weight'] += 1
                elif name == 'completion.json':
                    original['binding_sha256'] = '0' * 64
                else:
                    original['tampered'] = True
                save(path, original)
                before = file_snapshot(env['directory'])
                with self.assertRaises(ValueError):
                    driver.run(evaluate_only=True)
                self.assertEqual(file_snapshot(env['directory']), before)
                self.assertEqual(len(env['calls']), 84)

    def test_completed_missing_binding_never_recreated(self):
        with self.environment() as env:
            driver.run(allow_paid=True)
            path = env['directory'] / 'binding.json'
            path.unlink()
            with self.assertRaises(ValueError):
                driver.run(evaluate_only=True)
            self.assertFalse(path.exists())
            self.assertEqual(len(env['calls']), 84)

    def test_existing_completion_never_opens_provider_without_paid_flag(self):
        with self.environment() as env:
            driver.run(allow_paid=True)
            driver.run(allow_paid=False)
            self.assertEqual(len(env['providers']), 1)

    def test_incomplete_evaluate_only_never_invokes_provider(self):
        with self.environment() as env:
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                driver.run(evaluate_only=True)
            self.assertFalse(env['calls'])
            self.assertFalse(env['providers'])
            self.assertFalse((env['directory'] / 'completion.json').exists())

    def test_interrupted_resume_keeps_completed_records_without_error_based_retry(self):
        with self.environment() as env:
            count = 0
            def interrupt(provider, image, examples):
                nonlocal count
                count += 1
                if count == 7:
                    raise driver.ProviderStop('synthetic stop')
                return env['infer_impl'](provider, image, examples)
            env['infer'].side_effect = interrupt
            with self.assertRaises(driver.ProviderStop):
                driver.run(allow_paid=True, workers=1)
            self.assertEqual(len(env['calls']), 6)
            existing = {p.name: (driver.sha(p), p.stat().st_mtime_ns) for p in (env['directory'] / 'records').iterdir()}
            self.assertFalse((env['directory'] / 'records_sealed.json').exists())
            env['infer'].side_effect = env['infer_impl']
            driver.run(allow_paid=True, workers=1)
            self.assertEqual(len(env['calls']), 84)
            for name, value in existing.items():
                p = env['directory'] / 'records' / name
                self.assertEqual((driver.sha(p), p.stat().st_mtime_ns), value)

    def test_inputs_or_assignments_drift_reject_before_resuming(self):
        for which in ['source', 'assignment']:
            with self.subTest(which=which), self.environment() as env:
                driver.run(allow_paid=True)
                if which == 'source':
                    env['context']['input_sha256']['synthetic-source'] = 'b' * 64
                else:
                    env['context']['assignments']['n5-0']['examples'].reverse()
                with self.assertRaisesRegex(ValueError, 'source or example assignments'):
                    driver.run(evaluate_only=True)
                self.assertEqual(len(env['calls']), 84)

    def test_source_change_during_run_retains_records_but_never_scores(self):
        with self.environment() as env:
            good = deepcopy(env['context'])
            changed = deepcopy(good)
            changed['input_sha256']['synthetic-source'] = 'b' * 64
            env['prepare'].side_effect = [good, changed]
            with self.assertRaisesRegex(ValueError, 'retained but unscored'):
                driver.run(allow_paid=True)
            self.assertEqual(len(env['calls']), 84)
            self.assertFalse((env['directory'] / 'metrics.json').exists())
            self.assertFalse((env['directory'] / 'records_sealed.json').exists())

    def test_persisted_seal_blocks_tampering_before_completion_exists(self):
        with self.environment() as env:
            driver.run(allow_paid=True)
            (env['directory'] / 'completion.json').unlink()
            path = driver.record_path(env['directory'], env['n5'][0])
            original = driver.load(path)
            original['record']['prediction']['fat'] += 1
            original['record_sha256'] = driver.fingerprint(original['record'])
            save(path, original)
            before = file_snapshot(env['directory'])
            with self.assertRaisesRegex(ValueError, 'external G seal'):
                driver.run(allow_paid=True)
            self.assertEqual(file_snapshot(env['directory']), before)
            self.assertEqual(len(env['calls']), 84)

    def test_inference_boundary_rechecks_support_provenance(self):
        rows, labels, _ = fixture()
        n5 = rows[:84]
        with patch.object(driver, 'select_examples', side_effect=choose):
            assignments = driver.make_assignments(n5, labels, [], [], [])
        query = n5[0]
        assignment = assignments[query['sample_id']]
        by_id = {r['sample_id']: r for r in n5}
        bad = deepcopy(assignment)
        bad['examples'][0]['reference_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'labels changed'):
            driver.example_inputs(query, bad, by_id, labels)
        bad = deepcopy(assignment)
        bad['examples'][0]['fold'] = query['fold']
        with self.assertRaisesRegex(ValueError, 'isolation changed'):
            driver.example_inputs(query, bad, by_id, labels)

    def test_sampler_returning_same_fold_duplicate_group_or_id_is_rejected(self):
        rows, labels, _ = fixture()
        n5 = rows[:84]
        for ids in [['n5-0', 'n5-1', 'n5-2', 'n5-3'], ['n5-1'] * 4,
                    ['n5-1', 'n5-79', 'n5-2', 'n5-3']]:
            with self.subTest(ids_kind=len(set(ids))), patch.object(driver, 'select_examples', return_value=ids):
                with self.assertRaises(ValueError):
                    driver.make_assignments(n5, labels, [], [], [])

    def test_wrong_population_and_worker_limits_fail(self):
        rows, labels, _ = fixture()
        with self.assertRaises(ValueError):
            driver.validate_population(rows[:-1], labels)
        for workers in [0, 5, True]:
            with self.assertRaises(ValueError):
                driver.run(workers=workers)

    def test_success_record_retains_raw_items_without_calibration(self):
        rows, labels, _ = fixture()
        answer = {'prediction': dict.fromkeys(driver.metrics.KEYS, 7.), 'items': [{'item_id': 'i1'}],
                  'raw_outputs': ['raw'], 'repair_used': False, 'failure': None, 'audit': {}}
        assignment = {'examples': []}
        record = driver.prediction_record(rows[0], answer, dict.fromkeys(driver.metrics.KEYS, 2.), assignment)
        self.assertEqual(record['prediction'], answer['prediction'])
        self.assertEqual(record['raw_prediction'], answer['prediction'])
        self.assertFalse(record['fallback'])
        self.assertTrue(record['native_complete'])
        self.assertNotIn('mass_factor', record)

    def test_trusted_review_evidence_hash_required(self):
        class Reader:
            hashes = {driver.REVIEW: '0' * 64, driver.METRIC_REVIEW: '1' * 64}
            def json(self, name):
                return {}
        with self.assertRaisesRegex(ValueError, 'Trusted review evidence'):
            driver.validate_review(Reader(), {})

    def test_context_real_selector_with_synthetic_files_and_explicit_dependencies(self):
        with self.source_fixture() as (root, rows, labels):
            context = driver.prepare_context(rows, labels)
            self.assertEqual(len(context['assignments']), 84)
            self.assertEqual(len(context['asa_predictions']), 99)
            self.assertEqual(context['raw_C_reference']['n'], 84)
            for path in ('runs/development/C/records_sealed.json', 'runs/development/C/predictions.json',
                         'data/vectors/manifest.json', 'data/vectors/embeddings.npy', 'data/vectors/codes.json',
                         'runs/development/selection.json', 'runs/development/selected_oof_predictions.json',
                         'round3/G_PROTOCOL.md'):
                self.assertIn(path, context['input_sha256'])
            save(root / 'round3/src/future_H.py', {'unrelated': True})
            save(root / 'round3/H_PROTOCOL.md', {'unrelated': True})
            again = driver.prepare_context(rows, labels)
            self.assertEqual(driver.binding(rows, again), driver.binding(rows, context))

    def test_context_rejects_raw_C_seal_aggregate_and_vector_drift(self):
        for kind in ['raw_record', 'raw_aggregate', 'vector', 'F_reference']:
            with self.subTest(kind=kind), self.source_fixture() as (root, rows, labels):
                if kind == 'raw_record':
                    path = root / 'runs/development/C/records' / driver.study.artifact(rows[0])
                    value = driver.load(path)
                    value['raw_prediction']['weight'] += 1
                    save(path, value)
                elif kind == 'raw_aggregate':
                    path = root / 'runs/development/C/predictions.json'
                    value = driver.load(path)
                    value[0]['raw_prediction']['weight'] += 1
                    save(path, value)
                elif kind == 'vector':
                    save(root / 'data/vectors/codes.json', ['87654321'])
                else:
                    path = root / 'round3/runs/F/metrics.json'
                    value = driver.load(path)
                    value['nutrition5k']['changed'] = True
                    save(path, value)
                with self.assertRaises(ValueError):
                    driver.prepare_context(rows, labels)

    def test_strict_json_and_write_once_preserve_artifacts(self):
        with self.assertRaises(ValueError):
            driver.decode('{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            driver.decode('{"a":NaN}')
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'one.json'
            driver.write_once(p, {'a': 1})
            before = (driver.sha(p), p.stat().st_mtime_ns)
            driver.write_once(p, {'a': 1})
            self.assertEqual((driver.sha(p), p.stat().st_mtime_ns), before)
            with self.assertRaises(ValueError):
                driver.write_once(p, {'a': 2})


if __name__ == '__main__':
    unittest.main()
