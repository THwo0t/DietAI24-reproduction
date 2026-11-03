"""Invented vectors/labels only: arithmetic, grouped isolation and fixed gate."""
from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from round5.src import gram_prior as p


def vector(index=0, sign=1.0):
    value = [0.0] * p.DIMENSIONS
    value[index] = sign
    return value


def item(identifier, grams, *, energy=1, fat=.1, carbs=.2, protein=.3):
    return {'ingredient_id': identifier, 'grams': grams,
            'nutrients': {k: grams * factor for k, factor in
                          [('energy', energy), ('fat', fat), ('carbs', carbs), ('protein', protein)]}}


def official(grams):
    return {'weight': grams, 'energy': grams, 'fat': grams * .1,
            'carbs': grams * .2, 'protein': grams * .3}


def fixture(n=10):
    rows, vectors, ingredients, targets = [], {}, {}, {}
    for index in range(n):
        sid = f's{index:03d}'
        rows.append({'sample_id': sid, 'group_id': f'g{index:03d}'})
        value = vector(index % 4)
        value[5] = (index + 1) / n
        vectors[sid] = value
        mass = 30 + index * 3
        ingredients[sid] = [item('ingredient-a' if index % 2 == 0 else 'ingredient-b', mass)]
        targets[sid] = official(mass)
    return rows, vectors, ingredients, targets


class PriorTests(unittest.TestCase):
    def test_two_row_hand_solution_uses_linear_kernel_lambda_one_and_intercept(self):
        vectors = {'a': vector(), 'b': vector(sign=-1)}
        ingredients = {'a': [item('food', 10)], 'b': [item('food', 30)]}
        model = p.fit(vectors, ingredients, {'a': official(10), 'b': official(30)}, ['b', 'a'])
        self.assertEqual(model.train_ids, ('a', 'b'))
        self.assertEqual(model.ingredient_ids, ('food',))
        # X=[+1,-1], mean(Y)=20; B=-20/3 for (K+I)^-1.
        self.assertAlmostEqual(model.coefficients[0, 0], -20 / 3)
        self.assertAlmostEqual(model.gram_mean[0], 20)
        self.assertAlmostEqual(p.predict(model, vector())['prediction']['weight'], 40 / 3)
        self.assertAlmostEqual(p.predict(model, vector(sign=-1))['prediction']['weight'], 80 / 3)
        self.assertAlmostEqual(p.predict(model, vector(1))['prediction']['weight'], 20)
        self.assertAlmostEqual(p.predict(model, vector())['prediction']['protein'], 4)

    def test_normalization_is_identical_for_scaled_input_embedding(self):
        _, vectors, ingredients, targets = fixture()
        model = p.fit(vectors, ingredients, targets, list(vectors))
        query = vectors['s000']
        a, b = p.predict(model, query), p.predict(model, [v * 17 for v in query])
        for key in p.TARGETS:
            self.assertAlmostEqual(a['prediction'][key], b['prediction'][key], places=12)

    def test_density_is_mass_pooled_not_unweighted_mean_and_fallback_official(self):
        vectors = {'a': vector(), 'b': vector(1)}
        ingredients = {'a': [item('food', 10, energy=2)], 'b': [item('food', 30, energy=1)]}
        model = p.fit(vectors, ingredients, {'a': official(100), 'b': official(200)}, ['a', 'b'])
        self.assertEqual(model.density_per_100g['food']['energy'], 125)
        self.assertEqual(model.fallback['weight'], 150)

    def test_train_subset_never_inspects_unselected_sentinel_values(self):
        vectors = {'a': vector(), 'heldout': object()}
        ingredients = {'a': [item('training-food', 20)], 'heldout': object()}
        targets = {'a': official(20), 'heldout': object()}
        model = p.fit(vectors, ingredients, targets, ['a'])
        self.assertEqual(model.ingredient_ids, ('training-food',))
        self.assertEqual(p.predict(model, vector())['prediction']['weight'], 20)

    def test_true_training_label_changes_fit_so_isolation_test_is_not_vacuous(self):
        vectors = {'a': vector(), 'b': vector(1)}
        ingredients = {'a': [item('food', 20)], 'b': [item('food', 30)]}
        targets = {'a': official(20), 'b': official(30)}
        first = p.predict(p.fit(vectors, ingredients, targets, ['a', 'b']), vector())
        ingredients['a'] = [item('food', 200)]
        second = p.predict(p.fit(vectors, ingredients, targets, ['a', 'b']), vector())
        self.assertNotEqual(first['prediction'], second['prediction'])

    def test_duplicate_id_rows_are_summed_and_zero_rows_do_not_add_catalogue_ids(self):
        ingredients = {'a': [item('food', 10), item('food', 15), item('absent', 0)]}
        model = p.fit({'a': vector()}, ingredients, {'a': official(25)}, ['a'])
        self.assertEqual(model.ingredient_ids, ('food',))
        self.assertEqual(p.predict(model, vector())['ingredient_grams'], {'food': 25})
        ingredients['a'][-1]['nutrients']['energy'] = 1
        with self.assertRaisesRegex(p.PriorError, 'zero_mass_nonzero_nutrients'):
            p.fit({'a': vector()}, ingredients, {'a': official(25)}, ['a'])

    def test_negative_clipping_and_all_zero_fallback_do_not_fabricate_ingredients(self):
        model = p.fit({'a': vector()}, {'a': [item('a', 5), item('b', 10)]}, {'a': official(18)}, ['a'])
        zero_coefficients = np.zeros_like(model.coefficients)
        partial = replace(model, gram_mean=np.array([-5.0, 8.0]), coefficients=zero_coefficients)
        result = p.predict(partial, vector())
        self.assertEqual(result['ingredient_grams'], {'a': 0, 'b': 8})
        self.assertEqual(result['prediction']['weight'], 8)
        self.assertEqual(result['audit']['negative_gram_magnitude_clipped'], 5)
        empty = replace(model, gram_mean=np.array([-5.0, -8.0]), coefficients=zero_coefficients)
        result = p.predict(empty, vector())
        self.assertTrue(result['fallback'])
        self.assertEqual(result['ingredient_grams'], {})
        self.assertEqual(result['prediction'], official(18))

    def test_balanced_230_group_folds_stable_under_permutation(self):
        groups = [f'group-{index}' for index in range(230)]
        actual = p.assign_folds(groups)
        self.assertEqual(actual, p.assign_folds(list(reversed(groups)) + groups[:10]))
        self.assertEqual([sum(v == fold for v in actual.values()) for fold in range(5)], [46] * 5)

    def test_whole_heldout_fold_label_poisoning_cannot_change_its_predictions(self):
        rows, vectors, ingredients, targets = fixture()
        initial = p.evaluate_oof(rows, vectors, ingredients, targets, expected_n=10, expected_groups=10)
        chosen = initial['fold_audit'][0]
        altered_ingredients, altered_targets = deepcopy(ingredients), deepcopy(targets)
        for sid in chosen['heldout_ids']:
            altered_ingredients[sid] = [item('query-only-poison-ingredient', 100000)]
            altered_targets[sid] = official(123456)
        altered = p.evaluate_oof(rows, vectors, altered_ingredients, altered_targets, expected_n=10, expected_groups=10)
        for sid in chosen['heldout_ids']:
            self.assertEqual(initial['oof_predictions'][sid], altered['oof_predictions'][sid])
            self.assertNotIn('query-only-poison-ingredient', altered['oof_predictions'][sid]['ingredient_grams'])
        self.assertEqual(initial['fold_audit'][0], altered['fold_audit'][0])

    def test_duplicate_group_members_never_cross_fold(self):
        rows, vectors, ingredients, targets = fixture()
        rows[1]['group_id'] = rows[0]['group_id']
        result = p.evaluate_oof(rows, vectors, ingredients, targets, expected_n=10, expected_groups=9)
        self.assertEqual(result['oof_predictions']['s000']['fold'], result['oof_predictions']['s001']['fold'])
        for fold in result['fold_audit']:
            self.assertFalse(set(fold['train_groups']) & set(fold['heldout_groups']))

    def test_full_oof_keeps_official_minus_two_gram_truth_and_exact_full_denominator(self):
        rows, vectors, ingredients, targets = fixture()
        targets['s000']['weight'] -= 2
        result = p.evaluate_oof(rows, vectors, ingredients, targets, expected_n=10, expected_groups=10)
        aggregate = result['aggregate']
        self.assertEqual(len(result['oof_predictions']), 10)
        audit = aggregate['official_minus_ingredient_totals']['weight']
        self.assertEqual(audit, {'nonzero_at_0_001_n': 1, 'signed_sum': -2, 'min': -2, 'max': 0})
        for key in p.TARGETS:
            manual = math.fsum(abs(result['oof_predictions'][sid]['prediction'][key] - targets[sid][key])
                               for sid in targets) / 10
            self.assertEqual(aggregate['candidate_mae'][key], manual)
            baseline_errors = []
            for fold in result['fold_audit']:
                training_values = sorted(targets[sid][key] for sid in fold['train_ids'])
                median = (training_values[3] + training_values[4]) / 2
                baseline_errors.extend(abs(median - targets[sid][key]) for sid in fold['heldout_ids'])
            self.assertEqual(aggregate['fold_median_baseline_mae'][key], math.fsum(baseline_errors) / 10)
        self.assertEqual(targets['s000']['weight'], 28)
        self.assertEqual(ingredients['s000'][0]['grams'], 30)
        json.dumps(result, allow_nan=False)

    def test_registered_default_population_scores_every_one_of_230_rows(self):
        rows, vectors, ingredients, targets = fixture(230)
        result = p.evaluate_oof(rows, vectors, ingredients, targets)
        self.assertEqual(result['aggregate']['n'], 230)
        self.assertEqual(result['aggregate']['groups'], 230)
        self.assertEqual(len(result['oof_predictions']), 230)
        self.assertEqual([len(fold['heldout_ids']) for fold in result['fold_audit']], [46] * 5)
        self.assertEqual([len(fold['train_ids']) for fold in result['fold_audit']], [184] * 5)
        self.assertEqual(result['aggregate']['api_calls'], 0)

    def test_all_whole_fallbacks_keep_full_mae_denominator_and_no_fake_composition(self):
        rows, vectors, ingredients, targets = fixture()
        fit = p.fit
        def negative_model(*args, **kwargs):
            model = fit(*args, **kwargs)
            return replace(model, gram_mean=-np.ones_like(model.gram_mean),
                           coefficients=np.zeros_like(model.coefficients))
        with patch.object(p, 'fit', negative_model):
            result = p.evaluate_oof(rows, vectors, ingredients, targets, expected_n=10, expected_groups=10)
        aggregate = result['aggregate']
        self.assertEqual(len(result['oof_predictions']), 10)
        self.assertEqual(aggregate['whole_fallback_n'], 10)
        self.assertEqual(aggregate['candidate_mae'], aggregate['fold_median_baseline_mae'])
        self.assertEqual(aggregate['composition']['evaluated_nonfallback_n'], 0)
        self.assertEqual(aggregate['composition']['excluded_whole_fallback_n'], 10)
        self.assertIsNone(aggregate['composition']['ingredient_l1_grams_mean'])
        self.assertFalse(aggregate['advance_gate']['advance'])

    def test_gate_exact_boundaries_zero_baseline_and_nonfinite_never_emit_inf(self):
        baseline = {k: 10.0 for k in p.TARGETS}
        good = dict(zip(p.TARGETS, [8.0, 8.0, 8.0, 11.0, 10.0]))
        self.assertTrue(p.advance_gate(good, baseline)['advance'])
        beyond = {**good, 'carbs': 11.0000000001}
        self.assertFalse(p.advance_gate(beyond, baseline)['advance'])
        self.assertFalse(p.advance_gate(baseline, baseline)['advance'])
        only_two = dict(zip(p.TARGETS, [8, 8, 10, 10, 10]))
        self.assertFalse(p.advance_gate(only_two, baseline)['advance'])
        for zero in (0.0, float('inf'), float('nan')):
            result = p.advance_gate(good, {**baseline, 'fat': zero})
            self.assertFalse(result['valid'])
            self.assertFalse(result['advance'])
            self.assertIsNone(result['ratios'])
            json.dumps(result, allow_nan=False)

    def test_composition_diagnostics_count_extra_mass_without_pruning(self):
        records = {'a': {'ingredient_grams': {'present': 9.5, 'absent': .5}, 'fallback': False,
                         'audit': {'negative_gram_count_clipped': 1, 'negative_gram_magnitude_clipped': 2}},
                   'b': {'ingredient_grams': {}, 'fallback': True}}
        ingredients = {'a': [item('present', 10), item('missed', 3)], 'b': [item('other', 50)]}
        result = p._composition(records, ingredients)
        self.assertEqual(result['positive_id_count_mean'], 2)
        self.assertEqual(result['at_least_one_gram_id_count_mean'], 1)
        self.assertEqual(result['absent_id_mass_grams_mean'], .5)
        self.assertEqual(result['absent_id_mass_fraction_pooled'], .05)
        self.assertEqual(result['omitted_true_id_mass_grams_mean'], 3)
        self.assertEqual(result['ingredient_l1_grams_mean'], 4)
        self.assertEqual(result['excluded_whole_fallback_n'], 1)
        self.assertEqual(records['a']['ingredient_grams']['absent'], .5)

    def test_population_missing_labels_and_malformed_values_are_rejected(self):
        rows, vectors, ingredients, targets = fixture()
        with self.assertRaisesRegex(p.PriorError, 'registered_population_changed'):
            p.evaluate_oof(rows, vectors, ingredients, targets)
        missing = dict(targets)
        missing.pop('s000')
        with self.assertRaisesRegex(p.PriorError, 'input_population_changed'):
            p.evaluate_oof(rows, vectors, ingredients, missing, expected_n=10, expected_groups=10)
        for invalid in (True, -1.0, float('nan')):
            wrong = deepcopy(ingredients)
            wrong['s000'][0]['grams'] = invalid
            with self.assertRaises(p.PriorError):
                p.fit(vectors, wrong, targets, ['s000'])
        for invalid in ([0] * p.DIMENSIONS, [1] * (p.DIMENSIONS - 1), [True] * p.DIMENSIONS):
            with self.assertRaises(p.PriorError):
                p.fit({'s000': invalid}, ingredients, targets, ['s000'])

    def test_rows_reordered_produce_identical_oof_results(self):
        rows, vectors, ingredients, targets = fixture()
        a = p.evaluate_oof(rows, vectors, ingredients, targets, expected_n=10, expected_groups=10)
        b = p.evaluate_oof(list(reversed(rows)), vectors, ingredients, targets, expected_n=10, expected_groups=10)
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
