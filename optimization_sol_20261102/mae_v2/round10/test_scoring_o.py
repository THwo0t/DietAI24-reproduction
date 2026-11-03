from copy import deepcopy
from pathlib import Path
import sys
import unittest

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10')]
from scoring_o import score,public_summary


class ScoreTests(unittest.TestCase):
    def test_twenty_checks_fold_only_fit_and_failed_image_remains_scored(self):
        code='12345678';truth=dict(weight=100.,energy=100.,fat=2.,carbs=20.,protein=4.)
        rows=[];labels={};records=[]
        for dataset in ('asa24','nutrition5k'):
            for fold in range(5):
                sid=dataset+'-'+str(fold)
                row=dict(sample_id=sid,dataset=dataset,fold=fold,group_id=sid,split='dev')
                rows.append(row);labels[sid]={'truth':deepcopy(truth),'food_code':code,'size':'synthetic'}
                fallback=dataset=='nutrition5k' and fold==0
                record={**row,'final_codes':[code],'primary_code':code,'retrieved_codes':[code],
                    'prediction':deepcopy(truth),'raw_prediction':None if fallback else deepcopy(truth),
                    'fallback':fallback,'native_complete':not fallback,'repair_used':False,
                    'e2e':{'prediction':deepcopy(truth),'fallback':False},'conditional':None}
                if dataset=='asa24':
                    record['conditional']={'code':code,'option_id':'one','continuous_grams':100.,
                        'prediction':deepcopy(truth),'fallback':False,'native_complete':True}
                records.append(record)
        catalog={'foods':{code:{'density':{k:truth[k] for k in ('energy','fat','carbs','protein')}}},
                 'asa_options':{code:[{'option_id':'one','description':'1 cup','grams':100.}]}}
        result,predictions=score(rows,labels,records,catalog,bootstrap=0)
        self.assertEqual(result['OOF_mass']['metrics']['passed_checks'],20)
        self.assertEqual(result['OOF_mass']['metrics']['datasets']['nutrition5k']['primary']['n'],5)
        self.assertEqual(result['OOF_mass']['metrics']['datasets']['nutrition5k']['fallback_n'],1)
        self.assertEqual(len(predictions),10)
        for ds in result['calibration'].values():
            for fold in ds['fold_parameters']:
                self.assertTrue(set(fold['training_ids']).isdisjoint(fold['heldout_ids']))
                self.assertTrue(set(fold['training_groups']).isdisjoint(fold['heldout_groups']))
        public=public_summary(result)
        self.assertNotIn('training_ids',str(public));self.assertNotIn('heldout_ids',str(public))
        self.assertEqual(public['conditional_success']['native_n'],5)
        self.assertEqual(public['pure_median_baselines']['nutrition5k_all_population_median']['n'],5)


if __name__=='__main__':unittest.main()
