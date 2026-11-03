"""Actual scientific stage/cache/ledger integration with synthetic images only."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src')]
import test_uncertain_portions as fixtures
import run_n
import runtime_n
from gate_n import TaskGate
from opt_pipeline import encode_image
from opt_provider import CHAT_MODEL,fingerprint
from service_n import Ledger,allowed_slots,slot_id,payload,REPAIR

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.UncertainCoreTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = Path(self.f.temp.name); self.round = self.root/'round8'; self.round.mkdir()
        self.rows = [{'sample_id':ds,'dataset':ds,'group_id':ds,'fold':0,
            'image_path':self.f.image.name,'image_sha256':self.f.base['input_image_sha256']}
            for ds in ('asa24','nutrition5k')]
        old = {'identity':self.f.base,'portion':self.f.old_portion()}
        hashes = {r['sample_id']:fingerprint(encode_image(self.f.image,'native')) for r in self.rows}
        ledger = Ledger(self.round/'provider/N',{'freeze':'synthetic'},allowed_slots(self.rows,image_hashes=hashes))
        self.ctx = SimpleNamespace(rows=self.rows,catalog=deepcopy(fixtures.CATALOG),binding={'freeze':'synthetic'},
            imported={'records':{r['sample_id']:deepcopy(old) for r in self.rows}},
            fallbacks={'vectors':{ds:{'0':dict(weight=1,energy=2,fat=3,carbs=4,protein=5)} for ds in ('asa24','nutrition5k')}},
            verify_sources=lambda:True,ledger=ledger,parser_sha256='parser')
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(run_n,'ROOT',self.root))
        self.stack.enter_context(patch.object(run_n,'ROUND',self.round))
        self.stack.enter_context(patch('gate_n.frozen_gate',side_effect=lambda ledger:
            TaskGate(self.ctx,ledger,root=self.root)))
        self.calls = 0
        self.original = runtime_n.NProvider

    def handler(self,request):
        self.calls += 1
        prompt = json.loads(request.content)['messages'][1]['content'][0]['text']
        if 'Identify every fixed visible physical food' in prompt: result = self.f.choice
        else:
            p = self.f.pipeline([self.f.choice]); identity = self.f.identity(p)
            unit = p.unit_context(identity)['p1c1']['units'][0]
            result = self.f.quantity(unit)
        return httpx.Response(200,json={'model':CHAT_MODEL,'choices':[
            {'message':{'content':json.dumps(result)},'finish_reason':'stop'}]})

    def test_both_datasets_seal_and_replay_exactly_without_provider_or_writes(self):
        def factory(ledger,**kwargs):
            return self.original(ledger,allow_paid=True,keys=('synthetic-chat','synthetic-embed'),
                transport=httpx.MockTransport(self.handler),sleep=lambda _:None)
        with patch.object(runtime_n,'NProvider',side_effect=factory):
            first = run_n.run(self.ctx,True)
        self.assertEqual(first['pairs'],2); self.assertEqual(self.calls,2)
        self.assertTrue(first['provider_constructed'])
        before = {str(p): (p.stat().st_size,p.stat().st_mtime_ns) for p in self.round.rglob('*') if p.is_file()}
        with patch.object(runtime_n,'NProvider',side_effect=AssertionError('no client')):
            second = run_n.run(self.ctx,False)
        after = {str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in self.round.rglob('*') if p.is_file()}
        self.assertEqual(before,after); self.assertTrue(second['completed_replay'])
        self.assertFalse(second['provider_constructed']); self.assertEqual(self.calls,2)

    def test_incomplete_batch_without_paid_flag_rejects_before_service_creation(self):
        with patch.object(runtime_n,'NProvider',side_effect=AssertionError('no client')):
            with self.assertRaisesRegex(ValueError,'paid_flag_required'): run_n.run(self.ctx,False)
        self.assertFalse(self.ctx.ledger.path('admission.json').exists())

    def test_real_stage_format_failure_admits_only_one_fixed_repair_then_replays(self):
        def handler(request):
            messages = json.loads(request.content)['messages']
            prompt = messages[1]['content'][0]['text']
            if 'Identify every fixed visible physical food' in prompt and len(messages) == 2:
                self.calls += 1
                return httpx.Response(200,json={'model':CHAT_MODEL,'choices':[
                    {'message':{'content':'{"items":[]}'},'finish_reason':'stop'}]})
            return self.handler(request)
        def factory(ledger,**kwargs):
            return self.original(ledger,allow_paid=True,keys=('synthetic-chat','synthetic-embed'),
                transport=httpx.MockTransport(handler),sleep=lambda _:None)
        with patch.object(runtime_n,'NProvider',side_effect=factory): run_n.run(self.ctx,True)
        self.assertEqual(self.calls,3)
        self.assertEqual(len(self.ctx.ledger.read()['repairs']),2)
        before = self.ctx.ledger.audit(complete=True)
        with patch.object(runtime_n,'NProvider',side_effect=AssertionError('no provider')):
            run_n.run(self.ctx,False)
        self.assertEqual(self.ctx.ledger.audit(complete=True),before)

    def test_direct_initial_prompt_system_order_and_units_before_identity_rejected_before_http(self):
        self.ctx.ledger.initialize()
        sid = slot_id('asa24','N_identity',0)
        messages = self.ctx.ledger.task_gate().task(sid).messages
        bads = []
        bad = deepcopy(messages); bad[0]['content'] = 'other system'; bads.append(bad)
        bad = deepcopy(messages); bad[1]['content'][0]['text'] = 'arbitrary task'; bads.append(bad)
        bads.append(list(reversed(messages)))
        p = self.original(self.ctx.ledger,allow_paid=True,keys=('synthetic-chat','synthetic-embed'),
            transport=httpx.MockTransport(self.handler)); self.addCleanup(p.close)
        for bad in bads:
            with self.assertRaises(ValueError): p.request(sid,payload(bad))
        with self.assertRaisesRegex(ValueError,'before_registered_identity'):
            p.request(slot_id('asa24','N_units',0),payload(messages))
        self.assertEqual(self.calls,0); self.assertEqual(self.ctx.ledger.read()['reservations'],[])

    def test_direct_request_checks_frozen_source_before_first_reservation(self):
        self.ctx.ledger.initialize(); sid = slot_id('asa24','N_identity',0)
        messages = self.ctx.ledger.task_gate().task(sid).messages
        def changed(): raise ValueError('synthetic_frozen_source_changed')
        self.ctx.verify_sources = changed
        p = self.original(self.ctx.ledger,allow_paid=True,keys=('synthetic-chat','synthetic-embed'),
            transport=httpx.MockTransport(self.handler)); self.addCleanup(p.close)
        with self.assertRaisesRegex(ValueError,'frozen_source_changed'): p.request(sid,payload(messages))
        self.assertEqual(self.calls,0); self.assertEqual(self.ctx.ledger.read()['reservations'],[])

    def test_valid_identity_and_quantity_cannot_be_repaired_by_forged_error(self):
        def factory(ledger,**kwargs):
            return self.original(ledger,allow_paid=True,keys=('synthetic-chat','synthetic-embed'),
                transport=httpx.MockTransport(self.handler),sleep=lambda _:None)
        with patch.object(runtime_n,'NProvider',side_effect=factory): run_n.run(self.ctx,True)
        before = self.ctx.ledger.audit(complete=True)
        for stage in ('N_identity','N_units'):
            sid = slot_id('asa24',stage,0); state = self.ctx.ledger.read()
            cached = self.ctx.ledger.target(state['bindings'][sid])['cache']
            with self.assertRaisesRegex(ValueError,'valid_answer_cannot_acquire_repair'):
                self.ctx.ledger.format_failure(sid,cached['value'],'invented_error','parser')
            messages = self.ctx.ledger.task_gate().task(sid).messages + [
                {'role':'assistant','content':cached['value']}, {'role':'user','content':REPAIR+'invented_error'}]
            with self.assertRaisesRegex(ValueError,'valid_answer_cannot_acquire_repair'):
                self.ctx.ledger.bind(slot_id('asa24',stage,1),payload(messages))
        self.assertEqual(before,self.ctx.ledger.audit(complete=True)); self.assertEqual(self.calls,2)

    def test_actual_invalid_raw_rejects_fake_error_and_changed_context(self):
        self.ctx.ledger.initialize(); sid = slot_id('asa24','N_identity',0)
        gate = self.ctx.ledger.task_gate(); messages = gate.task(sid).messages
        def invalid(request):
            self.calls += 1
            return httpx.Response(200,json={'model':CHAT_MODEL,'choices':[
                {'message':{'content':'{"items":[]}'},'finish_reason':'stop'}]})
        p = self.original(self.ctx.ledger,allow_paid=True,keys=('synthetic-chat','synthetic-embed'),
            transport=httpx.MockTransport(invalid)); self.addCleanup(p.close)
        raw,_ = p.request(sid,payload(messages))
        with self.assertRaisesRegex(ValueError,'declared_parser_failure_not_actual'):
            self.ctx.ledger.format_failure(sid,raw,'invented_error','parser')
        self.ctx.imported['records']['asa24']['identity']['candidates']['p1c1'].reverse()
        with self.assertRaisesRegex(ValueError,'parser_context_changed'):
            gate.format_error(sid,raw)
        self.assertEqual(self.ctx.ledger.read()['repairs'],{}); self.assertEqual(self.calls,1)

if __name__=='__main__': unittest.main()
