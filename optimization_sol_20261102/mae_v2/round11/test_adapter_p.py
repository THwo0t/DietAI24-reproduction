"""Synthetic isolated post-seal code-only projection and negative paths."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE/name) for name in ('round11','round10','src','round7/src','round8/src')]+[str(BASE)]
import test_identity_gate_p as fixtures
from adapter_p import _prepare,prepare,code_only,contexts_after_seal,_isolation_check,CLEAN_ENV,main
from opt_provider import sha,fingerprint
from round4.src.artifacts import ArtifactStore


class CodeBranch(dict):
    def __getitem__(self,key):
        if key!='food_code':raise AssertionError('forbidden label branch accessed')
        return super().__getitem__(key)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.SnapshotTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.snapshot=self.f.snapshot();self.root=self.f.f.root
        self.labels=self.root/'round11/prepared/cohort/dev_labels.json'
        self.ctx=self.f.f.ctx
        binding=self.ctx.binding
        self.completion=self.f.store.directory/'completion.json'
        adapter_binding={'science':binding,'coding_completion_sha256':sha(self.completion),
            'labels_sha256':sha(self.labels),'role':'post_coding_ASA_code_and_full_catalogue_only'}
        self.store=ArtifactStore(self.root/'adapter',adapter_binding,['contexts','provenance'],
                                 verify_sources=lambda:True,root=self.root)

    def project(self,snapshot=None,path=None):
        return _prepare(self.ctx,self.snapshot if snapshot is None else snapshot,
                        self.labels if path is None else path,self.store,
                        coding_completion_path=self.completion,data_root=self.root)

    def test_projection_contains_only_code_and_complete_options_same_seal(self):
        result=self.project();self.assertEqual(result['Exact_contexts'],1)
        values=self.store.verify_completed()
        self.assertEqual(values['contexts'],{'a':{'code':'12345678','options':self.ctx.catalog['asa_options']['12345678']}})
        self.assertEqual(values['provenance']['coding_completion_sha256'],sha(self.completion))
        self.assertNotIn('POISON',json.dumps(values))
        self.assertEqual(self.project(),result)

    def test_only_reference_code_branch_is_accessed_and_n5_not_projected(self):
        rows=[{'sample_id':'a','dataset':'asa24'},{'sample_id':'n','dataset':'nutrition5k'}]
        labels={'a':CodeBranch(food_code='12345678',size='POISON'),'n':object()}
        self.assertEqual(code_only(labels,rows),{'a':'12345678'})
        with self.assertRaises(ValueError):code_only({'a':labels['a']},rows)

    def test_incomplete_snapshot_or_drift_refuses_before_label_open(self):
        self.labels.unlink()
        with self.assertRaisesRegex(ValueError,'verified_snapshot'):self.project(snapshot=lambda:None)
        self.completion.write_bytes(self.completion.read_bytes()+b' ')
        with self.assertRaises(Exception):self.project()

    def test_label_path_hash_and_population_refuse(self):
        other=self.root/'other.json';other.write_bytes(self.labels.read_bytes())
        with self.assertRaisesRegex(ValueError,'source_path'):self.project(path=other)
        self.labels.write_text('{}')
        with self.assertRaisesRegex(ValueError,'dependency_changed'):self.project()

    def test_exact_population_and_whole_catalogue_do_not_depend_on_portion_truth(self):
        identities,proof=self.snapshot.load()
        codes={'a':'12345679'}
        self.ctx.catalog['asa_options']['12345679']=deepcopy(self.ctx.catalog['asa_options']['12345678'])
        contexts=contexts_after_seal(self.ctx.rows,identities,self.ctx.catalog,codes,proof)
        self.assertEqual(contexts['a']['code'],'12345679')
        self.assertEqual(len(contexts['a']['options']),1)
        codes['a']='99999999'
        self.assertEqual(contexts_after_seal(self.ctx.rows,identities,self.ctx.catalog,codes,proof),{})
        identities['a']['status']='failed'
        with self.assertRaises(ValueError):contexts_after_seal(self.ctx.rows,identities,self.ctx.catalog,{'a':'12345678'},proof)

    def test_caller_context_cannot_change_snapshot_rows_or_catalogue(self):
        self.ctx=SimpleNamespace(rows=deepcopy(self.ctx.rows),catalog=deepcopy(self.ctx.catalog),binding=deepcopy(self.ctx.binding))
        self.ctx.catalog['asa_options']['12345678'].append(dict(option_id='extra',description='extra',grams=50))
        with self.assertRaisesRegex(ValueError,'snapshot_context_changed'):self.project()

    def test_clean_loopback_only_namespace_contract_is_accepted(self):
        raw=(b'Inter-| Receive | Transmit\n'
             b'face |bytes packets errs drop fifo frame compressed multicast |bytes packets errs drop fifo colls carrier compressed\n'
             b'lo: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n')
        with patch.dict('os.environ',CLEAN_ENV,clear=True),patch('adapter_p.sys.platform','linux'),patch.object(Path,'read_bytes',return_value=raw):
            self.assertIsNone(_isolation_check())

    def test_production_child_requires_clean_env_isolation_and_real_review(self):
        with patch.dict('os.environ',{'SYNTHETIC_SECRET':'opaque'},clear=True):
            with self.assertRaisesRegex(ValueError,'clean_environment'):prepare()
        with patch('adapter_p._isolation_check'),patch('context_p.runtime_context',side_effect=ValueError('synthetic_review_missing')):
            with self.assertRaisesRegex(ValueError,'review_missing'):prepare()
        with patch('adapter_p.sys.argv',['adapter_p.py','--alternate-path']):
            with self.assertRaisesRegex(ValueError,'no_arguments'):main()
        with patch.dict('os.environ',CLEAN_ENV,clear=True),patch('adapter_p.sys.platform','darwin'):
            with self.assertRaisesRegex(ValueError,'portable_fallback'): _isolation_check()
        with patch.dict('os.environ',CLEAN_ENV,clear=True),patch('adapter_p.sys.platform','linux'),patch.object(Path,'read_bytes',return_value=b'not isolated'):
            with self.assertRaisesRegex(ValueError,'isolated_network'):_isolation_check()


if __name__=='__main__':unittest.main()
