"""Small negative and positive witnesses for the scientific diagnostic."""
from itertools import combinations
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'runtime/packages'), str(HERE)]
import numpy as np
import joint_lp as lp


class CommonMassTests(unittest.TestCase):
    def setUp(self):
        self.thresholds = {k:(1.0, 1.0) for k in lp.TARGETS}

    def test_single_shared_mass_and_exact_rescore(self):
        truth = np.asarray([[20.,40.,2.,6.,4.]])
        d = [[[1.,2.,.1,.3,.2]]]
        result, witness = lp.analyze(d,[None],truth,self.thresholds)
        self.assertEqual(result['classification'],'shared_witness')
        self.assertEqual(result['attempts'][0]['common_witness_scores']['failed_checks'],0)
        self.assertAlmostEqual(witness['masses'][0],20.)

    def test_joint_incompatibility_despite_coordinate_optima(self):
        # Every target is individually exact at a different mass, but common
        # mass cannot satisfy 8/10 narrow checks. No spliced oracle is admitted.
        truth = np.asarray([[1.,10.,20.,30.,40.]])
        caps = {k:(.01,.0001) for k in lp.TARGETS}
        result, witness = lp.analyze([[[1.,1.,1.,1.,1.]]],[None],truth,caps)
        self.assertIsNone(witness)
        self.assertEqual(result['classification'],'verified_numerical_negative')
        self.assertTrue(all(a['dual']['exact_binary_coefficient_dual_feasible'] for a in result['attempts']))
        self.assertTrue(all(a['dual']['lower_bound']>1 for a in result['attempts']))

    def test_fallback_stays_in_denominator_and_budget(self):
        truth = np.ones((2,5))*10
        result, _ = lp.analyze([[[1.,1.,1.,1.,1.]],[]],[None,[100.,100.,100.,100.,100.]],truth,self.thresholds)
        self.assertEqual(result['population_n'],2)
        self.assertEqual(result['fallback_n'],1)
        self.assertEqual(result['classification'],'verified_numerical_negative')

    def test_per_unit_mean_and_inclusive_boundary(self):
        truth = np.asarray([[2.,2.,2.,2.,2.],[18.,18.,18.,18.,18.]])
        pred = truth+1
        caps = {k:(1.,.1) for k in lp.TARGETS}
        scores = lp.point_metrics(truth,pred,caps)
        self.assertEqual(scores['failed_checks'],0)
        self.assertEqual(scores['metrics']['weight']['per_unit'],.1)

    def test_all_retained_eight_effective_patterns_covered(self):
        truth = np.ones((1,5))*10
        caps = {k:(1.,.2) for k in lp.TARGETS}
        unique = list(lp.patterns(truth,caps))
        vectors = {tuple(p['effective_caps']) for p in unique}
        raw = [1.,2.]*5
        expected = {tuple(min((raw[j] for j in keep if j//2==k),default=None) for k in range(5))
                    for keep in combinations(range(10),8)}
        self.assertEqual(vectors,expected)
        self.assertEqual(len(vectors),21)

    def test_density_unit_and_mass_conservation(self):
        # Gram density .02 represents 2g/100g, two physical masses count once.
        truth = np.asarray([[30.,60.,.6,3.,6.]])
        result, witness = lp.analyze([[[1.,2.,.02,.1,.2],[1.,2.,.02,.1,.2]]],[None],truth,self.thresholds)
        self.assertEqual(result['classification'],'shared_witness')
        self.assertAlmostEqual(sum(witness['masses']),30.)
        self.assertAlmostEqual(witness['prediction'][0][2],.6)

    def test_dual_repair_closes_all_column_violations(self):
        truth = np.ones((1,5))*10
        p = lp.problem([[[1.,1.,1.,1.,1.]]],[None],truth,(1.,)*5)
        # Inconsistent plus/minus gives a positive mass-column violation;
        # rebuilding budgets also has to fix e columns and normalize t.
        y = np.zeros(len(p['b']))
        for pair in p['pairs']:
            for plus,minus in pair.values():
                y[plus] = -.01; y[minus] = -.5
        cert = lp.exact_dual_certificate(p,y)
        self.assertTrue(cert['exact_binary_coefficient_dual_feasible'])
        self.assertLessEqual(cert['lower_bound'],0.)

    def test_unsuccessful_solver_is_indeterminate(self):
        from types import SimpleNamespace
        with patch.object(lp,'linprog',return_value=SimpleNamespace(status=1,success=False,nit=0,x=None)):
            result, witness = lp.analyze([[[1.,1.,1.,1.,1.]]],[None],np.ones((1,5)),self.thresholds)
        self.assertEqual(result['classification'],'numerically_indeterminate')
        self.assertIsNone(witness)

    def test_illegal_density_and_mass_column_rejected(self):
        for matrix in ([[1.,float('nan'),1.,1.,1.]],[[1.,-1.,1.,1.,1.]],[[2.,1.,1.,1.,1.]]):
            with self.assertRaises(ValueError):
                lp.problem([matrix],[None],np.ones((1,5)),(1.,)*5)


if __name__ == '__main__':
    unittest.main()
