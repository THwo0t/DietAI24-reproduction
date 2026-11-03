"""Pure ASA metadata topology with honest, possibly incomplete byte coverage.

Input must contain all parsed metadata associations before eligibility filters,
plus historical association edges. External source completeness is NOT proved
here. Unknown images remain graph nodes; they never receive synthetic hashes.
No sample selection, target values or real files are consumed by this module.
"""
from collections import defaultdict

from qualification import code8
import hashlib

ROLES={'history','core','validation','training','retired'}


def require(value,code):
    if not value:raise ValueError(code)


def image_name(value):
    require(isinstance(value,str) and value and '/' not in value and '\\' not in value
            and value not in ('.','..'),'image_basename_required')
    return value


def sha_value(value):
    require(isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value),
            'actual_sha256_required')
    return value


def inventory(pairs,known_image_hash_rows,protected,*,unknown_images):
    """Return PRIVATE observed graph plus a fixed-schema aggregate.

    known_image_hash_rows is a sequence, not a dict, so conflicting basename
    entries cannot disappear through a caller's last-value overwrite. The
    caller must additionally prove complete ZIP-member and metadata coverage.
    A supplied-graph byte gap prevents a full byte-closure claim globally,
    including apparently unaffected known components.
    """
    require(set(protected)==ROLES,'complete_protected_role_inventory_required')
    pairs=[(code8(code),image_name(name)) for code,name in pairs]
    require(pairs,'nonempty_metadata_associations_required')
    hashes={}
    for name,value in known_image_hash_rows:
        name,value=image_name(name),sha_value(value)
        require(name not in hashes or hashes[name]==value,'conflicting_image_basename_bytes')
        hashes[name]=value
    missing={name for _,name in pairs}-hashes.keys()
    unknown={image_name(name) for name in unknown_images}
    require(unknown==missing,'exact_unknown_image_inventory_required')
    parent={}
    def find(node):
        parent.setdefault(node,node)
        while parent[node]!=node:
            parent[node]=parent[parent[node]];node=parent[node]
        return node
    def join(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[max(a,b)]=min(a,b)
    # All metadata edges precede byte evidence and any qualification.
    for code,name in pairs:join('c:'+code,'i:'+name)
    for name,value in hashes.items():join('i:'+name,'h:'+value)
    observed=set(parent);anchors={};unmatched={}
    for role,seeds in protected.items():
        require(set(seeds)=={'codes','images','hashes'},'complete_protected_anchor_types_required')
        nodes=(['c:'+code8(v) for v in seeds['codes']]
             +['i:'+image_name(v) for v in seeds['images']]
             +['h:'+sha_value(v) for v in seeds['hashes']])
        anchors[role]=nodes
        unmatched[role]={node for node in nodes if node not in observed}
        for node in nodes:find(node)
    members=defaultdict(list)
    for node in sorted(parent):members[find(node)].append(node)
    names={root:'asa-rawmeta-'+hashlib.sha256('\n'.join(nodes).encode()).hexdigest()
           for root,nodes in members.items()}
    mapping={node:names[find(node)] for node in parent}
    grouped={role:{mapping[node] for node in nodes} for role,nodes in anchors.items()}
    unresolved={mapping['i:'+name] for name in unknown}
    unresolved|={mapping[node] for nodes in unmatched.values() for node in nodes}
    intersections={a+'__'+b:len(grouped[a]&grouped[b])
        for i,a in enumerate(sorted(ROLES)) for b in sorted(ROLES)[i+1:]}
    supplied_complete=not missing and not any(unmatched.values())
    private={'node_groups':mapping,'members':{names[root]:nodes for root,nodes in members.items()},
        'protected_groups':grouped,'unknown_images':unknown,'unresolved_groups':unresolved}
    aggregate={'supplied_association_rows':len(pairs),
        'supplied_metadata_images':len({name for _,name in pairs}),
        'actual_hashed_image_names':len(hashes),'unknown_image_count':len(unknown),
        'unresolved_component_count':len(unresolved),
        'protected_unresolved_component_counts':{r:len(groups&unresolved) for r,groups in grouped.items()},
        'observed_protected_intersections':intersections,
        'supplied_graph_byte_closure_complete':supplied_complete,
        'external_source_completeness_proven':False,
        'status':'supplied_graph_complete' if supplied_complete else 'incomplete_identity_coverage',
        'claim_scope':'Observed metadata topology and real supplied byte hashes only; unknown bytes may join other components.'}
    return private,aggregate
