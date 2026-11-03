"""Rebuild registered N tasks from frozen sources and trusted upstream inputs.

No caller-supplied prompt, identity or parser declaration authorizes a task.
The quantity dependency is reconstructed from exact persisted identity answers.
"""
from copy import deepcopy
from pathlib import Path

from opt_provider import ROOT, fingerprint, sha
from opt_pipeline import ContractError, SYSTEM, encode_image
from uncertain_portions import UncertainPortionPipeline, REPAIR
from service_n import payload, request_hash, slot_id


class CapturedTask(BaseException):
    def __init__(self,messages,parser): self.messages,self.parser = messages,parser


class TaskGate:
    def __init__(self,ctx,ledger,*,root=ROOT,freeze_path=None):
        self.ctx,self.ledger,self.root = ctx,ledger,Path(root)
        self.rows = {r['sample_id']:r for r in ctx.rows}
        self.freeze_path = freeze_path
        self.freeze_sha256 = sha(freeze_path) if freeze_path is not None else None
        if ledger.binding != fingerprint(ctx.binding): raise ValueError('N_gate_freeze_binding_changed')

    def verify(self):
        self.ctx.verify_sources()
        if self.freeze_path is not None and sha(self.freeze_path) != self.freeze_sha256:
            raise ValueError('N_gate_freeze_file_changed')

    @property
    def parser_sha256(self): return self.ctx.parser_sha256

    def format_error(self,sid,raw):
        """Execute the registered parser, rather than trust a caller's error."""
        self.verify()
        if self.ledger.slots[sid]['ordinal'] != 0: raise ValueError('N_parser_failure_requires_initial_slot')
        task = self.task(sid); h = request_hash(payload(task.messages))
        if self.ledger.read()['bindings'].get(sid) != h: raise ValueError('N_parser_context_changed')
        cache = self.ledger.target(h)['cache']
        if cache is None or cache['value'] != raw: raise ValueError('N_parser_raw_not_persisted')
        try: task.parser(raw)
        except ContractError as exc: return str(exc)
        raise ValueError('N_valid_answer_cannot_acquire_repair')

    def pipeline(self,chat):
        return UncertainPortionPipeline(chat,lambda _:(_ for _ in ()).throw(AssertionError('N_gate_embedding')),
                                         self.ctx.catalog,None)

    def identity(self,row):
        """Read-only frozen-parser replay of the required earlier identity."""
        index = 0
        def chat(messages):
            nonlocal index
            sid = slot_id(row['sample_id'],'N_identity',index)
            state = self.ledger.read(); h = request_hash(payload(messages))
            if state['bindings'].get(sid) != h: raise ValueError('N_units_before_registered_identity')
            cache = self.ledger.target(h)['cache']
            if cache is None: raise ValueError('N_units_before_completed_identity')
            index += 1
            return cache['value']
        def failure(stage,raw,error):
            proof = {'raw_hash':fingerprint(raw),'error':str(error),'parser_sha256':self.ctx.parser_sha256}
            state = self.ledger.read(); sid = slot_id(row['sample_id'],'N_identity',0)
            if state['repairs'].get(sid) != proof: raise ValueError('N_identity_dependency_repair_changed')
        p = self.pipeline(chat); p.on_format_failure = failure
        base = self.ctx.imported['records'][row['sample_id']]['identity']
        identity = p.identify_uncertain(self.root/row['image_path'],base)
        if identity['status'] != 'ok': raise ValueError('N_units_requires_successful_identity')
        return identity

    def task(self,sid):
        meta = self.ledger.slots.get(sid)
        if meta is None: raise ValueError('N_unknown_registered_task')
        row = self.rows[meta['sample_id']]
        p = self.pipeline(lambda _:(_ for _ in ()).throw(AssertionError('N_gate_must_not_chat')))
        def capture(name,prompt,images,parser,stages):
            if name != meta['stage']: raise ValueError('N_registered_stage_changed')
            images = [images] if isinstance(images,str) else (images or [])
            messages = [{'role':'system','content':SYSTEM},{'role':'user','content':
                [{'type':'text','text':prompt}]+[{'type':'image_url','image_url':{'url':i}} for i in images]}]
            raise CapturedTask(messages,parser)
        p._stage = capture
        base = self.ctx.imported['records'][row['sample_id']]['identity']
        try:
            if meta['stage'] == 'N_identity': p.identify_uncertain(self.root/row['image_path'],base)
            else: p.unit_portion(self.root/row['image_path'],self.identity(row),base)
        except CapturedTask as captured: return captured
        raise ValueError('N_registered_task_has_no_request')

    def validate(self,sid,value):
        self.verify()
        task = self.task(sid)
        # Repairs retain the exact registered initial request and are checked
        # against a separately proved parser failure by the ledger.
        initial = {**value,'messages':value['messages'][:2]}
        if initial != payload(task.messages): raise ValueError('N_unregistered_prompt_or_context')
        if self.ledger.slots[sid]['ordinal'] == 0 and value != initial:
            raise ValueError('N_initial_task_message_order_changed')
        if self.ledger.slots[sid]['ordinal'] == 1:
            meta = self.ledger.slots[sid]
            initial_sid = slot_id(meta['sample_id'],meta['stage'],0)
            state = self.ledger.read()
            cache = self.ledger.target(request_hash(payload(task.messages)))['cache']
            if cache is None: raise ValueError('N_repair_without_initial_raw')
            error = self.format_error(initial_sid,cache['value'])
            proof = {'raw_hash':cache['value_hash'],'error':error,'parser_sha256':self.parser_sha256}
            expected = task.messages + [{'role':'assistant','content':cache['value']},
                {'role':'user','content':REPAIR+error}]
            if state['repairs'].get(initial_sid) != proof or value != payload(expected):
                raise ValueError('N_repair_not_proved_by_frozen_parser')
        return task


def frozen_gate(ledger):
    # Direct NProvider/Ledger callers use the SAME frozen context as the CLI.
    # There is no production hook accepting arbitrary user context/verifiers.
    from context_n import runtime_context, PREPARED
    ctx = runtime_context()
    if ctx.ledger.slots != ledger.slots: raise ValueError('N_gate_slot_universe_changed')
    return TaskGate(ctx,ledger,freeze_path=PREPARED/'freeze.json')
