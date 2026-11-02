"""Synthetic providers and prepopulated synthetic caches; no client/key files."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

V2 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(V2 / 'src'))
sys.path.insert(0, str(V2 / 'round4/src'))
import opt_provider as original
import trace_provider as t


def independent_hash(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


class FakeProvider:
    namespace = t.NAMESPACE

    def __init__(self, cache):
        self.cache = cache
        self.chat_calls, self.embed_calls = [], []

    @property
    def keys(self):
        raise AssertionError('tracer must not read keys')

    @property
    def client(self):
        raise AssertionError('tracer must not read client')

    def chat(self, messages, max_completion_tokens=4096):
        self.chat_calls.append((messages, max_completion_tokens))
        return 'synthetic response'

    def embed(self, texts):
        self.embed_calls.append(texts)
        return [[float(len(text)), 1.0] for text in texts]


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=V2 / 'round4/tests')
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)
        self.provider = FakeProvider(self.cache)
        self.trace = t.TraceProvider(self.provider)

    def test_chat_payload_hash_and_result_are_exact(self):
        messages = [{'role': 'user', 'content': 'synthetic 食物 text'}]
        result = self.trace.chat(messages, max_completion_tokens=8192)
        payload = {'model': original.CHAT_MODEL, 'temperature': 1,
                   'max_completion_tokens': 8192, 'messages': messages}
        expected = independent_hash({'url': original.CHAT_URL, 'payload': payload, 'namespace': t.NAMESPACE})
        self.assertEqual(self.trace.refs_since(0), [{'role': 'chat', 'request_hash': expected,
            'value_hash': independent_hash(result), 'status': 'returned', 'cache_present_before': False}])
        self.assertIs(self.provider.chat_calls[0][0], messages)

    def test_embeddings_are_per_text_on_official_route(self):
        values = self.trace.embed(['first text', 'second text'])
        self.assertEqual(self.provider.embed_calls, [['first text'], ['second text']])
        refs = self.trace.refs_since(0)
        self.assertEqual(len(refs), 2)
        for text, value, ref in zip(['first text', 'second text'], values, refs):
            expected = independent_hash({'url': original.EMBED_URL,
                'payload': {'model': original.EMBED_MODEL, 'input': [text], 'encoding_format': 'float'},
                'namespace': 'official-query-v1'})
            self.assertEqual(ref['request_hash'], expected)
            self.assertEqual(ref['value_hash'], independent_hash(value))
            self.assertEqual(ref['role'], 'embedding')

    def test_existing_provider_request_accepts_the_same_cached_hashes(self):
        # Use the real Provider methods with a deliberately uninitialized client
        # and presealed synthetic caches. __init__/credentials/network never run.
        provider = object.__new__(original.Provider)
        provider.namespace, provider.cache = t.NAMESPACE, self.cache
        provider.keys = ('synthetic-chat-sentinel', 'synthetic-embedding-sentinel')
        provider.lock, provider.key_locks = threading.Lock(), {}
        trace = t.TraceProvider(provider)
        messages = [{'role': 'user', 'content': 'offline cache contract'}]
        vector = [1.0] + [0.0] * 3071
        pairs = [('chat', original.CHAT_URL, original.CHAT_MODEL,
                  {'model': original.CHAT_MODEL, 'temperature': 1, 'max_completion_tokens': 4096,
                   'messages': messages}, 'cached text', t.NAMESPACE),
                 ('embedding', original.EMBED_URL, original.EMBED_MODEL,
                  {'model': original.EMBED_MODEL, 'input': ['offline vector'], 'encoding_format': 'float'},
                  vector, 'official-query-v1')]
        expected_hashes = []
        for role, url, model, payload, value, namespace in pairs:
            request_hash = independent_hash({'url': url, 'payload': payload, 'namespace': namespace})
            expected_hashes.append(request_hash)
            path = self.cache / role / (request_hash + '.json')
            path.parent.mkdir()
            path.write_text(json.dumps({'request_hash': request_hash, 'model': model,
                                        'value': value, 'value_hash': independent_hash(value)}))
        with mock.patch.object(original, 'read_credentials', side_effect=AssertionError('no credentials')):
            self.assertEqual(trace.chat(messages), 'cached text')
            self.assertEqual(trace.embed(['offline vector']), [vector])
        refs = trace.refs_since(0)
        self.assertEqual([ref['request_hash'] for ref in refs], expected_hashes)
        self.assertTrue(all(ref['cache_present_before'] for ref in refs))
        self.assertFalse(hasattr(provider, 'client'))

    def test_exception_keeps_reference_without_exception_text(self):
        secret_message = 'synthetic-private-response-and-credential-fragment'
        error = original.ProviderStop(secret_message)
        with mock.patch.object(self.provider, 'chat', side_effect=error):
            with self.assertRaises(original.ProviderStop) as raised:
                self.trace.chat([{'role': 'user', 'content': secret_message}])
        self.assertIs(raised.exception, error)
        ref = self.trace.refs_since(0)[0]
        self.assertEqual((ref['status'], ref['value_hash']), ('raised', None))
        self.assertNotIn(secret_message, json.dumps(ref))

    def test_later_embedding_exception_preserves_earlier_value_hash(self):
        error = original.ProviderStop('synthetic failure body must not persist')
        with mock.patch.object(self.provider, 'embed', side_effect=[[[1.0]], error]):
            with self.assertRaises(original.ProviderStop):
                self.trace.embed(['first', 'second'])
        refs = self.trace.refs_since(0)
        self.assertEqual([ref['status'] for ref in refs], ['returned', 'raised'])
        self.assertEqual(refs[0]['value_hash'], independent_hash([1.0]))
        self.assertIsNone(refs[1]['value_hash'])

    def test_cache_presence_is_only_observation_without_reading_contents(self):
        messages = [{'role': 'user', 'content': 'same'}]
        self.trace.chat(messages)
        ref = self.trace.refs_since(0)[0]
        path = self.cache / 'chat' / (ref['request_hash'] + '.json')
        path.parent.mkdir()
        path.write_bytes(b'not JSON; the tracer must not read this body')
        marker = self.trace.mark()
        self.trace.chat(messages)
        later = self.trace.refs_since(marker)[0]
        self.assertEqual(later['request_hash'], ref['request_hash'])
        self.assertTrue(later['cache_present_before'])
        self.assertNotIn('cache_hit', later)
        self.assertEqual(len(self.provider.chat_calls), 2)

    def test_trace_copies_are_detached_and_mark_is_current_thread(self):
        self.trace.chat([{'role': 'user', 'content': 'first'}])
        marker = self.trace.mark()
        self.trace.chat([{'role': 'user', 'content': 'second'}])
        refs = self.trace.refs_since(marker)
        self.assertEqual(len(refs), 1)
        refs[0]['request_hash'] = 'edited'
        self.assertNotEqual(self.trace.refs_since(marker)[0]['request_hash'], 'edited')
        for bad in (-1, 3, True, None):
            with self.assertRaises(t.TraceError):
                self.trace.refs_since(bad)

    def test_threads_have_isolated_trace_lists(self):
        barrier = threading.Barrier(2)
        results, lock = {}, threading.Lock()
        def worker(name):
            marker = self.trace.mark()
            barrier.wait()
            self.trace.chat([{'role': 'user', 'content': name}])
            with lock:
                results[name] = self.trace.refs_since(marker)
        threads = [threading.Thread(target=worker, args=(name,)) for name in ('one', 'two')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(set(results), {'one', 'two'})
        self.assertTrue(all(len(value) == 1 for value in results.values()))
        self.assertNotEqual(results['one'][0]['request_hash'], results['two'][0]['request_hash'])
        self.assertEqual(self.trace.refs_since(0), [])

    def test_namespace_mismatch_at_construction_and_after_mutation(self):
        self.provider.namespace = 'wrong'
        with self.assertRaises(t.TraceError):
            t.TraceProvider(self.provider)
        with self.assertRaises(t.TraceError):
            self.trace.chat([])
        self.assertEqual(self.trace.refs_since(0), [])
        self.assertEqual(self.provider.chat_calls, [])

    def test_embedding_batch_limits_and_invalid_later_text_preserve_order(self):
        for invalid in ([], (), ['x'] * 13):
            with self.assertRaises(original.ProviderStop):
                self.trace.embed(invalid)
        self.assertEqual(self.provider.embed_calls, [])
        with self.assertRaises(original.ProviderStop):
            self.trace.embed(['valid', ' '])
        self.assertEqual(self.provider.embed_calls, [['valid']])
        self.assertEqual(len(self.trace.refs_since(0)), 1)

    def test_tracer_does_not_construct_provider_or_open_credentials(self):
        with (
            mock.patch.object(original.Provider, '__init__', side_effect=AssertionError('no construction')),
            mock.patch.object(original, 'read_credentials', side_effect=AssertionError('no credential read')),
        ):
            trace = t.TraceProvider(self.provider)
            trace.chat([{'role': 'user', 'content': 'no credentials'}])
            trace.embed(['no credentials'])


if __name__ == '__main__':
    unittest.main()
