"""Synthetic images/answers only; no provider or source-data access."""
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),*[str(BASE/n) for n in ('src','round7/src','round8/src','round10','round11')]]
import engine_p as e
from opt_pipeline import ContractError
from opt_provider import fingerprint


class Client:
    def __init__(self,answers):self.answers=iter(answers);self.calls=[]
    def chat(self,stage,messages,image):
        self.calls.append((stage,deepcopy(messages),image));return next(self.answers)
    def embed(self,texts):raise AssertionError('unexpected retrieval')
    def finish(self):return {'synthetic_calls':len(self.calls)}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        Image.new('RGB',(17,31),'red').save(self.root/'image.png')
        self.row={'sample_id':'a','dataset':'asa24','image_path':'image.png'}
        self.catalog={'foods':{code:{'description':text,'density':dict(energy=100,fat=2,carbs=20,protein=4)}
                       for code,text in [('12345678','rice'),('12345679','other rice')]},'asa_options':{}}
        self.ctx=SimpleNamespace(catalog=self.catalog,retriever=None)
        self.identity={'status':'ok','items':[dict(item_id='i1',description='rice',broad_query='rice',
            region_ids=['r1'],primary_code='12345678',alternative_codes=['12345679'])],
            'candidates':{'i1':['12345678','12345679']},'final_codes':['12345678','12345679']}
        self.q=json.dumps({'total_grams':240,'items':[{'item_id':'i1','ratio':2}]})
        self.d=json.dumps({'items':[{'item_id':'i1','density_code':'12345679'}]})

    def test_quantity_density_native_repair_and_both_datasets(self):
        for dataset in ('asa24','nutrition5k'):
            row={**self.row,'dataset':dataset};identity=deepcopy(self.identity)
            if dataset=='nutrition5k':identity['final_codes']=['12345678']
            for kind,raw in [('quantity',self.q),('density',self.d)]:
                for answers,status in [([raw],'native'),(['{}',raw],'repaired'),(['{}','{}'],'failed')]:
                    with self.subTest(dataset=dataset,kind=kind,status=status):
                        client=Client(answers);result=getattr(e,kind)(self.ctx,row,identity,client,root=self.root)
                        self.assertEqual(result['result']['status'],status)
                        self.assertEqual(result['request_refs'],client.finish())
                        self.assertTrue(all(call[0]==kind for call in client.calls))
                        self.assertEqual(result['result']['image_mode'],'square256')

    def test_fixed_lineage_invalid_before_image_or_chat(self):
        for change in (lambda x:x.update(final_codes=[]),lambda x:x['candidates'].update(i1=['12345679']),
                       lambda x:x['items'][0].update(primary_code='99999999')):
            identity=deepcopy(self.identity);change(identity)
            for function in (e.quantity,e.density,e.portions):
                client=Client([])
                with self.assertRaises(ContractError):function(self.ctx,{**self.row,'image_path':'missing'},identity,client,root=self.root)
                self.assertEqual(client.calls,[])

    def test_unsigned_metadata_not_in_blind_prompts(self):
        self.identity['reference_weight']='TARGET_POISON'
        self.catalog['foods']['12345678']['true_code']='TARGET_POISON'
        for fn,raw in ((e.quantity,self.q),(e.density,self.d)):
            client=Client([raw]);result=fn(self.ctx,self.row,self.identity,client,root=self.root)
            self.assertNotIn('TARGET_POISON',json.dumps(client.calls))
            self.assertNotIn('TARGET_POISON',json.dumps(result['result']['source_binding']))

    def test_conditional_isolated_argument_and_n5_forbidden(self):
        context={'code':'12345678','options':[]};seen=[]
        def conditional(pipeline,path,identity,received):seen.append(received);return {'sentinel':'conditional'}
        with patch.object(e.SourcePortionPipeline,'conditional_portion',conditional):
            result=e.portions(self.ctx,self.row,self.identity,Client([]),conditional_context=context,root=self.root)
        self.assertEqual(seen,[context]);self.assertEqual(result['result']['sentinel'],'conditional')
        with self.assertRaises(ContractError):
            e.portions(self.ctx,{**self.row,'dataset':'nutrition5k'},self.identity,Client([]),conditional_context=context,root=self.root)
        import inspect
        for function in (e.identify,e.quantity,e.density):self.assertNotIn('conditional_context',inspect.signature(function).parameters)

    def test_identify_routes_source_pipeline_identify_retrieval_select(self):
        class Source:
            def __init__(self,chat,embed,catalog,retriever):self.chat,self.embed=chat,embed
            def identify_select(self,path,dataset,config):
                self.chat(['first']);self.embed(['query']);self.chat(['select']);return {'status':'fixture'}
        class IdentityClient(Client):
            def embed(self,texts):self.calls.append(('retrieval',texts,None));return [[1]]
        client=IdentityClient(['first','selected'])
        with patch.object(e,'SourcePortionPipeline',Source):result=e.identify(self.ctx,self.row,client,root=self.root)
        self.assertEqual([c[0] for c in client.calls],['identify','retrieval','select'])
        self.assertEqual(result['result'],{'status':'fixture'})

    def test_actual_identify_and_conditional_source_pipeline(self):
        class Retriever:
            def hybrid(inner,queries,vectors,cap):return ['12345678','12345679']
        class IdentityClient(Client):
            def embed(inner,texts):return [[1] for _ in texts]
        self.ctx.retriever=Retriever()
        raw_identity=json.dumps({'items':[{k:self.identity['items'][0][k] for k in
                                          ('item_id','description','broad_query','region_ids')}]})
        raw_selection=json.dumps({'items':[{k:self.identity['items'][0][k] for k in
                                           ('item_id','primary_code','alternative_codes')}]})
        identity_client=IdentityClient([raw_identity,raw_selection])
        identity=e.identify(self.ctx,self.row,identity_client,root=self.root)['result']
        self.assertEqual(identity['final_codes'],self.identity['final_codes'])
        self.assertEqual([c[0] for c in identity_client.calls],['identify','select'])
        context={'code':'12345679','options':[{'option_id':'small','description':'small legal','grams':50},
                                            {'option_id':'large','description':'large legal','grams':150}]}
        client=Client(['{"grams":140}'])
        result=e.portions(self.ctx,self.row,identity,client,conditional_context=context,root=self.root)['result']
        self.assertEqual(result['code'],'12345679');self.assertEqual(result['option_id'],'large')
        self.assertEqual(result['continuous_grams'],140);self.assertEqual(client.calls[0][0],'conditional')
        # The conditional source food stays absent from subsequent blind Q input metadata.
        qclient=Client([self.q]);e.quantity(self.ctx,self.row,identity,qclient,root=self.root)
        self.assertNotIn('large legal',json.dumps(qclient.calls))

    def test_whole_uses_source_parser(self):
        raw=json.dumps({'items':[{'item_id':'i1','mode':'grams','grams':100}]})
        client=Client([raw]);result=e.portions(self.ctx,self.row,self.identity,client,root=self.root)
        self.assertEqual(result['result']['prediction']['weight'],100)
        self.assertEqual(client.calls[0][0],'whole')

    def replay(self,refs,verifier=None):
        return e.RowReplay(self.row,None,{},'a'*64,refs,_verifier=verifier or self.verify)

    def verify(self,ledger,imports,manifest,ref,value):
        if ref['payload_hash']!=fingerprint(value):raise ValueError('fixture_exact_payload_changed')
        return ref['answer']

    def refs(self):return {k:[] for k in e.STAGES}

    def test_replay_exact_single_physical_ref_and_payload(self):
        refs=self.refs();value=e.payload([{'role':'user','content':'q'}])
        refs['quantity']=[{'slot':e.slot_id('a','quantity',0),'payload_hash':fingerprint(value),'answer':self.q}]
        replay=self.replay(refs)
        self.assertEqual(replay.chat('quantity',value['payload']['messages'],'ignored'),self.q)
        self.assertEqual(replay.finish(),refs)
        with self.assertRaisesRegex(ValueError,'missing'):replay.chat('quantity',[],None)
        with self.assertRaisesRegex(ValueError,'payload_changed'):self.replay(refs).chat('quantity',[],None)
        with self.assertRaisesRegex(ValueError,'extra'):self.replay(refs).finish()

    def test_replay_schema_slot_stage_role_and_verifier_declines(self):
        for refs in (None,{},dict(self.refs(),quantity={}),dict(self.refs(),quantity=[{}])):
            with self.assertRaises(ValueError):self.replay(refs)
        refs=self.refs();refs['quantity']=[{'slot':e.slot_id('a','density',0)}]
        with self.assertRaisesRegex(ValueError,'slot_order'):self.replay(refs).chat('quantity',[],None)
        with self.assertRaises(ValueError):self.replay(self.refs()).chat('retrieval',[],None)
        with self.assertRaisesRegex(ValueError,'role_changed'):self.replay(self.refs()).request('quantity',e.embedding_payload('q'))
        refs['quantity']=[{'slot':e.slot_id('a','quantity',0)}]
        def decline(*args):raise ValueError('verifier_declines')
        with self.assertRaisesRegex(ValueError,'verifier_declines'):self.replay(refs,decline).chat('quantity',[],None)

    def test_replay_embedding_order_and_forty_slot_bound(self):
        refs=self.refs()
        for i in range(40):
            value=e.embedding_payload(str(i));refs['retrieval'].append({'slot':e.slot_id('a',f'embed_{i:02d}',0),
                                                        'payload_hash':fingerprint(value),'answer':[i]})
        replay=self.replay(refs);self.assertEqual(replay.embed([str(i) for i in range(40)]),[[i] for i in range(40)])
        replay.finish();refs['retrieval'].append({'slot':'forged'})
        replay=self.replay(refs);replay.embed([str(i) for i in range(40)])
        with self.assertRaises(ValueError):replay.embed(['40'])

    def test_rowlive_scopes_refs_and_no_retrieval_chat(self):
        class Trace:
            @contextmanager
            def expect(inner,sample,stage,image=None,refs=None):
                inner.scope=(sample,stage,image,refs);yield
            def chat(inner,messages):inner.scope[3].append({'stage':inner.scope[1]});return 'ok'
            def embed(inner,texts):inner.scope[3].append({'stage':'retrieval'});return [[1]]
        trace=Trace();live=e.RowLive(self.row,trace)
        for stage in e.STAGES:
            if stage=='retrieval':live.embed(['q'])
            else:
                self.assertEqual(live.chat(stage,[],'image'),'ok');self.assertEqual(trace.scope[:3],('a',stage,'image'))
        refs=live.finish();self.assertTrue(all(len(v)==1 for v in refs.values()))
        refs['whole'].clear();self.assertEqual(len(live.finish()['whole']),1)
        with self.assertRaises(ValueError):live.chat('retrieval',[],None)


if __name__=='__main__':unittest.main()
