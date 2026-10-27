"""Portable runtime data and saved embeddings; no model requests or Linux HNSW copies."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'.demo/assets'
INDEX=ROOT/'.demo/index/chroma'
SPEC=ROOT/'demo/runtime-release.json'
FOODS='FNDDS/2019-2020 FNDDS - Foods and Beverages.csv'
NUTRIENTS='FNDDS/2019-2020 FNDDS At A Glance - FNDDS Nutrient Values.xlsx'


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()


def load(path):return json.loads(Path(path).read_text())


def safe_members(archive):
    names=archive.namelist()
    if len(names)!=len(set(names)):raise ValueError('Duplicate archive entries')
    for member in archive.infolist():
        name=member.filename;parts=PurePosixPath(name)
        if '\\' in name or parts.is_absolute() or '..' in parts.parts or name.endswith('/'):
            raise ValueError('Unsafe archive path')
        if stat.S_ISLNK(member.external_attr>>16):raise ValueError('Archive symlink')
    if len(names)>100 or sum(x.file_size for x in archive.infolist())>300*1024*1024:
        raise ValueError('Runtime archive exceeds expected bounds')
    manifest=json.loads(archive.read('manifest.json'))
    if set(names)!=set(manifest['files'])|{'manifest.json'}:raise ValueError('Manifest membership mismatch')
    if not all(repr(v) and len(v)==64 and all(c in '0123456789abcdef' for c in v)
               for v in manifest['files'].values()):raise ValueError('Invalid checksums')
    return manifest


def build():
    import chromadb
    import numpy as np
    names=[FOODS,NUTRIENTS,'FoodWeights.csv','df_image_link.csv','df_results_dev.csv','dish_metadata_dev.csv']
    for table in ['df_results_dev.csv','dish_metadata_dev.csv']:
        with (ROOT/table).open(newline='') as f:
            for row in csv.DictReader(f):
                image=(ROOT/'code'/row['Link']).resolve()
                names.append(str(image.relative_to(ROOT)))
    names=list(dict.fromkeys(names))
    out=ROOT/'dist/mac-demo-runtime-v1.zip';out.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        stage=Path(temp)
        client=chromadb.PersistentClient(path=str(ROOT/'index/chroma'),settings=chromadb.Settings(anonymized_telemetry=False))
        collection=client.get_collection('openai_embed')
        saved=collection.get(include=['embeddings','documents','metadatas'])
        order=sorted(range(len(saved['ids'])),key=lambda n:int(saved['ids'][n]))
        original=np.asarray([saved['embeddings'][n] for n in order])
        vectors=original.astype('float32')
        if not np.array_equal(original,vectors.astype(original.dtype)):
            raise ValueError('Float32 conversion would change saved embeddings')
        assert vectors.shape==(5624,3072)
        np.save(stage/'embeddings.npy',vectors,allow_pickle=False)
        descriptor={'name':'openai_embed','count':5624,'dimension':3072,
                    'embedding_model':'text-embedding-3-large','foods_sha256':digest(ROOT/FOODS),
                    **{k:[saved[k][n] for n in order] for k in ['ids','documents','metadatas']}}
        (stage/'collection.json').write_text(json.dumps(descriptor))
        files={name:ROOT/name for name in names}
        files.update({name:stage/name for name in ['embeddings.npy','collection.json']})
        manifest={'format':1,'purpose':'Small development demo; not a repeat of either formal test.',
                  'files':{name:digest(path) for name,path in files.items()}}
        manifest_bytes=(json.dumps(manifest,indent=2)+'\n').encode()
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            archive.writestr('manifest.json',manifest_bytes)
            for name,path in files.items():archive.write(path,name)
    spec={'release_tag':'mac-demo-v1','url':'https://github.com/THwo0t/DietAI24-reproduction/releases/download/mac-demo-v1/'+out.name,
          'sha256':digest(out),'manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest(),
          'size_bytes':out.stat().st_size,'files':len(files),
          'embedding_model':'text-embedding-3-large','vectors':5624,'dimensions':3072}
    SPEC.write_text(json.dumps(spec,indent=2)+'\n')
    print(json.dumps(spec,indent=2))


def verify_assets():
    if digest(ASSETS/'manifest.json')!=load(SPEC)['manifest_sha256']:
        raise ValueError('Installed runtime manifest differs from pinned release')
    manifest=load(ASSETS/'manifest.json')
    for name,expected in manifest['files'].items():
        if digest(ASSETS/name)!=expected:raise ValueError('Runtime file mismatch: '+name)
    descriptor=load(ASSETS/'collection.json')
    if descriptor['foods_sha256']!=digest(ASSETS/FOODS):raise ValueError('Foods/index source mismatch')
    return manifest,descriptor


def restore_index():
    import chromadb
    import numpy as np
    _,descriptor=verify_assets()
    matrix=np.load(ASSETS/'embeddings.npy',allow_pickle=False)
    if matrix.shape!=(descriptor['count'],descriptor['dimension']):raise ValueError('Embedding shape mismatch')
    if not np.isfinite(matrix).all():raise ValueError('Non-finite embedding')
    client=chromadb.PersistentClient(path=str(INDEX),settings=chromadb.Settings(anonymized_telemetry=False))
    collection=client.get_or_create_collection('openai_embed')
    marker=INDEX.parent/'source.json'
    expected={'bundle_sha256':load(SPEC)['sha256'],'vectors':descriptor['count']}
    if marker.exists() and load(marker)==expected and collection.count()==descriptor['count']:
        return collection
    existing=set(collection.get(include=[])['ids'])
    if existing-set(descriptor['ids']):raise ValueError('Unexpected entries in demo index; use a fresh .demo/index')
    for offset in range(0,descriptor['count'],256):
        ix=[i for i in range(offset,min(offset+256,descriptor['count'])) if descriptor['ids'][i] not in existing]
        if not ix:continue
        collection.add(ids=[descriptor['ids'][i] for i in ix],embeddings=matrix[ix].tolist(),
                       documents=[descriptor['documents'][i] for i in ix],metadatas=[descriptor['metadatas'][i] for i in ix])
    if collection.count()!=descriptor['count']:raise ValueError('Incomplete restored collection')
    marker.write_text(json.dumps(expected,indent=2)+'\n')
    return collection


def install(archive_path=None):
    spec=load(SPEC)
    if ASSETS.exists():
        verify_assets()
    else:
        cache=ROOT/'.demo/downloads';cache.mkdir(parents=True,exist_ok=True)
        archive_path=Path(archive_path) if archive_path else cache/'mac-demo-runtime-v1.zip'
        if not archive_path.exists():
            partial=cache/'runtime.zip.part'
            with urllib.request.urlopen(spec['url'],timeout=60) as source,partial.open('wb') as dest:
                total=0
                for chunk in iter(lambda:source.read(1<<20),b''):
                    total+=len(chunk)
                    if total>spec['size_bytes']:raise ValueError('Download exceeds pinned release size')
                    dest.write(chunk)
            if digest(partial)!=spec['sha256']:raise ValueError('Release checksum mismatch')
            partial.rename(archive_path)
        if digest(archive_path)!=spec['sha256']:raise ValueError('Release checksum mismatch')
        with tempfile.TemporaryDirectory(dir=ROOT/'.demo') as temp:
            stage=Path(temp)
            with zipfile.ZipFile(archive_path) as archive:
                manifest=safe_members(archive)
                for name,expected in manifest['files'].items():
                    target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(name) as source,target.open('wb') as dest:shutil.copyfileobj(source,dest)
                    if digest(target)!=expected:raise ValueError('Extracted file checksum mismatch: '+name)
                (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            stage.rename(ASSETS)
    collection=restore_index()
    print(json.dumps({'status':'PASS','runtime_files':spec['files'],'vectors':collection.count(),
                      'embedding_api_calls':0,'index':'Native Chroma index rebuilt from saved float32 embeddings'}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['build','install','verify'])
    parser.add_argument('--archive',type=Path,help='Use a previously downloaded release file')
    args=parser.parse_args()
    if args.command=='build':build()
    elif args.command=='install':install(args.archive)
    else:
        _,d=verify_assets();c=restore_index()
        print(json.dumps({'status':'PASS','vectors':c.count(),'dimensions':d['dimension'],'api_calls':0}))

if __name__=='__main__':main()
