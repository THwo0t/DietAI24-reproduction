from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10'),str(BASE/'round11')]
import context_p as c
from opt_provider import fingerprint


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.rows=[dict(sample_id=ds+str(f),dataset=ds,split='dev',fold=f,group_id=ds+str(f),
            image_path=f'round11/prepared/cohort/images/dev/{ds}{f}.png',image_sha256=hashlib.sha256(b'synthetic').hexdigest())
            for ds in ('asa24','nutrition5k') for f in range(5)]
        for row in self.rows:self.write(row['image_path'],b'synthetic')
        for p in c.REQUIRED:self.write(p,b'synthetic source')
        self.write('round11/prepared/cohort/source_closure.json',{'complete':True})
        self.write('round11/REVIEW.md',b'synthetic independent review')
        self.write('round11/review_gate.json',dict(status='approved_or_fixed',scope='P_first_integrated_context_runner',
            unresolved_p1_p2=0,review_sha256=self.sha('round11/REVIEW.md')))
        self.write(c.ROLES['manifest'],self.rows)
        self.write(c.ROLES['labels'],b'POISON: must never be JSON-decoded')
        self.write(c.ROLES['lineage'],dict(schema_version=1,complete=True,
            rows=[{k:r[k] for k in ('sample_id','dataset','group_id','fold')} for r in self.rows]))
        self.write(c.ROLES['cohort_freeze'],dict(schema_version=1,status='reviewed_complete_new_cohort',
            manifest_sha256=self.sha(c.ROLES['manifest']),labels_sha256=self.sha(c.ROLES['labels']),
            lineage_sha256=self.sha(c.ROLES['lineage']),validation_opened=False,
            source_closure_sha256=self.sha('round11/prepared/cohort/source_closure.json')))
        self.common=dict(schema_version=1,namespace=c.NAMESPACE,paths=dict(c.ROLES),hashes={},
            rows_sha256=fingerprint(self.rows),asset_files={},labels_loaded=False,validation_opened=False,api_calls=0)
        for role in ('manifest','labels','lineage','cohort_freeze'):self.common['hashes'][role]=self.sha(c.ROLES[role])
        for role,kind in [('fallbacks','componentwise_training_medians'),('calibration','training_fold_calibration')]:
            bundle=dict(schema_version=1,role=kind,manifest_sha256=self.common['hashes']['manifest'],
                labels_sha256=self.common['hashes']['labels'],cohort_freeze_sha256=self.common['hashes']['cohort_freeze'],folds={})
            for ds in ('asa24','nutrition5k'):
                bundle['folds'][ds]={}
                for f in range(5):
                    train=c._members(self.rows,ds,f,True);held=c._members(self.rows,ds,f,False)
                    bundle['folds'][ds][str(f)]=dict(train_ids=train,heldout_ids=held,train_groups=train,heldout_groups=held,
                        value={k:1. for k in c.TARGETS} if role=='fallbacks' else dict(enabled=False,status='preregistered_disabled_identity',multipliers={k:1. for k in c.TARGETS}))
            self.write(c.ROLES[role],bundle)
        self.write(c.ROLES['embeddings'],dict(schema_version=1,namespace=c.NAMESPACE,entries={},blocked_hashes=[],policy='fresh_P_queries_only'))
        for p in ('data/catalog.json','data/vectors/manifest.json','data/vectors/codes.json','data/vectors/embeddings.npy'):
            self.write(p,b'synthetic generic asset');self.common['asset_files'][p]=self.sha(p)
        self.refresh()

    def write(self,p,value):
        path=self.root/p;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if type(value) is bytes else json.dumps(value,sort_keys=True).encode())
    def sha(self,p):return hashlib.sha256((self.root/p).read_bytes()).hexdigest()
    def refresh(self):
        self.common['hashes']={role:self.sha(path) for role,path in c.ROLES.items()}
        self.write('round11/prepared/common.json',self.common)
        pins=c.REQUIRED|set(c.ROLES.values())|{'round11/prepared/common.json','round11/prepared/cohort/source_closure.json'}|set(self.common['asset_files'])|{r['image_path'] for r in self.rows}
        slots=c.allowed_slots(self.rows,image_hashes={r['sample_id']:'b'*64 for r in self.rows})
        self.write('round11/prepared/freeze.json',dict(schema_version=1,namespace=c.NAMESPACE,
            source_files={p:self.sha(p) for p in pins},environment=c.environment(),
            allowed_slots_sha256=fingerprint(slots),transport_cap=len(slots)*3,labels_sha256=self.common['hashes']['labels']))
    def load(self):return c._context(self.root,asset_loader=lambda root:({'synthetic':True},object()),
        image_hashes={r['sample_id']:'b'*64 for r in self.rows})

    def test_complete_synthetic_contract_label_poison_not_parsed(self):
        ctx=self.load();self.assertEqual(ctx.rows,self.rows);self.assertEqual(ctx.imports['entries'],{})
        self.assertTrue(ctx.verify_sources())
    def test_source_environment_and_label_drift(self):
        ctx=self.load();self.write(c.ROLES['labels'],b'changed opaque label bytes')
        with self.assertRaises(ValueError):ctx.verify_sources()
        self.refresh()
        frozen=json.loads((self.root/'round11/prepared/freeze.json').read_text());frozen['environment']['python']='wrong'
        self.write('round11/prepared/freeze.json',frozen)
        with self.assertRaises(ValueError):self.load()
    def test_missing_review_gate_and_protected_role_path(self):
        (self.root/'round11/review_gate.json').unlink()
        with self.assertRaises(FileNotFoundError):self.load()
        self.common['paths']['labels']='data/validation/labels.json'
        self.write('round11/prepared/common.json',self.common)
        with self.assertRaises(ValueError):self.load()
    def test_symlink_traversal_and_nonregular_rejected(self):
        outside=self.root/'outside';outside.write_bytes(b'x')
        (self.root/'link').symlink_to(outside)
        for p in ('link','../outside','/etc/passwd','a//b','a/./b'):
            with self.subTest(path=p),self.assertRaises((ValueError,OSError)):c._read(self.root,p)
    def test_row_label_field_and_group_fold_rejected(self):
        for mutation in ('label','fold'):
            rows=deepcopy(self.rows)
            if mutation=='label':rows[0]['weight']=1
            else:rows[1]['group_id']=rows[0]['group_id']
            with self.assertRaises(ValueError):c.allowed_slots(rows,image_hashes={r['sample_id']:'b'*64 for r in rows})
    def test_fallback_fold_leakage_and_nonfinite_rejected(self):
        bundle=json.loads((self.root/c.ROLES['fallbacks']).read_text())
        for mutation in ('train','median'):
            bad=deepcopy(bundle);proof=bad['folds']['nutrition5k']['0']
            if mutation=='train':proof['train_ids']+=proof['heldout_ids']
            else:proof['value']['weight']=float('nan')
            with self.assertRaises(ValueError):c._validate_training(bad,self.rows,self.common,'componentwise_training_medians')
    def test_nonempty_historical_import_manifest_rejected(self):
        self.write(c.ROLES['embeddings'],dict(schema_version=1,namespace=c.NAMESPACE,entries={'a':{}},blocked_hashes=[],policy='fresh_P_queries_only'))
        self.refresh()
        with self.assertRaisesRegex(ValueError,'historical_imports_disabled'):self.load()
    def test_inference_calibration_identity_only_without_future_fit_artifacts(self):
        ctx=self.load();value=ctx.calibration['folds']['asa24']['0']['value']
        self.assertFalse(value['enabled']);self.assertEqual(set(value['multipliers'].values()),{1.})
        self.assertFalse((self.root/'round11/prepared/fits').exists())
        bundle=deepcopy(ctx.calibration)
        for change in ('enabled','multiplier','status'):
            bad=deepcopy(bundle);v=bad['folds']['asa24']['0']['value']
            if change=='enabled':v['enabled']=True
            elif change=='multiplier':v['multipliers']['weight']=1.2
            else:v['status']='fitted'
            with self.assertRaises(ValueError):c._validate_training(bad,self.rows,self.common,'training_fold_calibration')

    def test_live_context_and_freeze_mutation_rejected(self):
        ctx=self.load();ctx.fallbacks['folds']['asa24']['0']['value']['weight']=9
        with self.assertRaises(ValueError):ctx.verify_sources()
        ctx=self.load();self.write('round11/prepared/freeze.json',{'forged':True})
        with self.assertRaises(ValueError):ctx.verify_sources()

    def test_large_vector_exception_is_exact_path_digest_only_and_bounded(self):
        raw=b'synthetic-large-vector'
        self.write(c.VECTOR_PATH,raw);self.write('data/vectors/other.npy',raw)
        with patch.object(c,'MAX_BYTES',8),patch.object(c,'VECTOR_DIGEST_MAX_BYTES',32):
            self.assertEqual(c._read(self.root,c.VECTOR_PATH,digest_only=True),hashlib.sha256(raw).hexdigest())
            for path,digest in ((c.VECTOR_PATH,False),('data/vectors/other.npy',True),
                                ('data/vectors/other.npy',False)):
                with self.subTest(path=path,digest=digest),self.assertRaises(ValueError):
                    c._read(self.root,path,digest_only=digest)
            self.write(c.VECTOR_PATH,b'x'*33)
            with self.assertRaises(ValueError):c._read(self.root,c.VECTOR_PATH,digest_only=True)

    def test_public_entry_has_no_pre_review_bypass(self):
        with self.assertRaises(TypeError):c.runtime_context(pre_review=True)

if __name__=='__main__':unittest.main()
