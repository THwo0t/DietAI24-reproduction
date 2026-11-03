"""K estimator tests: synthetic pixels, fake providers, no research input."""
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, PngImagePlugin

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
from opt_pipeline import ContractError
from opt_provider import ProviderStop
from round5.src import component_estimator as estimator

A, B = 'ingr_0000000001', 'ingr_0000000002'
NAMES = [{'ingredient_id': A, 'name': 'synthetic grain'},
         {'ingredient_id': B, 'name': 'synthetic protein'}]
CATALOG = [{**NAMES[0], 'density_per_100g': {'energy': 120, 'fat': 1, 'carbs': 25, 'protein': 3}},
           {**NAMES[1], 'density_per_100g': {'energy': 200, 'fat': 10, 'carbs': 0, 'protein': 25}}]


def group(index=1, **updates):
    value = {'group_id': 'g' + str(index), 'description': 'visible synthetic food',
             'bbox': [.2, .2, .8, .8], 'preparation': 'single', 'hypotheses': [A, B],
             'evidence': 'rounded pieces', 'uncertainty': 'identity uncertain'}
    value.update(updates)
    return value


def leaf(index=1, **updates):
    value = {'item_id': 'i' + str(index), 'description': 'synthetic food', 'grams': 100,
             'ingredient_id': A, 'estimated_density': None}
    value.update(updates)
    return value


def mass_value(**updates):
    value = {'total_grams': 100, 'parents': [{'group_id': 'g1', 'grams': 100,
              'leaves': [leaf()]}], 'uncertainty': 'latent recipe unknown'}
    value.update(updates)
    return value


def hraw(*groups):
    return json.dumps({'groups': list(groups or [group()])})


def mraw(**updates):
    return json.dumps(mass_value(**updates))


class FakeProvider:
    def __init__(self, *outputs):
        self.outputs, self.requests = list(outputs), []

    def chat(self, messages, **kwargs):
        self.requests.append({'messages': deepcopy(messages), **kwargs})
        if not self.outputs:
            raise AssertionError('unexpected additional call')
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class ComponentEstimatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.query = self.root / 'query_PRIVATE_ID_AND_FILENAME.png'
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('Comment', 'PRIVATE_METADATA')
        Image.new('RGB', (100, 80), (30, 60, 90)).save(self.query, pnginfo=metadata)
        self.supports = []
        for index in range(8):
            path = self.root / ('support_PRIVATE_ID_' + str(index) + '.png')
            Image.new('RGB', (30, 20), (index, 90, 150)).save(path)
            self.supports.append({'image_path': path, 'ingredients': [{'ingredient_id': B, 'grams': 60}]})

    def mass_call(self, *outputs, groups=None, supports=None, crops=None, catalog=None):
        groups = [group()] if groups is None else groups
        provider = FakeProvider(*outputs)
        result = estimator.infer_mass(provider, self.query, groups,
            estimator.make_crops(self.query, groups) if crops is None else crops,
            self.supports if supports is None else supports, CATALOG if catalog is None else catalog)
        return result, provider

    def test_hypothesis_success_quantities_absent_native_encoding_and_tokens(self):
        provider = FakeProvider(hraw())
        result = estimator.infer_hypotheses(provider, self.query, NAMES)
        self.assertEqual(result['groups'], [group()])
        self.assertEqual(result['audit'], {'group_count': 1, 'major_group_ids': ['g1']})
        self.assertFalse(result['repair_used'])
        self.assertIsNone(result['failure'])
        self.assertEqual(provider.requests[0]['max_completion_tokens'], 4096)
        text = json.dumps(provider.requests[0]['messages'])
        for private in ('PRIVATE_ID', 'PRIVATE_METADATA', 'density_per_100g', str(self.root)):
            self.assertNotIn(private, text)
        self.assertEqual(estimator.validate_hypotheses_result(result, NAMES), result)

    def test_hypothesis_strict_fields_ids_and_no_quantities(self):
        variants = [group(group_id='g2'), group(preparation='raw'), group(hypotheses=[A, A]),
                    group(hypotheses=[A, B, A]), group(hypotheses=['ingr_9999999999']),
                    group(hypotheses=[True]), group(evidence=' '), group(uncertainty=None),
                    {**group(), 'grams': 100}, {**group(), 'query_reference': 10}]
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ContractError):
                estimator.parse_hypotheses(hraw(value), NAMES)
        for raw in ('{"groups":[]}', '{"groups":[],"groups":[]}', '[]',
                    json.dumps({'groups': [group()], 'truth': 12}), hraw(*[group(i) for i in range(1, 10)])):
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                estimator.parse_hypotheses(raw, NAMES)

    def test_boxes_reject_nan_infinity_bool_strings_reverse_and_outside(self):
        boxes = [[0, 0, float('nan'), 1], [0, 0, float('inf'), 1], [False, 0, 1, 1],
                 ['0', 0, 1, 1], [0, 0, 1.01, 1], [-.01, 0, 1, 1],
                 [.5, 0, .5, 1], [.6, 0, .5, 1], [0, 0, 1], None]
        for box in boxes:
            with self.subTest(box=box), self.assertRaises(ContractError):
                estimator.parse_hypotheses(hraw(group(bbox=box)), NAMES)

    def test_unknown_mixed_and_geometric_overlap_are_allowed(self):
        rows = [group(hypotheses=[], preparation='mixed'), group(2)]
        self.assertEqual(estimator.parse_hypotheses(hraw(*rows), NAMES), rows)

    def test_stage_one_text_rejects_quantities_paths_and_ids_but_allows_semantics(self):
        for field in ('description', 'evidence', 'uncertainty'):
            for text in ('approximately 100g', 'protein: 20', 'energy 100',
                         '/private/query.png', 'dish_1234567890.png', A):
                with self.subTest(field=field, text=text), self.assertRaises(ContractError):
                    estimator.parse_hypotheses(hraw(group(**{field: text})), NAMES)
        allowed = group(description='visible fat marbling', evidence='protein identity unclear',
                        uncertainty='texture could indicate either food', hypotheses=[A, B])
        self.assertEqual(estimator.parse_hypotheses(hraw(allowed), NAMES), [allowed])

    def test_major_groups_are_area_ordered_ties_stable_top_four(self):
        rows = [group(1, bbox=[0, 0, .2, .2]), group(2, bbox=[0, 0, .9, .9]),
                group(3, bbox=[0, 0, .5, .5]), group(4, bbox=[.5, .5, 1, 1]),
                group(5, bbox=[0, 0, .7, .7])]
        before = deepcopy(rows)
        self.assertEqual([row['group_id'] for row in estimator.major_groups(rows)], ['g2', 'g5', 'g3', 'g4'])
        self.assertEqual(rows, before)

    def test_crop_margin_floor_ceil_rgb_metadata_and_payload_sha(self):
        crop = estimator.make_crops(self.query, [group()])[0]
        self.assertEqual(crop['group_id'], 'g1')
        self.assertEqual(crop['sha256'], hashlib.sha256(crop['image_url'].encode('ascii')).hexdigest())
        with Image.open(BytesIO(base64.b64decode(crop['image_url'].split(',', 1)[1]))) as image:
            # [.17,.17,.83,.83] => [17,13,83,67], with floor/ceil.
            self.assertEqual(image.size, (66, 54))
            self.assertEqual(image.mode, 'RGB')
            self.assertEqual(image.info, {})
            self.assertEqual(image.getpixel((0, 0)), (30, 60, 90))

    def test_crop_clipping_no_upsampling_max1024_and_nonempty_tiny_region(self):
        for size, box, expected in [((20, 10), [0, 0, 1, 1], (20, 10)),
                                    ((2400, 1200), [0, 0, 1, 1], (1024, 512)),
                                    ((20, 10), [.000001, .000001, .000002, .000002], (1, 1))]:
            Image.new('RGB', size).save(self.query)
            crop = estimator.make_crops(self.query, [group(bbox=box)])[0]
            with Image.open(BytesIO(base64.b64decode(crop['image_url'].split(',', 1)[1]))) as image:
                self.assertEqual(image.size, expected)

    def test_hypothesis_one_format_repair_and_terminal_failure_cached(self):
        good = hraw()
        provider = FakeProvider('{}', good)
        result = estimator.infer_hypotheses(provider, self.query, NAMES)
        self.assertTrue(result['repair_used'])
        self.assertEqual(len(provider.requests), 2)
        self.assertIn('Preserve the initial visual interpretation', provider.requests[-1]['messages'][-1]['content'])
        self.assertEqual(estimator.validate_hypotheses_result(result, NAMES), result)
        bad_provider = FakeProvider('{}', '{}')
        bad = estimator.infer_hypotheses(bad_provider, self.query, NAMES)
        self.assertEqual(bad['groups'], [])
        self.assertIsNotNone(bad['failure'])
        self.assertEqual(estimator.validate_hypotheses_result(bad, NAMES), bad)

    def test_hypothesis_cache_reparses_raw_and_forbids_spurious_repair(self):
        result = estimator.infer_hypotheses(FakeProvider(hraw()), self.query, NAMES)
        for key, value in [('groups', [group(hypotheses=[B])]), ('failure', 'invented'),
                           ('repair_used', 0), ('raw_outputs', [hraw(), hraw()])]:
            altered = deepcopy(result)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                estimator.validate_hypotheses_result(altered, NAMES)

    def test_mass_predictions_use_leaf_density_no_parent_double_count(self):
        rows = [{'group_id': 'g1', 'grams': 150,
                 'leaves': [leaf(grams=100), leaf(2, grams=50, ingredient_id=B)]}]
        result, provider = self.mass_call(mraw(total_grams=150, parents=rows))
        self.assertEqual(result['prediction'], {'weight': 150, 'energy': 220, 'fat': 6, 'carbs': 25, 'protein': 15.5})
        self.assertEqual(result['raw_leaves'][1]['density'], CATALOG[1]['density_per_100g'])
        self.assertEqual(result['raw_leaves'][1]['group_id'], 'g1')
        self.assertFalse(result['audit']['macro_mass_excess_total'])
        self.assertEqual(provider.requests[0]['max_completion_tokens'], 8192)
        self.assertEqual(estimator.validate_mass_result(result, [group()], CATALOG), result)

    def test_all_stage_one_groups_mandatory_rejection_and_remainder_legal(self):
        groups = [group(), group(2)]
        parents = [{'group_id': 'g2', 'grams': 0, 'leaves': []},
                   {'group_id': 'remainder', 'grams': 20, 'leaves': [leaf(2, grams=20)]},
                   {'group_id': 'g1', 'grams': 100, 'leaves': [leaf()]}]
        parsed = estimator.parse_mass(mraw(total_grams=120, parents=parents), groups, CATALOG)
        self.assertEqual(parsed['audit']['rejected_group_ids'], ['g2'])
        self.assertEqual(parsed['prediction']['weight'], 120)
        for invalid in (parents[:2], [parents[0], parents[0], parents[2]],
                        [{**parents[2], 'group_id': 'g9'}, parents[0]]):
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                estimator.parse_mass(mraw(parents=invalid), groups, CATALOG)

    def test_positive_parent_needs_leaves_zero_parent_must_be_empty(self):
        for parent in ({'group_id': 'g1', 'grams': 100, 'leaves': []},
                       {'group_id': 'g1', 'grams': 0, 'leaves': [leaf()]},
                       {'group_id': 'g1', 'grams': 100, 'leaves': [leaf(grams=0)]}):
            with self.subTest(parent=parent), self.assertRaises(ContractError):
                estimator.parse_mass(mraw(parents=[parent]), [group()], CATALOG)
        with self.assertRaises(ContractError):
            estimator.parse_mass(mraw(total_grams=0, parents=[{'group_id': 'g1', 'grams': 0, 'leaves': []}]), [group()], CATALOG)

    def test_parent_and_total_mass_inconsistency_reject_without_rescaling(self):
        for raw in (mraw(total_grams=100.002),
                    mraw(parents=[{'group_id': 'g1', 'grams': 100.002, 'leaves': [leaf()]}])):
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                estimator.parse_mass(raw, [group()], CATALOG)
        near = estimator.parse_mass(mraw(total_grams=100.0009), [group()], CATALOG)
        self.assertEqual(near['prediction']['weight'], 100)
        self.assertEqual(near['total_grams'], 100.0009)

    def test_exact_mass_tolerance_boundary_is_accepted_not_rounded_or_rescaled(self):
        for total in (100.001, 99.999):
            parsed = estimator.parse_mass(mraw(total_grams=total), [group()], CATALOG)
            self.assertEqual(parsed['prediction']['weight'], 100)
            self.assertEqual(parsed['audit']['total_mass_residual'], .001)
        for total in (100.00100001, 99.99899999):
            with self.assertRaises(ContractError):
                estimator.parse_mass(mraw(total_grams=total), [group()], CATALOG)
        parents = [{'group_id': 'g1', 'grams': 100.001, 'leaves': [leaf()]}]
        parsed = estimator.parse_mass(mraw(total_grams=100.001, parents=parents), [group()], CATALOG)
        self.assertEqual(parsed['audit']['max_parent_mass_residual'], .001)

    def test_leaf_ids_unique_globally_and_maximum_twenty(self):
        parents = [{'group_id': 'g1', 'grams': 100, 'leaves': [leaf()]},
                   {'group_id': 'g2', 'grams': 100, 'leaves': [leaf()]}]
        with self.assertRaises(ContractError):
            estimator.parse_mass(mraw(total_grams=200, parents=parents), [group(), group(2)], CATALOG)
        for children in ([leaf(i, grams=1) for i in range(1, 22)], [leaf(item_id='i0')]):
            with self.assertRaises(ContractError):
                estimator.parse_mass(mraw(parents=[{'group_id': 'g1', 'grams': 100, 'leaves': children}]), [group()], CATALOG)
        twenty = [leaf(i, grams=5) for i in range(1, 21)]
        self.assertEqual(len(estimator.parse_mass(mraw(parents=[{'group_id': 'g1', 'grams': 100, 'leaves': twenty}]),
                        [group()], CATALOG)['raw_leaves']), 20)

    def test_unknown_density_explicit_finite_and_known_null_only(self):
        density = {'energy': 80, 'fat': 2, 'carbs': 10, 'protein': 5}
        children = [leaf(grams=50), leaf(2, grams=50, ingredient_id=None, estimated_density=density)]
        parsed = estimator.parse_mass(mraw(parents=[{'group_id': 'g1', 'grams': 100, 'leaves': children}]), [group()], CATALOG)
        self.assertEqual(parsed['prediction'], {'weight': 100, 'energy': 100, 'fat': 1.5, 'carbs': 17.5, 'protein': 4})
        self.assertEqual(parsed['audit']['unknown_mass_fraction'], .5)
        variants = [leaf(estimated_density=density), leaf(ingredient_id=None),
                    leaf(ingredient_id=None, estimated_density={'fat': 2}),
                    leaf(ingredient_id=None, estimated_density={**density, 'fat': -1}),
                    leaf(ingredient_id=None, estimated_density={**density, 'fat': True}),
                    leaf(ingredient_id=None, estimated_density={**density, 'fat': float('inf')}),
                    leaf(ingredient_id='ingr_9999999999')]
        for child in variants:
            with self.subTest(child=child), self.assertRaises(ContractError):
                estimator.parse_mass(mraw(parents=[{'group_id': 'g1', 'grams': 100, 'leaves': [child]}]), [group()], CATALOG)

    def test_numeric_contract_and_overflow_fail_safely(self):
        for grams in (False, '100', -1, float('nan'), float('inf')):
            with self.subTest(grams=grams), self.assertRaises(ContractError):
                estimator.parse_mass(mraw(total_grams=grams), [group()], CATALOG)
        huge_catalog = deepcopy(CATALOG)
        huge_catalog[0]['density_per_100g']['energy'] = 1e308
        with self.assertRaises(ContractError):
            estimator.parse_mass(mraw(total_grams=1e308, parents=[{'group_id': 'g1', 'grams': 1e308,
                                      'leaves': [leaf(grams=1e308)]}]), [group()], huge_catalog)

    def test_mass_strict_fields_and_uncertainty_no_model_total_override(self):
        for value in ({**mass_value(), 'protein': 999}, {**mass_value(), 'uncertainty': ''},
                      {**mass_value(), 'query_reference': {}}):
            with self.subTest(value=value), self.assertRaises(ContractError):
                estimator.parse_mass(json.dumps(value), [group()], CATALOG)

    def test_mass_one_repair_terminal_failure_and_cache_replay(self):
        result, provider = self.mass_call('{}', mraw())
        self.assertTrue(result['repair_used'])
        self.assertEqual(len(provider.requests), 2)
        self.assertIsNone(result['failure'])
        self.assertEqual(estimator.validate_mass_result(result, [group()], CATALOG), result)
        failed, provider = self.mass_call('{}', '{}')
        self.assertEqual(len(provider.requests), 2)
        for key in ('items', 'parents', 'raw_leaves'):
            self.assertEqual(failed[key], [])
        self.assertIsNone(failed['prediction'])
        self.assertEqual(estimator.validate_mass_result(failed, [group()], CATALOG), failed)

    def test_mass_cache_reparse_rejects_derived_tampering(self):
        result, _ = self.mass_call(mraw())
        for field in ('prediction', 'raw_leaves', 'parents', 'audit', 'items', 'total_grams'):
            altered = deepcopy(result)
            if field == 'prediction':
                altered[field]['protein'] = 999
            elif field == 'audit':
                altered[field]['unknown_count'] = 9
            elif field == 'total_grams':
                altered[field] = 999
            else:
                altered[field] = []
            with self.subTest(field=field), self.assertRaises(ContractError):
                estimator.validate_mass_result(altered, [group()], CATALOG)

    def test_full_message_contains_maximum13_images_and_no_private_metadata(self):
        groups = [group(i) for i in range(1, 5)]
        parents = [{'group_id': 'g1', 'grams': 100, 'leaves': [leaf()]}] + [
                  {'group_id': 'g' + str(i), 'grams': 0, 'leaves': []} for i in range(2, 5)]
        _, provider = self.mass_call(mraw(parents=parents), groups=groups)
        content = provider.requests[0]['messages'][1]['content']
        urls = [part['image_url']['url'] for part in content if part['type'] == 'image_url']
        self.assertEqual(len(urls), 13)
        self.assertEqual(urls[1:5], [row['image_url'] for row in estimator.make_crops(self.query, groups)])
        text = json.dumps(provider.requests)
        for forbidden in ('PRIVATE_ID', 'PRIVATE_METADATA', str(self.root), 'query_reference', 'previous_prediction'):
            self.assertNotIn(forbidden, text)
        self.assertIn('Training support s8', text)
        self.assertIn('synthetic protein', text)
        self.assertIn('"grams": 60.0', json.dumps(content).replace('\\"', '"'))

    def test_crops_wrong_group_order_bytes_or_hash_rejected_before_chat(self):
        groups = [group(), group(2)]
        valid = estimator.make_crops(self.query, groups)
        variants = [valid[::-1], valid[:1], [{**valid[0], 'sha256': '0' * 64}, valid[1]],
                    [{**valid[0], 'image_url': valid[0]['image_url'] + 'x'}, valid[1]],
                    [{**valid[0], 'query_reference': 100}, valid[1]]]
        for crops in variants:
            provider = FakeProvider(mraw())
            with self.subTest(crops=crops), self.assertRaises(ContractError):
                estimator.infer_mass(provider, self.query, groups, crops, self.supports, CATALOG)
            self.assertEqual(provider.requests, [])

    def test_whitelisted_inputs_reject_query_labels_and_previous_predictions_before_call(self):
        provider = FakeProvider(hraw())
        for names in (CATALOG, [{**NAMES[0], 'query_reference': 10}], NAMES + [NAMES[0]]):
            with self.assertRaises(ContractError):
                estimator.infer_hypotheses(provider, self.query, names)
        self.assertEqual(provider.requests, [])
        for supports in ([{**self.supports[0], 'training_id': 'PRIVATE'}],
                         [{'image_path': self.query, 'ingredients': self.supports[0]['ingredients']}],
                         [self.supports[0], self.supports[0]], self.supports + [self.supports[0]],
                         [{'image_path': self.supports[0]['image_path'], 'ingredients': [{'ingredient_id': B, 'grams': 1, 'truth': 3}]}]):
            with self.subTest(supports=supports), self.assertRaises(ContractError):
                estimator.infer_mass(provider, self.query, [group()], [], supports, CATALOG)
        self.assertEqual(provider.requests, [])

    def test_no_supports_legal_query_and_crop_only(self):
        result, provider = self.mass_call(mraw(), supports=[])
        self.assertEqual(result['prediction']['weight'], 100)
        self.assertEqual(sum(part['type'] == 'image_url' for part in provider.requests[0]['messages'][1]['content']), 2)

    def test_provider_exceptions_propagate_at_initial_or_repair_for_both_stages(self):
        for outputs in ((ProviderStop('safe_stop'),), ('{}', ProviderStop('safe_stop')),
                        (RuntimeError('safe_error'),), ('{}', RuntimeError('safe_error'))):
            for stage in ('hypotheses', 'mass'):
                provider = FakeProvider(*outputs)
                with self.subTest(stage=stage, outputs=outputs), self.assertRaises(type(outputs[-1])):
                    if stage == 'hypotheses':
                        estimator.infer_hypotheses(provider, self.query, NAMES)
                    else:
                        estimator.infer_mass(provider, self.query, [group()],
                            estimator.make_crops(self.query, [group()]), self.supports, CATALOG)
                self.assertEqual(len(provider.requests), len(outputs))

    def test_inputs_and_results_have_no_shared_mutable_density_objects(self):
        before = deepcopy(CATALOG)
        result, _ = self.mass_call(mraw())
        result['raw_leaves'][0]['density']['protein'] = 999
        result['items'][0]['grams'] = 999
        self.assertEqual(CATALOG, before)
        self.assertEqual(result['parents'][0]['leaves'][0]['grams'], 100)


if __name__ == '__main__':
    unittest.main()
