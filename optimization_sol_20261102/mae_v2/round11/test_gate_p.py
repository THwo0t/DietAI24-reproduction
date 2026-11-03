"""Source/synthetic-only P frozen-task reconstruction; no transport or real data."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE)]+[str(BASE/name) for name in ('src','round7/src','round8/src','round10','round11')]
from PIL import Image
from opt_pipeline import encode_image
from opt_provider import fingerprint
from service_p import allowed_slots,slot_id,payload,embedding_payload,request_hash
from gate_p import Gate,frozen_gate
import engine_p


class Retriever:
    def hybrid(self,queries,vectors,cap):return ['12345678','12345679']


class MemoryLedger:
    def __init__(self,slots):
        self.slots=slots;self.parser_sha256='b'*64
        self.state={'bindings':{},'repairs':{}};self.cache={}
    def read(self):return deepcopy(self.state)
    def target(self,h):return {'cache':deepcopy(self.cache.get(h))}


class Client:
    def __init__(self,test,answers):
        self.t=test;self.answers=iter(answers);self.indices={};self.values=[]
    def request(self,stage,value):
        index=self.indices.get(stage,0);self.indices[stage]=index+1
        sid=slot_id('a',stage,index)
        if index==1:
            initial=slot_id('a',stage,0);h=self.t.ledger.state['bindings'][initial]
            raw=self.t.ledger.cache[h]['value']
            self.t.ledger.state['repairs'][initial]={'raw_hash':fingerprint(raw),
                'error':self.t.gate.format_error(initial,raw),'parser_sha256':self.t.ledger.parser_sha256}
        self.t.gate.validate(sid,value);self.values.append((sid,deepcopy(value)))
        raw=next(self.answers);h=request_hash(value)
        self.t.ledger.state['bindings'][sid]=h
        self.t.ledger.cache[h]={'value':raw,'value_hash':fingerprint(raw)}
        return raw
    def chat(self,stage,messages,image):return self.request(stage,payload(messages))
    def embed(self,texts):
        values=[]
        for text in texts:
            stage=f'embed_{self.indices.get("retrieval",0):02d}'
            self.indices['retrieval']=self.indices.get('retrieval',0)+1
            values.append(self.request(stage,embedding_payload(text)))
        return values
    def finish(self):return {}


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);image=self.root/'synthetic.png'
        Image.new('RGB',(31,17),'red').save(image)
        self.row=dict(sample_id='a',dataset='asa24',split='dev',fold=0,group_id='g',
                      image_path='synthetic.png',image_sha256='c'*64)
        option=[dict(option_id='one',description='1 cup cooked',grams=160.)]
        self.ctx=SimpleNamespace(rows=[self.row],retriever=Retriever(),imports={'entries':{}},
            manifest_sha256='d'*64,verify_sources=lambda:True,catalog={
            'foods':{code:dict(description=desc,density=dict(energy=100,fat=2,carbs=20,protein=4))
                     for code,desc in [('12345678','rice'),('12345679','other rice')]},
            'standard_options':{'12345678':option},'asa_options':{'12345678':deepcopy(option)}})
        slots=allowed_slots([self.row],image_hashes={'a':fingerprint(encode_image(image,'square256'))})
        self.ledger=MemoryLedger(slots);self.sealed={};self.context={}
        self.gate=Gate(self.ctx,self.ledger,root=self.root,
            identity_loader=lambda:(deepcopy(self.sealed),{'complete':True}),
            context_loader=lambda:deepcopy(self.context))
        self.identity_raw=json.dumps({'items':[dict(item_id='i1',description='synthetic rice',
            broad_query='synthetic grain',region_ids=['r1'])]})
        self.selection=json.dumps({'items':[dict(item_id='i1',primary_code='12345678',alternative_codes=['12345679'])]})

    def identify(self,bad=False):
        answers=(["{}"] if bad else [])+[self.identity_raw,[.1]*3072,[.1]*3072,self.selection]
        client=Client(self,answers)
        result=engine_p.identify(self.ctx,self.row,client,root=self.root)['result']
        self.sealed={'a':deepcopy(result)}
        return client,result

    def test_all_six_chat_stages_and_embeddings_reconstruct(self):
        client,identity=self.identify()
        for stage,raw,fn in [
            ('whole',json.dumps({'items':[dict(item_id='i1',mode='standard',option_id='one')]}),engine_p.portions),
            ('quantity',json.dumps({'total_grams':240,'items':[dict(item_id='i1',ratio=2)]}),engine_p.quantity),
            ('density',json.dumps({'items':[dict(item_id='i1',density_code='12345679')]}),engine_p.density)]:
            client=Client(self,[raw]);value=fn(self.ctx,self.row,identity,client,root=self.root)
            self.assertNotEqual(value['result']['status'],'failed')
            self.assertEqual(self.ledger.slots[client.values[0][0]]['stage'],stage)
        self.context={'a':dict(code='12345678',options=self.ctx.catalog['asa_options']['12345678'])}
        client=Client(self,[json.dumps({'grams':160})])
        engine_p.portions(self.ctx,self.row,identity,client,root=self.root,conditional_context=self.context['a'])
        self.assertEqual(self.ledger.slots[client.values[0][0]]['stage'],'conditional')
        self.assertEqual(len(self.ledger.slots),52)

    def test_payload_role_stage_and_model_drift_rejected(self):
        client,_=self.identify();sid,value=client.values[-1]
        for mutation in ('prompt','model','role','image'):
            changed=deepcopy(value)
            if mutation=='prompt':changed['payload']['messages'][1]['content'][0]['text']+=' poison'
            if mutation=='model':changed['payload']['model']='changed'
            if mutation=='role':changed['role']='embedding'
            if mutation=='image':changed['payload']['messages'][1]['content'][1]['image_url']['url']='changed'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.gate.validate(sid,changed)
        with self.assertRaises(ValueError):self.gate.validate(slot_id('a','quantity',0),value)
        with self.assertRaises(ValueError):self.gate.validate(slot_id('other','select',0),value)

    def test_rows_labels_dataset_source_and_image_drift_rejected(self):
        client,_=self.identify();sid,value=client.values[0]
        original=deepcopy(self.row)
        for key,val in [('reference_weight',10),('true_code','12345678'),('dataset','nutrition5k'),('fold',1)]:
            self.row[key]=val
            with self.subTest(key=key),self.assertRaises(ValueError):self.gate.validate(sid,value)
            self.row.clear();self.row.update(original)
        Image.new('RGB',(31,17),'blue').save(self.root/'synthetic.png')
        with self.assertRaises(ValueError):self.gate.validate(sid,value)

    def test_repair_requires_actual_cached_parser_failure(self):
        client,_=self.identify(bad=True)
        sid,value=client.values[1]
        self.assertTrue(self.gate.validate(sid,value))
        initial=slot_id('a','identify',0)
        proof=self.ledger.state['repairs'][initial]
        proof['error']='injected parser error'
        with self.assertRaisesRegex(ValueError,'repair_proof'):self.gate.validate(sid,value)
        proof['error']=self.gate.format_error(initial,'{}')
        h=self.ledger.state['bindings'][initial]
        self.ledger.cache[h]={'value':self.identity_raw,'value_hash':fingerprint(self.identity_raw)}
        with self.assertRaisesRegex(ValueError,'repair_proof'):self.gate.validate(sid,value)

    def test_q_d_require_exact_sealed_identity_and_no_label_context(self):
        _,identity=self.identify()
        self.sealed['a']['final_codes']=[]
        with self.assertRaisesRegex(ValueError,'verified_identity'):
            engine_p.quantity(self.ctx,self.row,identity,Client(self,[]),root=self.root)
        self.sealed={'a':identity}
        self.context={'a':dict(code='12345678',options=self.ctx.catalog['asa_options']['12345678'],reference_weight=160)}
        with self.assertRaises(ValueError):
            engine_p.portions(self.ctx,self.row,identity,Client(self,[]),root=self.root,conditional_context=self.context['a'])
        self.context={'a':dict(code='12345678',options=[])}
        with self.assertRaises(ValueError):
            engine_p.portions(self.ctx,self.row,identity,Client(self,[]),root=self.root,conditional_context=self.context['a'])

    def test_q_d_repair_and_native_answer_cannot_authorize_repair(self):
        _,identity=self.identify()
        for fn,raw in [(engine_p.quantity,json.dumps({'total_grams':240,'items':[dict(item_id='i1',ratio=1)]})),
                       (engine_p.density,json.dumps({'items':[dict(item_id='i1',density_code='12345679')]}))]:
            client=Client(self,['{}',raw])
            result=fn(self.ctx,self.row,identity,client,root=self.root)['result']
            self.assertEqual(result['status'],'repaired')
            self.assertEqual(len(client.values),2)
            initial=client.values[0][0]
            self.assertIsNone(self.gate.format_error(initial,raw))
            sid,value=client.values[1]
            self.ledger.state['repairs'][initial]['error']='invented'
            with self.assertRaisesRegex(ValueError,'repair_proof'):self.gate.validate(sid,value)

    def test_source_verification_and_candidate_drift_stop_admission(self):
        client,identity=self.identify();sid,value=client.values[-1]
        def changed():raise ValueError('synthetic_source_drift')
        self.ctx.verify_sources=changed
        with self.assertRaisesRegex(ValueError,'source_drift'):self.gate.validate(sid,value)
        self.ctx.verify_sources=lambda:True
        self.ctx.retriever.hybrid=lambda *args,**kwargs:['12345679','12345678']
        with self.assertRaisesRegex(ValueError,'previous_exact_request'):
            engine_p.density(self.ctx,self.row,identity,Client(self,[]),root=self.root)

    def test_production_entry_requires_review_and_exact_ledger_science_root(self):
        with patch('context_p.runtime_context',side_effect=ValueError('synthetic_missing_review')):
            with self.assertRaisesRegex(ValueError,'missing_review'):frozen_gate(self.ledger)
        self.ctx.binding={'synthetic':True};self.ledger.binding=fingerprint(self.ctx.binding)
        self.ledger.directory=self.root/'round11/provider/P'
        with patch('context_p.runtime_context',return_value=self.ctx),patch('gate_p.ROOT',self.root):
            gate=frozen_gate(self.ledger);self.assertIsInstance(gate,Gate)
            self.ledger.binding='0'*64
            with self.assertRaisesRegex(ValueError,'science_or_root'):frozen_gate(self.ledger)


if __name__=='__main__':unittest.main()
