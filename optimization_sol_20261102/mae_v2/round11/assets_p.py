"""P-only extended ASA legal catalog plus unchanged generic vector assets.

No corpus/query embeddings, labels, API, preparation or writes. Only asa_options
may grow relative to the old catalog; all old content remains byte-value equal and old option lists stay exact prefixes.
The preparer must register ALL safe eligible broader codes before group sampling.
"""
from copy import deepcopy
import os
from pathlib import Path
import re
import stat

import numpy as np
from opt_provider import ROOT,EMBED_MODEL,fingerprint
from opt_pipeline import Retriever,validate_options
from round4.src.artifacts import decode

BASE_CATALOG='data/catalog.json'
P_CATALOG='round11/prepared/catalog.json'
VECTOR_MANIFEST='data/vectors/manifest.json'
VECTOR_PATH='data/vectors/embeddings.npy'
VECTORS=5624
DIMENSIONS=3072


def require(ok,code):
    if not ok:raise ValueError('P_assets_'+code)


def _hash(v):return type(v) is str and re.fullmatch('[0-9a-f]{64}',v) is not None


def catalog_extension(base,new):
    """Validate generic catalog immutability and additive code-level options."""
    require(type(base) is dict and type(new) is dict and set(base)==set(new) and
            'foods' in base and 'asa_options' in base,'catalog_topkeys_changed')
    require(all(fingerprint(new[k])==fingerprint(base[k]) for k in base if k!='asa_options'),'generic_catalog_changed')
    require(type(base['foods']) is dict and base['foods'] and type(base['asa_options']) is dict and
            type(new['asa_options']) is dict and set(base['asa_options'])<=set(new['asa_options']),
            'old_ASA_option_codes_missing')
    for code,options in new['asa_options'].items():
        require(type(code) is str and re.fullmatch('[0-9]{8}',code) and code in base['foods'],
                'ASA_option_code_outside_fixed_foodbank')
        checked=validate_options(options)
        require(checked==options,'canonical_ASA_options_required')
        if code in base['asa_options']:
            old=base['asa_options'][code]
            require(len(options)>=len(old) and fingerprint(options[:len(old)])==fingerprint(old),
                    'old_ASA_option_prefix_changed')
            pairs=[(o['description'],o['grams']) for o in options]
            oldpairs={(o['description'],o['grams']) for o in old}
            added=pairs[len(old):]
            require(len(set(added))==len(added) and not set(added)&oldpairs,'duplicate_appended_ASA_option_pair')
        else:
            pairs=[(o['description'],o['grams']) for o in options]
            require(len(set(pairs))==len(pairs),'duplicate_new_ASA_option_pair')
    return deepcopy(new)


def asset_paths(description,*,vectors=VECTORS,dimensions=DIMENSIONS):
    require(type(description) is dict and set(description)=={'vectors','dimensions','api_calls','embedding_model','files'} and
            type(description['vectors']) is int and description['vectors']==vectors and
            type(description['dimensions']) is int and description['dimensions']==dimensions and
            type(description['api_calls']) is int and description['api_calls']==0 and
            description['embedding_model']==EMBED_MODEL,'official_vector_manifest_changed')
    files=description['files']
    require(type(files) is dict and {'embeddings.npy','codes.json'}<=set(files) and 2<=len(files)<=16 and
            all(type(name) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',name) and
                name not in ('.','..','manifest.json') and '..' not in name and
                name.endswith(('.json','.npy')) and _hash(h) for name,h in files.items()),
            'fixed_vector_file_inventory_changed')
    return {BASE_CATALOG,P_CATALOG,VECTOR_MANIFEST}|{'data/vectors/'+name for name in files}


def _matrix(root,expected_shape):
    # Load the fixed NPY through a held no-follow descriptor; never materialize
    # a large raw byte string through context_p._read's JSON/body interface.
    from context_p import VECTOR_DIGEST_MAX_BYTES
    root=Path(root);require(root.resolve()==root and not root.is_symlink(),'unsafe_root')
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in ('data','vectors'):
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        vectorfd=os.open('embeddings.npy',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            before=os.fstat(vectorfd)
            require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=VECTOR_DIGEST_MAX_BYTES,'bounded_vector_file_required')
            with os.fdopen(vectorfd,'rb',closefd=False) as stream:
                magic=np.lib.format.read_magic(stream)
                require(magic in ((1,0),(2,0)),'supported_npy_header_required')
                header=(np.lib.format.read_array_header_1_0(stream) if magic==(1,0) else
                        np.lib.format.read_array_header_2_0(stream))
                shape,fortran,dtype=header
                require(shape==expected_shape and dtype==np.dtype('float32') and fortran is False,
                        'vector_shape_dtype_or_order_changed')
                require(stream.tell()+int(np.prod(shape))*dtype.itemsize==before.st_size,'exact_npy_payload_size_required')
                stream.seek(0)
                matrix=np.load(stream,allow_pickle=False)
                require(stream.tell()==before.st_size,'vector_trailing_bytes_changed')
            after=os.fstat(vectorfd)
            require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'vector_changed_during_load')
        finally:os.close(vectorfd)
    finally:os.close(fd)
    require(type(matrix) is np.ndarray and matrix.shape==expected_shape and matrix.dtype==np.dtype('float32') and
            np.isfinite(matrix).all(),'vector_shape_dtype_or_finiteness_changed')
    return matrix


def _assets(root,*,vectors=VECTORS,dimensions=DIMENSIONS):
    from context_p import _read
    root=Path(root)
    description=decode(_read(root,VECTOR_MANIFEST));paths=asset_paths(description,vectors=vectors,dimensions=dimensions)
    # Record every asset digest on both sides of loading; descriptor per-file
    # hashes independently bind code order, vector bytes and auxiliary assets.
    hashes={path:_read(root,path,digest_only=True) for path in paths}
    for name,expected in description['files'].items():
        require(hashes['data/vectors/'+name]==expected,'vector_source_hash_changed')
    catalog=catalog_extension(decode(_read(root,BASE_CATALOG)),decode(_read(root,P_CATALOG)))
    codes=decode(_read(root,'data/vectors/codes.json'))
    require(type(codes) is list and len(codes)==vectors and
            all(type(c) is str and re.fullmatch('[0-9]{8}',c) for c in codes) and len(set(codes))==len(codes) and
            set(codes)==set(catalog['foods']),'complete_unique_vector_code_join_required')
    matrix=_matrix(root,(vectors,dimensions))
    retriever=Retriever(codes,matrix,catalog);retriever.vectors.setflags(write=False)
    require(all(_read(root,path,digest_only=True)==expected for path,expected in hashes.items()),'asset_changed_during_load')
    return catalog,retriever


def assets(root=ROOT):return _assets(root)
