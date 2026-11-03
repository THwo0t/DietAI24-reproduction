from copy import deepcopy
from pathlib import Path
import sys
import unittest

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE/'src'),str(BASE/'round10')]
from conditional_o import contexts_after_seal,code_only
from opt_provider import fingerprint


class IsolatedConditionalTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'sample_id':'asa','dataset':'asa24'},{'sample_id':'n5','dataset':'nutrition5k'}]
        self.identities={'asa':{'status':'ok','final_codes':['12345678']},
                         'n5':{'status':'ok','final_codes':['23456789']}}
        self.catalog={'asa_options':{'12345678':[
            {'option_id':'small','description':'1/2 cup','grams':80},
            {'option_id':'large','description':'1 cup','grams':160}]}}
        self.proof={'complete':True,'identity_records_sha256':fingerprint(self.identities)}

    def test_all_legal_options_without_query_nutrition_or_size(self):
        labels={'asa':{'food_code':'12345678','truth':{'weight':999999,'energy':88888},
                       'size':'secret-current-size','option_id':'secret-current-option'}}
        codes=code_only(labels,self.rows)
        result=contexts_after_seal(self.rows,self.identities,self.catalog,codes,self.proof)
        self.assertEqual(set(result['asa']),{'code','options'})
        self.assertEqual(len(result['asa']['options']),2)
        self.assertNotIn('n5',result)
        self.assertNotIn('999999',str(result))
        self.assertNotIn('secret-current',str(result))

    def test_incomplete_or_changed_coding_refuses_before_context(self):
        for proof in ({},{'complete':False,'identity_records_sha256':fingerprint(self.identities)},
                      {'complete':True,'identity_records_sha256':'changed'}):
            with self.assertRaises(ValueError):
                contexts_after_seal(self.rows,self.identities,self.catalog,{'asa':'12345678'},proof)

    def test_unmatched_truecode_never_reaches_conditional_predictor(self):
        result=contexts_after_seal(self.rows,self.identities,self.catalog,{'asa':'87654321'},self.proof)
        self.assertEqual(result,{})

    def test_N5_cannot_receive_truecode_adapter(self):
        with self.assertRaises(ValueError):
            contexts_after_seal(self.rows,self.identities,self.catalog,
                                {'asa':'12345678','n5':'23456789'},self.proof)


if __name__=='__main__': unittest.main()
