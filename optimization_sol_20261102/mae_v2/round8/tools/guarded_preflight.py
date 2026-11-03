#!/usr/bin/env python3
"""Read-only upstream preparation proof with forbidden reference/service guards."""
import argparse
import builtins
from contextlib import ExitStack
import io
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path[:0] = [str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src')]
import context_n
import opt_provider
import runtime_n
import runtime_m


def main():
    p = argparse.ArgumentParser(); p.add_argument('--prepare',action='store_true')
    p.add_argument('--post-freeze',action='store_true'); args = p.parse_args()
    original = (builtins.open,io.open,Path.open)
    counts = {'forbidden_reads':0,'image_opens':0}
    def check(file,mode):
        if isinstance(file,(str,Path)):
            path = Path(file).absolute()
            if (path.suffix != '.py' and any(word in str(path) for word in
                    ('dev_labels','validation','.env','credentials'))):
                counts['forbidden_reads'] += 1; raise AssertionError('N_forbidden_reference_or_key_open')
            if any(flag in mode for flag in 'wax+') and not path.is_relative_to(context_n.ROUND/'prepared'):
                raise AssertionError('N_unexpected_python_write')
            if path.suffix.lower() in ('.png','.jpg','.jpeg'): counts['image_opens'] += 1
    def bopen(file,mode='r',*a,**kw): check(file,mode); return original[0](file,mode,*a,**kw)
    def iopen(file,mode='r',*a,**kw): check(file,mode); return original[1](file,mode,*a,**kw)
    def popen(file,mode='r',*a,**kw): check(file,mode); return original[2](file,mode,*a,**kw)
    def deny(*a,**kw): raise AssertionError('N_network_Provider_or_credentials_forbidden')
    def snapshot():
        result = {}
        for name in ('prepared','runs','provider','diagnostics'):
            for path in (BASE/'round7'/name).rglob('*'):
                if path.is_file(): result[str(path)] = (path.stat().st_size,path.stat().st_mtime_ns)
        return result
    before = snapshot()
    with ExitStack() as stack:
        for obj,name,value in [(builtins,'open',bopen),(io,'open',iopen),(Path,'open',popen),
            (socket.socket,'connect',deny),(socket,'create_connection',deny),
            (opt_provider,'read_credentials',deny),(opt_provider.Provider,'__init__',deny),
            (runtime_n,'NProvider',deny),(runtime_m,'MProvider',deny)]: stack.enter_context(patch.object(obj,name,value))
        prepared = context_n.prepare() if args.prepare else None
        ctx = context_n.runtime_context(pre_review=not args.post_freeze)
        ctx.verify_sources()
    after = snapshot()
    if before != after: raise AssertionError('N_old_M_files_changed')
    result = {'status':'guarded_N_preflight_passed','rows':len(ctx.rows),'imported_pairs':len(ctx.imported['records']),
        'old_M_files_preserved':len(before),'counts':counts,'provider_and_network_forbidden':True,
        'api_calls':0,'pre_review':not args.post_freeze,'preparation':prepared}
    print(json.dumps(result),flush=True)

if __name__=='__main__': main()
