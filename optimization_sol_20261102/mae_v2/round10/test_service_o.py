from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10')]
import service_o as s
from opt_provider import fingerprint,ProviderStop,CHAT_MODEL,EMBED_MODEL
from historical_m import request_hash as old_hash
from runtime_m import durable_json


class BoundGate:
    def __init__(self, expected): self.expected=expected
    def validate(self,sid,value):
        if self.expected.get(sid)!=value: raise ValueError('synthetic_unregistered_task')


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        rows=[{'sample_id':'a','dataset':'asa24'},{'sample_id':'n','dataset':'nutrition5k'}]
        self.image='data:image/png;base64,fixture'
        self.slots=s.allowed_slots(rows,image_hashes={r['sample_id']:fingerprint(self.image) for r in rows})
        self.ledger=s.Ledger(Path(self.temp.name)/'service',{'source_files':{}},self.slots)
        self.expected={}; self.ledger._gate=BoundGate(self.expected);self.ledger.initialize()

    def chat(self):
        value=s.payload([{'role':'system','content':'synthetic'}, {'role':'user','content':[
            {'type':'text','text':'synthetic prompt'}, {'type':'image_url','image_url':{'url':self.image}}]}])
        sid=s.slot_id('a','identify',0); self.expected[sid]=value
        return sid,value

    def test_exact_slot_universe_and_no_N5_conditional(self):
        rows=[{'sample_id':str(i),'dataset':'asa24' if i<99 else 'nutrition5k'} for i in range(183)]
        slots=s.allowed_slots(rows,image_hashes={r['sample_id']:'synthetic' for r in rows})
        self.assertEqual(len(slots),8616)
        self.assertEqual(sum(v['role']=='embedding' for v in slots.values()),7320)
        self.assertNotIn(s.slot_id('100','conditional',0),slots)
        for stage,ordinal in [('embed_40',0),('embed_00',1)]:
            with self.assertRaises(ValueError):s.slot_id('a',stage,ordinal)

    def test_fixed_role_and_unchanged_official_embedding_hash(self):
        value=s.embedding_payload('synthetic food')
        self.assertEqual(s.request_hash(value),old_hash('embedding',value['payload'],'official-query-v1'))
        for change in ('model','batch','role'):
            bad=deepcopy(value)
            if change=='model':bad['payload']['model']=CHAT_MODEL
            elif change=='batch':bad['payload']['input']*=2
            else:bad['role']='chat'
            with self.assertRaises(ValueError):s.request_hash(bad)

    def test_unknown_reservations_are_not_refunded_across_slots(self):
        value=s.embedding_payload('same query')
        a,b=s.slot_id('a','embed_00',0),s.slot_id('n','embed_00',0)
        self.expected.update({a:value,b:value})
        h=self.ledger.bind(a,value);self.ledger.reserve(a,h);self.ledger.reserve(a,h)
        self.ledger.bind(b,value);self.ledger.reserve(b,h)
        with self.assertRaises(ProviderStop):self.ledger.reserve(b,h)
        self.assertEqual(self.ledger.audit()['counts']['unknown_outcomes'],3)

    def test_raw_success_recovery_without_new_reservation_or_provider(self):
        sid,value=self.chat();h=self.ledger.bind(sid,value);reservation=self.ledger.reserve(sid,h)
        body={'model':CHAT_MODEL,'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}
        outcome={'reservation':reservation,'kind':'success','status':200,'body':body,
                 'value':'ok','value_hash':fingerprint('ok'),'error_type':None}
        durable_json(self.ledger.outcome_path(reservation['id']),outcome)
        with self.assertRaisesRegex(ValueError,'unanchored_outcome'):self.ledger.target(h)
        recovered=self.ledger.target(h,recover=True)
        self.assertEqual(recovered['cache']['value'],'ok')
        self.assertEqual(recovered['cache']['role'],'chat')
        self.assertEqual(recovered['reserved'],1)
        with self.assertRaises(ProviderStop):self.ledger.reserve(sid,h)

    def test_cache_tamper_cannot_replace_successful_answer(self):
        sid,value=self.chat();h=self.ledger.bind(sid,value);reservation=self.ledger.reserve(sid,h)
        body={'model':CHAT_MODEL,'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}
        self.ledger.persist(reservation,{'kind':'success','status':200,'body':body,
                            'value':'ok','value_hash':fingerprint('ok'),'error_type':None})
        cache=s.load(self.ledger.cache_path(h));cache['value']='changed'
        durable_json(self.ledger.cache_path(h),cache)
        with self.assertRaisesRegex(ValueError,'cache_outcome'):self.ledger.target(h)

    def test_embedding_success_and_nonfinite_or_wrong_model_rejection(self):
        value=s.embedding_payload('rice');sid=s.slot_id('a','embed_00',0)
        self.expected[sid]=value;h=self.ledger.bind(sid,value);reservation=self.ledger.reserve(sid,h)
        vector=[.1]*3072
        body={'model':EMBED_MODEL,'data':[{'index':0,'embedding':vector}]}
        outcome={'kind':'success','status':200,'body':body,'value':vector,
                 'value_hash':fingerprint(vector),'error_type':None}
        self.ledger.persist(reservation,outcome)
        self.assertEqual(self.ledger.target(h)['cache']['role'],'embedding')
        for change in ('index','model','nonfinite'):
            bad=deepcopy(outcome)
            if change=='index':bad['body']['data'][0]['index']=1
            elif change=='model':bad['body']['model']=CHAT_MODEL
            else:bad['body']['data'][0]['embedding'][0]=float('nan')
            with self.assertRaises(ValueError):
                self.ledger.validate_outcome({'reservation':reservation,**bad},reservation)

    def test_fatal_outcome_cannot_acquire_another_reservation(self):
        sid,value=self.chat();h=self.ledger.bind(sid,value);reservation=self.ledger.reserve(sid,h)
        self.ledger.persist(reservation,{'kind':'fatal','status':401,'body':None,'error_type':'authentication'})
        with self.assertRaises(ProviderStop):self.ledger.reserve(sid,h)

    def test_changed_slot_payload_refused(self):
        sid,value=self.chat();self.ledger.bind(sid,value)
        changed=deepcopy(value);changed['payload']['messages'][0]['content']='different'
        self.expected[sid]=changed
        with self.assertRaisesRegex(ValueError,'slot_payload_changed'):self.ledger.bind(sid,changed)


if __name__=='__main__': unittest.main()
