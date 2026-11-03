from copy import deepcopy
from pathlib import Path
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from round6.src import score_pilot as score


def fixture():
    records, rows, labels, ingredients = {}, [], {}, {}
    for i in range(25):
        sid = 's%02d' % i
        meta = {'sample_id': sid, 'group_id': 'g%02d' % i, 'fold': i % 5,
                'dataset': 'nutrition5k', 'split': 'train_pilot'}
        rows.append(meta)
        truth = {k: float(100 + j + i) for j, k in enumerate(score.metrics.KEYS)}
        labels[sid] = {'truth': truth}
        ingredients[sid] = [{'ingredient_id': 'ingr_0000000001', 'grams': truth['weight']}]
        record = {**meta, 'query_id': sid, 'stages': {'atlas': {}}}
        for role, error in (('baseline', 10), ('candidate', 8)):
            prediction = {k: v + error for k, v in truth.items()}
            record[role] = {'prediction': prediction, 'raw_prediction': prediction, 'fallback': False,
                'method_fallback': False, 'repair_used': False, 'native_complete': True,
                'raw_leaves': [{'ingredient_id': 'ingr_0000000001', 'grams': prediction['weight']}]}
        records[sid] = record
    return records, rows, labels, ingredients


class ScoreTests(unittest.TestCase):
    def test_manual_mae_per_unit_and_paired_gate(self):
        args = fixture()
        result = score.summarize(*args, bootstrap=20)
        self.assertAlmostEqual(result['baseline']['primary']['metrics']['weight']['mae'], 10)
        self.assertAlmostEqual(result['candidate']['primary']['metrics']['weight']['mae'], 8)
        self.assertAlmostEqual(result['candidate']['primary']['metrics']['weight']['per_unit'], 8 / 112)
        self.assertTrue(result['advance_gate']['advance'])
        self.assertEqual(result['advance_gate']['improved_mae_count'], 5)
        self.assertEqual(result['paired_bootstrap']['intervals']['weight.mae']['candidate_minus_baseline']['low'], -2)
        self.assertEqual(result['exact_id_mass_diagnostic']['candidate']['exact_id_gram_l1'], 8)
        self.assertEqual(len(result['candidate']['checks']), 10)

    def test_gate_exact_boundaries_and_no_rounding(self):
        baseline = score.summarize(*fixture(), bootstrap=0)['baseline']
        candidate = deepcopy(baseline)
        for value in candidate['primary']['metrics'].values():
            value['mae'] *= .9
            value['per_unit'] *= .9
            value['pass_mae'] = value['mae'] <= value['threshold_mae']
            value['pass_per_unit'] = value['per_unit'] <= value['threshold_per_unit']
        self.assertTrue(score.advance_gate(baseline, candidate)['advance'])
        for value in candidate['primary']['metrics'].values():
            value['mae'] += .0000001
            value['per_unit'] += .0000001
        self.assertFalse(score.advance_gate(baseline, candidate)['advance'])

    def test_zero_baseline_rejects_without_infinity(self):
        summary = score.summarize(*fixture(), bootstrap=0)
        summary['baseline']['primary']['metrics']['weight']['mae'] = 0
        gate = score.advance_gate(summary['baseline'], summary['candidate'])
        self.assertFalse(gate['valid'])
        self.assertFalse(gate['advance'])
        self.assertIsNone(gate['five_mae_ratios'])

    def test_previously_passed_cap_regression_blocks_otherwise_improved_profile(self):
        summary = score.summarize(*fixture(), bootstrap=0)
        baseline, candidate = summary['baseline'], summary['candidate']
        baseline['primary']['metrics']['fat']['mae'] = 5.0
        candidate['primary']['metrics']['fat']['mae'] = 5.25
        # Recompute from values: stale stored pass flags cannot hide crossing.
        candidate['primary']['metrics']['fat']['pass_mae'] = True
        gate = score.advance_gate(baseline, candidate)
        self.assertFalse(gate['advance'])
        self.assertFalse(gate['conditions']['no_previously_passed_check_regression'])

    def test_all_25_include_whole_fallback(self):
        records, rows, labels, ingredients = fixture()
        branch = records['s00']['candidate']
        branch.update(fallback=True, native_complete=False, raw_leaves=[])
        result = score.summarize(records, rows, labels, ingredients, bootstrap=0)
        self.assertEqual(result['candidate']['fallback_n'], 1)
        self.assertEqual(result['candidate']['primary']['n'], 25)
        self.assertGreater(result['exact_id_mass_diagnostic']['candidate']['unknown_grams'], 0)

    def test_missing_record_nan_negative_and_bad_state_are_rejected(self):
        for kind in ('missing', 'nan', 'negative', 'state'):
            records, rows, labels, ingredients = fixture()
            if kind == 'missing':
                records.pop('s00')
            elif kind in ('nan', 'negative'):
                records['s00']['candidate']['prediction']['weight'] = float('nan') if kind == 'nan' else -1
            else:
                records['s00']['candidate']['fallback'] = 1
            with self.assertRaises(ValueError):
                score.summarize(records, rows, labels, ingredients, bootstrap=0)

    def test_unknown_extra_omitted_mass_all_enter_l1(self):
        branch = {'fallback': False, 'prediction': {'weight': 8},
                  'raw_leaves': [{'ingredient_id': 'b', 'grams': 3}, {'ingredient_id': None, 'grams': 5}]}
        result = score._mass_diagnostic(branch, [{'ingredient_id': 'a', 'grams': 7}])
        self.assertEqual(result['exact_id_gram_l1'], 15)
        self.assertEqual(result['mass_overlap_dice'], 0)

    def test_incomplete_base_blocks_before_reference_reader_construction(self):
        with patch.object(score, 'verified_base', side_effect=ValueError('not_complete')), \
             patch.object(score, 'ReferenceReader', side_effect=AssertionError('reader constructed')) as reader:
            with self.assertRaisesRegex(ValueError, 'not_complete'):
                score.score()
            reader.assert_not_called()

    def test_bootstrap_same_sampling_is_reproducible(self):
        args = fixture()
        self.assertEqual(score.summarize(*args, bootstrap=100)['paired_bootstrap'],
                         score.summarize(*args, bootstrap=100)['paired_bootstrap'])

    def test_complete_score_artifact_replay_and_changed_base_block_before_reference_read(self):
        records, rows, labels, ingredients = fixture()
        with tempfile.TemporaryDirectory(prefix='synthetic-l-score-') as temp:
            root = Path(temp).resolve()
            (root / 'round6').mkdir(mode=0o700)
            for name in {*score.context.SOURCES, *score.SOURCE_NAMES}:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, path)
            release = root / score.context.TRAIN
            release.mkdir(parents=True)
            all_labels = deepcopy(labels)
            all_ingredients = [{'sample_id': sid, 'ingredients': items} for sid, items in ingredients.items()]
            for i in range(205):
                sid = 'unused%03d' % i
                all_labels[sid] = {'truth': {k: 1 for k in score.metrics.KEYS}}
                all_ingredients.append({'sample_id': sid, 'ingredients': [{'ingredient_id': 'ingr_0000000001', 'grams': 1}]})
            payloads = {'labels.json': score.canonical(all_labels),
                        'ingredients.json': score.canonical({'records': all_ingredients})}
            for name, raw in payloads.items():
                (release / name).write_bytes(raw)
            freeze = score.canonical({'artifacts': {k: hashlib.sha256(v).hexdigest() for k, v in payloads.items()}})
            (release / 'freeze.json').write_bytes(freeze)
            binding = {'phase': 'external_training_paired_pilot', 'method_config': deepcopy(score.context.METHOD_CONFIG),
                       'query_count': 25, 'query_groups': 25, 'pilot_rows': rows,
                       'input_sha256': {score.context.TRAIN + '/' + k: hashlib.sha256(v).hexdigest()
                                        for k, v in payloads.items()}}
            directory = root / score.BASE
            directory.mkdir(parents=True)
            (directory / 'intent.json').write_bytes(score.canonical({'binding': binding, 'expected_records': sorted(records)}))
            complete_raw = score.canonical({'synthetic_complete': True})
            (directory / 'completion.json').write_bytes(complete_raw)
            verified = {'records': records, 'binding': binding, 'completion_sha256': hashlib.sha256(complete_raw).hexdigest()}
            with patch.object(score.context, 'TRAIN_FREEZE_SHA256', hashlib.sha256(freeze).hexdigest()), \
                 patch.object(score, 'verified_base', return_value=verified):
                first = score.score(root=root)
                before = {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in root.rglob('*') if p.is_file()}
                second = score.score(root=root)
                self.assertEqual(first['metrics'], second['metrics'])
                self.assertEqual(second['status'], 'pilot_scoring_verified')
                self.assertEqual(before, {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                                         for p in root.rglob('*') if p.is_file()})
                changed = deepcopy(verified)
                changed['records']['s00']['candidate']['prediction']['weight'] += 1
                original_read = score.ReferenceReader.read
                opened_targets = []
                def watched(reader, name):
                    if name == score.context.TRAIN + '/labels.json':
                        opened_targets.append(name)
                    return original_read(reader, name)
                with patch.object(score, 'verified_base', return_value=changed), \
                     patch.object(score.ReferenceReader, 'read', watched):
                    with self.assertRaises(Exception):
                        score.score(root=root)
                self.assertEqual(opened_targets, [])


if __name__ == '__main__':
    unittest.main()
