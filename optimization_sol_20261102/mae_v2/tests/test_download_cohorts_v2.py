"""Network-free downloader recovery, byte-budget and privacy tests."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import cohorts_v2 as c
import download_cohorts_v2 as d


class Response:
    def __init__(self, url, body, *, declared=None, status=200):
        self.url, self.stream, self.status = url, io.BytesIO(body), status
        self.headers = {'Content-Length': str(len(body) if declared is None else declared)}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def geturl(self):
        return self.url

    def read(self, count):
        return self.stream.read(count)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.dish = 'dish_1500000000'
        self.url = f'{c.BASE_URL}/{self.dish}/rgb.png'
        self.destination = f'data/incoming/{c.rank("incoming", self.dish)}/rgb.png'
        proposal = {'downloads': [{'dish_id': self.dish, 'source_url': self.url,
            'destination': self.destination, 'max_bytes': c.MAX_IMAGE_BYTES}]}
        c.frozen_write(self.base, 'data/freeze/cohort_proposal.json', c.json_bytes(proposal), private=True)
        summary = {'proposal_sha256': c.sha256(self.base / 'data/freeze/cohort_proposal.json'),
                   'downloads': {'exact_file_count': 1}}
        c.frozen_write(self.base, 'evidence/audit_summary.json', c.json_bytes(summary))
        buffer = io.BytesIO()
        Image.new('RGB', (640, 480), (17, 31, 55)).save(buffer, format='PNG')
        self.png = buffer.getvalue()

    def tearDown(self):
        self.temp.cleanup()

    def run_download(self, opener, budget=100_000):
        return d.download(v2_root=self.base, authorized=True, max_total_bytes=budget,
                          opener=opener, sleep_fn=lambda _: None, finalize=False)

    def success(self, request, **kwargs):
        return Response(request.full_url, self.png)

    def test_authorization_required_before_opener_or_files(self):
        opener = Mock(side_effect=AssertionError('network'))
        with self.assertRaisesRegex(c.AuditError, 'explicit_download_authorization_required'):
            d.download(v2_root=self.base, opener=opener, finalize=False)
        opener.assert_not_called()
        self.assertFalse((self.base / 'data/downloads').exists())

    def test_exact_proposal_download_and_resume_without_network(self):
        opener = Mock(side_effect=self.success)
        result = self.run_download(opener)
        self.assertEqual(result['received_bytes_recorded'], len(self.png))
        self.assertEqual(result['completed_files'], 1)
        self.assertEqual((self.base / self.destination).read_bytes(), self.png)
        self.assertEqual((self.base / self.destination).stat().st_mode & 0o777, 0o600)
        never = Mock(side_effect=AssertionError('should resume locally'))
        self.assertEqual(self.run_download(never), result)
        never.assert_not_called()

    def test_retries_persist_and_provider_error_text_is_not_logged(self):
        calls = []
        def opener(request, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise OSError('PRIVATE_PROVIDER_SENTINEL')
            return self.success(request)
        self.run_download(opener)
        attempts, _, _, _ = d.read_ledger(self.base / 'data/downloads/attempts.jsonl', {self.dish})
        self.assertEqual(attempts[self.dish], 3)
        self.assertNotIn('PRIVATE_PROVIDER_SENTINEL', (self.base / 'data/downloads/attempts.jsonl').read_text())

    def test_three_failed_attempts_are_not_reset_on_resume(self):
        opener = Mock(side_effect=OSError('transient'))
        for _ in range(2):
            with self.assertRaisesRegex(c.AuditError, 'download_attempts_exhausted'):
                self.run_download(opener)
        self.assertEqual(opener.call_count, 3)

    def test_reserved_byte_budget_survives_restart(self):
        opener = Mock(side_effect=self.success)
        for _ in range(2):
            with self.assertRaisesRegex(c.AuditError, 'download_byte_budget'):
                self.run_download(opener, budget=1)
        self.assertEqual(opener.call_count, 1)
        _, _, reserved, actual = d.read_ledger(self.base / 'data/downloads/attempts.jsonl', {self.dish})
        self.assertEqual((reserved, actual), (1, 1))

    def test_crash_reservations_remain_charged_and_attempt_consumed(self):
        ledger = self.base / 'data/downloads/attempts.jsonl'
        d.append_event(ledger, {'event': 'start', 'dish_id': self.dish, 'attempt': 1})
        d.append_event(ledger, {'event': 'reserve', 'dish_id': self.dish, 'attempt': 1, 'bytes': 300})
        result = self.run_download(self.success)
        self.assertEqual(result['reserved_transfer_bytes'], 300 + len(self.png))
        attempts, _, _, _ = d.read_ledger(ledger, {self.dish})
        self.assertEqual(attempts[self.dish], 2)

    def test_redirect_response_rejected_without_retry(self):
        opener = Mock(return_value=Response('https://unapproved.invalid/image', self.png))
        with self.assertRaisesRegex(c.AuditError, 'download_redirect_rejected'):
            self.run_download(opener)
        self.assertEqual(opener.call_count, 1)

    def test_real_redirect_handler_never_creates_redirect_request(self):
        self.assertIsNone(d.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.invalid'))

    def test_oversized_declared_body_rejected_before_read(self):
        response = Response(self.url, b'', declared=c.MAX_IMAGE_BYTES + 1)
        response.read = Mock(side_effect=AssertionError('must not read'))
        with self.assertRaisesRegex(c.AuditError, 'download_image_byte_limit'):
            self.run_download(lambda *args, **kwargs: response)
        response.read.assert_not_called()

    def test_non_rgb_or_wrong_size_image_is_integrity_failure(self):
        buffer = io.BytesIO()
        Image.new('RGB', (64, 48)).save(buffer, format='PNG')
        opener = Mock(return_value=Response(self.url, buffer.getvalue()))
        with self.assertRaisesRegex(c.AuditError, 'download_image_format_mismatch'):
            self.run_download(opener)
        self.assertEqual(opener.call_count, 1)

    def test_changed_completed_image_is_not_silently_replaced(self):
        self.run_download(self.success)
        changed = io.BytesIO()
        Image.new('RGB', (640, 480), (1, 2, 3)).save(changed, format='PNG')
        (self.base / self.destination).write_bytes(changed.getvalue())
        with self.assertRaisesRegex(c.AuditError, 'completed_incoming_image_changed'):
            self.run_download(Mock(side_effect=AssertionError('must not download')))

    def test_changed_proposal_rejected_before_network(self):
        (self.base / 'data/freeze/cohort_proposal.json').write_text('{}')
        opener = Mock(side_effect=AssertionError('network'))
        with self.assertRaisesRegex(c.AuditError, 'download_proposal_hash_mismatch'):
            self.run_download(opener)
        opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
