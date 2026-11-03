"""O's label-blind inputs, exact frozen fallback reuse and source binding."""
import json
import os
import platform
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

from opt_provider import ROOT, sha, fingerprint
from context_m import manifest, assets
from round4.src.artifacts import decode

ROUND = ROOT/'round10'
OLD_N_FREEZE = 'e581d24372a4ad1f4d8baf5f0f26e1490242c949368a48cb5107c3165945011d'


def require(ok, code):
    if not ok: raise ValueError(code)


def checked(relative):
    relative = Path(relative)
    require(not relative.is_absolute() and '..' not in relative.parts,'O_unsafe_relative_path')
    path = ROUND/relative
    require(path.resolve() == path and not path.is_symlink(),'O_symlink_path_rejected')
    return path


def write_once(relative, value):
    path = checked(relative)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    raw = json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n'
    if path.exists():
        require(path.read_text() == raw,'O_immutable_preparation_conflict')
        return
    fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def inputs():
    rows = manifest()
    catalog,retriever = assets()
    old_path = ROOT/'round8/prepared/freeze.json'
    require(sha(old_path) == OLD_N_FREEZE,'O_wrong_fallback_source_freeze')
    old = decode(old_path.read_bytes())
    fallback_path = ROOT/'round7/prepared/fallbacks.json'
    require(sha(fallback_path) == old['source_files']['round7/prepared/fallbacks.json'],
            'O_frozen_fallback_changed')
    fallbacks = decode(fallback_path.read_bytes())
    require(fallbacks['manifest_sha256'] == sha(ROOT/'data/cohorts/dev.jsonl'),
            'O_fallback_population_changed')
    for row in rows:
        value = fallbacks['vectors'][row['dataset']][str(row['fold'])]
        require(set(value) == {'weight','energy','fat','carbs','protein'},'O_five_fallback_targets_required')
    prepared = {'schema_version':1,'rows':rows,'rows_sha256':fingerprint(rows),
        'manifest_sha256':sha(ROOT/'data/cohorts/dev.jsonl'),'catalog_sha256':sha(ROOT/'data/catalog.json'),
        'vector_manifest_sha256':sha(ROOT/'data/vectors/manifest.json'),
        'fallbacks':fallbacks,'fallback_sha256':sha(fallback_path),'fallback_source_freeze':OLD_N_FREEZE,
        'labels_loaded':False,'validation_opened':False,'api_calls':0}
    return prepared,catalog,retriever


def prepare():
    prepared,_,_ = inputs()
    write_once('prepared/common.json',prepared)
    return {'status':'O_inputs_prepared','rows':len(prepared['rows']),
            'query_labels_loaded':False,'validation_opened':False,'api_calls':0}


def source_pins():
    files = list(ROUND.glob('*.py'))
    files += [ROUND/'PROTOCOL.md',ROUND/'review_gate.json']
    files += [ROOT/'src'/n for n in ('opt_provider.py','opt_pipeline.py','pipeline_v2.py',
                                   'opt_metrics.py','metrics_v2.py')]
    files += [ROOT/'round4/src/artifacts.py', ROOT/'round7/src/context_m.py',
              ROOT/'round7/src/historical_m.py',ROOT/'round7/src/service_m.py',
              ROOT/'round7/src/runtime_m.py',ROOT/'round8/src/uncertain_portions.py',
              ROUND/'prepared/common.json',ROUND/'prepared/embeddings.json']
    files += list((ROOT/'round7/src').glob('*.py'))
    return {p.relative_to(ROOT).as_posix():sha(p) for p in files}


def environment():
    return {'python':platform.python_version(),
            'packages':{p:version(p) for p in ('numpy','Pillow','httpx')}}


def freeze():
    gate = decode(checked('review_gate.json').read_bytes())
    require(gate.get('status') == 'approved_or_fixed' and gate.get('unresolved_p1_p2') == 0
            and gate.get('review_sha256') == sha(checked('REVIEW.md')),'O_review_gate_incomplete')
    prepared,_,_ = inputs()
    require(decode(checked('prepared/common.json').read_bytes()) == prepared,'O_prepared_inputs_changed')
    value = {'schema_version':1,'source_files':source_pins(),
             'review_sha256':gate['review_sha256'],'prepared_sha256':sha(checked('prepared/common.json')),
             'rows_sha256':prepared['rows_sha256'],'labels_sha256':prepared['fallbacks']['labels_sha256'],
             'environment':environment()}
    from service_o import allowed_slots
    value['allowed_slots_sha256']=fingerprint(allowed_slots(prepared['rows']))
    write_once('prepared/freeze.json',value)
    return value


def runtime_context(*,pre_review=False):
    prepared,catalog,retriever = inputs()
    require(decode(checked('prepared/common.json').read_bytes()) == prepared,'O_prepared_inputs_changed')
    frozen = {'source_files':{p.relative_to(ROOT).as_posix():sha(p) for p in ROUND.glob('*.py')}} if pre_review else \
             decode(checked('prepared/freeze.json').read_bytes())
    def verify_sources():
        require(all(sha(ROOT/name)==expected for name,expected in frozen['source_files'].items()),
                'O_frozen_source_changed')
        return True
    verify_sources()
    if not pre_review:
        from service_o import allowed_slots
        require(frozen['source_files'] == source_pins()
                and frozen['prepared_sha256'] == sha(checked('prepared/common.json'))
                and frozen['rows_sha256'] == prepared['rows_sha256']
                and frozen['review_sha256'] == sha(checked('REVIEW.md'))
                and frozen['environment']==environment()
                and frozen['allowed_slots_sha256']==fingerprint(allowed_slots(prepared['rows'])),
                'O_frozen_context_changed')
    from imports_o import verify_sources as verify_embedding_sources
    imports = decode(checked('prepared/embeddings.json').read_bytes())
    verify_embedding_sources(imports)
    return SimpleNamespace(rows=prepared['rows'],catalog=catalog,retriever=retriever,
        fallbacks=prepared['fallbacks'],binding=frozen,verify_sources=verify_sources,imports=imports)
