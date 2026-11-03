from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE/'round11'),str(BASE/'round10')]
import test_gate_o as fixtures
import stores_o
import identity_gate as fast
from opt_provider import fingerprint
from service_o import payload
from runtime_o import Trace


class IntegratedIdentitySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ExactGateTests('test_valid_initial_answer_cannot_get_repair')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.ctx.binding={'source_files':{}}
        self.f.imports.update(source_files={},legacy={'source_files':{}})
        self.f.identify_replies=['invalid format',json.dumps({'items':[
            {'item_id':'i1','description':'synthetic O gate fixture food 94e',
             'broad_query':'synthetic O gate fixture category 94e','region_ids':['r1']}]})]
        envelope=self.f.identity();self.identity=envelope['result']
        self.assertTrue(self.identity['repaired'])
        directory=self.f.root/'O';directory.mkdir(mode=0o700)
        with patch.object(stores_o,'ROUND',directory):
            self.store=stores_o.identity_store(self.f.ctx)
        refs={stage:values for stage,values in envelope['request_refs'].items()}
        proof=stores_o.proof_for_refs(self.f.ledger,refs)
        self.store.finalize({stores_o.name('identity',self.f.row):self.identity,'service-proof':proof})
        self.context={'code':self.f.code,'options':self.f.ctx.catalog['asa_options'][self.f.code]}
        self.f.gate.context_loader=lambda:{'a':deepcopy(self.context)}
        self.f.gate.identity_loader=lambda:({'a':deepcopy(self.identity)},
            {'complete':True,'identity_records_sha256':fingerprint({'a':self.identity})})

    def test_real_seals_and_task_gate_match_uncached_on_same_payload_without_extra_HTTP(self):
        # Only MockTransport was used in setUp. No new request is sent below.
        from gate_o import Machine,Captured
        from service_o import slot_id
        sid=slot_id('a','conditional',0)
        try:Machine(self.f.gate,sid).execute()
        except Captured as capture:value=capture.value
        self.assertTrue(self.f.gate.validate(sid,value))
        before=len(self.f.seen)
        with patch.object(fast,'verify_proof',wraps=stores_o.verify_proof) as verify:
            snap=fast.build_loader(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root)
            self.f.gate.identity_loader=snap.load
            for _ in range(3):self.assertTrue(self.f.gate.validate(sid,value))
            self.assertEqual(verify.call_count,1)
            snap.revalidate_full();self.assertEqual(verify.call_count,2)
        self.assertEqual(len(self.f.seen),before)
        changed=deepcopy(value);changed['payload']['messages'][1]['content'][0]['text']+=' changed'
        with self.assertRaisesRegex(ValueError,'frozen_task_payload_changed'):
            self.f.gate.validate(sid,changed)
        self.f.gate.context_loader=lambda:{'a':{'code':self.f.code,'options':[]}}
        with self.assertRaisesRegex(ValueError,'context_changed'):self.f.gate.validate(sid,value)

    def test_completed_identity_record_tamper_preserving_marker_is_refused(self):
        snap=fast.build_loader(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root)
        record=next((self.store.directory/'records').glob('*.json'))
        record.write_bytes(record.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'dependency_changed'):snap.load()

    def test_real_quantity_append_preserves_identity_but_old_outcome_anchor_drift_refuses(self):
        from engine_o import RowLive,portions
        snap=fast.build_loader(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root)
        self.f.gate.identity_loader=snap.load
        portions(self.f.ctx,self.f.row,self.identity,RowLive(self.f.row,self.f.trace),root=self.f.root)
        self.assertEqual(snap.load()[0],{'a':self.identity})
        state=self.f.ledger.read();old=state['reservations'][0]['id']
        state['outcomes'][old]='0'*64;self.f.ledger.save(state)
        with self.assertRaisesRegex(ValueError,'dependency_changed'):snap.load()

    def test_real_identity_repair_proof_change_removal_or_new_identity_repair_refuses(self):
        from service_o import slot_id
        for case in ('edit','remove','add_select'):
            with self.subTest(case=case):
                baseline=self.f.ledger.read()
                snap=fast.build_loader(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root)
                changed=deepcopy(baseline);initial=slot_id('a','identify',0)
                if case=='edit':changed['repairs'][initial]['error']='schema-valid but changed'
                elif case=='remove':del changed['repairs'][initial]
                else:changed['repairs'][slot_id('a','select',0)]=deepcopy(changed['repairs'][initial])
                self.f.ledger.save(changed)
                try:
                    with self.assertRaisesRegex(ValueError,'dependency_changed'):snap.load()
                finally:self.f.ledger.save(baseline)

    def test_full_factory_refuses_preexisting_false_or_missing_identity_repair_proofs(self):
        from service_o import slot_id
        for case in ('edit','remove','add_select'):
            with self.subTest(case=case):
                baseline=self.f.ledger.read();changed=deepcopy(baseline);initial=slot_id('a','identify',0)
                if case=='edit':changed['repairs'][initial]['error']='schema-valid but changed'
                elif case=='remove':del changed['repairs'][initial]
                else:changed['repairs'][slot_id('a','select',0)]=deepcopy(changed['repairs'][initial])
                self.f.ledger.save(changed)
                try:
                    with self.assertRaisesRegex(ValueError,'snapshot_identity_repair'):
                        fast.build_loader(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root)
                finally:self.f.ledger.save(baseline)

    def test_real_new_whole_format_repair_remains_a_legal_nonidentity_append(self):
        import httpx
        from opt_provider import CHAT_MODEL
        from engine_o import RowLive,portions
        snap=fast.build_loader(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root)
        self.f.gate.identity_loader=snap.load
        transport=self.f.provider.client._transport;original=transport.handler;bad=[True]
        def handler(request):
            value=json.loads(request.content)
            if len(value.get('messages',[]))==2 and bad[0]:
                bad[0]=False;self.f.seen.append(value)
                return httpx.Response(200,json={'model':CHAT_MODEL,'choices':[
                    {'message':{'content':'invalid quantity format'},'finish_reason':'stop'}]})
            return original(request)
        transport.handler=handler
        result=portions(self.f.ctx,self.f.row,self.identity,RowLive(self.f.row,self.f.trace),root=self.f.root)
        self.assertTrue(result['result']['repaired'])
        self.assertEqual(len(self.f.ledger.read()['repairs']),2)
        self.assertEqual(snap.load()[0],{'a':self.identity})
        snap.revalidate_full()

    def test_image_or_manifest_or_catalog_drift_is_refused_before_cached_use(self):
        for kind in ('image','rows','catalog'):
            with self.subTest(kind=kind):
                snap=fast.build_loader(self.f.ctx,self.f.ledger,self.store,data_root=self.f.root)
                original_image=(self.f.root/'synthetic.png').read_bytes()
                original_row=deepcopy(self.f.row);original_catalog=deepcopy(self.f.ctx.catalog)
                if kind=='image':(self.f.root/'synthetic.png').write_bytes(original_image+b' ')
                elif kind=='rows':self.f.row['group_id']='changed'
                else:self.f.ctx.catalog['foods'][self.f.code]['density']['fat']+=1
                with self.assertRaisesRegex(ValueError,'dependency_changed'):snap.load()
                (self.f.root/'synthetic.png').write_bytes(original_image)
                self.f.row.clear();self.f.row.update(original_row)
                self.f.ctx.catalog.clear();self.f.ctx.catalog.update(original_catalog)


if __name__=='__main__':unittest.main()
