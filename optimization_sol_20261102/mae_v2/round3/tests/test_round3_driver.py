from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import run_round3 as driver


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))


def sample(index=0):
    group = index % 78
    return {'sample_id': 'synthetic-' + str(index), 'dataset': 'nutrition5k',
            'group_id': 'g' + str(group), 'fold': group % 5,
            'split': 'dev', 'image_path': 'pixels-only.png'}


class DriverTests(unittest.TestCase):
    def test_failure_preserves_raw_and_uses_given_training_fallback(self):
        answer = {'prediction': None, 'raw_outputs': ['invalid', 'still invalid'],
                  'repair_used': True, 'failure': 'schema', 'items': []}
        fallback = dict.fromkeys(driver.metrics.KEYS, 3.0)
        result = driver.prediction_record(sample(), answer, fallback)
        self.assertTrue(result['fallback'])
        self.assertFalse(result['native_complete'])
        self.assertIsNone(result['raw_prediction'])
        self.assertEqual(result['prediction'], fallback)
        fallback['weight'] = 999
        self.assertEqual(result['prediction']['weight'], 3)
        self.assertEqual(result['raw_outputs'], answer['raw_outputs'])

    def test_binding_and_record_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(driver, 'atomic_json', save):
            directory = Path(tmp)
            expected = {'hash': 'first'}
            driver.bind_once(directory, expected)
            driver.bind_once(directory, expected)
            with self.assertRaises(ValueError):
                driver.bind_once(directory, {'hash': 'changed'})
            row = sample()
            record = {k: row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')}
            env = {'record': record, 'record_sha256': driver.fingerprint(record),
                   'binding_sha256': driver.fingerprint(expected)}
            save(driver.record_path(directory, row), env)
            self.assertEqual(driver.read_record(directory, row, expected), record)
            env['record']['fold'] = 4
            save(driver.record_path(directory, row), env)
            with self.assertRaises(ValueError):
                driver.read_record(directory, row, expected)

    def test_full_population_fallback_fold_isolation_and_no_resume_calls(self):
        rows = [sample(i) for i in range(84)]
        labels = {r['sample_id']: {'truth': dict.fromkeys(driver.metrics.KEYS,
            1000.0 if r['fold'] == 0 else 2.0), 'split': 'dev'} for r in rows}
        answer = {'prediction': None, 'raw_outputs': ['bad'], 'repair_used': True,
                  'failure': 'invalid', 'items': [], 'audit': {}}
        calls = []

        class FakeProvider:
            def __init__(self, *args, **kwargs):
                self.allow_paid = kwargs['allow_paid']
            def close(self):
                pass

        def infer(provider, image_path):
            self.assertTrue(provider.allow_paid)
            self.assertIsInstance(image_path, Path)
            calls.append(image_path)
            return deepcopy(answer)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save(root / 'runs/development/selected_oof_predictions.json', [])
            save(root / 'runs/development/selection.json', {'metrics': {'datasets': {'nutrition5k': {}}}})
            with patch.object(driver, 'ROUND', root), patch.object(driver, 'ROOT', root), \
                    patch.object(driver, 'atomic_json', save), patch.object(driver, 'binding', return_value={'fixed': True}), \
                    patch.object(driver.study, 'dev_inputs', return_value=(rows, labels, {})), \
                    patch.object(driver, 'Provider', FakeProvider), patch.object(driver, 'infer', side_effect=infer), \
                    patch.object(driver, 'usage', return_value={}), patch.object(driver, 'event'):
                driver.run(allow_paid=True)
                self.assertEqual(len(calls), 84)
                pred = driver.read_record(root / 'runs/F', rows[0], {'fixed': True})
                self.assertEqual(pred['prediction']['weight'], 2.0)
                self.assertTrue(pred['fallback'])
                result = driver.run(evaluate_only=True)
                self.assertEqual(len(calls), 84)
                self.assertEqual(result['nutrition5k']['n'], 84)
                self.assertEqual(result['nutrition5k']['fallback_n'], 84)
                self.assertFalse(result['validation_opened'])
                saved = root / 'runs/F/records'
                self.assertEqual(len(list(saved.glob('*.json'))), 84)

    def test_missing_population_cannot_be_scored(self):
        rows = [sample(i) for i in range(84)]
        with tempfile.TemporaryDirectory() as tmp, patch.object(driver, 'ROUND', Path(tmp)), \
                patch.object(driver, 'atomic_json', save), patch.object(driver, 'binding', return_value={}), \
                patch.object(driver.study, 'dev_inputs', return_value=(rows, {}, {})), \
                patch.object(driver, 'Provider') as provider:
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                driver.run(evaluate_only=True)
            provider.assert_not_called()


if __name__ == '__main__':
    unittest.main()
