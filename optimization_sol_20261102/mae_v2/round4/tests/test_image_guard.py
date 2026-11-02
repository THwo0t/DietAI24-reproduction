import sys
from pathlib import Path
import unittest

V2 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(V2))
from round4.src.image_guard import ImageGuard, ImageBindingError, payload_hash, expected_images


class Fake:
    def __init__(self):
        self.calls = 0
    def chat(self, messages, max_completion_tokens=4096):
        self.calls += 1
        return 'ok'
    def embed(self, texts):
        self.calls += 1
        return ['vector']


class ImageGuardTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.guard = ImageGuard(self.fake)
        self.urls = ['data:image/png;base64,' + x for x in ('a', 'b', 'c')]
    def messages(self, urls):
        return [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': u}} for u in urls]}]

    def test_same_images_and_format_repair_preserve_exact_payload_order(self):
        messages = self.messages(self.urls)
        with self.guard.expect([payload_hash(u) for u in self.urls]):
            self.assertEqual(self.guard.chat(messages), 'ok')
            messages += [{'role': 'assistant', 'content': 'bad json'}, {'role': 'user', 'content': 'format repair'}]
            self.assertEqual(self.guard.chat(messages), 'ok')
        self.assertEqual(self.fake.calls, 2)

    def test_changed_reordered_missing_extra_images_never_reach_provider(self):
        for actual in (self.urls[::-1], self.urls[:2], self.urls + self.urls[:1],
                       ['data:image/png;base64,changed', *self.urls[1:]]):
            with self.guard.expect([payload_hash(u) for u in self.urls]):
                with self.assertRaises(ImageBindingError):
                    self.guard.chat(self.messages(actual))
        self.assertEqual(self.fake.calls, 0)

    def test_scope_and_embedding_boundaries_reset_after_exception(self):
        with self.assertRaises(ImageBindingError):
            self.guard.chat(self.messages(self.urls))
        with self.assertRaises(RuntimeError):
            with self.guard.expect([payload_hash(self.urls[0])]):
                raise RuntimeError('synthetic interruption')
        with self.guard.expect([]):
            self.assertEqual(self.guard.embed(['description']), ['vector'])
            with self.assertRaises(ImageBindingError):
                self.guard.chat(self.messages(self.urls))
        with self.guard.expect([payload_hash(self.urls[0])]):
            with self.assertRaises(ImageBindingError):
                self.guard.embed(['description'])

    def test_stage_order_description_rerank_and_estimate(self):
        hashes = {'q': 'query-payload', 'a': 'first', 'b': 'second'}
        query = {'image_sha256': 'q'}
        supports = [{'image_sha256': key} for key in ('a', 'b')]
        self.assertEqual(expected_images('x:description', {'image': query}, hashes), ['query-payload'])
        self.assertEqual(expected_images('x:rerank', {'query': query, 'candidates': supports}, hashes),
                         ['query-payload', 'first', 'second'])
        self.assertEqual(expected_images('x:estimate', {'query': query, 'supports': supports}, hashes),
                         ['first', 'second', 'query-payload'])
        self.assertEqual(expected_images('x:embedding', {}, hashes), [])
        with self.assertRaises(ImageBindingError):
            expected_images('x:description', {'image': {'image_sha256': 'unknown'}}, hashes)


if __name__ == '__main__':
    unittest.main()
