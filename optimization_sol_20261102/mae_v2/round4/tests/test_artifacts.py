"""Synthetic, provider-free checks of private immutable stage/run artifacts."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import artifacts as a


def snapshot(root):
    return {p.relative_to(root).as_posix():
            (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns,
             stat.S_IMODE(p.stat().st_mode))
            for p in root.rglob('*') if p.is_file()}


class ProviderStop(RuntimeError):
    pass


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binding = {'namespace': 'fixed-synthetic-provider', 'source': 'a' * 64,
                        'phase': 'J', 'train_freeze': 'b' * 64}
        self.sources = Mock(return_value=None)
        self.store = self.new_store()
        self.inputs = {'query_sha256': 'c' * 64, 'support_ids': ['t1', 't2']}
        self.records = {'q1': {'prediction': [1, 2]}, 'q2': {'failure': 'contract'}}

    def new_store(self, binding=None, expected=('q1', 'q2')):
        return a.ArtifactStore('runs/J', self.binding if binding is None else binding,
                               expected, verify_sources=self.sources, root=self.root)

    def path(self, suffix):
        return self.store.directory / suffix

    def stage_path(self, filename, name='q1:describe'):
        return self.path('stages/' + a.key_path(name) + '/' + filename)

    def write(self, path, value):
        path.write_bytes(a.canonical(value))
        path.chmod(0o600)

    def run_stage(self, call=None, validator=None, name='q1:describe', inputs=None):
        return self.store.stage_runner(name, self.inputs if inputs is None else inputs,
                                       call or (lambda: {'prediction': 7, 'failure': None}),
                                       validator or (lambda value: value))

    def completed(self):
        self.run_stage()
        return self.store.finalize(self.records)

    def test_fresh_and_cached_reparse_raw_and_return_canonical_wrapper(self):
        call = Mock(return_value={'result': {'value': '7'}, 'request_refs': ['request-1']})
        validator = Mock(side_effect=lambda value: {'result': {'value': int(value['result']['value'])},
                                                   'request_refs': value['request_refs']})
        expected = {'result': {'value': 7}, 'request_refs': ['request-1']}
        self.assertEqual(self.run_stage(call, validator), expected)
        self.assertEqual(self.run_stage(call, validator), expected)
        call.assert_called_once_with()
        self.assertEqual(validator.call_count, 2)
        self.assertEqual(validator.call_args.args[0]['result']['value'], '7')

    def test_contract_failure_is_terminal_json_not_retried(self):
        failed = {'prediction': None, 'failure': 'invalid_after_repair', 'repair_used': True,
                  'raw_outputs': ['first invalid', 'second invalid']}
        call = Mock(return_value=failed)
        self.assertEqual(self.run_stage(call), failed)
        self.assertEqual(self.run_stage(call), failed)
        call.assert_called_once_with()

    def test_changed_inputs_reject_before_call(self):
        self.run_stage()
        never = Mock(side_effect=AssertionError('must not call'))
        with self.assertRaises(a.ArtifactError):
            self.run_stage(never, inputs={'query_sha256': 'different'})
        never.assert_not_called()

    def test_changed_binding_on_reopen_or_mutated_binding_rejects(self):
        self.store.initialize()
        changed = dict(self.binding, source='d' * 64)
        with self.assertRaises(a.ArtifactError):
            self.new_store(changed).initialize()
        self.binding['namespace'] = 'changed'
        with self.assertRaises(a.ArtifactError):
            self.run_stage()

    def test_source_failure_before_work_has_no_new_files_or_calls(self):
        self.sources.return_value = False
        call = Mock()
        with self.assertRaises(a.ArtifactError):
            self.run_stage(call)
        call.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_source_or_input_mutation_during_call_cannot_seal(self):
        def mutate_source():
            self.sources.return_value = False
            return {'ok': True}
        with self.assertRaises(a.ArtifactError):
            self.run_stage(mutate_source)
        self.assertFalse(self.stage_path('result.seal.json').exists())
        self.sources.return_value = None
        def mutate_input():
            self.inputs['support_ids'].append('different')
            return {'ok': True}
        with self.assertRaises(a.ArtifactError):
            self.run_stage(mutate_input)
        self.assertFalse(self.stage_path('result.seal.json').exists())

    def test_provider_stop_propagates_identical_and_resume_keeps_namespace(self):
        error = ProviderStop('secret-request-body-must-never-be-logged')
        call = Mock(side_effect=[error, {'ok': True}])
        with self.assertRaises(ProviderStop) as caught:
            self.run_stage(call)
        self.assertIs(caught.exception, error)
        event = self.stage_path('events.jsonl').read_text()
        self.assertIn('ProviderStop', event)
        self.assertNotIn('secret-request', event)
        self.assertFalse(self.stage_path('result.json').exists())
        self.assertEqual(self.run_stage(call), {'ok': True})
        intent = a.decode(self.path('intent.json').read_bytes())
        self.assertEqual(intent['binding']['namespace'], 'fixed-synthetic-provider')

    def test_keyboard_interrupt_preserves_intent_and_resumes(self):
        call = Mock(side_effect=[KeyboardInterrupt(), {'ok': True}])
        with self.assertRaises(KeyboardInterrupt):
            self.run_stage(call)
        original_intent = self.stage_path('intent.json').read_bytes()
        self.assertEqual(self.run_stage(call), {'ok': True})
        self.assertEqual(self.stage_path('intent.json').read_bytes(), original_intent)

    def test_explicit_terminal_stage_error_never_calls_again(self):
        call = Mock(side_effect=a.TerminalStageError('insufficient_gallery'))
        for _ in range(2):
            with self.assertRaisesRegex(a.TerminalStageError, 'insufficient_gallery'):
                self.run_stage(call)
        call.assert_called_once_with()
        with self.assertRaises(ValueError):
            a.TerminalStageError('unsafe secret text')

    def test_validator_exception_is_safe_logged_and_not_disguised(self):
        error = ValueError('private raw body')
        with self.assertRaises(ValueError) as caught:
            self.run_stage(validator=Mock(side_effect=error))
        self.assertIs(caught.exception, error)
        event = self.stage_path('events.jsonl').read_text()
        self.assertIn('validator_exception', event)
        self.assertNotIn('private', event)

    def test_result_tamper_even_consistent_raw_and_parsed_rejects(self):
        self.run_stage()
        self.write(self.stage_path('result.json'), {'kind': 'result', 'raw': {'bad': 8}, 'parsed': {'bad': 8}})
        never = Mock()
        with self.assertRaisesRegex(a.ArtifactError, 'external_seal'):
            self.run_stage(never)
        never.assert_not_called()

    def test_missing_external_stage_seal_rejects_without_call(self):
        self.run_stage()
        self.stage_path('result.seal.json').unlink()
        never = Mock()
        with self.assertRaises(a.ArtifactError):
            self.run_stage(never)
        never.assert_not_called()

    def test_validator_drift_cannot_silently_reinterpret_cached_output(self):
        self.run_stage()
        with self.assertRaisesRegex(a.ArtifactError, 'cached_reparse_changed'):
            self.run_stage(validator=lambda raw: {'new': 'meaning'})

    def interrupt_after_result_receipt(self):
        original = self.store._write_once
        def interrupted(path, value):
            original(path, value)
            if path.endswith('/result.seal.json'):
                raise KeyboardInterrupt()
        with patch.object(self.store, '_write_once', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.run_stage()
        self.assertTrue(self.stage_path('result.seal.json').exists())
        self.assertFalse(self.stage_path('result.json').exists())
        self.assertTrue(self.stage_path('result.json.pending').exists())

    def test_sealed_pending_crash_recovers_without_provider_replay(self):
        self.interrupt_after_result_receipt()
        original = self.stage_path('result.seal.json').read_bytes()
        never = Mock(side_effect=AssertionError('no provider replay after receipt'))
        self.assertEqual(self.run_stage(never), {'prediction': 7, 'failure': None})
        never.assert_not_called()
        self.assertEqual(self.stage_path('result.seal.json').read_bytes(), original)

    def test_sealed_pending_crash_rejects_changed_body_without_replay(self):
        self.interrupt_after_result_receipt()
        self.write(self.stage_path('result.json.pending'), {'prediction': 99})
        never = Mock()
        with self.assertRaisesRegex(a.ArtifactError, 'stage_pending_external_seal_mismatch'):
            self.run_stage(never)
        never.assert_not_called()
        self.assertFalse(self.stage_path('result.json').exists())

    def test_sealed_pending_missing_body_rejects_without_replay(self):
        self.interrupt_after_result_receipt()
        self.stage_path('result.json.pending').unlink()
        never = Mock()
        with self.assertRaises(a.ArtifactError): self.run_stage(never)
        never.assert_not_called()

    def test_unsealed_pending_crash_can_resume_same_provider_namespace(self):
        original = self.store._write_once
        def interrupted(path, value):
            if path.endswith('/result.seal.json'): raise KeyboardInterrupt()
            return original(path, value)
        with patch.object(self.store, '_write_once', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): self.run_stage()
        self.assertFalse(self.stage_path('result.seal.json').exists())
        self.assertTrue(self.stage_path('result.json.pending').exists())
        call = Mock(return_value={'ok': 'provider cache observation may differ'})
        self.assertEqual(self.run_stage(call), call.return_value)
        call.assert_called_once_with()

    def test_names_scope_and_symlinks_rejected(self):
        for name in ('../escape', '/absolute', 'a/b', 'a..b', ''):
            with self.subTest(name=name), self.assertRaises(a.ArtifactError):
                self.run_stage(name=name)
        with self.assertRaises(a.ArtifactError):
            a.ArtifactStore(self.root / '../escape', self.binding, ['q'],
                            verify_sources=self.sources, root=self.root)
        self.path('').parent.mkdir(mode=0o700)
        self.path('').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(a.ArtifactError):
            self.new_store()

    def test_all_written_files_and_directories_are_private(self):
        self.completed()
        for p in self.root.rglob('*'):
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700 if p.is_dir() else 0o600)
        self.stage_path('result.json').chmod(0o644)
        with self.assertRaises(a.ArtifactError):
            self.store.verify_completed()

    def test_nonprivate_existing_directory_and_file_symlink_rejected(self):
        self.path('').mkdir(parents=True, mode=0o755)
        with self.assertRaises(a.ArtifactError):
            self.store.initialize()

    def test_stage_file_symlink_rejected(self):
        self.run_stage()
        target = self.root / 'elsewhere'
        target.write_bytes(self.stage_path('result.json').read_bytes())
        target.chmod(0o600)
        self.stage_path('result.json').unlink()
        self.stage_path('result.json').symlink_to(target)
        with self.assertRaises(a.ArtifactError):
            self.run_stage()

    def test_nonregular_lock_file_rejected(self):
        self.store.directory.mkdir(parents=True, mode=0o700)
        self.store.directory.parent.chmod(0o700)
        os.mkfifo(self.path('.lock'), mode=0o600)
        with self.assertRaises(a.ArtifactError):
            self.store.initialize()

    def test_concurrent_first_stage_directory_creation(self):
        self.store.initialize()
        original = Path.mkdir
        parent = self.path('stages')
        barrier = threading.Barrier(2)
        def synchronized_mkdir(path, *args, **kwargs):
            if path == parent:
                barrier.wait(timeout=5)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', synchronized_mkdir), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.run_stage, None, None, 'q1:first')
            second = pool.submit(self.run_stage, None, None, 'q2:first')
            self.assertEqual(first.result(timeout=5), {'prediction': 7, 'failure': None})
            self.assertEqual(second.result(timeout=5), {'prediction': 7, 'failure': None})

    def test_final_population_exact_missing_or_extra_records_rejected(self):
        for records in ({'q1': {}}, dict(self.records, q3={})):
            with self.assertRaises(a.ArtifactError):
                self.store.finalize(records)
        self.assertFalse(self.path('completion.json').exists())

    def test_incomplete_stage_prevents_final_seal(self):
        with self.assertRaises(ProviderStop):
            self.run_stage(Mock(side_effect=ProviderStop('safe')))
        with self.assertRaisesRegex(a.ArtifactError, 'stage_incomplete'):
            self.store.finalize(self.records)
        self.assertFalse(self.path('completion.json').exists())

    def test_extra_stage_or_root_artifacts_cannot_be_sanctioned_by_finalize(self):
        self.run_stage()
        extra = self.stage_path('unexpected.json')
        self.write(extra, {})
        with self.assertRaises(a.ArtifactError):
            self.store.finalize(self.records)
        extra.unlink()
        self.path('unknown').mkdir(mode=0o700)
        with self.assertRaises(a.ArtifactError):
            self.store.finalize(self.records)

    def test_completed_verification_and_reuse_are_read_only(self):
        self.assertEqual(self.completed(), self.records)
        before = snapshot(self.root)
        never = Mock(side_effect=AssertionError('provider must never be called'))
        self.assertEqual(self.store.verify_completed(), self.records)
        self.store.initialize()
        self.assertEqual(self.store.finalize(self.records), self.records)
        self.assertEqual(self.run_stage(never), {'prediction': 7, 'failure': None})
        never.assert_not_called()
        self.assertEqual(snapshot(self.root), before)

    def test_completed_rejects_new_stage_without_creating_anything(self):
        self.completed()
        before = snapshot(self.root)
        never = Mock()
        with self.assertRaises(a.ArtifactError):
            self.run_stage(never, name='q2:newstage')
        never.assert_not_called()
        self.assertEqual(snapshot(self.root), before)

    def test_completed_rejects_modified_record_missing_extra_and_directory(self):
        self.completed()
        record_path = self.path('records/' + a.key_path('q1') + '.json')
        raw = record_path.read_bytes()
        self.write(record_path, {'name': 'q1', 'record': {'bad': True}})
        with self.assertRaises(a.ArtifactError): self.store.verify_completed()
        record_path.write_bytes(raw)
        record_path.unlink()
        with self.assertRaises(a.ArtifactError): self.store.verify_completed()
        record_path.write_bytes(raw)
        record_path.chmod(0o600)
        self.write(self.path('unexpected.json'), {})
        with self.assertRaises(a.ArtifactError): self.store.verify_completed()
        self.path('unexpected.json').unlink()
        self.path('empty_extra').mkdir(mode=0o700)
        with self.assertRaises(a.ArtifactError): self.store.verify_completed()

    def test_completed_changed_binding_source_or_records_rejected(self):
        self.completed()
        with self.assertRaises(a.ArtifactError):
            self.new_store(dict(self.binding, phase='other')).verify_completed()
        with self.assertRaises(a.ArtifactError):
            self.store.finalize(dict(self.records, q1={'different': True}))
        self.sources.return_value = False
        with self.assertRaises(a.ArtifactError): self.store.verify_completed()

    def test_final_seal_crash_resume_preserves_existing_seal(self):
        self.run_stage()
        original = self.store._write_once
        def interrupted(path, value):
            if path == 'completion.json': raise KeyboardInterrupt()
            return original(path, value)
        with patch.object(self.store, '_write_once', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.store.finalize(self.records)
        seal = self.path('seal.json').read_bytes()
        self.assertEqual(self.store.finalize(self.records), self.records)
        self.assertEqual(self.path('seal.json').read_bytes(), seal)

    def test_completion_link_crash_leftover_is_verified_without_mutation(self):
        self.completed()
        os.link(self.path('completion.json'), self.path('completion.json.pending'))
        before = snapshot(self.root)
        self.assertEqual(self.store.verify_completed(), self.records)
        self.store.initialize()
        self.assertEqual(snapshot(self.root), before)
        self.path('completion.json.pending').unlink()
        self.write(self.path('completion.json.pending'), {'different': True})
        with self.assertRaises(a.ArtifactError): self.store.verify_completed()

    def test_distinct_stages_concurrent_same_stage_and_finalize_busy(self):
        self.store.initialize()
        started, release = threading.Event(), threading.Event()
        def active_call():
            started.set()
            if not release.wait(5): raise AssertionError('test synchronization timed out')
            return {'ok': True}
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = pool.submit(self.run_stage, active_call)
            self.assertTrue(started.wait(5))
            try:
                never = Mock()
                with self.assertRaises(a.ArtifactBusy): self.run_stage(never)
                never.assert_not_called()
                with self.assertRaises(a.ArtifactBusy): self.store.finalize(self.records)
                parallel = pool.submit(self.run_stage, lambda: {'other': True}, None, 'q2:describe')
                self.assertEqual(parallel.result(timeout=5), {'other': True})
            finally:
                release.set()
            self.assertEqual(active.result(timeout=5), {'ok': True})
        self.assertEqual(self.store.finalize(self.records), self.records)

    def test_duplicate_json_and_nonfinite_rejected(self):
        with self.assertRaises(a.ArtifactError): a.decode(b'{"a":1,"a":2}')
        with self.assertRaises(a.ArtifactError): a.decode(b'{"a":NaN}')
        with self.assertRaises(ValueError): self.run_stage(lambda: {'a': float('nan')})


if __name__ == '__main__':
    unittest.main()
