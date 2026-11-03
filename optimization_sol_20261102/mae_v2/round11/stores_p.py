"""P's separate coding, conditional-adapter and complete-prediction seals."""
from copy import deepcopy

from opt_provider import ROOT,sha,fingerprint
from pathlib import Path

ROUND = Path(__file__).resolve().parent

def require(condition,code):
    if not condition:raise ValueError(code)

from round4.src.artifacts import ArtifactStore
from service_p import load


def name(prefix,row):return prefix+'-'+fingerprint(row['sample_id'])[:32]


def identity_store(ctx):
    return ArtifactStore(ROUND/'runs/identities',ctx.binding,
        [name('identity',r) for r in ctx.rows]+['service-proof'],
        verify_sources=ctx.verify_sources,root=ROUND)


def final_store(ctx):
    return ArtifactStore(ROUND/'runs/development',ctx.binding,
        [name('record',r) for r in ctx.rows]+['service-proof'],
        verify_sources=ctx.verify_sources,root=ROUND)


def proof_for_refs(ledger,refs):
    require(type(refs) is dict and all(type(group) is list for group in refs.values()),
            'P_reference_groups_invalid')
    flat=[ref for group in refs.values() for ref in group]
    fields={'slot','payload_hash','value_hash','reservation_id','cache_present_before','origin'}
    for ref in flat:
        require(type(ref) is dict and set(ref)==(fields | ({'manifest_sha256'} if ref.get('origin') in ('legacy','M','O') else set()))
                and type(ref.get('cache_present_before')) is bool,'P_reference_schema_changed')
    state=ledger.read();bindings={};hashes=set();files={}
    for ref in flat:
        sid,h=ref['slot'],ref['payload_hash']
        if ref['origin']=='new_P':
            require(state['bindings'].get(sid)==h,'P_identity_request_binding_changed')
            cached=ledger.target(h)['cache']
            require(cached is not None and cached['reservation_id']==ref['reservation_id']
                    and cached['value_hash']==ref['value_hash'],'P_identity_request_value_changed')
            bindings[sid]=h;hashes.add(h)
            files['responses/'+h+'.json']=sha(ledger.cache_path(h))
        else:
            require(ref.get('origin') in ('legacy','M','O'),'P_unknown_reference_origin')
            path=ledger.path('imports/'+sid+'.json')
            usage=load(path)
            require(set(usage)=={'slot','payload_hash','manifest_sha256','value_hash','origin'}
                    and all(usage[k]==ref.get(k) for k in usage)
                    and ref.get('reservation_id') is None and ref.get('cache_present_before') is True,
                    'P_identity_import_usage_changed')
            ledger.task_gate().verify_import(usage)
            files['imports/'+sid+'.json']=sha(path)
    reservations=[r for r in state['reservations'] if r['payload_hash'] in hashes]
    anchors={}
    for reservation in reservations:
        rid=reservation['id']
        if rid in state['outcomes']:
            anchors[rid]=state['outcomes'][rid]
            files['outcomes/'+rid+'.json']=sha(ledger.outcome_path(rid))
    return {'bindings':bindings,'reservations':deepcopy(reservations),'outcomes':anchors,
            'files':files,'request_refs_sha256':fingerprint(refs),'logical_answers':len(flat)}


def verify_proof(ledger,proof):
    require(type(proof) is dict and set(proof)=={'bindings','reservations','outcomes','files',
            'request_refs_sha256','logical_answers'},'P_proof_schema_changed')
    state=ledger.read()
    require(all(state['bindings'].get(sid)==h for sid,h in proof['bindings'].items()),
            'P_sealed_identity_bindings_changed')
    hashes=set(proof['bindings'].values())
    require([r for r in state['reservations'] if r['payload_hash'] in hashes]==proof['reservations'],
            'P_sealed_identity_reservations_changed')
    require(all(state['outcomes'].get(rid)==h for rid,h in proof['outcomes'].items()),
            'P_sealed_identity_outcome_anchors_changed')
    for relative,expected in proof['files'].items():
        path=ledger.path(relative)
        require(sha(path)==expected,'P_sealed_identity_service_file_changed')
        if relative.startswith('imports/'):
            ledger.task_gate().verify_import(load(path))
    return True


def sealed_identities(ctx,ledger):
    from identity_gate_p import coding_snapshot
    return coding_snapshot(ctx,ledger).load()


def adapter_store(ctx):
    binding={'science':ctx.binding,'coding_completion_sha256':sha(ROUND/'runs/identities/completion.json'),
             'labels_sha256':ctx.binding['labels_sha256'],'role':'post_coding_ASA_code_and_full_catalogue_only'}
    return ArtifactStore(ROUND/'runs/conditional-adapter',binding,['contexts','provenance'],
                         verify_sources=ctx.verify_sources,root=ROUND)


def verified_contexts(ctx,ledger,snapshot,store):
    """Full coding-snapshot evidence plus exact sealed adapter provenance."""
    from verified_identity import VerifiedIdentitySnapshot
    require(type(snapshot) is VerifiedIdentitySnapshot,'P_verified_coding_snapshot_required')
    identities,proof=snapshot.load();values=store.verify_completed()
    require(type(values) is dict and set(values)=={'contexts','provenance'},'P_adapter_record_schema_changed')
    provenance=values['provenance'];seal=proof['coding_completion_sha256']
    fields={'coding_completion_sha256','labels_sha256','identity_records_sha256','adapter_source_sha256',
            'input_rows','Exact_contexts','permitted_fields','current_portion_truth_exported','api_calls','validation_opened'}
    require(type(provenance) is dict and set(provenance)==fields and proof['complete'] is True and
        proof['science_binding_sha256']==fingerprint(ctx.binding) and proof['rows_sha256']==fingerprint(ctx.rows) and
        proof['catalog_sha256']==fingerprint(ctx.catalog) and provenance['coding_completion_sha256']==seal and
        provenance['labels_sha256']==ctx.binding['labels_sha256'] and
        provenance['identity_records_sha256']==fingerprint(identities) and
        provenance['adapter_source_sha256']==sha(Path(__file__).with_name('adapter_p.py')) and
        type(provenance['input_rows']) is int and provenance['input_rows']==len(ctx.rows) and
        provenance['permitted_fields']==['code','options'] and provenance['current_portion_truth_exported'] is False and
        type(provenance['api_calls']) is int and provenance['api_calls']==0 and provenance['validation_opened'] is False,
        'P_adapter_provenance_changed')
    contexts=values['contexts'];rows={r['sample_id']:r for r in ctx.rows}
    require(type(contexts) is dict and type(provenance['Exact_contexts']) is int and
            provenance['Exact_contexts']==len(contexts),'P_adapter_exact_count_changed')
    require(store.binding=={'science':ctx.binding,'coding_completion_sha256':seal,
            'labels_sha256':ctx.binding['labels_sha256'],'role':'post_coding_ASA_code_and_full_catalogue_only'},
            'P_adapter_store_binding_changed')
    for sid,context in contexts.items():
        require(sid in rows and rows[sid]['dataset']=='asa24' and identities[sid].get('status')=='ok' and
                type(context) is dict and set(context)=={'code','options'} and
                context['code'] in identities[sid]['final_codes'] and
                context['options']==ctx.catalog['asa_options'][context['code']], 'P_adapter_context_changed')
    return deepcopy(contexts)


def sealed_contexts(ctx,ledger):
    from identity_gate_p import coding_snapshot
    return verified_contexts(ctx,ledger,coding_snapshot(ctx,ledger),adapter_store(ctx))
