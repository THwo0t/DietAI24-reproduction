from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10'),str(BASE/'round11')]
import records_p as r
from source_portions import SourcePortionPipeline,CONFIG
from paired_stage_pipeline import PairedStagePipeline
from opt_provider import fingerprint
from opt_metrics import option_prediction


class RecordsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.image=Path(self.tmp.name)/'synthetic.png';Image.new('RGB',(13,17),'red').save(self.image)
        self.row=dict(sample_id='synthetic',dataset='asa24',split='dev',fold=0,group_id='g',
            image_path='round11/prepared/cohort/images/dev/synthetic.png',image_sha256='a'*64)
        self.catalog={'foods':{code:dict(description=text,density=dict(energy=e,fat=2,carbs=10,protein=3))
            for code,text,e in [('12345678','rice',100),('12345679','other rice',300),('22345678','beans',50)]},
            'standard_options':{},'asa_options':{'12345678':[dict(option_id='small',grams=50,description='small'),
                dict(option_id='medium',grams=100,description='medium'),dict(option_id='large',grams=150,description='large')]}}
        self.fallback=dict(weight=25,energy=40,fat=1,carbs=4,protein=2)
        self.binding=dict(row_sha256=fingerprint(self.row),identity_seal_sha256='b'*64,
            request_proof_sha256='c'*64,fallback_binding_sha256='d'*64)
        self.identify=[json.dumps({'items':[dict(item_id='i1',description='rice',broad_query='rice',region_ids=['r1'])]}),
            json.dumps({'items':[dict(item_id='i1',primary_code='12345678',alternative_codes=['12345679'])]})]
        self.q=json.dumps(dict(total_grams=200,items=[dict(item_id='i1',ratio=2)]))
        self.d=json.dumps(dict(items=[dict(item_id='i1',density_code='12345679')]))

    def pipeline(self,answers,paired=False):
        answers=iter(answers)
        class Retriever:
            def hybrid(self,*args,**kwargs):return ['12345678','12345679','22345678']
        cls=PairedStagePipeline if paired else SourcePortionPipeline
        return cls(lambda messages:next(answers),lambda texts:[[1.] for _ in texts],self.catalog,Retriever())

    def envelope(self,result):
        refs={stage:[] for stage in r.STAGES}
        for stage in result['stages']:
            kind={'source_standard_first':'whole','paired_quantity':'quantity','paired_density':'density',
                  'portion_conditional_option_continuous_option':'conditional'}.get(stage['stage'],stage['stage'])
            if kind=='retrieval':
                for i,_ in enumerate(stage['queries']):
                    refs[kind].append(self.ref('retrieval',i,fingerprint([1.])))
            else:
                for i,attempt in enumerate(stage['attempts']):refs[kind].append(self.ref(kind,i,fingerprint(attempt['raw'])))
        return dict(result=result,request_refs=refs)

    def ref(self,stage,index,value_hash):
        slot=r.slot_id(self.row['sample_id'],f'embed_{index:02d}',0) if stage=='retrieval' else r.slot_id(self.row['sample_id'],stage,index)
        return dict(slot=slot,payload_hash='e'*64,value_hash=value_hash,reservation_id=f'{index+1:032x}',cache_present_before=False,origin='new_P')

    def stages(self,*,whole=None,q=None,d=None,identity=None):
        identity=self.pipeline(self.identify if identity is None else identity).identify_select(self.image,self.row['dataset'],CONFIG)
        ie=self.envelope(identity)
        if identity['status']=='failed':return [ie,None,None,None]
        original=self.pipeline(['{"items":[{"item_id":"i1","mode":"grams","grams":100}]}'] if whole is None else whole).whole_portions(self.image,identity,self.row['dataset'])
        quantity=self.pipeline([self.q] if q is None else q,True).quantity_intervention(self.image,identity,self.row['dataset'])
        density=self.pipeline([self.d] if d is None else d,True).density_intervention(self.image,identity,self.row['dataset'])
        return [ie,self.envelope(original),self.envelope(quantity),self.envelope(density)]

    def compose(self,stages=None):return r.compose_record(self.row,*(self.stages() if stages is None else stages),self.catalog,self.fallback,evidence_binding=self.binding)

    def conditional(self,record,answers):
        context=dict(code='12345678',options=deepcopy(self.catalog['asa_options']['12345678']))
        identity=record['stage_envelopes']['identity']['result']
        result=self.pipeline(answers).conditional_portion(self.image,identity,context)
        return r.attach_conditional(record,self.envelope(result),context,self.catalog,adapter_binding=dict(
            identity_seal_sha256=self.binding['identity_seal_sha256'],context_sha256=fingerprint(context),request_proof_sha256='f'*64))

    def test_actual_native_stages_hand_computed_vectors_and_primary_distinction(self):
        record=self.compose();profiles=record['profiles']
        self.assertEqual([profiles[k]['prediction']['weight'] for k in ('O','Q','D','Q+D')],[100,200,100,200])
        self.assertEqual([profiles[k]['prediction']['energy'] for k in ('O','Q','D','Q+D')],[200,400,300,600])
        self.assertEqual(profiles['O']['prediction'],dict(weight=100,energy=200,fat=2,carbs=10,protein=3))
        for k,v in profiles.items():
            self.assertEqual(v['final_codes'],['12345678','12345679'])
            self.assertEqual(v['primary_code'],'12345678')
            self.assertEqual(v['leaves'][0]['mass_context_code'],'12345678')
        self.assertEqual(profiles['D']['density_primary_code'],'12345679')
        self.assertEqual(record['weight_manipulation'],{'O:D':'passed','Q:Q+D':'passed'})
        self.assertEqual(record['evidence_authentication'],'caller_responsibility_not_authenticated_here')

    def test_repaired_and_failed_dependencies_keep_unaffected_controls(self):
        record=self.compose(self.stages(q=['{}',self.q]));self.assertEqual(record['profiles']['Q']['status'],'repaired')
        record=self.compose(self.stages(q=['{}','{}']))
        self.assertEqual(record['profiles']['O']['status'],'native');self.assertEqual(record['profiles']['D']['status'],'native')
        for profile in ('Q','Q+D'):
            self.assertEqual(record['profiles'][profile]['prediction'],self.fallback)
            self.assertEqual(record['profiles'][profile]['fallback_reason'],'quantity_failed')
        record=self.compose(self.stages(whole=['{}','{}'],d=['{}','{}']))
        self.assertEqual(record['profiles']['Q']['status'],'native')
        self.assertEqual(record['profiles']['D']['fallback_reason'],'original+density_failed')
        self.assertEqual(record['weight_manipulation']['O:D'],'unavailable_due_to_fallback')

    def test_identity_failure_skips_all_and_preserves_population(self):
        record=self.compose(self.stages(identity=['{}','{}']))
        self.assertEqual(record['fallback_count'],4)
        self.assertTrue(all(v['prediction']==self.fallback for v in record['profiles'].values()))

    def test_one_shared_conditional_native_repaired_and_legal_median_fallback(self):
        record=self.compose();before=deepcopy([v['e2e'] for v in record['profiles'].values()])
        for answers,status,option in [(['{"grams":140}'],'native','large'),(['{}','{"grams":140}'],'repaired','large'),(['{}','{}'],'fallback','medium')]:
            out=self.conditional(record,answers);shared=out['conditional']
            self.assertEqual(shared['status'],status);self.assertEqual(shared['option_id'],option)
            self.assertEqual(len(shared['options']),3)
            self.assertEqual([v['e2e'] for v in out['profiles'].values()],before)
            self.assertTrue(all(v['conditional']==shared for v in out['profiles'].values()))
            self.assertEqual(out['coding']['final_codes'],record['coding']['final_codes'])
        self.assertEqual(shared['raw_option'],dict(weight=100,energy=100,fat=2,carbs=10,protein=3))

    def test_malformed_declared_successes_and_gram_joins_rejected(self):
        original=self.stages()
        for mutation in ('duplicate','missing','nan','illegal_code','grams','parsed','status','origin'):
            stages=deepcopy(original)
            if mutation=='duplicate':stages[1]['result']['raw_leaves']*=2
            elif mutation=='missing':stages[2]['result']['value']['items']=[]
            elif mutation=='nan':stages[1]['result']['raw_leaves'][0]['grams']=float('nan')
            elif mutation=='illegal_code':stages[3]['result']['value']['items'][0]['density_code']='99999999'
            elif mutation=='grams':stages[1]['result']['portions'][0]['grams']=999
            elif mutation=='parsed':stages[2]['result']['stages'][0]['parsed']['total_grams']=999
            elif mutation=='status':stages[3]['result']['status']='failed'
            else:stages[1]['request_refs']['whole'][0]['origin']='new_O'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.compose(stages)

    def test_n5_multi_item_physical_mass_and_density_never_rejoin_standards(self):
        self.row['dataset']='nutrition5k';self.binding['row_sha256']=fingerprint(self.row)
        self.identify=[json.dumps({'items':[dict(item_id='i1',description='rice',broad_query='rice',region_ids=['r1']),
            dict(item_id='i2',description='beans',broad_query='beans',region_ids=['r2'])]}),
            json.dumps({'items':[dict(item_id='i1',primary_code='12345678',alternative_codes=['12345679']),
                dict(item_id='i2',primary_code='22345678',alternative_codes=[])]})]
        self.q=json.dumps(dict(total_grams=240,items=[dict(item_id='i2',ratio=3),dict(item_id='i1',ratio=1)]))
        self.d=json.dumps(dict(items=[dict(item_id='i2',density_code='22345678'),dict(item_id='i1',density_code='12345679')]))
        stages=self.stages(whole=['{"items":[{"item_id":"i2","mode":"grams","grams":30},{"item_id":"i1","mode":"grams","grams":70}]}'])
        out=self.compose(stages);ps=out['profiles']
        self.assertEqual(ps['O']['prediction']['weight'],100)
        self.assertEqual(ps['O']['prediction']['energy'],155)
        self.assertEqual(ps['D']['prediction']['energy'],225)
        self.assertEqual(ps['Q']['prediction']['energy'],210)
        self.assertEqual(ps['Q+D']['prediction']['energy'],270)
        self.assertEqual([v['grams'] for v in ps['O']['leaves']],[70,30])
        self.assertEqual([v['grams'] for v in ps['D']['leaves']],[70,30])
        self.assertEqual([v['grams'] for v in ps['Q']['leaves']],[60,180])
        self.assertTrue(all(v['final_codes']==['12345678','22345678'] for v in ps.values()))
        with self.assertRaises(ValueError):self.conditional(out,['{"grams":100}'])

    def test_asa_four_code_identity_rejected_before_composition(self):
        stages=self.stages();stages[0]['result']['final_codes']+=['22345678','99999999']
        with self.assertRaises(ValueError):self.compose(stages)

    def test_conditional_subset_and_wrong_seal_or_non_nearest_mapping_rejected(self):
        record=self.compose()
        context=dict(code='12345678',options=deepcopy(self.catalog['asa_options']['12345678']))
        result=self.pipeline(['{"grams":140}']).conditional_portion(self.image,record['stage_envelopes']['identity']['result'],context)
        binding=dict(identity_seal_sha256='b'*64,context_sha256=fingerprint(context),request_proof_sha256='f'*64)
        for mutation in ('subset','seal','mapping'):
            ctx=deepcopy(context);env=self.envelope(deepcopy(result));proof=deepcopy(binding)
            if mutation=='subset':ctx['options']=ctx['options'][:1];proof['context_sha256']=fingerprint(ctx)
            elif mutation=='seal':proof['identity_seal_sha256']='0'*64
            else:env['result']['option_id']='small'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                r.attach_conditional(record,env,ctx,self.catalog,adapter_binding=proof)

    def test_failed_stage_cannot_carry_success_and_binding_not_self_authenticating(self):
        stages=self.stages(q=['{}','{}']);stages[2]['result']['value']={'total_grams':1,'items':[]}
        with self.assertRaises(ValueError):self.compose(stages)
        binding=deepcopy(self.binding);binding['row_sha256']='0'*64
        with self.assertRaises(ValueError):r.compose_record(self.row,*self.stages(),self.catalog,self.fallback,evidence_binding=binding)

if __name__=='__main__':unittest.main()
