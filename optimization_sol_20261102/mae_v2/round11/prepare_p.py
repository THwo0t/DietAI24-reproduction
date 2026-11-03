"""Private write-once capacity-v4 development preparation; no inference permit.

The fixed public entry checks an independent source-pinned preparation review
before loading any development labels or interpreting candidate dish totals.
Acceptance output is identity-only, pending boundary confirmation and download.
"""
from collections import defaultdict,Counter
from copy import deepcopy
import csv
from decimal import Decimal,InvalidOperation
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import stat
import statistics
import sys
import zipfile

BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10'),str(BASE/'round11')]
from source_census import REPO,PREFIX,bounded_read,decode,sha,encoded,require,directory_fd,same_directory,isolated_network
from service_p import NAMESPACE,ROW_FIELDS
from opt_provider import fingerprint

REVIEW=PREFIX+'round11/preparation/preparation_review_gate.json'
REVIEW_TEXT=PREFIX+'round11/preparation/PREPARATION_REVIEW.md'
PREPARED=PREFIX+'round11/prepared/'
CATALOG='round11/prepared/catalog.json'
VECTOR='data/vectors/embeddings.npy'
TARGETS=('weight','energy','fat','carbs','protein')
RECEIPTS={
 PREFIX+'round11/preparation/source_inventory/source_inventory.json':'203bbb7c9f26f2bf6a4bf3846151fe068c3399f61efbb3f1a0b41c830dc9892d',
 PREFIX+'round11/preparation/source_role_audit/source_role_audit.json':'075931a1172269c1ed998ca06f686d99b7a5fa1bd7bda387d02c3270a82971e7',
 PREFIX+'round11/preparation/local_disposition/local_unassigned.json':'e529b2772d3a05153f43b998441967295c43cfb364a0873cda51435b5d757ddc',
 PREFIX+'round11/preparation/callers/caller_registration.json':'c3320f0499b9c4c446524a7e77919713f54fa8ee4432f8e3ebda71ead24c43bd',
 PREFIX+'round11/preparation/capacity/identity_capacity.json':'506aaa9df00f7d3e6bf1d1b9f50e99fe32f6b382e27ef042843c313b0d56e493'}
PREPARATION_SOURCES={PREFIX+'round11/'+n for n in (
 'prepare_p.py','PREPARATION_PROTOCOL.md','CAPACITY_AMENDMENT.md','COHORT_REPAIR_DESIGN.md',
 'preparation/SOURCE_DISPOSITION_DESIGN.md','source_scope_v3.py','asa_expansion_v3.py','capacity_cohort_v4.py',
 'n5_sources.py','development_identity.py','training_identity.py','caller_registration.py',
 'source_census.py','source_inventory_capture.py','source_role_audit.py','source_capture.py',
 'asa_workbook.py','asa_tables.py','asa_eligibility.py','asa_archive.py','asa_role_sources.py',
 'n5_preparation.py','n5_pool.py','asa_phase_graph.py','asa_identity.py','asa_content_identity.py',
 'qualification.py','cohort_lineage_v3.py','lineage_pool_v3.py','n5_identity.py',
 # R-PC6-1: active source-verification and import-time dependency closure.
 # Historical implementation hashes in held receipts do not pin these files.
 'service_p.py','asa_source_capture.py','legacy_input_identity.py',
 'local_content_inventory.py','local_input_inventory.py','n5_potential_identity.py')}
PREPARATION_SOURCES |= {PREFIX+p for p in (
 'src/opt_provider.py','src/opt_pipeline.py','src/cohorts_v2.py',
 'round4/src/artifacts.py','round7/src/historical_m.py',
 'round7/src/runtime_m.py','round7/src/service_m.py')}
ASSETS={PREFIX+p for p in ('data/catalog.json','data/vectors/manifest.json','data/vectors/codes.json',VECTOR)}
ROLES={'manifest':'round11/prepared/cohort/dev.json','labels':'round11/prepared/cohort/dev_labels.json',
 'lineage':'round11/prepared/cohort/lineage.json','cohort_freeze':'round11/prepared/cohort/freeze.json',
 'fallbacks':'round11/prepared/fallbacks.json','calibration':'round11/prepared/calibration.json',
 'embeddings':'round11/prepared/embeddings.json'}


def _hash(value):return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _canonical(relative):
    require(type(relative) is str and relative and '\\' not in relative and '\0' not in relative
        and not relative.startswith('/') and all(p not in ('','.','..') for p in relative.split('/')),
        'P_preparation_relative_path_required')
    return relative


class BoundSources:
    """Secure fixed pins; the vector matrix has a digest-only 96 MiB exception."""
    def __init__(self,repo,pins):
        self.repo=Path(repo);require(self.repo.is_absolute() and self.repo.resolve()==self.repo,'P_preparation_root_required')
        require(type(pins) is dict and all(_hash(v) for v in pins.values()),'P_preparation_source_pins_required')
        self.pins={_canonical(p):h for p,h in pins.items()};self.used={}
    def bind(self,path,digest):
        _canonical(path);require(_hash(digest),'P_preparation_digest_required')
        require(path not in self.pins or self.pins[path]==digest,'P_preparation_source_rebinding')
        self.pins[path]=digest
    def read(self,path):
        require(path in self.pins and path!=PREFIX+VECTOR,'P_preparation_unregistered_body')
        raw=bounded_read(self.repo,path);require(sha(raw)==self.pins[path],'P_preparation_source_drift')
        self.used[path]=self.pins[path];return raw
    def digest(self,path):
        require(path in self.pins,'P_preparation_unregistered_digest')
        if path!=PREFIX+VECTOR:return sha(self.read(path))
        full=self.repo/path;parent=directory_fd(full.parent)
        try:
            fd=os.open(full.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            try:
                info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and 0<info.st_size<=96*1024*1024,'P_vector_digest_bound')
                h=hashlib.sha256();size=0
                while True:
                    block=os.read(fd,1024*1024)
                    if not block:break
                    size+=len(block);require(size<=96*1024*1024,'P_vector_digest_bound');h.update(block)
                current=os.stat(full.name,dir_fd=parent,follow_symlinks=False)
                require(size==info.st_size and (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)==
                    (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns) and same_directory(full.parent,parent),
                    'P_vector_changed_during_digest')
                digest=h.hexdigest();require(digest==self.pins[path],'P_vector_digest_changed')
                self.used[path]=digest;return digest
            finally:os.close(fd)
        finally:os.close(parent)
    def revalidate(self):
        for path in tuple(self.used):self.digest(path)


def _review(repo,*,required=PREPARATION_SOURCES|ASSETS,receipts=RECEIPTS):
    # This is deliberately the first source read in preparation. No alternate
    # public path/count/hash/review overrides are accepted.
    raw=bounded_read(Path(repo),REVIEW);gate=decode(raw)
    require(type(gate) is dict and set(gate)=={'status','scope','unresolved_p1_p2','review_sha256','source_files','receipt_sha256'}
        and gate['status']=='approved_or_fixed' and gate['scope']=='P_capacity_v4_preparation'
        and type(gate['unresolved_p1_p2']) is int and gate['unresolved_p1_p2']==0
        and _hash(gate['review_sha256']) and gate['receipt_sha256']==receipts,'P_first_preparation_review_required')
    pins=gate['source_files'];require(type(pins) is dict and required<=set(pins)
        and REVIEW not in pins and all(_hash(h) for h in pins.values()),'P_exact_preparation_review_sources_required')
    reader=BoundSources(repo,{**pins,REVIEW_TEXT:gate['review_sha256'],**receipts})
    reader.bind(REVIEW,sha(raw));reader.read(REVIEW);reader.read(REVIEW_TEXT)
    derived=set();descriptor_path=PREFIX+'data/vectors/manifest.json'
    if descriptor_path in required:
        descriptor=decode(reader.read(descriptor_path))
        require(type(descriptor) is dict and type(descriptor.get('files')) is dict,'P_review_vector_descriptor_required')
        for name,digest in descriptor['files'].items():
            require(type(name) is str and name and '/' not in name and '\\' not in name and name not in ('.','..') and _hash(digest),
                    'P_review_fixed_vector_file_required')
            path=PREFIX+'data/vectors/'+name
            require(pins.get(path)==digest,'P_review_complete_vector_pins_required');derived.add(path)
    require(set(pins)==required|derived,'P_exact_preparation_review_sources_required')
    for path in pins:reader.digest(path)
    for path in receipts:reader.read(path)
    return reader


def _write_once(repo,relative,raw):
    """No replacement: an interrupted partial file remains a hard refusal."""
    require(type(raw) is bytes and relative.startswith(PREPARED),'P_preparation_output_scope_required')
    _canonical(relative);root=Path(repo);parent=directory_fd(root)
    parts=relative.split('/');private=False
    try:
        for part in parts[:-1]:
            if part=='prepared':private=True
            try:os.mkdir(part,0o700 if private else 0o755,dir_fd=parent)
            except FileExistsError:pass
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent);parent=child
            if private:require(stat.S_IMODE(os.fstat(parent).st_mode)==0o700,'P_private_prepared_directory_required')
        expected_parent=root/Path(relative).parent
        require(same_directory(expected_parent,parent),'P_prepared_parent_changed')
        try:fd=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        except FileExistsError:
            fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            try:
                info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode)==0o600 and info.st_size==len(raw),
                                         'P_existing_prepared_file_changed')
                chunks=[];remaining=len(raw)
                while remaining:
                    block=os.read(fd,min(1024*1024,remaining));require(block,'P_existing_prepared_file_truncated')
                    chunks.append(block);remaining-=len(block)
                require(b''.join(chunks)==raw,'P_existing_prepared_file_changed')
            finally:os.close(fd)
            require(same_directory(expected_parent,parent),'P_prepared_parent_changed')
            return
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.fsync(parent)
        require(same_directory(expected_parent,parent),'P_prepared_parent_changed')
    finally:os.close(parent)


def _finite_truth(label):
    require(type(label) is dict and type(label.get('truth')) is dict and set(label['truth'])==set(TARGETS),
            'P_complete_development_truth_required')
    truth=label['truth'];require(all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in truth.values())
        and truth['weight']>0,'P_finite_positive_development_mass_required')
    return deepcopy(label)


def _eligible_raw(raw_tables,allowed,objects):
    """Only six dish fields of unblocked official-RGB rows receive conversion."""
    eligible=set();seen=set()
    for slot in ('cafe1','cafe2'):
        for row in csv.reader(io.StringIO(raw_tables[slot].decode('utf-8-sig'))):
            require(len(row)>=6 and row[0] not in seen,'P_unique_raw_candidate_identity_required');seen.add(row[0])
            dish=row[0]
            if dish not in allowed or dish not in objects:continue
            try:values=[Decimal(v) for v in row[1:6]]
            except (InvalidOperation,ValueError):raise ValueError('P_invalid_unblocked_candidate_targets') from None
            require(all(v.is_finite() and v>=0 for v in values) and values[1]>0,'P_invalid_unblocked_candidate_targets')
            try:finite=all(math.isfinite(float(v)) for v in values)
            except OverflowError:finite=False
            require(finite,'P_invalid_unblocked_candidate_targets')
            if any(values[i]>0 for i in (0,2,3,4)):eligible.add(dish)
    require(eligible<=set(allowed) and len(set(allowed)&set(objects))<=137,'P_registered_raw_candidate_capacity_changed')
    return eligible


def _catalog_prefix(old,new):
    """Preserve all old data and each old legal-option sequence as a prefix."""
    from opt_pipeline import validate_options
    require(type(new) is dict and type(old) is dict and set(new)==set(old) and
        {k:v for k,v in new.items() if k!='asa_options'}=={k:v for k,v in old.items() if k!='asa_options'} and
        type(new.get('asa_options')) is dict and type(old.get('asa_options')) is dict,
        'P_original_catalog_must_remain_immutable')
    for code,options in new['asa_options'].items():
        require(code in old['foods'],'P_ASA_code_outside_frozen_food_bank')
        validate_options(options)
        prefix=old['asa_options'].get(code,[])
        require(options[:len(prefix)]==prefix,'P_original_ASA_option_prefix_changed')
        known={(o['description'],o['grams']) for o in prefix}
        for option in options[len(prefix):]:
            key=(option['description'],option['grams'])
            require(key not in known,'P_duplicate_appended_ASA_legal_option');known.add(key)
    require(set(old['asa_options'])<=set(new['asa_options']),'P_original_ASA_option_code_missing')


def _extend_catalog(catalog,legal,permitted_codes):
    """Append ALL distinct safe legal options before any group selection.

    Existing entries, their IDs and their order remain an exact old prefix.
    Catalogue scope includes safe broader codes and admitted core-extra codes;
    it never depends on which twenty broader components are selected.
    """
    from opt_pipeline import validate_options
    out=deepcopy(catalog);bycode=defaultdict(list)
    for row in legal['rows']:
        code=row['FoodCode']
        if code in permitted_codes:bycode[code].append(row)
    for code,rows in sorted(bycode.items()):
        require(code in out['foods'],'P_ASA_code_outside_frozen_food_bank')
        prefix=deepcopy(out['asa_options'].get(code,[]))
        known={(o['description'],o['grams']) for o in prefix};ids={o['option_id'] for o in prefix};additional={}
        for row in rows:
            grams=float(row['Weight']);text=row['Portion'];key=(text,grams)
            require(math.isfinite(grams) and grams>0 and type(text) is str and text.strip(),
                    'P_complete_safe_legal_option_required')
            if key in known:continue
            additional[key]={'option_id':'p'+sha(encoded([code,text,grams]))[:24],
                             'description':text,'grams':grams}
        for key in sorted(additional):
            option=additional[key]
            require(option['option_id'] not in ids,'P_appended_option_identifier_collision')
            ids.add(option['option_id']);prefix.append(option)
        validate_options(prefix);out['asa_options'][code]=prefix
    _catalog_prefix(catalog,out)
    return out


def _training_bundles(rows,labels,hashes):
    common={'schema_version':1,'manifest_sha256':hashes['manifest'],'labels_sha256':hashes['labels'],
            'cohort_freeze_sha256':hashes['cohort_freeze']}
    medians={**common,'role':'componentwise_training_medians','folds':{}}
    calibration={**common,'role':'training_fold_calibration','folds':{}}
    for ds in ('asa24','nutrition5k'):
        medians['folds'][ds]={};calibration['folds'][ds]={}
        for fold in range(5):
            train=[r for r in rows if r['dataset']==ds and r['fold']!=fold]
            held=[r for r in rows if r['dataset']==ds and r['fold']==fold]
            tg=sorted({r['group_id'] for r in train});hg=sorted({r['group_id'] for r in held})
            require(train and held and not set(tg)&set(hg),'P_training_fold_group_leakage_or_shortfall')
            proof={'train_ids':sorted(r['sample_id'] for r in train),'heldout_ids':sorted(r['sample_id'] for r in held),
                   'train_groups':tg,'heldout_groups':hg}
            medians['folds'][ds][str(fold)]={**proof,'value':{k:float(statistics.median(labels[r['sample_id']]['truth'][k] for r in train)) for k in TARGETS}}
            calibration['folds'][ds][str(fold)]={**proof,'value':{'enabled':False,
                'status':'preregistered_disabled_identity','multipliers':{k:1 for k in TARGETS}}}
    return medians,calibration


def _produce(repo,reader,bundle,*,image_loader,revalidate):
    """Private fixture seam. Every supplied row is a development observation."""
    revalidate();reader.revalidate()
    require(type(bundle) is dict and set(bundle)=={'records','catalog','old_catalog','assets','closure','proposals'},'P_preparation_bundle_schema_changed')
    require(bundle['closure'].get('original_global_guard_remains_stopped') is True and
        bundle['closure'].get('actual_api_exposure_complete') is False and
        bundle['closure'].get('source_association_complete') is False,'P_false_global_closure_required')
    rows=[];labels={};strata={};source_bindings={};payloads={};groups={};seen=set();outputs={}
    for record in bundle['records']:
        require(set(record)=={'row','label','stratum','source_image','association_group_id'},'P_development_record_projection_required')
        row=deepcopy(record['row']);require(set(row)==ROW_FIELDS and row['sample_id'] not in seen and
            row['dataset'] in ('asa24','nutrition5k') and type(row['sample_id']) is str and
            row['sample_id'].startswith(row['dataset']+'-') and
            (row['dataset']!='nutrition5k' or re.fullmatch(r'nutrition5k-dish_[0-9]{10}',row['sample_id'])) and row['split']=='dev' and type(row['fold']) is int and
            row['fold'] in range(5) and _hash(row['image_sha256']) and type(row['group_id']) is str and row['group_id'],
            'P_development_blind_row_required')
        group=(row['dataset'],row['group_id']);require(group not in groups or groups[group]==row['fold'],'P_group_crosses_folds')
        assoc=(row['dataset'],record['association_group_id']);require(assoc not in groups or groups[assoc]==row['fold'],'P_association_crosses_folds')
        groups[group]=row['fold'];groups[assoc]=row['fold'];seen.add(row['sample_id'])
        label=_finite_truth(record['label'])
        if row['dataset']=='asa24':
            require(type(label.get('food_code')) is str and len(label['food_code'])==8 and label['food_code'].isdigit()
                and row['sample_id'].startswith('asa24-'+label['food_code']+'-'),'P_explicit_ASA_identity_code_binding_required')
        spec=record['source_image']
        require(type(spec) is dict and spec.get('sha256')==row['image_sha256'],'P_source_image_binding_required')
        if spec.get('kind')=='fixed_development_or_support':
            require(set(spec)=={'kind','path','sha256'} and any(spec['path'].startswith(PREFIX+p) for p in (
                'data/asa24/dev/images/','data/nutrition5k/dev/images/','round4/data/train/images/')),
                'P_no_protected_image_sources_allowed')
            _canonical(spec['path'])
        else:
            require(set(spec)=={'kind','member_index','member_path','sha256','bytes'} and
                spec['kind']=='bound_ASA_archive_member' and type(spec['member_index']) is int and spec['member_index']>=0
                and type(spec['bytes']) is int and 0<spec['bytes']<=5*1024*1024,'P_bound_archive_spec_required')
            _canonical(spec['member_path'])
        raw=image_loader(spec);require(type(raw) is bytes and 0<len(raw)<=5*1024*1024 and sha(raw)==row['image_sha256'],
                                                         'P_development_source_image_changed')
        neutral=sha(('P-capacity-v4|'+row['sample_id']+'|'+row['image_sha256']).encode())+'.png'
        path='round11/prepared/cohort/images/dev/'+neutral
        row['image_path']=path;_write_once(repo,PREFIX+path,raw);outputs[PREFIX+path]=sha(raw);rows.append(row);labels[row['sample_id']]=label
        strata[row['sample_id']]=record['stratum'];source_bindings[row['sample_id']]=deepcopy(record['source_image'])
    require(rows and len(rows)==len(labels),'P_complete_development_population_required')
    rows.sort(key=lambda r:(r['dataset'],r['sample_id']))
    old=bundle['old_catalog'];new=bundle['catalog']
    _catalog_prefix(old,new)
    for row in rows:
        if row['dataset']!='asa24':continue
        label=labels[row['sample_id']];code=label['food_code']
        require(code in new['asa_options'] and any(o['grams']==label['truth']['weight'] for o in new['asa_options'][code]),
                'P_ASA_development_truth_not_in_complete_legal_catalogue')
    assets=deepcopy(bundle['assets']);require('data/catalog.json' in assets and VECTOR in assets
        and all(_hash(h) for h in assets.values()) and decode(reader.read(PREFIX+'data/catalog.json'))==old,
        'P_exact_old_asset_bindings_required')
    # Preserve the original catalogue's source bytes hash, not a reserialized
    # approximation: production passes its canonical payload explicitly below.
    for path in assets:require(reader.digest(PREFIX+path)==assets[path],'P_old_vector_asset_changed')
    payloads[CATALOG]=encoded(new);assets[CATALOG]=sha(payloads[CATALOG])
    payloads[ROLES['manifest']]=encoded(rows);payloads[ROLES['labels']]=encoded(labels)
    payloads[ROLES['lineage']]=encoded({'schema_version':1,'complete':True,
        'rows':[{k:r[k] for k in ('sample_id','dataset','group_id','fold')} for r in rows]})
    closure={**deepcopy(bundle['closure']),
        'preparation_review_gate_sha256':reader.pins[REVIEW],
        'preparation_review_sha256':reader.pins[REVIEW_TEXT],
        'authenticated_preparation_source_sha256':deepcopy(reader.used),'strata_private':strata,'development_source_bindings_private':source_bindings,
        'acceptance_proposals_private':deepcopy(bundle['proposals']),
        'acceptance_designated':False,'acceptance_download_authorized':False,'new_downloads':0,'api_calls':0,
        'inference_authorized':False,'inference_science_frozen':False,'validation_targets_opened':False,
        'development_labels_loaded_by_preparation':True}
    payloads['round11/prepared/cohort/source_closure.json']=encoded(closure)
    hashes={k:sha(payloads[p]) for k,p in ROLES.items() if p in payloads}
    payloads[ROLES['cohort_freeze']]=encoded({'schema_version':1,'status':'prepared_development_pending_integrated_review',
        'manifest_sha256':hashes['manifest'],'labels_sha256':hashes['labels'],'lineage_sha256':hashes['lineage'],
        'source_closure_sha256':sha(payloads['round11/prepared/cohort/source_closure.json']),'validation_opened':False})
    hashes['cohort_freeze']=sha(payloads[ROLES['cohort_freeze']])
    fallback,calibration=_training_bundles(rows,labels,hashes)
    payloads[ROLES['fallbacks']]=encoded(fallback);payloads[ROLES['calibration']]=encoded(calibration)
    payloads[ROLES['embeddings']]=encoded({'schema_version':1,'namespace':NAMESPACE,'entries':{},'blocked_hashes':[],
                                        'policy':'fresh_P_queries_only'})
    hashes={role:sha(payloads[path]) for role,path in ROLES.items()}
    payloads['round11/prepared/common.json']=encoded({'schema_version':1,'namespace':NAMESPACE,'paths':ROLES,'hashes':hashes,
        'rows_sha256':fingerprint(rows),'asset_files':assets,'labels_loaded':False,'validation_opened':False,'api_calls':0})
    revalidate();reader.revalidate()
    # Common is the last publication; partial preceding files are never treated
    # as a completed preparation and resume must compare every immutable byte.
    for path,raw in sorted(payloads.items(),key=lambda item:(item[0]=='round11/prepared/common.json',item[0])):
        _write_once(repo,PREFIX+path,raw);outputs[PREFIX+path]=sha(raw)
    revalidate();reader.revalidate()
    for path,digest in outputs.items():
        require(sha(bounded_read(Path(repo),path))==digest,'P_prepared_output_changed')
    return {'status':'P_capacity_v4_development_prepared_acceptance_proposal_only','development_rows':len(rows),
        'dataset_counts':{ds:sum(r['dataset']==ds for r in rows) for ds in ('asa24','nutrition5k')},
        'development_stratum_counts':dict(sorted(Counter(strata.values()).items())),
        'acceptance_proposal_counts':{
            'nutrition5k':deepcopy(bundle['proposals'].get('nutrition5k',{}).get('counts',{})),
            'asa24':{k:bundle['proposals'].get('asa24',{}).get(k) for k in ('resulting_rows','resulting_association_groups')}},
        'fixed_order_shortfall_reasons':deepcopy(bundle['closure'].get('ASA_expansion_shortfall_reasons',[]))+
            deepcopy(bundle['proposals'].get('nutrition5k',{}).get('shortfall_reasons',[])),
        'common_sha256':sha(payloads['round11/prepared/common.json']),'api_calls':0,'new_downloads':0,
        'validation_targets_opened':False,'inference_authorized':False,'acceptance_designated':False}


def _production_inputs(repo,reader):
    """Fixed authenticated source assembly, invoked only AFTER _review succeeds."""
    import n5_sources,development_identity,training_identity,caller_registration
    import source_scope_v3,capacity_cohort_v4,asa_expansion_v3
    from source_census import CONTROL_PINS,control_evidence
    from source_inventory_capture import verify_asa_bindings,verify_legacy_bindings
    from source_capture import ASA_SOURCES,plain
    from n5_preparation import official_rgb_sizes
    from asa_workbook import capture_workbook
    from asa_tables import code_membership,weight_projection
    from asa_eligibility import legal_rows
    import asa_archive
    mechanical=decode(reader.read(next(iter(RECEIPTS))))
    audit=decode(reader.read(PREFIX+'round11/preparation/source_role_audit/source_role_audit.json'))
    local=decode(reader.read(PREFIX+'round11/preparation/local_disposition/local_unassigned.json'))
    held_callers=decode(reader.read(PREFIX+'round11/preparation/callers/caller_registration.json'))
    reader.read(PREFIX+'round11/preparation/capacity/identity_capacity.json')
    # These readers open only fixed authenticated identity sources; no source
    # seal inventory is recursively followed into protected images or labels.
    n5,n5reader=n5_sources.load_identity_sources(repo)
    development,devreader=development_identity._load_development_identity(repo,n5_sources.ANCHORS['development_seal'])
    training,trainreader=training_identity._load_at(repo)
    callers,callerreader=caller_registration._load_at(repo)
    require(plain(callers)==held_callers and development==mechanical['development_identity']
        and n5['source_hashes']==mechanical['n5_source_sha256'],'P_held_identity_projections_changed')
    base=Path(repo)/PREFIX.rstrip('/')
    controls=control_evidence(base,CONTROL_PINS)
    require(controls==mechanical['control_sha256']==audit['control_sha256'],'P_original_controls_changed')
    asa=mechanical['asa_mechanical_sources'];roles=audit['asa_role_sources_private']
    def revalidate():
        reader.revalidate();n5reader.revalidate();devreader.revalidate();trainreader.revalidate();callerreader.revalidate()
        verify_asa_bindings(Path(repo),asa);verify_legacy_bindings(Path(repo).parent,mechanical['legacy_inputs_private'])
        require(control_evidence(base,CONTROL_PINS)==controls,'P_original_controls_changed')
        # Existing audit sources are authenticated byte bindings only. In
        # particular no historical result payload or protected targets are parsed.
        for path,digest in roles['source_hashes'].items():
            absolute=Path(path)
            if absolute.is_relative_to(Path(repo)):root=Path(repo);relative=str(absolute.relative_to(root))
            elif absolute.is_relative_to(Path(repo).parent):root=Path(repo).parent;relative=str(absolute.relative_to(root))
            else:raise ValueError('P_role_source_outside_fixed_project_scope')
            require(sha(bounded_read(root,relative))==digest,'P_role_identity_source_changed')
    revalidate()
    scope=source_scope_v3.disposition(mechanical,audit,callers,training,local,repair_registration={
        'source_disposition_design_sha256':reader.digest(PREFIX+'round11/preparation/SOURCE_DISPOSITION_DESIGN.md'),
        'original_linkage_guard_remains_stopped':True,'ASA_bridge_pending_replacement':{
            'affected_validation_records':3,'old_validation_records':78,'status':'proposal_only_pending_boundary_confirmation'}})
    state=scope['n5_identity_state_private'];devbinding=capacity_cohort_v4.developer_identity_bindings(
        development['n5_core']['rows'],training,state)
    # Read only the already sealed seven-field manifest, never validation labels
    # or any validation photo. All 200 old associations remain blocked.
    seal=decode(n5reader.bound['validation_seal']);valpath=PREFIX+'data/cohorts/sealed/validation.jsonl'
    reader.bind(valpath,seal['artifacts'][valpath.removeprefix(PREFIX)])
    validation=[decode(line) for line in reader.read(valpath).splitlines()]
    require(all(type(r) is dict and set(r)==ROW_FIELDS for r in validation),'P_identity_only_validation_manifest_required')
    oldn5=[r for r in validation if r['dataset']=='nutrition5k']
    objects=official_rgb_sizes(n5['official_objects'])
    rawframe=set(state['allowed_ids'])&set(objects)
    require(len(rawframe)==137 and not rawframe&set(state['protected']['legacy_reserved']['dish_ids']),
            'P_capacity_amendment_full_raw_frame_changed')
    eligible=_eligible_raw(n5['raw_tables'],rawframe,objects)
    acceptance=capacity_cohort_v4.acceptance_identity_proposal(oldn5,state,eligible)
    require(acceptance['counts']['retained_old_rows']==102,'P_retained_acceptance_identity_population_changed')
    # Authenticate deferred ASA sources only after bounded scope and review.
    pins=asa['registered_asa_sources_sha256']
    for path,pin in pins.items():reader.bind(path,pin)
    workbook,identity,_=capture_workbook(reader.read(ASA_SOURCES[1]),pins[ASA_SOURCES[1]])
    require(plain(identity)==asa['asa_workbook_identity'],'P_ASA_workbook_identity_changed')
    graph=audit['asa_phase_graph_private'];mapping=graph['node_groups']
    core=development['asa_rows'];corecodes={r['sample_id'].split('-',2)[1] for r in core}
    forbidden=set(scope['missing_source_quarantine_components_private'])|set(graph['protected_groups']['validation'])
    permitted=set(scope['asa_permitted_codes_private'])|{c for c in corecodes if mapping['c:'+c] not in forbidden}
    tables=workbook.eligibility_projection(permitted)
    foodcodes,_=code_membership(reader.read(ASA_SOURCES[3]),pins[ASA_SOURCES[3]])
    topcodes,_=code_membership(reader.read(ASA_SOURCES[2]),pins[ASA_SOURCES[2]])
    weights,_=weight_projection(reader.read(ASA_SOURCES[4]),pins[ASA_SOURCES[4]],permitted)
    imagehashes={r['image']:r['bytes_sha256'] for r in asa['asa_archive_identity']['image_fingerprints']}
    legal,_=legal_rows(tables['metadata'],tables['inventory'],weights['food_weights'],
        permitted_codes=permitted,fndds_codes=foodcodes['codes'],top_codes=topcodes['codes'],image_hashes=imagehashes,broader_frame=True)
    # Extend the complete safe eligible code catalogue BEFORE the 20-component
    # subset is used. Existing food/density/standard fields and ASA option prefixes remain exact.
    oldcatalog=decode(reader.read(PREFIX+'data/catalog.json'))
    catalog=_extend_catalog(oldcatalog,legal,permitted)
    expansion=asa_expansion_v3.build_asa_expansion(core,roles['currentmanifestbinding']['validation'],
        roles['originalmanifestbinding'],legal,graph,scope,imagehashes,topcodes['codes'])
    # The only supervised source bodies are old development and accepted support
    # labels at their independently authenticated fixed paths.
    devlabels_path=PREFIX+'data/cohorts/dev_labels.json'
    reader.bind(devlabels_path,development['n5_core']['labels_sha256'])
    oldlabels=decode(reader.read(devlabels_path))
    original_ids={r['sample_id'] for r in core+development['n5_core']['rows']}
    require(type(oldlabels) is dict and set(oldlabels)==original_ids,'P_old_development_label_population_changed')
    trainfreeze=decode(n5reader.bound['training_freeze']);trainlabels_path=PREFIX+'round4/data/train/labels.json'
    reader.bind(trainlabels_path,trainfreeze['artifacts']['labels.json'])
    trainlabels=decode(reader.read(trainlabels_path))
    require(type(trainlabels) is dict and set(trainlabels)=={r['sample_id'] for r in training['accepted_manifest_private']},
            'P_support_label_population_changed')
    records=[]
    def oldrecord(row,label,stratum,group,fold,association):
        expected=row['image_sha256'];path=PREFIX+row['image_path'];reader.bind(path,expected)
        records.append({'row':{k:v for k,v in {**row,'split':'dev','group_id':group,'fold':fold}.items() if k in ROW_FIELDS},
            'label':_finite_truth(label),'stratum':stratum,'source_image':{'kind':'fixed_development_or_support','path':path,'sha256':expected},
            'association_group_id':association})
    for dish,binding in devbinding['development_bindings_private'].items():
        old=binding['historical_source_binding_private'];sample=old['sample_id']
        oldrecord(old,(oldlabels if sample in oldlabels else trainlabels)[sample],binding['stratum'],
                  binding['fold_unit'],binding['prospective_fold'],binding['association_group_id'])
    asafolds={}
    for row in core:
        component=mapping['c:'+row['sample_id'].split('-',2)[1]]
        require(component not in asafolds or asafolds[component]==row['fold'],'P_ASA_core_crossfold_bridge')
        asafolds[component]=row['fold'];oldrecord(row,oldlabels[row['sample_id']],'asa_core',component,row['fold'],component)
    for index,component in enumerate(expansion['chosen_broader_components_private']):
        require(component not in asafolds,'P_broader_core_component_collision');asafolds[component]=index%5
    archive_members=defaultdict(list)
    for entry in asa['asa_archive_identity']['members']:archive_members[entry['image']].append(entry)
    for item in expansion['core_extra_proposals_private']+expansion['broader_development_proposals_private']:
        code=item['FoodCode'];source=item['portion_source_private'];grams=float(source['Weight'])
        sample='asa24-'+code+'-extra-'+item['source_row_sha256'];group=item['association_group_id']
        entry=min(archive_members[item['Image']],key=lambda e:e['member_index'])
        require(entry['bytes_sha256']==item['image_sha256'],'P_bound_ASA_member_changed')
        records.append({'row':{'sample_id':sample,'dataset':'asa24','split':'dev','fold':asafolds[group],'group_id':group,
            'image_path':'not-a-runtime-path','image_sha256':item['image_sha256']},
            'label':{'truth':{'weight':grams,**{k:grams*catalog['foods'][code]['density'][k]/100 for k in TARGETS[1:]}},
                     'food_code':code,'size':'all_legal'},'stratum':item['stratum'],
            'source_image':{'kind':'bound_ASA_archive_member','member_index':entry['member_index'],
                            'member_path':entry['member_path'],'sha256':entry['bytes_sha256'],'bytes':entry['bytes']},
            'association_group_id':group})
    require(devbinding['counts']['development_rows']==314,'P_all_314_capacity_development_rows_required')
    # Preserve proposal identities, never candidate target values or source
    # portion weights in the independent acceptance proposal publication.
    asa_proposal=deepcopy(expansion['validation_proposal_private'])
    asa_proposal['new_triplet_rows']=[{k:v for k,v in r.items() if k not in ('portion_source_private',)}
                                      for r in asa_proposal['new_triplet_rows']]
    proposed={**acceptance,'official_RGB_bytes':sum(objects[d] for d in acceptance['new_acceptance_dish_ids_private']),
        'new_official_RGB_objects_private':[{
            'dish_id':d,'source_url':'https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/imagery/realsense_overhead/'+d+'/rgb.png',
            'official_response_bytes':objects[d],'image_content_sha256':None}
            for d in acceptance['new_acceptance_dish_ids_private']],
        'max_response_bytes':5*1024*1024,'max_attempts_per_fixed_URL':3,
        'future_response_body_budget_bytes':200*1024*1024,
        'postdownload_blind_exact_collision_check_required':True,'no_download_performed':True}
    assets={}
    descriptor=decode(reader.read(PREFIX+'data/vectors/manifest.json'))
    for path in ('data/catalog.json','data/vectors/manifest.json','data/vectors/codes.json',VECTOR):
        assets[path]=reader.digest(PREFIX+path)
    for filename,digest in descriptor['files'].items():
        require(type(filename) is str and '/' not in filename and filename not in ('.','..') and _hash(digest),
                'P_fixed_vector_descriptor_file_required')
        path='data/vectors/'+filename;reader.bind(PREFIX+path,digest);assets[path]=reader.digest(PREFIX+path)
    def image_loader(spec):
        if spec['kind']=='fixed_development_or_support':
            require(any(spec['path'].startswith(PREFIX+p) for p in ('data/asa24/dev/images/','data/nutrition5k/dev/images/','round4/data/train/images/')),
                    'P_fixed_development_image_role_required')
            return reader.read(spec['path'])
        require(spec['kind']=='bound_ASA_archive_member','P_registered_development_image_source_required')
        with asa_archive._open(repo) as stream:
            require(asa_archive._digest(stream)[0]==pins[ASA_SOURCES[0]],'P_ASA_archive_changed')
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                infos=archive.infolist();index=spec['member_index'];require(type(index) is int and index in range(len(infos)),
                                                                       'P_bound_ASA_member_index_changed')
                entry=infos[index];asa_archive._member(entry)
                require(entry.filename==spec['member_path'] and entry.file_size==spec['bytes'] and entry.file_size<=5*1024*1024,
                        'P_bound_ASA_member_path_or_size_changed')
                with archive.open(entry) as image:raw=image.read(5*1024*1024+1)
        require(sha(raw)==spec['sha256'],'P_ASA_member_bytes_changed');return raw
    revalidate()
    closure={'schema_version':1,'status':'reviewed_development_capacity_v4_proposals_pending',
        'original_global_guard_remains_stopped':True,'actual_api_exposure_complete':False,'source_association_complete':False,
        'global_supplied_byte_closure_complete':False,'global_supplied_pixel_closure_complete':False,
        'development_numeric_eligibility_evaluated':True,'acceptance_candidate_target_validity_evaluated':True,
        'source_receipts_sha256':RECEIPTS,'source_disposition_private':scope,
        'N5_development_identity_bindings_private':devbinding,'ASA_original_core_private':core,
        'ASA_expansion_shortfall_reasons':expansion['shortfall_reasons'],
        'ASA_development_group_order_private':expansion['broader_component_order_private'],
        'ASA_chosen_broader_components_private':expansion['chosen_broader_components_private'],
        'N5_support_is_fresh_or_independent':False}
    return {'records':records,'catalog':catalog,'old_catalog':oldcatalog,'assets':assets,'closure':closure,
            'proposals':{'nutrition5k':proposed,'asa24':asa_proposal,'pending_boundary_confirmation':True}},image_loader,revalidate


def _prepare_at(repo,*,source_loader=_production_inputs,required=PREPARATION_SOURCES|ASSETS,receipts=RECEIPTS):
    """Private synthetic entry; production exposes none of these overrides."""
    reader=_review(repo,required=required,receipts=receipts)
    bundle,image_loader,revalidate=source_loader(Path(repo),reader)
    return _produce(Path(repo),reader,bundle,image_loader=image_loader,revalidate=revalidate)


def prepare():
    require(isolated_network(Path('/proc/self/net/dev').read_bytes()),'P_preparation_network_namespace_required')
    return _prepare_at(REPO)


if __name__=='__main__':
    require(len(sys.argv)==1,'P_preparation_CLI_overrides_refused')
    try:print(json.dumps(prepare(),sort_keys=True))
    except Exception as exc:
        print(json.dumps({'status':'P_preparation_refused_preserve_state','error_type':type(exc).__name__}))
        raise SystemExit(1)
