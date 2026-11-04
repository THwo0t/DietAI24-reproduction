"""Network-forbidden synthetic scientific equivalence and worker refusal tests."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import p_parallel_worker as worker
import test_run_p as original
from identity_gate_p import _load_snapshot
from opt_provider import sha, fingerprint
from stores_p import name
from runtime_p import Trace


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('socket.socket.connect', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.f = original.RunnerTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.addCleanup(worker.close_worker)
        self.f.execute()
        self.ids, self.out, self.adapter = self.f.stores
        self.contexts = self.adapter.verify_completed()['contexts']
        self.snapshot = _load_snapshot(self.f.ctx, self.f.ledger, self.ids, data_root=self.f.root)
        self.seal = sha(self.ids.directory/'completion.json')

    def configure(self, *, contexts=None, verifier=lambda value:True):
        worker._configure_for_test(self.f.ctx, self.f.ledger, self.ids, self.out,
            True, True, self.snapshot, self.contexts if contexts is None else contexts,
            {'synthetic':True}, root=self.f.root, trace_factory=Trace, verifier=verifier)
        worker.initialize_forked_worker()

    def test_exact_completed_rows_refs_conditional_fallback_without_provider(self):
        with patch('runtime_p.PProvider', side_effect=AssertionError('provider forbidden')):
            self.configure()
            refs = {}
            for row in self.f.ctx.rows:
                result = worker.identity_task(row)
                self.assertFalse(result['provider_constructed'])
                envelope = result['envelope']
                stem = name('identity', row)
                refs.update({stem+'-'+phase:deepcopy(group)
                             for phase, group in envelope['request_refs'].items()})
                fallback = self.f.ctx.fallbacks['folds'][row['dataset']][str(row['fold'])]
                predicted = worker.prediction_task(row, envelope['result'], envelope,
                    self.seal, fallback, self.contexts.get(row['sample_id']))
                self.assertFalse(predicted['provider_constructed'])
                self.assertEqual(predicted['record'], self.out.verify_completed()[name('record', row)])
                refs.update(predicted['all_refs'])
                if row['sample_id'] in self.contexts:
                    self.assertTrue(any('-conditional-' in key for key in predicted['all_refs']))
                if envelope['result']['status'] != 'ok':
                    self.assertTrue(all(value['fallback'] for value in predicted['record']['profiles'].values()))
            self.assertEqual(fingerprint(refs), self.out.verify_completed()['service-proof']['stage_refs_sha256'])

    def test_cached_envelope_is_replayed_not_trusted(self):
        self.configure()
        row = self.f.ctx.rows[0]
        with patch.object(worker, 'identify', wraps=worker.identify) as replay:
            worker.identity_task(row)
            self.assertEqual(replay.call_count, 1)
            self.assertIsInstance(replay.call_args.args[2], worker.RowReplay)
        real = worker.identify
        def changed(*args, **kwargs):
            envelope = real(*args, **kwargs)
            envelope['result'] = {'status':'forged'}
            return envelope
        with patch.object(worker, 'identify', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'exact_scientific_replay'):
                worker.identity_task(row)

    def test_engineering_reverified_each_task_and_changed_row_refused(self):
        checks = []
        self.configure(verifier=lambda value: checks.append(deepcopy(value)))
        before = len(checks)
        worker.identity_task(self.f.ctx.rows[0])
        self.assertEqual(len(checks), before+1)
        row = {**self.f.ctx.rows[0], 'fold':99}
        with self.assertRaisesRegex(ValueError, 'row_changed'):
            worker.identity_task(row)

    def test_inherited_trace_and_unregistered_context_refused(self):
        self.configure()
        with self.assertRaisesRegex(ValueError, 'inherited_trace'):
            worker.initialize_forked_worker()
        row = self.f.ctx.rows[0]
        envelope = worker.identity_task(row)['envelope']
        fallback = self.f.ctx.fallbacks['folds'][row['dataset']][str(row['fold'])]
        with self.assertRaisesRegex(ValueError, 'context_changed'):
            worker.prediction_task(row, envelope['result'], envelope, self.seal,
                                   fallback, {'unregistered':True})

    def test_public_configuration_rejects_synthetic_context(self):
        with self.assertRaisesRegex(ValueError, 'context_origin_changed'):
            worker.configure(self.f.ctx, self.f.ledger, self.ids, self.out, True, True,
                             engineering={'synthetic':True})


if __name__ == '__main__':
    unittest.main()
