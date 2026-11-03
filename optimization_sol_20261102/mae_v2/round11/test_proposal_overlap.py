from collections import Counter
from copy import deepcopy
import csv
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import proposal_overlap as d
import source_census as c
import source_capture as s
import n5_sources
import test_source_capture as capture_fixtures


class ProposalOverlapTests(unittest.TestCase):
    def setUp(self):
        fixture = capture_fixtures.SourceCaptureTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.repo, self.base, self.data = fixture.repo, fixture.base, fixture.data
        p = deepcopy(fixture.n5.projection)
        self.ids = fixture.n5.ids
        val_pixel = next(row for row in p['index']['known_image_fingerprints'] if row['dish_id'] == self.ids['val'])
        p['train_entries'].append({'dish_id': self.ids['a']})
        p['train_pixels'].append({'dish_id': self.ids['a'], 'bytes_sha256': c.sha(b'synthetic-a'),
                                 'rgb_sha256': val_pixel['rgb_sha256']})
        self.p = p
        self.counts = {**fixture.n5.counts, 'training': 2}
        self.data.write_raw('available', b'ALL_DISH_TARGET_FIELDS_ARE_POISON\n')
        index = deepcopy(self.data.values['index'])
        index['source_sha256'][n5_sources.PATHS['available']] = self.data.hash('available')
        self.data.write('index', index)
        for slot in ('original_snapshot', 'final_snapshot'):
            value = deepcopy(self.data.values[slot]);value['source_sha256'] = index['source_sha256']
            self.data.write(slot, value)
        self.data.write('training_proposal', {'entries': p['train_entries']})
        self.audit = {'schema_version': 1, 'proposal_sha256': self.data.hash('training_proposal'),
            'private_audit_index_sha256': self.data.hash('index'), 'complete_candidate_count': 2,
            'candidate_audit': [{**row, 'screening_component_id': p['index']['screening_components'][row['dish_id']],
                'quarantine_reasons': [] if row['dish_id'] == self.ids['train'] else ['protected_rgb_sha256']}
                for row in p['train_pixels']], 'target_sum_max_abs_residual': {'weight': 'POISON_DO_NOT_EXPORT'}}
        self.freeze = {'schema_version': 1, 'status': 'accepted_external_training_frozen',
            'binding': {'proposal_sha256': self.audit['proposal_sha256'],
                        'private_audit_index_sha256': self.audit['private_audit_index_sha256']}}
        self.refusal = {'status': 'mechanical_identity_capture_stopped_for_blind_linkage_resolution',
                        'stop_code': 'validation_linkage_requires_separate_resolution',
                        'eligibility_or_inference_granted': False}
        path = self.base / d.REFUSAL;path.write_bytes(c.encoded(self.refusal))
        self.refusal_sha = c.sha(path.read_bytes())
        (self.base / 'round11/proposal_overlap.py').write_bytes(b'# SYNTHETIC implementation binding\n')
        self.persist()

    def persist(self):
        accepted = [row for row in self.audit['candidate_audit'] if not row['quarantine_reasons']]
        self.manifest = b''.join(c.encoded({'sample_id': 'nutrition5k-' + row['dish_id'],
            'dataset': 'nutrition5k', 'split': 'train', 'group_id': row['screening_component_id'],
            'original_component_id': self.p['index']['original_components'][row['dish_id']],
            'recipe_sha256': self.p['index']['recipe_sha256'][row['dish_id']],
            'image_path': 'round4/data/train/images/' + row['bytes_sha256'] + '.png',
            'image_sha256': row['bytes_sha256'], 'rgb_sha256': row['rgb_sha256']}).replace(b'\n', b'') + b'\n'
            for row in accepted)
        counts = {'accepted_images': len(accepted), 'accepted_groups': len({row['screening_component_id'] for row in accepted}),
                  'quarantined_images': len(self.audit['candidate_audit']) - len(accepted)}
        self.audit.update(counts)
        self.audit['quarantine_reason_counts_overlapping'] = dict(Counter(
            reason for row in self.audit['candidate_audit'] for reason in row['quarantine_reasons']))
        self.freeze.update(counts)
        path = self.base / d.MANIFEST;path.write_bytes(self.manifest)
        self.data.write('training_audit', self.audit)
        self.freeze['artifacts'] = {'audit.json': self.data.hash('training_audit'),
            'manifest.jsonl': c.sha(self.manifest), 'labels.json': 'f' * 64, 'images/protected.png': 'e' * 64}
        self.data.write('training_freeze', self.freeze)
        self.anchors = {slot: self.data.hash(slot) for slot in n5_sources.ANCHORS}

    def run_diagnostic(self):
        return d._diagnose_at(self.repo, self.base, controls=self.fixture.controls.pins,
            refusal_sha=self.refusal_sha, n5_anchors=self.anchors, expected_counts=self.counts)

    def test_preexisting_rejected_proposal_overlap_is_distinct_from_accepted_input(self):
        value = self.run_diagnostic();summary = value['summary']
        self.assertEqual(summary['overlap_class_counts'], {'preexisting_rejected_proposal_overlap': 1})
        self.assertEqual(summary['validation_component_intersections']['accepted_training'], 0)
        self.assertEqual(summary['validation_component_intersections']['proposed_training'], 1)
        self.assertTrue(summary['original_linkage_guard_remains_stopped'])
        self.assertFalse(summary['grants_eligibility_download_or_inference'])
        self.assertFalse(summary['actual_API_exposure_proven'])
        self.assertNotIn('POISON', json.dumps(value))
        self.assertFalse(any(dish in json.dumps(summary) for dish in self.ids.values()))

    def test_accepted_training_overlap_remains_a_critical_unresolved_source_issue(self):
        self.audit['candidate_audit'][1]['quarantine_reasons'] = []
        self.persist()
        summary = self.run_diagnostic()['summary']
        self.assertEqual(summary['overlap_class_counts'], {'accepted_training_overlap_requires_resolution': 1})
        self.assertEqual(summary['validation_component_intersections']['accepted_training'], 1)
        self.assertTrue(summary['original_linkage_guard_remains_stopped'])

    def test_reader_opens_only_fixed_metadata_not_any_inventory_image_or_label(self):
        allowed = {self.repo / relative for relative in n5_sources.PATHS.values()}
        allowed |= {self.base / relative for relative in self.fixture.controls.blobs}
        allowed |= {self.base / relative for relative in s.IMPLEMENTATION_FILES}
        allowed |= {self.base / name for name in (d.MANIFEST, d.REFUSAL, 'round11/proposal_overlap.py')}
        original = os.open
        def observe(path, flags, *args, **kwargs):
            if not flags & os.O_DIRECTORY:
                parent = Path('/proc/self/fd/' + str(kwargs['dir_fd'])).resolve() if 'dir_fd' in kwargs else None
                self.assertIn(parent / Path(path) if parent is not None else Path(path), allowed)
            return original(path, flags, *args, **kwargs)
        with patch.object(c.os, 'open', side_effect=observe), \
                patch.object(s.asa_archive, 'capture_archive', side_effect=AssertionError('no image archive')):
            self.assertEqual(self.run_diagnostic()['summary']['protected_dish_targets_interpreted'], 0)

    def test_stale_refusal_or_manifest_is_not_accepted(self):
        path = self.base / d.MANIFEST;before = path.read_bytes();path.write_bytes(before + b' ')
        with self.assertRaisesRegex(ValueError, 'accepted_identity_manifest_hash_changed'):
            self.run_diagnostic()
        path.write_bytes(before)
        (self.base / d.REFUSAL).write_bytes(c.encoded(self.refusal) + b' ')
        with self.assertRaisesRegex(ValueError, 'registered_capture_refusal_required'):
            self.run_diagnostic()

    def test_audit_manifest_disagreement_or_unknown_reason_refuses(self):
        self.audit['candidate_audit'][1]['quarantine_reasons'] = []
        self.data.write('training_audit', self.audit)
        self.freeze['artifacts']['audit.json'] = self.data.hash('training_audit')
        self.data.write('training_freeze', self.freeze)
        self.anchors['training_freeze'] = self.data.hash('training_freeze')
        with self.assertRaisesRegex(ValueError, 'accepted_manifest_not_exact_audit_acceptance'):
            self.run_diagnostic()
        self.audit['candidate_audit'][1]['quarantine_reasons'] = ['unregistered_reason']
        self.persist()
        with self.assertRaisesRegex(ValueError, 'registered_prior_quarantine_reasons_required'):
            self.run_diagnostic()

    def test_source_drift_after_analysis_refuses_output(self):
        original = d.analyse
        def mutate(*args, **kwargs):
            value = original(*args, **kwargs)
            self.data.path('available').write_bytes(b'SYNTHETIC drift')
            return value
        with patch.object(d, 'analyse', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'hash_changed'):
                self.run_diagnostic()

    def test_cli_is_private_aggregate_only_and_has_no_override(self):
        original = d._diagnose_at
        def fixture(repo, base):
            return original(repo, base, controls=self.fixture.controls.pins,
                refusal_sha=self.refusal_sha, n5_anchors=self.anchors, expected_counts=self.counts)
        with patch.object(d, 'REPO', self.repo), patch.object(d, 'BASE', self.base), \
                patch.object(d, '_diagnose_at', side_effect=fixture) as called, \
                patch.object(d.sys, 'argv', ['proposal_overlap.py']), patch('builtins.print') as printed:
            d.main()
            with self.assertRaisesRegex(ValueError, 'fresh_overlap_output_required'):
                d.main()
        self.assertEqual(called.call_count, 1)
        output = self.repo / d.OUTPUT
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)
        summary = json.loads(printed.call_args.args[0])
        self.assertFalse(any(dish in json.dumps(summary) for dish in self.ids.values()))
        self.assertFalse(summary['grants_eligibility_download_or_inference'])
        with patch.object(d.sys, 'argv', ['proposal_overlap.py', '--root', '/tmp']):
            with self.assertRaisesRegex(ValueError, 'overlap_cli_overrides_refused'):
                d.main()

    def test_recipe_bridge_reports_screening_ambiguity_even_if_validation_raw_is_unambiguous(self):
        p = deepcopy(self.p)
        rows = list(csv.reader(io.StringIO(p['raw_tables']['cafe1'].decode())))
        def dish_row(dish, ingredients):
            result = [dish] + ['NEVER_PARSE_DISH_TARGETS'] * 5
            for identifier, name, mass in ingredients:
                result += [identifier, name, str(mass), '1', '1', '1', '1']
            return result
        names = ('synthetic-val-left', 'synthetic-val-right')
        rows = [row if row[0] != self.ids['val'] else dish_row(self.ids['val'], [
            ('ingr_0000000090', names[0], 4), ('ingr_0000000091', names[1], 9)]) for row in rows]
        rows += [dish_row('dish_1000000100', [('ingr_0000000100', names[0], 10),
                                            ('ingr_0000000101', names[1], 10)]),
                 dish_row('dish_1000000101', [('ingr_0000000100', 'different-left', 10),
                                            ('ingr_0000000101', 'different-right', 9)])]
        stream = io.StringIO();csv.writer(stream).writerows(rows)
        p['raw_tables']['cafe1'] = stream.getvalue().encode()
        scans = d.raw_scans(p['raw_tables'])
        old, ambiguous, _, members = d.build_components(scans, p['index']['known_image_fingerprints'])
        p['index']['original_components'] = old
        p['index']['recipe_sha256'] = {dish: scan.recipe_hash for dish, scan in scans.items()}
        p['index']['screening_components'] = d.screening_closure(old, p['index']['recipe_sha256'],
                                                               p['index']['known_image_fingerprints'])
        p['snapshot']['ambiguous_component_ids'] = list(ambiguous)
        p['snapshot']['component_members'] = members
        p['source_hashes'] = {'training_proposal': self.audit['proposal_sha256'],
                              'index': self.audit['private_audit_index_sha256']}
        summary = d.analyse(p, self.audit, self.freeze, self.manifest, expected_counts=self.counts)['summary']
        self.assertEqual(summary['validation_ambiguous_raw_components'], 0)
        self.assertEqual(summary.get('validation_ambiguous_screening_components'), 1)
        self.assertTrue(summary['original_linkage_guard_remains_stopped'])
        from n5_identity import reconcile
        with self.assertRaisesRegex(ValueError, 'validation_linkage_requires_separate_resolution'):
            reconcile(scans, p['index'], p['snapshot'], p['cohort_proposal'], p['registry'],
                p['train_entries'], p['train_pixels'], expected_counts=self.counts)


if __name__ == '__main__':
    unittest.main()
