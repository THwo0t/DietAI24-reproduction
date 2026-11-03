"""N preparation and runtime context: imports already frozen fallbacks, no labels."""
from pathlib import Path
from types import SimpleNamespace

from opt_provider import ROOT, fingerprint, sha
from historical_m import checked_path
from context_m import manifest, assets
from runtime_m import durable_json
from upstream_n import prepare_imports, verify_imports
from service_n import Ledger, allowed_slots, load

ROUND = ROOT/'round8'
PREPARED = ROUND/'prepared'


def write_once(path, value):
    path = Path(path)
    checked = checked_path(ROUND,path.relative_to(ROUND))
    if checked.exists():
        if load(checked) != value: raise ValueError('N_write_once_conflict')
    else: durable_json(checked,value)


def prepare():
    rows = manifest(); catalog,_ = assets()
    imported = prepare_imports()
    verify_imports(imported,catalog)
    if rows != imported['rows']: raise ValueError('N_preparation_population_changed')
    write_once(PREPARED/'upstream.json',imported)
    return {'rows':len(rows),'imported_pairs':len(imported['records']),
            'new_api_calls':0,'labels_loaded':False,'validation_opened':False}


def source_pins():
    files = list((ROUND/'src').glob('*.py'))
    files += [ROOT/'src'/name for name in ('opt_provider.py','opt_pipeline.py','pipeline_v2.py',
                'opt_metrics.py','metrics_v2.py','diagnostics_v2.py','cohorts_v2.py')]
    files += [ROOT/'round4/src/artifacts.py',ROUND/'PROTOCOL.md',ROUND/'review_gate.json',PREPARED/'upstream.json']
    # Every original source/data file used to reinterpret M0 remains pinned.
    old = load(ROOT/'round7/prepared/freeze.json')
    files += [checked_path(ROOT,name) for name in old['source_files']]
    files += [ROOT/'round7/prepared/freeze.json',ROOT/'round7/runs/development/completion.json']
    files += [ROOT/'round7/development_checkpoint.json']
    return {p.relative_to(ROOT).as_posix():sha(p) for p in files}


def freeze():
    gate = load(ROUND/'review_gate.json')
    if (gate.get('status') != 'approved_or_fixed' or gate.get('unresolved_p1_p2') != 0
            or gate.get('review_sha256') != sha(ROUND/'REVIEW.md')):
        raise ValueError('N_independent_review_gate_incomplete')
    rows = manifest(); catalog,_ = assets()
    imported = load(PREPARED/'upstream.json'); verify_imports(imported,catalog)
    frozen = {'schema_version':1, 'source_files':source_pins(),'rows_sha256':fingerprint(rows),
        'manifest_sha256':sha(ROOT/'data/cohorts/dev.jsonl'),'catalog_sha256':sha(ROOT/'data/catalog.json'),
        'dev_freeze_sha256':sha(ROOT/'data/cohorts/dev_freeze.json'),
        'review_sha256':sha(ROUND/'REVIEW.md'),'allowed_slots_sha256':fingerprint(allowed_slots(rows))}
    write_once(PREPARED/'freeze.json',frozen)
    return frozen


def runtime_context(*, pre_review=False):
    """No scorer, labels, credentials, service client or embedding request."""
    if pre_review:
        frozen = {'source_files':{p.relative_to(ROOT).as_posix():sha(p) for p in (ROUND/'src').glob('*.py')}}
    else:
        frozen = load(PREPARED/'freeze.json')
        if sha(ROUND/'REVIEW.md') != frozen['review_sha256']: raise ValueError('N_frozen_review_changed')
    def verify_sources():
        for relative, expected in frozen['source_files'].items():
            if sha(checked_path(ROOT,relative)) != expected: raise ValueError('N_frozen_source_changed')
        return True
    verify_sources()
    rows = manifest(); catalog,_ = assets()
    imported = load(PREPARED/'upstream.json'); verify_imports(imported,catalog)
    if rows != imported['rows']: raise ValueError('N_runtime_population_changed')
    if not pre_review:
        current = {'rows_sha256':fingerprint(rows),'manifest_sha256':sha(ROOT/'data/cohorts/dev.jsonl'),
            'catalog_sha256':sha(ROOT/'data/catalog.json'),'dev_freeze_sha256':sha(ROOT/'data/cohorts/dev_freeze.json'),
            'allowed_slots_sha256':fingerprint(allowed_slots(rows))}
        if any(frozen[k] != v for k,v in current.items()): raise ValueError('N_frozen_input_changed')
    ledger = Ledger(ROUND/'provider/N',frozen,allowed_slots(rows))
    return SimpleNamespace(rows=rows,catalog=catalog,imported=imported,
        fallbacks=imported['fallbacks'],binding=frozen,verify_sources=verify_sources,ledger=ledger,
        parser_sha256=sha(ROUND/'src/uncertain_portions.py'))
