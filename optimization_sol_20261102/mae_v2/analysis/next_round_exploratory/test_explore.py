"""Synthetic negative checks; no research input files are opened by these tests."""
import unittest

import numpy as np

import explore as e


class ExploratoryTests(unittest.TestCase):
    def fixture(self):
        rng = np.random.default_rng(40)
        x = rng.uniform(2, 25, (20, 5))
        y = x * [1.2, .7, .8, 1.3, .9] + [1, 3, 1, 2, 1]
        return x, y, np.repeat(np.arange(5), 4), np.array(['synthetic_%d' % i for i in range(20)])

    def test_l1_scale_and_tie(self):
        self.assertEqual(e.scalar_fit(np.array([1., 1.]), np.array([.5, 2.])), 1)
        x, y = np.array([1., 2., 3.]), np.array([2., 4., 6.])
        self.assertEqual(e.scalar_fit(x, y), 2)

    def test_exact_two_parameter_solution(self):
        x = np.array([[1., 5.], [2., 1.], [3., 2.], [4., 7.]])
        np.testing.assert_allclose(e.lad_two(x, x @ [2., .3], second_nonnegative=True), [2., .3])
        x[:, 1] = 1
        np.testing.assert_allclose(e.lad_two(x, x @ [2., -.3], second_nonnegative=False), [2., -.3])

    def test_nonnegative_constraint(self):
        x = np.array([[1., 5.], [2., 1.], [3., 2.], [4., 7.]])
        result = e.lad_two(x, np.array([10., 1., 2., 10.]), second_nonnegative=True)
        self.assertTrue(np.all(result >= 0))

    def test_group_leak_fails(self):
        x, y, folds, groups = self.fixture()
        groups[4] = groups[0]
        with self.assertRaisesRegex(ValueError, 'group spans folds'):
            e.oof('scale', x, y, folds, groups)

    def test_outer_labels_do_not_enter_fits(self):
        x, y, folds, groups = self.fixture()
        changed = y.copy()
        changed[folds == 0] *= 80
        for family in e.FAMILIES:
            a, _ = e.oof(family, x, y, folds, groups)
            b, _ = e.oof(family, x, changed, folds, groups)
            np.testing.assert_array_equal(a[folds == 0], b[folds == 0])
            self.assertEqual(a.shape, x.shape)

    def test_outer_labels_do_not_enter_inner_choice(self):
        x, y, folds, groups = self.fixture()
        changed = y.copy()
        changed[folds == 0] *= 80
        a, ca = e.nested_oof(x, y, folds, groups)
        b, cb = e.nested_oof(x, changed, folds, groups)
        np.testing.assert_array_equal(a[folds == 0], b[folds == 0])
        self.assertEqual(ca[0], cb[0])

    def test_missing_never_dropped_and_full_denominator(self):
        x, y, folds, groups = self.fixture()
        self.assertEqual(e.score(x, y)['n'], 20)
        x[1, 1] = np.nan
        with self.assertRaises(ValueError):
            e.oof('scale', x, y, folds, groups)

    def test_per_unit_is_ratio_of_mae_to_reference_mean(self):
        x = np.array([[1., 1., 1., 1., 1.], [10., 10., 10., 10., 10.]])
        y = np.array([[2., 2., 2., 2., 2.], [10., 10., 10., 10., 10.]])
        result = e.score(x, y)['metrics']['weight']
        self.assertAlmostEqual(result['per_unit'], .5 / 6)
        self.assertNotAlmostEqual(result['per_unit'], .25)


if __name__ == '__main__':
    unittest.main()
