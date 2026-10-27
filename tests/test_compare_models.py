"""F5: pairing and bootstrap behavior, verified on small hand-computable data."""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
import compare_models as comparison


class TestPairing(unittest.TestCase):
    def test_reorders_by_sample_key_and_rejects_drift(self):
        left = pd.DataFrame({'id': ['a', 'b'], 'label': [2., 3.], 'prediction': [1., 5.]})
        right = left.iloc[::-1].copy()
        a, b = comparison.align(left, right, ['id'], ['label'])
        pd.testing.assert_frame_equal(a, b)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            comparison.align(left, pd.concat([right, right]), ['id'], ['label'])
        with self.assertRaisesRegex(ValueError, 'keys differ'):
            comparison.align(left, right.iloc[:1], ['id'], ['label'])
        right.loc[right.id == 'a', 'label'] = 99
        with self.assertRaises(AssertionError):
            comparison.align(left, right, ['id'], ['label'])


class TestPairedBootstrap(unittest.TestCase):
    def test_identical_answers_have_zero_interval_with_clustered_failures(self):
        errors = [1., 10., np.nan, 3., 9., np.nan]
        out = comparison.bootstrap_difference(errors, errors, ['a'] * 3 + ['b'] * 3, replicates=1000)
        self.assertEqual(out['ci95'], [0., 0.])
        self.assertEqual(out['n'], [4, 4])
        self.assertEqual(out['groups_with_estimate'], [2, 2])

    def test_three_sizes_stay_together(self):
        # The three sizes of a code are perfectly linked. Drawing two codes
        # gives differences 0, 5 or 10; incorrectly drawing six rows instead
        # would narrow the percentile interval to about 1.67--8.33.
        left = [0.] * 6
        right = [0., 0., 0., 10., 10., 10.]
        out = comparison.bootstrap_difference(left, right, ['a'] * 3 + ['b'] * 3, replicates=1000)
        self.assertEqual(out['difference'], 5.)
        self.assertEqual(out['ci95'], [0., 10.])

    def test_common_subset_does_not_mix_different_success_sets(self):
        cols = comparison.evaluate.TARGETS
        reference = pd.DataFrame({t: [10., 10., 10.] for t in cols})
        left = pd.DataFrame({t: [11., 100., 13.] for t in cols})
        right = pd.DataFrame({t: [100., 12., 11.] for t in cols})
        selected_left, selected_right = pd.Series([True, False, True]), pd.Series([False, True, True])
        result = comparison.mae_comparison(left, right, reference, ['a', 'b', 'c'],
                                          selected_left, selected_right, common=True)
        for cell in result.values():
            self.assertEqual(cell['n'], [1, 1])
            self.assertEqual(cell['difference'], -2.)
            self.assertEqual(cell['ci95'], [-2., -2.])
            self.assertGreater(cell['replicates_without_estimate'], 0)
            np.testing.assert_allclose(cell['per_unit'], [.3, .1])

    def test_no_success_is_explicit(self):
        out = comparison.bootstrap_difference([np.nan], [np.nan], ['a'], replicates=10)
        self.assertIsNone(out['difference'])
        self.assertEqual(out['ci95'], [None, None])
        self.assertEqual(out['replicates_without_estimate'], 10)


if __name__ == '__main__':
    unittest.main()
