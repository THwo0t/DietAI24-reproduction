#!/usr/bin/env python3
"""Run once only after the scored batch, in an external-network-free namespace."""
import builtins
import io
import json
import os
from pathlib import Path
import socket
import sys

sys.dont_write_bytecode=True
import diagnose_o as d
import httpx,opt_provider,runtime_o


def kernel_loopback_only(raw):
    """Parse the calling process's proc network view, not shared sysfs."""
    try:
        lines=raw.decode('ascii').strip().splitlines()
    except (AttributeError,UnicodeDecodeError):
        return False
    if len(lines)!=3 or [s.strip() for s in lines[0].split('|')]!=['Inter-','Receive','Transmit']:
        return False
    header=[s.split() for s in lines[1].split('|')]
    if header!=[['face'],['bytes','packets','errs','drop','fifo','frame','compressed','multicast'],
                ['bytes','packets','errs','drop','fifo','colls','carrier','compressed']]:
        return False
    name,separator,counters=lines[2].rpartition(':')
    values=counters.split()
    return bool(separator) and name.strip()=='lo' and len(values)==16 and all(v.isdecimal() for v in values)


def allowed_path(path,write,*,allowed_files,read_trees,write_tree,receipt,label_path,labels_allowed):
    p=Path(path).absolute().resolve()
    inside=lambda parent:p==parent or parent in p.parents
    if (p.name=='.env' or 'validation' in p.parts or p.name.startswith(('val_','validation_'))
            or p.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.bmp','.gif','.tif','.tiff','.heic','.avif','.ppm')
            or p==label_path and not labels_allowed):
        return False
    if write:return inside(write_tree) or p==receipt
    # Closed globally, including files outside the experiment root.
    return p in allowed_files or any(inside(tree) for tree in read_trees)


def main():
    d.prerequisites(d.ROUND)
    # /sys may retain the parent mount's network view after unshare -n.
    # /proc/self/net/dev is resolved in this process's network namespace.
    d.require(kernel_loopback_only(Path('/proc/self/net/dev').read_bytes()),'O_network_namespace_required')
    d.require(not (d.ROUND/'evidence/postscore_guard.json').exists(),'O_guard_receipt_exists')
    frozen=json.loads((d.ROUND/'prepared/freeze.json').read_text())
    allowed_files={d.ROOT/p for p in frozen['source_files']}
    allowed_files|={d.ROOT/'data/catalog.json',d.ROOT/'data/cohorts/dev_labels.json',
                    d.ROUND/'prepared/freeze.json',d.ROUND/'REVIEW.md',d.ROUND/'development_checkpoint.json',
                    d.ROUND/'launch/automatic_followup.json',Path(d.__file__),Path(__file__),
                    d.ROOT/'round7/tools/diagnose_completed_m.py'}
    read_trees=[d.ROUND/'runs',d.ROUND/'diagnostics/completed_o']
    write_tree=d.ROUND/'diagnostics/completed_o';receipt=d.ROUND/'evidence/postscore_guard.json'
    protected=[]
    for folder in ('round7','round8','round9','round10'):
        for sub in ('prepared','runs','provider'):
            base=d.ROOT/folder/sub
            if base.exists():protected.extend(p for p in base.rglob('*') if p.is_file())
    snapshot={p:(p.stat().st_size,p.stat().st_mtime_ns) for p in protected}
    counts={'labels':0,'forbidden':0,'provider_or_network':0};labels_allowed=False;approved_fds=set()
    original_path=Path.open;original_io=io.open;original_builtin=builtins.open;original_os=os.open
    def check(path,write):
        if isinstance(path,int):
            if path not in approved_fds:counts['forbidden']+=1;raise AssertionError('O_unknown_file_descriptor')
            return
        p=Path(path).absolute().resolve()
        if not allowed_path(p,write,allowed_files=allowed_files,read_trees=read_trees,
                            write_tree=write_tree,receipt=receipt,
                            label_path=d.ROOT/'data/cohorts/dev_labels.json',labels_allowed=labels_allowed):
            counts['forbidden']+=1;raise AssertionError('O_diagnostic_access_boundary')
        if p==d.ROOT/'data/cohorts/dev_labels.json':counts['labels']+=1
    def popen(path,mode='r',*args,**kwargs):
        check(path,any(c in mode for c in 'wax+'));return original_path(path,mode,*args,**kwargs)
    def iopen(path,mode='r',*args,**kwargs):
        check(path,any(c in mode for c in 'wax+'));return original_io(path,mode,*args,**kwargs)
    def bopen(path,mode='r',*args,**kwargs):
        check(path,any(c in mode for c in 'wax+'));return original_builtin(path,mode,*args,**kwargs)
    def oopen(path,flags,*args,**kwargs):
        check(path,bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)))
        fd=original_os(path,flags,*args,**kwargs);approved_fds.add(fd);return fd
    def forbidden(*args,**kwargs):
        counts['provider_or_network']+=1;raise AssertionError('O_diagnostic_provider_network_forbidden')
    def enable_labels():
        nonlocal labels_allowed
        labels_allowed=True
    Path.open=popen;io.open=iopen;builtins.open=bopen;os.open=oopen
    socket.socket=forbidden;socket.create_connection=forbidden;httpx.Client=forbidden
    opt_provider.Provider=forbidden;opt_provider.read_credentials=forbidden
    runtime_o.OProvider=forbidden;runtime_o.read_credentials=forbidden
    try:
        output=d.run(before_labels=enable_labels)
        d.require(all(p.is_file() and (p.stat().st_size,p.stat().st_mtime_ns)==value
                      for p,value in snapshot.items()),'O_diagnostic_prior_artifacts_mutated')
        d.require(counts['labels']>0 and counts['forbidden']==counts['provider_or_network']==0,
                  'O_diagnostic_guard_failed')
        value={'status':'O_postscore_diagnostic_guard_passed','protected_files':len(snapshot),
               'opens':counts,'external_network':False,'api_calls':0,'validation_opened':False,
               'diagnostic_source_sha256':d.sha(Path(d.__file__)),'guard_source_sha256':d.sha(Path(__file__))}
        with receipt.open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')
        print(json.dumps(value))
    finally:
        Path.open=original_path;io.open=original_io;builtins.open=original_builtin;os.open=original_os


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'O_postscore_guard_refused','error_type':type(exc).__name__}))
        raise SystemExit(1)
