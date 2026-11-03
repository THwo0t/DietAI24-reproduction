"""Completed-O evidence barrier prototype; no real invocation/phase CLI yet.

The public check pins the original production freeze. Private fixture hooks
exist only for synthetic tests and must never become CLI/config overrides.
This proves completed artifact consistency, not permission to sample/download/
infer or completion of the separate diagnostic/full-project retrospective.
No labels, catalog, image, credential, provider or network source is opened.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from round4.src.artifacts import ArtifactStore,decode

O_FREEZE='0815819980716aa6be5a5e77a71de6c007f8985566bf5503f5b007d201164d92'
MAX_BYTES=64*1024*1024


def require(value,code):
    if not value:raise ValueError(code)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
        allow_nan=False,separators=(',',':')).encode()).hexdigest()


def _production_sources(base):
    """Mirror the source-name universe of frozen context_o.source_pins."""
    directory=base/'round10';files=list(directory.glob('*.py'))
    files += [directory/'PROTOCOL.md',directory/'review_gate.json']
    files += [base/'src'/name for name in ('opt_provider.py','opt_pipeline.py','pipeline_v2.py',
                                         'opt_metrics.py','metrics_v2.py')]
    files += [base/'round4/src/artifacts.py',base/'round7/src/context_m.py',
              base/'round7/src/historical_m.py',base/'round7/src/service_m.py',
              base/'round7/src/runtime_m.py',base/'round8/src/uncertain_portions.py',
              directory/'prepared/common.json',directory/'prepared/embeddings.json']
    files += list((base/'round7/src').glob('*.py'))
    return {path.relative_to(base).as_posix() for path in files}


class Reader:
    def __init__(self,base):
        self.base=Path(base)
        require(self.base.is_absolute() and self.base.resolve()==self.base,'canonical_O_evidence_root_required')
        self.hashes={}

    def raw(self,relative):
        relative=Path(relative)
        require(not relative.is_absolute() and '..' not in relative.parts,'unsafe_O_evidence_path')
        require(not set(relative.parts)&{'data','provider','validation','.git','.codex'}
                and not relative.name.startswith(('.env','val_','validation_','credentials'))
                and relative.suffix in ('.json','.py','.md'),'forbidden_O_evidence_source')
        path=self.base/relative
        require(path.resolve()==path,'linked_O_evidence_refused')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_size<=MAX_BYTES,'bounded_regular_O_evidence_required')
            with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(MAX_BYTES+1)
            require(len(raw)<=MAX_BYTES,'O_evidence_size_bound_exceeded')
        finally:os.close(fd)
        key=relative.as_posix();digest=hashlib.sha256(raw).hexdigest()
        require(key not in self.hashes or self.hashes[key]==digest,'O_evidence_changed')
        self.hashes[key]=digest
        return raw

    def value(self,relative):return decode(self.raw(relative))

    def revalidate(self):
        for relative in tuple(self.hashes):self.raw(relative)
        return True


class CompletedStore(ArtifactStore):
    """Restrict reads before original complete-inventory verification runs."""
    def _bytes(self,relative):
        parts=Path(relative).parts
        root_member=len(parts)==1 and parts[0] in (
            '.lock','intent.json','seal.json','completion.json','completion.json.pending')
        record_member=len(parts)==2 and parts[0]=='records' and re.fullmatch(r'[0-9a-f]{64}\.json',parts[1])
        stage_member=len(parts)==3 and parts[0]=='stages' and re.fullmatch(r'[0-9a-f]{64}',parts[1])\
            and parts[2] in ('.lock','intent.json','result.json','result.seal.json','events.jsonl')
        require(root_member or record_member or stage_member,'unexpected_O_store_read_refused')
        return super()._bytes(relative)


@dataclass(frozen=True)
class CompletedOEvidence:
    freeze_sha256:str
    development_completion_sha256:str
    verification_sha256:str
    scoring_completion_sha256:str
    checkpoint_sha256:str
    identities_completion_sha256:str
    evidence_sha256:str
    records:int=183
    grants_new_phase_action:bool=False


def _verify_at(base,expected_freeze,*,source_inventory=_production_sources):
    """Internal fixture interface; future production entry must call public check."""
    reader=Reader(base);directory=reader.base/'round10'
    follow=reader.value('round10/launch/automatic_followup.json')
    require(follow.get('status')=='development_scored'
            and type(follow.get('new_paid_requests')) is int and follow['new_paid_requests']==0
            and follow.get('validation_opened') is False,'O_complete_offline_score_required')
    frozen=reader.value('round10/prepared/freeze.json')
    require(reader.hashes['round10/prepared/freeze.json']==expected_freeze,'trusted_O_freeze_required')
    require(frozen.get('schema_version')==1 and set(frozen['source_files'])==source_inventory(reader.base),
            'complete_O_source_inventory_required')
    for relative,expected in frozen['source_files'].items():
        reader.raw(relative);require(reader.hashes[relative]==expected,'O_scientific_source_changed')
    reader.raw('round10/REVIEW.md')
    require(reader.hashes['round10/REVIEW.md']==frozen['review_sha256'],'O_review_changed')
    prepared=reader.value('round10/prepared/common.json');rows=prepared['rows']
    require(reader.hashes['round10/prepared/common.json']==frozen['prepared_sha256']
            and fingerprint(rows)==frozen['rows_sha256']
            and Counter(row['dataset'] for row in rows)=={'asa24':99,'nutrition5k':84}
            and len({row['sample_id'] for row in rows})==183,'complete_O_populations_required')
    def store(folder,binding,names):
        value=CompletedStore(directory/'runs'/folder,binding,names,
            verify_sources=reader.revalidate,root=directory).verify_completed()
        reader.raw('round10/runs/'+folder+'/completion.json')
        return value
    names=lambda prefix:[prefix+'-'+fingerprint(row['sample_id'])[:32] for row in rows]
    identities=store('identities',frozen,names('identity')+['service-proof'])
    records=store('development',frozen,names('record')+['service-proof'])
    devhash=reader.hashes['round10/runs/development/completion.json']
    verified=reader.value('round10/runs/verification.json')
    require(verified.get('completed_replay') is True and verified.get('provider_constructed') is False
            and verified.get('records')==183 and verified.get('completion_sha256')==devhash
            and verified.get('freeze_sha256')==expected_freeze,'bound_zero_Provider_replay_required')
    scored=store('scoring',{'science':frozen,'completion_sha256':devhash},['results','OOF_predictions'])
    result=scored['results'];predictions=scored['OOF_predictions']
    raw=[records['record-'+fingerprint(row['sample_id'])[:32]] for row in rows]
    require(all(record['sample_id']==row['sample_id'] and record['dataset']==row['dataset']
                for row,record in zip(rows,raw)),'O_final_record_identity_changed')
    require(len(predictions)==183 and {p['sample_id'] for p in predictions}=={r['sample_id'] for r in rows}
            and Counter(p['dataset'] for p in predictions)=={'asa24':99,'nutrition5k':84},
            'complete_O_OOF_population_required')
    require(result.get('scope')=='O_development_OOF_not_independent_validation'
            and result.get('validation_opened') is False and type(result.get('api_calls')) is int
            and result['api_calls']==0 and result.get('source_records_sha256')==fingerprint(raw),
            'O_score_scope_or_sources_changed')
    # Match frozen scoring_o.public_summary without importing any inference code.
    summary=decode(json.dumps(result,allow_nan=False))
    for value in summary['calibration'].values():value.pop('fold_parameters',None)
    for value in summary['full_development_parameters'].values():
        for name in ('training_ids','eligible_ids'):value.pop(name,None)
    checkpoint=reader.value('round10/development_checkpoint.json')
    require(checkpoint==summary and follow.get('selection')==result['selection']
            and follow.get('failed_checks')=={key:result[key]['tolerance']['failed_checks']
                for key in ('raw','OOF_mass')},'O_scored_checkpoint_or_followup_changed')
    # Re-verify complete store inventories as well as captured source/header bytes.
    store('identities',frozen,names('identity')+['service-proof'])
    store('development',frozen,names('record')+['service-proof'])
    store('scoring',{'science':frozen,'completion_sha256':devhash},['results','OOF_predictions'])
    reader.revalidate()
    return CompletedOEvidence(expected_freeze,devhash,reader.hashes['round10/runs/verification.json'],
        reader.hashes['round10/runs/scoring/completion.json'],reader.hashes['round10/development_checkpoint.json'],
        reader.hashes['round10/runs/identities/completion.json'],fingerprint(reader.hashes))


def verify_completed_o():
    """Production pin, no caller overrides; not invoked on real data in this phase."""
    return _verify_at(BASE,O_FREEZE)
