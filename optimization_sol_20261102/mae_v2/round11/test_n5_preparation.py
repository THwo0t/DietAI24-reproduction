from copy import deepcopy
import csv
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from n5_preparation import raw_scans,official_rgb_sizes,inspect_pool
from n5_identity import screening_closure
from cohorts_v2 import build_components,parse_metadata


def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def csv_bytes(rows):
    stream=io.StringIO();csv.writer(stream).writerows(rows)
    return stream.getvalue().encode()


class BlindN5PreparationTests(unittest.TestCase):
    def setUp(self):
        self.ids={name:f'dish_{1000000000+i:010d}' for i,name in enumerate(
            ('history','core','val','retired','train','a','b','c'))}
        raw=[];available=[['dish_id','total_mass','total_calories','total_fat','total_carbs','total_protein']]
        for i,(name,dish) in enumerate(self.ids.items()):
            row=[dish]+['PROTECTED_TARGET_MUST_NOT_PARSE']*5
            if i==0:row+=['1']
            row += [f'ingr_{i:010d}','synthetic-'+name,str(i+1),'1','1','1','1']
            raw.append(row)
            available.append([dish]+(['100','120','2','15','6'] if name in ('a','b','c')
                                     else ['PROTECTED_TARGET_MUST_NOT_PARSE']*5))
        tables={'cafe1':csv_bytes(raw),'cafe2':b'','available':csv_bytes(available)}
        scans=raw_scans(tables)
        pixels=[{'dish_id':self.ids[name],'bytes_sha256':digest('bytes-'+name),
                 'rgb_sha256':digest('rgb-'+name)} for name in ('history','core','val','retired')]
        mapping,quarantine,_,members=build_components(scans,pixels)
        recipes={dish:scan.recipe_hash for dish,scan in scans.items()}
        screening=screening_closure(mapping,recipes,pixels)
        self.projection={'raw_tables':tables,'index':{'original_components':mapping,
            'recipe_sha256':recipes,'screening_components':screening,'known_image_fingerprints':pixels,
            'blocked_screening_components':[screening[self.ids[name]]
                for name in ('history','core','val','retired')]},
            'snapshot':{'component_members':members,'ambiguous_component_ids':list(quarantine),
                'active_development_ids':[self.ids['core']],'historical_exposure_ids':[self.ids['history']]},
            'cohort_proposal':{'selected_dish_ids':[self.ids['val']],
                'original_development_exposure_ids':[self.ids['core'],self.ids['retired']],
                'retired_validation_dish_ids':[]},
            'registry':{'exposed_dish_ids':[self.ids['history']],'local_dish_ids':[],
                        'exposed_ingredient_group_sha256':[]},
            'train_entries':[{'dish_id':self.ids['train']}],
            'train_pixels':[{'dish_id':self.ids['train'],'bytes_sha256':digest('bytes-train'),
                             'rgb_sha256':digest('rgb-train')}],
            'official_objects':[{'name':'nutrition5k_dataset/imagery/realsense_overhead/'+dish+'/rgb.png',
                                 'size':'300000'} for dish in self.ids.values()],
            'source_hashes':{str(i):'0'*64 for i in range(15)}}
        self.counts={'core':1,'validation':1,'original_development':2,'training':1}

    def inspect(self):return inspect_pool(self.projection,expected_counts=self.counts)

    def test_in_memory_parser_matches_original_complete_variable_width_and_declared_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            paths=[]
            for slot in ('cafe1','cafe2'):
                path=Path(directory)/('dish_metadata_'+slot+'.csv')
                path.write_bytes(self.projection['raw_tables'][slot]);paths.append(path)
            self.assertEqual(raw_scans(self.projection['raw_tables']),parse_metadata(paths))

    def test_all_protected_targets_remain_poison_and_only_unblocked_candidates_get_truths(self):
        private,aggregate=self.inspect()
        self.assertEqual(set(private['candidates']),{self.ids[n] for n in ('a','b','c')})
        self.assertEqual(set(private['truths']),set(private['candidates']))
        self.assertEqual(aggregate['eligible_images'],3)
        self.assertEqual(aggregate['new_samples_selected'],0)
        self.assertFalse(aggregate['latest_exposure_completeness_proven'])
        self.assertNotIn('PROTECTED_TARGET',str(aggregate))
        self.assertFalse(any(dish in str(aggregate) for dish in self.ids.values()))

    def test_unblocked_invalid_targets_refuse_individual_zero_is_valid_and_all_zero_is_excluded(self):
        before=self.projection['raw_tables']['available']
        self.projection['raw_tables']['available']=before.replace(b',100,120,2,15,6',b',100,120,0,15,6')
        private,_=self.inspect();self.assertEqual(len(private['candidates']),3)
        self.projection['raw_tables']['available']=before.replace(b',100,120,2,15,6',b',100,0,0,0,0')
        private,summary=self.inspect();self.assertFalse(private['candidates'])
        self.assertEqual(summary['unblocked_missing_nutrition_exclusions'],3)
        self.projection['raw_tables']['available']=before.replace(b',100,120,2,15,6',b',100,NaN,2,15,6')
        with self.assertRaisesRegex(ValueError,'finite_complete_positive_candidate'):self.inspect()

    def test_validation_pixel_bridge_stops_before_any_unblocked_target_parse(self):
        self.projection['train_pixels'][0]['rgb_sha256']=digest('rgb-val')
        raw=self.projection['raw_tables']['available']
        self.projection['raw_tables']['available']=raw.replace(b',100,120,2,15,6',b',POISON,POISON,POISON,POISON,POISON')
        with self.assertRaisesRegex(ValueError,'validation_linkage_requires_separate_resolution'):
            self.inspect()

    def test_official_listing_mismatch_duplicate_and_size_bounds_refuse_without_network(self):
        before=deepcopy(self.projection['official_objects'])
        self.projection['official_objects']=before[:-1]
        with self.assertRaisesRegex(ValueError,'available_identity_changed'):self.inspect()
        with self.assertRaisesRegex(ValueError,'unique_official_rgb_object'):
            official_rgb_sizes(before+[before[0]])
        invalid=deepcopy(before);invalid[0]['size']='5000001'
        with self.assertRaisesRegex(ValueError,'outside_bound'):official_rgb_sizes(invalid)

    def test_original_deduplicated_frame_and_raw_structure_cannot_be_relaxed(self):
        before=self.projection['raw_tables']['available']
        lines=before.decode().splitlines()
        self.projection['raw_tables']['available']=('\n'.join(lines+[lines[-1]])+'\n').encode()
        with self.assertRaisesRegex(ValueError,'available_identity_changed'):self.inspect()
        malformed=deepcopy(self.projection['raw_tables'])
        malformed['cafe1']=malformed['cafe1'].replace(b',1,ingr_',b',2,ingr_',1)
        with self.assertRaisesRegex(ValueError,'ingredient_count_mismatch'):raw_scans(malformed)


if __name__=='__main__':unittest.main()
