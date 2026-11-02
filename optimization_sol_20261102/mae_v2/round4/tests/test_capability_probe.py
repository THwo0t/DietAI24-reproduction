"""Synthetic-only fixed probe, artifact seals and provider-construction gates."""
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image

V2 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(V2))
sys.path.insert(0, str(V2 / 'src'))
from round4.src import capability_probe as c
from round4.src.artifacts import ArtifactError, key_path
from round4.src.image_guard import ImageBindingError, payload_hash
from opt_provider import ProviderStop


VALID = '{"selected_ids":["c1","c3","c5","c7"]}'


class FakeProvider:
    def __init__(self, directory, *, allow_paid, namespace, responses=None, callback=None):
        assert allow_paid is True
        self.namespace = namespace
        self.cache = directory.parent / 'synthetic_cache'
        self.directory = directory
        self.responses = list(responses or [VALID])
        self.callback = callback
        self.messages = []
        self.closed = False

    def chat(self, messages, max_completion_tokens=4096):
        assert max_completion_tokens == 4096
        self.messages.append(deepcopy(messages))
        if self.callback:
            self.callback()
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def embed(self, texts):
        raise AssertionError('probe must never embed')

    def close(self):
        self.closed = True


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=V2 / 'round4/tests')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.providers = []
        self.make_train(14)

    def put(self, name, raw):
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)
        return c.sha(raw)

    def make_train(self, count):
        for name in c.SOURCE_NAMES:
            self.put(name, b'synthetic source binding')
        rows, artifacts = [], {}
        for index in range(count):
            stream = io.BytesIO()
            image = Image.new('RGB', (3, 2), (index, index + 20, index + 40))
            image.save(stream, 'PNG')
            raw = stream.getvalue()
            image_sha = c.sha(raw)
            name = c.TRAIN + '/images/' + image_sha + '.png'
            self.put(name, raw)
            artifacts['images/' + image_sha + '.png'] = image_sha
            rows.append({'sample_id': f'train-{index:03d}', 'group_id': f'group-{index}',
                'dataset': 'nutrition5k', 'split': 'train', 'image_path': name,
                'image_sha256': image_sha, 'rgb_sha256': c.sha(str(image.size).encode() + b'\0' + image.tobytes())})
        # Reverse physical order, so the fixed lexical rule is exercised.
        self.rows = rows
        raw = b''.join((json.dumps(row) + '\n').encode() for row in reversed(rows))
        artifacts['manifest.jsonl'] = self.put(c.TRAIN + '/manifest.jsonl', raw)
        for name in ('labels.json', 'ingredients.json', 'catalog.json', 'fallback.json'):
            artifacts[name] = self.put(c.TRAIN + '/' + name, b'POISON: labels must not be consumed')
        freeze = {'artifacts': artifacts, 'binding': {'synthetic': True}}
        freeze_sha = self.put(c.TRAIN + '/freeze.json', json.dumps(freeze).encode())
        self.proof = {'status': 'accepted_external_training_verified', 'accepted_images': count,
                      'accepted_groups': count, 'freeze_sha256': freeze_sha}

    def verify_train(self, base):
        self.assertEqual(base, self.base)
        return deepcopy(self.proof)

    def factory(self, directory, **kwargs):
        provider = FakeProvider(directory, **kwargs)
        self.providers.append(provider)
        return provider

    def run_probe(self, **kwargs):
        return c.probe(self.base, verify_train=self.verify_train,
                       provider_factory=self.factory, **kwargs)

    def test_default_is_read_only_offline_and_fixed_lexical_first13(self):
        result = self.run_probe()
        self.assertEqual(result['status'], 'offline_capability_preflight_pass')
        self.assertFalse(self.providers)
        self.assertFalse((self.base / c.RUN).exists())
        state = c._state(self.base, self.verify_train)
        self.assertEqual([row['sample_id'] for row in state['binding']['fixed_probe_images']],
                         [f'train-{index:03d}' for index in range(13)])
        self.assertEqual(state['query'], str(self.base / self.rows[0]['image_path']))
        expected = [payload_hash(c.encode_image(io.BytesIO(
            (self.base / row['image_path']).read_bytes()), 'native')) for row in self.rows[:13]]
        self.assertEqual(state['ordered_payload_hashes'], expected)
        self.assertEqual(state['binding']['image_payload_sha256'],
                         {row['image_sha256']: value for row, value in zip(self.rows, expected)})

    def test_cli_sets_private_umask_before_parsing_or_execution(self):
        events = []
        original_parse = c.argparse.ArgumentParser.parse_args
        def parsed(parser, *args, **kwargs):
            events.append('parse')
            return original_parse(parser, *args, **kwargs)
        def probed(**kwargs):
            events.append('probe')
            self.assertEqual(kwargs, {'allow_paid': False})
            return {'status': 'synthetic_offline'}
        with mock.patch.object(c.os, 'umask', side_effect=lambda value: events.append(('umask', value))), \
                mock.patch.object(c.argparse.ArgumentParser, 'parse_args', parsed), \
                mock.patch.object(c, 'probe', side_effect=probed), \
                mock.patch('builtins.print'):
            self.assertEqual(c.main([]), 0)
        self.assertEqual(events, [('umask', 0o077), 'parse', 'probe'])

    def test_reopened_image_change_is_blocked_before_provider_chat(self):
        original = c.vision.encode_image
        replacement = self.base / self.rows[13]['image_path']
        def changed(path, mode):
            return original(replacement if Path(path) == self.base / self.rows[0]['image_path'] else path, mode)
        with mock.patch.object(c.vision, 'encode_image', side_effect=changed):
            with self.assertRaisesRegex(ImageBindingError, 'sent_images_differ_from_frozen_stage'):
                self.run_probe(allow_paid=True)
        self.assertEqual(self.providers[0].messages, [])
        self.assertTrue(self.providers[0].closed)
        self.assertTrue((self.base / c.RUN / 'intent.json').is_file())
        self.assertFalse((self.base / c.RUN / 'completion.json').exists())

    def test_candidate_payload_swap_is_blocked_before_provider_chat(self):
        original = c.vision.encode_image
        first, second = [self.base / row['image_path'] for row in self.rows[1:3]]
        def swapped(path, mode):
            return original({first: second, second: first}.get(Path(path), path), mode)
        with mock.patch.object(c.vision, 'encode_image', side_effect=swapped):
            with self.assertRaises(ImageBindingError):
                self.run_probe(allow_paid=True)
        self.assertEqual(self.providers[0].messages, [])
        self.assertFalse((self.base / c.RUN / 'completion.json').exists())

    def test_success_seals_and_completed_is_read_only_without_provider(self):
        result = self.run_probe(allow_paid=True)
        self.assertEqual((result['status'], result['probe_images']), ('capability_passed', 13))
        provider = self.providers[0]
        self.assertTrue(provider.closed)
        self.assertEqual(provider.directory, self.base / c.PROVIDER_LOGS)
        self.assertEqual(len(provider.messages), 1)
        blocks = provider.messages[0][1]['content']
        self.assertEqual(sum(block['type'] == 'image_url' for block in blocks), 13)
        text_blocks = ' '.join(block.get('text', '') for block in blocks)
        self.assertNotIn('train-', text_blocks)
        self.assertNotIn('POISON', text_blocks)
        before = {str(path.relative_to(self.base)): (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.base.rglob('*') if path.is_file()}
        never = mock.Mock(side_effect=AssertionError('completed must not construct provider'))
        again = c.probe(self.base, allow_paid=True, provider_factory=never, verify_train=self.verify_train)
        self.assertFalse(again['provider_constructed'])
        self.assertEqual(again['completion_sha256'], result['completion_sha256'])
        after = {str(path.relative_to(self.base)): (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.base.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        never.assert_not_called()

    def test_single_format_repair_is_allowed_and_traced(self):
        def factory(directory, **kwargs):
            provider = FakeProvider(directory, responses=['bad format', VALID], **kwargs)
            self.providers.append(provider)
            return provider
        result = c.probe(self.base, allow_paid=True, provider_factory=factory, verify_train=self.verify_train)
        self.assertEqual(result['request_ref_count'], 2)
        self.assertEqual(len(self.providers[0].messages), 2)
        proof = c.verify_capability(self.base, verify_train=self.verify_train)
        self.assertTrue(proof['passed'])

    def test_two_contract_failures_are_sealed_and_cannot_reselect(self):
        def factory(directory, **kwargs):
            provider = FakeProvider(directory, responses=['bad', 'still bad'], **kwargs)
            self.providers.append(provider)
            return provider
        with self.assertRaisesRegex(c.CapabilityError, 'sealed_capability_contract_failure'):
            c.probe(self.base, allow_paid=True, provider_factory=factory, verify_train=self.verify_train)
        self.assertTrue((self.base / c.RUN / 'completion.json').is_file())
        self.assertEqual(len(self.providers[0].messages), 2)
        never = mock.Mock(side_effect=AssertionError('no new provider after sealed failure'))
        with self.assertRaisesRegex(c.CapabilityError, 'sealed_capability_contract_failure'):
            c.probe(self.base, allow_paid=True, provider_factory=never, verify_train=self.verify_train)
        never.assert_not_called()

    def test_provider_stop_propagates_without_completed_negative(self):
        stop = ProviderStop('synthetic transport detail must not enter completion')
        def factory(directory, **kwargs):
            provider = FakeProvider(directory, responses=[stop], **kwargs)
            self.providers.append(provider)
            return provider
        with self.assertRaises(ProviderStop) as raised:
            c.probe(self.base, allow_paid=True, provider_factory=factory, verify_train=self.verify_train)
        self.assertIs(raised.exception, stop)
        self.assertTrue(self.providers[0].closed)
        self.assertTrue((self.base / c.RUN / 'intent.json').is_file())
        self.assertFalse((self.base / c.RUN / 'completion.json').exists())
        self.assertFalse(list((self.base / c.RUN).rglob('result.json')))
        self.assertTrue(list((self.base / c.RUN).rglob('events.jsonl')))

    def test_only12_released_train_images_blocks_without_provider(self):
        self.make_train(12)
        with self.assertRaisesRegex(c.CapabilityError, 'at_least_13'):
            self.run_probe(allow_paid=True)
        self.assertFalse(self.providers)
        self.assertFalse((self.base / c.RUN).exists())

    def test_probe_does_not_open_training_reference_payloads(self):
        original = c.train_data.read_bytes
        forbidden = {self.base / c.TRAIN / name for name in ('labels.json', 'ingredients.json', 'catalog.json', 'fallback.json')}
        def guarded(path, **kwargs):
            self.assertNotIn(Path(path), forbidden)
            return original(path, **kwargs)
        with mock.patch.object(c.train_data, 'read_bytes', side_effect=guarded):
            self.run_probe(allow_paid=True)

    def test_source_change_during_call_prevents_sealing(self):
        def factory(directory, **kwargs):
            return FakeProvider(directory, callback=lambda: self.put(c.SOURCE_NAMES[0], b'changed'), **kwargs)
        with self.assertRaisesRegex(c.CapabilityError, 'capability_bound_source_or_input_changed'):
            c.probe(self.base, allow_paid=True, provider_factory=factory, verify_train=self.verify_train)
        self.assertFalse((self.base / c.RUN / 'completion.json').exists())

    def test_completed_record_tamper_rejected_before_any_provider(self):
        self.run_probe(allow_paid=True)
        record = self.base / c.RUN / 'records' / (key_path(c.RECORD) + '.json')
        record.write_bytes(b'{}\n')
        never = mock.Mock(side_effect=AssertionError('no provider'))
        with self.assertRaises(ArtifactError):
            c.probe(self.base, allow_paid=True, provider_factory=never, verify_train=self.verify_train)
        never.assert_not_called()

    def test_training_artifact_change_after_verifier_is_caught(self):
        def changed(base):
            path = self.base / c.TRAIN / 'manifest.jsonl'
            path.write_bytes(path.read_bytes() + b' ')
            return self.verify_train(base)
        with self.assertRaisesRegex(c.CapabilityError, 'capability_input_hash_changed'):
            c.probe(self.base, verify_train=changed)


if __name__ == '__main__':
    unittest.main()
