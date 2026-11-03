"""Synthetic fixtures only; no project images or network/provider access."""
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import local_content_inventory as content
import local_input_inventory as inv
import source_census as sc


def image_bytes(mode='RGB', fmt='PNG'):
    out = io.BytesIO()
    Image.new(mode, (3, 2)).save(out, format=fmt)
    return out.getvalue()


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.network = patch.object(socket, 'socket', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def setup_inventory(self, files):
        entries = []
        for name, body in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            entries.append({'path': name, 'kind': 'file', 'bytes': len(body)})
        raw = json.dumps({'entries': entries, 'status': 'path_census_complete_not_exposure_closure',
                          'research_file_bodies_opened': 0,
                          'grants_sampling_download_or_inference': False}).encode()
        census = self.repo / inv.CENSUS
        census.parent.mkdir(parents=True, exist_ok=True)
        census.write_bytes(raw)
        pin = patch.object(inv, 'CENSUS_SHA', sc.sha(raw))
        pin.start()
        self.addCleanup(pin.stop)
        return inv.load_projected(self.repo)

    def test_all_copies_and_labels_not_opened(self):
        raw = image_bytes()
        projected = self.setup_inventory({'reports/a.png': raw, '.tools/b.png': raw,
                                         'labels.csv': b'poison'})
        original = content._read
        with patch.object(content, '_read', wraps=original) as reader:
            got = content._load_at(self.repo, projected)
        self.assertEqual(got['counts']['images'], 2)
        self.assertEqual({call.args[1] for call in reader.call_args_list}, {'reports/a.png', '.tools/b.png'})
        self.assertEqual(got['rows_private'][0]['rgb_sha256'], hashlib.sha256(b'(3, 2)\0' + bytes(18)).hexdigest())
        self.assertTrue(all(r['asa_compatible'] for r in got['rows_private']))

    def test_alpha_is_registered_model_input_with_semantics_flag(self):
        got = content._fingerprint(image_bytes('RGBA'))
        self.assertTrue(got['asa_compatible'])
        self.assertEqual(got['asa_algorithm'], 'png-model-input-rgb-u32be-v2')
        self.assertTrue(got['nontrivial_render_semantics'])
        self.assertIsNotNone(got['rgb_sha256'])

    def test_jpeg(self):
        got = content._fingerprint(image_bytes(fmt='JPEG'))
        self.assertEqual(got['format'], 'JPEG')
        self.assertFalse(got['asa_compatible'])

    def test_animated_png_refuses_and_crc_is_checked(self):
        out = io.BytesIO()
        Image.new('RGB', (2, 2)).save(out, format='PNG', save_all=True,
            append_images=[Image.new('RGB', (2, 2), (1, 2, 3))])
        with self.assertRaisesRegex(ValueError, 'animated_image'):
            content._fingerprint(out.getvalue())
        corrupt = bytearray(image_bytes()); corrupt[29] ^= 1
        with self.assertRaises(ValueError):
            content._fingerprint(bytes(corrupt))

    def test_unknown_format(self):
        with self.assertRaisesRegex(ValueError, 'unsupported_image_format'):
            content._fingerprint(image_bytes(fmt='GIF'))

    def test_decode_failure(self):
        with self.assertRaisesRegex(ValueError, 'image_decode_failed'):
            content._fingerprint(b'broken')

    def test_size_and_pixel_bounds(self):
        projected = self.setup_inventory({'a.png': image_bytes()})
        with patch.object(content, 'MAX_BYTES', 1), self.assertRaisesRegex(ValueError, 'bounded_census_image'):
            content._load_at(self.repo, projected)
        with patch.object(content, 'MAX_PIXELS', 1), self.assertRaisesRegex(ValueError, 'pixel_bound'):
            content._fingerprint(image_bytes())

    def test_projection_poison(self):
        projected = self.setup_inventory({'a.png': image_bytes()})
        projected['image_paths'].append('labels.csv')
        with self.assertRaisesRegex(ValueError, 'authenticated_projection'):
            content._load_at(self.repo, projected)

    def test_duplicate_paths(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_census_path'):
            inv.project_paths({'entries': [{'path': 'a.png', 'kind': 'file', 'bytes': 2}] * 2})

    def test_symlink_leaf(self):
        projected = self.setup_inventory({'a.png': image_bytes()})
        path = self.repo / 'a.png'
        path.unlink()
        path.symlink_to('labels.csv')
        with self.assertRaises(OSError):
            content._load_at(self.repo, projected)

    def test_symlink_parent(self):
        projected = self.setup_inventory({'parent/a.png': image_bytes()})
        (self.repo / 'parent').rename(self.repo / 'hidden')
        (self.repo / 'parent').symlink_to('hidden')
        with self.assertRaises(OSError):
            content._load_at(self.repo, projected)

    def test_fifo(self):
        projected = self.setup_inventory({'a.png': image_bytes()})
        (self.repo / 'a.png').unlink()
        os.mkfifo(self.repo / 'a.png')
        with self.assertRaisesRegex(ValueError, 'regular_census_size'):
            content._load_at(self.repo, projected)

    def test_changed_size(self):
        projected = self.setup_inventory({'a.png': image_bytes()})
        (self.repo / 'a.png').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'regular_census_size'):
            content._load_at(self.repo, projected)

    def test_fresh_path_content_recapture(self):
        projected = self.setup_inventory({'a.png': image_bytes()})
        original = content._fingerprint
        def mutate(raw):
            result = original(raw)
            body = bytearray(raw)
            body[-1] ^= 1
            (self.repo / 'a.png').write_bytes(body)
            return result
        with patch.object(content, '_fingerprint', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'image_source_binding_changed'):
                content._load_at(self.repo, projected)

    def test_read_race(self):
        self.setup_inventory({'a.png': image_bytes()})
        with patch.object(sc, 'same_directory', return_value=False):
            with self.assertRaisesRegex(ValueError, 'image_changed_during_read'):
                content._read(self.repo, 'a.png', len(image_bytes()))

    def test_census_pin(self):
        projected = self.setup_inventory({'a.png': image_bytes()})
        with patch.object(inv, 'CENSUS_SHA', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'registered_path_census'):
                content._load_at(self.repo, projected)

    def test_public_fixed_repository(self):
        with patch.object(content, '_load_at', return_value={}) as load:
            content.load_local_content_inventory({'fixture': True})
        load.assert_called_once_with(sc.REPO, {'fixture': True})


if __name__ == '__main__':
    unittest.main()
