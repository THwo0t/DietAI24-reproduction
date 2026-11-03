"""Synthetic-only accounting identities and full-seal/label-read ordering."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

V2 = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(V2), str(V2 / 'src')]
from round4.diagnostics import analyze_j as d
from round4.src.artifacts import ArtifactStore, ArtifactError, canonical, fingerprint, key_path


def density(energy):
    return {'energy': energy, 'fat': energy / 100, 'carbs': energy / 10, 'protein': energy / 20}


def leaf(identifier, grams, energy=100):
    return {'ingredient_id': identifier, 'grams': grams, 'density': density(energy)}


def reference(identifier, grams, energy=100):
    return {'ingredient_id': identifier, 'grams': grams,
            'nutrients': {k: grams * v / 100 for k, v in density(energy).items()}}


def truth(items):
    return {'weight': sum(x['grams'] for x in items),
            **{k: sum(x['nutrients'][k] for x in items) for k in d.NUTRIENTS}}


def prediction(leaves):
    return {'weight': sum(x['grams'] for x in leaves),
            **{k: sum(x['grams'] * x['density'][k] / 100 for x in leaves) for k in d.NUTRIENTS}}


def record(leaves):
    return {'fallback': False, 'raw_leaves': leaves, 'prediction': prediction(leaves)}


def decompose(pred, refs, totals, catalog_ids=None):
    # Old arithmetic fixtures declare their invented known IDs available;
    # catalogue-availability tests supply a separate explicit catalogue.
    if catalog_ids is None:
        catalog_ids = {r['ingredient_id'] for r in refs} | {
            r['ingredient_id'] for r in pred.get('raw_leaves', []) if r['ingredient_id'] is not None}
    return d.decompose(pred, refs, totals, catalog_ids)


class AccountingTests(unittest.TestCase):
    def test_hand_computed_shared_mass_density_and_identity_terms(self):
        refs = [reference('a', 100), reference('missing', 30, 300)]
        pred = record([leaf('a', 50, 200), leaf('extra', 10, 200), leaf(None, 20, 150)])
        result = decompose(pred, refs, truth(refs))
        terms = result['components']['energy']
        self.assertEqual({k: terms[k] for k in ('omitted_reference', 'extra_known_id', 'unknown',
            'shared_id_mass', 'shared_id_density')}, {'omitted_reference': -90, 'extra_known_id': 20,
            'unknown': 30, 'shared_id_mass': -50, 'shared_id_density': 50})
        self.assertEqual(result['signed_error']['energy'], -40)
        self.assertEqual(result['signed_error']['weight'], -50)
        self.assertEqual(result['mass']['unpaired_mass_l1_g'], 110)
        self.assertLessEqual(result['max_identity_residual'], 1e-7)

    def test_duplicate_ids_are_merged_before_matching(self):
        one = decompose(record([leaf('a', 50, 200)]), [reference('a', 100)], truth([reference('a', 100)]))
        two = decompose(record([leaf('a', 25, 200), leaf('a', 25, 200)]),
                          [reference('a', 60), reference('a', 40)], truth([reference('a', 100)]))
        self.assertEqual(one, two)

    def test_aggregate_signed_identity_does_not_assert_additive_mae(self):
        refs = [reference('a', 100), reference('missing', 30, 300)]
        value = decompose(record([leaf('a', 50, 200), leaf('extra', 10, 200), leaf(None, 20, 150)]),
                            refs, truth(refs))
        aggregate = d.aggregate_decomposition([value, value])
        for key in d.KEYS:
            terms = aggregate['components_all_rows'][key]
            self.assertAlmostEqual(sum(v['mean_signed'] for v in terms.values()),
                                   aggregate['mean_signed_error_all_rows'][key])
        self.assertGreater(sum(v['mean_absolute'] for v in aggregate['components_all_rows']['energy'].values()),
                           abs(value['signed_error']['energy']))

    def test_different_densities_on_same_id_use_mass_weighted_density(self):
        refs = [reference('a', 50, 100), reference('a', 50, 300)]
        result = decompose(record([leaf('a', 25, 100), leaf('a', 25, 300)]), refs, truth(refs))
        self.assertEqual(result['components']['energy']['shared_id_density'], 0)
        self.assertEqual(result['components']['energy']['shared_id_mass'], -100)

    def test_cancellation_does_not_turn_unpaired_mass_into_accuracy(self):
        refs = [reference('omitted', 100)]
        result = decompose(record([leaf('extra', 100)]), refs, truth(refs))
        self.assertEqual(result['signed_error']['weight'], 0)
        self.assertEqual(result['mass']['unpaired_mass_l1_g'], 200)
        self.assertEqual(result['mass']['exact_id_overlap_g'], 0)

    def test_unknown_is_not_assigned_to_true_id(self):
        refs = [reference('a', 100)]
        result = decompose(record([leaf(None, 100)]), refs, truth(refs))
        self.assertEqual(result['mass']['unknown_g'], 100)
        self.assertEqual(result['mass']['omitted_reference_id_g'], 100)
        self.assertEqual(result['mass']['reference_mass_with_present_id_g'], 0)

    def test_omission_splits_catalog_absent_and_available_with_explicit_denominators(self):
        refs = [reference('a', 100), reference('available', 30), reference('unavailable', 20)]
        pred = record([leaf('a', 100), leaf(None, 10)])
        value = decompose(pred, refs, truth(refs), {'a', 'available'})
        self.assertEqual(value['omission_catalog_split'], {
            'catalog_absent_reference_id_g': 20,
            'catalog_present_unselected_reference_id_g': 30,
            'catalog_absent_reference_id_dish_occurrences': 1,
            'catalog_present_unselected_reference_id_dish_occurrences': 1})
        fallback = decompose({'fallback': True, 'raw_leaves': [], 'prediction': prediction([leaf(None, 50)])},
                             refs, truth(refs), {'a', 'available'})
        aggregate = d.aggregate_decomposition([value] + [fallback] * 83)
        split = aggregate['omitted_reference_catalog_availability']
        self.assertEqual((split['population_n'], split['decomposable_n'], split['excluded_whole_fallback_n']), (84, 1, 83))
        self.assertEqual(split['totals_on_decomposable_rows']['catalog_absent_reference_id_g'], 20)
        self.assertEqual(split['mean_mass_on_decomposable_rows']['catalog_present_unselected_reference_id_g'], 30)
        self.assertEqual(split['measured_mass_sums_divided_by_population_n']['catalog_absent_reference_id_g'], 20 / 84)
        self.assertEqual(value['components']['weight']['omitted_reference'], -50)
        self.assertLessEqual(value['max_identity_residual'], 1e-7)

    def test_reference_rounding_reconciliation_is_explicit(self):
        refs = [reference('a', 100)]; totals = truth(refs); totals['weight'] += .0005
        result = decompose(record([leaf('a', 100)]), refs, totals)
        self.assertAlmostEqual(result['components']['weight']['reference_reconciliation'], -.0005)
        totals['weight'] += .01
        with self.assertRaisesRegex(d.DiagnosticError, 'reference_ingredient_totals_changed'):
            decompose(record([leaf('a', 100)]), refs, totals)

    def test_true_weight_oracle_keeps_all84_and_raw_records_unchanged(self):
        records = {str(i): record([leaf('a', 50, 200)]) for i in range(84)}
        records['0'].update(fallback=True, raw_leaves=[])
        labels = {sid: {'truth': truth([reference('a', 100, 200)])} for sid in records}
        before = deepcopy(records)
        oracle = d.true_weight_oracle(records, labels)
        self.assertEqual(len(oracle), 84)
        self.assertEqual(records, before)
        self.assertEqual(oracle['0']['prediction']['weight'], 100)
        self.assertEqual(oracle['0']['prediction']['energy'], 200)
        self.assertTrue(oracle['0']['fallback'])
        records['1']['prediction']['weight'] = 0
        with self.assertRaisesRegex(d.DiagnosticError, 'nonpositive_weight_invalid_full_population'):
            d.true_weight_oracle(records, labels)
        self.assertEqual(len(records), 84)

    def test_all_fallbacks_have_explicit_error_term_not_fake_ingredients(self):
        pred = {'prediction': prediction([leaf(None, 50)]), 'fallback': True, 'raw_leaves': []}
        refs = [reference('a', 100)]
        value = decompose(pred, refs, truth(refs))
        aggregate = d.aggregate_decomposition([value] * 84)
        self.assertEqual(aggregate['population_n'], 84)
        self.assertEqual(aggregate['decomposable_n'], 0)
        self.assertEqual(aggregate['whole_fallback_n'], 84)
        self.assertIsNone(aggregate['mass_micro_rates_on_decomposable_rows'])
        self.assertEqual(aggregate['components_all_rows']['weight']['whole_fallback_error']['mean_signed'], -50)

    def test_invalid_leaf_accounting_and_nonfinite_inputs_rejected(self):
        refs = [reference('a', 100)]; bad = record([leaf('a', 100)])
        bad['prediction']['energy'] += 1
        with self.assertRaisesRegex(d.DiagnosticError, 'leaf_prediction_accounting_changed'):
            decompose(bad, refs, truth(refs))
        for value in (float('nan'), float('inf'), -1, True):
            bad = record([leaf('a', 100)]); bad['prediction']['weight'] = value
            with self.assertRaises(d.DiagnosticError): decompose(bad, refs, truth(refs))


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='diagnostic-synthetic-', dir=Path(__file__).resolve().parent)
        self.addCleanup(temp.cleanup); self.root = Path(temp.name).resolve()
        self.reads, self.rows, self.labels, self.records, metadata = [], [], {}, {}, []
        for dataset, count, groups in (('nutrition5k', 84, 78), ('asa24', 99, 23)):
            for i in range(count):
                sid = f'synthetic-{dataset}-{i:03d}'
                row = {'sample_id': sid, 'dataset': dataset, 'split': 'dev',
                       'group_id': f'{dataset}-g-{i % groups}', 'fold': i % groups % 5}
                self.rows.append(row); refs = [reference('ingredient-a', 100, 200)]
                self.labels[sid] = {'truth': truth(refs), 'split': 'dev'}
                if dataset == 'nutrition5k':
                    pred = {**row, **record([leaf('ingredient-a', 90, 200)])}
                    pred.update(raw_prediction=deepcopy(pred['prediction']), method_fallback=False,
                                repair_used=False, native_complete=True, query_id=sid)
                    self.records[sid] = pred
                    metadata.append({**row, 'ingredients': refs})
        catalog_hash = self.put(d.CATALOG, canonical({'schema_version': 1,
            'scope': 'accepted_external_training_only_domain_catalog',
            'ingredients': [{'ingredient_id': name} for name in
                            ['ingredient-a'] + ['catalog-only-' + str(i) for i in range(d.CATALOG_SIZE - 1)]]}))
        self.verified = {'records': self.records,
            'binding': {'synthetic_base': True, 'input_sha256': {d.CATALOG: catalog_hash}},
            'completion_sha256': 'a' * 64}
        self.put(d.continuation.SERVICE_PROTOCOL, b'synthetic service protocol')
        for name in d.SOURCES: self.put(name, b'synthetic source')
        self.put(d.scorer.MANIFEST, b''.join(canonical(row) for row in self.rows))
        self.put(d.scorer.LABELS, canonical(self.labels))
        metadata_hash = self.put(d.INGREDIENTS, canonical({'records': metadata}))
        n5 = [row for row in self.rows if row['dataset'] == 'nutrition5k']
        score = d.scorer.metrics.evaluate(n5, {sid: self.labels[sid] for sid in self.records},
                    list(self.records.values()), bootstrap=0)['datasets']['nutrition5k']
        binding = {'candidate': d.continuation.CANDIDATE, 'service_continuation': True,
            'phase': 'service_continuation_calibration_scoring', 'base_completion_sha256': 'a' * 64,
            'base_records_sha256': fingerprint(self.records)}
        for directory, key in ((d.continuation.RAW_OUTPUT, 'raw_scoring_completion_sha256'),
                               (d.continuation.CAL_OUTPUT, 'calibration_completion_sha256')):
            binding[key] = self.put(directory + '/completion.json', canonical({'synthetic': directory}))
        self.score_store = ArtifactStore(self.root / d.continuation.SCORE_OUTPUT, binding, ['metrics'],
            verify_sources=lambda: None, root=self.root / 'round4')
        self.score_store.finalize({'metrics': {'raw': {'nutrition5k': score}, 'calibrated': {'nutrition5k': score}}})
        outer = self

        class Reader(d.scorer.Inputs):
            def read(self, name):
                outer.reads.append(name)
                raw = (self.root / name).read_bytes(); value = hashlib.sha256(raw).hexdigest()
                d.require(name not in self.hashes or self.hashes[name] == value, 'synthetic_input_changed')
                self.hashes[name] = value
                return raw

        for p in (patch.object(d, 'ROOT', self.root), patch.object(d, 'Inputs', Reader),
                  patch.object(d, 'INGREDIENTS_SHA256', metadata_hash),
                  patch.object(d, 'verified_base', side_effect=lambda: deepcopy(self.verified)),
                  patch.object(d, 'external_binding', return_value={'synthetic_proof': True})):
            p.start(); self.addCleanup(p.stop)

    def put(self, relative, raw):
        path = self.root / relative; parent = self.root
        for part in path.parent.relative_to(self.root).parts:
            parent /= part; parent.mkdir(mode=0o700, exist_ok=True)
        path.write_bytes(raw); path.chmod(0o600)
        return hashlib.sha256(raw).hexdigest()

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_full_run_aggregate_only_and_completed_rerun_readonly(self):
        first = d.run(); value = first['aggregate']; before = self.snapshot()
        self.assertEqual(value['n'], 84)
        self.assertEqual(value['decomposition']['population_n'], 84)
        self.assertEqual(value['true_weight_oracle_point_metrics']['weight']['mae'], 0)
        self.assertFalse(value['calibration_refitted'] or value['new_profile_selected'])
        self.assertNotIn('synthetic-nutrition5k', json.dumps(value))
        self.assertNotIn('ingredient-a', json.dumps(value))
        second = d.run()
        self.assertEqual(second['status'], 'diagnostic_verified')
        self.assertEqual(second['aggregate'], value)
        self.assertEqual(before, self.snapshot())

    def test_partial_base_stops_before_reading_any_input(self):
        self.verified['records'].pop(next(iter(self.records)))
        with self.assertRaisesRegex(d.DiagnosticError, 'all_84_base_records_required'): d.run()
        self.assertEqual(self.reads, [])

    def test_failed_base_verifier_never_constructs_label_reader(self):
        with patch.object(d, 'verified_base', side_effect=ArtifactError('synthetic_unsealed')):
            with self.assertRaises(ArtifactError): d.run()
        self.assertEqual(self.reads, [])

    def test_scoring_seal_must_pass_before_labels(self):
        path = self.root / d.continuation.SCORE_OUTPUT / 'records' / (key_path('metrics') + '.json')
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises(ArtifactError): d.run()
        self.assertNotIn(d.scorer.LABELS, self.reads)
        self.assertNotIn(d.INGREDIENTS, self.reads)
        self.assertNotIn(d.CATALOG, self.reads)

    def test_catalog_hash_mismatch_rejected_before_development_labels(self):
        self.put(d.CATALOG, canonical({'ingredients': []}))
        with self.assertRaisesRegex(d.DiagnosticError, 'base_bound_training_catalog_changed'): d.run()
        self.assertNotIn(d.scorer.LABELS, self.reads)
        self.assertNotIn(d.INGREDIENTS, self.reads)

    def test_missing_catalog_binding_does_not_follow_other_recorded_paths(self):
        self.verified['binding']['input_sha256'] = {'other/labels.json': 'b' * 64}
        with self.assertRaisesRegex(d.DiagnosticError, 'base_bound_training_catalog_hash_required'): d.run()
        self.assertNotIn(d.CATALOG, self.reads)
        self.assertNotIn('other/labels.json', self.reads)

    def test_pinned_ingredients_mismatch_never_produces_diagnostic(self):
        self.put(d.INGREDIENTS, canonical({'records': []}))
        with self.assertRaisesRegex(d.DiagnosticError, 'pinned_development_ingredients_changed'): d.run()
        self.assertFalse((self.root / d.OUTPUT).exists())


if __name__ == '__main__':
    unittest.main()
