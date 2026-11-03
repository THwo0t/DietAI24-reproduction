from copy import deepcopy
from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest

from asa_eligibility import legal_rows


class ASALegalPortionTests(unittest.TestCase):
    def setUp(self):
        self.code='11111111';self.val='22222222'
        self.metadata=[];self.inventory=[];self.hashes={}
        for i in range(1,5):
            image=f'synthetic{i}.png'
            self.inventory.append({'FileName':image,'Portion':f'synthetic portion{i}'})
            self.hashes[image]=str(i)*64
            for pc,multiplier in ((1,i),(98,i*10)):
                self.metadata.append({'FoodCode':self.code,'Image':image,'ImageType':'PORTION',
                    'ModCode':0,'PortionCode':pc,'Multiplier':multiplier})
        self.units=[{'Food Code':self.code,'Portion Code':1,'Portion Weight':10}]

    def legal(self,**kwargs):
        return legal_rows(self.metadata,self.inventory,self.units,permitted_codes={self.code},
            fndds_codes={self.code},top_codes={self.code},image_hashes=self.hashes,**kwargs)

    def test_standard_mapping_gram98_dominant_code_and_all_legal_portions(self):
        private,summary=self.legal();rows=private['rows']
        self.assertEqual([r['Weight'] for r in rows],[Decimal(10),Decimal(20),Decimal(30),Decimal(40)])
        self.assertEqual({r['PortionCode'] for r in rows},{1})
        self.assertEqual(summary['eligible_portion_rows'],4)
        self.assertFalse(summary['external_identity_isolation_proven'])
        self.units=[]
        private,_=self.legal()
        self.assertEqual({r['PortionCode'] for r in private['rows']},{98})

    def test_valid_original_frame_matches_original_project_mapping_and_series_selection(self):
        import pandas as pd
        path=Path(__file__).resolve().parents[3]/'code/asa24_proc.py'
        spec=importlib.util.spec_from_file_location('synthetic_asa_original',path)
        original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
        frame=pd.DataFrame(self.metadata)
        descriptions={r['FileName']:r['Portion'] for r in self.inventory}
        frame['Portion']=frame['Image'].map(descriptions)
        frame['FC_Description']='synthetic food';frame['Category']='synthetic'
        frame['PortionSubCode']=0
        weighted=original.add_weights(frame,pd.DataFrame(self.units))
        old=original.select_image_links(weighted,{self.code},{self.code}).to_dict('records')
        current,_=self.legal()
        shape=lambda rows:[(r['FoodCode'],r['Image'],r['Portion'],int(r['PortionCode']),Decimal(str(r['Weight']))) for r in rows]
        self.assertEqual(shape(current['rows']),shape(old))

    def test_protected_code_numbers_are_not_interpreted(self):
        self.metadata.append({'FoodCode':self.val,'Image':'protected.png','ImageType':'PORTION',
            'ModCode':'POISON','PortionCode':'POISON','Multiplier':'POISON'})
        self.units.append({'Food Code':self.val,'Portion Code':'POISON','Portion Weight':'POISON'})
        private,_=self.legal();self.assertEqual(len(private['rows']),4)

    def test_broader_frame_changes_only_the_rank_membership_filter(self):
        args=dict(permitted_codes={self.code},fndds_codes={self.code},top_codes=set(),image_hashes=self.hashes)
        private,_=legal_rows(self.metadata,self.inventory,self.units,**args)
        self.assertFalse(private['rows'])
        private,_=legal_rows(self.metadata,self.inventory,self.units,broader_frame=True,**args)
        self.assertEqual(len(private['rows']),4)
        args['fndds_codes']=set()
        private,_=legal_rows(self.metadata,self.inventory,self.units,broader_frame=True,**args)
        self.assertFalse(private['rows'])

    def test_filename_and_same_byte_weight_conflicts_are_explicit_before_selection(self):
        self.metadata[0]['Multiplier']=Decimal('1.02')
        private,summary=self.legal()
        self.assertIn((self.code,'synthetic1.png'),private['ambiguous_code_images'])
        self.assertEqual(summary['eligible_portion_rows'],3)
        self.metadata[0]['Multiplier']=1
        self.hashes['synthetic2.png']=self.hashes['synthetic1.png']
        private,summary=self.legal()
        self.assertEqual(len(private['ambiguous_code_images']),2)
        self.assertFalse(private['rows'])

    def test_one_percent_boundary_is_exact_and_illegal_numeric_or_conflicting_units_refuse(self):
        self.metadata[0]['Multiplier']=Decimal('1.01')
        private,_=self.legal();self.assertFalse(private['ambiguous_code_images'])
        self.metadata[0]['Multiplier']='NaN'
        with self.assertRaisesRegex(ValueError,'nonfinite'):self.legal()
        self.metadata[0]['Multiplier']=1
        self.units.append({'Food Code':self.code,'Portion Code':1,'Portion Weight':11})
        with self.assertRaisesRegex(ValueError,'conflicting_exact_food_weight'):self.legal()
        self.units[-1]['Portion Weight']=-1
        with self.assertRaisesRegex(ValueError,'negative_exact_food_weight'):self.legal()

    def test_zero_positive_source_conflicts_refuse_both_orders_identical_and_zero_only_are_preserved(self):
        for values in ((0,10),(10,0)):
            with self.subTest(values=values):
                self.units=[{'Food Code':self.code,'Portion Code':1,'Portion Weight':value}
                            for value in values]
                with self.assertRaisesRegex(ValueError,'conflicting_exact_food_weight'):self.legal()
        self.units=[{'Food Code':self.code,'Portion Code':1,'Portion Weight':10}]*2
        private,_=self.legal()
        self.assertEqual(len(private['rows']),4)
        self.assertEqual({row['PortionCode'] for row in private['rows']},{1})
        self.units=[{'Food Code':self.code,'Portion Code':1,'Portion Weight':0}]*2
        private,_=self.legal()
        self.assertEqual({row['PortionCode'] for row in private['rows']},{98})
        self.metadata=[row for row in self.metadata if row['PortionCode']!=98]
        private,_=self.legal();self.assertFalse(private['rows'])

    def test_ambiguous_portion_text_and_too_few_weight_levels_are_not_relaxed(self):
        self.inventory[1]['Portion']=self.inventory[0]['Portion']
        private,summary=self.legal();self.assertFalse(private['rows'])
        self.assertEqual(summary['excluded']['portion_text_has_multiple_weights'],1)
        self.inventory[1]['Portion']='synthetic portion2'
        self.inventory[3]['Portion']=None
        private,_=self.legal();self.assertEqual(len(private['rows']),3)
        self.metadata=self.metadata[:4]
        private,summary=self.legal();self.assertFalse(private['rows'])
        self.assertEqual(summary['excluded']['fewer_than_three_distinct_weights'],1)


if __name__=='__main__':unittest.main()
