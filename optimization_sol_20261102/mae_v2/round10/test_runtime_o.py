from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10')]
import httpx
import service_o as s
from runtime_o import OProvider
from opt_provider import fingerprint,ProviderStop,CHAT_MODEL,EMBED_MODEL
from test_service_o import BoundGate


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.image='data:image/png;base64,fixture'
        slots=s.allowed_slots([{'sample_id':'a','dataset':'asa24'}],image_hashes={'a':fingerprint(self.image)})
        self.ledger=s.Ledger(Path(self.temp.name)/'service',{'source_files':{}},slots)
        self.expected={};self.ledger._gate=BoundGate(self.expected);self.ledger.initialize()
        self.keys=('synthetic-chat-secret','synthetic-embedding-secret')
        self.imports={'entries':{},'blocked_hashes':[]}

    def provider(self,handler):
        p=OProvider(self.ledger,self.imports,allow_paid=True,keys=self.keys,
                    transport=httpx.MockTransport(handler),sleep=lambda _:None)
        self.addCleanup(p.close)
        return p

    def chat(self):
        value=s.payload([{'role':'system','content':'synthetic'},{'role':'user','content':[
            {'type':'image_url','image_url':{'url':self.image}}]}])
        sid=s.slot_id('a','identify',0);self.expected[sid]=value
        return sid,value

    @staticmethod
    def chat_body(answer='ok',model=CHAT_MODEL):
        return {'model':model,'choices':[{'message':{'content':answer},'finish_reason':'stop'}]}

    def test_chat_and_official_embedding_use_separate_routes_and_keys(self):
        seen=[]
        def handler(request):
            seen.append((str(request.url),request.headers['Authorization']))
            if request.url.host=='api.zicc.cc':return httpx.Response(200,json=self.chat_body())
            return httpx.Response(200,json={'model':EMBED_MODEL,'data':[{'index':0,'embedding':[.1]*3072}]})
        provider=self.provider(handler)
        sid,value=self.chat();self.assertEqual(provider.request(sid,value)[0],'ok')
        sid=s.slot_id('a','embed_00',0);value=s.embedding_payload('synthetic transport rice')
        self.expected[sid]=value;self.assertEqual(len(provider.request(sid,value)[0]),3072)
        self.assertEqual(seen,[('https://api.zicc.cc/v1/chat/completions','Bearer '+self.keys[0]),
                               ('https://api.openai.com/v1/embeddings','Bearer '+self.keys[1])])

    def test_successful_answer_replayed_without_second_transmission(self):
        seen=[]
        def handler(request):seen.append(1);return httpx.Response(200,json=self.chat_body())
        p=self.provider(handler);sid,value=self.chat()
        p.request(sid,value);_,ref=p.request(sid,value)
        self.assertEqual(len(seen),1);self.assertTrue(ref['cache_present_before'])

    def test_two_transient_errors_keep_original_three_reservation_budget(self):
        seen=[]
        def handler(request):
            seen.append(1)
            return httpx.Response(502,json={'error':{'type':'service'}}) if len(seen)<3 else \
                   httpx.Response(200,json=self.chat_body())
        p=self.provider(handler);sid,value=self.chat();self.assertEqual(p.request(sid,value)[0],'ok')
        counts=self.ledger.audit()['counts']
        self.assertEqual(counts['reserved_attempts'],3);self.assertEqual(counts['errors'],2)

    def test_authentication_failure_is_persisted_redacted_and_not_retried(self):
        p=self.provider(lambda request:httpx.Response(401,json={'error':{'message':' '.join(self.keys)}}))
        sid,value=self.chat()
        with self.assertRaises(ProviderStop):p.request(sid,value)
        for path in self.ledger.directory.rglob('*.json'):
            text=path.read_text()
            for key in self.keys:self.assertNotIn(key,text)
        self.assertEqual(self.ledger.audit()['counts']['reserved_attempts'],1)

    def test_wrong_model_is_fatal(self):
        p=self.provider(lambda request:httpx.Response(200,json=self.chat_body(model='wrong-model')))
        sid,value=self.chat()
        with self.assertRaises(ProviderStop):p.request(sid,value)
        self.assertTrue(self.ledger.target(s.request_hash(value))['fatal'])

    def test_nonfinite_json_is_safe_fatal_evidence_not_unlogged_success(self):
        p=self.provider(lambda request:httpx.Response(200,content=b'{"model":"text-embedding-3-large","data":[{"index":0,"embedding":[NaN]}]}'))
        sid=s.slot_id('a','embed_00',0);value=s.embedding_payload('synthetic invalid vector')
        self.expected[sid]=value
        with self.assertRaises(ProviderStop):p.request(sid,value)
        state=self.ledger.target(s.request_hash(value))
        self.assertTrue(state['fatal']);self.assertEqual(len(state['outcomes']),1)


if __name__=='__main__':unittest.main()
