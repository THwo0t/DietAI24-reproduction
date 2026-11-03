#!/usr/bin/env python3
"""Run only in a network namespace; enforce local read/write boundaries too."""
import builtins
import io
import json
import os
from pathlib import Path
import socket
import sys
import sysconfig

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import run_diagnostic as diagnostic
from opt_provider import atomic_json
import opt_provider


class FileBoundary:
    def __init__(self, reads, runtime_roots, state):
        self.reads = {Path(p).resolve() for p in reads}
        self.runtime_roots = tuple(Path(p).resolve() for p in runtime_roots)
        self.state = state

    def check(self, path, mode='r'):
        if isinstance(path,int):
            return
        p = Path(path).absolute().resolve()
        writing = (bool(mode & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
                   if isinstance(mode,int) else any(c in mode for c in 'wax+'))
        outputs = tuple(HERE/n for n in ('diagnostics','evidence','launch'))
        output = any(p == root or root in p.parents for root in outputs)
        allowed = output if writing else (output or p in self.reads or
                    any(p == root or root in p.parents for root in self.runtime_roots))
        if not writing:
            if p.name == '.env' or p.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.bmp'):
                allowed = False
            if p == diagnostic.BASE/'data/cohorts/dev_labels.json':
                allowed &= self.state['label_gate_passed']
                self.state['development_label_opens'] += 1
        if not allowed:
            self.state['forbidden_opens'] += 1
            raise AssertionError('R9_forbidden_file_open_or_mutation')


def readable_inputs():
    old = diagnostic.BASE/'round8'
    frozen_path = old/'prepared/freeze.json'
    if diagnostic.sha(frozen_path) != diagnostic.N_FREEZE:
        raise AssertionError('R9_untrusted_input_inventory')
    frozen = diagnostic.decode(frozen_path.read_bytes())
    sources = [diagnostic.BASE/p for p in frozen['source_files']]
    sources += [diagnostic.BASE/'round7/prepared/freeze.json',
                diagnostic.BASE/'round7/tools/diagnose_completed_m.py']
    sources += [HERE/n for n in ('review_gate.json','REVIEW.md','PROTOCOL.md','prepared/freeze.json',
                                 'joint_lp.py','run_diagnostic.py','guarded_run.py')]
    own_freeze = diagnostic.decode((HERE/'prepared/freeze.json').read_bytes())
    sources += [Path(sys.executable).resolve(),
                HERE/'runtime/wheels'/own_freeze['runtime']['wheel_name']]
    sources += [old/n for n in ('prepared/freeze.json','REVIEW.md','development_checkpoint.json',
                  'runs/scoring/results.json','launch/automatic_followup.json','launch/automatic_verify.log')]
    sources += [diagnostic.BASE/n for n in ('data/cohorts/dev.jsonl','data/cohorts/dev_labels.json','data/catalog.json')]
    sources += [Path(n) for n in ('/proc/net/dev','/proc/net/route','/proc/net/ipv6_route')]
    for directory in (old/'runs/development',old/'provider/N'):
        sources += [p for p in directory.rglob('*') if p.is_file() or p.is_dir()]
    roots = [Path(sysconfig.get_path('stdlib'))]
    for module in (diagnostic.np,diagnostic.scipy):
        root = Path(module.__file__).resolve().parent
        roots += [root, root.parent/(root.name+'.libs')]
    return sources, roots


def mutation_wrapper(raw, check, arity=1):
    def invoke(*args,**kwargs):
        if any(v is not None for k,v in kwargs.items() if k.endswith('dir_fd')):
            raise AssertionError('R9_relative_mutation_forbidden')
        for path in args[:arity]:
            check(path,'w')
        return raw(*args,**kwargs)
    return invoke


def require_network_isolation(dev, route, ipv6_route):
    interfaces = {line.split(':',1)[0].strip() for line in dev.splitlines() if ':' in line}
    v4 = {line.split()[0] for line in route.splitlines()[1:] if line.strip()}
    v6 = {line.split()[-1] for line in ipv6_route.splitlines() if line.strip()}
    if interfaces != {'lo'} or not v4 <= {'lo'} or not v6 <= {'lo'}:
        raise AssertionError('R9_external_network_interface_or_route_present')
    return {'interfaces':['lo'], 'external_routes':0}


def network_evidence():
    proof = require_network_isolation(Path('/proc/net/dev').read_text(),
        Path('/proc/net/route').read_text(), Path('/proc/net/ipv6_route').read_text())
    proof['namespace'] = os.readlink('/proc/self/ns/net')
    return proof


def snapshot():
    return {str(p): (p.stat().st_size,p.stat().st_mtime_ns)
            for name in ('round7','round8') for sub in ('prepared','runs','provider','diagnostics','launch')
            for p in (diagnostic.BASE/name/sub).rglob('*') if p.is_file()}


def run():
    network = network_evidence() # Refuse before inputs, providers or labels.
    state = {'label_gate_passed':False, 'development_label_opens':0, 'forbidden_opens':0,
             'provider_constructed':False, 'api_calls':0, 'validation_opened':False,
             'images_opened':False}
    def forbidden(*args, **kwargs):
        raise AssertionError('R9_provider_or_network_forbidden')
    def label_gate():
        state['label_gate_passed'] = True
    raw_builtin, raw_io, raw_path, raw_os = builtins.open, io.open, Path.open, os.open
    raw_socket, raw_connection = socket.socket, socket.create_connection
    raw_provider, raw_credentials = opt_provider.Provider, opt_provider.read_credentials
    raw_gate = diagnostic.label_gate_passed
    before = snapshot()
    reads, roots = readable_inputs()
    boundary = FileBoundary(reads,roots,state)
    check = boundary.check
    def bopen(path,mode='r',*args,**kwargs):
        check(path,mode); return raw_builtin(path,mode,*args,**kwargs)
    def iopen(path,mode='r',*args,**kwargs):
        check(path,mode); return raw_io(path,mode,*args,**kwargs)
    def popen(path,mode='r',*args,**kwargs):
        check(path,mode); return raw_io(path,mode,*args,**kwargs)
    def oopen(path,flags,*args,**kwargs):
        if kwargs.get('dir_fd') is not None:
            raise AssertionError('R9_relative_open_forbidden')
        check(path,flags); return raw_os(path,flags,*args,**kwargs)
    raw_mutations = {name:getattr(os,name) for name in
        ('rename','replace','link','unlink','remove','rmdir','mkdir','chmod','utime','truncate','symlink')}
    for name,raw in raw_mutations.items():
        setattr(os,name,forbidden if name == 'symlink' else
                mutation_wrapper(raw,check,2 if name in ('rename','replace','link') else 1))
    builtins.open, io.open, Path.open, os.open = bopen, iopen, popen, oopen
    socket.socket, socket.create_connection = forbidden, forbidden
    opt_provider.Provider, opt_provider.read_credentials = forbidden, forbidden
    diagnostic.label_gate_passed = label_gate
    def execution_boundary():
        if not (builtins.open is bopen and io.open is iopen and Path.open is popen
                and os.open is oopen and socket.socket is forbidden
                and opt_provider.Provider is forbidden):
            raise AssertionError('R9_guards_not_installed')
        network_evidence()
    try:
        result = diagnostic.run(execution_boundary=execution_boundary)
        after = snapshot()
        if before != after:
            raise AssertionError('R9_changed_prior_experiment_files')
        def audit(value):
            if isinstance(value,dict):
                if set(value) & {'sample_id','truth','prediction','masses','raw_leaves','image_path'}:
                    raise AssertionError('R9_public_row_output_forbidden')
                for item in value.values(): audit(item)
            elif isinstance(value,list):
                for item in value: audit(item)
        audit(result)
        atomic_json(HERE/'evidence/guard.json', {**state,'status':'completed','network':network,
                    'prior_files_preserved':len(before),'old_sizes_and_mtimes_unchanged':True})
        # The sole public data output is an aggregate; witnesses stay private.
        # Export occurs outside the guarded write scope, after all invariants.
    finally:
        builtins.open, io.open, Path.open, os.open = raw_builtin, raw_io, raw_path, raw_os
        socket.socket, socket.create_connection = raw_socket, raw_connection
        opt_provider.Provider, opt_provider.read_credentials = raw_provider, raw_credentials
        diagnostic.label_gate_passed = raw_gate
        for name,raw in raw_mutations.items():
            setattr(os,name,raw)
    atomic_json(HERE/'joint_checkpoint.json',result)
    return state


if __name__ == '__main__':
    try:
        state = run()
        print(json.dumps({'status':'R9_guarded_diagnostic_completed',**state}))
    except Exception as exc:
        print(json.dumps({'status':'R9_guarded_diagnostic_refused','error_type':type(exc).__name__}))
        raise SystemExit(1)
