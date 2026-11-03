"""Hand-calculated alternative joins, full fallbacks and common-profile selection."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src')]
import test_uncertain_portions as fixtures
A, B, C = fixtures.A, fixtures.B, fixtures.C
from records_n import core_record,coding_snapshot
from scoring_n import adapt_asa,shared_identity,select
from opt_pipeline import ContractError

class RecordScoreTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.UncertainCoreTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.base['candidates']['p1c2'].append(B)
        self.f.choice['items'][1]['codes'] = [C,B]
        self.p = self.f.pipeline([self.f.choice]); self.i = self.f.identity(self.p)
        self.q = self.p.density_portion(self.f.image,self.i,self.f.base,self.f.old_portion())
        self.row = {'sample_id':'synthetic','dataset':'asa24','group_id':'g','fold':0}
        self.median = {'weight':500,'energy':600,'fat':7,'carbs':8,'protein':9}
        self.record = core_record(self.row,self.i,self.q,self.median,coding_snapshot(self.i))
        self.catalog = deepcopy(self.p.catalog)
        self.catalog['asa_options'] = {B:[{'option_id':'a','grams':100}, {'option_id':'b','grams':200}]}

    def test_alternative_true_code_sums_two_distinct_physical_leaves_once(self):
        pred = adapt_asa([self.row],{'synthetic':{'food_code':B}},[self.record],self.catalog)[0]
        self.assertEqual(pred['conditional']['continuous_grams'],150)
        self.assertEqual(pred['conditional']['option_id'],'a')
        self.assertEqual(pred['conditional']['prediction']['energy'],300)
        self.assertEqual(pred['e2e']['prediction'],self.q['prediction'])

    def test_whole_image_failure_keeps_exact_identity_and_scores_median_option(self):
        failed = {'status':'failed','failure':'bad_quantity','prediction':None,'raw_leaves':[]}
        record = core_record(self.row,self.i,failed,self.median,coding_snapshot(self.i))
        pred = adapt_asa([self.row],{'synthetic':{'food_code':B}},[record],self.catalog)[0]
        self.assertEqual(pred['final_codes'],self.record['final_codes'])
        self.assertTrue(pred['conditional']['fallback']); self.assertIsNone(pred['conditional']['continuous_grams'])
        self.assertEqual(pred['conditional']['option_id'],'a')
        self.assertEqual(pred['e2e']['prediction'],self.median)

    def test_missing_duplicate_mass_and_changed_alternative_density_or_total_rejected(self):
        bads = []
        q = deepcopy(self.q); q['raw_leaves'].pop(); bads.append(q)
        q = deepcopy(self.q); q['raw_leaves'][1] = q['raw_leaves'][0]; bads.append(q)
        q = deepcopy(self.q); q['raw_leaves'][0]['codes'] = [B]; bads.append(q)
        q = deepcopy(self.q); q['prediction']['fat'] += 1; bads.append(q)
        for q in bads:
            with self.assertRaises((ValueError,ContractError)):
                core_record(self.row,self.i,q,self.median,coding_snapshot(self.i))

    def test_quantity_cannot_change_codes_and_imported_repair_is_not_native(self):
        coding = coding_snapshot(self.i); self.q['imported_quantity_repaired'] = True
        record = core_record(self.row,self.i,self.q,self.median,coding)
        self.assertTrue(record['repair_used']); self.assertFalse(record['new_repair_used'])
        self.assertFalse(record['native_complete']); self.assertEqual(record['coding'],coding)
        altered = deepcopy(coding); altered['final_codes'].reverse()
        with self.assertRaisesRegex(ValueError,'pre_quantity_coding'):
            core_record(self.row,self.i,self.q,self.median,altered)

    def test_profile_shared_identity_is_required_despite_quantity_failure(self):
        second = deepcopy(self.record); second['prediction'] = self.median; second['fallback'] = True
        self.assertTrue(shared_identity({'N-density':[self.record],'N-units':[second]}))
        second['final_codes'].reverse()
        with self.assertRaisesRegex(ValueError,'shared_identity'):
            shared_identity({'N-density':[self.record],'N-units':[second]})

    def test_tied_profile_selection_prefers_density_independent_of_dict_order(self):
        result = {'tolerance':{'recognition_guard_pass':True,'rank':[2,1.1,3,0.8],'accepted':True}}
        for names in [('N-density','N-units'),('N-units','N-density')]:
            self.assertEqual(select({n:deepcopy(result) for n in names})['selected'],'N-density')

if __name__ == '__main__': unittest.main()
