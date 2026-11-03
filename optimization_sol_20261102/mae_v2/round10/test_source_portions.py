from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE/'src'),str(BASE/'round8/src'),str(BASE/'round7/src'),str(BASE/'round10')]
from source_portions import SourcePortionPipeline
from opt_pipeline import ContractError


class SourcePortionTests(unittest.TestCase):
    def setUp(self):
        self.code='12345678'; self.alt='12345679'
        self.catalog={'foods':{
            self.code:{'description':'cooked rice','density':dict(energy=100,fat=2,carbs=20,protein=4)},
            self.alt:{'description':'other rice','density':dict(energy=200,fat=4,carbs=30,protein=6)}},
            'standard_options':{self.code:[{'option_id':'half','description':'1/2 cup cooked','grams':80.0},
                                          {'option_id':'one','description':'1 cup cooked','grams':160.0}]}}
        self.pipeline=SourcePortionPipeline(None,None,self.catalog,None)
        self.identity={'status':'ok','items':[{'item_id':'i1','description':'cooked rice',
            'broad_query':'rice','region_ids':['r1'],'primary_code':self.code,'alternative_codes':[self.alt]}],
            'candidates':{'i1':[self.code,self.alt]},'final_codes':[self.code,self.alt]}

    def parse(self, item, context=None):
        context=self.pipeline.portion_context(self.identity,'asa24') if context is None else context
        return self.pipeline.parse_quantities(json.dumps({'items':[item]}),self.identity,'asa24',context)

    def test_standard_is_exact_and_alternatives_do_not_duplicate_mass(self):
        value=self.parse({'item_id':'i1','mode':'standard','option_id':'half'})
        self.assertEqual(value['prediction']['weight'],80.)
        self.assertEqual(value['prediction']['energy'],120.)
        self.assertEqual(value['prediction']['protein'],4.)
        self.assertEqual(len(value['raw_leaves']),1)

    def test_standard_mode_cannot_hide_count_multiplier(self):
        with self.assertRaises(ContractError):
            self.parse({'item_id':'i1','mode':'standard','option_id':'half','count':3})

    def test_adjusted_count_is_one_unit_not_fractional_source(self):
        context=self.pipeline.portion_context(self.identity,'asa24')
        unit=context[0]['canonical_units'][0]
        value=self.parse({'item_id':'i1','mode':'adjusted','no_standard_fit':True,
                          'unit_id':unit['unit_id'],'count':1.5},context)
        self.assertEqual(value['prediction']['weight'],240.)
        self.assertEqual(len(unit['sources']),2)

    def test_adjustment_requires_explicit_no_fit_and_legal_unit(self):
        for flag,uid in [(False,'u_bad'),(1,'u_bad'),(True,'u_bad')]:
            with self.assertRaises(ContractError):
                self.parse({'item_id':'i1','mode':'adjusted','no_standard_fit':flag,'unit_id':uid,'count':1})

    def test_direct_grams_only_when_no_physical_catalogue(self):
        with self.assertRaises(ContractError):
            self.parse({'item_id':'i1','mode':'grams','grams':100})
        self.catalog['standard_options']={}
        self.assertEqual(self.parse({'item_id':'i1','mode':'grams','grams':100})['prediction']['weight'],100.)

    def test_nan_infinity_negative_zero_and_bool_are_rejected(self):
        self.catalog['standard_options']={}
        for grams in [float('nan'),float('inf'),-1,0,True]:
            with self.assertRaises(ContractError):
                self.parse({'item_id':'i1','mode':'grams','grams':grams})

    def test_changed_quantity_context_rejected(self):
        context=self.pipeline.portion_context(self.identity,'asa24')
        context[0]['standard_options'][0]['grams']=1
        with self.assertRaises(ContractError):
            self.parse({'item_id':'i1','mode':'standard','option_id':'half'},context)

    def test_code_and_physical_ownership_tampering_rejected(self):
        self.identity['items'][0]['alternative_codes']=[self.code]
        with self.assertRaises(ContractError):
            self.pipeline.portion_context(self.identity,'asa24')

    def test_main_quantity_prompt_has_no_label_interface(self):
        context=self.pipeline.portion_context(self.identity,'asa24')
        prompt=self.pipeline.quantity_prompt(context)
        for text in ('reference_weight','true_weight','food_code_truth','LabelUnit','sample_id'):
            self.assertNotIn(text,prompt)

    def test_conditional_context_cannot_include_true_weight_or_option(self):
        with self.assertRaises(ContractError):
            self.pipeline.conditional_portion(None,self.identity,{'code':self.code,'options':[], 'true_weight':80})

    def test_duplicate_quantities_are_not_partial_success(self):
        context=self.pipeline.portion_context(self.identity,'asa24')
        raw={'items':[{'item_id':'i1','mode':'standard','option_id':'half'}]*2}
        with self.assertRaises(ContractError):
            self.pipeline.parse_quantities(json.dumps(raw),self.identity,'asa24',context)

    def test_record_keeps_whole_fallback_and_rejects_changed_mass_join(self):
        from records_o import main_record,coding_snapshot
        self.identity['retrieved_codes']=[self.code,self.alt]
        row={'sample_id':'synthetic','dataset':'asa24','group_id':'g','fold':0}
        fallback=dict(weight=100,energy=200,fat=3,carbs=20,protein=5)
        coding=coding_snapshot(self.identity)
        failed={'status':'failed','failure':'format','prediction':None,'raw_leaves':[]}
        record=main_record(row,self.identity,failed,fallback,self.pipeline,coding)
        self.assertTrue(record['fallback'])
        self.assertEqual(record['prediction'],fallback)
        good=self.parse({'item_id':'i1','mode':'standard','option_id':'half'})
        good['prediction']['weight']=1
        with self.assertRaisesRegex(ValueError,'mass_or_density_join'):
            main_record(row,self.identity,good,fallback,self.pipeline,coding)

    def test_conditional_fallback_retains_exact_row_without_changing_E2E(self):
        from records_o import main_record,coding_snapshot,attach_conditional
        self.identity['retrieved_codes']=[self.code,self.alt]
        row={'sample_id':'synthetic','dataset':'asa24','group_id':'g','fold':0}
        fallback=dict(weight=100,energy=200,fat=3,carbs=20,protein=5)
        main=self.parse({'item_id':'i1','mode':'standard','option_id':'half'})
        record=main_record(row,self.identity,main,fallback,self.pipeline,coding_snapshot(self.identity))
        self.catalog['asa_options']={self.code:deepcopy(self.catalog['standard_options'][self.code])}
        failed={'status':'failed','failure':'conditional_format','prediction':None,'repaired':False}
        output=attach_conditional(record,failed,{'code':self.code,'options':self.catalog['asa_options'][self.code]},self.catalog)
        self.assertTrue(output['conditional']['fallback'])
        self.assertEqual(output['e2e'],record['e2e'])
        self.assertEqual(output['prediction'],record['prediction'])
        self.assertEqual(output['final_codes'],record['final_codes'])

    def assert_repair_provenance(self, *, main_repaired, main_failed, conditional_repaired):
        from records_o import main_record,coding_snapshot,attach_conditional
        from opt_metrics import evaluate,option_prediction
        self.identity['retrieved_codes']=[self.code,self.alt]
        row={'sample_id':'synthetic','dataset':'asa24','group_id':'g','fold':0}
        fallback=dict(weight=100,energy=200,fat=3,carbs=20,protein=5)
        main=({'status':'failed','failure':'format','prediction':None,'raw_leaves':[]}
              if main_failed else self.parse({'item_id':'i1','mode':'standard','option_id':'half'}))
        main['repaired']=main_repaired
        record=main_record(row,self.identity,main,fallback,self.pipeline,coding_snapshot(self.identity))
        options=deepcopy(self.catalog['standard_options'][self.code])
        self.catalog['asa_options']={self.code:options}
        prediction=option_prediction(options[0],self.catalog['foods'][self.code]['density'])
        conditional={'status':'ok','code':self.code,'option_id':'half','continuous_grams':80.,
                     'prediction':prediction,'repaired':conditional_repaired}
        output=attach_conditional(record,conditional,{'code':self.code,'options':options},self.catalog)
        self.assertEqual({k:v for k,v in output.items() if k not in ('conditional','conditional_repair_used')},
                         {k:v for k,v in record.items() if k not in ('conditional','conditional_repair_used')})
        self.assertEqual(output['conditional_repair_used'],conditional_repaired)
        labels={'synthetic':{'truth':prediction,'food_code':self.code,'size':'synthetic'}}
        stats=evaluate([row],labels,[output],bootstrap=0)['datasets']['asa24']
        self.assertEqual(stats['native_complete_n'],int(not main_repaired and not main_failed))
        self.assertEqual(stats['repair_success_n'],int(main_repaired and not main_failed))
        self.assertEqual(stats['fallback_n'],int(main_failed))
        self.assertEqual(stats['conditional_fallback_n'],0)
        self.assertEqual(stats['primary']['n'],1)

    def test_native_main_and_repaired_conditional_have_separate_success_counts(self):
        self.assert_repair_provenance(main_repaired=False,main_failed=False,conditional_repaired=True)

    def test_repaired_main_and_native_conditional_have_separate_success_counts(self):
        self.assert_repair_provenance(main_repaired=True,main_failed=False,conditional_repaired=False)

    def test_main_fallback_and_conditional_success_keep_distinct_provenance(self):
        self.assert_repair_provenance(main_repaired=False,main_failed=True,conditional_repaired=True)


if __name__=='__main__': unittest.main()
