"""Explicit read-only official embedding reuse; never create old service state."""
from copy import deepcopy
from pathlib import Path

from opt_provider import ROOT,sha,fingerprint
from round4.src.artifacts import decode
from historical_m import imported_embedding,checked_path
from service_m import audit_target
from context_o import ROUND,OLD_N_FREEZE,require,write_once


def prepare():
    n_path=ROOT/'round8/prepared/freeze.json'
    require(sha(n_path)==OLD_N_FREEZE,'O_embedding_import_wrong_N_freeze')
    n=decode(n_path.read_bytes())
    legacy_path=ROOT/'round7/prepared/embeddings.json'
    require(sha(legacy_path)==n['source_files']['round7/prepared/embeddings.json'],
            'O_legacy_embedding_inventory_changed')
    legacy=decode(legacy_path.read_bytes())
    require(legacy.get('hash_namespace')=='official-query-v1' and len(legacy['entries'])==3159,
            'O_legacy_embedding_population_changed')
    # Verify each registered historical source once; individual uses still
    # recheck their own exact cache/log/counter/value provenance.
    for relative,expected in legacy['source_files'].items():
        require(sha(checked_path(ROOT.parent,relative))==expected,'O_legacy_embedding_source_changed')
    entries={h:{'origin':'legacy','value_hash':v['value_hash']} for h,v in legacy['entries'].items()}
    m_entries,source_files={},{}
    blocked=set(legacy['rejected_hashes'])
    def pin(path):
        path=Path(path)
        require(path.resolve()==path and not path.is_symlink(),'O_embedding_source_symlink')
        relative=path.relative_to(ROOT).as_posix()
        source_files[relative]=sha(path)
        return relative
    pin(legacy_path); pin(n_path)
    for name in ('round7/src/service_m.py','round7/src/historical_m.py'):
        pin(ROOT/name)
    mroot=ROOT/'round7/provider/M'
    hashes={p.stem for kind in ('attempts','responses')
            for p in (mroot/kind/'embedding').glob('*.json')}
    for h in sorted(hashes):
        item=audit_target(ROOT,'embedding',h,allow_absent=False,allow_incomplete=True)
        for relative,expected in item['files'].items():
            require(sha(ROOT/relative)==expected,'O_M_embedding_evidence_changed')
            pin(ROOT/relative)
        if item['value'] is None:
            blocked.add(h); continue
        value=item['value']; value_hash=fingerprint(value)
        if h in entries:
            require(imported_embedding(ROOT,legacy,h)==value,'O_conflicting_embedding_import_copies')
        else:
            entries[h]={'origin':'M','value_hash':value_hash}
        m_entries[h]={'files':deepcopy(item['files']),'value_hash':value_hash}
    log=mroot/'requests.jsonl'
    if log.is_file(): pin(log)
    # Unknown/failed old state never receives a fresh O budget. File names are
    # admission evidence only, not a new broad cache import.
    known_old=set()
    for base in (ROOT,ROOT.parent):
        for kind in ('responses','attempts'):
            known_old.update(p.stem for p in (base/f'runtime_cache/{kind}/embedding').glob('*.json'))
    blocked.update(known_old-set(entries))
    require(not (blocked & set(entries)),'O_successful_embedding_also_marked_unusable')
    value={'schema_version':1,'legacy':legacy,'entries':entries,'M_entries':m_entries,
           'blocked_hashes':sorted(blocked),'source_files':source_files,
           'hash_namespace':'official-query-v1','api_calls':0,'query_labels_loaded':False,
           'validation_opened':False}
    write_once('prepared/embeddings.json',value)
    return {'status':'O_embedding_imports_prepared','entries':len(entries),
            'legacy_entries':3159,'M_successes':len(m_entries),'blocked_hashes':len(blocked),'api_calls':0}


def verify_sources(bundle):
    require(bundle.get('schema_version')==1 and bundle['hash_namespace']=='official-query-v1',
            'O_embedding_import_schema_changed')
    for relative,expected in bundle['source_files'].items():
        require(sha(checked_path(ROOT,relative))==expected,'O_embedding_import_source_changed')
    for relative,expected in bundle['legacy']['source_files'].items():
        require(sha(checked_path(ROOT.parent,relative))==expected,'O_legacy_embedding_source_changed')
    return True


def imported_value(bundle,h):
    entry=bundle['entries'].get(h)
    require(entry is not None and h not in bundle['blocked_hashes'],'O_unregistered_embedding_import')
    if entry['origin']=='legacy':
        value=imported_embedding(ROOT,bundle['legacy'],h)
    elif entry['origin']=='M':
        log='round7/provider/M/requests.jsonl'
        require(sha(ROOT/log)==bundle['source_files'][log],'O_M_embedding_log_changed')
        original=bundle['M_entries'][h]
        for relative,expected in original['files'].items():
            require(sha(checked_path(ROOT,relative))==expected,'O_M_embedding_source_changed')
        item=audit_target(ROOT,'embedding',h,allow_absent=False,allow_incomplete=False)
        require(item['files']==original['files'],'O_M_embedding_evidence_set_changed')
        value=item['value']
    else:
        raise ValueError('O_unknown_embedding_import_origin')
    require(fingerprint(value)==entry['value_hash'],'O_imported_embedding_value_changed')
    return value


def refuse_unregistered_old_state(bundle,h):
    require(h not in bundle['blocked_hashes'],'O_old_embedding_budget_not_resettable')
    if h in bundle['entries']:
        raise ValueError('O_registered_import_cannot_be_reissued')
    for base in (ROOT,ROOT.parent):
        for kind in ('responses','attempts'):
            require(not (base/f'runtime_cache/{kind}/embedding/{h}.json').exists(),
                    'O_unregistered_old_embedding_state')
    for kind in ('responses','attempts'):
        require(not (ROOT/f'round7/provider/M/{kind}/embedding/{h}.json').exists(),
                'O_unregistered_M_embedding_state')
