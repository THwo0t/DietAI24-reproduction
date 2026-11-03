"""Synthetic-only release tests. No real dataset image or target is read."""
from contextlib import ExitStack
from decimal import Decimal
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, PngImagePlugin

ROUND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND / 'src'))
import train_data as t


def png(index, annotation=None):
    stream = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if annotation is not None:
        info.add_text('synthetic', annotation)
    Image.new('RGB', (640, 480), (index, index + 20, index + 40)).save(stream, format='PNG', pnginfo=info)
    return stream.getvalue()


class Fixture:
    def __init__(self, parent, count=14, payloads=None, protected=None, incomplete=False, mass_exception=False):
        self.base = Path(parent) / 'repo/optimization_sol_20261102/mae_v2'
        self.base.mkdir(parents=True)
        self.repo = self.base.parents[1]
        self.count = count
        self.expected_exception_count = int(mass_exception)
        self.entries, self.receipts, ledger, rows = [], [], [], []
        originals, screening, recipes = {}, {}, {}
        self.freezes = {}
        for position, name in enumerate(sorted(t.FREEZE_NAMES)):
            raw = t.encoded({'synthetic_frozen_metadata': position})
            self.put(name, raw)
            self.freezes[name] = t.digest(raw)
        for name in t.SOURCE_NAMES:
            self.put(name, (t.V2 / name).read_bytes(), private=False)
        self.downloader_sha = t.digest((self.base / t.SOURCE_NAMES[2]).read_bytes())
        for index in range(count):
            dish = f'dish_{1000000000 + index}'
            group = 'round4-screening-' + t.digest(dish.encode())
            original = 'nutrition5k-v2-' + t.digest(dish.encode())
            ingredient = f'ingr_{1000000000 + index}'
            name = 'Synthetic food ' + str(index)
            grams = Decimal(100 + index)
            targets = [grams * 2, grams, grams * Decimal('.03'), grams * Decimal('.3'), grams * Decimal('.1')]
            if mass_exception and index == 6:
                targets[1] -= Decimal(2)
            # Raw header order energy, weight, fat, carbs, protein.
            fields = [dish, *map(str, targets), ingredient, name, str(grams),
                      str(targets[0]), str(targets[2]), str(targets[3]), str(targets[4])]
            rows.append((','.join(fields) + '\n').encode())
            recipe = t.digest(name.encode())
            raw = payloads[index] if payloads is not None else png(index + 1)
            destination = 'round4/data/incoming/' + t.digest((t.SEED + '|incoming|' + dish).encode()) + '/rgb.png'
            self.put(destination, raw)
            entry = {'dish_id': dish, 'screening_component_id': group, 'original_component_id': original,
                'recipe_sha256': recipe, 'source_url': f'{t.BASE_URL}/{dish}/rgb.png',
                'planned_destination': destination, 'cached_object_bytes': len(raw),
                'max_image_bytes': t.MAX_IMAGE_BYTES, 'in_archived_available_frame': False,
                'pixel_verification': 'pending_authorized_download'}
            self.entries.append(entry)
            self.receipts.append({'dish_id': dish, 'destination': destination, 'source_url': entry['source_url'],
                                  'bytes': len(raw), 'bytes_sha256': t.digest(raw), 'attempts_consumed': 1})
            ledger.extend([{'event': 'start', 'dish_id': dish, 'attempt': 1, 'reserved_bytes': len(raw) + 1},
                {'event': 'received', 'dish_id': dish, 'attempt': 1, 'bytes': len(raw)},
                {'event': 'ready', 'dish_id': dish, 'attempt': 1, 'bytes': len(raw), 'bytes_sha256': t.digest(raw)}])
            if not (incomplete and index == count - 1):
                ledger.append({'event': 'complete', 'dish_id': dish, 'attempt': 1})
            originals[dish], screening[dish], recipes[dish] = original, group, recipe
        # Unmatched poison cannot be UTF-8 or CSV decoded, much less parsed as targets.
        rows.insert(0, b'dish_1999999999,\xff,POISON,"unterminated\n')
        self.raw_bytes = b''.join(rows)
        raw_hashes = {}
        for position, name in enumerate(t.RAW_NAMES):
            raw = self.raw_bytes if position == 0 else b''
            self.put_repo(name, raw)
            raw_hashes[name] = t.digest(raw)
        fp = protected or {'bytes_sha256': 'a' * 64, 'rgb_sha256': 'b' * 64, 'bytes': 1}
        index = {'schema_version': 1, 'seed': t.SEED, 'blocked_screening_components': [],
            'known_image_fingerprints': [{'dish_id': 'dish_1999999999', **fp}],
            'original_components': originals, 'screening_components': screening,
            'recipe_sha256': recipes, 'source_sha256': raw_hashes}
        self.index_sha = t.digest(self.put(t.AUDIT_INDEX, t.encoded(index)))
        proposal = {'schema_version': 1, 'seed': t.SEED, 'status': 'awaiting_new_download_authorization',
            'actual_images_and_screening_groups': count, 'private_audit_index_sha256': self.index_sha,
            'original_frozen_hashes': self.freezes, 'entries': self.entries}
        self.proposal_sha = t.digest(self.put(t.PROPOSAL, t.encoded(proposal)))
        self.total_bytes = sum(entry['cached_object_bytes'] for entry in self.entries)
        summary = {'proposal_sha256': self.proposal_sha, 'selected_images': count,
                   'selected_groups': count, 'cached_download_byte_estimate': self.total_bytes}
        self.summary_sha = t.digest(self.put(t.PROPOSAL_SUMMARY, t.encoded(summary), private=False))
        auth = {'status': 'operator_asserted_authorization', 'operator_asserted_current_user_authorization': True,
            'proposal_sha256': self.proposal_sha, 'raw_rgb_summary_sha256': self.summary_sha,
            'downloader_sha256': self.downloader_sha, 'maximum_total_response_body_transfer_bytes': t.MAX_TRANSFER_BYTES,
            'maximum_attempts_per_file': t.MAX_ATTEMPTS, 'maximum_image_bytes': t.MAX_IMAGE_BYTES}
        auth_sha = t.digest(self.put(t.DOWNLOADS + '/authorization.json', t.encoded(auth)))
        receipt = {'schema_version': 1, 'proposal_sha256': self.proposal_sha,
            'raw_rgb_summary_sha256': self.summary_sha, 'training_release': False,
            'pixel_verification_performed': False, 'entries': self.receipts}
        receipt_sha = t.digest(self.put(t.DOWNLOADS + '/receipts.json', t.encoded(receipt)))
        ledger_raw = b''.join((json.dumps(event, sort_keys=True) + '\n').encode() for event in ledger)
        ledger_sha = t.digest(self.put(t.DOWNLOADS + '/attempts.jsonl', ledger_raw))
        done = {'status': 'incoming_bytes_complete_pending_blind_dedup', 'completed_files': count,
            'proposal_sha256': self.proposal_sha, 'raw_rgb_summary_sha256': self.summary_sha,
            'training_release': False, 'pixel_verification_performed': False,
            'receipts_sha256': receipt_sha, 'authorization_sha256': auth_sha, 'ledger_sha256': ledger_sha,
            'reserved_response_body_bytes': self.total_bytes + count, 'received_body_bytes_recorded': self.total_bytes,
            'attempts_consumed': count, 'cached_expected_payload_bytes': self.total_bytes,
            'maximum_total_response_body_transfer_bytes': t.MAX_TRANSFER_BYTES,
            'maximum_attempts_per_file': t.MAX_ATTEMPTS, 'maximum_image_bytes': t.MAX_IMAGE_BYTES}
        self.put(t.DOWNLOADS + '/download_summary.json', t.encoded(done))

    def put(self, name, raw, private=True):
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600 if private else 0o644)
        return raw

    def put_repo(self, name, raw):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def patch(self):
        stack = ExitStack()
        for key, value in {'PROPOSAL_SHA256': self.proposal_sha, 'SUMMARY_SHA256': self.summary_sha,
                           'INDEX_SHA256': self.index_sha, 'DOWNLOADER_SHA256': self.downloader_sha,
                           'FILE_COUNT': self.count, 'CACHED_BYTES': self.total_bytes,
                           'EXPECTED_EXCEPTION_COUNT': self.expected_exception_count}.items():
            stack.enter_context(mock.patch.object(t, key, value))
        return stack


class TrainReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROUND / 'tests')
        self.addCleanup(self.temporary.cleanup)

    def fixture(self, **kwargs):
        return Fixture(self.temporary.name, **kwargs)

    def test_complete_release_and_training_only_median(self):
        f = self.fixture()
        with f.patch():
            result = t.prepare(f.base)
            self.assertEqual((result['accepted_images'], result['accepted_groups']), (14, 14))
            fallback = t.decode((f.base / t.TRAIN / 'fallback.json').read_bytes())
            self.assertEqual(fallback['prediction']['weight'], 106.5)
            self.assertEqual(fallback['prediction']['energy'], 213.0)
            self.assertEqual(result['training_catalog_size'], 14)
            self.assertEqual(len(t.decode((f.base / t.TRAIN / 'labels.json').read_bytes())), 14)
            self.assertFalse(result['protected_images_or_labels_opened'])

    def test_completed_prepare_is_read_only(self):
        f = self.fixture()
        with f.patch():
            expected = t.prepare(f.base)
            before = {str(path.relative_to(f.base)): (path.read_bytes(), path.stat().st_mtime_ns)
                      for path in f.base.rglob('*') if path.is_file()}
            self.assertEqual(t.prepare(f.base), expected)
            after = {str(path.relative_to(f.base)): (path.read_bytes(), path.stat().st_mtime_ns)
                     for path in f.base.rglob('*') if path.is_file()}
            self.assertEqual(before, after)

    def test_candidate_collision_quarantines_every_endpoint(self):
        payloads = [png(i + 1) for i in range(14)]
        payloads[1] = payloads[0]
        f = self.fixture(payloads=payloads)
        with f.patch():
            result = t.prepare(f.base)
            self.assertEqual((result['accepted_images'], result['quarantined_images']), (12, 2))
            labels = t.decode((f.base / t.TRAIN / 'labels.json').read_bytes())
            self.assertNotIn('nutrition5k-' + f.entries[0]['dish_id'], labels)
            self.assertNotIn('nutrition5k-' + f.entries[1]['dish_id'], labels)
            fallback = t.decode((f.base / t.TRAIN / 'fallback.json').read_bytes())
            self.assertEqual(fallback['prediction']['weight'], 107.5)

    def test_same_rgb_different_encoded_bytes_also_quarantines_all(self):
        payloads = [png(i + 1) for i in range(14)]
        payloads[1] = png(1, 'different PNG metadata')
        self.assertNotEqual(t.digest(payloads[0]), t.digest(payloads[1]))
        f = self.fixture(payloads=payloads)
        with f.patch():
            self.assertEqual(t.prepare(f.base)['quarantined_images'], 2)

    def test_protected_rgb_match_quarantines_without_protected_image(self):
        raw = png(1, 'old protected encoding')
        fp = t.fingerprint_candidate(raw, {'bytes': len(raw), 'bytes_sha256': t.digest(raw)})
        f = self.fixture(protected=fp)
        with f.patch():
            result = t.prepare(f.base)
            self.assertEqual((result['accepted_images'], result['quarantined_images']), (13, 1))

    def test_less_than_12_groups_does_not_publish(self):
        f = self.fixture(count=11)
        with f.patch(), self.assertRaisesRegex(t.TrainDataError, 'fewer_than_12'):
            t.prepare(f.base)
        self.assertFalse((f.base / t.TRAIN).exists())

    def test_incomplete_ledger_blocks_before_image_decode(self):
        f = self.fixture(incomplete=True)
        with f.patch(), mock.patch.object(t, 'fingerprint_candidate', side_effect=AssertionError('must not decode')):
            with self.assertRaisesRegex(t.TrainDataError, 'all_downloads_must_complete'):
                t.prepare(f.base)
        self.assertFalse((f.base / t.TRAIN).exists())

    def test_missing_completion_blocks_before_image_decode(self):
        f = self.fixture()
        (f.base / t.DOWNLOADS / 'download_summary.json').unlink()
        with f.patch(), mock.patch.object(t, 'fingerprint_candidate', side_effect=AssertionError('must not decode')):
            with self.assertRaises(t.TrainDataError):
                t.prepare(f.base)

    def test_changed_original_freeze_blocks(self):
        f = self.fixture()
        f.put(next(iter(t.FREEZE_NAMES)), b'changed')
        with f.patch(), self.assertRaisesRegex(t.TrainDataError, 'input_hash_mismatch'):
            t.prepare(f.base)

    def test_changed_receipt_blocks_even_before_decode(self):
        f = self.fixture()
        f.put(t.DOWNLOADS + '/receipts.json', b'{}\n')
        with f.patch(), self.assertRaisesRegex(t.TrainDataError, 'input_hash_mismatch'):
            t.prepare(f.base)

    def test_changed_incoming_bytes_blocks(self):
        f = self.fixture()
        f.put(f.entries[0]['planned_destination'], png(200))
        with f.patch(), self.assertRaisesRegex(t.TrainDataError, 'candidate_bytes_mismatch'):
            t.prepare(f.base)

    def test_bad_image_contract_blocks_whole_release(self):
        payloads = [png(i + 1) for i in range(14)]
        payloads[0] = b'synthetic invalid image'
        f = self.fixture(payloads=payloads)
        with f.patch(), self.assertRaisesRegex(t.TrainDataError, 'candidate_image_decode_failed'):
            t.prepare(f.base)
        self.assertFalse((f.base / t.TRAIN).exists())

    def test_symlink_candidate_rejected(self):
        f = self.fixture()
        path = f.base / f.entries[0]['planned_destination']
        raw = path.read_bytes()
        path.unlink()
        target = f.base / 'synthetic.png'
        target.write_bytes(raw)
        path.symlink_to(target)
        with f.patch(), self.assertRaisesRegex(t.TrainDataError, 'symlink_rejected'):
            t.prepare(f.base)

    def test_training_artifact_tamper_rejected(self):
        f = self.fixture()
        with f.patch():
            t.prepare(f.base)
            f.put(t.TRAIN + '/fallback.json', b'{}\n')
            with self.assertRaisesRegex(t.TrainDataError, 'training_artifact_changed'):
                t.verify_train_only(f.base)

    def test_extra_training_file_rejected(self):
        f = self.fixture()
        with f.patch():
            t.prepare(f.base)
            f.put(t.TRAIN + '/extra.json', b'{}\n')
            with self.assertRaisesRegex(t.TrainDataError, 'training_inventory_changed'):
                t.verify_train_only(f.base)

    def test_forged_verify_input_cannot_open_protected_label(self):
        f = self.fixture()
        with f.patch():
            t.prepare(f.base)
            path = f.base / t.TRAIN / 'freeze.json'
            freeze = t.decode(path.read_bytes())
            forbidden = 'data/cohorts/sealed/validation_labels.json'
            freeze['binding']['inputs_sha256'][forbidden] = t.digest(b'POISON')
            path.write_bytes(t.encoded(freeze))
            original = t.read_bytes
            def guard(path, **kwargs):
                if str(path).endswith(forbidden):
                    self.fail('must reject inventory before opening protected labels')
                return original(path, **kwargs)
            with mock.patch.object(t, 'read_bytes', side_effect=guard):
                with self.assertRaisesRegex(t.TrainDataError, 'training_input_inventory_changed'):
                    t.verify_train_only(f.base)

    def test_metadata_hash_change_fails_without_release(self):
        f = self.fixture()
        path = f.repo / t.RAW_NAMES[0]
        path.write_bytes(path.read_bytes() + b'dish_1888888888,unmatched-extra\n')
        with f.patch(), self.assertRaisesRegex(t.TrainDataError, 'frozen_raw_metadata_changed'):
            t.prepare(f.base)
        self.assertFalse((f.base / t.TRAIN).exists())

    def test_quarantine_propagates_across_component(self):
        entries = [{'dish_id': 'a', 'screening_component_id': 'same'},
                   {'dish_id': 'b', 'screening_component_id': 'same'},
                   {'dish_id': 'c', 'screening_component_id': 'other'}]
        fps = [{'bytes_sha256': x, 'rgb_sha256': x} for x in ('1', '2', '3')]
        reasons = t.quarantine(entries, fps, {'bytes_sha256': {'1'}, 'rgb_sha256': set()})
        self.assertTrue(reasons['a'])
        self.assertEqual(reasons['b'], ['quarantined_screening_component'])
        self.assertFalse(reasons['c'])

    def test_matched_total_tolerance_accepts_exact_boundary(self):
        f = self.fixture()
        helpers = t.load_ingredient_helpers(f.base)
        entry = f.entries[0]
        rows = f.raw_bytes.splitlines(keepends=True)
        parts = rows[1].decode().rstrip('\n').split(',')
        parts[2] = '100.001'
        rows[1] = (','.join(parts) + '\n').encode()
        records, labels, _, residuals = t.extract_accepted(
            [('synthetic', io.BytesIO(b''.join(rows)))], {entry['dish_id']: entry}, helpers)
        self.assertEqual(len(records), 1)
        self.assertEqual(labels['nutrition5k-' + entry['dish_id']]['truth']['weight'], 100.001)
        self.assertEqual(Decimal(residuals['weight']), Decimal('.001'))

    def test_matched_total_tolerance_rejects_larger_residual(self):
        f = self.fixture()
        helpers = t.load_ingredient_helpers(f.base)
        entry = f.entries[0]
        rows = f.raw_bytes.splitlines(keepends=True)
        parts = rows[1].decode().rstrip('\n').split(',')
        parts[2] = '100.0011'
        rows[1] = (','.join(parts) + '\n').encode()
        with self.assertRaisesRegex(t.TrainDataError, 'ingredient_target_total_mismatch'):
            t.extract_accepted([('synthetic', io.BytesIO(b''.join(rows)))], {entry['dish_id']: entry}, helpers)

    def exception_fixture(self):
        f = self.fixture(mass_exception=True)
        raw = f.raw_bytes.splitlines(keepends=True)[7]
        policy = dict(t.TRAINING_DATA_EXCEPTION, raw_source_relative_path=t.RAW_NAMES[0],
                      raw_source_sha256=t.digest(f.raw_bytes), raw_record_sha256=t.digest(raw))
        return f, policy

    def test_exact_registered_mass_exception_preserves_original_values_and_binds_evidence(self):
        f, policy = self.exception_fixture()
        with f.patch(), mock.patch.object(t, 'TRAINING_DATA_EXCEPTION', policy):
            summary = t.prepare(f.base)
            self.assertEqual(summary['data_quality_exception_count'], 1)
            labels = t.decode((f.base / t.TRAIN / 'labels.json').read_bytes())
            ingredients = t.decode((f.base / t.TRAIN / 'ingredients.json').read_bytes())
            sid = 'nutrition5k-' + f.entries[6]['dish_id']
            self.assertEqual(labels[sid]['truth']['weight'], 104)
            row = next(row for row in ingredients['records'] if row['sample_id'] == sid)
            self.assertEqual(row['ingredients'][0]['grams'], 106)
            fallback = t.decode((f.base / t.TRAIN / 'fallback.json').read_bytes())
            self.assertEqual(fallback['prediction']['weight'], 106)
            audit = t.decode((f.base / t.TRAIN / 'audit.json').read_bytes())
            self.assertEqual(audit['data_quality_exceptions'], [t.exception_record()])
            self.assertEqual(audit['target_sum_max_abs_residual']['weight'], '2')
            freeze = t.decode((f.base / t.TRAIN / 'freeze.json').read_bytes())
            self.assertIn('round4/TRAINING_DATA_EXCEPTION.md', freeze['binding']['source_sha256'])
            self.assertEqual(freeze['binding']['policy']['data_quality_exception'], policy)
            self.assertEqual(t.verify_train_only(f.base), summary)

    def test_mass_exception_wrong_source_path_rejected(self):
        f, policy = self.exception_fixture()
        with mock.patch.object(t, 'TRAINING_DATA_EXCEPTION', policy):
            with self.assertRaisesRegex(t.TrainDataError, 'ingredient_target_total_mismatch'):
                t.extract_accepted([(t.RAW_NAMES[1], io.BytesIO(f.raw_bytes))],
                    {e['dish_id']: e for e in f.entries}, t.load_ingredient_helpers(f.base))

    def test_missing_expected_production_exception_blocks_release(self):
        f = self.fixture()
        with f.patch(), mock.patch.object(t, 'EXPECTED_EXCEPTION_COUNT', 1):
            with self.assertRaisesRegex(t.TrainDataError, 'registered_exception_expected_count_mismatch'):
                t.prepare(f.base)
        self.assertFalse((f.base / t.TRAIN).exists())

    def test_mass_exception_wrong_source_hash_rejected(self):
        f, policy = self.exception_fixture()
        with mock.patch.object(t, 'TRAINING_DATA_EXCEPTION', policy):
            with self.assertRaisesRegex(t.TrainDataError, 'registered_exception_source_hash_mismatch'):
                t.extract_accepted([(t.RAW_NAMES[0], io.BytesIO(f.raw_bytes + b'unmatched,extra\n'))],
                    {e['dish_id']: e for e in f.entries}, t.load_ingredient_helpers(f.base))

    def test_mass_exception_wrong_raw_record_hash_rejected(self):
        f, policy = self.exception_fixture()
        policy['raw_record_sha256'] = '0' * 64
        with mock.patch.object(t, 'TRAINING_DATA_EXCEPTION', policy):
            with self.assertRaisesRegex(t.TrainDataError, 'ingredient_target_total_mismatch'):
                t.extract_accepted([(t.RAW_NAMES[0], io.BytesIO(f.raw_bytes))],
                    {e['dish_id']: e for e in f.entries}, t.load_ingredient_helpers(f.base))

    def test_mass_exception_wrong_signed_delta_rejected_even_with_matching_hashes(self):
        f, policy = self.exception_fixture()
        lines = f.raw_bytes.splitlines(keepends=True)
        parts = lines[7].decode().rstrip('\n').split(',')
        parts[2] = '108'  # ingredient mass 106 -> signed difference -2, not +2.
        lines[7] = (','.join(parts) + '\n').encode()
        raw = b''.join(lines)
        policy.update(raw_source_sha256=t.digest(raw), raw_record_sha256=t.digest(lines[7]))
        with mock.patch.object(t, 'TRAINING_DATA_EXCEPTION', policy):
            with self.assertRaisesRegex(t.TrainDataError, 'ingredient_target_total_mismatch'):
                t.extract_accepted([(t.RAW_NAMES[0], io.BytesIO(raw))],
                    {e['dish_id']: e for e in f.entries}, t.load_ingredient_helpers(f.base))

    def test_mass_exception_never_waives_nutrient_mismatch(self):
        f, policy = self.exception_fixture()
        for position in (1, 3, 4, 5):
            with self.subTest(nutrient_field=position):
                lines = f.raw_bytes.splitlines(keepends=True)
                parts = lines[7].decode().rstrip('\n').split(',')
                parts[position] = str(Decimal(parts[position]) + Decimal('.0011'))
                lines[7] = (','.join(parts) + '\n').encode()
                raw = b''.join(lines)
                policy.update(raw_source_sha256=t.digest(raw), raw_record_sha256=t.digest(lines[7]))
                applied = []
                with mock.patch.object(t, 'TRAINING_DATA_EXCEPTION', policy):
                    with self.assertRaisesRegex(t.TrainDataError, 'ingredient_target_total_mismatch'):
                        t.extract_accepted([(t.RAW_NAMES[0], io.BytesIO(raw))],
                            {e['dish_id']: e for e in f.entries}, t.load_ingredient_helpers(f.base),
                            exception_audit=applied)
                self.assertEqual(applied, [])

    def test_matched_nonfinite_numeric_is_not_silent(self):
        f = self.fixture()
        helpers = t.load_ingredient_helpers(f.base)
        entry = f.entries[0]
        rows = f.raw_bytes.splitlines(keepends=True)
        parts = rows[1].decode().rstrip('\n').split(',')
        parts[2] = 'NaN'
        rows[1] = (','.join(parts) + '\n').encode()
        with self.assertRaisesRegex(t.TrainDataError, 'accepted_metadata_invalid'):
            t.extract_accepted([('synthetic', io.BytesIO(b''.join(rows)))], {entry['dish_id']: entry}, helpers)

    def test_catalog_density_conflict_is_hard_failure(self):
        f = self.fixture()
        helpers = t.load_ingredient_helpers(f.base)
        entries = {entry['dish_id']: entry for entry in f.entries}
        records, _, _, _ = t.extract_accepted([('synthetic', io.BytesIO(f.raw_bytes))], entries, helpers)
        records[1]['ingredients'][0] = dict(records[0]['ingredients'][0])
        records[1]['ingredients'][0]['nutrients'] = dict(records[0]['ingredients'][0]['nutrients'], energy=201)
        with self.assertRaisesRegex(t.TrainDataError, 'training_ingredient_density_conflict'):
            t.build_catalog(records, helpers)

    def test_no_publish_when_atomic_staging_write_fails(self):
        f = self.fixture()
        with f.patch(), mock.patch.object(t, 'write_private', side_effect=OSError('synthetic write failure')):
            with self.assertRaises(OSError):
                t.prepare(f.base)
        self.assertFalse((f.base / t.TRAIN).exists())
        self.assertFalse(list((f.base / 'round4/data').glob('.train-stage-*')))


if __name__ == '__main__':
    unittest.main()
