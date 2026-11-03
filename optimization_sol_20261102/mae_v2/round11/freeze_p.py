"""Fixed offline science freeze after complete P cohort/runtime/scoring review."""
from copy import deepcopy
import json
from pathlib import Path
import sys

BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10'),str(BASE/'round11')]
from context_p import ROOT,ROLES,REQUIRED,_read,_load,environment,require
from service_p import NAMESPACE,allowed_slots
from opt_provider import fingerprint
from source_census import REPO,PREFIX,encoded,isolated_network
from prepare_p import _write_once
from assets_p import asset_paths,VECTOR_MANIFEST

PATH='round11/prepared/freeze.json'
REVIEW='round11/REVIEW.md'
GATE='round11/review_gate.json'
PREPARATION_GATE='round11/preparation/preparation_review_gate.json'
CLOSURE='round11/prepared/cohort/source_closure.json'
COMMON='round11/prepared/common.json'
EXTRA={'round11/verified_identity.py','round11/freeze_p.py','round11/FREEZE_PROTOCOL.md','round11/scoring_p.py',
       'round11/postscore_p.py','round11/POSTSCORE_PROTOCOL.md',
       'round11/postscore/review_gate.json','round11/postscore/REVIEW.md'}


def _review(root):
    gate=_load(root,GATE)
    require(type(gate) is dict and set(gate)=={'status','scope','unresolved_p1_p2','review_sha256'}
        and gate['status']=='approved_or_fixed' and gate['scope']=='P_first_integrated_context_runner'
        and type(gate['unresolved_p1_p2']) is int and gate['unresolved_p1_p2']==0
        and gate['review_sha256']==_read(root,REVIEW,digest_only=True),'P_complete_integrated_review_required')
    return deepcopy(gate)


def _freeze_at(root,*,required=None,image_hashes=None,validate_context=None):
    """Private synthetic seam. The production entry has no overrides."""
    root=Path(root)
    require(root.is_absolute() and root.resolve()==root,'P_freeze_canonical_root_required')
    review=_review(root)  # Before all prepared inputs, including opaque labels.
    common=_load(root,COMMON)
    require(type(common) is dict and common.get('paths')==ROLES and common.get('namespace')==NAMESPACE
        and common.get('labels_loaded') is False and common.get('validation_opened') is False
        and type(common.get('hashes')) is dict and set(common['hashes'])==set(ROLES),
        'P_freeze_preparation_binding_required')
    prep=_load(root,PREPARATION_GATE)
    require(type(prep) is dict and type(prep.get('source_files')) is dict and
        prep.get('status')=='approved_or_fixed' and prep.get('scope')=='P_capacity_v4_preparation'
        and type(prep.get('unresolved_p1_p2')) is int and prep.get('unresolved_p1_p2')==0,'P_freeze_preparation_review_required')
    if required is None:
        from postscore_p import SOURCES as SCORING_SOURCES
        required=set(REQUIRED)|EXTRA|{p.removeprefix(PREFIX) for p in SCORING_SOURCES}
    paths=set(required)|set(ROLES.values())|{COMMON,CLOSURE,GATE,REVIEW,PREPARATION_GATE}
    for path in prep['source_files']:
        require(type(path) is str and path.startswith(PREFIX),'P_freeze_preparation_source_scope_changed')
        paths.add(path.removeprefix(PREFIX))
    assets=common.get('asset_files')
    require(type(assets) is dict and set(assets)==asset_paths(_load(root,VECTOR_MANIFEST)),
        'P_freeze_exact_assets_required')
    paths.update(assets)
    rows=_load(root,ROLES['manifest'])
    require(type(rows) is list and fingerprint(rows)==common.get('rows_sha256'),
        'P_freeze_manifest_changed')
    for row in rows:
        require(type(row) is dict and type(row.get('image_path')) is str and
            row['image_path'].startswith('round11/prepared/cohort/images/dev/'),
            'P_freeze_development_image_scope_required')
        paths.add(row['image_path'])
    require(PATH not in paths and all(not p.lower().endswith(('.zip','.tar','.tgz','.tar.gz'))
        and not p.startswith('round11/preparation/source_inventory/')
        and not p.startswith('round11/preparation/source_role_audit/') for p in paths),
        'P_freeze_raw_corpus_or_recursive_pin_forbidden')
    sources={path:_read(root,path,digest_only=True) for path in sorted(paths)}
    require(all(sources[path]==common['hashes'][role] for role,path in ROLES.items())
        and all(sources[path]==h for path,h in assets.items())
        and all(sources[path.removeprefix(PREFIX)]==h for path,h in prep['source_files'].items()),
        'P_freeze_prepared_source_drift')
    require(all(sources[row['image_path']]==row['image_sha256'] for row in rows),
        'P_freeze_development_image_drift')
    slots=allowed_slots(rows,image_hashes=image_hashes)
    frozen={'schema_version':1,'namespace':NAMESPACE,'source_files':sources,
        'environment':environment(),'allowed_slots_sha256':fingerprint(slots),
        'transport_cap':len(slots)*3,'labels_sha256':common['hashes']['labels']}
    require(_review(root)==review and all(_read(root,p,digest_only=True)==h for p,h in sources.items()),
        'P_freeze_source_changed_during_assembly')
    _write_once(root.parents[1],PREFIX+PATH,encoded(frozen))
    if validate_context is None:
        from context_p import _context
        validate_context=_context
    ctx=validate_context(root)
    require(ctx.binding==frozen,'P_freeze_full_context_validation_failed')
    ctx.verify_sources()
    require(_review(root)==review and environment()==frozen['environment']
        and _read(root,PATH)==encoded(frozen)
        and all(_read(root,p,digest_only=True)==h for p,h in sources.items()),
        'P_freeze_source_changed_during_context_validation')
    return {'status':'P_reviewed_development_science_frozen','rows':len(rows),'source_files':len(sources),
        'science_sha256':fingerprint(frozen),'freeze_sha256':_read(root,PATH,digest_only=True),
        'transport_cap':frozen['transport_cap'],'api_calls':0,'labels_parsed':False,'validation_opened':False}


def main():
    require(len(sys.argv)==1,'P_freeze_cli_overrides_refused')
    require(isolated_network(Path('/proc/self/net/dev').read_bytes()),'P_freeze_isolated_network_required')
    return _freeze_at(ROOT)


if __name__=='__main__':
    try:print(json.dumps(main(),sort_keys=True))
    except Exception as exc:
        print(json.dumps({'status':'P_freeze_refused_preserve_state','error_type':type(exc).__name__}))
        raise SystemExit(1)
