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
    records=identity_store(ctx).verify_completed()
    verify_proof(ledger,records['service-proof'])
    identities={r['sample_id']:records[name('identity',r)] for r in ctx.rows}
    return identities,{'complete':True,'identity_records_sha256':fingerprint(identities)}


def adapter_store(ctx):
    binding={'science':ctx.binding,'coding_completion_sha256':sha(ROUND/'runs/identities/completion.json'),
             'labels_sha256':ctx.binding['labels_sha256'],'role':'post_coding_ASA_code_and_full_catalogue_only'}
    return ArtifactStore(ROUND/'runs/conditional-adapter',binding,['contexts','provenance'],
                         verify_sources=ctx.verify_sources,root=ROUND)


def sealed_contexts(ctx):
    values=adapter_store(ctx).verify_completed()
    require(values['provenance']['coding_completion_sha256']==sha(ROUND/'runs/identities/completion.json')
            and values['provenance']['labels_sha256']==ctx.binding['labels_sha256'],
            'P_conditional_adapter_provenance_changed')
    return values['contexts']
