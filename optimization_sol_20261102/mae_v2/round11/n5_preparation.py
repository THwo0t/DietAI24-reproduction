"""Blind N5 pool computation from authenticated in-memory source bytes.

No CLI, files, network, sample selection or model calls. The future isolated
runner must authenticate the source reader and complete exposure inventory.
Only ingredient masses are interpreted for protected metadata graph linkage;
the five protected dish targets are never converted or used for eligibility.
"""
import csv
from decimal import Decimal,InvalidOperation
import hashlib
import io
import math
from pathlib import Path
import re
import sys

BASE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BASE/'src'))
from cohorts_v2 import make_scan,DISH
from n5_identity import reconcile
from n5_pool import candidate_pool,TARGETS

COUNTS={'core':84,'validation':200,'original_development':100,'training':230}
COLUMNS=dict(zip(TARGETS,('total_mass','total_calories','total_fat','total_carbs','total_protein')))


def require(value,code):
    if not value:raise ValueError(code)


def raw_scans(raw_tables):
    """Reproduce cohorts_v2.parse_metadata on captured, hash-checked bytes."""
    require({'cafe1','cafe2'}<=set(raw_tables),'both_complete_raw_cafes_required')
    scans={}
    for slot in ('cafe1','cafe2'):
        cafe='dish_metadata_'+slot
        for row in csv.reader(io.StringIO(raw_tables[slot].decode('utf-8-sig'))):
            require(len(row)>=6 and DISH.fullmatch(row[0]),'invalid_metadata_row')
            start,declared=6,None
            if len(row)>6 and not row[6].startswith('ingr_'):
                try:declared=int(row[6])
                except ValueError:raise ValueError('invalid_ingredient_structure') from None
                start=7
            require((len(row)-start)%7==0,'invalid_ingredient_structure')
            chunks=[row[i:i+7] for i in range(start,len(row),7)]
            require(declared is None or declared==len(chunks),'ingredient_count_mismatch')
            recipe=hashlib.sha256(', '.join(sorted(chunk[1] for chunk in chunks)).encode()).hexdigest()
            scan=make_scan(row[0],cafe,[(chunk[0],chunk[2]) for chunk in chunks],recipe)
            require(scan.dish_id not in scans,'duplicate_raw_dish_id')
            scans[scan.dish_id]=scan
    return scans


def official_rgb_sizes(objects):
    result={}
    for row in objects:
        match=re.fullmatch(r'nutrition5k_dataset/imagery/realsense_overhead/(dish_[0-9]{10})/rgb\.png',row['name'])
        if match:
            dish=match[1];text=str(row['size'])
            require(dish not in result and text.isdigit(),'unique_official_rgb_object_required')
            size=int(text)
            require(0<size<=5_000_000,'official_rgb_size_outside_bound')
            result[dish]=size
    return result


def eligible_available(raw,scans,allowed,objects):
    """Only unblocked original-frame rows receive numerical target parsing."""
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    require(reader.fieldnames is not None and set(COLUMNS.values())|{'dish_id'}<=set(reader.fieldnames),
            'complete_available_frame_columns_required')
    seen=set();recipes=set();rows=[];truths={};zero_nutrition=0
    for row in reader:
        dish=row['dish_id']
        require(dish in scans and dish in objects and dish not in seen,'original_available_identity_changed')
        seen.add(dish);recipe=scans[dish].recipe_hash
        require(recipe not in recipes,'original_available_recipe_deduplication_required');recipes.add(recipe)
        if dish not in allowed:continue
        try:values={key:Decimal(row[column]) for key,column in COLUMNS.items()}
        except (InvalidOperation,ValueError,TypeError):raise ValueError('invalid_unblocked_candidate_target') from None
        require(all(v.is_finite() and v>=0 for v in values.values()) and values['weight']>0,
                'finite_complete_positive_candidate_weight_required')
        if not any(values[key] for key in TARGETS[1:]):zero_nutrition+=1;continue
        truth={key:float(value) for key,value in values.items()}
        require(all(math.isfinite(v) for v in truth.values()),'nonfinite_unblocked_candidate_target')
        if not scans[dish].masses:continue
        rows.append({'dish_id':dish,'truth':truth});truths[dish]=truth
    return rows,truths,{'original_available_frame_count':len(seen),
        'unblocked_missing_nutrition_exclusions':zero_nutrition}


def inspect_pool(projection,*,expected_counts=None):
    """PRIVATE result and ID-free aggregate; never freeze or select a cohort."""
    scans=raw_scans(projection['raw_tables'])
    identities,summary=reconcile(scans,projection['index'],projection['snapshot'],
        projection['cohort_proposal'],projection['registry'],projection['train_entries'],
        projection['train_pixels'],expected_counts=COUNTS if expected_counts is None else expected_counts)
    objects=official_rgb_sizes(projection['official_objects'])
    available,truths,frame=eligible_available(projection['raw_tables']['available'],scans,
                                             identities['allowed_ids'],objects)
    candidates,pool=candidate_pool(scans,available,identities['mapping'],identities['quarantine'],
                                   identities['protected'])
    require(set(candidates)<=identities['allowed_ids'],'previous_screening_exclusion_lost')
    private={'identities':identities,'candidates':candidates,'truths':truths,
             'official_object_bytes':{dish:objects[dish] for dish in candidates}}
    aggregate={**summary,**frame,'eligible_images':len(candidates),'eligible_groups':pool['eligible_groups'],
        'source_files_bound':len(projection['source_hashes']),
        'new_samples_selected':0,'new_downloads':0,'new_model_requests':0,
        'latest_exposure_completeness_proven':False,
        'scope':'Supplied authenticated sources only; a registered complete exposure inventory is still required.'}
    return private,aggregate
