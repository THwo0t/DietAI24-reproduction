from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10'),str(BASE/'round11')]
import assets_p as a


class AssetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        foods={code:dict(description=name,category='synthetic',density=dict(energy=100,fat=2,carbs=10,protein=3))
            for code,name in [('12345678','rice'),('22345678','beans')]}
        self.base=dict(foods=foods,standard_options={'12345678':[dict(option_id='standard',description='unit',grams=50)]},
            asa_options={'12345678':[dict(option_id='old-small',description='small',grams=20),
                                     dict(option_id='old-large',description='large',grams=100)]},
            provenance={'unchanged':'generic corpus'})
        self.new=deepcopy(self.base);self.new['asa_options']['22345678']=[dict(option_id='broad-small',description='small',grams=30),
            dict(option_id='broad-medium',description='medium',grams=60),dict(option_id='broad-large',description='large',grams=90)]
        self.write(a.BASE_CATALOG,self.base);self.write(a.P_CATALOG,self.new)
        self.write('data/vectors/codes.json',['12345678','22345678']);self.write('data/vectors/collection.json',{'synthetic':True})
        self.matrix(np.array([[1,2,3],[4,5,6]],dtype=np.float32));self.manifest()
    def write(self,path,value):
        file=self.root/path;file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(value if type(value) is bytes else json.dumps(value,sort_keys=True).encode())
    def matrix(self,matrix):
        data=io.BytesIO();np.save(data,matrix,allow_pickle=False);self.write(a.VECTOR_PATH,data.getvalue())
    def sha(self,path):return hashlib.sha256((self.root/path).read_bytes()).hexdigest()
    def manifest(self):
        self.description=dict(vectors=2,dimensions=3,api_calls=0,embedding_model='text-embedding-3-large',
            files={name:self.sha('data/vectors/'+name) for name in ('embeddings.npy','codes.json','collection.json')})
        self.write(a.VECTOR_MANIFEST,self.description)
    def load(self):return a._assets(self.root,vectors=2,dimensions=3)

    def test_new_ASA_options_use_new_catalog_and_unchanged_readonly_vectors(self):
        catalog,retriever=self.load()
        self.assertEqual(catalog,self.new);self.assertIn('22345678',catalog['asa_options'])
        self.assertEqual(catalog['asa_options']['12345678'],self.base['asa_options']['12345678'])
        self.assertEqual(retriever.codes,['12345678','22345678']);self.assertFalse(retriever.vectors.flags.writeable)
        self.assertEqual(retriever.dense([1,2,3],k=1),['12345678'])
        self.assertEqual(json.loads((self.root/a.BASE_CATALOG).read_text()),self.base)

    def test_food_density_description_category_standard_and_topkeys_immutable(self):
        for kind in ('density','description','category','standard','topkey','boolnumeric'):
            new=deepcopy(self.new)
            if kind=='density':new['foods']['12345678']['density']['fat']=3
            elif kind=='description':new['foods']['12345678']['description']='changed'
            elif kind=='category':new['foods']['12345678']['category']='changed'
            elif kind=='standard':new['standard_options']['12345678'][0]['grams']=60
            elif kind=='topkey':new['new_key']='unregistered'
            else:new['foods']['12345678']['density']['fat']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):a.catalog_extension(self.base,new)

    def test_old_options_cannot_change_or_disappear_and_new_options_must_be_legal(self):
        for kind in ('id','desc','grams','remove','reorder','truncate','duplicatepair','unknowncode','duplicate','nan','extra'):
            new=deepcopy(self.new)
            if kind=='id':new['asa_options']['12345678'][0]['option_id']='newid'
            elif kind=='desc':new['asa_options']['12345678'][0]['description']='different'
            elif kind=='grams':new['asa_options']['12345678'][0]['grams']=21
            elif kind=='remove':new['asa_options'].pop('12345678')
            elif kind=='reorder':new['asa_options']['12345678'].reverse()
            elif kind=='truncate':new['asa_options']['12345678'].pop()
            elif kind=='duplicatepair':new['asa_options']['12345678'].append(dict(option_id='newid',description='small',grams=20))
            elif kind=='unknowncode':new['asa_options']['99999999']=new['asa_options']['22345678']
            elif kind=='duplicate':new['asa_options']['22345678']*=2
            elif kind=='nan':new['asa_options']['22345678'][0]['grams']=float('nan')
            else:new['asa_options']['22345678'][0]['target_size']='small'
            with self.subTest(kind=kind),self.assertRaises(ValueError):a.catalog_extension(self.base,new)

    def test_new_legal_entries_can_append_to_exact_old_prefix(self):
        new=deepcopy(self.new)
        new['asa_options']['12345678'].append(dict(option_id='appended-medium',description='medium',grams=60))
        self.write(a.P_CATALOG,new);catalog,_=self.load()
        self.assertEqual(catalog['asa_options']['12345678'][:2],self.base['asa_options']['12345678'])
        self.assertEqual(catalog['asa_options']['12345678'][2]['grams'],60)

    def test_manifest_model_dimension_counts_and_unregistered_files_rejected(self):
        for kind in ('model','dimensions','vectors','api_calls','traversal','missing'):
            description=deepcopy(self.description)
            if kind=='model':description['embedding_model']='wrong'
            elif kind in ('dimensions','vectors','api_calls'):description[kind]=9
            elif kind=='traversal':description['files']['../labels.json']='a'*64
            else:description['files'].pop('codes.json')
            self.write(a.VECTOR_MANIFEST,description)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.load()

    def test_vector_hash_code_join_shape_dtype_and_nonfinite_rejected(self):
        self.write('data/vectors/codes.json',['12345678','12345678'])
        with self.assertRaisesRegex(ValueError,'hash_changed'):self.load()
        self.manifest()
        with self.assertRaisesRegex(ValueError,'code_join'):self.load()
        self.write('data/vectors/codes.json',['12345678','22345678'])
        for matrix in (np.zeros((3,3),np.float32),np.zeros((2,3),np.float64),np.array([[1,2,3],[4,np.nan,6]],np.float32)):
            self.matrix(matrix);self.manifest()
            with self.assertRaises(ValueError):self.load()

    def test_symlink_and_trailing_payload_rejected(self):
        path=self.root/a.P_CATALOG;path.unlink();path.symlink_to(self.root/a.BASE_CATALOG)
        with self.assertRaises(OSError):self.load()
        path.unlink();self.write(a.P_CATALOG,self.new)
        self.write(a.VECTOR_PATH,(self.root/a.VECTOR_PATH).read_bytes()+b'trailing');self.manifest()
        with self.assertRaisesRegex(ValueError,'payload_size'):self.load()

    def test_small_npy_forged_massive_shape_rejected_before_array_load(self):
        data=io.BytesIO();np.lib.format.write_array_header_1_0(data,{'descr':'<f4','fortran_order':False,'shape':(10**9,3)})
        self.write(a.VECTOR_PATH,data.getvalue());self.manifest()
        with self.assertRaisesRegex(ValueError,'shape_dtype_or_order'):self.load()

if __name__=='__main__':unittest.main()
