from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from verified_identity import VerifiedIdentitySnapshot as Snapshot,checked_file,identity_projection


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.file=self.root/'sealed.json';self.file.write_bytes(b'ABCD')
        self.ids={'synthetic':{'status':'ok','final_codes':['12345678']}}
        self.proof={'complete':True,'synthetic_verified':True};self.full_calls=0
        self.state={'bindings':{'identity-slot':'identity-hash'},
            'reservations':[{'id':'r1','payload_hash':'identity-hash','sequence':1}],
            'outcomes':{'r1':'outcome-hash'}}

    def evidence(self):
        return {'source_hash':checked_file(self.file),'slot_binding':'fixed',
                'identity_projection':identity_projection(self.state,{'identity-slot'},{'identity-hash'})}

    def full(self):
        self.full_calls+=1
        # A real frozen integration invokes the existing complete ArtifactStore
        # and service semantic verification here. This fixture models its output.
        return deepcopy(self.ids),deepcopy(self.proof),self.evidence()

    def test_only_full_factory_initializes_and_each_restart_verifies_again(self):
        with self.assertRaisesRegex(TypeError,'full_verify'):Snapshot()
        a=Snapshot.verify(self.full,self.evidence)
        for _ in range(3):self.assertEqual(a.load(),(self.ids,self.proof))
        self.assertEqual(self.full_calls,1)
        a.revalidate_full();self.assertEqual(self.full_calls,2)
        Snapshot.verify(self.full,self.evidence);self.assertEqual(self.full_calls,3)

    def test_content_change_with_same_size_and_mtime_refuses_without_refresh(self):
        a=Snapshot.verify(self.full,self.evidence);stat=self.file.stat()
        self.file.write_bytes(b'WXYZ');os.utime(self.file,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'dependency_changed'):a.load()
        self.assertEqual(self.full_calls,1)

    def test_symlink_replacement_refuses_even_if_target_bytes_match(self):
        a=Snapshot.verify(self.full,self.evidence)
        target=self.root/'other.json';target.write_bytes(self.file.read_bytes());self.file.unlink();self.file.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'unaliased'):a.load()

    def test_legal_quantity_append_allowed_but_old_identity_state_cannot_change(self):
        a=Snapshot.verify(self.full,self.evidence)
        self.state['bindings']['whole-slot']='whole-hash'
        self.state['reservations'].append({'id':'r2','payload_hash':'whole-hash','sequence':2})
        self.state['outcomes']['r2']='whole-outcome'
        self.assertEqual(a.load(),(self.ids,self.proof))
        for field,value in [('bindings',{'identity-slot':'changed'}),
                            ('outcomes',{'r1':'changed'})]:
            old=deepcopy(self.state[field]);self.state[field].update(value)
            with self.assertRaisesRegex(ValueError,'dependency_changed'):a.load()
            self.state[field]=old
        self.state['reservations'][0]['sequence']=9
        with self.assertRaisesRegex(ValueError,'dependency_changed'):a.load()

    def test_returned_values_cannot_poison_cache_and_partial_verify_fails(self):
        a=Snapshot.verify(self.full,self.evidence)
        identities,proof=a.load();identities.clear();proof.clear()
        self.assertEqual(a.load(),(self.ids,self.proof))
        with self.assertRaisesRegex(ValueError,'complete_verified'):
            Snapshot.verify(lambda:({}, {}, {}),lambda:{})
        with self.assertRaisesRegex(ValueError,'complete_verified'):
            Snapshot.verify(lambda:({}, {'complete':True}, {'a':1}),lambda:{'a':1})
        with self.assertRaisesRegex(ValueError,'drift_during'):
            Snapshot.verify(self.full,lambda:{'different':True})


if __name__=='__main__':unittest.main()
