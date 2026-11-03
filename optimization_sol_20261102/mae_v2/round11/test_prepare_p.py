"""Synthetic-only preparation producer; no production identity reader invoked."""
from copy import deepcopy
import hashlib
from io import BytesIO
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE/'round11')]
from PIL import Image
import prepare_p as p


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.loaded=0;self.review_reads=[];self.image_calls=0
        self.catalog={'foods':{'12345678':{'description':'synthetic rice','density':{'energy':100,'fat':1,'carbs':20,'protein':3}},
            '12345679':{'description':'synthetic beans','density':{'energy':110,'fat':2,'carbs':19,'protein':4}}},
            'standard_options':{},'asa_options':{'12345678':[{'option_id':'a1','description':'one cup','grams':100}]}}
        self.pins={};self.required={p.PREFIX+'fixture-source.py'}
        self.put(p.PREFIX+'fixture-source.py',b'synthetic source binding\n')
        self.put(p.PREFIX+'data/catalog.json',p.encoded(self.catalog))
        self.put(p.PREFIX+'data/vectors/manifest.json',p.encoded({'files':{}}))
        self.put(p.PREFIX+'data/vectors/codes.json',p.encoded(['12345678','12345679']))
        self.put(p.PREFIX+p.VECTOR,b'synthetic-vector-digest-only')
        self.put(p.PREFIX+'data/vectors/manifest.json',p.encoded({'files':{
            'codes.json':self.pins[p.PREFIX+'data/vectors/codes.json'],
            'embeddings.npy':self.pins[p.PREFIX+p.VECTOR]}}))
        self.required|={p.PREFIX+x for x in ('data/catalog.json','data/vectors/manifest.json','data/vectors/codes.json',p.VECTOR)}
        self.receipts={p.PREFIX+'fixture-receipt.json':p.sha(b'{}\n')};self.put(next(iter(self.receipts)),b'{}\n')
        self.put(p.REVIEW_TEXT,b'Synthetic reviewed preparation source evidence.\n')
        self.records=[];self.sourceimages={};self.labels={}
        for ds in ('asa24','nutrition5k'):
            for f in range(5):
                sid=('asa24-12345678-original'+str(f) if ds=='asa24' else 'nutrition5k-dish_'+str(f).zfill(10))
                buffer=BytesIO();Image.new('RGB',(8,8),(f*20,20 if ds=='asa24' else 40,80)).save(buffer,format='PNG');raw=buffer.getvalue()
                relative=p.PREFIX+'data/'+ds+'/dev/images/'+p.sha(raw)+'.png'
                self.put(relative,raw);self.sourceimages[relative]=raw
                label={'truth':{'weight':float(10+f),'energy':float(100+f),'fat':2.,'carbs':20.,'protein':4.}}
                if ds=='asa24':label.update(food_code='12345678',size='largest')
                row=dict(sample_id=sid,dataset=ds,split='dev',group_id=ds+'-g'+str(f),fold=f,
                         image_path='source-only.png',image_sha256=p.sha(raw))
                self.records.append(dict(row=row,label=label,stratum='asa_core99' if ds=='asa24' else 'core84',
                    source_image={'kind':'fixed_development_or_support','path':relative,'sha256':p.sha(raw)},association_group_id=row['group_id']))
                self.labels[sid]=label
        self.devlabels=p.PREFIX+'data/cohorts/dev_labels.json';self.put(self.devlabels,p.encoded(self.labels))
        self.protected=p.PREFIX+'data/cohorts/sealed/validation_labels.json';self.put(self.protected,b'PROTECTED_POISON_NOT_JSON')
        self.gate={'status':'approved_or_fixed','scope':'P_capacity_v4_preparation','unresolved_p1_p2':0,
            'review_sha256':self.pins[p.REVIEW_TEXT],'source_files':{x:self.pins[x] for x in self.required},
            'receipt_sha256':self.receipts}
        self.put(p.REVIEW,p.encoded(self.gate))
        self.mutate=None;self.interrupt_at=None

    def put(self,path,raw):
        full=self.root/path;full.parent.mkdir(parents=True,exist_ok=True);full.write_bytes(raw);self.pins[path]=p.sha(raw)

    def loader(self,repo,reader):
        self.loaded+=1
        reader.bind(self.devlabels,self.pins[self.devlabels]);labels=p.decode(reader.read(self.devlabels))
        records=deepcopy(self.records)
        for record in records:
            record['label']=labels[record['row']['sample_id']]
            reader.bind(record['source_image']['path'],record['source_image']['sha256'])
        legal={'rows':[{'FoodCode':'12345678','Portion':'legal '+str(f),'Weight':10+f} for f in range(5)]+[
            {'FoodCode':'12345678','Portion':'one cup','Weight':100},
            {'FoodCode':'12345679','Portion':'full safe catalogue','Weight':75}]}
        catalog=p._extend_catalog(self.catalog,legal,{'12345678','12345679'})
        bundle={'records':records,'catalog':catalog,'old_catalog':deepcopy(self.catalog),
            'assets':{x.removeprefix(p.PREFIX):self.pins[x] for x in self.required if x.startswith(p.PREFIX+'data/')},
            'closure':{'original_global_guard_remains_stopped':True,'actual_api_exposure_complete':False,
                       'source_association_complete':False},
            'proposals':{'nutrition5k':{'retained_old_rows':[],'new_identity_ids':['identity-only-candidate'],
                                      'pending_boundary_confirmation':True},
                         'asa24':{'pending_boundary_confirmation':True}}}
        if self.mutate:self.mutate(bundle)
        def image(spec):
            self.image_calls+=1
            if self.interrupt_at==self.image_calls:raise RuntimeError('synthetic interrupted copy')
            return reader.read(spec['path'])
        return bundle,image,reader.revalidate

    def execute(self):return p._prepare_at(self.root,source_loader=self.loader,required=self.required,receipts=self.receipts)
    def output(self,name):return p.decode((self.root/p.PREFIX/name).read_bytes())

    def test_complete_minimal_producer_private_resume_no_old_modification(self):
        old={path:p.sha((self.root/path).read_bytes()) for path in self.pins}
        with patch('prepare_p._production_inputs',side_effect=AssertionError('actual readers forbidden')):
            first=self.execute();second=self.execute()
        self.assertEqual(first,second);self.assertEqual(first['development_rows'],10)
        self.assertFalse(first['acceptance_designated']);self.assertFalse(first['inference_authorized'])
        for path,digest in old.items():self.assertEqual(p.sha((self.root/path).read_bytes()),digest)
        prepared=self.root/p.PREPARED
        for path in prepared.rglob('*'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o700 if path.is_dir() else 0o600)
        rows=self.output(p.ROLES['manifest']);self.assertTrue(all(set(r)==p.ROW_FIELDS and r['image_path'].startswith('round11/prepared/cohort/images/dev/') for r in rows))
        newcat=self.output(p.CATALOG);self.assertIn('12345679',newcat['asa_options']);self.assertEqual(newcat['asa_options']['12345678'][:1],self.catalog['asa_options']['12345678'])
        self.assertEqual({o['grams'] for o in newcat['asa_options']['12345678']},{100.,10.,11.,12.,13.,14.})
        self.assertFalse((self.root/p.PREFIX/'round11/prepared/freeze.json').exists())

    def test_review_before_any_labels_or_candidate_loader(self):
        for field,value in [('status','pending'),('scope','other'),('unresolved_p1_p2',1)]:
            gate=deepcopy(self.gate);gate[field]=value;self.put(p.REVIEW,p.encoded(gate))
            with self.subTest(field=field),self.assertRaises(ValueError):self.execute()
            self.assertEqual(self.loaded,0)
        self.put(p.REVIEW,p.encoded(self.gate));(self.root/next(iter(self.required))).write_bytes(b'drift')
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(self.loaded,0)

    def test_protected_label_poison_never_opened(self):
        original=p.bounded_read
        def guarded(root,path):
            if str(path)==self.protected:raise AssertionError('protected label opened')
            return original(root,path)
        with patch('prepare_p.bounded_read',guarded):self.execute()
        self.assertEqual((self.root/self.protected).read_bytes(),b'PROTECTED_POISON_NOT_JSON')

    def test_fold_local_fallback_excludes_query_group(self):
        self.execute();bundle=self.output(p.ROLES['fallbacks']);labels=self.output(p.ROLES['labels'])
        for ds in ('asa24','nutrition5k'):
            proof=bundle['folds'][ds]['0']
            self.assertFalse(set(proof['train_groups'])&set(proof['heldout_groups']))
            self.assertEqual(proof['value']['weight'],12.5)
            self.assertTrue(all(labels[sid]['truth']['weight']!=10 for sid in proof['train_ids']))
        calibration=self.output(p.ROLES['calibration'])
        self.assertTrue(all(not v['value']['enabled'] and set(v['value']['multipliers'].values())=={1}
            for ds in calibration['folds'].values() for v in ds.values()))

    def test_identity_fold_protected_source_and_missing_body_refuse(self):
        cases=[lambda b:b['records'][0]['row'].update(sample_id='bad'),
            lambda b:b['records'][1]['row'].update(group_id=b['records'][0]['row']['group_id']),
            lambda b:b['records'][0]['source_image'].update(path=self.protected),
            lambda b:b['records'][0]['source_image'].update(sha256='0'*64)]
        for change in cases:
            self.mutate=change
            with self.subTest(change=change),self.assertRaises((ValueError,OSError)):self.execute()
        self.mutate=None;(self.root/self.records[-1]['source_image']['path']).unlink()
        with self.assertRaises(FileNotFoundError):self.execute()
        self.assertFalse((self.root/p.PREFIX/'round11/prepared/common.json').exists())

    def test_link_and_interrupted_resume_and_changed_output_refuse(self):
        imagepath=self.root/self.records[0]['source_image']['path'];raw=imagepath.read_bytes()
        other=self.root/'fixture-image-copy';other.write_bytes(raw);imagepath.unlink();imagepath.symlink_to(other)
        with self.assertRaises((ValueError,OSError)):self.execute()
        imagepath.unlink();imagepath.write_bytes(raw)
        self.interrupt_at=self.image_calls+3
        with self.assertRaises(RuntimeError):self.execute()
        self.interrupt_at=None;self.execute()
        common=self.root/p.PREFIX/'round11/prepared/common.json';common.write_bytes(common.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'existing_prepared_file_changed'):self.execute()

    def test_candidate_filter_does_not_parse_protected_totals_and_is_deterministic(self):
        raw={'cafe1':b'dish_protected,POISON,POISON,POISON,POISON,POISON\ndish_new,10,20,1,2,3\n','cafe2':b''}
        self.assertEqual(p._eligible_raw(raw,{'dish_new'},{'dish_new':30}),{'dish_new'})
        self.assertEqual(p._eligible_raw(raw,{'dish_new'},{'dish_new':30}),{'dish_new'})
        raw['cafe1']=b'dish_new,POISON,20,1,2,3\n'
        with self.assertRaises(ValueError):p._eligible_raw(raw,{'dish_new'},{'dish_new':30})

    def test_complete_legal_catalogue_appends_old_prefix_before_selection(self):
        legal={'rows':[
            {'FoodCode':'12345678','Portion':'one cup','Weight':100},
            {'FoodCode':'12345678','Portion':'two cups','Weight':200},
            {'FoodCode':'12345678','Portion':'two cups','Weight':200},
            {'FoodCode':'12345679','Portion':'unselected safe option','Weight':75},
            {'FoodCode':'12345679','Portion':'another unselected safe option','Weight':125}]}
        before=deepcopy(self.catalog)
        first=p._extend_catalog(self.catalog,legal,{'12345678','12345679'})
        second=p._extend_catalog(self.catalog,{'rows':list(reversed(legal['rows']))},{'12345679','12345678'})
        self.assertEqual(first,second);self.assertEqual(self.catalog,before)
        self.assertEqual(first['asa_options']['12345678'][:1],before['asa_options']['12345678'])
        self.assertEqual(len(first['asa_options']['12345678']),2)
        self.assertEqual(len(first['asa_options']['12345679']),2)
        self.assertEqual(p._extend_catalog(first,legal,{'12345678','12345679'}),first)
        for changed in ('prefix','duplicate','density'):
            modified=deepcopy(first)
            if changed=='prefix':modified['asa_options']['12345678'][0]['option_id']='changed'
            if changed=='duplicate':modified['asa_options']['12345678'].append(dict(option_id='another-id',description='one cup',grams=100))
            if changed=='density':modified['foods']['12345678']['density']['fat']=99
            with self.subTest(changed=changed),self.assertRaises(ValueError):p._catalog_prefix(before,modified)

    def test_ASA_development_mass_must_be_a_full_catalogue_legal_value(self):
        def change(bundle):bundle['records'][0]['label']['truth']['weight']=987654.
        self.mutate=change
        with self.assertRaisesRegex(ValueError,'truth_not_in_complete_legal_catalogue'):self.execute()
        self.assertFalse((self.root/p.PREFIX/'round11/prepared/common.json').exists())

    def test_capacity_round_robin_proposal_is_identity_only_and_deterministic(self):
        from capacity_cohort_v4 import _acceptance
        oldids=['dish_'+str(i+100).zfill(10) for i in range(3)]
        newids=['dish_'+str(i+200).zfill(10) for i in range(6)]
        old=[dict(sample_id='nutrition5k-'+d,dataset='nutrition5k',split='validation',fold=None,
                  group_id='old-'+d,image_path='sealed-identity-path/'+d+'.png',image_sha256='a'*64) for d in oldids]
        mapping={d:'legacy-'+str(i) for i,d in enumerate(oldids)}
        mapping.update({d:'fresh-'+str(i%2) for i,d in enumerate(newids)})
        protected={role:{'dish_ids':[],'recipe_hashes':[]} for role in
            ('core','history','training','retired','legacy_reserved','potential_extra')}
        protected['legacy_reserved']['dish_ids']=oldids;protected['core']['dish_ids']=[oldids[0]]
        state={'mapping':mapping,'protected':protected,'quarantine':[],'allowed_ids':newids}
        first=_acceptance(old,state,newids,old_count=3,retained_expected=2,new_count=3,max_candidates=6)
        second=_acceptance(old,state,list(reversed(newids)),old_count=3,retained_expected=2,new_count=3,max_candidates=6)
        self.assertEqual(first,second);self.assertEqual(first['counts']['proposed_rows'],5)
        chosen=first['new_acceptance_dish_ids_private']
        self.assertEqual(len({mapping[d] for d in chosen[:2]}),2)
        self.assertFalse(first['new_acceptance_designated']);self.assertEqual(first['new_downloads'],0)
        self.assertTrue(all(set(row)==p.ROW_FIELDS for row in first['retained_old_rows_private']))
        self.assertNotIn('truth',str(first));self.assertEqual(old[0]['fold'],None)

    def dependency_review_fixture(self):
        # Independent literal regression set: every R-PC6-1 addition must be
        # required by production, not merely accepted through fixture overrides.
        added={p.PREFIX+name for name in (
            'round11/service_p.py','round11/asa_source_capture.py','round11/legacy_input_identity.py',
            'round11/local_content_inventory.py','round11/local_input_inventory.py','round11/n5_potential_identity.py',
            'round4/src/artifacts.py','round7/src/historical_m.py','round7/src/runtime_m.py','round7/src/service_m.py',
            'src/opt_provider.py','src/opt_pipeline.py','src/cohorts_v2.py')}
        self.assertTrue(added<=p.PREPARATION_SOURCES)
        for path in added:self.put(path,('synthetic reviewed dependency '+path).encode())
        self.required|=added
        self.gate['source_files']={path:self.pins[path] for path in self.required}
        self.put(p.REVIEW,p.encoded(self.gate))
        return sorted(added)

    def test_R_PC6_1_each_added_dependency_drift_or_missing_refuses_before_loader(self):
        paths=self.dependency_review_fixture()
        for path in paths:
            full=self.root/path;original=full.read_bytes()
            for change in ('edited','missing'):
                if change=='edited':full.write_bytes(original+b' changed since review')
                else:full.unlink()
                try:
                    with self.subTest(dependency=path,change=change),self.assertRaises((ValueError,FileNotFoundError)):
                        self.execute()
                    self.assertEqual(self.loaded,0)
                finally:full.write_bytes(original)
        self.assertFalse((self.root/p.PREFIX/'round11/prepared/common.json').exists())

    def test_R_PC6_1_each_added_dependency_final_drift_is_refused(self):
        paths=self.dependency_review_fixture();write=p._write_once
        for path in paths:
            full=self.root/path;original=full.read_bytes()
            for change in ('edited','missing'):
                changed=[False]
                def publish_then_drift(repo,relative,raw):
                    write(repo,relative,raw)
                    if relative==p.PREFIX+'round11/prepared/common.json':
                        if change=='edited':full.write_bytes(original+b' changed during preparation')
                        else:full.unlink()
                        changed[0]=True
                try:
                    with self.subTest(dependency=path,change=change),patch('prepare_p._write_once',publish_then_drift),self.assertRaises((ValueError,FileNotFoundError)):
                        self.execute()
                    self.assertTrue(changed[0])
                finally:full.write_bytes(original)
        # Recovery succeeds only after all reviewed bytes are restored; already
        # published immutable outputs are compared, never replaced or cleared.
        self.assertEqual(self.execute()['status'],'P_capacity_v4_development_prepared_acceptance_proposal_only')

    def test_large_vector_digest_only_fixed_path(self):
        path=p.PREFIX+p.VECTOR;full=self.root/path
        with full.open('wb') as stream:stream.truncate(65*1024*1024)
        h=hashlib.sha256()
        with full.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
        reader=p.BoundSources(self.root,{path:h.hexdigest()})
        with self.assertRaises(ValueError):reader.read(path)
        with patch('prepare_p.bounded_read',side_effect=AssertionError('whole large matrix forbidden')):
            self.assertEqual(reader.digest(path),h.hexdigest())

if __name__=='__main__':unittest.main()
