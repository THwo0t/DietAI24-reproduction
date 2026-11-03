"""Verify declared public payloads against committed Git blobs, not local files."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

PREFIX='optimization_sol_20261102/mae_v2/'


def require(ok,code):
    if not ok:raise ValueError(code)


def validate(manifest,paths,read_blob):
    require(type(manifest) is dict and type(manifest.get('files')) is dict and manifest['files'],
            'public_manifest_payload_map_required')
    require(type(manifest.get('file_count')) is int and manifest['file_count']==len(manifest['files']),
            'public_manifest_count_mismatch')
    checked=0
    for relative,meta in manifest['files'].items():
        require(type(relative) is str and relative and '\\' not in relative and not relative.startswith('/')
            and all(p not in ('','.','..') for p in relative.split('/')),'public_manifest_noncanonical_path')
        path=PREFIX+relative
        require(path in paths,'public_manifest_payload_missing_from_git')
        require(type(meta) is dict and set(meta)=={'bytes','sha256'} and type(meta['bytes']) is int
            and meta['bytes']>=0 and type(meta['sha256']) is str
            and re.fullmatch('[0-9a-f]{64}',meta['sha256']) is not None,'public_manifest_bad_descriptor')
        raw=read_blob(path)
        require(type(raw) is bytes and len(raw)==meta['bytes'] and
            hashlib.sha256(raw).hexdigest()==meta['sha256'],'public_manifest_committed_blob_drift')
        checked+=1
    return {'status':'PASS','declared_payloads':checked,'committed_payloads_verified':checked,'missing_payloads':0}


def committed(repo):
    repo=Path(repo)
    require(repo.is_absolute() and repo.resolve()==repo,'public_manifest_canonical_repo_required')
    def git(*args):return subprocess.check_output(['git',*args],cwd=repo,stderr=subprocess.DEVNULL)
    revision=git('rev-parse','--verify','HEAD^{commit}').decode().strip()
    entries=git('ls-tree','-r','-z',revision).split(b'\0')
    paths=set()
    for entry in entries:
        if not entry:continue
        header,name=entry.split(b'\t',1)
        mode,kind,oid=header.split()
        if mode in (b'100644',b'100755') and kind==b'blob':paths.add(name.decode())
    manifest=json.loads(git('show',revision+':'+PREFIX+'BACKUP_MANIFEST.json'))
    result=validate(manifest,paths,lambda path:git('show',revision+':'+path))
    return {**result,'checkpoint':revision,'working_directory_bodies_used':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(committed(args.repo),sort_keys=True))


if __name__=='__main__':main()
