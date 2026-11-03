from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import postscore_p as post
from source_census import encoded,sha
import scoring_p


class PostscoreTests(unittest.TestCase):
    def fixture(self,stack):
        root=Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        for path in post.SOURCES:
            file=root/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'# fixture source\n')
        review=root/post.REVIEW;review.parent.mkdir(parents=True,exist_ok=True);review.write_bytes(b'fixture review')
        gate={'status':'approved_or_fixed','scope':'P_first_integrated_postscore','unresolved_p1_p2':0,
            'review_sha256':sha(review.read_bytes()),'source_sha256':{p:sha((root/p).read_bytes()) for p in post.SOURCES}}
        raw=encoded(gate);(root/post.GATE).write_bytes(raw)
        rows=[]
        for ds in ('asa24','nutrition5k'):
            for fold in range(5):
                rows.append({'sample_id':ds+str(fold),'dataset':ds,'split':'dev','fold':fold,
                    'group_id':ds+str(fold),'image_path':'never-follow.png','image_sha256':'f'*64})
        labels={r['sample_id']:{'truth':dict.fromkeys(('weight','energy','fat','carbs','protein'),1)} for r in rows}
        labelraw=encoded(labels);labelpath=root/post.LABELS
        labelpath.parent.mkdir(parents=True,exist_ok=True);labelpath.write_bytes(labelraw)
        value={'rows':rows,'records':[{'row':deepcopy(r),'profiles':dict.fromkeys(('O','Q','D','Q+D'),{})} for r in rows],
            'catalog':{},'strata':{r['sample_id']:'fixture' for r in rows},
            'bindings':{k:'a'*64 for k in post.BINDINGS},
            'audit':{'completed':True,'provider_constructed':False,'labels_parsed':False,
                'validation_opened':False,'exact_records_reconstructed':True,
                'all_cache_model_matrix_refs_authenticated':True},'revalidate':Mock()}
        value['bindings']['labels_sha256']=sha(labelraw)
        scorer=stack.enter_context(patch.object(scoring_p,'score',return_value={'selected_profile':None,'profiles':{}}))
        return root,sha(raw),value,scorer

    def run_fixture(self,root,pin,value):
        return post._postscore_at(root,expected_gate_sha=pin,verifier=lambda root:value)

    def test_missing_registered_gate_and_closed_verifier_open_no_labels(self):
        with patch.object(post,'bounded_read',side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(ValueError,'registered_review_receipt_required'):
                post._postscore_at(post.REPO,expected_gate_sha=None,verifier=lambda root:(_ for _ in ()).throw(ValueError('P_verifier_not_implemented')))
        with ExitStack() as stack:
            root,pin,value,scorer=self.fixture(stack)
            original=post.bounded_read
            def read(base,path):
                self.assertNotEqual(path,post.LABELS);return original(base,path)
            stack.enter_context(patch.object(post,'bounded_read',side_effect=read))
            with self.assertRaisesRegex(ValueError,'verifier_not_implemented'):
                post._postscore_at(root,expected_gate_sha=pin,verifier=lambda root:(_ for _ in ()).throw(ValueError('P_verifier_not_implemented')))
            scorer.assert_not_called()

    def test_early_incomplete_provider_and_matrix_proof_refused(self):
        for mode in ('incomplete','provider','missingbinding','missingrow'):
            with self.subTest(mode=mode),ExitStack() as stack:
                root,pin,value,scorer=self.fixture(stack)
                if mode=='incomplete':value['audit']['completed']=False
                elif mode=='provider':value['audit']['provider_constructed']=True
                elif mode=='missingbinding':value['bindings'].pop('matrix_sha256')
                else:value['records'].pop()
                original=post.bounded_read
                def read(base,path):
                    self.assertNotEqual(path,post.LABELS);return original(base,path)
                stack.enter_context(patch.object(post,'bounded_read',side_effect=read))
                with self.assertRaises(ValueError):self.run_fixture(root,pin,value)
                scorer.assert_not_called()

    def test_label_hash_and_source_tamper(self):
        for mode in ('label','source'):
            with self.subTest(mode=mode),ExitStack() as stack:
                root,pin,value,scorer=self.fixture(stack)
                path=post.LABELS if mode=='label' else post.SOURCES[0]
                (root/path).write_bytes(b'tamper')
                with self.assertRaises(ValueError):self.run_fixture(root,pin,value)
                scorer.assert_not_called()

    def test_single_score_private_output_and_resume_compare(self):
        with ExitStack() as stack:
            root,pin,value,scorer=self.fixture(stack)
            result=self.run_fixture(root,pin,value);scorer.assert_called_once()
            self.assertEqual(result['rows'],10)
            self.assertEqual((root/post.OUTPUT).stat().st_mode&0o777,0o600)
            self.assertEqual((root/post.OUTPUT).parent.stat().st_mode&0o777,0o700)
            self.assertEqual(result,self.run_fixture(root,pin,value))
            (root/post.OUTPUT).write_bytes(b'conflict')
            with self.assertRaisesRegex(ValueError,'existing_result_conflict'):self.run_fixture(root,pin,value)

    def test_held_snapshot_and_postscore_label_drift_refused(self):
        with ExitStack() as stack:
            root,pin,value,scorer=self.fixture(stack)
            calls=0
            def revalidate():
                nonlocal calls
                calls+=1
                if calls==2:value['catalog']['changed']=True
            value['revalidate']=revalidate
            with self.assertRaisesRegex(ValueError,'held_snapshot_changed'):self.run_fixture(root,pin,value)
            scorer.assert_not_called()
        with ExitStack() as stack:
            root,pin,value,scorer=self.fixture(stack)
            scorer.side_effect=lambda *a,**kw:((root/post.LABELS).write_bytes(b'changed') or {})
            # Return a proper result after mutating labels.
            def score(*args,**kwargs):
                (root/post.LABELS).write_bytes(b'changed');return {'selected_profile':None,'profiles':{}}
            scorer.side_effect=score
            with self.assertRaisesRegex(ValueError,'labels_changed_during_score'):self.run_fixture(root,pin,value)
            self.assertFalse((root/post.OUTPUT).exists())

    def test_final_fit_only_for_confirmed_qualified_selected_arm(self):
        with ExitStack() as stack:
            root,pin,value,scorer=self.fixture(stack)
            scorer.return_value={'selected_profile':'O','profiles':{'O':{'calibration_retained':False}}}
            prepare=stack.enter_context(patch.object(scoring_p,'_prepare',return_value={'O':['raw arm']}))
            fit=stack.enter_context(patch.object(scoring_p,'full_development_parameters',return_value={
                'parameters':{'nutrition5k':{'factors':{'weight':1.1}},'asa24':{'factor':1.1}}}))
            self.run_fixture(root,pin,value)
            scorer.assert_called_once();fit.assert_called_once()
            self.assertEqual(fit.call_args.kwargs,{'selected_profile':'O','selection_confirmed':True})
            result=post.decode((root/post.OUTPUT).read_bytes())
            final=result['selected_full_development_fit']
            self.assertEqual(final['postprocessor'],'raw_identity')
            self.assertEqual(final['parameters']['nutrition5k']['factors']['weight'],1)
        with ExitStack() as stack:
            root,pin,value,scorer=self.fixture(stack)
            fit=stack.enter_context(patch.object(scoring_p,'full_development_parameters'))
            self.run_fixture(root,pin,value);fit.assert_not_called()

    def test_science_freeze_derives_gate_without_self_pin_cycle(self):
        with ExitStack() as stack:
            root,pin,value,scorer=self.fixture(stack)
            gate=post.decode((root/post.GATE).read_bytes())
            sources={p.removeprefix(post.PREFIX):digest for p,digest in gate['source_sha256'].items()}
            sources[post.GATE.removeprefix(post.PREFIX)]=pin
            sources[post.REVIEW.removeprefix(post.PREFIX)]=gate['review_sha256']
            science={'schema_version':1,'source_files':sources}
            file=root/post.SCIENCE_FREEZE;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(encoded(science))
            gatepin,rawsha,binding=post._science_gate_at(root)
            self.assertEqual(gatepin,pin);self.assertEqual(rawsha,sha(file.read_bytes()))
            value['bindings']['science_sha256']=binding
            result=post._postscore_at(root,expected_gate_sha=gatepin,verifier=lambda root:value,
                expected_science_sha=rawsha,expected_science_binding=binding)
            self.assertEqual(result['rows'],10)
            sources[post.SOURCES[0].removeprefix(post.PREFIX)]='f'*64
            file.write_bytes(encoded(science))
            with self.assertRaisesRegex(ValueError,'science_scoring_source_pins_differ'):
                post._science_gate_at(root)

    def test_R_P_1_snapshot_source_missing_pin_drift_and_science_gate_mismatch(self):
        critical=post.PREFIX+'round11/verified_identity.py'
        self.assertIn(critical,post.SOURCES)
        for mode in ('missing','drift','science_mismatch'):
            with self.subTest(mode=mode),ExitStack() as stack:
                root,pin,value,scorer=self.fixture(stack)
                gate=post.decode((root/post.GATE).read_bytes())
                if mode=='missing':
                    gate['source_sha256'].pop(critical)
                    raw=encoded(gate);(root/post.GATE).write_bytes(raw);pin=sha(raw)
                    with self.assertRaisesRegex(ValueError,'review_incomplete'):self.run_fixture(root,pin,value)
                elif mode=='drift':
                    (root/critical).write_bytes(b'changed synthetic snapshot implementation')
                    with self.assertRaisesRegex(ValueError,'source_changed'):self.run_fixture(root,pin,value)
                else:
                    sources={p.removeprefix(post.PREFIX):h for p,h in gate['source_sha256'].items()}
                    sources[post.GATE.removeprefix(post.PREFIX)]=pin
                    sources[post.REVIEW.removeprefix(post.PREFIX)]=gate['review_sha256']
                    sources[critical.removeprefix(post.PREFIX)]='f'*64
                    path=root/post.SCIENCE_FREEZE;path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(encoded({'schema_version':1,'source_files':sources}))
                    with self.assertRaisesRegex(ValueError,'science_scoring_source_pins_differ'):post._science_gate_at(root)
                scorer.assert_not_called()
                value['revalidate'].assert_not_called()

    def test_cli_override_refused_before_work(self):
        with patch.object(post.sys,'argv',['postscore','--root=/tmp']),patch.object(post,'_postscore_at') as run:
            with self.assertRaisesRegex(ValueError,'cli_overrides_refused'):post.main()
            run.assert_not_called()


if __name__=='__main__':unittest.main()
