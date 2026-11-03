"""Synthetic-only P interruption/resume/complete replay and isolation tests."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE/name) for name in ('round11','round10','src','round7/src','round8/src')]+[str(BASE)]
import test_gate_p as fixture
from opt_provider import sha,fingerprint,ProviderStop
from opt_pipeline import encode_image
from service_p import Ledger,PARSER_SOURCES,allowed_slots
from runtime_p import Trace
from gate_p import Gate
from round4.src.artifacts import ArtifactStore
from stores_p import name
from adapter_p import _prepare
from run_p import _run,run,_verified_completed,_isolated_adapter,main
from types import SimpleNamespace


class OfflineProvider:
    def __init__(self,ledger,answers,*,interrupt=None):
        self.ledger=ledger;self.answers=answers;self.interrupt=interrupt;self.calls=[]
    def request(self,sid,value):
        meta=self.ledger.slots[sid];stage=meta['stage'];sample=meta['sample_id']
        h=self.ledger.bind(sid,value);cache=self.ledger.target(h)['cache']
        before=cache is not None
        if cache is None:
            if self.interrupt==stage:raise ProviderStop('synthetic_interruption')
            self.calls.append((sample,stage));r=self.ledger.reserve(sid,h)
            raw=self.answers(sample,stage)
            body=({'model':value['payload']['model'],'choices':[{'message':{'content':raw},'finish_reason':'stop'}]}
                  if value['role']=='chat' else {'model':value['payload']['model'],'data':[{'index':0,'embedding':raw}]})
            self.ledger.persist(r,dict(kind='success',status=200,body=body,value=raw,value_hash=fingerprint(raw),error_type=None))
            cache=self.ledger.target(h)['cache']
        return cache['value'],dict(slot=sid,payload_hash=h,value_hash=cache['value_hash'],reservation_id=cache['reservation_id'],
                                  cache_present_before=before,origin='new_P')
    def close(self):pass


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.GateTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;self.root=f.root;self.ctx=f.ctx
        other={**deepcopy(f.row),'sample_id':'n','dataset':'nutrition5k','group_id':'n'}
        self.ctx.rows.append(other)
        sources={}
        for source in PARSER_SOURCES:
            p=self.root/source;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic '+source);sources[source]=sha(p)
        labels=self.root/'round11/prepared/cohort/dev_labels.json';labels.parent.mkdir(parents=True,exist_ok=True)
        labels.write_text(json.dumps({'a':{'food_code':'12345678','weight':'POISON','size':'POISON'},'n':{'weight':'POISON'}}))
        self.labels=labels;sources['round11/prepared/cohort/dev_labels.json']=sha(labels)
        for path,raw in [('round11/prepared/cohort/dev.json',b'synthetic manifest'),('data/vectors/embeddings.npy',b'synthetic vectors'),
                         ('round11/prepared/cohort/source_closure.json',json.dumps({'strata_private':{'a':'core','n':'core'}}).encode())]:
            dest=self.root/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw);sources[path]=sha(dest)
        slots=allowed_slots(self.ctx.rows,image_hashes={r['sample_id']:fingerprint(encode_image(self.root/r['image_path'],'square256')) for r in self.ctx.rows})
        self.ctx.binding={'schema_version':1,'environment':{'synthetic':True},'source_files':sources,'labels_sha256':sha(labels),
                          'allowed_slots_sha256':fingerprint(slots),'transport_cap':len(slots)*3}
        self.ctx.fallbacks={'folds':{ds:{'0':{'value':dict(weight=100.,energy=110.,fat=3.,carbs=20.,protein=5.),
                                            'train_ids':['synthetic-train'],'heldout_ids':['a' if ds=='asa24' else 'n']}}
                                    for ds in ('asa24','nutrition5k')}}
        self.ledger=Ledger(self.root/'service',self.ctx.binding,slots)
        self.gate=Gate(self.ctx,self.ledger,root=self.root);self.ledger._gate=self.gate
        ids=ArtifactStore(self.root/'identities',self.ctx.binding,[name('identity',r) for r in self.ctx.rows]+['service-proof'],
                          verify_sources=self.ctx.verify_sources,root=self.root)
        out=ArtifactStore(self.root/'development',self.ctx.binding,[name('record',r) for r in self.ctx.rows]+['service-proof'],
                          verify_sources=self.ctx.verify_sources,root=self.root)
        # Adapter store binding needs the future coding seal, created by child seam.
        self.stores=[ids,out,None];self.adapter_calls=0;self.fail_quantity=False;self.fail_conditional=False

    def answers(self,sample,stage):
        if stage.startswith('embed_'):return [.1]*3072
        if sample=='n':return '{}'
        if stage=='identify':return self.f.identity_raw
        if stage=='select':return self.f.selection
        if stage=='whole':return json.dumps({'items':[dict(item_id='i1',mode='standard',option_id='one')]})
        if stage=='quantity':return '{}' if self.fail_quantity else json.dumps({'total_grams':240,'items':[dict(item_id='i1',ratio=1)]})
        if stage=='density':return json.dumps({'items':[dict(item_id='i1',density_code='12345679')]})
        if stage=='conditional':return '{}' if self.fail_conditional else json.dumps({'grams':160})
        raise AssertionError(stage)

    def adapter_store(self):
        seal=sha(self.stores[0].directory/'completion.json')
        return ArtifactStore(self.root/'adapter',{'science':self.ctx.binding,'coding_completion_sha256':seal,
            'labels_sha256':self.ctx.binding['labels_sha256'],'role':'post_coding_ASA_code_and_full_catalogue_only'},
            ['contexts','provenance'],verify_sources=self.ctx.verify_sources,root=self.root)

    def child(self,ctx,ledger,snapshot):
        self.adapter_calls+=1
        self.assertTrue((self.stores[0].directory/'completion.json').is_file())
        _prepare(ctx,snapshot,self.labels,self.stores[2],coding_completion_path=self.stores[0].directory/'completion.json',data_root=self.root)

    def execute(self,*,interrupt=None,complete=False):
        trace=Trace(self.ledger,self.ctx.imports,self.ctx.manifest_sha256,allow_paid=False)
        provider=None if complete else OfflineProvider(self.ledger,self.answers,interrupt=interrupt)
        trace.provider=provider
        # Resolve adapter lazily after the identity completion exists.
        class LazyStores:
            def __init__(inner,outer):inner.outer=outer
            def __getitem__(inner,key):
                if isinstance(key,slice):return inner.outer.stores[key]
                if key==2 and inner.outer.stores[2] is None:inner.outer.stores[2]=inner.outer.adapter_store()
                return inner.outer.stores[key]
        result=_run(self.ctx,ledger=self.ledger,trace=trace,adapter_runner=self.child,data_root=self.root,stores=LazyStores(self))
        return result,provider

    def test_four_profiles_shared_calls_fallback_all_rows_and_zero_provider_replay(self):
        result,provider=self.execute();self.assertEqual(result['records'],2);self.assertEqual(self.adapter_calls,1)
        self.assertEqual(provider.calls.count(('a','conditional')),1)
        self.assertEqual([s for sample,s in provider.calls if sample=='n'],['identify','identify'])
        values=self.stores[1].verify_completed();record=values[name('record',self.ctx.rows[0])]
        profiles=record['profiles']
        self.assertEqual(profiles['O']['prediction']['weight'],profiles['D']['prediction']['weight'])
        self.assertEqual(profiles['Q']['prediction']['weight'],profiles['Q+D']['prediction']['weight'])
        failed=values[name('record',self.ctx.rows[1])]
        self.assertTrue(all(p['fallback'] for p in failed['profiles'].values()))
        with patch('runtime_p.PProvider',side_effect=AssertionError('provider forbidden')):
            replay,_=self.execute(complete=True)
        self.assertTrue(replay['completed_replay']);self.assertFalse(replay['provider_constructed']);self.assertEqual(self.adapter_calls,1)

    def test_interruption_resume_does_not_repeat_completed_stage(self):
        with self.assertRaises(ProviderStop):self.execute(interrupt='quantity')
        self.assertFalse((self.stores[1].directory/'completion.json').exists())
        result,provider=self.execute();self.assertEqual(result['status'],'completed')
        self.assertNotIn(('a','whole'),provider.calls);self.assertEqual(self.adapter_calls,1)

    def test_partial_coding_never_runs_adapter(self):
        with self.assertRaises(ProviderStop):self.execute(interrupt='select')
        self.assertEqual(self.adapter_calls,0);self.assertFalse((self.stores[0].directory/'completion.json').exists())

    def test_exhausted_q_failure_keeps_successful_controls(self):
        self.fail_quantity=True;self.execute()
        record=self.stores[1].verify_completed()[name('record',self.ctx.rows[0])]
        self.assertFalse(record['profiles']['O']['fallback']);self.assertFalse(record['profiles']['D']['fallback'])
        self.assertTrue(record['profiles']['Q']['fallback']);self.assertTrue(record['profiles']['Q+D']['fallback'])

    def test_failed_conditional_remains_shared_exact_with_legal_median(self):
        self.fail_conditional=True;_,provider=self.execute()
        record=self.stores[1].verify_completed()[name('record',self.ctx.rows[0])]
        self.assertTrue(record['conditional']['fallback'])
        self.assertEqual(record['conditional']['option_id'],'one')
        self.assertEqual(provider.calls.count(('a','conditional')),2)
        self.assertTrue(all(p['conditional']==record['conditional'] for p in record['profiles'].values()))

    def test_frozen_row_and_sealed_stage_tamper_refuse(self):
        self.execute();self.ctx.rows[0]['fold']=1
        with self.assertRaises(Exception):self.execute(complete=True)

    def test_main_never_decodes_label_file_outside_adapter_child(self):
        original=Path.read_bytes;inside=[False];child=self.child
        def isolated(*args):
            inside[0]=True
            try:return child(*args)
            finally:inside[0]=False
        def guarded(path):
            if path==self.labels and not inside[0]:raise AssertionError('main label read forbidden')
            return original(path)
        self.child=isolated
        with patch.object(Path,'read_bytes',guarded):self.execute()

    def test_public_entry_requires_frozen_review_and_explicit_paid_boolean(self):
        with patch('context_p.runtime_context',side_effect=ValueError('synthetic_review_missing')):
            with self.assertRaisesRegex(ValueError,'review_missing'):run()
        with self.assertRaisesRegex(ValueError,'explicit_paid_flag'):run(allow_paid=1)
        with patch('run_p.run',return_value={'synthetic':True}) as call,patch('run_p.sys.argv',['run_p.py','--allow-paid']):
            self.assertEqual(main(),{'synthetic':True});call.assert_called_once_with(allow_paid=True)

    def test_incomplete_no_paid_flag_and_missing_adapter_seal_refuse(self):
        with self.assertRaisesRegex(ValueError,'paid_flag'):
            _run(self.ctx,ledger=self.ledger,data_root=self.root,stores=self.stores)
        self.execute();calls=self.adapter_calls
        (self.stores[2].directory/'completion.json').unlink()
        with patch('runtime_p.PProvider',side_effect=AssertionError('provider forbidden')):
            with self.assertRaisesRegex(ValueError,'existing_adapter_seal'):self.execute(complete=True)
        self.assertEqual(self.adapter_calls,calls)

    def test_completed_verifier_exports_postscore_binding_contract_without_provider(self):
        self.execute()
        with patch('runtime_p.PProvider',side_effect=AssertionError('provider forbidden')):
            result=_verified_completed(self.ctx,self.ledger,data_root=self.root,stores=self.stores)
            self.assertTrue(result['revalidate']())
        self.assertEqual(set(result),{'rows','records','catalog','strata','bindings','audit','revalidate'})
        self.assertEqual(len(result['records']),2);self.assertFalse(result['audit']['labels_parsed'])
        self.assertEqual(set(result['bindings']),{'science_sha256','manifest_sha256','labels_sha256',
            'record_seal_sha256','coding_seal_sha256','adapter_seal_sha256','model_environment_sha256',
            'matrix_sha256','request_cache_proof_sha256','source_snapshot_sha256'})

    def test_adapter_subprocess_has_fixed_offline_command_and_no_inherited_environment(self):
        self.execute()
        from identity_gate_p import _load_snapshot
        snapshot=_load_snapshot(self.ctx,self.ledger,self.stores[0],data_root=self.root)
        with patch('run_p.subprocess.run',return_value=SimpleNamespace(returncode=0)) as child:
            _isolated_adapter(self.ctx,self.ledger,snapshot)
            args=child.call_args;self.assertEqual(args.args[0][:2],['/usr/bin/unshare','-Urn'])
            self.assertIn('-B',args.args[0]);self.assertEqual(set(args.kwargs['env']),{'PATH','LANG','LC_ALL','PYTHONNOUSERSITE','PYTHONDONTWRITEBYTECODE'})
            self.assertEqual(args.kwargs['stdout'],__import__('subprocess').DEVNULL)
        with patch('run_p.subprocess.run',return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError,'child_failed'):_isolated_adapter(self.ctx,self.ledger,snapshot)


if __name__=='__main__':unittest.main()
