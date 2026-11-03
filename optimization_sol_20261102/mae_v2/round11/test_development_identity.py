"""Synthetic identity tests; no actual protected artifacts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import development_identity as d


class DevelopmentIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.rows = []
        for dataset, count in (('asa24',99), ('nutrition5k',84)):
            for n in range(count):
                sample = dataset + '-synthetic' + str(n)
                name = d._sha((d.SEED+'|sample|'+sample).encode())+'.png'
                self.rows.append(dict(sample_id=sample,dataset=dataset,split='dev',group_id='g'+str(n),
                    fold=n%5,image_path=f'data/{dataset}/dev/images/{name}',image_sha256='a'*64))
        self.seal = {'artifacts':{'data/cohorts/dev_labels.json':'b'*64}}
        self.save()

    def put(self, name, raw):
        p = self.root/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw)

    def save(self):
        raw = b'\n'.join(json.dumps(r).encode() for r in self.rows)+b'\n'
        self.put(d.MANIFEST,raw)
        self.seal['artifacts']['data/cohorts/dev.jsonl'] = d._sha(raw)
        for row in self.rows: self.seal['artifacts'].setdefault(row['image_path'],row['image_sha256'])
        raw = json.dumps(self.seal).encode(); self.put(d.SEAL,raw); self.anchor=d._sha(raw)

    def load(self): return d._load_development_identity(self.root,self.anchor)

    def test_success_poison_labels_images_and_fixed_read_inventory(self):
        (self.root/d.PREFIX/'data/cohorts/dev_labels.json').symlink_to('/nonexistent-label-poison')
        image=self.root/d.PREFIX/self.rows[0]['image_path']; image.parent.mkdir(parents=True)
        image.symlink_to('/nonexistent-image-poison')
        original=d.bounded_read; calls=[]
        def read(root,path):
            self.assertIn(path,(d.SEAL,d.MANIFEST)); calls.append(path); return original(root,path)
        with patch.object(d,'bounded_read',read):
            result,reader=self.load(); reader.revalidate()
        self.assertEqual(set(calls),{d.SEAL,d.MANIFEST})
        self.assertEqual(set(result['n5_core']),{'rows','labels_sha256'})
        self.assertEqual(len(result['n5_core']['rows']),84)
        self.assertEqual(len(result['asa_rows']),99)
        self.assertEqual(result['asa_rows'][0],self.rows[0])
        self.assertEqual(set(result['source_hashes']),{d.SEAL,d.MANIFEST})

    def test_tamper_and_revalidate(self):
        for path in (d.SEAL,d.MANIFEST):
            self.save(); _,reader=self.load(); p=self.root/path; p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaises(ValueError): reader.revalidate()
            with self.assertRaises(ValueError): self.load()

    def test_invalid_fields(self):
        original=deepcopy(self.rows)
        for fields in ({'truth':123},{'fold':True},{'fold':5},{'fold':1.0},{'fold':float('nan')},
                       {'split':'validation'},{'image_path':'../protected'}, {'image_path':'/protected'},
                       {'image_path':original[1]['image_path']},{'image_sha256':'invalid'},
                       {'group_id':''},{'dataset':[]},{'sample_id':'nutrition5k-other'}):
            with self.subTest(fields=fields):
                self.rows=deepcopy(original); self.rows[0].update(fields); self.save()
                with self.assertRaises(ValueError): self.load()

    def test_missing_duplicate_population(self):
        original=deepcopy(self.rows)
        for rows in (original[:-1],original+[original[0]], [original[0]]+original[:-1]):
            self.rows=rows; self.save()
            with self.assertRaises(ValueError): self.load()

    def test_wrong_dataset_counts(self):
        row=self.rows[0]; row['dataset']='nutrition5k'; row['sample_id']='nutrition5k-extra'
        row['image_path']='data/nutrition5k/dev/images/'+d._sha((d.SEED+'|sample|'+row['sample_id']).encode())+'.png'
        self.save()
        with self.assertRaises(ValueError): self.load()

    def test_labels_hash_not_from_other_field_and_image_binding(self):
        del self.seal['artifacts']['data/cohorts/dev_labels.json']; self.seal['labels_sha256']='b'*64
        self.save()
        with self.assertRaises(ValueError): self.load()
        self.seal['artifacts']['data/cohorts/dev_labels.json']='b'*64
        self.seal['artifacts'][self.rows[0]['image_path']]='c'*64; self.save()
        with self.assertRaises(ValueError): self.load()

    def test_links_leaf_and_ancestor(self):
        for relative in (d.SEAL,d.MANIFEST):
            self.save(); path=self.root/relative; target=self.root/'copy'; target.write_bytes(path.read_bytes())
            path.unlink(); path.symlink_to(target)
            with self.assertRaises((ValueError,OSError)): self.load()
            path.unlink()
        self.save(); path=self.root/d.PREFIX/'data/cohorts'; target=path.with_name('moved')
        path.rename(target); path.symlink_to(target,target_is_directory=True)
        with self.assertRaises((ValueError,OSError)): self.load()

    def test_duplicate_json_and_nonfinite(self):
        for raw in (b'{"artifacts":{},"artifacts":{}}',b'{"artifacts":NaN}'):
            self.put(d.SEAL,raw); self.anchor=d._sha(raw)
            with self.assertRaises(ValueError): self.load()

    def test_special_and_oversized_files(self):
        path=self.root/d.MANIFEST; path.unlink(); os.mkfifo(path)
        with self.assertRaises(ValueError): self.load()
        path.unlink()
        with path.open("wb") as stream: stream.truncate(64*1024*1024+1)
        with self.assertRaises(ValueError): self.load()

    def test_public_no_override(self):
        with self.assertRaises(TypeError): d.load_development_identity(repo=self.root)


if __name__=='__main__': unittest.main()
