"""Fork-only transport ownership around the unchanged P scientific row stages.

The parent configures verified original objects before each pool is forked.
Only the private test seam accepts a different root or trace constructor.
"""
import atexit
from copy import deepcopy
import os
from multiprocessing.util import Finalize
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(BASE), str(BASE/'src'), str(BASE/'round7/src'),
               str(BASE/'round8/src'), str(BASE/'round10'), str(BASE/'round11')]

from opt_provider import ROOT, fingerprint, sha
from engine_p import RowLive, RowReplay, identify, portions, quantity, density
from runtime_p import Trace
from run_p import cached, require
from stores_p import name, proof_for_refs
from records_p import compose_record, attach_conditional

_STATE = None
_TRACE = None
_WORKER_PID = None


def _verify_context_origin(ctx):
    import context_p
    from types import CodeType
    expected = [code for code in context_p._context.__code__.co_consts
                if isinstance(code, CodeType) and code.co_name == 'verify_sources']
    verify = ctx.verify_sources
    require(len(expected) == 1 and getattr(verify, '__code__', None) is expected[0]
            and getattr(verify, '__globals__', None) is vars(context_p),
            'P_parallel_context_origin_changed')
    closure = dict(zip(verify.__code__.co_freevars,
                       (cell.cell_contents for cell in verify.__closure__)))
    require(closure.get('root') == ROOT, 'P_parallel_context_root_changed')


def _engineering_check(engineering):
    from p_parallel_registration import verify_engineering
    return verify_engineering(engineering)


def configure(ctx, ledger, identity_store, final_store, id_complete, complete,
              snapshot=None, contexts=None, engineering=None, *, allow_paid=False):
    """Fixed-root parent setup; never constructs a transport or a Provider."""
    _verify_context_origin(ctx)
    _configure(ctx, ledger, identity_store, final_store, id_complete, complete,
               snapshot, contexts, engineering, allow_paid, ROOT, Trace,
               _engineering_check, False)


def _configure(ctx, ledger, ids, out, id_complete, complete, snapshot, contexts,
               engineering, allow_paid, root, trace_factory, verifier, synthetic):
    global _STATE
    require(_TRACE is None, 'P_parallel_parent_must_not_own_transport')
    require(type(allow_paid) is bool and type(id_complete) is bool and type(complete) is bool,
            'P_parallel_explicit_flags_required')
    require(not complete or id_complete, 'P_final_without_complete_coding')
    require(ledger.binding == fingerprint(ctx.binding), 'P_runner_ledger_science_binding_changed')
    require(ids.binding == ctx.binding and out.binding == ctx.binding,
            'P_runner_artifact_science_binding_changed')
    verifier(engineering)
    ctx.verify_sources()
    _STATE = dict(ctx=ctx, ledger=ledger, ids=ids, out=out, id_complete=id_complete,
                  complete=complete, snapshot=snapshot, contexts=deepcopy(contexts),
                  engineering=deepcopy(engineering), allow_paid=allow_paid and not complete,
                  root=Path(root), trace_factory=trace_factory, verifier=verifier,
                  synthetic=synthetic, parent_pid=os.getpid(), binding=fingerprint(ctx.binding),
                  rows={row['sample_id']:deepcopy(row) for row in ctx.rows})


def _configure_for_test(ctx, ledger, ids, out, id_complete=False, complete=False,
                        snapshot=None, contexts=None, engineering=None, *,
                        root, trace_factory, verifier=lambda value: True):
    """Synthetic-only dependency seam, deliberately absent from controller API."""
    _configure(ctx, ledger, ids, out, id_complete, complete, snapshot, contexts,
               engineering, False, root, trace_factory, verifier, True)


def close_worker():
    global _TRACE, _WORKER_PID
    if _TRACE is not None:
        require(_WORKER_PID == os.getpid(), 'P_parallel_inherited_transport_forbidden')
        try:
            _TRACE.close()
        finally:
            _TRACE = None
            _WORKER_PID = None


def initialize_forked_worker():
    """Each child owns its lazy Trace and eventual HTTP client independently."""
    global _TRACE, _WORKER_PID
    require(_STATE is not None and _TRACE is None, 'P_parallel_unconfigured_or_inherited_trace')
    state = _STATE
    require(state['synthetic'] or state['parent_pid'] != os.getpid(),
            'P_parallel_fork_required')
    _verify_state()
    gate = state['ledger'].task_gate()  # Keep the original Gate and Ledger.
    if state['snapshot'] is not None:
        gate.identity_loader = state['snapshot'].load
    if state['contexts'] is not None:
        gate.context_loader = lambda: deepcopy(state['contexts'])
    ctx = state['ctx']
    _TRACE = state['trace_factory'](state['ledger'], ctx.imports,
                                    ctx.manifest_sha256, allow_paid=state['allow_paid'])
    require(not state['complete'] or _TRACE.provider is None,
            'P_complete_replay_requires_zero_provider')
    _WORKER_PID = os.getpid()
    atexit.register(close_worker)
    # multiprocessing children use os._exit and skip Python atexit callbacks.
    if not state['synthetic']:
        Finalize(None, close_worker, exitpriority=10)


def _verify_state(row=None):
    require(_STATE is not None, 'P_parallel_worker_unconfigured')
    state = _STATE
    state['verifier'](state['engineering'])
    ctx = state['ctx']
    if not state['synthetic']:
        _verify_context_origin(ctx)
    require(fingerprint(ctx.binding) == state['binding'], 'P_parallel_science_binding_changed')
    ctx.verify_sources()
    if row is not None:
        require(state['rows'].get(row.get('sample_id')) == row, 'P_parallel_row_changed')
        require(_TRACE is not None and _WORKER_PID == os.getpid(),
                'P_parallel_child_trace_required')
    return state


def _stage(state, store, sealed, stem, row, operation, inputs, all_refs):
    ctx, ledger = state['ctx'], state['ledger']
    def validate(envelope):
        require(type(envelope) is dict and set(envelope) == {'result', 'request_refs'},
                'P_scientific_envelope_changed')
        replay = operation(RowReplay(row, ledger, ctx.imports, ctx.manifest_sha256,
                                     envelope['request_refs']))
        require(replay == envelope, 'P_exact_scientific_replay_changed')
        return envelope
    envelope = cached(store, sealed, stem, inputs,
                      lambda: operation(RowLive(row, _TRACE)), validate)
    for phase, refs in envelope['request_refs'].items():
        all_refs[stem+'-'+phase] = deepcopy(refs)
    return envelope


def identity_task(row):
    state = _verify_state(row)
    ctx = state['ctx']
    envelope = _stage(state, state['ids'], state['id_complete'], name('identity', row), row,
        lambda client: identify(ctx, row, client, root=state['root']),
        {'row_sha256':fingerprint(row), 'image_sha256':row['image_sha256']}, {})
    return {'envelope':envelope, 'provider_constructed':_TRACE.provider is not None}


def prediction_task(row, identity, identity_envelope, identity_seal,
                    fallback_proof, optional_context=None):
    state = _verify_state(row)
    ctx, ledger = state['ctx'], state['ledger']
    require(identity_envelope['result'] == identity, 'P_parallel_identity_changed')
    require(state['snapshot'] is not None, 'P_parallel_verified_identity_snapshot_required')
    identities, proof = state['snapshot'].load()
    require(identities.get(row['sample_id']) == identity and
            proof['coding_completion_sha256'] == identity_seal and
            sha(state['ids'].directory/'completion.json') == identity_seal,
            'P_parallel_identity_seal_changed')
    require(fallback_proof == ctx.fallbacks['folds'][row['dataset']][str(row['fold'])],
            'P_parallel_fallback_changed')
    contexts = state['contexts'] or {}
    require(optional_context == contexts.get(row['sample_id']), 'P_parallel_context_changed')
    stem = name('record', row)
    inputs = {'row_sha256':fingerprint(row), 'identity_sha256':fingerprint(identity),
              'coding_completion_sha256':identity_seal}
    all_refs, stage_envelopes = {}, {}
    if identity.get('status') == 'ok':
        for kind, operation in [('whole', portions), ('quantity', quantity), ('density', density)]:
            stage_envelopes[kind] = _stage(state, state['out'], state['complete'], stem+'-'+kind,
                row, lambda client, op=operation: op(ctx, row, identity, client, root=state['root']),
                inputs, all_refs)
    else:
        stage_envelopes = {kind:None for kind in ('whole', 'quantity', 'density')}
    row_refs = {}
    for kind, envelope in [('identity', identity_envelope)]+list(stage_envelopes.items()):
        if envelope is not None:
            for phase, refs in envelope['request_refs'].items():
                row_refs[kind+'-'+phase] = refs
    record = compose_record(row, identity_envelope, stage_envelopes['whole'],
        stage_envelopes['quantity'], stage_envelopes['density'], ctx.catalog, fallback_proof['value'],
        evidence_binding={'row_sha256':fingerprint(row), 'identity_seal_sha256':identity_seal,
            'request_proof_sha256':fingerprint(proof_for_refs(ledger, row_refs)),
            'fallback_binding_sha256':fingerprint({'science':ctx.binding, 'dataset':row['dataset'],
                'fold':row['fold'], 'training_fold':fallback_proof})})
    if optional_context is not None:
        context = optional_context
        conditional = _stage(state, state['out'], state['complete'], stem+'-conditional', row,
            lambda client: portions(ctx, row, identity, client, conditional_context=context,
                                    root=state['root']),
            {**inputs, 'task_context_sha256':fingerprint(context)}, all_refs)
        refs = {phase:group for phase, group in conditional['request_refs'].items()}
        record = attach_conditional(record, conditional, context, ctx.catalog, adapter_binding={
            'identity_seal_sha256':identity_seal, 'context_sha256':fingerprint(context),
            'request_proof_sha256':fingerprint(proof_for_refs(ledger, refs))})
    def validate_record(old):
        require(old == record, 'P_completed_record_changed')
        return old
    cached(state['out'], state['complete'], stem+'-record', inputs,
           lambda:deepcopy(record), validate_record)
    return {'record':record, 'all_refs':all_refs, 'provider_constructed':_TRACE.provider is not None}
