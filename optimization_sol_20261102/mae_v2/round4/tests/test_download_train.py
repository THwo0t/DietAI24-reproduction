"""Synthetic, network-free tests of the exact quarantined-download action."""
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import download_train as d


class Response:
    def __init__(self, url, body, *, length=None, status=200, encoding='identity'):
        self.url, self.stream, self.status = url, io.BytesIO(body), status
        self.headers = {'Content-Length': str(len(body)) if length is None else length,
                        'Content-Encoding': encoding}

    def __enter__(self): return self
    def __exit__(self, *args): return None
    def geturl(self): return self.url
    def read(self, size): return self.stream.read(size)


def snapshot(path):
    return {p.relative_to(path).as_posix(): (d.digest(p.read_bytes()), p.stat().st_mtime_ns)
            for p in path.rglob('*') if p.is_file()}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.body = b'synthetic opaque payload; no image parsing' * 2000
        self.dish = 'dish_1500000000'
        self.url = f'{d.BASE_URL}/{self.dish}/rgb.png'
        destination = 'round4/data/incoming/' + d.digest((d.SEED + '|incoming|' + self.dish).encode()) + '/rgb.png'
        self.entry = {'dish_id': self.dish, 'source_url': self.url, 'planned_destination': destination,
                      'cached_object_bytes': len(self.body), 'max_image_bytes': d.MAX_IMAGE_BYTES,
                      'screening_component_id': 'synthetic-component', 'original_component_id': 'synthetic-original',
                      'recipe_sha256': 'a' * 64, 'in_archived_available_frame': False,
                      'pixel_verification': 'pending_authorized_download'}
        frozen = {}
        for name in d.FROZEN_PATHS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'synthetic_freeze': name}))
            frozen[name] = d.digest(path.read_bytes())
        self.proposal = {'schema_version': 1, 'seed': d.SEED, 'status': 'awaiting_new_download_authorization',
                         'actual_images_and_screening_groups': 1, 'entries': [self.entry],
                         'original_frozen_hashes': frozen}
        self.summary = {'proposal_relative_path': d.PROPOSAL, 'status': 'awaiting_new_download_authorization',
                        'seed': d.SEED, 'new_download_file_count': 1, 'selected_groups': 1, 'selected_images': 1,
                        'cached_download_byte_estimate': len(self.body), 'maximum_per_image_bytes': d.MAX_IMAGE_BYTES,
                        'selected_already_local': 0, 'downloaded_images': 0,
                        'new_download_authorization_received': False, 'automatic_replacement_permitted': False,
                        'postdownload_blind_dedup_and_quarantine_required': True, 'source_freezes_unchanged': True,
                        'original_frozen_hashes': self.proposal['original_frozen_hashes']}
        self.stack.enter_context(patch.object(d, 'FILE_COUNT', 1))
        self.stack.enter_context(patch.object(d, 'CACHED_TOTAL_BYTES', len(self.body)))
        self.stack.enter_context(patch.object(d, 'MAX_TOTAL_BYTES', 1000000))
        self.stack.enter_context(patch.object(d, 'ROOT', self.root))
        self.repin()

    def tearDown(self): self.stack.close()

    def repin(self):
        path = self.root / d.PROPOSAL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.proposal))
        proposal_hash = d.digest(path.read_bytes())
        self.summary['proposal_sha256'] = proposal_hash
        summary_path = self.root / d.SUMMARY
        summary_path.write_text(json.dumps(self.summary))
        self.stack.enter_context(patch.object(d, 'PROPOSAL_SHA256', proposal_hash))
        self.stack.enter_context(patch.object(d, 'SUMMARY_SHA256', d.digest(summary_path.read_bytes())))

    def success(self, request, **kwargs):
        self.assertEqual(request.full_url, self.url)
        self.assertEqual(request.get_method(), 'GET')
        return Response(request.full_url, self.body)

    def run_download(self, opener=None):
        return d.download(root=self.root, authorized=True, opener=opener or self.success, sleep_fn=lambda _: None)

    def ledger(self): return d.read_ledger(self.root, [self.entry])

    def test_default_dry_run_reads_only_pinned_proposal_no_files_or_network(self):
        before = snapshot(self.root)
        never = Mock(side_effect=AssertionError('network'))
        with patch.object(d.urllib.request, 'build_opener', never):
            result = d.download(root=self.root, opener=never)
        never.assert_not_called()
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(result['network_requests'], 0)
        self.assertEqual(result['file_count'], 1)
        self.assertFalse(result['training_release'])
        self.assertFalse((self.root / d.DOWNLOADS).exists())

    def test_complete_and_resume_without_rewrite_or_network(self):
        result = self.run_download()
        self.assertEqual(result['received_body_bytes_recorded'], len(self.body))
        self.assertEqual(result['reserved_response_body_bytes'], len(self.body) + 1)
        self.assertFalse(result['pixel_verification_performed'])
        receipts = d.decode((self.root / d.DOWNLOADS / 'receipts.json').read_bytes())
        self.assertEqual(receipts['entries'], [{'dish_id': self.dish,
            'destination': self.entry['planned_destination'], 'source_url': self.url,
            'bytes': len(self.body), 'bytes_sha256': d.digest(self.body), 'attempts_consumed': 1}])
        self.assertEqual(result['receipts_sha256'], d.digest((self.root / d.DOWNLOADS / 'receipts.json').read_bytes()))
        before = snapshot(self.root)
        never = Mock(side_effect=AssertionError('network'))
        self.assertEqual(self.run_download(never), result)
        never.assert_not_called()
        self.assertEqual(snapshot(self.root), before)
        path = self.root / self.entry['planned_destination']
        self.assertEqual(path.read_bytes(), self.body)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for part in ('round4/downloads', 'round4/data', 'round4/data/incoming', str(path.parent.relative_to(self.root))):
            self.assertEqual((self.root / part).stat().st_mode & 0o777, 0o700)
        for file in (self.root / d.DOWNLOADS).iterdir():
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_three_attempts_persist_and_errors_are_redacted(self):
        opener = Mock(side_effect=OSError('PRIVATE_ERROR https://secret.invalid/token'))
        for _ in range(2):
            with self.assertRaisesRegex(d.DownloadError, 'attempts_exhausted'):
                self.run_download(opener)
        self.assertEqual(opener.call_count, 3)
        states, reserved, received = self.ledger()
        self.assertEqual(states[self.dish]['attempt'], 3)
        self.assertEqual(reserved, 3 * (len(self.body) + 1))
        self.assertEqual(received, 0)
        text = (self.root / d.DOWNLOADS / 'attempts.jsonl').read_text()
        self.assertNotIn('PRIVATE_ERROR', text)
        self.assertNotIn('https://', text)

    def test_retry_then_success_same_url_only(self):
        calls = []
        def opener(request, **kwargs):
            calls.append(request.full_url)
            if len(calls) < 3: raise OSError('temporary')
            return self.success(request, **kwargs)
        result = self.run_download(opener)
        self.assertEqual(calls, [self.url] * 3)
        self.assertEqual(result['attempts_consumed'], 3)

    def test_reserve_precedes_network_and_survives_crash(self):
        def crash(request, **kwargs):
            states, reserved, _ = self.ledger()
            self.assertEqual(states[self.dish]['attempt'], 1)
            self.assertEqual(reserved, len(self.body) + 1)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.run_download(crash)
        result = self.run_download()
        self.assertEqual(result['attempts_consumed'], 2)
        self.assertEqual(result['reserved_response_body_bytes'], 2 * (len(self.body) + 1))

    def test_mid_body_crash_discards_partial_but_retains_budget(self):
        response = Response(self.url, self.body)
        original = response.read
        count = 0
        def read(size):
            nonlocal count
            count += 1
            if count == 2: raise KeyboardInterrupt()
            return original(size)
        response.read = read
        with self.assertRaises(KeyboardInterrupt): self.run_download(lambda *a, **k: response)
        self.assertTrue((self.root / (self.entry['planned_destination'] + '.part')).exists())
        result = self.run_download()
        self.assertEqual(result['attempts_consumed'], 2)
        self.assertEqual(result['received_body_bytes_recorded'], len(self.body) + 65536)

    def test_ready_crash_recovers_without_request(self):
        with patch.object(d, 'finish_ready', side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.run_download()
        never = Mock(side_effect=AssertionError('network'))
        result = self.run_download(never)
        never.assert_not_called()
        self.assertEqual(result['attempts_consumed'], 1)

    def test_link_before_complete_crash_recovers_without_request(self):
        original = d.append_event
        def interrupted(base, event):
            if event['event'] == 'complete': raise KeyboardInterrupt()
            return original(base, event)
        with patch.object(d, 'append_event', interrupted), self.assertRaises(KeyboardInterrupt):
            self.run_download()
        self.assertTrue((self.root / self.entry['planned_destination']).exists())
        never = Mock(side_effect=AssertionError('network'))
        self.run_download(never)
        never.assert_not_called()

    def test_budget_exhaustion_blocks_before_new_request_and_persists(self):
        with patch.object(d, 'MAX_TOTAL_BYTES', len(self.body) + 1):
            opener = Mock(side_effect=KeyboardInterrupt())
            with self.assertRaises(KeyboardInterrupt): self.run_download(opener)
            with self.assertRaisesRegex(d.DownloadError, 'transfer_budget_exhausted'):
                self.run_download(opener)
            self.assertEqual(opener.call_count, 1)

    def test_changed_header_terminal_without_body_or_resume_retry(self):
        response = Response(self.url, self.body, length=str(len(self.body) + 1))
        response.read = Mock(side_effect=AssertionError('body'))
        opener = Mock(return_value=response)
        with self.assertRaisesRegex(d.DownloadError, 'cached_content_length_changed'):
            self.run_download(opener)
        with self.assertRaisesRegex(d.DownloadError, 'persisted_terminal'):
            self.run_download(opener)
        response.read.assert_not_called()
        self.assertEqual(opener.call_count, 1)

    def test_actual_short_and_overlong_bodies_terminal(self):
        for payload in (self.body[:-1], self.body + b'x'):
            with self.subTest(size=len(payload)):
                # Separate disk/ledger per subcase, retaining only pinned input files.
                with tempfile.TemporaryDirectory() as other:
                    base = Path(other)
                    for name in (d.PROPOSAL, d.SUMMARY, *d.FROZEN_PATHS):
                        (base / name).parent.mkdir(parents=True, exist_ok=True)
                        (base / name).write_bytes((self.root / name).read_bytes())
                    response = Response(self.url, payload, length=str(len(self.body)))
                    with self.assertRaisesRegex(d.DownloadError, 'cached_size'):
                        d.download(root=base, authorized=True, opener=lambda *a, **k: response, sleep_fn=lambda _: None)
                    self.assertFalse((base / self.entry['planned_destination']).exists())

    def test_redirect_rejected_no_follow_and_no_retry(self):
        self.assertIsNone(d.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid'))
        opener = Mock(return_value=Response('https://other.invalid', self.body))
        with self.assertRaisesRegex(d.DownloadError, 'redirect_rejected'): self.run_download(opener)
        self.assertEqual(opener.call_count, 1)

    def test_http_404_nonretryable_and_cli_does_not_print_error_url(self):
        error = urllib.error.HTTPError('https://SECRET.invalid', 404, 'PRIVATE_TEXT', {}, io.BytesIO(b'PRIVATE_BODY'))
        opener = Mock(side_effect=error)
        with patch.object(d.urllib.request, 'build_opener', return_value=Mock(open=opener)):
            output = io.StringIO()
            with redirect_stdout(output): code = d.main(['--authorized'])
        self.assertEqual(code, 2)
        self.assertNotIn('PRIVATE', output.getvalue())
        self.assertNotIn('https://', output.getvalue())
        self.assertEqual(opener.call_count, 1)

    def test_completed_payload_change_or_loss_is_not_redownloaded(self):
        self.run_download()
        path = self.root / self.entry['planned_destination']
        path.write_bytes(b'x' * len(self.body))
        never = Mock(side_effect=AssertionError('network'))
        with self.assertRaisesRegex(d.DownloadError, 'incoming_payload_changed'): self.run_download(never)
        path.unlink()
        with self.assertRaisesRegex(d.DownloadError, 'completed_incoming_payload_missing'): self.run_download(never)
        never.assert_not_called()

    def test_proposal_or_summary_hash_change_blocks_before_network(self):
        for name, code in ((d.PROPOSAL, 'proposal_hash'), (d.SUMMARY, 'summary_hash')):
            path = self.root / name
            before = path.read_bytes()
            path.write_bytes(before + b' ')
            with self.subTest(name=name), self.assertRaisesRegex(d.DownloadError, code):
                self.run_download(Mock(side_effect=AssertionError('network')))
            path.write_bytes(before)
        self.assertFalse((self.root / d.DOWNLOADS).exists())

    def test_exact_url_and_destination_checks_even_when_fixture_repinned(self):
        for field, bad in (('source_url', 'https://other.invalid/rgb.png'),
                           ('planned_destination', '../outside.png')):
            old = self.entry[field]
            self.entry[field] = bad
            self.repin()
            with self.subTest(field=field), self.assertRaises(d.DownloadError):
                self.run_download(Mock(side_effect=AssertionError('network')))
            self.entry[field] = old
        self.repin()

    def test_symlink_ancestor_and_partial_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'round4/data').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(d.DownloadError, 'symlink'): d.download(root=self.root)
        (self.root / 'round4/data').unlink()
        d.private_dir(self.root, Path(self.entry['planned_destination']).parent)
        (self.root / (self.entry['planned_destination'] + '.part')).symlink_to(outside / 'file')
        with self.assertRaisesRegex(d.DownloadError, 'symlink'):
            self.run_download(Mock(side_effect=AssertionError('network')))

    def test_unreceipted_file_and_truncated_ledger_rejected(self):
        d.private_dir(self.root, Path(self.entry['planned_destination']).parent)
        path = self.root / self.entry['planned_destination']
        path.write_bytes(self.body)
        path.chmod(0o600)
        with self.assertRaisesRegex(d.DownloadError, 'unreceipted'): self.run_download()
        path.unlink()
        ledger = self.root / d.DOWNLOADS / 'attempts.jsonl'
        ledger.write_bytes(b'{"event":')
        ledger.chmod(0o600)
        with self.assertRaisesRegex(d.DownloadError, 'truncated_download_ledger'): self.run_download()

    def test_completed_ledger_tampering_rejected_before_request(self):
        self.run_download()
        ledger = self.root / d.DOWNLOADS / 'attempts.jsonl'
        ledger.write_bytes(ledger.read_bytes() + b'\n')
        never = Mock(side_effect=AssertionError('network'))
        with self.assertRaises(d.DownloadError): self.run_download(never)
        never.assert_not_called()

    def test_completed_receipt_tampering_rejected_without_replacement(self):
        self.run_download()
        receipt = self.root / d.DOWNLOADS / 'receipts.json'
        value = d.decode(receipt.read_bytes())
        value['entries'][0]['bytes_sha256'] = 'f' * 64
        receipt.write_text(json.dumps(value))
        before = snapshot(self.root)
        never = Mock(side_effect=AssertionError('network'))
        with self.assertRaisesRegex(d.DownloadError, 'receipt_binding_changed'): self.run_download(never)
        self.assertEqual(snapshot(self.root), before)
        never.assert_not_called()

    def test_concurrent_writer_lock_rejected_before_request(self):
        d.private_dir(self.root, d.DOWNLOADS)
        lock = self.root / d.DOWNLOADS / '.lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            d.fcntl.flock(fd, d.fcntl.LOCK_EX | d.fcntl.LOCK_NB)
            never = Mock(side_effect=AssertionError('network'))
            with self.assertRaisesRegex(d.DownloadError, 'already_running'): self.run_download(never)
            never.assert_not_called()
        finally:
            os.close(fd)

    def test_changed_source_freeze_zero_network_and_no_files(self):
        for name in d.FROZEN_PATHS:
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            before = snapshot(self.root)
            never = Mock(side_effect=AssertionError('network'))
            with self.subTest(name=name), self.assertRaisesRegex(d.DownloadError, 'source_freeze_changed'):
                self.run_download(never)
            never.assert_not_called()
            self.assertEqual(snapshot(self.root), before)
            self.assertFalse((self.root / d.DOWNLOADS).exists())
            path.write_bytes(original)

    def test_freeze_inventory_is_exact_allowlist_not_arbitrary_paths(self):
        self.proposal['original_frozen_hashes']['../outside.json'] = 'f' * 64
        self.repin()
        never = Mock(side_effect=AssertionError('network'))
        with self.assertRaisesRegex(d.DownloadError, 'source_freeze_inventory_mismatch'):
            self.run_download(never)
        never.assert_not_called()
        self.assertFalse((self.root / d.DOWNLOADS).exists())

    def test_freeze_changed_during_transfer_blocks_completion_receipts(self):
        def opener(request, **kwargs):
            path = self.root / 'data/cohorts/dev_freeze.json'
            path.write_bytes(path.read_bytes() + b' ')
            return self.success(request, **kwargs)
        with self.assertRaisesRegex(d.DownloadError, 'source_freeze_changed'):
            self.run_download(opener)
        self.assertTrue((self.root / self.entry['planned_destination']).exists())
        self.assertFalse((self.root / d.DOWNLOADS / 'receipts.json').exists())
        self.assertFalse((self.root / d.DOWNLOADS / 'download_summary.json').exists())


if __name__ == '__main__':
    unittest.main()
