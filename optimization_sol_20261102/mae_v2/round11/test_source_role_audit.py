"""Synthetic orchestration boundaries; no real source opens."""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import source_role_audit as audit


class AuditTests(unittest.TestCase):
    def fixture(self, stack):
        repo = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        base = repo / audit.PREFIX.rstrip('/')
        dev = {'asa_rows': [], 'source_hashes': {}}
        held = {'schema_version': 1,
            'status': 'mechanical_source_inventory_captured_role_closure_pending',
            **{k: False for k in audit.FALSE_FLAGS}, **{k: 0 for k in audit.ZERO_FLAGS},
            'potential_input_coverage_complete': False,
            'original_linkage_guard_remains_stopped': True,
            'implementation_sha256': {'capture': 'pin'}, 'control_sha256': {'control': 'pin'},
            'n5_source_sha256': {'source': 'pin'}, 'development_identity': dev,
            'asa_mechanical_sources': {}, 'legacy_inputs_private': {},
            'local_content_private': {'rows_private': []}}
        roles = {'role_inventory_complete': False, 'source_association_complete': False,
                 'unresolved_sources': [], 'grants_sampling_download_or_inference': False}
        counts = {k: 0 for k in ('old_core_fold_bridge_components',
            'core_validation_intersection_components', 'merged_old_group_components',
            'unverified_original_image_bindings', 'local_attachment_count',
            'unmatched_local_potential_input_count')}
        reader = Mock()
        mocks = {}
        for module, name, value in (
            (audit, 'bounded_read', audit.encoded(held)),
            (audit, 'implementation_pins', {'entry': 'pin'}),
            (audit.inventory, 'implementation_pins', {'capture': 'pin'}),
            (audit, 'control_evidence', {'control': 'pin'}),
            (audit.n5_sources, 'load_identity_sources', ({'source_hashes': {'source': 'pin'}}, reader)),
            (audit.development_identity, '_load_development_identity', (dev, reader)),
            (audit.inventory, 'verify_asa_bindings', None),
            (audit.inventory, 'verify_legacy_bindings', None),
            (audit.asa_role_sources, '_load_at', roles),
            (audit.asa_phase_graph, 'build_phase_graph', ({}, counts))):
            mocks[name] = stack.enter_context(patch.object(module, name, return_value=value))
        return repo, base, held, mocks

    def run_fixture(self, repo, base, held):
        return audit._audit_at(repo, base, expected_sha=audit.sha(audit.encoded(held)))

    def test_success_is_still_unresolved_and_revalidated(self):
        with ExitStack() as stack:
            repo, base, held, mocks = self.fixture(stack)
            value, summary = self.run_fixture(repo, base, held)
            self.assertFalse(summary['caller_registration_complete'])
            self.assertFalse(value['role_inventory_complete'])
            self.assertGreaterEqual(mocks['verify_asa_bindings'].call_count, 4)
            self.assertNotIn('asa_role_sources_private', summary)

    def test_false_grant_and_identity_poison(self):
        for key in ('api_calls', 'grants_sampling_download_or_inference', 'development_identity'):
            with self.subTest(key=key), ExitStack() as stack:
                repo, base, held, mocks = self.fixture(stack)
                poisoned = deepcopy(held)
                poisoned[key] = {'poison': True} if key == 'development_identity' else 1
                mocks['bounded_read'].return_value = audit.encoded(poisoned)
                with self.assertRaises(ValueError): self.run_fixture(repo, base, poisoned)

    def test_control_source_implementation_and_receipt_drift(self):
        for name in ('control_evidence', 'load_identity_sources', 'implementation_pins', 'receipt'):
            with self.subTest(name=name), ExitStack() as stack:
                repo, base, held, mocks = self.fixture(stack)
                if name == 'receipt': mocks['bounded_read'].return_value = b'changed'
                elif name == 'load_identity_sources':
                    mocks[name].return_value = ({'source_hashes': {}}, Mock())
                else: mocks[name].return_value = {}
                with self.assertRaises(ValueError): self.run_fixture(repo, base, held)

    def test_stale_held_snapshot(self):
        with ExitStack() as stack:
            repo, base, held, mocks = self.fixture(stack)
            mocks['bounded_read'].side_effect = [audit.encoded(held), b'changed']
            with self.assertRaisesRegex(ValueError, 'held_inventory_changed'):
                self.run_fixture(repo, base, held)

    def test_unregistered_receipt_is_closed(self):
        with patch.object(audit, 'bounded_read', side_effect=AssertionError('must not open')):
            with self.assertRaisesRegex(ValueError, 'registered_inventory_receipt_required'):
                audit._audit_at(audit.REPO, audit.BASE, expected_sha=None)

    def test_cli_overrides_refused_before_access(self):
        with patch.object(audit.sys, 'argv', ['entry', '--root=/tmp']), \
             patch.object(audit, '_audit_at', side_effect=AssertionError('must not run')):
            with self.assertRaisesRegex(ValueError, 'cli_overrides_refused'): audit.main()

    def test_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve(); output = repo / audit.OUTPUT
            output.parent.mkdir(parents=True); output.write_text('prior')
            with patch.object(audit, 'REPO', repo), patch.object(audit.sys, 'argv', ['entry']), \
                 patch.object(audit, 'isolated_network', return_value=True), \
                 patch.object(audit, '_audit_at', side_effect=AssertionError('must not run')):
                with self.assertRaisesRegex(ValueError, 'fresh_role_audit_output_required'): audit.main()
            self.assertEqual(output.read_text(), 'prior')


if __name__ == '__main__': unittest.main()
