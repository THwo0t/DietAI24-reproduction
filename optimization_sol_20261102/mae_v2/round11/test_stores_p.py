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

if __name__=='__main__':unittest.main()
