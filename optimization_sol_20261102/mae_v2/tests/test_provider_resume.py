"""Persistent transmission bounds and component-token routing; no real credentials."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import opt_provider as p


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.object(p, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.sent = []

    def provider(self, handler):
        client = p.Provider(self.root / 'run', allow_paid=True,
                            keys=('fictitious-chat-key', 'fictitious-embed-key'),
                            transport=httpx.MockTransport(handler), sleep=lambda _: None)
        self.addCleanup(client.close)
        return client

    def test_completed_error_attempts_do_not_reset_on_restart(self):
        def handler(request):
            self.sent.append(request)
            return httpx.Response(503, json={'error': {'type': 'temporary'}})
        messages = [{'role': 'user', 'content': 'synthetic'}]
        with self.assertRaises(p.ProviderStop):
            self.provider(handler).chat(messages)
        self.assertEqual(len(self.sent), 3)
        with self.assertRaises(p.ProviderStop):
            self.provider(handler).chat(messages)
        self.assertEqual(len(self.sent), 3)

    def test_crash_after_reservation_consumes_attempt(self):
        payload = {'model': p.CHAT_MODEL, 'temperature': 1,
                   'max_completion_tokens': 4096, 'messages': []}
        key = p.fingerprint({'url': p.CHAT_URL, 'payload': payload, 'namespace': 'development'})
        first = self.provider(lambda _: None)
        self.assertEqual(first._reserve_attempt(key, 'chat'), 1)
        def handler(request):
            self.sent.append(request)
            return httpx.Response(503, json={})
        with self.assertRaises(p.ProviderStop):
            self.provider(handler).chat([])
        self.assertEqual(len(self.sent), 2)

    def test_only_registered_component_limit_and_response_cache(self):
        def handler(request):
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={'model': p.CHAT_MODEL, 'choices': [
                {'finish_reason': 'stop', 'message': {'content': 'ok'}}]})
        client = self.provider(handler)
        self.assertEqual(client.chat([], max_completion_tokens=8192), 'ok')
        self.assertEqual(client.chat([], max_completion_tokens=8192), 'ok')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['max_completion_tokens'], 8192)
        with self.assertRaises(p.ProviderStop):
            client.chat([], max_completion_tokens=16384)

    def test_corrupt_attempt_ledger_blocks_request(self):
        client = self.provider(lambda _: self.fail('must not send'))
        directory = self.root / 'runtime_cache/attempts/chat'
        directory.mkdir(parents=True)
        (directory / 'test.json').write_text('{"request_hash":"different","attempts":0}')
        with self.assertRaises(p.ProviderStop):
            client._reserve_attempt('test', 'chat')


if __name__ == '__main__':
    unittest.main()
