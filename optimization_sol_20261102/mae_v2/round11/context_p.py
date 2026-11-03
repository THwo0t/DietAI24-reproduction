"""Provisional P context reader. No preparation, fitting, labels or paid entry.

The artifacts described here do not yet exist. Only an independently reviewed
complete new-cohort freeze can make this reader operational.
"""
from copy import deepcopy
import hashlib
import math
import os
from pathlib import Path
import platform
import stat
from importlib.metadata import version
from types import SimpleNamespace

from opt_provider import ROOT, fingerprint, CHAT_MODEL, EMBED_MODEL, CHAT_URL, EMBED_URL
from round4.src.artifacts import decode
from service_p import allowed_slots, NAMESPACE, PARSER_SOURCES

ROUND = ROOT/'round11'
TARGETS = {'weight','energy','fat','carbs','protein'}
MAX_BYTES = 32*1024*1024
VECTOR_DIGEST_MAX_BYTES = 96*1024*1024
VECTOR_PATH = 'data/vectors/embeddings.npy'
REQUIRED = set(PARSER_SOURCES) | {
    'round11/verified_identity.py','round11/assets_p.py','round11/records_p.py','round11/run_p.py','round11/identity_gate_p.py',
    'round11/adapter_p.py','round11/prepare_p.py','round11/source_scope_v3.py','round11/capacity_cohort_v4.py',
    'round11/asa_expansion_v3.py','round11/training_identity.py','round11/caller_registration.py',
    'round11/lineage_pool_v3.py','round11/cohort_lineage_v3.py','round11/n5_identity.py',
    'round11/asa_phase_graph.py','round11/asa_content_identity.py','round11/asa_identity.py',
    'round11/development_identity.py','round11/source_capture.py','round11/source_census.py','round11/n5_sources.py',
    'round11/PREPARATION_PROTOCOL.md','round11/preparation/preparation_review_gate.json',
    'round11/preparation/PREPARATION_REVIEW.md','round11/source_role_audit.py',
    'round11/source_inventory_capture.py','round11/asa_workbook.py','round11/asa_tables.py',
    'round11/asa_eligibility.py','round11/asa_archive.py','round11/asa_role_sources.py',
    'round11/n5_preparation.py','round11/n5_pool.py','round11/qualification.py',
    'round11/CAPACITY_AMENDMENT.md','round11/preparation/SOURCE_DISPOSITION_DESIGN.md',
    'round11/preparation/CALLER_COVERAGE_DESIGN.md','round11/COHORT_REPAIR_DESIGN.md',
    'round11/context_p.py','round11/runtime_p.py','round11/stores_p.py','round11/engine_p.py',
    'round11/paired_failure.py','round11/paired_stage_pipeline.py','round11/paired_accounting.py',
    'round11/DESIGN.md','round11/PAIRED_CONTEXT_DESIGN.md','round11/PAIRED_FAILURE_DESIGN.md',
    'round11/PAIRED_ASA_ADAPTER_DESIGN.md','round11/REVIEW.md','round11/review_gate.json',
    'round11/INTEGRITY_CACHE_PROTOCOL.md','round11/integrity_review/REVIEW.md',
    'src/opt_provider.py','src/opt_pipeline.py','src/pipeline_v2.py',
    'round7/src/context_m.py','round7/src/historical_m.py','round7/src/service_m.py',
    'round7/src/runtime_m.py','round8/src/uncertain_portions.py','round4/src/artifacts.py'}
ROLES = {'manifest':'round11/prepared/cohort/dev.json',
         'labels':'round11/prepared/cohort/dev_labels.json',
         'lineage':'round11/prepared/cohort/lineage.json',
         'cohort_freeze':'round11/prepared/cohort/freeze.json',
         'fallbacks':'round11/prepared/fallbacks.json',
         'calibration':'round11/prepared/calibration.json',
         'embeddings':'round11/prepared/embeddings.json'}


def require(ok,code):
    if not ok:raise ValueError(code)


def _hash(v):return type(v) is str and len(v)==64 and all(c in '0123456789abcdef' for c in v)


def _read(root,relative,*,digest_only=False):
    """Walk every component with openat/O_NOFOLLOW, bounded regular files only."""
    require(type(relative) is str and relative and '\\' not in relative,'P_path_invalid')
    limit=VECTOR_DIGEST_MAX_BYTES if digest_only and relative==VECTOR_PATH else MAX_BYTES
    parts=relative.split('/')
    require(all(p not in ('','.','..') for p in parts) and not relative.startswith('/'),'P_path_invalid')
    root=Path(root)
    require(root.resolve()==root and not root.is_symlink(),'P_root_invalid')
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=nxt
        filefd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            info=os.fstat(filefd)
            require(stat.S_ISREG(info.st_mode) and 0<info.st_size<=limit,'P_file_invalid')
            chunks=[];h=hashlib.sha256();size=0
            while True:
                chunk=os.read(filefd,65536)
                if not chunk:break
                size+=len(chunk);require(size<=limit,'P_file_too_large');h.update(chunk)
                if not digest_only:chunks.append(chunk)
            require(size==info.st_size,'P_file_changed_during_read')
            return h.hexdigest() if digest_only else b''.join(chunks)
        finally:os.close(filefd)
    finally:os.close(fd)


def environment():
    return {'python':platform.python_version(),
            'packages':{p:version(p) for p in ('numpy','Pillow','httpx')},
            'model':{'chat':CHAT_MODEL,'embedding':EMBED_MODEL,'chat_url':CHAT_URL,'embedding_url':EMBED_URL,
                     'temperature':1,'max_completion_tokens':8192,'image_transform':'square256'}}


def _load(root,path):return decode(_read(root,path))


def _members(rows,dataset,fold,training):
    return sorted(r['sample_id'] for r in rows if r['dataset']==dataset and
                  ((r['fold']!=fold) if training else (r['fold']==fold)))


def _validate_training(bundle,rows,common,kind):
    require(type(bundle) is dict and set(bundle)=={'schema_version','role','manifest_sha256','labels_sha256',
            'cohort_freeze_sha256','folds'} and bundle['schema_version']==1 and bundle['role']==kind,
            'P_training_schema_changed')
    require(bundle['manifest_sha256']==common['hashes']['manifest'] and
            bundle['labels_sha256']==common['hashes']['labels'] and
            bundle['cohort_freeze_sha256']==common['hashes']['cohort_freeze'],'P_training_source_changed')
    require(set(bundle['folds'])=={'asa24','nutrition5k'},'P_training_datasets_changed')
    for ds in ('asa24','nutrition5k'):
        require(set(bundle['folds'][ds])==set(map(str,range(5))),'P_training_folds_changed')
        for f in range(5):
            proof=bundle['folds'][ds][str(f)]
            require(type(proof) is dict and set(proof)=={'train_ids','heldout_ids','train_groups','heldout_groups','value'},
                    'P_training_proof_schema_changed')
            train=_members(rows,ds,f,True);held=_members(rows,ds,f,False)
            groups=lambda ids:sorted({r['group_id'] for r in rows if r['sample_id'] in ids})
            require(train and held and proof['train_ids']==train and proof['heldout_ids']==held and
                    proof['train_groups']==groups(train) and proof['heldout_groups']==groups(held) and
                    not set(proof['train_groups'])&set(proof['heldout_groups']),'P_training_fold_leakage')
            value=proof['value']
            if kind=='componentwise_training_medians':
                require(type(value) is dict and set(value)==TARGETS and all(type(v) in (int,float) and
                        math.isfinite(v) and v>=0 for v in value.values()),'P_fallback_vector_invalid')
            else:
                require(type(value) is dict and set(value)=={'enabled','status','multipliers'} and
                        value['enabled'] is False and value['status']=='preregistered_disabled_identity' and
                        type(value['multipliers']) is dict and set(value['multipliers'])==TARGETS and
                        all(type(v) in (int,float) and v==1 for v in value['multipliers'].values()),
                        'P_inference_calibration_must_be_disabled_identity')


def _context(root,*,asset_loader=None,image_hashes=None):
    """Private synthetic seam; production entry has no arguments or bypass."""
    common=_load(root,'round11/prepared/common.json')
    require(type(common) is dict and set(common)=={'schema_version','namespace','paths','hashes','rows_sha256',
            'asset_files','labels_loaded','validation_opened','api_calls'} and common['schema_version']==1 and
            common['namespace']==NAMESPACE and common['paths']==ROLES and common['labels_loaded'] is False and
            common['validation_opened'] is False and type(common['api_calls']) is int and common['api_calls']==0,
            'P_common_contract_changed')
    require(set(common['hashes'])==set(ROLES) and all(_hash(v) for v in common['hashes'].values()),'P_role_hashes_invalid')
    frozen=_load(root,'round11/prepared/freeze.json')
    require(type(frozen) is dict and set(frozen)=={'schema_version','namespace','source_files','environment',
            'allowed_slots_sha256','transport_cap','labels_sha256'} and frozen['schema_version']==1 and
            frozen['namespace']==NAMESPACE and frozen['environment']==environment() and
            frozen['labels_sha256']==common['hashes']['labels'],'P_freeze_contract_changed')
    freeze_sha256=_read(root,'round11/prepared/freeze.json',digest_only=True)
    sources=deepcopy(frozen['source_files'])
    required=REQUIRED|set(ROLES.values())|{'round11/prepared/common.json','round11/prepared/cohort/source_closure.json'}
    require(type(sources) is dict and required<=set(sources) and all(_hash(v) for v in sources.values()),'P_source_pins_missing')
    for role,path in ROLES.items():require(sources[path]==common['hashes'][role],'P_role_pin_changed')
    assets=common['asset_files']
    from assets_p import asset_paths,VECTOR_MANIFEST
    required_assets=asset_paths(_load(root,VECTOR_MANIFEST))
    require(type(assets) is dict and set(assets)==required_assets and
            all(_hash(v) and sources.get(p)==v for p,v in assets.items()),'P_assets_changed')
    require(all(not p.lower().endswith(('.zip','.tar','.tar.gz','.tgz')) and
                not p.startswith('round11/preparation/source_inventory/') and
                not p.startswith('round11/preparation/source_role_audit/') for p in sources),
            'P_runtime_raw_corpus_or_mechanical_receipt_forbidden')
    live={}
    def verify_sources():
        require(_read(root,'round11/prepared/freeze.json',digest_only=True)==freeze_sha256,'P_freeze_changed')
        if live:
            require(fingerprint({k:getattr(live['ctx'],k) for k in live['keys']})==live['snapshot'],
                    'P_live_context_changed')
        require(environment()==frozen['environment'],'P_environment_changed')
        for path,expected in sources.items():
            require(_read(root,path,digest_only=True)==expected,'P_source_changed')
        return True
    verify_sources()
    review=_load(root,'round11/review_gate.json')
    require(type(review) is dict and set(review)=={'status','scope','unresolved_p1_p2','review_sha256'} and
            review['status']=='approved_or_fixed' and review['scope']=='P_first_integrated_context_runner' and
            type(review['unresolved_p1_p2']) is int and review['unresolved_p1_p2']==0 and
            review['review_sha256']==sources['round11/REVIEW.md'],'P_review_gate_incomplete')
    rows=_load(root,ROLES['manifest'])
    require(type(rows) is list and all(type(r) is dict and type(r.get('image_path')) is str and
            r['image_path'].startswith('round11/prepared/cohort/images/dev/') and
            Path(r['image_path']).suffix.lower() in ('.png','.jpg','.jpeg') for r in rows),
            'P_image_role_path_changed')
    # allowed_slots enforces all seven fields, canonical image paths and group folds.
    slots=allowed_slots(rows,image_hashes=image_hashes)
    require(fingerprint(rows)==common['rows_sha256'] and frozen['allowed_slots_sha256']==fingerprint(slots) and
            type(frozen['transport_cap']) is int and frozen['transport_cap']==len(slots)*3,'P_population_changed')
    for ds in ('asa24','nutrition5k'):
        require({r['fold'] for r in rows if r['dataset']==ds}==set(range(5)),'P_incomplete_five_folds')
    for row in rows:require(sources.get(row['image_path'])==row['image_sha256'],'P_image_pin_missing')
    lineage=_load(root,ROLES['lineage'])
    require(type(lineage) is dict and set(lineage)=={'schema_version','complete','rows'} and
            lineage['schema_version']==1 and lineage['complete'] is True and
            lineage['rows']==[{k:r[k] for k in ('sample_id','dataset','group_id','fold')} for r in rows],
            'P_association_lineage_changed')
    cohort=_load(root,ROLES['cohort_freeze'])
    require(type(cohort) is dict and set(cohort)=={'schema_version','status','manifest_sha256','labels_sha256',
            'lineage_sha256','source_closure_sha256','validation_opened'} and cohort['schema_version']==1 and
            cohort['status']=='prepared_development_pending_integrated_review' and cohort['validation_opened'] is False and
            cohort['source_closure_sha256']==sources['round11/prepared/cohort/source_closure.json'] and
            all(cohort[k+'_sha256']==common['hashes'][k] for k in ('manifest','labels','lineage')),
            'P_new_cohort_freeze_incomplete')
    # The immutable producer output remains pending. The separate runtime gate
    # above, and the genuine earlier preparation gate copied into this proof,
    # are both required; no post-review rewrite of the cohort freeze occurs.
    closure=_load(root,'round11/prepared/cohort/source_closure.json')
    prep_path='round11/preparation/preparation_review_gate.json'
    prep_review='round11/preparation/PREPARATION_REVIEW.md'
    require(type(closure) is dict and closure.get('preparation_review_gate_sha256')==sources[prep_path] and
            closure.get('preparation_review_sha256')==sources[prep_review] and
            closure.get('inference_authorized') is False and closure.get('inference_science_frozen') is False and
            closure.get('validation_targets_opened') is False,'P_preparation_source_proof_missing')
    prep=_load(root,prep_path)
    require(type(prep) is dict and set(prep)=={'status','scope','unresolved_p1_p2','review_sha256','source_files','receipt_sha256'} and
            prep['status']=='approved_or_fixed' and prep['scope']=='P_capacity_v4_preparation' and
            type(prep['unresolved_p1_p2']) is int and prep['unresolved_p1_p2']==0 and
            prep['review_sha256']==sources[prep_review],'P_preparation_review_gate_incomplete')
    held=closure.get('authenticated_preparation_source_sha256')
    require(type(held) is dict and all(type(path) is str and _hash(h) for path,h in held.items()) and
            type(prep['source_files']) is dict and type(prep['receipt_sha256']) is dict and
            prep['source_files'] and prep['receipt_sha256'] and
            all(type(path) is str and _hash(h) and held.get(path)==h
                for group in (prep['source_files'],prep['receipt_sha256']) for path,h in group.items()),
            'P_preparation_review_source_bindings_changed')
    prefix='optimization_sol_20261102/mae_v2/'
    require(held.get(prefix+prep_path)==sources[prep_path] and held.get(prefix+prep_review)==sources[prep_review] and
            all(sources.get(path.removeprefix(prefix),h)==h for path,h in prep['source_files'].items()
                if path.startswith(prefix)),'P_preparation_to_runtime_source_drift')
    imports=_load(root,ROLES['embeddings'])
    require(type(imports) is dict and set(imports)=={'schema_version','namespace','entries','blocked_hashes','policy'} and
            imports['schema_version']==1 and imports['namespace']==NAMESPACE and imports['entries']=={} and
            type(imports['blocked_hashes']) is list and imports['blocked_hashes']==sorted(set(imports['blocked_hashes'])) and
            all(_hash(h) for h in imports['blocked_hashes']) and imports['policy']=='fresh_P_queries_only',
            'P_historical_imports_disabled')
    fallbacks=_load(root,ROLES['fallbacks']);calibration=_load(root,ROLES['calibration'])
    _validate_training(fallbacks,rows,common,'componentwise_training_medians')
    _validate_training(calibration,rows,common,'training_fold_calibration')
    if asset_loader is None:
        from assets_p import assets as asset_loader
    catalog,retriever=asset_loader(root)
    verify_sources()
    ctx=SimpleNamespace(rows=rows,catalog=catalog,retriever=retriever,fallbacks=fallbacks,
        calibration=calibration,binding=deepcopy(frozen),verify_sources=verify_sources,imports=imports,
        manifest_sha256=common['hashes']['embeddings'])
    live['ctx']=ctx;live['keys']=('rows','catalog','fallbacks','calibration','binding','imports','manifest_sha256')
    live['snapshot']=fingerprint({k:getattr(ctx,k) for k in live['keys']})
    return ctx


def runtime_context():return _context(ROOT)
