"""Synthetic offline contract and failure-propagation tests."""
from copy import deepcopy
from itertools import product
import unittest

import paired_accounting as p
import paired_failure as f
import test_paired_accounting as fixtures


class FailureTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.PairedAccountingTests()
        fixture.setUp()
        self.items, self.foods = fixture.items, fixture.foods
        self.stages = [dict(status='native', value=value) for value in (
            fixture.original, p.parse_quantity(fixture.qraw, self.items),
            p.parse_density(fixture.draw, self.items))]
        self.median = dict(zip(p.TARGETS, (123, 456, 7, 8, 9)))
        self.binding = 'a' * 64

    def run_profiles(self, stages=None, **kwargs):
        return f.compose_profiles(self.items, self.foods, *(stages or self.stages),
                                  self.median, self.binding, **kwargs)

    def test_all_eight_stage_failure_combinations_and_identity_failure(self):
        for flags in product((False, True), repeat=3):
            stages = deepcopy(self.stages)
            for failed, stage in zip(flags, stages):
                if failed:
                    stage.update(status='failed', value=None)
            result = self.run_profiles(stages)
            expected = dict(zip(f.PROFILES, (flags[0], flags[1], flags[0] or flags[2], flags[1] or flags[2])))
            self.assertEqual(result['fallback_count'], sum(expected.values()))
            for name, failed in expected.items():
                row = result['profiles'][name]
                self.assertEqual(row['fallback'], failed)
                self.assertEqual(set(row['prediction']), set(p.TARGETS))
                if failed:
                    self.assertEqual(row['prediction'], self.median)
                    self.assertEqual(row['leaves'], [])
                self.assertEqual(row['prediction_sha256'], p.fingerprint(row['prediction']))
                self.assertEqual(row['leaves_sha256'], p.fingerprint(row['leaves']))
                self.assertEqual(row['provenance_sha256'], p.fingerprint(row['provenance']))
            for a, b in (('O', 'D'), ('Q', 'Q+D')):
                self.assertEqual(result['weight_manipulation'][a + ':' + b],
                                 'unavailable_due_to_fallback' if expected[a] or expected[b] else 'passed')
        failed = [dict(status='failed', value=None) for _ in range(3)]
        result = f.compose_profiles(None, None, *failed, self.median, self.binding, identity_status='failed')
        self.assertEqual(result['fallback_count'], 4)
        self.assertTrue(all(row['fallback_reason'] == 'identity_failed' for row in result['profiles'].values()))
        with self.assertRaises(p.PairContractError):
            self.run_profiles(identity_status='failed')

    def test_success_matches_existing_arithmetic_and_fixed_hashes(self):
        expected = p.successful_profiles(self.items, self.foods, *(s['value'] for s in self.stages))
        result = self.run_profiles()
        for name in f.PROFILES:
            for key in ('prediction', 'leaves'):
                self.assertEqual(result['profiles'][name][key], expected['profiles'][name][key])
            self.assertEqual(result['profiles'][name]['provenance']['fixed_items_sha256'], expected['fixed_items_sha256'])
        self.assertEqual(result['repair_count'], 0)

    def test_repairs_are_stage_counted_and_dependencies_reported(self):
        for flags in product(('native', 'repaired'), repeat=4):
            stages = deepcopy(self.stages)
            for status, stage in zip(flags[1:], stages):
                stage['status'] = status
            result = self.run_profiles(stages, identity_status=flags[0])
            self.assertEqual(result['repair_count'], flags.count('repaired'))
            for name, indices in {'O': (0, 1), 'Q': (0, 2), 'D': (0, 1, 3), 'Q+D': (0, 2, 3)}.items():
                self.assertEqual(result['profiles'][name]['repaired'], any(flags[i] == 'repaired' for i in indices))
        stages = [dict(status='failed', value=None) for _ in self.stages]
        result = self.run_profiles(stages)
        self.assertEqual(result['profiles']['D']['fallback_reason'], 'original+density_failed')
        self.assertEqual(result['profiles']['Q+D']['fallback_reason'], 'quantity+density_failed')

    def test_fallback_does_not_force_independent_success_weights(self):
        stages = deepcopy(self.stages)
        stages[2] = dict(status='failed', value=None)
        result = self.run_profiles(stages)
        self.assertEqual(result['profiles']['O']['prediction']['weight'], 300)
        self.assertEqual(result['profiles']['Q']['prediction']['weight'], 600)
        self.assertEqual(result['profiles']['D']['prediction']['weight'], 123)

    def test_binding_and_five_vector_validation(self):
        for binding in ('', 'A' * 64, 'x' * 64, 'a' * 63, None, True):
            with self.subTest(binding=binding), self.assertRaises(p.PairContractError):
                f.compose_profiles(self.items, self.foods, *self.stages, self.median, binding)
        for key in p.TARGETS:
            for bad in (-1, True, '1', float('nan'), float('inf')) + ((0,) if key == 'weight' else ()):
                median = dict(self.median, **{key: bad})
                with self.subTest(key=key, value=bad), self.assertRaises(p.PairContractError):
                    f.compose_profiles(self.items, self.foods, *self.stages, median, self.binding)
        for median in ({}, dict(self.median, truth=123)):
            with self.assertRaises(p.PairContractError):
                f.compose_profiles(self.items, self.foods, *self.stages, median, self.binding)

    def test_success_tampering_cannot_become_native_or_silent_fallback(self):
        for index in range(3):
            for extra in (False, True):
                stages = deepcopy(self.stages)
                if index == 0:
                    stages[index]['value'][0]['truth' if extra else 'grams'] = 42 if extra else float('nan')
                elif index == 1:
                    stages[index]['value']['items'][0]['truth' if extra else 'grams'] = 42
                else:
                    stages[index]['value']['items'][0]['truth' if extra else 'density_code'] = '99999999'
                # Even when other stages failed, invalid success is a contract error.
                for j in range(3):
                    if j != index:
                        stages[j] = dict(status='failed', value=None)
                with self.subTest(index=index, extra=extra), self.assertRaises(p.PairContractError):
                    self.run_profiles(stages)
        for bad in ('ok', None, True):
            stages = deepcopy(self.stages); stages[0]['status'] = bad
            with self.assertRaises(p.PairContractError):
                self.run_profiles(stages)
        stages = deepcopy(self.stages); stages[0]['unexpected'] = 1
        with self.assertRaises(p.PairContractError):
            self.run_profiles(stages)
        stages = deepcopy(self.stages); stages[0]['status'] = 'failed'
        with self.assertRaises(p.PairContractError):
            self.run_profiles(stages)

    def test_catalogue_and_identity_are_validated_and_metadata_not_exported(self):
        for value in (float('nan'), float('inf'), True):
            foods = deepcopy(self.foods); foods['11111111']['density']['energy'] = value
            with self.assertRaises(p.PairContractError):
                f.compose_profiles(self.items, foods, *self.stages, self.median, self.binding)
        foods = deepcopy(self.foods); foods['11111111']['density']['truth'] = 42
        with self.assertRaises(p.PairContractError):
            f.compose_profiles(self.items, foods, *self.stages, self.median, self.binding)
        items = deepcopy(self.items); items[0]['truth'] = 42
        with self.assertRaises(p.PairContractError):
            f.compose_profiles(items, self.foods, *self.stages, self.median, self.binding)
        self.assertNotIn('DO_NOT_EXPORT', str(self.run_profiles()))

    def test_no_mutation_or_aliasing(self):
        before = deepcopy((self.items, self.foods, self.stages, self.median))
        result = self.run_profiles()
        result['profiles']['O']['leaves'][0]['original_final_codes'].clear()
        result['profiles']['O']['prediction']['weight'] = 999
        result['profiles']['O']['provenance']['stage_statuses'].clear()
        self.assertEqual((self.items, self.foods, self.stages, self.median), before)
        stages = [dict(status='failed', value=None) for _ in self.stages]
        result = self.run_profiles(stages)
        result['profiles']['O']['prediction']['weight'] = 999
        self.assertEqual(result['profiles']['Q']['prediction'], self.median)


if __name__ == '__main__':
    unittest.main()
