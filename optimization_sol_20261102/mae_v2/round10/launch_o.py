#!/usr/bin/env python3
"""Launch the reviewed frozen O batch and offline follower once, detached."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode=True
ROUND=Path(__file__).resolve().parent;BASE=ROUND.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(ROUND)]
from context_o import runtime_context,require
from opt_provider import sha


def write_once(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        stream.write(json.dumps(value,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())


def launch():
    runtime_context()
    directory=ROUND/'launch';directory.mkdir(mode=0o700,exist_ok=True)
    receipt=directory/'O_launch.json'
    require(not receipt.exists() and not (ROUND/'runs/development/completion.json').exists(),
            'O_existing_launch_must_be_inspected_not_duplicated')
    lock=os.open(directory/'coordinator.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # Reserve the immutable launch before either process is created.
    write_once(receipt,{'status':'launch_reserved','freeze_sha256':sha(ROUND/'prepared/freeze.json')})
    logfd=os.open(directory/'O.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(logfd,'w') as log:
        base=subprocess.Popen(['flock','--no-fork',str(directory/'run.lock'),sys.executable,'-B',
            str(ROUND/'run_o.py'),'run','--allow-paid'],stdout=log,stderr=subprocess.STDOUT,
            start_new_session=True)
    write_once(directory/'O_process.json',{'pid':base.pid,'freeze_sha256':sha(ROUND/'prepared/freeze.json'),
                'source_checkpoint':subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE).decode().strip()})
    followfd=os.open(directory/'follower.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(followfd,'w') as log:
        follower=subprocess.Popen([sys.executable,'-B',str(ROUND/'watch_o.py'),'--base-pid',str(base.pid)],
            stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    write_once(directory/'automatic_followup_launch.json',{'pid':follower.pid,'base_pid':base.pid,
                'new_paid_requests':0,'validation_opened':False})
    os.close(lock)
    return {'status':'O_launched_once','base_pid':base.pid,'offline_follower_pid':follower.pid}


if __name__=='__main__':
    try:print(json.dumps(launch()))
    except Exception as exc:
        print(json.dumps({'status':'O_launch_refused','error_type':type(exc).__name__}))
        raise SystemExit(1)
