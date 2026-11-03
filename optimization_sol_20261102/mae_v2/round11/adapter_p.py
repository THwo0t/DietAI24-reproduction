"""Isolated offline P ASA projection after complete verified blind coding.

No provider, scoring, calibration or fallback fitting. The fixed reviewed runner
invokes this in a Linux user/network namespace with a clean environment.
Portable Mac isolation and real Mac hardware acceptance remain unimplemented.
"""
from copy import deepcopy
from pathlib import Path
import json
import hashlib
import os
import sys

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10'),str(BASE/'round11')]

from opt_pipeline import _code,validate_options
from opt_provider import fingerprint,ROOT
from round4.src.artifacts import decode
from verified_identity import VerifiedIdentitySnapshot,checked_file


def code_only(labels,rows):
    """The only semantic label access is food_code for ASA rows."""
    if type(labels) is not dict or set(labels)!={r['sample_id'] for r in rows}:
        raise ValueError('P_adapter_label_population_changed')
    return {r['sample_id']:_code(labels[r['sample_id']]['food_code'])
            for r in rows if r['dataset']=='asa24'}


def contexts_after_seal(rows,identities,catalog,code_map,proof):
    if (type(proof) is not dict or proof.get('complete') is not True
            or proof.get('identity_records_sha256')!=fingerprint(identities)
            or type(proof.get('coding_completion_sha256')) is not str
            or len(proof['coding_completion_sha256'])!=64
            or set(identities)!={r['sample_id'] for r in rows}):
        raise ValueError('P_complete_all_identity_seal_required_before_conditional')
    asa={r['sample_id'] for r in rows if r['dataset']=='asa24'}
    if set(code_map)!=asa:raise ValueError('P_adapter_code_population_changed')
    contexts={}
    for sid in sorted(asa):
        code=_code(code_map[sid]);identity=identities[sid]
        if code not in identity.get('final_codes',[]):continue
        if identity.get('status')!='ok':raise ValueError('P_failed_identity_contains_conditional_code')
        contexts[sid]={'code':code,'options':deepcopy(validate_options(catalog['asa_options'][code]))}
    return contexts


def _prepare(ctx,snapshot,labels_path,store,*,coding_completion_path,data_root):
    """Private synthetic/integration seam; never opens labels before full proof."""
    if type(snapshot) is not VerifiedIdentitySnapshot:
        raise ValueError('P_adapter_verified_snapshot_required')
    identities,proof=snapshot.revalidate_full()
    if (proof.get('science_binding_sha256')!=fingerprint(ctx.binding)
            or proof.get('rows_sha256')!=fingerprint(ctx.rows)
            or proof.get('catalog_sha256')!=fingerprint(ctx.catalog)):
        raise ValueError('P_adapter_snapshot_context_changed')
    seal=checked_file(coding_completion_path)
    if proof.get('coding_completion_sha256')!=seal:
        raise ValueError('P_adapter_coding_seal_changed')
    root=Path(data_root)
    if not root.is_absolute() or root.resolve()!=root:raise ValueError('P_adapter_data_root_changed')
    path=Path(labels_path)
    relative='round11/prepared/cohort/dev_labels.json'
    if path!=root/relative or ctx.binding['source_files'].get(relative)!=ctx.binding['labels_sha256']:
        raise ValueError('P_adapter_label_source_path_changed')
    expected_binding={'science':ctx.binding,'coding_completion_sha256':seal,
        'labels_sha256':ctx.binding['labels_sha256'],'role':'post_coding_ASA_code_and_full_catalogue_only'}
    if store.binding!=expected_binding:raise ValueError('P_adapter_store_binding_changed')
    if checked_file(path)!=ctx.binding['labels_sha256']:
        raise ValueError('P_adapter_label_binding_changed')
    from context_p import _read
    raw=_read(root,relative)
    if hashlib.sha256(raw).hexdigest()!=ctx.binding['labels_sha256']:
        raise ValueError('P_adapter_label_bytes_changed')
    labels=decode(raw);del raw
    contexts=contexts_after_seal(ctx.rows,identities,ctx.catalog,code_only(labels,ctx.rows),proof)
    del labels
    if checked_file(path)!=ctx.binding['labels_sha256']:
        raise ValueError('P_adapter_labels_changed_during_projection')
    snapshot.revalidate_full()
    if checked_file(coding_completion_path)!=seal:raise ValueError('P_adapter_coding_seal_changed')
    provenance={'coding_completion_sha256':seal,'labels_sha256':ctx.binding['labels_sha256'],
        'identity_records_sha256':proof['identity_records_sha256'],
        'adapter_source_sha256':checked_file(Path(__file__).resolve()),
        'input_rows':len(ctx.rows),'Exact_contexts':len(contexts),'permitted_fields':['code','options'],
        'current_portion_truth_exported':False,'api_calls':0,'validation_opened':False}
    values={'contexts':contexts,'provenance':provenance}
    if (store.directory/'completion.json').is_file():
        if store.verify_completed()!=values:raise ValueError('P_existing_adapter_projection_changed')
    else:store.finalize(values)
    return {'status':'P_conditional_adapter_sealed','Exact_contexts':len(contexts),'api_calls':0,
            'current_portion_truth_exported':False,'validation_opened':False}


CLEAN_ENV={'PATH':os.defpath,'LANG':'C.UTF-8','LC_ALL':'C.UTF-8',
           'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}


def _isolation_check():
    from source_census import isolated_network
    if not sys.platform.startswith('linux'):
        raise ValueError('P_adapter_Linux_network_namespace_required_portable_fallback_unimplemented')
    if dict(os.environ)!=CLEAN_ENV:
        raise ValueError('P_adapter_clean_environment_required')
    if not isolated_network(Path('/proc/net/dev').read_bytes()):
        raise ValueError('P_adapter_isolated_network_required')


def prepare():
    """Fixed offline child entry. No public paths, labels or context overrides."""
    _isolation_check()
    from context_p import runtime_context
    from service_p import Ledger,allowed_slots
    from identity_gate_p import coding_snapshot
    from stores_p import adapter_store
    ctx=runtime_context()
    ledger=Ledger(ROOT/'round11/provider/P',ctx.binding,allowed_slots(ctx.rows))
    ledger.read();snapshot=coding_snapshot(ctx,ledger)
    return _prepare(ctx,snapshot,ROOT/'round11/prepared/cohort/dev_labels.json',adapter_store(ctx),
        coding_completion_path=ROOT/'round11/runs/identities/completion.json',data_root=ROOT)


def main():
    if len(sys.argv)!=1:raise ValueError('P_adapter_no_arguments_allowed')
    return prepare()


if __name__=='__main__':
    try:print(json.dumps(main(),sort_keys=True))
    except (Exception,SystemExit):
        # Never print labels, paths, exception details or inherited credentials.
        print(json.dumps({'status':'P_adapter_refused_preserve_state'}))
        raise SystemExit(1)
