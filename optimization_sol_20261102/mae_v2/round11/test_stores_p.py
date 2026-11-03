from copy import deepcopy
from pathlib import Path
import sys
import unittest
BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10'),str(BASE/'round11')]
import test_runtime_p as runtime_fixture
from stores_p import proof_for_refs,verify_proof,ROUND,identity_store,final_store,adapter_store
from runtime_p import verify_reference
from runtime_m import durable_json
import httpx


class StoreTests(runtime_fixture.RuntimeTests):
    def sealed(self):
        p=self.provider(lambda request:httpx.Response(200,json=self.chat_body()))
        sid,value=self.chat();_,ref=p.request(sid,value)
        refs={'identify':[ref]}
        return refs,proof_for_refs(self.ledger,refs)

    def test_p_root_and_complete_proof(self):
        self.assertEqual(ROUND,BASE/'round11')
        refs,proof=self.sealed()
        self.assertTrue(verify_proof(self.ledger,proof))
        self.assertEqual(proof['logical_answers'],1)
        self.assertEqual(len(proof['reservations']),1)
        self.assertEqual(len(proof['files']),2)

    def test_cache_and_outcome_tamper_rejected(self):
        refs,proof=self.sealed();ref=refs['identify'][0]
        path=self.ledger.cache_path(ref['payload_hash'])
        import service_p
        cache=service_p.load(path);cache['value']='forged';durable_json(path,cache)
        with self.assertRaises(ValueError):verify_proof(self.ledger,proof)
        with self.assertRaises(ValueError):proof_for_refs(self.ledger,refs)

    def test_forged_proof_binding_reservation_and_anchor_rejected(self):
        _,proof=self.sealed()
        for field in ('bindings','reservations','outcomes','files','extra'):
            forged=deepcopy(proof)
            if field=='bindings':forged[field][next(iter(forged[field]))]='0'*64
            elif field=='reservations':forged[field][0]['attempt']=3
            elif field=='outcomes':forged[field][next(iter(forged[field]))]='0'*64
            elif field=='files':forged[field][next(iter(forged[field]))]='0'*64
            else:forged[field]=True
            with self.subTest(field=field),self.assertRaises(ValueError):verify_proof(self.ledger,forged)

    def test_forged_reference_origin_and_extra_field_rejected(self):
        refs,_=self.sealed()
        for change in ('origin','extra'):
            forged=deepcopy(refs)
            if change=='origin':forged['identify'][0]['origin']='new_O'
            else:forged['identify'][0]['unregistered']=True
            with self.assertRaises(ValueError):proof_for_refs(self.ledger,forged)

class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        import test_adapter_p as fixture
        self.f=fixture.AdapterTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.project()

    def test_default_sealed_context_validator_requires_full_snapshot_not_flags(self):
        from stores_p import verified_contexts
        ctx=self.f.ctx;ledger=self.f.f.f.ledger
        expected=self.f.store.verify_completed()['contexts']
        self.assertEqual(verified_contexts(ctx,ledger,self.f.snapshot,self.f.store),expected)
        with self.assertRaisesRegex(ValueError,'verified_coding_snapshot'):
            verified_contexts(ctx,ledger,{'complete':True},self.f.store)

    def test_new_valid_seal_with_forged_provenance_or_subset_context_rejected(self):
        from stores_p import verified_contexts
        from round4.src.artifacts import ArtifactStore
        for change in ('source','population','truth_export','options'):
            values=deepcopy(self.f.store.verify_completed())
            if change=='source':values['provenance']['adapter_source_sha256']='0'*64
            elif change=='population':values['provenance']['input_rows']+=1
            elif change=='truth_export':values['provenance']['current_portion_truth_exported']=True
            else:values['contexts']['a']['options']=[]
            store=ArtifactStore(self.f.root/('forged-'+change),self.f.store.binding,['contexts','provenance'],
                verify_sources=lambda:True,root=self.f.root);store.finalize(values)
            with self.subTest(change=change),self.assertRaises(ValueError):
                verified_contexts(self.f.ctx,self.f.f.f.ledger,self.f.snapshot,store)


if __name__=='__main__':unittest.main()
