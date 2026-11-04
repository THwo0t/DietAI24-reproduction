"""Negative-path and record-boundary checks; no provider construction."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('c_repro_runner_tests', HERE / 'run.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class Boundaries(unittest.TestCase):
    def row(self):
        return dict(sample_id='sample', dataset='nutrition5k', group_id='group', fold=0)

    def test_record_retains_average_density_not_primary_density(self):
        row = self.row()
        identity = dict(final_codes=['12345678', '23456789'], retrieved_codes=['12345678', '23456789'])
        portion = dict(status='ok', prediction=dict(weight=100., energy=150., fat=2., carbs=3., protein=4.),
                       raw_leaves=[dict(item_id='i1', grams=100., code='12345678', codes=identity['final_codes'],
                                       density=dict(energy=150., fat=2., carbs=3., protein=4.))])
        out = r.n5_record(row, identity, portion, {})
        self.assertEqual(out['raw_leaves'], portion['raw_leaves'])
        self.assertEqual(out['prediction']['energy'], 150.)
        self.assertEqual(out['prediction']['weight'], 100.)

    def test_fallback_and_repair_are_explicit_and_not_native_success(self):
        fallback = dict.fromkeys(r.KEYS, 1.)
        out = r.n5_record(self.row(), {}, dict(status='failed', failure='invalid_mass'), fallback)
        self.assertTrue(out['fallback'])
        self.assertFalse(out['native_complete'])
        self.assertEqual(out['prediction'], fallback)
        out = r.n5_record(self.row(), {'repaired': True}, dict(status='ok', prediction=fallback), {})
        self.assertTrue(out['repair_used'])
        self.assertFalse(out['native_complete'])

    def test_ASA_density_uses_only_branch_code_and_projects_legal_option(self):
        catalog = {'foods': {'12345678': {'density': dict(energy=100., fat=1., carbs=2., protein=3.)}}}
        options = [dict(option_id='s1', description='small', grams=100.),
                   dict(option_id='s2', description='large', grams=150.)]
        out = r.asa_branch(dict(status='ok', continuous_grams=140., prediction={'weight': 999.}),
                           '12345678', options, catalog, {})
        self.assertEqual(out['prediction']['weight'], 150.)
        self.assertEqual(out['prediction']['energy'], 150.)
        self.assertEqual(out['continuous_grams'], 140.)

    def test_parallel_stops_provider_after_worker_fault(self):
        class Provider:
            stopped = False
        provider = Provider()
        with self.assertRaisesRegex(ValueError, 'bad_input'):
            r.parallel([self.row()], lambda row: (_ for _ in ()).throw(ValueError('bad_input')), provider, 1)
        self.assertTrue(provider.stopped)

    def test_score_does_not_load_labels_when_completion_check_fails(self):
        ctx = dict(rows=[self.row()], frozen='frozen')
        with patch.object(r, 'context', return_value=ctx), patch('score.completed_records', side_effect=ValueError('incomplete')), \
                patch.object(r, 'load', side_effect=AssertionError('labels opened')):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                r.score_completed()

    def test_identity_seal_rejects_missing_or_changed_identity(self):
        row = dict(sample_id='asa', dataset='asa24', group_id='group', fold=0)
        ctx = dict(rows=[row], frozen='frozen')
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            directory = Path(temp)
            store = r.Store(directory, 'frozen', 529)
            with self.assertRaisesRegex(ValueError, 'seal_required'):
                r.validate_identity_seal(ctx, directory)
            identity = {'final_codes': ['12345678']}
            binding = dict(row=row, config=r.ASA_CONFIG)
            store.put('identity', 'asa', binding, identity)
            store.put('identity_seal', 'all', dict(population=['asa'], method='all_blind_identities_before_conditional_context'),
                      {'asa': r.fingerprint(identity)})
            self.assertEqual(r.validate_identity_seal(ctx, directory), {'asa': r.fingerprint(identity)})
            path = store.path('identity', 'asa')
            value = json.loads(path.read_text())
            value['value']['final_codes'] = ['23456789']
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'saved_stage_changed'):
                r.validate_identity_seal(ctx, directory)

    def test_transport_slots_are_global_and_released(self):
        from newcommon import CachedProvider
        provider = object.__new__(CachedProvider)
        provider.stopped = False
        mutex = threading.Lock()
        acquired = threading.Barrier(32)
        active = 0
        peak = 0
        def worker(n):
            nonlocal active, peak
            with provider.transport_slot(format(n, '064x')):
                with mutex:
                    active += 1
                    peak = max(peak, active)
                acquired.wait(timeout=15)
                with mutex:
                    active -= 1
        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(worker, range(32)))
        self.assertEqual(peak, 32)
        self.assertEqual(active, 0)


if __name__ == '__main__':
    unittest.main()
