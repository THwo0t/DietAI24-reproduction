"""Synthetic P durable coding seal and zero-provider identity replay."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE/name) for name in ('round11','round10','src','round7/src','round8/src')]+[str(BASE)]
import test_gate_p as fixtures
from opt_provider import fingerprint,sha
from service_p import Ledger,PARSER_SOURCES,request_hash,slot_id
from runtime_p import Trace
from engine_p import RowLive,identify
from gate_p import Gate
from stores_p import name,proof_for_refs
from round4.src.artifacts import ArtifactStore
from identity_gate_p import build_loader,_load_snapshot


class LocalAnswers:
    """Persist synthetic envelopes directly; no HTTP/client/credential code."""
    def __init__(self,ledger,answers):self.ledger=ledger;self.answers=iter(answers);self.calls=0
    def request(self,sid,value):
        self.calls+=1;h=self.ledger.bind(sid,value);reservation=self.ledger.reserve(sid,h)
        raw=next(self.answers)
        body=({'model':value['payload']['model'],'choices':[{'message':{'content':raw},'finish_reason':'stop'}]}
              if value['role']=='chat' else {'model':value['payload']['model'],'data':[{'index':0,'embedding':raw}]})
        self.ledger.persist(reservation,dict(kind='success',status=200,body=body,value=raw,
                                           value_hash=fingerprint(raw),error_type=None))
        return raw,dict(slot=sid,payload_hash=h,value_hash=fingerprint(raw),reservation_id=reservation['id'],
                        cache_present_before=False,origin='new_P')
    def close(self):pass


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.GateTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;sources={}
        for source in PARSER_SOURCES:
            p=f.root/source;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic source '+source)
            sources[source]=sha(p)
        labels=f.root/'round11/prepared/cohort/dev_labels.json'
        labels.parent.mkdir(parents=True,exist_ok=True)
        labels.write_text(json.dumps({'a':dict(food_code='12345678',reference_weight='POISON_WEIGHT',
            size='POISON_SIZE',nutrients='POISON_NUTRIENTS')}))
        sources['round11/prepared/cohort/dev_labels.json']=sha(labels)
        slots=f.ledger.slots
        f.ctx.binding={'labels_sha256':sha(labels),'source_files':sources,'allowed_slots_sha256':fingerprint(slots),'transport_cap':len(slots)*3}
        f.ledger=Ledger(f.root/'service',f.ctx.binding,slots)
        f.gate=Gate(f.ctx,f.ledger,root=f.root,identity_loader=lambda:(f.sealed,{}))
        f.ledger._gate=f.gate;f.ledger.initialize()
        self.trace=Trace(f.ledger,f.ctx.imports,f.ctx.manifest_sha256,allow_paid=False)
        self.trace.provider=LocalAnswers(f.ledger,[f.identity_raw,[.1]*3072,[.1]*3072,f.selection])
        self.addCleanup(self.trace.close)
        self.store=ArtifactStore(f.root/'identities',f.ctx.binding,[name('identity',f.row),'service-proof'],
                                 verify_sources=f.ctx.verify_sources,root=f.root)
        stem=name('identity',f.row);inputs={'row_sha256':fingerprint(f.row),'image_sha256':f.row['image_sha256']}
        envelope=self.store.stage_runner(stem,inputs,
             lambda:identify(f.ctx,f.row,RowLive(f.row,self.trace),root=f.root),lambda value:value)
        self.envelopes={'a':envelope};f.sealed={'a':envelope['result']}
        refs={stem+'-'+stage:group for stage,group in envelope['request_refs'].items()}
        self.store.finalize({stem:envelope['result'],'service-proof':proof_for_refs(f.ledger,refs)})

    def snapshot(self,envelopes=None):
        return build_loader(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root,
                            envelopes=self.envelopes if envelopes is None else envelopes)

    def test_complete_snapshot_replays_without_provider(self):
        with patch('opt_provider.Provider',side_effect=AssertionError('provider forbidden')):
            snapshot=self.snapshot();self.assertEqual(snapshot.load()[0],self.f.sealed)
            snapshot.revalidate_full()
        self.assertEqual(self.trace.provider.calls,4)
        self.assertEqual(snapshot.load()[1]['coding_completion_sha256'],sha(self.store.directory/'completion.json'))

    def test_incomplete_and_caller_changed_envelopes_refused(self):
        with self.assertRaises(ValueError):self.snapshot({})
        for field in ('final_codes','candidates'):
            changed=deepcopy(self.envelopes);changed['a']['result'][field]=[]
            with self.subTest(field=field),self.assertRaises(ValueError):self.snapshot(changed)
        for field,value in [('origin','new_O'),('payload_hash','0'*64),('extra',True)]:
            changed=deepcopy(self.envelopes);changed['a']['request_refs']['identify'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.snapshot(changed)

    def test_cache_bad_parser_and_model_change_refuse(self):
        initial=slot_id('a','identify',0);h=self.f.ledger.read()['bindings'][initial]
        path=self.f.ledger.cache_path(h);original=path.read_bytes()
        path.write_bytes(original+b' ')
        with self.assertRaises(ValueError):self.snapshot()
        path.write_bytes(original)
        snapshot=self.snapshot()
        self.f.row['image_sha256']='0'*64
        with self.assertRaises(ValueError):snapshot.load()

    def test_restart_loader_reads_exact_sealed_envelopes_without_provider(self):
        with patch('runtime_p.PProvider',side_effect=AssertionError('provider forbidden')):
            snapshot=_load_snapshot(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root)
            self.assertEqual(snapshot.load()[0],self.f.sealed)
        self.f.ledger.binding='0'*64
        with self.assertRaisesRegex(ValueError,'science_binding'):
            _load_snapshot(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root)

    def test_false_repair_proof_and_source_change_refuse(self):
        initial=slot_id('a','identify',0);state=self.f.ledger.read()
        state['repairs'][initial]={'raw_hash':fingerprint(self.f.identity_raw),'error':'injected',
                                  'parser_sha256':self.f.ledger.parser_sha256}
        self.f.ledger.save(state)
        with self.assertRaisesRegex(ValueError,'repair_not_actual'):self.snapshot()
        state['repairs']={};self.f.ledger.save(state);snapshot=self.snapshot()
        path=self.f.root/next(iter(self.f.ctx.binding['source_files']))
        path.write_text('changed synthetic source')
        with self.assertRaisesRegex(ValueError,'dependency_changed'):snapshot.load()

if __name__=='__main__':unittest.main()
