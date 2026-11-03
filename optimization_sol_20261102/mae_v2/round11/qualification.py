"""Pure expansion-audit primitives; no data loading, selection, download or API.

The future isolated preparer must supply the complete source association table
and byte fingerprints before eligibility filtering. Current O is not imported
or modified. No function here constitutes a completed real-data audit.
"""
from collections import defaultdict
from decimal import Decimal
import hashlib
import math


def code8(value):
    text=str(value)
    if len(text)!=8 or not text.isdigit():raise ValueError('exact_eight_digit_code_required')
    return text


def associations(pairs,image_hashes,protected):
    """Return private complete components and aggregate protected intersections.

    protected is a role→{codes,images,hashes} mapping supplied by the blind
    adapter. Unknown anchors remain explicit singleton nodes; they cannot
    manufacture eligibility. All components include pre-filter bridge codes.
    """
    parent={}
    def find(node):
        parent.setdefault(node,node)
        root=node
        while parent[root]!=root:root=parent[root]
        while node!=root:node,parent[node]=parent[node],root
        return root
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[max(a,b)]=min(a,b)
    def image(value):
        if not isinstance(value,str) or not value or '/' in value or '\\' in value or value in ('.','..'):
            raise ValueError('image_basename_required')
        return value
    def hashed(value):
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('sha256_required')
        return value
    pairs=[(code8(code),image(name)) for code,name in pairs]
    if {name for _,name in pairs}-set(image_hashes):
        raise ValueError('complete_pair_image_hashes_required')
    for code,name in pairs:union('c:'+code,'i:'+name)
    for name,value in image_hashes.items():union('i:'+image(name),'h:'+hashed(value))
    anchors={}
    for role,seeds in protected.items():
        if set(seeds)!={'codes','images','hashes'}:raise ValueError('all_protected_anchor_types_required')
        anchors[role]=(['c:'+code8(v) for v in seeds['codes']]
            +['i:'+image(v) for v in seeds['images']]+['h:'+hashed(v) for v in seeds['hashes']])
        for node in anchors[role]:find(node)
    members=defaultdict(list)
    for node in sorted(parent):members[find(node)].append(node)
    names={root:'asa-expanded-'+hashlib.sha256('\n'.join(values).encode()).hexdigest()
           for root,values in members.items()}
    mapping={node:names[find(node)] for node in parent}
    roles={role:{mapping[node] for node in nodes} for role,nodes in anchors.items()}
    overlap={a+'__'+b:len(roles[a]&roles[b]) for i,a in enumerate(sorted(roles))
             for b in sorted(roles)[i+1:]}
    return {'node_groups':mapping,'protected_groups':roles,
            'members':{names[root]:values for root,values in members.items()}}, {
        'components':len(members),'protected_component_counts':{r:len(v) for r,v in roles.items()},
        'protected_intersections':overlap}


def ambiguous_query_weights(rows,image_hashes):
    """Flag byte-identical same-code queries with >1% inconsistent references.

    No model error is consulted. A future protocol must specify how these
    source conflicts affect new eligibility; it must not silently rewrite O.
    """
    weights=defaultdict(list)
    for row in rows:
        value=row['Weight']
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
            raise ValueError('finite_positive_source_weight_required')
        weights[(code8(row['FoodCode']),image_hashes[row['Image']])].append(Decimal(str(value)))
    return {key for key,values in weights.items() if max(values)-min(values)>min(values)*Decimal('0.01')}


def new_group_order(groups,*,seed,count):
    """Fixed whole-group order; no outcomes or nutrition can enter selection."""
    if type(count) is not int or count<0 or not isinstance(seed,str) or not seed:
        raise ValueError('fixed_seed_and_nonnegative_group_count_required')
    values=set(groups)
    if any(not isinstance(v,str) or not v for v in values):raise ValueError('group_id_required')
    return sorted(values,key=lambda v:(hashlib.sha256((seed+'|'+v).encode()).hexdigest(),v))[:count]
