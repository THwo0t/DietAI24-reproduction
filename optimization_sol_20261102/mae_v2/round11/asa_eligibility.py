"""Pure ASA portion eligibility AFTER complete blind association screening.

No files, sampling, targets from blocked codes or inference. Only the top1000
condition may differ in the broader frame. New code/hash source conflicts are
reported before a caller compares exact existing-core identity/reference pins.
"""
from collections import Counter,defaultdict
from decimal import Decimal,InvalidOperation

from qualification import code8


def number(value):
    try:result=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):raise ValueError('invalid_portion_source_number') from None
    if not result.is_finite():raise ValueError('nonfinite_portion_source_number')
    return result


def integer(value):
    result=number(value)
    if result!=result.to_integral_value() or result<0:raise ValueError('integer_portion_source_code_required')
    return int(result)


def legal_rows(metadata,inventory,food_weights,*,permitted_codes,fndds_codes,top_codes,
               image_hashes,broader_frame=False):
    """PRIVATE rows/ambiguity identities and an ID-free aggregate.

    The caller must refuse incomplete global byte coverage and new protected
    graph/fold bridges before calling this function. permitted_codes is derived
    from that identity audit, never from numerical model errors. It must keep
    original core references immutable or stop for separately registered repair.
    """
    permitted={code8(v) for v in permitted_codes}&{code8(v) for v in fndds_codes}
    if not broader_frame:permitted&={code8(v) for v in top_codes}
    portions={};units={};excluded=Counter()
    for row in inventory:
        image=row['FileName'];text='' if row['Portion'] is None else str(row['Portion']).strip()
        if text.lower() in ('nan','<na>'):text=''
        if image in portions and portions[image]!=text:raise ValueError('conflicting_inventory_portion_text')
        portions[image]=text
    for row in food_weights:
        code=code8(row['Food Code'])
        if code not in permitted:continue
        key=(code,integer(row['Portion Code']));value=number(row['Portion Weight'])
        if value<0:raise ValueError('negative_exact_food_weight_mapping')
        if key in units and units[key]!=value:raise ValueError('conflicting_exact_food_weight_mapping')
        units[key]=value
    # Detect all exact-key conflicts first, including zero/positive evidence.
    # Only unambiguous zero-only nonquantitative mappings may be excluded.
    units={key:value for key,value in units.items() if value>0}
    grouped=defaultdict(list);seen=set()
    for position,row in enumerate(metadata):
        code=code8(row['FoodCode'])
        if code not in permitted:excluded['outside_permitted_frame']+=1;continue
        if row['ImageType']!='PORTION' or integer(row['ModCode'])!=0:
            excluded['nonoriginal_portion_type']+=1;continue
        image=row['Image'];portion=portions.get(image,'')
        if image not in image_hashes or not portion or portion.lower()=='nan':
            excluded['unavailable_image_or_portion']+=1;continue
        pc=integer(row['PortionCode']);multiplier=number(row['Multiplier'])
        unit=Decimal(1) if pc==98 else units.get((code,pc))
        if unit is None:excluded['missing_exact_weight_mapping']+=1;continue
        if multiplier<=0:excluded['nonpositive_multiplier']+=1;continue
        grams=unit*multiplier
        record={'FoodCode':code,'Image':image,'Portion':portion,'PortionCode':pc,
            'Multiplier':multiplier,'PortionWeight':unit,'Weight':grams,'_source_position':position}
        signature=tuple(record[k] for k in ('FoodCode','Image','Portion','PortionCode',
                                           'Multiplier','PortionWeight','Weight'))
        if signature in seen:continue
        seen.add(signature);grouped[code].append(record)
    selected=[];ambiguous=set()
    for code,rows in sorted(grouped.items()):
        by_image=defaultdict(list);by_hash=defaultdict(list)
        for row in rows:
            by_image[row['Image']].append(row['Weight'])
            by_hash[image_hashes[row['Image']]].append(row['Weight'])
        conflicting_images={image for image,weights in by_image.items()
                            if max(weights)-min(weights)>min(weights)*Decimal('0.01')}
        conflicting_hashes={value for value,weights in by_hash.items()
                            if max(weights)-min(weights)>min(weights)*Decimal('0.01')}
        bad={row['Image'] for row in rows if row['Image'] in conflicting_images
             or image_hashes[row['Image']] in conflicting_hashes}
        ambiguous.update((code,image) for image in bad)
        rows=[row for row in rows if row['Image'] not in bad]
        frequency=Counter(row['PortionCode'] for row in rows);chosen={}
        for row in sorted(rows,key=lambda r:(-frequency[r['PortionCode']],r['PortionCode'],r['_source_position'])):
            chosen.setdefault(row['Image'],row)
        texts=defaultdict(set)
        for row in chosen.values():texts[row['Portion']].add(row['Weight'])
        if any(len(weights)>1 for weights in texts.values()):
            excluded['portion_text_has_multiple_weights']+=1;continue
        if len({row['Weight'] for row in chosen.values()})<3:
            excluded['fewer_than_three_distinct_weights']+=1;continue
        selected.extend({key:value for key,value in row.items() if not key.startswith('_')}
                        for _,row in sorted(chosen.items()))
    return {'rows':selected,'ambiguous_code_images':ambiguous},{
        'eligible_codes':len({row['FoodCode'] for row in selected}),'eligible_portion_rows':len(selected),
        'ambiguous_code_image_pairs':len(ambiguous),'excluded':dict(excluded),
        'broader_frame':bool(broader_frame),'new_samples_selected':0,
        'external_identity_isolation_proven':False}
