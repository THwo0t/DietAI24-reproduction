from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10')]
import httpx
from PIL import Image
from opt_pipeline import encode_image
from opt_provider import fingerprint,CHAT_MODEL,EMBED_MODEL
from service_o import Ledger,allowed_slots,slot_id,payload
from runtime_o import Trace,OProvider
from gate_o import Gate
from engine_o import RowLive,RowReplay,identify,portions


class FakeRetriever:
    def hybrid(self,queries,vectors,cap):return ['12345678','12345679']


class ExactGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);Image.new('RGB',(80,60),(180,170,120)).save(self.root/'synthetic.png')
        self.row={'sample_id':'a','dataset':'asa24','group_id':'g','fold':0,'image_path':'synthetic.png'}
        self.code='12345678';self.alt='12345679'
        options=[{'option_id':'one','description':'1 cup cooked','grams':160.0}]
        catalog={'foods':{
            self.code:{'description':'rice','density':dict(energy=100,fat=2,carbs=20,protein=4)},
            self.alt:{'description':'other rice','density':dict(energy=200,fat=4,carbs=30,protein=6)}},
            'standard_options':{self.code:options},'asa_options':{self.code:deepcopy(options)}}
        self.imports={'entries':{},'blocked_hashes':[]}
        self.ctx=SimpleNamespace(rows=[self.row],catalog=catalog,retriever=FakeRetriever(),
                                imports=self.imports,verify_sources=lambda:True)
        self.image=encode_image(self.root/'synthetic.png','square256')
        self.ledger=Ledger(self.root/'service',{'source_files':{}},
            allowed_slots([self.row],image_hashes={'a':fingerprint(self.image)}))
        self.gate=Gate(self.ctx,self.ledger,root=self.root);self.ledger._gate=self.gate
        self.ledger.initialize();self.trace=Trace(self.ledger,self.imports,'synthetic-manifest',allow_paid=True)
        self.seen=[];self.identify_replies=[]
        def handler(request):
            value=json.loads(request.content);self.seen.append(value)
            if request.url.host=='api.openai.com':
                return httpx.Response(200,json={'model':EMBED_MODEL,'data':[{'index':0,'embedding':[.1]*3072}]})
            prompt=value['messages'][1]['content'][0]['text']
            if prompt.startswith('Identify the visible food accounting units'):
                answer=self.identify_replies.pop(0) if self.identify_replies else json.dumps({'items':[
                    {'item_id':'i1','description':'synthetic O gate fixture food 94e',
                     'broad_query':'synthetic O gate fixture category 94e','region_ids':['r1']}]})
            elif prompt.startswith('Recheck the image'):
                answer=json.dumps({'items':[{'item_id':'i1','primary_code':self.code,'alternative_codes':[self.alt]}]})
            elif prompt.startswith('Estimate the cooked edible portion'):
                answer=json.dumps({'items':[{'item_id':'i1','mode':'standard','option_id':'one'}]})
            elif prompt.startswith('Estimate the cooked edible weight'):
                answer=json.dumps({'grams':160.0})
            else:raise AssertionError('synthetic_unexpected_prompt')
            return httpx.Response(200,json={'model':CHAT_MODEL,'choices':[{'message':{'content':answer},'finish_reason':'stop'}]})
        self.provider=OProvider(self.ledger,self.imports,allow_paid=True,
            keys=('synthetic-chat-secret','synthetic-embedding-secret'),transport=httpx.MockTransport(handler),sleep=lambda _:None)
        self.trace.provider=self.provider;self.addCleanup(self.trace.close)

    def identity(self):return identify(self.ctx,self.row,RowLive(self.row,self.trace),root=self.root)

    def test_actual_identity_and_quantity_requests_reconstruct_and_replay(self):
        identity=self.identity()
        self.assertEqual(len(self.seen),4) # identify, two query embeddings, select.
        replay=identify(self.ctx,self.row,RowReplay(self.row,self.ledger,self.imports,'synthetic-manifest',identity['request_refs']),root=self.root)
        self.assertEqual(replay,identity);self.assertEqual(len(self.seen),4)
        portion=portions(self.ctx,self.row,identity['result'],RowLive(self.row,self.trace),root=self.root)
        self.assertEqual(portion['result']['prediction']['weight'],160.)
        replay=portions(self.ctx,self.row,identity['result'],
            RowReplay(self.row,self.ledger,self.imports,'synthetic-manifest',portion['request_refs']),root=self.root)
        self.assertEqual(replay,portion);self.assertEqual(len(self.seen),5)

    def test_changed_prompt_rejected_before_mock_http(self):
        identity=self.identity();ref=identity['request_refs']['select'][0]
        original=self.seen[-1]
        changed=deepcopy(original);changed['messages'][1]['content'][0]['text']+=' changed'
        with self.assertRaisesRegex(ValueError,'frozen_task_payload_changed'):
            self.gate.validate(ref['slot'],{'role':'chat','payload':changed})
        self.assertEqual(len(self.seen),4)

    def test_valid_initial_answer_cannot_get_repair(self):
        self.identity()
        initial=slot_id('a','identify',0)
        raw=self.ledger.target(self.ledger.read()['bindings'][initial])['cache']['value']
        self.assertIsNone(self.gate.format_error(initial,raw))
        with self.assertRaisesRegex(ValueError,'declared_parser_failure_not_actual'):
            self.ledger.format_failure(initial,raw,'invented_error',self.ledger.parser_sha256)

    def test_actual_invalid_initial_acquires_only_one_format_repair(self):
        self.identify_replies=['bad format',json.dumps({'items':[
            {'item_id':'i1','description':'synthetic O gate fixture food 94e',
             'broad_query':'synthetic O gate fixture category 94e','region_ids':['r1']}]})]
        identity=self.identity()
        self.assertTrue(identity['result']['repaired'])
        self.assertEqual(len(identity['request_refs']['identify']),2)
        self.assertEqual(len(self.ledger.read()['repairs']),1)
        replay=identify(self.ctx,self.row,RowReplay(self.row,self.ledger,self.imports,'synthetic-manifest',identity['request_refs']),root=self.root)
        self.assertEqual(identity,replay)

    def test_conditional_requires_seal_loader_then_uses_only_code_context(self):
        identity=self.identity();result=identity['result']
        self.gate.identity_loader=lambda:({'a':deepcopy(result)},{'complete':True})
        self.gate.context_loader=lambda:{'a':{'code':self.code,'options':self.ctx.catalog['asa_options'][self.code]}}
        context=self.gate.contexts()['a']
        conditional=portions(self.ctx,self.row,result,RowLive(self.row,self.trace),
                             conditional_context=context,root=self.root)
        self.assertEqual(conditional['result']['prediction']['weight'],160.)
        self.gate.context_loader=lambda:{}
        ref=conditional['request_refs']['conditional'][0]
        with self.assertRaisesRegex(ValueError,'not_registered_Exact'):
            self.gate.validate(ref['slot'],{'role':'chat','payload':self.seen[-1]})


if __name__=='__main__':unittest.main()
