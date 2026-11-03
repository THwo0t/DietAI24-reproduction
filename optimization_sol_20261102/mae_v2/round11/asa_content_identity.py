"""Pure ASA exact-content graph and bounded PNG fingerprint prototype.

This extends, rather than changes, the reviewed byte-only P-B contract. It has
no file reader, phase permission, source authentication, sampling or inference.
The future isolated preparer must supply every metadata image and every local
PNG (including unassociated members), and authenticate all historical anchors.
No real project image is opened here. RGB equality is exact under the declared
decoder rules; resized/cropped/perceptually similar images are outside scope.
"""
from collections import defaultdict
import hashlib
import io
import json
import struct
import warnings

from PIL import Image

from asa_identity import ROLES,image_name as original_image_name,require,sha_value
from qualification import code8

ALGORITHM='image-model-input-rgb-u32be-v3'
MAX_BYTES=8*1024*1024
MAX_PIXELS=16*1024*1024
ANCHOR_TYPES={'codes','images','hashes','rgb_hashes'}


def image_name(value):
    original_image_name(value)
    require(all(ord(character)>=32 and ord(character)!=127 for character in value),
            'control_character_in_image_identity')
    return value


def _image_fingerprint(raw,formats,kind):
    """Fingerprint bounded supported image bytes; unsupported decoding is fatal.

    Match opt_pipeline.encode_image's pre-resize PIL.convert('RGB') exactly:
    no alpha compositing, color management, or EXIF rotation. Single-frame PNG/JPEG
    modes supported by Pillow conversion are accepted. Alpha/profile/orientation
    differences may intentionally join; this is not universal rendered appearance
    or physical-plate identity. Dimensions and the version prefix bind the digest.
    Text chunks and compression level do not change this model-input identity.
    """
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_BYTES,'bounded_'+kind+'_bytes_required')
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(raw)) as image:
                width,height=image.size
                require(image.format in formats and width>0 and height>0
                        and width*height<=MAX_PIXELS,'supported_bounded_'+kind+'_required')
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                require(getattr(image,'n_frames',1)==1,'animated_'+kind+'_out_of_scope')
                rgb=image.convert('RGB');rgb.load()
                payload=ALGORITHM.encode()+b'\0'+struct.pack('>II',width,height)+rgb.tobytes()
        except ValueError:
            raise
        except Exception:
            raise ValueError(kind+'_decode_failed') from None
    return {'bytes_sha256':hashlib.sha256(raw).hexdigest(),
            'rgb_sha256':hashlib.sha256(payload).hexdigest(),
            'width':width,'height':height,'algorithm':ALGORITHM}


def image_fingerprint(raw):
    """Content-detected PNG/JPEG model-input identity, independent of extension."""
    return _image_fingerprint(raw,('PNG','JPEG'),'image')


def png_fingerprint(raw):
    """PNG-only compatibility entry point using the registered v3 identity."""
    return _image_fingerprint(raw,('PNG',),'png')


def build_asa_content_inventory(pairs,image_fingerprints,protected,*,metadata_images,
                                unknown_byte_images,unknown_pixel_images):
    """Return PRIVATE graph/fingerprints and an ID-free bounded aggregate.

    Unknown inventories must exactly match the full supplied image universe.
    Empty historical anchor collections do not prove exposure completeness.
    Neither a complete supplied graph nor this function authenticates sources.
    """
    require(set(protected)==ROLES,'complete_protected_role_inventory_required')
    pairs=[(code8(code),image_name(name)) for code,name in pairs]
    require(pairs,'nonempty_metadata_associations_required')
    metadata={image_name(name) for name in metadata_images}
    require({name for _,name in pairs}<=metadata,'all_associated_metadata_images_required')
    fingerprints={};byte_pixels={};pixel_sizes={}
    for supplied in image_fingerprints:
        require(set(supplied)=={'image','bytes_sha256','rgb_sha256','width','height','algorithm'},
                'complete_image_fingerprint_schema_required')
        row=dict(supplied);name=image_name(row['image']);byte=sha_value(row['bytes_sha256'])
        pixel=row['rgb_sha256']
        if pixel is None:
            require(all(row[k] is None for k in ('width','height','algorithm')),
                    'unknown_pixel_metadata_must_be_empty')
        else:
            pixel=sha_value(pixel);size=(row['width'],row['height'])
            require(row['algorithm']==ALGORITHM and all(type(v) is int and v>0 for v in size)
                    and size[0]*size[1]<=MAX_PIXELS,'registered_pixel_semantics_required')
            require(pixel not in pixel_sizes or pixel_sizes[pixel]==size,'conflicting_pixel_dimensions')
            require(byte not in byte_pixels or byte_pixels[byte]==(pixel,size),
                    'same_bytes_have_conflicting_pixels')
            pixel_sizes[pixel]=size;byte_pixels[byte]=(pixel,size)
        if name in fingerprints:
            old=fingerprints[name]
            require(old['bytes_sha256']==byte,'conflicting_image_basename_bytes')
            require(old['rgb_sha256'] is None or pixel is None or old==row,
                    'conflicting_image_basename_pixels')
            if pixel is None:continue
        fingerprints[name]=row
    universe=metadata|set(fingerprints)
    unknown_bytes={image_name(v) for v in unknown_byte_images}
    unknown_pixels={image_name(v) for v in unknown_pixel_images}
    require(unknown_bytes==universe-fingerprints.keys(),'exact_unknown_byte_inventory_required')
    known_pixels={name for name,row in fingerprints.items() if row['rgb_sha256'] is not None}
    require(unknown_pixels==universe-known_pixels,'exact_unknown_pixel_inventory_required')
    parent={}
    def find(node):
        parent.setdefault(node,node)
        while parent[node]!=node:
            parent[node]=parent[parent[node]];node=parent[node]
        return node
    def join(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[max(a,b)]=min(a,b)
    for name in sorted(universe):find('i:'+name)
    for code,name in pairs:join('c:'+code,'i:'+name)
    for name,row in fingerprints.items():
        join('i:'+name,'b:'+row['bytes_sha256'])
        if row['rgb_sha256'] is not None:join('i:'+name,'r:'+row['rgb_sha256'])
    observed=set(parent);anchors={};unmatched={};byte_unmatched=set()
    for role,seeds in protected.items():
        require(set(seeds)==ANCHOR_TYPES,'complete_content_anchor_types_required')
        nodes=(['c:'+code8(v) for v in seeds['codes']]
               +['i:'+image_name(v) for v in seeds['images']]
               +['b:'+sha_value(v) for v in seeds['hashes']]
               +['r:'+sha_value(v) for v in seeds['rgb_hashes']])
        anchors[role]=nodes;unmatched[role]={node for node in nodes if node not in observed}
        byte_unmatched|={node for node in unmatched[role] if not node.startswith('r:')}
        for node in nodes:find(node)
    members=defaultdict(list)
    for node in sorted(parent):members[find(node)].append(node)
    names={root:'asa-content-'+hashlib.sha256(json.dumps(nodes,ensure_ascii=False,
           separators=(',',':')).encode()).hexdigest()
           for root,nodes in members.items()}
    mapping={node:names[find(node)] for node in parent}
    groups={role:{mapping[node] for node in nodes} for role,nodes in anchors.items()}
    unresolved={mapping['i:'+name] for name in unknown_bytes|unknown_pixels}
    unresolved|={mapping[node] for nodes in unmatched.values() for node in nodes}
    intersections={a+'__'+b:len(groups[a]&groups[b])
        for index,a in enumerate(sorted(ROLES)) for b in sorted(ROLES)[index+1:]}
    byte_complete=not unknown_bytes and not byte_unmatched
    pixel_complete=byte_complete and not unknown_pixels and not any(unmatched.values())
    private={'node_groups':mapping,'members':{names[root]:nodes for root,nodes in members.items()},
        'protected_groups':groups,'fingerprints':fingerprints,'unknown_byte_images':unknown_bytes,
        'unknown_pixel_images':unknown_pixels,'unresolved_groups':unresolved}
    aggregate={'supplied_association_rows':len(pairs),'supplied_metadata_images':len(metadata),
        'supplied_image_universe':len(universe),'actual_byte_image_names':len(fingerprints),
        'actual_pixel_image_names':len(known_pixels),'unknown_byte_image_count':len(unknown_bytes),
        'unknown_pixel_image_count':len(unknown_pixels),'unresolved_component_count':len(unresolved),
        'unmatched_protected_anchor_counts':{r:len(v) for r,v in unmatched.items()},
        'observed_protected_intersections':intersections,'supplied_byte_closure_complete':byte_complete,
        'supplied_pixel_closure_complete':pixel_complete,'external_source_completeness_proven':False,
        'algorithm':ALGORITHM,'status':'supplied_content_graph_complete' if pixel_complete else
        'incomplete_content_identity_coverage','new_samples_selected':0,'api_calls':0}
    return private,aggregate
