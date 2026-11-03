"""Synthetic continuation seals and label gates; no real data or Provider use.

Only aliases in the new evaluator are replaced for fixtures. Original modules,
constants and functions are never monkeypatched. The summary function's exact
code runs with a separate test globals dictionary setting bootstrap draws to
zero; this avoids repeating the existing bootstrap tests or mathematical code.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import FunctionType
import unittest
from unittest.mock import patch

V2 = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(V2), str(V2 / 'src')]
from round4.continuation import evaluate as e
from round4.continuation.integrity import policy as registered_service_policy
from round4.src.artifacts import ArtifactStore, ArtifactError, canonical, decode, fingerprint, key_path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ContinuationEvaluationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='evaluation-synthetic-', dir=Path(__file__).resolve().parent)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / 'round4').mkdir(mode=0o700)
        self.rows, self.labels, self.records, self.preserved = [], {}, {}, []
        for dataset, count, groups in (('nutrition5k', 84, 78), ('asa24', 99, 23)):
            for index in range(count):
                sid = f'synthetic-{dataset}-{index:03d}'
                row = {'sample_id': sid, 'dataset': dataset, 'group_id': f'{dataset}-group-{index % groups:03d}',
                       'fold': index % groups % 5, 'split': 'dev'}
                self.rows.append(row)
                truth = {'weight': 100, 'energy': 200, 'fat': 10, 'carbs': 30, 'protein': 15}
                self.labels[sid] = {'truth': deepcopy(truth), 'split': 'dev'}
                pred = {k: row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')}
                pred.update(prediction=deepcopy(truth), raw_prediction=deepcopy(truth), fallback=False,
                    method_fallback=False, repair_used=False, native_complete=True, final_codes=[],
                    primary_code=None, failure=None)
                if dataset == 'nutrition5k':
                    pred['query_id'] = sid
                    self.records[sid] = pred
                else:
                    self.labels[sid].update(food_code='12345678', size='synthetic')
                    pred.update(final_codes=['12345678'], primary_code='12345678',
                        conditional={'prediction': deepcopy(truth), 'fallback': False},
                        e2e={'prediction': deepcopy(truth), 'fallback': False})
                    self.preserved.append(pred)
        for name in set(e.SOURCES) | set(e.CONTINUATION_SOURCES):
            self.put(name, ('synthetic-bound-source:' + name).encode())
        self.put(e.calibration.PROTOCOL, (V2 / e.calibration.PROTOCOL).read_bytes())
        self.put(e.SERVICE_PROTOCOL, b'synthetic explicit service protocol')
        self.put(e.OLD_SNAPSHOT, canonical({'synthetic_stage_snapshot': True}))
        self.put(e.scorer.MANIFEST, b''.join(canonical(row) for row in self.rows))
        self.put(e.scorer.LABELS, canonical(self.labels))
        self.put(e.scorer.PRESERVED, canonical(self.preserved))
        self.pins = {name: sha((self.root / name).read_bytes()) for name in e.scorer.PINNED_INPUTS}
        freeze = {'status': 'accepted_external_training_frozen', 'binding': {'synthetic_exclusion': True}}
        freeze_sha = self.put(e.calibration.TRAIN_FREEZE, canonical(freeze))
        self.put(e.GALLERY_COMPLETION, canonical({'synthetic_full_gallery': True}))
        self.binding = {'phase': 'development_base',
            'method_config': deepcopy(e.scorer.run_base.context.METHOD_CONFIG),
            'query_count': 84, 'query_groups': 78, 'training_freeze_sha256': freeze_sha,
            'training_exclusion_binding': freeze['binding'],
            'gallery_completion_sha256': sha((self.root / e.GALLERY_COMPLETION).read_bytes()),
            'input_sha256': {e.calibration.TRAIN_FREEZE: freeze_sha,
                            e.scorer.MANIFEST: self.pins[e.scorer.MANIFEST]}}
        source_hashes = {name: sha((self.root / name).read_bytes()) for name in e.CONTINUATION_SOURCES}
        registration_sha = self.put(e.REGISTRATION, canonical({'continuation_source_sha256': source_hashes}))
        self.binding['service_continuation'] = {'registration_sha256': registration_sha,
            'protocol_sha256': sha((self.root / e.SERVICE_PROTOCOL).read_bytes()),
            'old_stage_snapshot_sha256': sha((self.root / e.OLD_SNAPSHOT).read_bytes()),
            'original_base_intent_sha256': '', 'source_sha256': source_hashes,
            'policy': registered_service_policy('a' * 64)}
        self.reseal()
        self.reads = []
        fixture = self

        class SyntheticInputs(e.scorer.Inputs):
            def read(self, relative):
                fixture.reads.append(relative)
                path = self.root / relative
                e.require(not Path(relative).is_absolute() and '..' not in Path(relative).parts
                          and path.resolve() == path and path.is_file(), 'unsafe_test_input')
                raw = path.read_bytes(); value = sha(raw)
                e.require(relative not in fixture.pins or value == fixture.pins[relative], 'pinned_test_input_changed')
                e.require(relative not in self.hashes or self.hashes[relative] == value, 'test_input_changed')
                self.hashes[relative] = value
                return raw

        # The reviewed summary body is unchanged; its production alias still
        # has BOOTSTRAP=10000. No original global dictionary is modified.
        self.summary = FunctionType(e.scorer._summary.__code__,
            {**e.scorer._summary.__globals__, 'BOOTSTRAP': 0}, name='synthetic_summary')
        for p in (patch.object(e, 'ROOT', self.root), patch.object(e, 'Inputs', SyntheticInputs),
                  patch.object(e, 'PINNED_INPUTS', self.pins),
                  patch.object(e, 'verified_base', self.base), patch.object(e, 'summarize', self.summary)):
            p.start(); self.addCleanup(p.stop)

    def put(self, name, raw):
        path = self.root / name
        parent = self.root
        for part in path.parent.relative_to(self.root).parts:
            parent /= part
            parent.mkdir(mode=0o700, exist_ok=True)
        path.write_bytes(raw); path.chmod(0o600)
        return sha(raw)

    def reseal(self):
        # Only this test's invented base is replaced to exercise independent
        # scientific-binding failures under otherwise correct artifact seals.
        if (self.root / e.BASE_OUTPUT).exists():
            shutil.rmtree(self.root / e.BASE_OUTPUT)
        old = {k: v for k, v in self.binding.items() if k != 'service_continuation'}
        old_store = ArtifactStore(self.root / 'round4/runs/J', old, self.records,
                                 verify_sources=lambda: None, root=self.root / 'round4')
        old_sha = self.put(e.OLD_INTENT, canonical(old_store.intent))
        self.binding['service_continuation']['original_base_intent_sha256'] = old_sha
        self.store = ArtifactStore(self.root / e.BASE_OUTPUT, self.binding, self.records,
                                   verify_sources=lambda: None, root=self.root / 'round4')
        self.store.finalize(self.records)

    def base(self):
        records = self.store.verify_completed()
        return {'status': 'base_verified', 'n': len(records), 'records': records,
            'provider_constructed': False, 'validation_opened': False,
            'binding': deepcopy(self.binding),
            'completion_sha256': sha((self.root / e.BASE_COMPLETION).read_bytes())}

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_three_seals_order_math_reuse_and_only_new_output_paths(self):
        self.assertEqual(self.binding['service_continuation']['policy']['max_workers'], 2)
        self.assertIs(e.service_policy, registered_service_policy)
        events = []
        def summary(*args):
            events.append('summary')
            self.assertTrue((self.root / e.BASE_COMPLETION).is_file())
            if len(events) > 1:
                self.assertTrue((self.root / e.CAL_OUTPUT / 'completion.json').is_file())
            return self.summary(*args)
        def derived(*args):
            events.append('fit')
            self.assertTrue((self.root / e.RAW_OUTPUT / 'completion.json').is_file())
            return e.calibration.build_oof(*args)
        with patch.object(e, 'summarize', summary), patch.object(e, 'build_oof', derived):
            result = e.run()
        self.assertEqual(events, ['summary', 'fit', 'summary'])
        self.assertEqual(result['status'], 'continuation_evaluation_complete')
        self.assertEqual(result['metrics']['scope'], 'development_not_independent_validation')
        self.assertTrue(result['metrics']['service_continuation'])
        self.assertEqual(result['metrics']['selection']['selected_profile'], 'raw')
        self.assertEqual(decode((self.root / e.CAL_OUTPUT / 'completion.json').read_bytes())['record_count'], 85)
        self.assertFalse((self.root / 'round4/runs/J/completion.json').exists())
        self.assertFalse((self.root / e.scorer.OUTPUT).exists())
        self.assertFalse((self.root / e.calibration.CAL_OUTPUT).exists())
        self.assertFalse((self.root / e.calibration.SCORE_OUTPUT).exists())
        self.assertIs(e.build_oof, e.calibration.build_oof)
        self.assertIs(e.select_profile, e.calibration.select_profile)
        self.assertEqual(e.scorer.BOOTSTRAP, 10000)

    def test_partial_or_paid_base_rejected_before_reader(self):
        valid = self.base()
        cases = [{**valid, 'n': 83}, {**valid, 'provider_constructed': True},
                 {**valid, 'validation_opened': True}, {**valid, 'status': 'base_complete'},
                 {**valid, 'records': dict(list(valid['records'].items())[:-1])}]
        for value in cases:
            with self.subTest(status=value['status']), patch.object(e, 'verified_base', return_value=value):
                with self.assertRaises(e.EvaluationError): e.run()
        self.assertEqual(self.reads, [])

    def test_full_base_artifact_seal_verified_before_any_label_access(self):
        path = self.root / e.BASE_OUTPUT / 'records' / (key_path(next(iter(self.records))) + '.json')
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises(ArtifactError): e.run()
        self.assertEqual(self.reads, [])

    def test_external_only_and_service_provenance_gates_precede_labels(self):
        original = deepcopy(self.binding)
        mutations = [lambda b: b['method_config'].update(method='hybrid'),
            lambda b: b['input_sha256'].update({e.scorer.LABELS: 'b' * 64}),
            lambda b: b.update(training_freeze_sha256='b' * 64),
            lambda b: b['service_continuation']['policy']['exception'].update(max_total_attempts=5),
            lambda b: b['service_continuation'].update(old_stage_snapshot_sha256='b' * 64)]
        for mutate in mutations:
            self.binding = deepcopy(original); mutate(self.binding); self.reseal(); self.reads.clear()
            with self.assertRaises(e.EvaluationError): e.run()
            self.assertNotIn(e.scorer.LABELS, self.reads)
            self.assertFalse((self.root / e.RAW_OUTPUT).exists())

    def test_missing_or_extra_labels_rejected_without_any_output(self):
        variants = [dict(list(self.labels.items())[1:]), {**self.labels, 'extra': next(iter(self.labels.values()))}]
        for labels in variants:
            self.pins[e.scorer.LABELS] = self.put(e.scorer.LABELS, canonical(labels))
            with self.assertRaisesRegex(e.EvaluationError, 'registered_development_label_population_required'):
                e.run()
            self.assertFalse((self.root / e.RAW_OUTPUT).exists())

    def test_service_worker_limit_missing_or_changed_rejected_before_labels(self):
        for missing in (True, False):
            self.binding['service_continuation']['policy'] = registered_service_policy('a' * 64)
            if missing:
                del self.binding['service_continuation']['policy']['max_workers']
            else:
                self.binding['service_continuation']['policy']['max_workers'] = 3
            self.reseal(); self.reads.clear()
            with self.subTest(missing=missing):
                with self.assertRaisesRegex(e.EvaluationError, 'single_registered_service_policy_required'):
                    e.run()
            self.assertNotIn(e.scorer.LABELS, self.reads)
            self.assertFalse((self.root / e.RAW_OUTPUT).exists())

    def test_all84_whole_fallbacks_remain_in_denominator_and_unchanged(self):
        for pred in self.records.values():
            pred.update(raw_prediction=None, fallback=True, native_complete=False,
                        failure='synthetic_contract_failure')
        self.reseal()
        result = e.run()['metrics']
        for key in ('raw', 'calibrated'):
            self.assertEqual(result[key]['nutrition5k']['primary']['n'], 84)
            self.assertEqual(result[key]['nutrition5k']['primary']['available_n'], 84)
            self.assertEqual(result[key]['nutrition5k']['fallback_n'], 84)
            self.assertEqual(result[key]['nutrition5k']['complete_subset']['n'], 0)
        self.assertEqual(result['future_selected_profile_factors'], dict.fromkeys(e.calibration.KEYS, 1))

    def test_completed_evaluation_is_strictly_read_only(self):
        first = e.run(); before = self.snapshot()
        second = e.run()
        self.assertEqual(second['status'], 'continuation_evaluation_verified')
        self.assertEqual(first['metrics'], second['metrics'])
        self.assertEqual(self.snapshot(), before)

    def test_registered_continuation_source_drift_rejected_before_labels(self):
        self.put('round4/continuation/evaluate.py', b'changed synthetic source')
        with self.assertRaisesRegex(e.EvaluationError, 'registered_continuation_source_changed'): e.run()
        self.assertNotIn(e.scorer.LABELS, self.reads)

    def test_original_protocol_drift_rejected_before_labels(self):
        self.put(e.calibration.PROTOCOL, b'changed')
        with self.assertRaisesRegex(e.EvaluationError, 'registered_calibration_protocol_changed'): e.run()
        self.assertNotIn(e.scorer.LABELS, self.reads)

    def test_output_artifact_tamper_is_rejected_without_rewrite(self):
        e.run()
        path = self.root / e.CAL_OUTPUT / 'records' / (key_path('fit_audit') + '.json')
        path.write_bytes(path.read_bytes() + b' ')
        before = self.snapshot()
        with self.assertRaises(ArtifactError): e.run()
        self.assertEqual(self.snapshot(), before)

    def test_base_mutation_during_final_evaluation_blocks_selection_seal(self):
        calls = []
        def summary(*args):
            value = self.summary(*args)
            calls.append(True)
            if len(calls) == 2:
                path = self.root / e.BASE_OUTPUT / 'records' / (key_path(next(iter(self.records))) + '.json')
                path.write_bytes(path.read_bytes() + b' ')
            return value
        with patch.object(e, 'summarize', summary), self.assertRaises(ArtifactError):
            e.run()
        self.assertTrue((self.root / e.RAW_OUTPUT / 'completion.json').is_file())
        self.assertTrue((self.root / e.CAL_OUTPUT / 'completion.json').is_file())
        self.assertFalse((self.root / e.SCORE_OUTPUT).exists())


if __name__ == '__main__':
    unittest.main()
