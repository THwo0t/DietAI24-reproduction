from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10'),str(BASE/'round11')]
import service_p as s
from opt_provider import fingerprint,ProviderStop,CHAT_MODEL,EMBED_MODEL
from historical_m import request_hash as old_hash
from runtime_m import durable_json


class BoundGate:
    def __init__(self, expected): self.expected=expected
    def format_error(self,sid,raw):return None if raw=='valid' else 'bad format'
    def validate(self,sid,value):
        if self.expected.get(sid)!=value: raise ValueError('synthetic_unregistered_task')


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        rows=[self.row('a'),self.row('n','nutrition5k')]
        self.image='data:image/png;base64,fixture'
        self.slots=s.allowed_slots(rows,image_hashes={r['sample_id']:fingerprint(self.image) for r in rows})
        self.ledger=s.Ledger(Path(self.temp.name)/'service',self.binding(self.slots),self.slots)
        self.expected={}; self.ledger._gate=BoundGate(self.expected);self.ledger._gate.parser_sha256=self.ledger.parser_sha256;self.ledger.initialize()

    def chat(self):
        value=s.payload([{'role':'system','content':'synthetic'}, {'role':'user','content':[
            {'type':'text','text':'synthetic prompt'}, {'type':'image_url','image_url':{'url':self.image}}]}])
        sid=s.slot_id('a','identify',0); self.expected[sid]=value
        return sid,value

    @staticmethod
    def row(sample,dataset='asa24'):
        return dict(sample_id=sample,dataset=dataset,split='dev',fold=0,group_id=sample,
                    image_path='data/dev/images/'+sample+'.png',image_sha256='a'*64)

    @staticmethod
    def binding(slots):
        return {'source_files':{p:'b'*64 for p in s.PARSER_SOURCES},
                'allowed_slots_sha256':fingerprint(slots),'transport_cap':len(slots)*3}

    def success(self,sid,value,raw='bad'):
        h=self.ledger.bind(sid,value);r=self.ledger.reserve(sid,h)
        body={'model':value['payload']['model'],'choices':[{'message':{'content':raw},'finish_reason':'stop'}]}
        outcome={'kind':'success','status':200,'body':body,'value':raw,'value_hash':fingerprint(raw),'error_type':None}
        self.ledger.persist(r,outcome)
        return h,r

    def test_exact_slot_universe_and_all_stage_ordinals(self):
        self.assertEqual(len(self.slots),102)
        for stage in ('identify','select','whole','quantity','density','conditional'):
            for ordinal in (0,1):self.assertIn(s.slot_id('a',stage,ordinal),self.slots)
            with self.assertRaises(ValueError):s.slot_id('a',stage,2)
        self.assertNotIn(s.slot_id('n','conditional',0),self.slots)
        for stage,ordinal in [('embed_40',0),('embed_00',1)]:
            with self.assertRaises(ValueError):s.slot_id('a',stage,ordinal)

    def test_blind_rows_and_hash_injection_reject_malformed_inputs(self):
        for change in ('label','duplicate','fold','dataset','path','hash','group','empty','limit'):
            rows=[self.row('a')]
            if change=='label':rows[0]['weight']=1
            elif change=='duplicate':rows*=2
            elif change=='fold':rows[0]['fold']=True
            elif change=='dataset':rows[0]['dataset']='unknown'
            elif change=='path':rows[0]['image_path']='data/../a.png'
            elif change=='hash':rows[0]['image_sha256']='oops'
            elif change=='group':
                rows.append(self.row('b'));rows[1].update(group_id='a',fold=1)
            elif change=='empty':rows=[]
            else:rows=[self.row(str(i)) for i in range(2001)]
            with self.subTest(change=change),self.assertRaises(ValueError):
                s.allowed_slots(rows,image_hashes={r['sample_id']:'a'*64 for r in rows})
        with self.assertRaises(ValueError):s.allowed_slots([self.row('a')],image_hashes={'a':'bad'})

    def test_exact_freeze_and_parser_sources_required(self):
        for key in ('allowed_slots_sha256','transport_cap','source_files'):
            binding=self.binding(self.slots);binding.pop(key)
            with self.assertRaises(ValueError):s.Ledger(Path(self.temp.name)/'other',binding,self.slots)
        for source in s.PARSER_SOURCES:
            binding=self.binding(self.slots);binding['source_files'][source]='bad'
            with self.assertRaises(ValueError):s.Ledger(Path(self.temp.name)/'other',binding,self.slots)

    def test_chat_namespace_independent(self):
        sid,value=self.chat()
        self.assertEqual(s.route(value)[2],'paired-portions-r11-p.1')
        old=old_hash('chat',value['payload'],'source-portions-r10-o.1')
        self.assertNotEqual(s.request_hash(value),old)
        state=self.ledger.read();state['namespace']='source-portions-r10-o.1';self.ledger.save(state)
        with self.assertRaises(ValueError):self.ledger.read()

    def test_repair_requires_actual_failure_raw_and_parser_then_exact_append(self):
        sid,value=self.chat();self.success(sid,value)
        for raw,error,parser in [('forged','bad format',self.ledger.parser_sha256),
                                 ('bad','forged',self.ledger.parser_sha256),('bad','bad format','c'*64)]:
            with self.assertRaises(ValueError):self.ledger.format_failure(sid,raw,error,parser)
        self.ledger.format_failure(sid,'bad','bad format',self.ledger.parser_sha256)
        repair=deepcopy(value);repair['payload']['messages'] += [
            {'role':'assistant','content':'bad'},{'role':'user','content':s.REPAIR+'bad format'}]
        repair_sid=s.slot_id('a','identify',1);self.expected[repair_sid]=repair
        self.ledger.bind(repair_sid,repair)
        forged=deepcopy(repair);forged['payload']['messages'][-2]['content']='forged';self.expected[repair_sid]=forged
        with self.assertRaises(ValueError):self.ledger.bind(repair_sid,forged)

    def test_valid_raw_never_gets_repair_and_success_is_permanent(self):
        sid,value=self.chat();h,_=self.success(sid,value,'valid')
        with self.assertRaises(ValueError):self.ledger.format_failure(sid,'valid',None,self.ledger.parser_sha256)
        with self.assertRaises(ProviderStop):self.ledger.reserve(sid,h)
        restarted=s.Ledger(self.ledger.directory,self.binding(self.slots),self.slots)
        self.assertEqual(restarted.target(h)['cache']['value'],'valid')
        with self.assertRaises(ProviderStop):restarted.reserve(sid,h)

    def test_wrong_image_refused_even_when_gate_accepts(self):
        sid,value=self.chat();value['payload']['messages'][1]['content'][1]['image_url']['url']='wrong'
        with self.assertRaisesRegex(ValueError,'slot_image_changed'):self.ledger.bind(sid,value)

    def test_import_origins_are_explicit_and_embedding_only(self):
        for i,origin in enumerate(('legacy','M','O')):
            sid=s.slot_id('a',f'embed_{i:02d}',0);value=s.embedding_payload('rice')
            self.expected[sid]=value
            self.assertEqual(self.ledger.import_usage(sid,value,'a'*64,'b'*64,origin)['origin'],origin)
        sid=s.slot_id('a','embed_03',0);self.expected[sid]=value
        with self.assertRaises(ValueError):self.ledger.import_usage(sid,value,'a'*64,'b'*64,'calibrated')

    def test_cache_publication_crash_and_fatal_survive_restart(self):
        sid,value=self.chat();h,r=self.success(sid,value,'unparseable')
        self.ledger.cache_path(h).unlink()
        restarted=s.Ledger(self.ledger.directory,self.binding(self.slots),self.slots)
        with self.assertRaisesRegex(ValueError,'cache_missing'):restarted.target(h)
        restarted.recover_pending()
        self.assertEqual(restarted.target(h)['cache']['value'],'unparseable')
        self.assertEqual(restarted.target(h)['reserved'],1)
        with self.assertRaises(ProviderStop):restarted.reserve(sid,h)
        value=s.embedding_payload('fatal query');sid=s.slot_id('n','embed_01',0)
        self.expected[sid]=value;h=self.ledger.bind(sid,value);r=self.ledger.reserve(sid,h)
        self.ledger.persist(r,{'kind':'fatal','status':401,'body':None,'error_type':'authentication'})
        with self.assertRaises(ProviderStop):restarted.reserve(sid,h)

    def test_stored_repair_proof_cannot_forge_valid_answer_failure(self):
        sid,value=self.chat();self.success(sid,value,'valid')
        state=self.ledger.read();state['repairs'][sid]={'raw_hash':fingerprint('valid'),
            'error':'invented','parser_sha256':self.ledger.parser_sha256};self.ledger.save(state)
        repair=deepcopy(value);repair['payload']['messages'] += [
            {'role':'assistant','content':'valid'},{'role':'user','content':s.REPAIR+'invented'}]
        repair_sid=s.slot_id('a','identify',1);self.expected[repair_sid]=repair
        with self.assertRaisesRegex(ValueError,'not_actual_cached_failure'):self.ledger.bind(repair_sid,repair)

    def test_module_has_no_provider_or_credential_construction(self):
        import ast
        tree=ast.parse(Path(s.__file__).read_text())
        forbidden={'httpx','requests','runtime_o','service_o','read_credentials','Provider','OProvider'}
        names={node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):names.update(alias.name for alias in node.names)
            elif isinstance(node,ast.ImportFrom):
                names.add(node.module);names.update(alias.name for alias in node.names)
        self.assertFalse(names & forbidden)
        # No key is loaded: mock response model follows the requested model.
        import contextlib,io
        capture=io.StringIO()
        with contextlib.redirect_stdout(capture),contextlib.redirect_stderr(capture):
            sid,value=self.chat();self.success(sid,value)
        self.assertEqual(capture.getvalue(),'')

    def test_fixed_role_and_unchanged_official_embedding_hash(self):
        value=s.embedding_payload('synthetic food')
        self.assertEqual(s.request_hash(value),old_hash('embedding',value['payload'],'official-query-v1'))
        for change in ('model','batch','role'):
            bad=deepcopy(value)
            if change=='model':bad['payload']['model']=CHAT_MODEL
            elif change=='batch':bad['payload']['input']*=2
            else:bad['role']='chat'
            with self.assertRaises(ValueError):s.request_hash(bad)

    def test_unknown_reservations_are_not_refunded_across_slots(self):
        value=s.embedding_payload('same query')
        a,b=s.slot_id('a','embed_00',0),s.slot_id('n','embed_00',0)
        self.expected.update({a:value,b:value})
        h=self.ledger.bind(a,value);self.ledger.reserve(a,h);self.ledger.reserve(a,h)
        self.ledger.bind(b,value);self.ledger.reserve(b,h)
        with self.assertRaises(ProviderStop):self.ledger.reserve(b,h)
        self.assertEqual(self.ledger.audit()['counts']['unknown_outcomes'],3)

    def test_raw_success_recovery_without_new_reservation_or_provider(self):
        sid,value=self.chat();h=self.ledger.bind(sid,value);reservation=self.ledger.reserve(sid,h)
        body={'model':CHAT_MODEL,'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}
        outcome={'reservation':reservation,'kind':'success','status':200,'body':body,
                 'value':'ok','value_hash':fingerprint('ok'),'error_type':None}
        durable_json(self.ledger.outcome_path(reservation['id']),outcome)
        with self.assertRaisesRegex(ValueError,'unanchored_outcome'):self.ledger.target(h)
        recovered=self.ledger.target(h,recover=True)
        self.assertEqual(recovered['cache']['value'],'ok')
        self.assertEqual(recovered['cache']['role'],'chat')
        self.assertEqual(recovered['reserved'],1)
        with self.assertRaises(ProviderStop):self.ledger.reserve(sid,h)

    def test_cache_tamper_cannot_replace_successful_answer(self):
        sid,value=self.chat();h=self.ledger.bind(sid,value);reservation=self.ledger.reserve(sid,h)
        body={'model':CHAT_MODEL,'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}
        self.ledger.persist(reservation,{'kind':'success','status':200,'body':body,
                            'value':'ok','value_hash':fingerprint('ok'),'error_type':None})
        cache=s.load(self.ledger.cache_path(h));cache['value']='changed'
        durable_json(self.ledger.cache_path(h),cache)
        with self.assertRaisesRegex(ValueError,'cache_outcome'):self.ledger.target(h)

    def test_embedding_success_and_nonfinite_or_wrong_model_rejection(self):
        value=s.embedding_payload('rice');sid=s.slot_id('a','embed_00',0)
        self.expected[sid]=value;h=self.ledger.bind(sid,value);reservation=self.ledger.reserve(sid,h)
        vector=[.1]*3072
        body={'model':EMBED_MODEL,'data':[{'index':0,'embedding':vector}]}
        outcome={'kind':'success','status':200,'body':body,'value':vector,
                 'value_hash':fingerprint(vector),'error_type':None}
        self.ledger.persist(reservation,outcome)
        self.assertEqual(self.ledger.target(h)['cache']['role'],'embedding')
        for change in ('index','model','nonfinite'):
            bad=deepcopy(outcome)
            if change=='index':bad['body']['data'][0]['index']=1
            elif change=='model':bad['body']['model']=CHAT_MODEL
            else:bad['body']['data'][0]['embedding'][0]=float('nan')
            with self.assertRaises(ValueError):
                self.ledger.validate_outcome({'reservation':reservation,**bad},reservation)

    def test_fatal_outcome_cannot_acquire_another_reservation(self):
        sid,value=self.chat();h=self.ledger.bind(sid,value);reservation=self.ledger.reserve(sid,h)
        self.ledger.persist(reservation,{'kind':'fatal','status':401,'body':None,'error_type':'authentication'})
        with self.assertRaises(ProviderStop):self.ledger.reserve(sid,h)

    def test_changed_slot_payload_refused(self):
        sid,value=self.chat();self.ledger.bind(sid,value)
        changed=deepcopy(value);changed['payload']['messages'][0]['content']='different'
        self.expected[sid]=changed
        with self.assertRaisesRegex(ValueError,'slot_payload_changed'):self.ledger.bind(sid,changed)


if __name__=='__main__': unittest.main()
