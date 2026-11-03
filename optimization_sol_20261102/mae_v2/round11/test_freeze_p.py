"""Synthetic freeze publication; never touch real prepared artifacts."""
from contextlib import ExitStack
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import test_context_p as context_fixture
import context_p as context
import freeze_p as freeze
import assets_p
import numpy as np
from opt_provider import fingerprint
from source_census import encoded


class FreezeTests(unittest.TestCase):
    def fixture(self,stack):
        original=context_fixture.ContextTests('test_complete_synthetic_contract_label_poison_not_parsed')
        original.setUp();stack.callback(original.doCleanups)
        import tempfile
        temp=Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        root=temp/freeze.PREFIX.rstrip('/')
        shutil.copytree(original.root,root)
        original.root=root
        # Real tiny NPY payload, with fixture-specific manifest size validation.
        vector=root/'data/vectors/embeddings.npy'
        with vector.open('wb') as stream:np.save(stream,np.ones((2,2),dtype=np.float32),allow_pickle=False)
        manifest={'vectors':2,'dimensions':2,'api_calls':0,'embedding_model':'text-embedding-3-large',
            'files':{name:original.sha('data/vectors/'+name) for name in ('codes.json','embeddings.npy')}}
        original.write('data/vectors/manifest.json',manifest)
        original.common['asset_files']['data/vectors/manifest.json']=original.sha('data/vectors/manifest.json')
        original.common['asset_files']['data/vectors/embeddings.npy']=original.sha('data/vectors/embeddings.npy')
        original.refresh();(root/freeze.PATH).unlink()
        prepared=root/'round11/prepared'
        for path in [prepared,*prepared.rglob('*')]:path.chmod(0o700 if path.is_dir() else 0o600)
        asset_paths=assets_p.asset_paths
        small=lambda description:asset_paths(description,vectors=2,dimensions=2)
        stack.enter_context(patch.object(freeze,'asset_paths',side_effect=small))
        stack.enter_context(patch.object(assets_p,'asset_paths',side_effect=small))
        hashes={r['sample_id']:'b'*64 for r in original.rows}
        def validate(base):
            self.assertEqual(base,root)
            self.assertEqual(np.load(vector,allow_pickle=False).shape,(2,2))
            return context._context(root,asset_loader=lambda root:({'synthetic':True},object()),image_hashes=hashes)
        return original,hashes,validate

    def run_fixture(self,fixture,hashes,validate):
        return freeze._freeze_at(fixture.root,required=context.REQUIRED,image_hashes=hashes,validate_context=validate)

    def test_full_context_tiny_assets_slots_private_write_and_resume(self):
        with ExitStack() as stack:
            f,hashes,validate=self.fixture(stack)
            result=self.run_fixture(f,hashes,validate)
            self.assertEqual(result['rows'],10);self.assertFalse(result['labels_parsed'])
            frozen=freeze._load(f.root,freeze.PATH)
            slots=freeze.allowed_slots(f.rows,image_hashes=hashes)
            self.assertEqual(frozen['allowed_slots_sha256'],fingerprint(slots))
            self.assertEqual(frozen['transport_cap'],len(slots)*3)
            self.assertEqual((f.root/freeze.PATH).stat().st_mode&0o777,0o600)
            self.assertEqual((f.root/freeze.PATH).parent.stat().st_mode&0o777,0o700)
            self.assertEqual(result,self.run_fixture(f,hashes,validate))
            self.assertIn('round11/preparation/preparation_review_gate.json',frozen['source_files'])
            self.assertEqual(frozen['source_files'][context.ROLES['labels']],f.sha(context.ROLES['labels']))

    def test_R_P_1_default_production_inventory_binds_snapshot_authenticator(self):
        from postscore_p import SOURCES
        critical='round11/verified_identity.py'
        self.assertIn(critical,context.REQUIRED);self.assertIn(critical,freeze.EXTRA)
        self.assertIn(freeze.PREFIX+critical,SOURCES)
        with ExitStack() as stack:
            f,hashes,validate=self.fixture(stack)
            production=set(context.REQUIRED)|freeze.EXTRA|{p.removeprefix(freeze.PREFIX) for p in SOURCES}
            for path in production:
                if not (f.root/path).exists():f.write(path,b'synthetic production-inventory source')
            result=freeze._freeze_at(f.root,image_hashes=hashes,validate_context=validate)
            frozen=freeze._load(f.root,freeze.PATH)
            expected=production|set(context.ROLES.values())|{freeze.COMMON,freeze.CLOSURE,freeze.GATE,freeze.REVIEW,freeze.PREPARATION_GATE}
            expected.update(f.common['asset_files']);expected.update(r['image_path'] for r in f.rows)
            prep=freeze._load(f.root,freeze.PREPARATION_GATE)
            expected.update(p.removeprefix(freeze.PREFIX) for p in prep['source_files'])
            self.assertEqual(set(frozen['source_files']),expected)
            self.assertEqual(frozen['source_files'][critical],f.sha(critical))
            self.assertEqual(result['source_files'],len(expected))
            ctx=validate(f.root);f.write(critical,b'changed after synthetic science freeze')
            with self.assertRaisesRegex(ValueError,'source_changed'):ctx.verify_sources()

    def test_review_refused_before_any_prepared_role(self):
        with ExitStack() as stack:
            f,hashes,validate=self.fixture(stack)
            f.write(freeze.GATE,{'status':'pending'})
            reader=freeze._load;seen=[]
            def load(root,path):seen.append(path);return reader(root,path)
            stack.enter_context(patch.object(freeze,'_load',side_effect=load))
            with self.assertRaisesRegex(ValueError,'complete_integrated_review_required'):
                self.run_fixture(f,hashes,validate)
            self.assertEqual(seen,[freeze.GATE]);self.assertFalse((f.root/freeze.PATH).exists())

    def test_prep_source_and_opaque_label_drift_refused_before_publish(self):
        for path in ('round11/prepare_p.py',context.ROLES['labels']):
            with self.subTest(path=path),ExitStack() as stack:
                f,hashes,validate=self.fixture(stack);f.write(path,b'changed source bytes')
                with self.assertRaisesRegex(ValueError,'prepared_source_drift'):
                    self.run_fixture(f,hashes,validate)
                self.assertFalse((f.root/freeze.PATH).exists())

    def test_exact_assets_manifest_rows_and_slots_fail_closed(self):
        for mode in ('asset','row','slot'):
            with self.subTest(mode=mode),ExitStack() as stack:
                f,hashes,validate=self.fixture(stack)
                if mode=='asset':f.common['asset_files'].pop('data/vectors/codes.json')
                elif mode=='row':f.rows[0]['fold']=5;f.write(context.ROLES['manifest'],f.rows)
                else:hashes.pop(f.rows[0]['sample_id'])
                if mode!='slot':f.write(freeze.COMMON,f.common)
                with self.assertRaises((ValueError,KeyError)):self.run_fixture(f,hashes,validate)
                self.assertFalse((f.root/freeze.PATH).exists())

    def test_source_change_during_assembly_refused(self):
        with ExitStack() as stack:
            f,hashes,validate=self.fixture(stack)
            original=freeze.allowed_slots
            def slots(*args,**kwargs):
                f.write('round11/prepare_p.py',b'changed after hashing')
                return original(*args,**kwargs)
            stack.enter_context(patch.object(freeze,'allowed_slots',side_effect=slots))
            with self.assertRaisesRegex(ValueError,'source_changed_during_assembly'):
                self.run_fixture(f,hashes,validate)
            self.assertFalse((f.root/freeze.PATH).exists())

    def test_context_must_validate_before_success_partial_preserved(self):
        with ExitStack() as stack:
            f,hashes,validate=self.fixture(stack)
            with self.assertRaisesRegex(ValueError,'full_context_validation_failed'):
                self.run_fixture(f,hashes,lambda root:SimpleNamespace(binding={'wrong':True}))
            self.assertTrue((f.root/freeze.PATH).exists())
            (f.root/freeze.PATH).write_bytes(b'partial')
            with self.assertRaisesRegex(ValueError,'existing_prepared_file_changed'):
                self.run_fixture(f,hashes,validate)
            self.assertEqual((f.root/freeze.PATH).read_bytes(),b'partial')

    def test_late_context_source_drift_and_bool_review_count_refused(self):
        with ExitStack() as stack:
            f,hashes,validate=self.fixture(stack)
            def changed(root):
                ctx=validate(root)
                def verify():f.write('round11/prepare_p.py',b'changed during context verification')
                ctx.verify_sources=verify
                return ctx
            with self.assertRaisesRegex(ValueError,'source_changed_during_context_validation'):
                self.run_fixture(f,hashes,changed)
        with ExitStack() as stack:
            f,hashes,validate=self.fixture(stack)
            prep=freeze._load(f.root,freeze.PREPARATION_GATE);prep['unresolved_p1_p2']=False
            f.write(freeze.PREPARATION_GATE,prep)
            with self.assertRaisesRegex(ValueError,'preparation_review_required'):
                self.run_fixture(f,hashes,validate)

    def test_symlink_output_and_ancestor_refused(self):
        for mode in ('output','ancestor'):
            with self.subTest(mode=mode),ExitStack() as stack:
                f,hashes,validate=self.fixture(stack)
                if mode=='output':
                    target=f.root/'target';target.write_bytes(b'keep')
                    (f.root/freeze.PATH).symlink_to(target)
                else:
                    path=f.root/'round11/prepared';target=f.root/'private-target'
                    path.rename(target);path.symlink_to(target,target_is_directory=True)
                with self.assertRaises((ValueError,OSError)):self.run_fixture(f,hashes,validate)
                if mode=='output':self.assertEqual(target.read_bytes(),b'keep')

    def test_public_cli_no_overrides(self):
        with patch.object(freeze.sys,'argv',['freeze','--root=/tmp']),patch.object(freeze,'_freeze_at') as work:
            with self.assertRaisesRegex(ValueError,'cli_overrides_refused'):freeze.main()
            work.assert_not_called()


if __name__=='__main__':unittest.main()
