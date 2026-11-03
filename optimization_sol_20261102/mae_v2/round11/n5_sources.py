"""Restricted N5 identity-source reader; no CLI, inference or real audit here.

Only fixed identity seals, prior audit projections and raw metadata may be
opened. Seals are checked without chasing protected image/label paths in their
inventories. A later reviewed runner must enforce O completion, registration
and latest exposure discovery before invoking this reader on actual sources.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from source_census import directory_fd,same_directory

PREFIX='optimization_sol_20261102/mae_v2/'
PATHS={
    'index':PREFIX+'round4/proposal/private_audit_index.json',
    'original_snapshot':PREFIX+'data/freeze/source_snapshot.json',
    'final_snapshot':PREFIX+'data/freeze/final_source_snapshot.json',
    'validation_seal':PREFIX+'data/freeze/validation_freeze.json',
    'development_seal':PREFIX+'data/cohorts/dev_freeze.json',
    'cohort_proposal':PREFIX+'data/freeze/cohort_proposal.json',
    'registry':'optimization_sol_20261102/data/freeze/exclusion_registry.json',
    'training_proposal':PREFIX+'round4/proposal/private_train_pool_proposal.json',
    'training_summary':PREFIX+'round4/proposal/raw_rgb_summary.json',
    'training_freeze':PREFIX+'round4/data/train/freeze.json',
    'training_audit':PREFIX+'round4/data/train/audit.json',
    **{name:'Nutrition5k/metadata/'+filename for name,filename in (
        ('cafe1','dish_metadata_cafe1.csv'),('cafe2','dish_metadata_cafe2.csv'),
        ('available','dish_metadata_available.csv'),('objects','realsense_overhead_objects.json'))}}
ANCHORS={
    'index':'e0a57d390fced7b3d811900e3cfd634bfaced7b4f7c1b897c59b495aac4fc5f2',
    'original_snapshot':'2b933e6434b78116646f47adfe8544ed9fc5fbb174b9f85422cccdeddc4b7c05',
    'final_snapshot':'bea5ad2910a6637c0a80671145a02ce803fdeb936f1b7da1d071218bb03e1e4d',
    'validation_seal':'ff40c572ecc457e331d1e720ba17c7960cffeaf312add66ee94f9ba64bd4a82b',
    'development_seal':'a5f5edbb6082e4c70a1bf6eccfcd2e11be1b3b1f5de5ac12e3bcc3a38f6c2681',
    'training_proposal':'eddf9a644114f5b4aecc4d906dbdec6ee0eaecd80b97e23743d9edf663e03eb0',
    'training_summary':'3e3d3dc8f66faf1176971480ad988925c5b63d5dc92f8673a3b75dd54c70f810',
    'training_freeze':'885f8d1a0573313e9e09771f3c38ec938b807e9ffcc9525d706867d3d0d081cb'}
HEX=re.compile(r'[0-9a-f]{64}\Z')
MAX_SOURCE_BYTES=32*1024*1024


def require(value,code):
    if not value:raise ValueError(code)


def unique_object(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'duplicate_source_json_key')
        result[key]=value
    return result


def decode(raw):
    def refuse(_):raise ValueError('nonfinite_source_json')
    return json.loads(raw,object_pairs_hook=unique_object,parse_constant=refuse)


class IdentitySourceReader:
    def __init__(self,repo):
        self.repo=Path(repo)
        require(self.repo.is_absolute() and self.repo.resolve()==self.repo,'canonical_source_root_required')
        self.hashes={};self.bound={}

    def _read(self,slot):
        require(slot in PATHS,'unregistered_source_slot')
        path=self.repo/PATHS[slot]
        require(path.resolve()==path,'linked_source_path_refused')
        parent=directory_fd(path.parent)
        try:
            fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            try:
                info=os.fstat(fd)
                require(stat.S_ISREG(info.st_mode) and info.st_size<=MAX_SOURCE_BYTES,
                        'regular_bounded_source_required')
                with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(MAX_SOURCE_BYTES+1)
                require(len(raw)<=MAX_SOURCE_BYTES,'source_size_bound_exceeded')
                current=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
                require((current.st_dev,current.st_ino)==(info.st_dev,info.st_ino)
                        and same_directory(path.parent,parent),'source_path_changed')
                return raw
            finally:os.close(fd)
        finally:os.close(parent)

    def bind(self,slot,expected):
        require(isinstance(expected,str) and HEX.fullmatch(expected),'registered_source_hash_required')
        raw=self._read(slot);actual=hashlib.sha256(raw).hexdigest()
        require(actual==expected,'identity_source_hash_changed')
        require(slot not in self.hashes or self.hashes[slot]==actual,'identity_source_rebinding_refused')
        value=decode(raw) if PATHS[slot].endswith('.json') else raw
        self.hashes[slot]=actual;self.bound[slot]=raw
        return value

    def revalidate(self):
        require(set(self.hashes)==set(PATHS),'complete_fixed_identity_source_inventory_required')
        for slot,expected in self.hashes.items():
            require(hashlib.sha256(self._read(slot)).hexdigest()==expected,'identity_source_hash_changed')


def load_identity_sources(repo,*,anchors=None):
    """Return a PRIVATE projection; overrides exist for synthetic fixtures only.

    Production callers must use the module's source-pinned ANCHORS unchanged.
    This reader cannot certify current protected files it deliberately does not
    open, or any historical exposure after the last registered snapshot.
    """
    anchors=deepcopy(ANCHORS if anchors is None else anchors)
    require(set(anchors)==set(ANCHORS),'complete_trusted_identity_anchors_required')
    reader=IdentitySourceReader(repo)
    values={slot:reader.bind(slot,expected) for slot,expected in anchors.items()}
    index=values['index'];valseal=values['validation_seal'];trainfreeze=values['training_freeze']
    require(values['development_seal']['rules_sha256']==valseal['rules_sha256'],
            'development_validation_rule_seals_differ')
    require(trainfreeze['binding']['proposal_sha256']==anchors['training_proposal']
            and trainfreeze['binding']['private_audit_index_sha256']==anchors['index'],
            'training_identity_binding_changed')
    values['cohort_proposal']=reader.bind('cohort_proposal',valseal['proposal_sha256'])
    values['training_audit']=reader.bind('training_audit',trainfreeze['artifacts']['audit.json'])
    # Resolve ONLY the named permitted sources. Never recurse through an index
    # or seal's self-described paths: it also records protected images/labels.
    for slot in ('registry','cafe1','cafe2','available','objects'):
        relative=PATHS[slot]
        matches={index['source_sha256'][key] for key in (relative,str(reader.repo/relative))
                 if key in index['source_sha256']}
        require(len(matches)==1,'unambiguous_fixed_source_pin_required')
        values[slot]=reader.bind(slot,matches.pop())
    require(all(values['final_snapshot']['source_sha256'].get(key)==value
                for key,value in values['original_snapshot']['source_sha256'].items()),
            'old_source_snapshot_identity_changed')
    require(values['original_snapshot']['component_members']==values['final_snapshot']['component_members'],
            'old_source_snapshot_partition_changed')
    reader.revalidate()
    projection={
        'index':{**{key:index[key] for key in ('original_components','recipe_sha256','screening_components',
            'blocked_screening_components')},'known_image_fingerprints':[
                {key:row[key] for key in ('dish_id','bytes_sha256','rgb_sha256')}
                for row in index['known_image_fingerprints']]},
        'snapshot':{key:values['final_snapshot'][key] for key in ('component_members',
            'ambiguous_component_ids','active_development_ids','historical_exposure_ids')},
        'cohort_proposal':{key:values['cohort_proposal'][key] for key in ('selected_dish_ids',
            'original_development_exposure_ids','retired_validation_dish_ids')},
        'registry':{key:values['registry'][key] for key in ('exposed_dish_ids','local_dish_ids',
            'exposed_ingredient_group_sha256')},
        'train_entries':[{'dish_id':row['dish_id']} for row in values['training_proposal']['entries']],
        'train_pixels':[{key:row[key] for key in ('dish_id','bytes_sha256','rgb_sha256')}
                        for row in values['training_audit']['candidate_audit']],
        'raw_tables':{slot:values[slot] for slot in ('cafe1','cafe2','available')},
        'official_objects':values['objects'],'source_hashes':deepcopy(reader.hashes)}
    return projection,reader
