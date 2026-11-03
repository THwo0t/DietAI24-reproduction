"""MockTransport crash, concurrency, budget, repair and no-network replay tests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), str(BASE/'src'), str(BASE/'round7/src'), str(BASE/'round8/src')]
from opt_provider import ProviderStop, CHAT_MODEL, fingerprint, sha
from service_n import Ledger, allowed_slots, slot_id, payload, request_hash, REPAIR
from runtime_n import NProvider, Replay
from runtime_m import durable_json

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.rows = [{'sample_id':'a'}, {'sample_id':'b'}]
        self.slots = allowed_slots(self.rows,image_hashes={r['sample_id']:fingerprint('synthetic-image') for r in self.rows})
        self.ledger = Ledger(Path(self.temp.name)/'N', {'freeze':'synthetic'}, self.slots)
        self.ledger.initialize()
        # These are transport/ledger fixtures; actual frozen task admission is
        # exercised without this stub in test_run_n (TaskGate integration).
        self.task_stub = patch('gate_n.frozen_gate')
        self.fake_gate = self.task_stub.start().return_value
        self.fake_gate.parser_sha256 = 'parser-source'
        self.fake_gate.format_error.return_value = 'bad_shape'
        self.addCleanup(self.task_stub.stop)
        self.sid = slot_id('a','N_identity',0)
        self.messages = [{'role':'system','content':'system'}, {'role':'user','content':[
            {'type':'text','text':'query'}, {'type':'image_url','image_url':{'url':'synthetic-image'}}]}]
        self.value = payload(self.messages)
        self.calls = 0

    def good(self, request):
        self.calls += 1
        return httpx.Response(200, json={'model':CHAT_MODEL, 'choices':[{
            'message':{'content':'{"ok":true}'}, 'finish_reason':'stop'}], 'usage':{'total_tokens':7}})

    def provider(self, handler=None):
        p = NProvider(self.ledger, allow_paid=True, keys=('synthetic-chat-credential','synthetic-embed-credential'),
            transport=httpx.MockTransport(handler or self.good), sleep=lambda _:None)
        self.addCleanup(p.close); return p

    def test_success_and_completed_replay_do_not_construct_provider_or_write(self):
        answer, ref = self.provider().request(self.sid,self.value)
        before = self.ledger.audit(complete=True)
        with patch('runtime_n.NProvider',side_effect=AssertionError('no provider')):
            replay = Replay(self.ledger,'a','N_identity',[ref],'parser')
            self.assertEqual(replay.chat(self.messages),answer); replay.finish()
        self.assertEqual(before,self.ledger.audit(complete=True)); self.assertEqual(self.calls,1)

    def test_two_concurrent_slots_one_payload_use_one_http_transmission(self):
        p = self.provider(); sid2 = slot_id('b','N_identity',0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda sid:p.request(sid,self.value)[0], [self.sid,sid2]))
        self.assertEqual(values[0],values[1]); self.assertEqual(self.calls,1)
        self.assertEqual(len(self.ledger.read()['reservations']),1)

    def test_unknown_reservation_consumed_and_third_restart_never_gets_fourth(self):
        h = self.ledger.bind(self.sid,self.value)
        for _ in range(3): self.ledger.reserve(self.sid,h)
        restarted = Ledger(self.ledger.directory,{'freeze':'synthetic'},self.slots)
        p = self.provider()
        with self.assertRaises(ProviderStop): p.request(self.sid,self.value)
        self.assertEqual(len(restarted.read()['reservations']),3); self.assertEqual(self.calls,0)

    def test_same_payload_new_slot_cannot_reset_three_attempts(self):
        h = self.ledger.bind(self.sid,self.value)
        for _ in range(3): self.ledger.reserve(self.sid,h)
        with self.assertRaises(ProviderStop):
            self.provider().request(slot_id('b','N_identity',0),self.value)
        self.assertEqual(self.calls,0)

    def test_response_persisted_before_anchor_and_cache_recovers_without_http(self):
        h = self.ledger.bind(self.sid,self.value); reservation = self.ledger.reserve(self.sid,h)
        body = self.good(None).json(); self.calls = 0
        raw = {'reservation':reservation,'kind':'success','status':200,'body':body,
               'value':'{"ok":true}','value_hash':fingerprint('{"ok":true}')}
        durable_json(self.ledger.outcome_path(reservation['id']),raw)
        with self.assertRaisesRegex(ValueError,'needs_recovery'): self.ledger.target(h)
        self.ledger.recover_pending()
        self.ledger.audit(complete=True)
        answer, _ = self.provider().request(self.sid,self.value)
        self.assertEqual(answer,'{"ok":true}'); self.assertEqual(self.calls,0)
        self.ledger.audit(complete=True)

    def test_cache_value_tamper_rejected_even_when_self_hash_updated(self):
        self.provider().request(self.sid,self.value); h = request_hash(self.value)
        path = self.ledger.cache_path(h); saved = json.loads(path.read_text())
        saved.update(value='changed',value_hash=fingerprint('changed')); durable_json(path,saved)
        with self.assertRaisesRegex(ValueError,'cache_outcome'): self.ledger.target(h)

    def test_raw_reply_tamper_rejected_by_ledger_anchor(self):
        self.provider().request(self.sid,self.value); state = self.ledger.read()
        path = self.ledger.outcome_path(state['reservations'][0]['id'])
        saved = json.loads(path.read_text()); saved['body']['usage']['total_tokens'] = 8
        durable_json(path,saved)
        with self.assertRaisesRegex(ValueError,'anchor_changed'): self.ledger.audit()

    def test_slot_payload_change_unknown_slot_and_binding_change_rejected(self):
        self.ledger.bind(self.sid,self.value)
        messages = deepcopy(self.messages); messages[1]['content'][0]['text'] = 'changed'
        other = payload(messages)
        with self.assertRaisesRegex(ValueError,'slot_payload_changed'): self.ledger.bind(self.sid,other)
        with self.assertRaisesRegex(ValueError,'slot_image_changed'):
            self.ledger.bind(self.sid,payload([{'role':'user','content':'no image'}]))
        with self.assertRaisesRegex(ValueError,'unknown_slot'): self.ledger.bind('not-registered',self.value)
        wrong = Ledger(self.ledger.directory,{'freeze':'other'},self.slots)
        with self.assertRaisesRegex(ValueError,'binding_changed'): wrong.read()

    def test_repair_requires_initial_actual_parser_failure_and_exact_rule(self):
        repair_sid = slot_id('a','N_identity',1)
        raw, _ = self.provider().request(self.sid,self.value)
        messages = self.messages + [{'role':'assistant','content':raw}, {'role':'user','content':REPAIR+'bad_shape'}]
        with self.assertRaisesRegex(ValueError,'without_parser_failure'):
            self.ledger.bind(repair_sid,payload(messages))
        self.ledger.format_failure(self.sid,raw,'bad_shape','parser-source')
        self.ledger.bind(repair_sid,payload(messages))
        changed = deepcopy(messages); changed[-1]['content'] += ' choose accurate answer'
        with self.assertRaisesRegex(ValueError,'slot_payload_changed'):
            self.ledger.bind(repair_sid,payload(changed))
        with self.assertRaisesRegex(ValueError,'without_initial_answer'):
            self.ledger.format_failure(self.sid,'different raw','bad_shape','parser-source')

    def test_http_model_mismatch_stops_permanently_without_format_or_retry(self):
        def wrong(request):
            self.calls += 1
            return httpx.Response(200,json={'model':'wrong','choices':[]})
        p = self.provider(wrong)
        for _ in range(2):
            with self.assertRaises(ProviderStop): p.request(self.sid,self.value)
        self.assertEqual(self.calls,1)
        self.assertEqual(self.ledger.read()['repairs'],{})

    def test_transport_three_then_restart_stays_exhausted(self):
        def timeout(request):
            self.calls += 1; raise httpx.ReadTimeout('synthetic',request=request)
        p = self.provider(timeout)
        for _ in range(2):
            with self.assertRaises(ProviderStop): p.request(self.sid,self.value)
        self.assertEqual(self.calls,3)
        self.assertEqual(self.ledger.audit()['counts']['errors'],3)

    def test_missing_ledger_with_artifacts_and_ancestor_symlink_rejected(self):
        self.ledger.path('admission.json').unlink()
        self.ledger.path('orphan.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'missing_ledger'): self.ledger.initialize()
        self.ledger.path('orphan.json').unlink()
        moved = self.ledger.directory.with_name('moved'); self.ledger.directory.rename(moved)
        self.ledger.directory.symlink_to(moved,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'ancestor_changed'): self.ledger.path('admission.json')

    def test_sanitized_raw_and_value_remove_full_and_truncated_synthetic_keys(self):
        key = 'sk-' + 'syntheticlongcredential1234567890'
        def handler(request):
            return httpx.Response(200,json={'model':CHAT_MODEL,'choices':[{
                'message':{'content':key+' '+key[:15]+'...'},'finish_reason':'stop'}]})
        p = NProvider(self.ledger,allow_paid=True,keys=(key,'different-synthetic-key'),
                      transport=httpx.MockTransport(handler)); self.addCleanup(p.close)
        answer,_ = p.request(self.sid,self.value)
        self.assertNotIn(key,answer); self.assertNotIn(key[:15],answer)
        for path in self.ledger.directory.rglob('*.json'):
            self.assertNotIn(key,path.read_text()); self.assertNotIn(key[:15],path.read_text())

if __name__ == '__main__': unittest.main()
