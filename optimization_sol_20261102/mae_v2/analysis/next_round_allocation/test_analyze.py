"""Synthetic mathematical checks; no private data/image/provider reads."""
import unittest

import numpy as np

from analyze import grouped_folds, project, score, solve


class AllocationTests(unittest.TestCase):
    def test_simplex_analytic_projection(self):
        np.testing.assert_allclose(project([.2, -.4, 1.3]), [0, 0, 1], atol=1e-14)
        np.testing.assert_allclose(project([.8, .8]), [.5, .5], atol=1e-14)

    def test_bounded_projection_hits_both_bounds(self):
        lo, hi = np.array([.1, .2, .1]), np.array([.4, .5, .6])
        x = project([2, -1, .3], lo, hi)
        np.testing.assert_allclose(x, [.4, .2, .4], atol=1e-13)

    def test_projection_agrees_with_independent_bisection(self):
        v = np.array([-.32, 1.5, .7, -.2])
        lo, hi = np.array([.1, .05, .1, .2]), np.array([.4, .4, .3, .7])
        left, right = -10., 10.
        for _ in range(100):
            mid = (left + right) / 2
            if np.clip(v - mid, lo, hi).sum() > 1:
                left = mid
            else:
                right = mid
        np.testing.assert_allclose(project(v, lo, hi), np.clip(v - (left + right) / 2, lo, hi), atol=1e-13)

    def test_infeasible_box_rejected(self):
        with self.assertRaises(ValueError):
            project([0, 0], np.array([.6, .6]), np.ones(2))

    def test_solver_recovers_known_interior_solution(self):
        x, d = solve(np.eye(3), np.array([.2, .3, .5]), [.8, .1, .1])
        np.testing.assert_allclose(x, [.2, .3, .5], atol=1e-10)
        self.assertTrue(d["converged"])
        self.assertLess(d["frank_wolfe_gap"], 1e-10)

    def test_solver_boundary_certificate_and_determinism(self):
        args = (np.eye(2), np.array([2., -1.]), [.5, .5])
        x, d = solve(*args)
        np.testing.assert_allclose(x, [1, 0], atol=1e-12)
        y, e = solve(*args)
        self.assertEqual(d, e)
        np.testing.assert_array_equal(x, y)
        self.assertLess(d["frank_wolfe_gap"], 1e-12)

    def test_solver_box_solution(self):
        x, d = solve(np.eye(2), [1., 0.], [.5, .5], np.array([.1, .3]), np.array([.6, .9]))
        np.testing.assert_allclose(x, [.6, .4], atol=1e-12)
        self.assertTrue(d["converged"])
        self.assertLess(d["simplex_and_bound_violation"], 1e-13)
        self.assertLess(d["frank_wolfe_gap"], 1e-12)

    def test_score_strict_no_rounded_acceptance(self):
        truth = np.ones((2, 5))
        equal = score(truth + 1, truth, np.ones(5), np.ones(5))
        self.assertEqual(equal["checks_passed_of_10"], 0)
        less = score(truth + .99999999, truth, np.ones(5), np.ones(5))
        self.assertEqual(less["checks_passed_of_10"], 10)

    def test_group_fold_overlap_rejected(self):
        rows = [{"group_id": str(k), "fold": k} for k in range(5)]
        folds, count = grouped_folds(rows)
        self.assertEqual(count, 5)
        np.testing.assert_array_equal(folds, range(5))
        rows.append({"group_id": "0", "fold": 1})
        with self.assertRaises(ValueError):
            grouped_folds(rows)


if __name__ == "__main__":
    unittest.main()
