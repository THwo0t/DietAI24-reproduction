from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import diagnostics_v2 as d


def fixture():
    rows, labels, baseline, selected = [], {}, [], []
    for i, weight in enumerate((100., 200., 300., 400.)):
        sid = str(i)
        row = {'sample_id': sid, 'dataset': 'nutrition5k', 'group_id': 'g' + sid,
               'fold': i % 2, 'split': 'dev'}
        truth = {k: weight for k in d.KEYS}
        rows.append(row)
        labels[sid] = {'truth': truth, 'split': 'dev'}
        pred = {'sample_id': sid, 'dataset': 'nutrition5k', 'final_codes': [],
                'primary_code': None, 'prediction': truth.copy()}
        selected.append(pred)
        other = deepcopy(pred)
        other['prediction'] = {k: weight * 2 for k in d.KEYS}
        baseline.append(other)
    return rows, labels, baseline, selected


def asa_fixture(baseline_hits=(0, 1, 2), selected_hits=(1, 2, 3), groups=None):
    rows, labels, baseline, selected = [], {}, [], []
    for i, weight in enumerate((10., 100., 300., 1000.)):
        sid = 'asa' + str(i)
        rows.append({'sample_id': sid, 'dataset': 'asa24', 'group_id': groups[i] if groups else 'g' + str(i),
                     'fold': 0, 'split': 'dev'})
        truth = dict.fromkeys(d.KEYS, weight)
        labels[sid] = {'truth': truth, 'food_code': '12345678', 'size': 'medium', 'split': 'dev'}
        for hits, ratio, destination in ((baseline_hits, 2, baseline), (selected_hits, 1.5, selected)):
            # Retained conditional payloads on non-Exact rows must not establish
            # membership. Contradictory ignored flags and E2E also must not count.
            codes = ['12345678'] if i in hits else ['87654321']
            destination.append({'sample_id': sid, 'dataset': 'asa24', 'final_codes': codes,
                'primary_code': codes[0], 'exact': i not in hits, 'retrieved_codes': ['12345678', '87654321'],
                'conditional': {'prediction': {k: weight * ratio for k in d.KEYS}, 'option_id': str(ratio)},
                'prediction': dict.fromkeys(d.KEYS, 0), 'e2e': {'prediction': dict.fromkeys(d.KEYS, 0)}})
    return rows, labels, baseline, selected


class DiagnosticsTests(unittest.TestCase):
    def test_asa_intersection_uses_identical_exact_images_and_option_predictions(self):
        args = asa_fixture()
        before = deepcopy(args)
        result = d.asa24_exact_intersection(*args, draws=30)
        self.assertTrue(result['diagnostic_only'])
        self.assertEqual((result['population_n'], result['n'], result['groups']), (4, 2, 2))
        self.assertEqual((result['baseline_exact_n'], result['selected_exact_n']), (3, 3))
        for arm, error, per_unit in (('baseline', 200, 1), ('selected', 100, .5)):
            self.assertEqual(result[arm]['n'], 2)
            for metric in result[arm]['metrics'].values():
                self.assertEqual(metric['mae'], error)
                self.assertEqual(metric['reference_mean'], 200)
                self.assertEqual(metric['per_unit'], per_unit)
        self.assertLess(result['paired_bootstrap']['intervals']['weight.mae']['high'], 0)
        self.assertEqual(result, d.asa24_exact_intersection(*args, draws=30))
        self.assertEqual(args, before)

    def test_asa_nonoverlap_does_not_fall_back_to_union_or_separate_denominators(self):
        result = d.asa24_exact_intersection(*asa_fixture((0, 1), (2, 3)), draws=20)
        self.assertEqual((result['n'], result['groups']), (0, 0))
        self.assertEqual(result['baseline_only_exact_n'], 2)
        self.assertEqual(result['selected_only_exact_n'], 2)
        self.assertIsNone(result['paired_bootstrap']['intervals'])
        for arm in ('baseline', 'selected'):
            self.assertEqual(result[arm]['n'], 0)
            self.assertIsNone(result[arm]['metrics']['weight']['mae'])

    def test_asa_one_group_has_no_interval_even_with_multiple_exact_images(self):
        result = d.asa24_exact_intersection(*asa_fixture(groups=['a', 'b', 'b', 'c']), draws=20)
        self.assertEqual((result['n'], result['groups']), (2, 1))
        self.assertEqual(result['paired_bootstrap']['reason'], 'fewer_than_two_groups')
        self.assertIsNone(result['paired_bootstrap']['intervals'])

    def test_asa_missing_conditional_does_not_shrink_intersection(self):
        args = asa_fixture()
        args[3][1]['conditional'] = None
        result = d.asa24_exact_intersection(*args, draws=20)
        self.assertEqual(result['n'], 2)
        self.assertEqual(result['selected']['n'], 2)
        self.assertEqual(result['selected']['available_n'], 1)
        self.assertIsNone(result['selected']['metrics']['weight']['mae'])
        self.assertEqual(result['baseline']['metrics']['weight']['mae'], 200)
        self.assertIsNone(result['paired_bootstrap']['intervals'])

    def test_asa_reference_zero_preserves_absolute_error_but_not_per_unit_interval(self):
        args = asa_fixture()
        for label in args[1].values():
            label['truth']['fat'] = 0
        result = d.asa24_exact_intersection(*args, draws=20)
        self.assertIsNotNone(result['selected']['metrics']['fat']['mae'])
        self.assertIsNone(result['selected']['metrics']['fat']['per_unit'])
        self.assertEqual(result['paired_bootstrap']['intervals']['fat.per_unit']['valid_replicates'], 0)

    def test_asa_diagnostic_is_integrated_without_mutating_registered_scores(self):
        nr, nl, nb, ns = fixture()
        ar, al, ab, ass = asa_fixture()
        args = nr + ar, {**nl, **al}, nb + ab, ns + ass
        before = d.scoring.evaluate(args[0], args[1], args[3])
        result = d.diagnostic_aggregates(*args, draws=20)
        self.assertEqual(result['asa24_common_exact_comparison']['n'], 2)
        self.assertEqual(before, d.scoring.evaluate(args[0], args[1], args[3]))
        self.assertEqual(result['same_population_comparison']['n'], 4)
        self.assertEqual(result['asa24_common_exact_comparison']['selected_exact_n'], 3)
        ar[0]['split'] = 'validation'
        with self.assertRaises(ValueError):
            d.asa24_exact_intersection(ar, al, ab, ass, draws=20)

    def test_fold_median_excludes_own_fold_and_reports_all_rows(self):
        result = d.diagnostic_aggregates(*fixture(), draws=50)
        score = result['median_baseline']['score']
        # folds: [100,300] and [200,400]; prediction medians: 300,200,300,200.
        self.assertEqual(score['n'], 4)
        self.assertEqual(score['metrics']['weight']['mae'], 100)
        self.assertEqual(score['metrics']['weight']['per_unit'], .4)

    def test_paired_resamples_direction_and_reproducibility(self):
        first = d.paired_n5(*fixture(), draws=100)
        self.assertEqual(first, d.paired_n5(*fixture(), draws=100))
        for interval in first['intervals'].values():
            self.assertLess(interval['high'], 0)
            self.assertEqual(interval['valid_replicates'], 100)

    def test_oracle_is_explicit_and_not_added_to_selection(self):
        rows, labels, baseline, selected = fixture()
        result = d.diagnostic_aggregates(rows, labels, selected, baseline, draws=20)
        oracle = result['oracle_weight_diagnostic']
        self.assertTrue(oracle['uses_reference_weight'])
        self.assertTrue(oracle['not_a_model_or_acceptance_result'])
        self.assertEqual(oracle['score']['metrics']['protein']['mae'], 0)
        self.assertEqual(result['same_population_comparison']['selected']['metrics']['weight']['mae'], 250)
        self.assertNotIn('candidate', result)
        self.assertEqual(baseline[0]['prediction']['weight'], 200)

    def test_zero_weight_exclusion_is_counted_only_in_oracle(self):
        args = fixture()
        args[3][0]['prediction']['weight'] = 0
        result = d.diagnostic_aggregates(*args, draws=20)
        self.assertEqual(result['same_population_comparison']['n'], 4)
        self.assertEqual(result['oracle_weight_diagnostic']['scored_n'], 3)
        self.assertEqual(result['oracle_weight_diagnostic']['excluded_nonpositive_weight_n'], 1)

    def test_missing_predictions_or_validation_provenance_rejected(self):
        rows, labels, baseline, selected = fixture()
        with self.assertRaises(ValueError):
            d.diagnostic_aggregates(rows, labels, baseline[:-1], selected, draws=10)
        rows[0]['split'] = 'validation'
        with self.assertRaises(ValueError):
            d.diagnostic_aggregates(rows, labels, baseline, selected, draws=10)


if __name__ == '__main__':
    unittest.main()
