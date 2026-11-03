"""Synthetic fixed-count fixtures; no research data is opened."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import asa_role_sources as s
from source_census import encoded, sha


class RoleSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name)/'repo'; self.repo.mkdir()
        self.digest='a'*64
        def rows(split, asa, n5):
            out=[]
            for dataset,count in (('asa24',asa),('nutrition5k',n5)):
                for i in range(count):
                    sample=f'asa24-{10000000+i:08d}-small' if dataset=='asa24' else f'nutrition5k-dish_{i:010d}'
                    out.append(dict(sample_id=sample,dataset=dataset,split=split,
                        group_id=f'{dataset}-group-{i%23}',fold=i%23%5 if split=='dev' else None,
                        image_path=(f'data/asa24/{split}/images/image{i}.png' if dataset=='asa24'
                                    else f'data/{split}/images/dish_{i:010d}/rgb.png'),image_sha256=self.digest))
            return out
        self.dev=rows('dev',99,100); self.val=rows('validation',78,200)
        self.protocol={'source_sha256':{},'frozen_sha256':{}}
        for split,rows_ in (('dev',self.dev),('validation',self.val)):
            raw=b''.join(encoded(r).replace(b'\n',b'')+b'\n' for r in rows_)
            self.write(s.MANIFESTS[split],raw)
            self.protocol['frozen_sha256'][s.MANIFESTS[split].removeprefix(s.V1)]=sha(raw)
        self.current=[dict(r,image_path='data/asa24/dev/images/'+sha(('dietai24-mae-v2-20261102|sample|'+r['sample_id']).encode())+'.png')
                      for i,r in enumerate(self.dev[:99])]
        self.v2val=[dict(r,image_path='data/'+r['dataset']+'/validation/images/'+sha(('dietai24-mae-v2-20261102|sample|'+r['sample_id']).encode())+'.png')
                    for i,r in enumerate(self.val)]
        raw=b''.join(encoded(r).replace(b'\n',b'')+b'\n' for r in self.v2val)
        self.write(s.VALIDATION,raw)
        self.seal={'artifacts':{s.VALIDATION.removeprefix(s.PREFIX):sha(raw),
                    **{r['image_path']:r['image_sha256'] for r in self.v2val}}}
        self.write(s.PATHS['validation_seal'],encoded(self.seal)); self.valpin=sha(encoded(self.seal))
        for path in s.HISTORY:
            raw=b'FoodCode,Image,Weight\n10000000,image0.png,POISON\n'
            self.write(path,raw); self.protocol['source_sha256'][path]=sha(raw)
        self.legacy={'sources':[],'private_identities':[]}
        for path in s.LEGACY_MANIFESTS:
            raw=b'dataset,image_path\nasa24,unused.png\n'
            self.write(path,raw,self.repo.parent)
            self.legacy['sources'].append({'path':path,'sha256':sha(raw)})
        self.census={'status':'path_census_complete_not_exposure_closure','entries':[]}
        self.persist()

    def write(self,path,raw,root=None):
        target=(root or self.repo)/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw)

    def persist(self):
        raw=encoded(self.protocol); self.write(s.V1_PROTOCOL,raw)
        self.capture={'source_sha256':{s.V1_PROTOCOL:sha(raw)}}
        raw=encoded(self.census); self.write(s.CENSUS,raw); self.censuspin=sha(raw)

    def load(self):
        return s._load_at(self.repo,self.capture,{'asa_rows':self.current},self.legacy,
                          census_sha=self.censuspin,validation_sha=self.valpin)

    def test_counts_poison_and_renames(self):
        result=self.load()
        self.assertEqual(len(result['roleanchors']['core']['codes']),99)
        self.assertEqual(len(result['roleanchors']['validation']['codes']),78)
        self.assertFalse(result['role_inventory_complete'])
        self.assertEqual(result['unknowncounts']['unresolved_source_pins'],4)
        self.assertEqual(result['originalmanifestbinding']['core'],self.dev[:99])

    def test_csv_code_normalization_is_exact_and_never_truncates(self):
        for value in ('11111111', '11111111.0', '1.1111111e7'):
            self.assertEqual(s.source_code(value), '11111111')
        for value in ('11111111.5', 'NaN', 'Infinity', '1e9999999', '1111111', ' 11111111', ''):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError,'exact_history_food_code'):
                s.source_code(value)

    def test_v1_n5_writer_grammar_required(self):
        self.dev[99]['image_path']='data/nutrition5k/dev/images/image0.png'
        raw=b''.join(encoded(r).replace(b'\n',b'')+b'\n' for r in self.dev)
        self.write(s.MANIFESTS['dev'],raw)
        self.protocol['frozen_sha256'][s.MANIFESTS['dev'].removeprefix(s.V1)]=sha(raw)
        self.persist()
        with self.assertRaisesRegex(ValueError,'image_binding'):self.load()

    def test_v2_unhashed_image_path_refused(self):
        self.v2val[0]['image_path']='data/asa24/validation/images/arbitrary.png'
        raw=b''.join(encoded(r).replace(b'\n',b'')+b'\n' for r in self.v2val)
        self.write(s.VALIDATION,raw)
        self.seal['artifacts'][s.VALIDATION.removeprefix(s.PREFIX)]=sha(raw)
        self.write(s.PATHS['validation_seal'],encoded(self.seal));self.valpin=sha(encoded(self.seal))
        with self.assertRaisesRegex(ValueError,'image_binding'):self.load()

    def test_tampered_seal_refused(self):
        self.write(s.PATHS['validation_seal'],b'{}')
        with self.assertRaisesRegex(ValueError,'hash_changed'):self.load()

    def test_changed_identity_refused(self):
        self.current[0]['fold']=4
        with self.assertRaisesRegex(ValueError,'identity_changed'):self.load()

    def test_unregistered_inventory_never_followed(self):
        self.protocol['frozen_sha256']['../../secret']='b'*64
        self.seal['artifacts']['../../secret']='b'*64
        self.write(s.PATHS['validation_seal'],encoded(self.seal)); self.valpin=sha(encoded(self.seal));self.persist()
        original=s.bounded_read; opened=[]
        def read(root,path):opened.append(path);return original(root,path)
        with patch.object(s,'bounded_read',side_effect=read):self.load()
        self.assertNotIn('../../secret',opened)

    def test_finite_runs_missing_old_pin_explicit(self):
        path='runs/probe/asa24_food_codes.csv'
        self.write(path,b'FoodCode,Image\n10000001,probe.png\n')
        self.census['entries']=[{'path':path,'kind':'file'}];self.persist()
        result=self.load()
        self.assertIn(('10000001','probe.png'),result['historical_pairs'])
        self.assertEqual(result['unknowncounts']['unresolved_source_pins'],5)

    def test_source_mutation_during_capture_refused(self):
        original=s.bounded_read; seen={}
        def read(root,path):
            raw=original(root,path); seen[path]=seen.get(path,0)+1
            if path==s.HISTORY[0] and seen[path]>1:return raw+b'changed'
            return raw
        with patch.object(s,'bounded_read',side_effect=read):
            with self.assertRaisesRegex(ValueError,'during_capture'):self.load()

    def test_extra_identity_field_refused(self):
        self.dev[0]['weight']='POISON'
        raw=b''.join(encoded(r).replace(b'\n',b'')+b'\n' for r in self.dev)
        self.write(s.MANIFESTS['dev'],raw)
        self.protocol['frozen_sha256'][s.MANIFESTS['dev'].removeprefix(s.V1)]=sha(raw)
        self.persist()
        with self.assertRaisesRegex(ValueError,'identity_only'):self.load()

    def test_same_identity_different_bytes_refused(self):
        self.current[0]['image_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'identity_changed'):self.load()

    def test_duplicate_current_refused(self):
        self.current[-1]=self.current[0]
        with self.assertRaises(ValueError):self.load()


if __name__=='__main__':unittest.main()
