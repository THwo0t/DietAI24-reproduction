import sys
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import json
import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from opt_provider import ProviderStop
from round5.src.component_runtime import BoundTrace, ComponentProvider, NAMESPACE
from round5.src import component_runtime as runtime

URL_A = 'data:image/png;base64,QUFB'
URL_B = 'data:image/png;base64,QkJC'


class Fake:
    namespace = NAMESPACE

    def __init__(self, cache):
        self.cache, self.calls, self.error = cache, 0, None

    def chat(self, messages, max_completion_tokens=4096):
        self.calls += 1
        if self.error:
            raise self.error
        return '{"ok":true}'


def messages(*urls):
    return [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': url}} for url in urls]}]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fake = Fake(Path(self.temp.name))
        self.trace = BoundTrace(self.fake)

    def test_ordered_binding_and_repair_receipts(self):
        with self.trace.expect([URL_A, URL_B]):
            mark = self.trace.mark()
            self.trace.chat(messages(URL_A, URL_B))
            self.trace.chat(messages(URL_A, URL_B) + [{'role': 'user', 'content': 'format repair'}])
        refs = self.trace.refs_since(mark)
        self.assertEqual(len(refs), 2)
        self.assertTrue(all(row['status'] == 'returned' for row in refs))
        self.assertNotEqual(refs[0]['request_hash'], refs[1]['request_hash'])
        self.assertNotIn('messages', refs[0])
        refs[0]['status'] = 'changed'
        self.assertEqual(self.trace.refs_since(0)[0]['status'], 'returned')

    def test_swapped_or_added_image_fails_before_provider(self):
        with self.trace.expect([URL_A, URL_B]):
            for urls in ((URL_B, URL_A), (URL_A,), (URL_A, URL_B, URL_A)):
                with self.assertRaises(ValueError):
                    self.trace.chat(messages(*urls))
        self.assertEqual(self.fake.calls, 0)

    def test_scope_and_namespace_are_mandatory(self):
        with self.assertRaises(ValueError):
            self.trace.chat(messages(URL_A))
        self.fake.namespace = 'old-run'
        with self.trace.expect([URL_A]):
            with self.assertRaises(ValueError):
                self.trace.chat(messages(URL_A))
        self.assertEqual(self.fake.calls, 0)

    def test_exception_propagates_and_never_becomes_success(self):
        error = ProviderStop('invented service fault')
        self.fake.error = error
        with self.trace.expect([URL_A]):
            with self.assertRaises(ProviderStop) as caught:
                self.trace.chat(messages(URL_A))
        self.assertIs(caught.exception, error)
        self.assertEqual(self.trace.refs_since(0)[0]['status'], 'raised')
        self.assertIsNone(self.trace.refs_since(0)[0]['value_hash'])

    def test_scope_restored_after_exception_and_no_embeddings(self):
        with self.assertRaises(RuntimeError):
            with self.trace.expect([URL_A]):
                raise RuntimeError('fixture')
        with self.trace.expect([URL_A]):
            self.trace.chat(messages(URL_A))
        with self.assertRaises(ProviderStop):
            self.trace.embed(['not sent'])

    def test_local_image_bound_and_maximum(self):
        for urls in ([], [URL_A] * 14, ['https://example.invalid/image.png']):
            with self.assertRaises(ValueError):
                with self.trace.expect(urls):
                    self.fail('invalid image scope entered')

    def test_thread_local_images_and_receipts(self):
        barrier, counts, errors = threading.Barrier(2), [], []
        def worker(url):
            try:
                with self.trace.expect([url]):
                    barrier.wait()
                    self.trace.chat(messages(url))
                counts.append(len(self.trace.refs_since(0)))
            except BaseException as exc:
                errors.append(type(exc).__name__)
        threads = [threading.Thread(target=worker, args=(u,)) for u in (URL_A, URL_B)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(counts, [1, 1])
        self.assertEqual(self.trace.refs_since(0), [])

    def test_transport_settings_extend_only_registered_timeout(self):
        seen = {}
        def parent_init(instance, run_dir, **kwargs):
            seen.update(kwargs)
            instance.client = SimpleNamespace(timeout=None)
        with patch('round5.src.component_runtime.Provider.__init__', parent_init), \
             patch('round5.src.component_runtime.audit_state', return_value={}):
            provider = ComponentProvider(Path(self.temp.name), allow_paid=True)
        self.assertEqual(seen['namespace'], NAMESPACE)
        self.assertEqual(seen['timeout'], 600)
        timeout = provider.client.timeout
        self.assertEqual((timeout.read, timeout.connect, timeout.write, timeout.pool), (600, 30, 120, 120))

    def test_interrupted_reserved_attempt_is_preserved_across_provider_restart(self):
        root = Path(self.temp.name)
        keys = ('invented-chat-credential', 'invented-embedding-credential')
        transmissions = []
        def interrupted(request):
            transmissions.append(1)
            raise KeyboardInterrupt()
        def success(request):
            transmissions.append(1)
            return httpx.Response(200, json={'model': 'gpt-6.1-sol', 'choices': [
                {'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}], 'usage': {}})
        with patch.object(runtime.original, 'ROOT', root):
            first = ComponentProvider(root / 'round5/provider/K', allow_paid=True, keys=keys,
                                      transport=httpx.MockTransport(interrupted))
            try:
                with self.assertRaises(KeyboardInterrupt):
                    first.chat(messages(URL_A))
            finally:
                first.close()
            second = ComponentProvider(root / 'round5/provider/K', allow_paid=True, keys=keys,
                                       transport=httpx.MockTransport(success))
            try:
                self.assertEqual(second.chat(messages(URL_A)), '{"ok":true}')
            finally:
                second.close()
        counter = next((root / 'runtime_cache/attempts/chat').glob('*.json'))
        self.assertEqual(json.loads(counter.read_text())['attempts'], 2)
        rows = (root / 'round5/provider/K/requests.jsonl').read_text().splitlines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0])['attempt'], 2)
        self.assertEqual(len(transmissions), 2)

    def test_exhausted_unlogged_reservations_block_next_provider_before_http(self):
        root = Path(self.temp.name)
        keys = ('invented-chat-credential', 'invented-embedding-credential')
        transmissions = []
        def interrupted(request):
            transmissions.append(1)
            raise KeyboardInterrupt()
        with patch.object(runtime.original, 'ROOT', root):
            for _ in range(3):
                provider = ComponentProvider(root / 'round5/provider/K', allow_paid=True, keys=keys,
                                             transport=httpx.MockTransport(interrupted))
                try:
                    with self.assertRaises(KeyboardInterrupt):
                        provider.chat(messages(URL_A))
                finally:
                    provider.close()
            with self.assertRaises(Exception):
                ComponentProvider(root / 'round5/provider/K', allow_paid=True, keys=keys,
                                  transport=httpx.MockTransport(interrupted))
        self.assertEqual(len(transmissions), 3)


if __name__ == '__main__':
    unittest.main()
