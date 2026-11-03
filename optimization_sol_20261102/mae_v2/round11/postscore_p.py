#!/usr/bin/env python3
"""Fixed P postscore entry after integrated runtime/scoring review.

No runner replay or provider construction. Labels are parsed only after source-bound
scoring review and an authenticated complete zero-provider verifier capability.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

from source_census import REPO, PREFIX, bounded_read, decode, encoded, sha, require, isolated_network, _write_at

GATE=PREFIX+'round11/postscore/review_gate.json'
REVIEW=PREFIX+'round11/postscore/REVIEW.md'
LABELS=PREFIX+'round11/prepared/cohort/dev_labels.json'
OUTPUT=PREFIX+'round11/postscore/scoring/results.json'
SCIENCE_FREEZE=PREFIX+'round11/prepared/freeze.json'
SOURCES=tuple(PREFIX+p for p in ('round11/postscore_p.py','round11/scoring_p.py',
    'round11/POSTSCORE_PROTOCOL.md','round11/source_census.py','round11/records_p.py',
    'round11/context_p.py','round11/run_p.py','round11/stores_p.py','round11/service_p.py',
    'round11/verified_identity.py','round11/identity_gate_p.py','round11/runtime_p.py','round11/engine_p.py',
    'round11/adapter_p.py','round11/assets_p.py','src/opt_metrics.py','src/metrics_v2.py'))
BINDINGS={'science_sha256','manifest_sha256','labels_sha256','record_seal_sha256',
    'coding_seal_sha256','adapter_seal_sha256','model_environment_sha256',
    'matrix_sha256','request_cache_proof_sha256','source_snapshot_sha256'}


def _hash(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _review_at(root,expected):
    require(_hash(expected),'P_postscore_registered_review_receipt_required')
    raw=bounded_read(root,GATE);require(sha(raw)==expected,'P_postscore_review_receipt_changed')
    gate=decode(raw)
    require(type(gate) is dict and set(gate)=={'status','scope','unresolved_p1_p2','review_sha256','source_sha256'}
        and gate['status']=='approved_or_fixed' and gate['scope']=='P_first_integrated_postscore'
        and type(gate['unresolved_p1_p2']) is int and gate['unresolved_p1_p2']==0
        and _hash(gate['review_sha256']) and set(gate['source_sha256'])==set(SOURCES),
        'P_postscore_review_incomplete')
    require(sha(bounded_read(root,REVIEW))==gate['review_sha256'],'P_postscore_review_body_changed')
    require(all(_hash(digest) and sha(bounded_read(root,path))==digest
                for path,digest in gate['source_sha256'].items()),'P_postscore_source_changed')
    return raw


def _science_gate_at(root):
    """Derive the reviewed gate pin from the fixed completed-run science freeze.

    The integrated complete-run verifier subsequently authenticates this freeze
    against sealed stores/ledger. No self-hash or hardcoded future None pin.
    """
    raw=bounded_read(root,SCIENCE_FREEZE);science=decode(raw)
    require(type(science) is dict and science.get('schema_version')==1
            and type(science.get('source_files')) is dict,
            'P_postscore_scientific_freeze_required')
    sources=science['source_files']
    gate_relative=GATE.removeprefix(PREFIX)
    require(gate_relative in sources and _hash(sources[gate_relative])
            and all(p.removeprefix(PREFIX) in sources for p in SOURCES),
            'P_postscore_review_missing_from_science_freeze')
    gate=decode(bounded_read(root,GATE))
    require(type(gate) is dict and gate.get('source_sha256')=={
        p:sources[p.removeprefix(PREFIX)] for p in SOURCES},
        'P_postscore_science_scoring_source_pins_differ')
    review_relative=REVIEW.removeprefix(PREFIX)
    require(sources.get(review_relative)==gate.get('review_sha256'),
            'P_postscore_review_body_missing_from_science_freeze')
    fingerprint=sha(json.dumps(science,sort_keys=True,ensure_ascii=False,allow_nan=False,
                              separators=(',',':')).encode())
    return sources[gate_relative],sha(raw),fingerprint


def _verified_inputs(root):
    # Late import: scoring review/source checks precede runtime construction.
    from run_p import verify_completed
    return verify_completed()


def _validate_verified(value):
    require(type(value) is dict and set(value)=={'rows','records','catalog','strata','bindings','audit','revalidate'},
            'P_postscore_verified_capability_contract_required')
    audit=value['audit']
    require(type(audit) is dict and set(audit)=={'completed','provider_constructed','labels_parsed',
        'validation_opened','exact_records_reconstructed','all_cache_model_matrix_refs_authenticated'}
        and audit=={'completed':True,'provider_constructed':False,'labels_parsed':False,
            'validation_opened':False,'exact_records_reconstructed':True,
            'all_cache_model_matrix_refs_authenticated':True},'P_postscore_completed_blind_audit_required')
    require(type(value['bindings']) is dict and set(value['bindings'])==BINDINGS
            and all(_hash(v) for v in value['bindings'].values())
            and callable(value['revalidate']),'P_postscore_complete_seal_bindings_required')
    rows=value['rows'];records=value['records']
    require(type(rows) is list and rows and type(records) is list and len(rows)==len(records),
            'P_postscore_complete_rows_required')
    fields={'sample_id','dataset','split','group_id','fold','image_path','image_sha256'}
    indexed={}
    for row in rows:
        require(type(row) is dict and set(row)==fields and isinstance(row['sample_id'],str)
            and row['sample_id'] and row['sample_id'] not in indexed
            and row['dataset'] in ('asa24','nutrition5k') and row['split']=='dev'
            and type(row['fold']) is int and row['fold'] in range(5),'P_postscore_blind_population_invalid')
        indexed[row['sample_id']]=row
    for ds in ('asa24','nutrition5k'):
        require({r['fold'] for r in rows if r['dataset']==ds}==set(range(5)),
                'P_postscore_complete_five_fold_datasets_required')
    seen=set()
    for record in records:
        row=record['row'];sid=row['sample_id']
        require(sid not in seen and indexed.get(sid)==row and set(record['profiles'])=={'O','Q','D','Q+D'},
                'P_postscore_complete_paired_records_required');seen.add(sid)
    require(seen==set(indexed) and type(value['strata']) is dict and set(value['strata'])==seen,
            'P_postscore_complete_strata_required')


def _write_or_compare(root,value):
    output=root/OUTPUT
    require(output.resolve()==output,'P_postscore_output_link_refused')
    if output.exists():
        require(bounded_read(root,OUTPUT)==encoded(value),'P_postscore_existing_result_conflict')
        require(output.stat().st_mode&0o777==0o600 and output.parent.stat().st_mode&0o777==0o700,
                'P_postscore_private_existing_output_required')
    else:_write_at(root,OUTPUT,value)


def _postscore_at(root,*,expected_gate_sha,verifier,expected_science_sha=None,expected_science_binding=None):
    """Private fixture wiring. Production derives the pin from science freeze and uses the fixed verifier."""
    root=Path(root)
    require(root.is_absolute() and root.resolve()==root,'P_postscore_canonical_root_required')
    review=_review_at(root,expected_gate_sha)
    value=verifier(root);_validate_verified(value)
    if expected_science_sha is not None:
        require(value['bindings']['science_sha256']==expected_science_binding,
                'P_postscore_verified_science_freeze_changed')
    value['revalidate']()
    held=deepcopy({k:v for k,v in value.items() if k!='revalidate'})
    snapshot=sha(encoded(held))
    def revalidate():
        require(_review_at(root,expected_gate_sha)==review,'P_postscore_review_changed')
        if expected_science_sha is not None:
            require(_science_gate_at(root)==(expected_gate_sha,expected_science_sha,expected_science_binding),
                    'P_postscore_science_freeze_changed')
        value['revalidate']()
        require(sha(encoded({k:v for k,v in value.items() if k!='revalidate'}))==snapshot,
                'P_postscore_held_snapshot_changed')
    revalidate()
    # First and only semantic label access: fixed new-development cohort, never old
    # cohorts or sealed independent acceptance. Verify bytes BEFORE decoding.
    raw=bounded_read(root,LABELS)
    require(sha(raw)==held['bindings']['labels_sha256'],'P_postscore_development_labels_changed')
    labels=decode(raw)
    require(type(labels) is dict and set(labels)=={r['sample_id'] for r in held['rows']},
            'P_postscore_exact_development_labels_required')
    revalidate()
    import scoring_p
    scored=scoring_p.score(held['rows'],labels,held['records'],held['catalog'],strata=held['strata'])
    selected=scored['selected_profile'];final=None
    if selected is not None:
        # The score decision confirms a single eligible coherent method. Full
        # fit is a distinct artifact field; no inference freeze is rewritten.
        raw_profiles=scoring_p._prepare(held['rows'],labels,held['records'],held['catalog'],held['strata'])
        final=scoring_p.full_development_parameters(held['rows'],labels,raw_profiles[selected],held['catalog'],
            selected_profile=selected,selection_confirmed=True)
        if not scored['profiles'][selected]['calibration_retained']:
            final['postprocessor']='raw_identity'
            for ds,params in final['parameters'].items():
                if ds=='nutrition5k':params['factors']={k:1.0 for k in params['factors']}
                else:params['factor']=1.0
        else:final['postprocessor']='bounded_shrunk'
    revalidate()
    require(bounded_read(root,LABELS)==raw,'P_postscore_labels_changed_during_score')
    artifact={'schema_version':1,'status':'P_development_postscore_complete',
        'scoring_review_receipt_sha256':expected_gate_sha,'verified_input_snapshot_sha256':snapshot,
        'bindings':held['bindings'],'scoring':scored,'selected_full_development_fit':final,
        'validation_opened':False,'api_calls':0,'grants_inference_or_acceptance':False}
    _write_or_compare(root,artifact)
    return {'status':artifact['status'],'rows':len(held['rows']),'selected_profile':selected,
        'private_result_sha256':sha(encoded(artifact)),'api_calls':0,'validation_opened':False}


def main():
    require(len(sys.argv)==1,'P_postscore_cli_overrides_refused')
    require(isolated_network(Path('/proc/self/net/dev').read_bytes()),'P_postscore_isolated_network_required')
    gate_sha,science_sha,science_binding=_science_gate_at(REPO)
    return _postscore_at(REPO,expected_gate_sha=gate_sha,verifier=_verified_inputs,
                        expected_science_sha=science_sha,expected_science_binding=science_binding)


if __name__=='__main__':
    try:print(json.dumps(main(),sort_keys=True))
    except Exception as exc:
        print(json.dumps({'status':'P_postscore_refused','error_type':type(exc).__name__}))
        raise SystemExit(1)
