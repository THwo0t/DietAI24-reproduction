from pathlib import Path
from itertools import product
import sys
import tempfile
from copy import deepcopy
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'runtime/packages'),str(HERE)]
import run_diagnostic as run


class LabelGateTests(unittest.TestCase):
    def test_explicit_read_boundary_rejects_external_labels_credentials_and_images(self):
        from guarded_run import FileBoundary
        state = {'label_gate_passed':False,'development_label_opens':0,'forbidden_opens':0}
        labels = run.BASE/'data/cohorts/dev_labels.json'
        boundary = FileBoundary([labels],[],state)
        for path in ('/tmp/synthetic-validation-labels.json','/tmp/api_credentials.json',
                     run.BASE/'data/copied-labels.json',labels,'/tmp/synthetic.jpg'):
            with self.assertRaisesRegex(AssertionError,'forbidden_file'):
                boundary.check(path)
        self.assertEqual(state['forbidden_opens'],5)
        state['label_gate_passed'] = True
        boundary.check(labels)

    def test_external_rename_unlink_link_never_reach_underlying_mutation(self):
        from guarded_run import FileBoundary,mutation_wrapper,HERE
        from unittest.mock import Mock
        state = {'label_gate_passed':False,'development_label_opens':0,'forbidden_opens':0}
        boundary = FileBoundary([],[],state)
        for args in [('/tmp/copied-labels.json',),
                     (HERE/'diagnostics/inside.json','/tmp/outside.json'),
                     ('/tmp/outside.json',HERE/'diagnostics/inside.json')]:
            raw = Mock()
            with self.assertRaisesRegex(AssertionError,'forbidden_file'):
                mutation_wrapper(raw,boundary.check,len(args))(*args)
            raw.assert_not_called()

    def test_direct_runner_refuses_before_label_reader(self):
        with patch.object(Path,'exists',return_value=False), \
             patch.object(run,'load_completed_n',side_effect=AssertionError('labels_opened')):
            with self.assertRaisesRegex(ValueError,'use_guarded_network_isolated_entrypoint'):
                run.run()

    def test_external_interface_and_route_refused_without_traffic(self):
        from guarded_run import require_network_isolation
        self.assertEqual(require_network_isolation('lo: 0','Iface Destination\n','')['external_routes'],0)
        for dev,route,v6 in [('lo: 0\neth0: 0','Iface Destination\n',''),
                             ('lo: 0','Iface Destination\neth0 00000000',''),
                             ('lo: 0','Iface Destination\n','synthetic eth0')]:
            with self.assertRaisesRegex(AssertionError,'external_network'):
                require_network_isolation(dev,route,v6)

    def test_agreeing_score_copies_with_wrong_point_statistic_are_refused(self):
        actual = {'metrics':{'datasets':{'nutrition5k':{'primary':{'mae':1.0}}}},
                  'tolerance':{'failed_checks':0}}
        saved = deepcopy(actual)
        saved['metrics']['datasets']['nutrition5k']['bootstrap'] = {'replicates':10000}
        run.verify_point_statistics(actual,saved)
        saved['metrics']['datasets']['nutrition5k']['primary']['mae'] = 2.0
        # Both old copies could have the same wrong value; sealed predictions
        # are the independently recomputed authority used here.
        with self.assertRaisesRegex(ValueError,'do_not_reproduce_saved_point_statistics'):
            run.verify_point_statistics(actual,saved)

    def test_changed_native_dependency_changes_runtime_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'scipy'; root.mkdir()
            native = Path(temp)/'scipy.libs'; native.mkdir()
            (root/'module.py').write_text('pass\n')
            library = native/'libsynthetic.so.3'; library.write_bytes(b'original')
            before = run.runtime_members(root)
            library.write_bytes(b'changed')
            after = run.runtime_members(root)
            self.assertNotEqual(before,after)
            self.assertIn('native-libs/libsynthetic.so.3',after)

    def test_python_requirement_cannot_be_changed_with_new_freeze(self):
        with patch.object(run.sys,'version_info',(3,11,0)):
            with self.assertRaisesRegex(ValueError,'requires_Python_3_10'):
                run.runtime_manifest()

    def test_executed_gate_helper_mutation_invalidates_freeze_before_labels(self):
        with patch.object(run,'source_files',return_value={'round7/tools/diagnose_completed_m.py':'changed'}), \
             patch.object(run,'label_gate_passed',side_effect=AssertionError('early_label_hook')):
            with self.assertRaisesRegex(ValueError,'source_freeze_changed'):
                run.verify_source_freeze({'source_files':{'round7/tools/diagnose_completed_m.py':'original'}})

    def test_top_three_cover_bound_matches_bruteforce(self):
        for banks in ([['a'],['b'],['c'],['truth']],
                      [['a','b'],['b','c'],['c'],['truth']],
                      [['a'],['a','b'],['truth']],
                      [['truth'],['b'],['c'],['d']], [['a'],['b']]):
            brute = any('truth' in list(dict.fromkeys(choice))[:3] for choice in product(*banks))
            self.assertEqual(run.reachable_in_three(banks,'truth'),brute)

    def test_incomplete_batch_refuses_before_any_data_read(self):
        with patch.object(run,'require_scored',side_effect=ValueError('not_scored')), \
             patch.object(Path,'read_bytes',side_effect=AssertionError('early_data_open')):
            with self.assertRaisesRegex(ValueError,'not_scored'):
                run.load_completed_n()

    def test_wrong_freeze_refuses_before_manifest_or_labels(self):
        with patch.object(run,'require_scored'), \
             patch.object(Path,'read_bytes',return_value=b'{}') as opened, \
             patch.object(Path,'read_text',side_effect=AssertionError('early_manifest_open')):
            with self.assertRaisesRegex(ValueError,'frozen_N_changed'):
                run.load_completed_n()
        self.assertEqual(opened.call_count,1)

    def test_repeated_completed_run_does_not_reopen_labels_or_solve(self):
        with patch.object(Path,'exists',return_value=True), \
             patch.object(run,'load_completed_n',side_effect=AssertionError('labels_reopened')):
            with self.assertRaisesRegex(ValueError,'already_completed'):
                run.run()

    def test_ASA_conditional_oracle_keeps_fixed_membership(self):
        # A changed population must stop; it cannot select only easy matches.
        with self.assertRaisesRegex(ValueError,'fixed_ASA_Exact_population_required'):
            run.asa_bounds([],[],{'records':{}},{},{})


if __name__ == '__main__':
    unittest.main()
