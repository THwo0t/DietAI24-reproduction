import copy
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from round6.src import train_context as ctx


def inputs(n=230):
    rows, ingredients, targets, vectors = [], {}, {}, {}
    for i in range(n):
        sid = 's%03d' % i
        rows.append({'sample_id': sid, 'group_id': 'g%03d' % i,
            'image_path': '/invented/' + sid + '.png',
            'image_sha256': hashlib.sha256(('bytes' + sid).encode()).hexdigest(),
            'rgb_sha256': hashlib.sha256(('rgb' + sid).encode()).hexdigest()})
        ingredients[sid] = [{'ingredient_id': 'ingr_%010d' % i, 'name': 'ingredient %d' % i,
            'grams': 10.0 + i, 'nutrients': {k: (10.0 + i) * (j + 1) / 10
                                           for j, k in enumerate(ctx.TARGETS[1:])}}]
        targets[sid] = {k: float(i + j + 1) for j, k in enumerate(ctx.TARGETS)}
        vectors[sid] = [1.0, float(i + 1)] + [0.0] * 3070
    return rows, ingredients, targets, vectors


class TrainContextTests(unittest.TestCase):
    def test_fixed_population_folds_queries_and_no_target_views(self):
        data = inputs()
        views = ctx.build_views(*data)
        self.assertEqual(len(views['queries']), 25)
        self.assertEqual([sum(r['fold'] == fold for r in views['rows']) for fold in range(5)], [5] * 5)
        self.assertNotIn('official_targets', views)
        for query in views['queries']:
            self.assertEqual(set(query), {'query_id', 'image_path', 'screening_group_id', 'image_sha256', 'rgb_sha256'})
        for fold, assets in views['fold_assets'].items():
            self.assertEqual(len(assets['supports']), 184)
            self.assertEqual(len(assets['catalog']), 184)
            heldout = set(views['fold_audit'][str(fold)]['heldout_ids'])
            self.assertFalse(heldout & set(assets['supports']))
            self.assertTrue(all(views['group_folds'][e['screening_group_id']] != fold
                                for e in views['fold_entries'][fold]))

    def test_heldout_supervision_poison_cannot_change_that_fold_assets(self):
        rows, ingredients, targets, vectors = inputs()
        initial = ctx.build_views(rows, ingredients, targets, vectors)
        altered_i, altered_t = copy.deepcopy(ingredients), copy.deepcopy(targets)
        for sid in initial['fold_audit']['0']['heldout_ids']:
            altered_i[sid] = [{'ingredient_id': 'ingr_%010d' % (int(sid[1:]) + 10000),
                              'name': 'heldout-only poison', 'grams': 9000.0,
                              'nutrients': {k: 7000.0 for k in ctx.TARGETS[1:]}}]
            altered_t[sid] = {k: 8000.0 for k in ctx.TARGETS}
        changed = ctx.build_views(rows, altered_i, altered_t, vectors)
        for key in ('fold_assets', 'fold_entries', 'fold_vectors', 'fold_annotation_names'):
            self.assertEqual(initial[key][0], changed[key][0])
        self.assertEqual(initial['queries'], changed['queries'])
        self.assertEqual(initial['query_vectors'], changed['query_vectors'])

    def test_fold_densities_and_fallback_use_training_rows_only(self):
        rows, ingredients, targets, vectors = inputs()
        for sid in ingredients:
            ingredients[sid][0]['ingredient_id'] = 'ingr_0000000001'
            ingredients[sid][0]['name'] = 'shared name'
        result = ctx.build_views(rows, ingredients, targets, vectors)
        for fold, assets in result['fold_assets'].items():
            train_ids = result['fold_audit'][str(fold)]['training_ids']
            expected = 100 * sum(ingredients[s][0]['nutrients']['energy'] for s in train_ids) / sum(
                ingredients[s][0]['grams'] for s in train_ids)
            self.assertAlmostEqual(assets['catalog'][0]['density_per_100g']['energy'], expected)
            import statistics
            self.assertEqual(assets['fallback']['weight'], statistics.median(targets[s]['weight'] for s in train_ids))

    def test_reordering_input_does_not_change_views(self):
        rows, *rest = inputs()
        first = ctx.build_views(rows, *rest)
        second = ctx.build_views(list(reversed(rows)), *rest)
        self.assertEqual(first, second)

    def test_missing_supervision_duplicate_group_or_bad_vector_rejected(self):
        for mutation in ('missing', 'duplicate_group', 'nonfinite'):
            rows, ingredients, targets, vectors = inputs()
            if mutation == 'missing':
                targets.pop(rows[0]['sample_id'])
            elif mutation == 'duplicate_group':
                rows[0]['group_id'] = rows[1]['group_id']
            else:
                vectors[rows[0]['sample_id']][0] = float('nan')
            with self.assertRaises(ValueError):
                ctx.build_views(rows, ingredients, targets, vectors)

    def test_pilot_selection_is_fixed_and_ignores_labels(self):
        folds = {str(i): i % 5 for i in range(230)}
        one = ctx.pilot_groups(folds)
        two = ctx.pilot_groups(dict(reversed(list(folds.items()))))
        self.assertEqual(one, two)
        self.assertEqual(len(set(one)), 25)
        self.assertEqual([sum(folds[g] == fold for g in one) for fold in range(5)], [5] * 5)


if __name__ == '__main__':
    unittest.main()
