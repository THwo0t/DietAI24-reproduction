"""Synthetic negative-path tests; never read the real sealed cohort."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import cohorts_v2 as c


def scan(time, masses, cafe='cafe1'):
    return c.make_scan('dish_' + str(1500000000 + time), cafe,
                       [('ingr_' + str(k).zfill(10), v) for k, v in masses.items()])


def build(*records, fingerprints=()):
    return c.build_components({row.dish_id: row for row in records}, fingerprints)


def fp(row, raw, rgb):
    return {'dish_id': row.dish_id, 'bytes_sha256': raw, 'rgb_sha256': rgb}


class LinkageTests(unittest.TestCase):
    def same(self, mapping, a, b):
        self.assertEqual(mapping[a.dish_id], mapping[b.dish_id])

    def different(self, mapping, a, b):
        self.assertNotEqual(mapping[a.dish_id], mapping[b.dish_id])

    def test_known_development_increment_shape(self):
        a = scan(29, {1: 133, 2: 102, 3: 76, 4: 73, 5: 69})
        b = scan(96, {1: 133, 2: 102, 3: 76, 4: 73, 5: 69, 6: 69, 7: 66})
        mapping, quarantine, counts, _ = build(a, b)
        self.same(mapping, a, b)
        self.assertFalse(quarantine)
        self.assertEqual(counts['exact_increment'], 1)

    def test_time_boundary_600_inclusive_601_excluded(self):
        a = scan(0, {1: 100, 2: 60})
        b = scan(600, {1: 100, 2: 60, 3: 20})
        d = scan(601, {1: 100, 2: 60, 4: 20})
        self.same(build(a, b)[0], a, b)
        self.different(build(a, d)[0], a, d)

    def test_complete_vector_decimal_equality_across_days(self):
        a = scan(0, {1: '120.0'})
        b = scan(86400, {1: '120.00'})
        mapping, _, counts, _ = build(a, b)
        self.same(mapping, a, b)
        self.assertEqual(counts['same_complete_mass_vector'], 1)

    def test_next_day_120_to_150_is_not_linked_or_quarantined(self):
        a = scan(0, {1: 120})
        b = scan(86400, {1: 150})
        mapping, quarantine, _, _ = build(a, b)
        self.different(mapping, a, b)
        self.assertFalse(quarantine)

    def test_single_ingredient_increment_is_not_a_link(self):
        a = scan(0, {1: 120})
        b = scan(60, {1: 120, 2: 50})
        mapping, quarantine, _, _ = build(a, b)
        self.different(mapping, a, b)
        self.assertFalse(quarantine)

    def test_same_recipe_with_different_masses_is_not_global_edge(self):
        a = scan(0, {1: 120, 2: 50})
        b = scan(10000, {1: 160, 2: 50})
        self.different(build(a, b)[0], a, b)

    def test_cafe_boundaries(self):
        a = scan(0, {1: 120, 2: 50}, 'a')
        b = scan(60, {1: 120, 2: 50, 3: 1}, 'b')
        self.different(build(a, b)[0], a, b)

    def test_exact_extension_can_cross_an_unrelated_intermediate_capture(self):
        a = scan(0, {1: 100, 2: 50})
        bridge = scan(30, {9: 99})
        b = scan(60, {1: 100, 2: 50, 3: 20})
        mapping, _, _, _ = build(a, bridge, b)
        self.same(mapping, a, b)
        self.different(mapping, a, bridge)

    def test_full_raw_adjacency_not_candidate_filtered_adjacency(self):
        a = scan(0, {1: 100, 2: 50})
        unrelated = scan(30, {9: 99})
        b = scan(60, {1: 110, 2: 50})
        self.different(build(a, unrelated, b)[0], a, b)
        self.same(build(a, b)[0], a, b)

    def test_adjacent_increment_requires_two_shared_and_one_exact_anchor(self):
        a = scan(0, {1: 100, 2: 50})
        b = scan(60, {1: 110, 2: 50})
        self.same(build(a, b)[0], a, b)
        no_anchor = scan(60, {1: 110, 2: 51})
        mapping, quarantine, _, _ = build(a, no_anchor)
        self.different(mapping, a, no_anchor)
        self.assertFalse(quarantine)

    def test_decrease_and_disappearance_quarantine_entire_later_closed_components(self):
        a = scan(0, {1: 100, 2: 50, 3: 20})
        b = scan(60, {1: 90, 2: 50, 3: 20})
        duplicate_a = scan(10000, {1: 100, 2: 50, 3: 20})
        mapping, quarantine, _, _ = build(a, b, duplicate_a)
        self.assertEqual(quarantine, {mapping[a.dish_id], mapping[b.dish_id]})
        self.assertIn(mapping[duplicate_a.dish_id], quarantine)
        disappeared = scan(60, {1: 100, 2: 50})
        mapping, quarantine, _, _ = build(a, disappeared)
        self.assertEqual(len(quarantine), 2)

    def test_decrease_without_anchor_not_blanket_quarantined(self):
        a = scan(0, {1: 100, 2: 50})
        b = scan(60, {1: 90, 2: 40})
        self.assertFalse(build(a, b)[1])

    def test_all_raw_nodes_bridge_before_exposure_exclusions(self):
        historical = scan(0, {1: 100, 2: 50})
        absent_from_rgb_frame = scan(500, {1: 100, 2: 50, 3: 20})
        candidate = scan(1000, {1: 100, 2: 50, 3: 20, 4: 30})
        mapping, _, _, _ = build(historical, absent_from_rgb_frame, candidate)
        self.same(mapping, historical, candidate)
        self.different(build(historical, candidate)[0], historical, candidate)

    def test_exact_pixel_or_byte_duplicates_link_across_cafes(self):
        a = scan(0, {1: 100}, 'a')
        b = scan(9999, {2: 70}, 'b')
        for fingerprints in ([fp(a, 'a', 'same'), fp(b, 'b', 'same')],
                             [fp(a, 'same', 'a'), fp(b, 'same', 'b')]):
            self.same(build(a, b, fingerprints=fingerprints)[0], a, b)

    def test_zero_mass_is_not_an_anchor_and_duplicate_ids_are_summed(self):
        a = c.make_scan('dish_1500000000', 'cafe1', [
            ('ingr_0000000001', '30.1'), ('ingr_0000000001', '20.2'), ('ingr_0000000002', '0')])
        self.assertEqual(dict(a.masses), {'ingr_0000000001': c.Decimal('50.3')})

    def test_invalid_numeric_mass_is_rejected_without_echoing_value(self):
        for value in ('NaN', 'Infinity', '-0.01', 'PRIVATE_SENTINEL'):
            with self.assertRaisesRegex(c.AuditError, '^invalid_mass$'):
                scan(0, {1: value})

    def test_component_ids_are_order_independent(self):
        a = scan(0, {1: 100, 2: 50})
        b = scan(60, {1: 100, 2: 50, 3: 1})
        self.assertEqual(build(a, b), build(b, a))


class SelectionTests(unittest.TestCase):
    def test_round_robin_prefers_new_groups_before_existing(self):
        mapping = {'kept': 'a', 'old-group': 'a', 'b1': 'b', 'b2': 'b', 'c1': 'c'}
        selected = c.select_round_robin(['kept'], list(mapping), mapping, target=3)
        self.assertEqual({mapping[dish] for dish in selected}, {'a', 'b', 'c'})

    def test_round_robin_same_input_order_independent(self):
        mapping = {str(i): str(i % 3) for i in range(9)}
        self.assertEqual(c.select_round_robin([], list(mapping), mapping, target=7),
                         c.select_round_robin([], list(reversed(mapping)), mapping, target=7))

    def test_insufficient_images_fail_instead_of_relaxing_grouping(self):
        with self.assertRaisesRegex(c.AuditError, 'fewer_than_200'):
            c.select_round_robin([], ['a'], {'a': 'g'}, target=2)

    def test_folds_grouped_deterministic_balanced(self):
        groups = [str(i) for i in range(12)]
        folds = c.five_folds(groups)
        self.assertEqual(folds, c.five_folds(groups[::-1] + groups))
        self.assertEqual(set(folds.values()), set(range(5)))
        self.assertLessEqual(max(c.Counter(folds.values()).values()) - min(c.Counter(folds.values()).values()), 1)
        with self.assertRaisesRegex(c.AuditError, 'fewer_than_five'):
            c.five_folds(['one'] * 100)


class ImageAndFreezeTests(unittest.TestCase):
    def test_reencoded_png_exact_pixel_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'a.png', Path(tmp) / 'b.png'
            image = Image.new('RGB', (16, 12), (44, 71, 22))
            image.save(a, compress_level=0)
            image.save(b, compress_level=9)
            fa, fb = c.image_fingerprint(a, 'a'), c.image_fingerprint(b, 'b')
            self.assertNotEqual(fa['bytes_sha256'], fb['bytes_sha256'])
            self.assertEqual(fa['rgb_sha256'], fb['rgb_sha256'])

    def test_private_immutable_and_path_traversal_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            c.frozen_write(tmp, 'sealed/a', b'private', private=True)
            c.frozen_write(tmp, 'sealed/a', b'private', private=True)
            self.assertEqual((Path(tmp) / 'sealed/a').stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(c.AuditError, 'immutable_artifact_conflict'):
                c.frozen_write(tmp, 'sealed/a', b'changed', private=True)
            with self.assertRaisesRegex(c.AuditError, 'unsafe_relative_path'):
                c.frozen_write(tmp, '../outside', b'x')

    def make_dev(self, base):
        rows, labels, files = [], {}, {}
        for dataset in ('asa24', 'nutrition5k'):
            for i in range(5):
                sample = dataset + '-' + str(i)
                image = 'data/' + dataset + '/dev/images/' + c.digest(sample.encode()) + '.png'
                blob = sample.encode()
                c.frozen_write(base, image, blob)
                files[image] = c.digest(blob)
                rows.append({'sample_id': sample, 'dataset': dataset, 'split': 'dev',
                    'fold': i, 'group_id': sample, 'image_path': image, 'image_sha256': c.digest(blob)})
                labels[sample] = {'truth': dict.fromkeys(c.TARGETS, 1)}
        for path, blob in {'data/cohorts/dev.jsonl': c._line_payload(rows),
                           'data/cohorts/dev_labels.json': c.json_bytes(labels)}.items():
            c.frozen_write(base, path, blob)
            files[path] = c.digest(blob)
        seal = {'seed': c.SEED, 'rules_sha256': c.digest(c.json_bytes(c.RULES)),
                'artifacts': files, 'counts': {'synthetic': True}}
        c.frozen_write(base, 'data/cohorts/dev_freeze.json', c.json_bytes(seal), private=True)
        return seal

    def test_verify_and_load_dev_never_read_sealed_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_dev(tmp)
            sealed = Path(tmp) / 'data/cohorts/sealed/validation_labels.json'
            sealed.parent.mkdir()
            sealed.write_text('DO_NOT_READ_VALIDATION_SENTINEL')
            original_open = Path.open
            opened = []

            def guard(path, *args, **kwargs):
                opened.append(str(path))
                if 'validation' in str(path) or '/sealed/' in str(path):
                    raise AssertionError('sealed access')
                return original_open(path, *args, **kwargs)

            with patch.object(Path, 'open', guard):
                self.assertTrue(c.verify_dev_only(tmp)['verified'])
                self.assertEqual(len(c.load_dev(tmp)[0]), 10)
            self.assertFalse(any('validation' in path for path in opened))

    def test_untrusted_dev_seal_cannot_smuggle_validation_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            seal = self.make_dev(tmp)
            seal['artifacts']['data/cohorts/sealed/validation_labels.json'] = 'anything'
            (Path(tmp) / 'data/cohorts/dev_freeze.json').write_bytes(c.json_bytes(seal))
            with self.assertRaisesRegex(c.AuditError, 'development_seal_has_forbidden_path'):
                c.verify_dev_only(tmp)

    def test_modified_development_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_dev(tmp)
            (Path(tmp) / 'data/cohorts/dev_labels.json').write_text('{}')
            with self.assertRaisesRegex(c.AuditError, 'development_hash_mismatch'):
                c.verify_dev_only(tmp)

    def test_cli_unexpected_error_is_sanitized(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['cohorts_v2.py']), \
             patch.object(c, 'prepare', side_effect=ValueError('PRIVATE_LABEL_SENTINEL')), \
             contextlib.redirect_stdout(output):
            self.assertEqual(c.main(), 2)
        self.assertNotIn('PRIVATE_LABEL_SENTINEL', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['error_code'], 'unexpected_ValueError')


if __name__ == '__main__':
    unittest.main()
