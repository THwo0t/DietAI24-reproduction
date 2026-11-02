"""Synthetic-only ensemble integrity and label-boundary tests."""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import evaluate_ensembles as driver


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))


def fixture_rows():
    n5 = [{'sample_id': f'n5-{i}', 'dataset': 'nutrition5k', 'group_id': f'n5g{i % 78}',
           'fold': (i % 78) % 5, 'split': 'dev', 'image_path': f'never-open/n5-{i}.png',
           'image_sha256': driver.fingerprint(['n5', i])} for i in range(84)]
    asa = [{'sample_id': f'asa-{i}', 'dataset': 'asa24', 'group_id': f'asag{i % 23}',
            'fold': (i % 23) % 5, 'split': 'dev', 'image_path': f'never-open/asa-{i}.png',
            'image_sha256': driver.fingerprint(['asa', i])} for i in range(99)]
    return n5 + asa


def make_record(row, value):
    vector = dict.fromkeys(driver.metrics.KEYS, float(value))
    return {**{k: row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')},
            'prediction': vector, 'raw_prediction': deepcopy(vector), 'fallback': False,
            'fallback_reason': None, 'native_complete': True, 'repair_used': False,
            'final_codes': [], 'primary_code': None}


def snapshot(directory):
    return {p.relative_to(directory).as_posix(): (driver.sha(p), p.stat().st_mtime_ns)
            for p in directory.rglob('*') if p.is_file()}


@contextmanager
def source_fixture():
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch.object(driver, 'ROOT', root))
        stack.enter_context(patch.object(driver, 'BOOTSTRAP', 0))
        all_rows = fixture_rows()
        rows, asa_rows = all_rows[:84], all_rows[84:]
        labels = {r['sample_id']: {'split': 'dev', 'truth': dict.fromkeys(driver.metrics.KEYS, 10.),
                                 'food_code': '12345678', 'size': 'medium'} for r in all_rows}
        h_sources, i_sources = driver.source_sets(rows)
        # Placeholder transitive files are hashed only, never parsed as labels.
        for name in h_sources | i_sources | {driver.SELF, driver.PROTOCOL}:
            save(root / name, {'synthetic': name})
        (root / driver.MANIFEST).write_text('\n'.join(json.dumps(r) for r in all_rows) + '\n')
        save(root / driver.LABELS, labels)
        asa = []
        for row in asa_rows:
            record = make_record(row, 10)
            record.update(final_codes=['12345678'], primary_code='12345678', retrieved_codes=['12345678'],
                          conditional={'prediction': dict.fromkeys(driver.metrics.KEYS, 10.)},
                          e2e={'prediction': dict.fromkeys(driver.metrics.KEYS, 10.)})
            asa.append(record)
        save(root / driver.SELECTED, asa)
        config = {'profile': 'C', 'identity_profile': 'A', 'crop_review': False, 'portion_mode': 'total_ratio'}
        save(root / driver.SELECTION, {'profiles': {'nutrition5k': {'name': 'C', 'config': config}}})
        current = {name: driver.sha(root / 'src' / name) for name in driver.CORE}
        old = {name: 'original-' + name for name in driver.CORE}
        save(root / 'runs/development/C/run_config.json', {
            'name': 'C', 'code_sha256': old, 'manifest_sha256': driver.fingerprint(rows),
            'protocol_sha256': driver.sha(root / 'PROTOCOL.md'), 'config': config,
            'vector_sha256': driver.sha(root / 'data/vectors/manifest.json')})
        save(root / 'runs/development/C/status.json', {'status': 'completed'})
        c_records, c_seal = [], {}
        for row in rows:
            record = make_record(row, 2)
            path = root / 'runs/development/C/records' / driver.artifact(row)
            save(path, record)
            c_records.append(record)
            c_seal[row['sample_id']] = driver.sha(path)
        save(root / 'runs/development/C/records_sealed.json', c_seal)
        save(root / 'runs/development/C/predictions.json', c_records)
        correction = {'finding': 'R-M2-4-1', 'source_sha256_after': current['opt_metrics.py'],
                      'actual_development_recalculation': dict.fromkeys((
                          'complete_metrics_object_equals_checkpoint', 'complete_metrics_object_equals_saved_selection',
                          'existing_structure_and_all_intervals_unchanged'), True),
                      'input_sha256': {name: driver.sha(root / name) for name in (
                          driver.MANIFEST, driver.LABELS, 'data/cohorts/dev_freeze.json', driver.SELECTED, driver.SELECTION)}}
        save(root / driver.CORRECTION, correction)
        reviewed = {'status': 'approved_or_fixed', 'unresolved_p1_p2': 0, 'code_sha256': current,
                    'original_code_sha256': old,
                    'evidence_sha256': {'R-M2-4-1.json': driver.sha(root / driver.CORRECTION)},
                    'dev_freeze_sha256': driver.sha(root / 'data/cohorts/dev_freeze.json'),
                    'selection_sha256': driver.sha(root / driver.SELECTION),
                    'protocol_sha256': driver.sha(root / 'PROTOCOL.md'),
                    'catalog_sha256': driver.sha(root / 'data/catalog.json')}
        save(root / driver.REVIEW, reviewed)
        stack.enter_context(patch.object(driver, 'TRUSTED_EVIDENCE', {
            name: driver.sha(root / name) for name in (driver.REVIEW, driver.CORRECTION)}))
        catalog_proofs = {str(f): {'heldout_fold': f,
            'training_group_count': len({r['group_id'] for r in rows if r['fold'] != f}),
            'inference_catalog_sha256': driver.fingerprint(['catalog', f]),
            'catalog_file_sha256': driver.sha(root / f'round3/data/train_catalogs/fold_{f}.json')}
            for f in range(5)}
        assignments = {}
        for row in rows:
            chosen, groups = [], set()
            for support in rows:
                if support['fold'] != row['fold'] and support['group_id'] != row['group_id'] and support['group_id'] not in groups:
                    chosen.append({**{k: support[k] for k in ('sample_id', 'group_id', 'fold', 'image_sha256')},
                                   'ingredients_sha256': driver.fingerprint(support['sample_id'])})
                    groups.add(support['group_id'])
                if len(chosen) == 4:
                    break
            assignments[row['sample_id']] = {'query_group_id': row['group_id'], 'query_fold': row['fold'],
                'query_image_sha256': row['image_sha256'], 'catalog_sha256': catalog_proofs[str(row['fold'])]['inference_catalog_sha256'],
                'examples': chosen}
        for candidate, value, sources in (('H', 8, h_sources), ('I', 20, i_sources)):
            prefix = root / 'round3/runs' / candidate
            binding = {'candidate': candidate, 'scope': 'development_only', 'validation_access': False,
                       'example_count': 4, 'manifest_sha256': driver.fingerprint(rows), 'calibration': 'none',
                       'input_sha256': {name: driver.sha(root / name) for name in sources},
                       'example_assignments_sha256': driver.fingerprint(assignments), 'fold_catalog_proofs': catalog_proofs}
            save(prefix / 'binding.json', binding)
            save(prefix / 'example_assignments.json', assignments)
            records, seal = [], {}
            for row in rows:
                record = make_record(row, value)
                record.update(example_assignment_sha256=driver.fingerprint(assignments[row['sample_id']]),
                              example_proof=deepcopy(assignments[row['sample_id']]))
                envelope = {'binding_sha256': driver.fingerprint(binding), 'record_sha256': driver.fingerprint(record), 'record': record}
                path = prefix / 'records' / driver.artifact(row)
                save(path, envelope)
                records.append(record)
                seal[row['sample_id']] = driver.sha(path)
            save(prefix / 'records_sealed.json', seal)
            save(prefix / 'predictions.json', records)
            save(prefix / 'metrics.json', {'candidate': candidate, 'synthetic': True})
            save(prefix / 'usage.json', {'new_api_calls': 0})
            save(prefix / 'completion.json', {'candidate': candidate, 'n': 84, 'groups': 78,
                'binding_sha256': driver.fingerprint(binding), 'validation_opened': False,
                'artifact_sha256': {name: driver.sha(prefix / name) for name in driver.MEMBER_FINAL}})
        yield root, all_rows, labels


class EnsembleTests(unittest.TestCase):
    def test_pure_arithmetic_whole_vector_and_member_fallback(self):
        row = fixture_rows()[0]
        members = {name: [make_record(row, v)] for name, v in (('C', 2), ('H', 8), ('I', 20))}
        members['I'][0].update(fallback=True, native_complete=False, raw_prediction=None,
                               fallback_reason='upstream_failure')
        seals = {name: {row['sample_id']: name * 64} for name in members}
        mean = driver.combine([row], members, seals, 'HI_mean')[0]
        med = driver.combine([row], members, seals, 'CHI_median')[0]
        self.assertEqual(mean['prediction'], dict.fromkeys(driver.metrics.KEYS, 14.))
        self.assertEqual(med['prediction'], dict.fromkeys(driver.metrics.KEYS, 8.))
        self.assertTrue(med['fallback'])
        self.assertFalse(med['native_complete'])
        self.assertEqual(med['member_failure_states']['I']['fallback_reason'], 'upstream_failure')

    def test_actual_boundary_seals_both_before_labels_then_resume_readonly(self):
        with source_fixture() as (root, rows, labels):
            original_json = driver.Reader.json
            label_reads = []
            def inspect(reader, name):
                if name == driver.LABELS:
                    for method in driver.METHODS:
                        self.assertTrue((root / 'round3/runs/ensembles' / method / 'records_sealed.json').is_file())
                    label_reads.append(name)
                return original_json(reader, name)
            with patch.object(driver.Reader, 'json', inspect):
                result = driver.run()
            self.assertEqual(label_reads, [driver.LABELS])
            self.assertEqual(set(result['ranking']), set(driver.METHODS))
            directory = root / 'round3/runs/ensembles'
            before = snapshot(directory)
            self.assertEqual(driver.run(), result)
            self.assertEqual(snapshot(directory), before)
            for method in driver.METHODS:
                saved = driver.load(directory / method / 'metrics.json')
                self.assertEqual(saved['nutrition5k']['n'], 84)
                joint = saved['joint_metrics_with_preserved_asa']
                self.assertEqual(joint['total_checks'], 20)
                self.assertEqual(joint['datasets']['asa24']['n'], 99)
                self.assertEqual(joint['datasets']['asa24']['exact_n'], 99)

    def test_label_decode_guard_and_no_image_or_validation_paths(self):
        with source_fixture():
            context = driver.prepare_context()
            with self.assertRaisesRegex(ValueError, 'Decode labels only'):
                context['reader'].json(driver.LABELS)
            with self.assertRaisesRegex(ValueError, 'allowlist'):
                context['reader'].bytes('data/cohorts/validation_labels.json')
            self.assertFalse(any(name.endswith('.png') for name in context['reader'].hashes))

    def test_change_labels_does_not_change_arithmetic(self):
        with source_fixture() as (_, rows, labels):
            context = driver.prepare_context()
            before = driver.combine(context['rows'], context['members'], context['member_seals'], 'CHI_median')
            for row in rows:
                labels[row['sample_id']]['truth'] = dict.fromkeys(driver.metrics.KEYS, 1e9)
            after = driver.combine(context['rows'], context['members'], context['member_seals'], 'CHI_median')
            self.assertEqual(before, after)

    def test_duplicate_missing_mismatched_population_rejected(self):
        row = fixture_rows()[0]
        members = {name: [make_record(row, 2)] for name in ('C', 'H', 'I')}
        seals = {name: {row['sample_id']: 'a' * 64} for name in members}
        for variant in ('duplicate', 'missing', 'fold'):
            altered = deepcopy(members)
            if variant == 'duplicate': altered['H'].append(deepcopy(altered['H'][0]))
            if variant == 'missing': altered['H'] = []
            if variant == 'fold': altered['H'][0]['fold'] = 99
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                driver.combine([row], altered, seals, 'HI_mean')

    def test_fold_group_leakage_and_same_group_supports_rejected(self):
        with source_fixture() as (_, rows, _):
            context = driver.prepare_context()
            h = driver.load(driver.ROOT / 'round3/runs/H/binding.json')
            original = driver.load(driver.ROOT / 'round3/runs/H/example_assignments.json')
            for variant in ('query', 'duplicate_group'):
                values = deepcopy(original)
                query = rows[0]
                selected = values[query['sample_id']]['examples']
                if variant == 'query':
                    selected[0] = {**{k: query[k] for k in ('sample_id', 'group_id', 'fold', 'image_sha256')}, 'ingredients_sha256': 'x'}
                else:
                    selected[1] = deepcopy(selected[0])
                h['example_assignments_sha256'] = driver.fingerprint(values)
                with self.subTest(variant=variant), self.assertRaises(ValueError):
                    driver.validate_assignments(context['rows'], values, h)

    def test_member_record_rechecksum_does_not_bypass_external_seal(self):
        with source_fixture() as (root, rows, _):
            path = root / 'round3/runs/I/records' / driver.artifact(rows[0])
            value = driver.load(path)
            value['record']['prediction']['weight'] += 1
            value['record_sha256'] = driver.fingerprint(value['record'])
            save(path, value)
            with self.assertRaisesRegex(ValueError, 'external seal'):
                driver.run()
            self.assertFalse((root / 'round3/runs/ensembles').exists())

    def test_ensemble_record_rechecksum_rejected_without_rewrite(self):
        with source_fixture() as (root, rows, _):
            driver.run()
            directory = root / 'round3/runs/ensembles'
            path = directory / 'HI_mean/records' / driver.artifact(rows[0])
            value = driver.load(path)
            value['record']['prediction']['protein'] += 1
            value['record_sha256'] = driver.fingerprint(value['record'])
            save(path, value)
            before = snapshot(directory)
            with self.assertRaisesRegex(ValueError, 'external seal'):
                driver.run()
            self.assertEqual(snapshot(directory), before)

    def test_metrics_tamper_rejected_before_label_decode(self):
        with source_fixture() as (root, _, _):
            driver.run()
            save(root / 'round3/runs/ensembles/HI_mean/metrics.json', {'tampered': True})
            original = driver.Reader.json
            def guard(reader, name):
                if name == driver.LABELS:
                    self.fail('Labels decoded before completion verification')
                return original(reader, name)
            with patch.object(driver.Reader, 'json', guard), self.assertRaisesRegex(ValueError, 'artifact changed'):
                driver.run()

    def test_incomplete_I_stops_without_creating_outputs(self):
        with source_fixture() as (root, _, _):
            (root / 'round3/runs/I/completion.json').unlink()
            with self.assertRaises(ValueError):
                driver.run()
            self.assertFalse((root / 'round3/runs/ensembles').exists())

    def test_core_drift_and_self_drift_rejected(self):
        with source_fixture() as (root, _, _):
            driver.run()
            with (root / driver.SELF).open('a') as handle: handle.write(' drift')
            with self.assertRaisesRegex(ValueError, 'differs'):
                driver.run()
        with source_fixture() as (root, _, _):
            with (root / 'src/opt_metrics.py').open('a') as handle: handle.write(' drift')
            with self.assertRaisesRegex(ValueError, 'Reviewed source'):
                driver.run()

    def test_member_fallback_retained_in_full_primary_population(self):
        with source_fixture() as (_, _, labels):
            context = driver.prepare_context()
            context['members']['I'][0].update(fallback=True, native_complete=False, raw_prediction=None)
            records = driver.combine(context['rows'], context['members'], context['member_seals'], 'HI_mean')
            result = driver.score(context, labels, records, 'HI_mean')
            self.assertEqual(result['nutrition5k']['primary']['n'], 84)
            self.assertEqual(result['nutrition5k']['complete_subset']['n'], 83)
            self.assertEqual(result['nutrition5k']['fallback_n'], 1)
            self.assertEqual(result['member_state_counts']['I']['fallback'], 1)

    def test_manifest_split_conflict_and_group_fold_leak_rejected(self):
        for variant in ('conflict', 'cross_fold'):
            rows = fixture_rows()
            if variant == 'conflict':
                rows[0]['partition'] = 'validation'
            else:
                rows[78]['fold'] = 4
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                driver.population(rows)

    def test_invalid_vector_rejected_and_zero_retained(self):
        row = fixture_rows()[0]
        members = {name: [make_record(row, 0)] for name in ('H', 'I')}
        seals = {name: {row['sample_id']: 'a' * 64} for name in members}
        result = driver.combine([row], members, seals, 'HI_mean')
        self.assertEqual(result[0]['prediction']['protein'], 0)
        for bad in (None, -1, float('nan')):
            altered = deepcopy(members)
            altered['H'][0]['prediction']['protein'] = bad
            altered['H'][0]['raw_prediction']['protein'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                driver.combine([row], altered, seals, 'HI_mean')

    def test_missing_completed_external_seal_not_recreated(self):
        with source_fixture() as (root, _, _):
            driver.run()
            directory = root / 'round3/runs/ensembles'
            (directory / 'HI_mean/records_sealed.json').unlink()
            before = snapshot(directory)
            with self.assertRaises(ValueError):
                driver.run()
            self.assertEqual(snapshot(directory), before)


if __name__ == '__main__':
    unittest.main()
