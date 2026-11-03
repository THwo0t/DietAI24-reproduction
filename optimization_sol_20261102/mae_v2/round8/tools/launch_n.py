#!/usr/bin/env python3
"""One persistent N coordinator and offline follower; refuses an existing receipt."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime,timezone

PROJECT = Path(__file__).resolve().parents[4]
ROUND = PROJECT/'optimization_sol_20261102/mae_v2/round8'
LAUNCH = ROUND/'launch'


def write(path,value):
    temp = path.with_suffix('.tmp')
    fd = os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def main():
    os.umask(0o077); LAUNCH.mkdir(parents=True,exist_ok=True,mode=0o700)
    if (LAUNCH/'N_launch.json').exists() or (LAUNCH/'automatic_followup_launch.json').exists():
        raise SystemExit('Existing N launch receipt: inspect and preserve it; no duplicate coordinator')
    frozen = ROUND/'prepared/freeze.json'
    if not frozen.is_file(): raise SystemExit('N freeze missing')
    freeze_sha = hashlib.sha256(frozen.read_bytes()).hexdigest()
    env = dict(os.environ,OPENBLAS_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
    entry = ROUND/'src/run_n.py'
    command = ['flock','-n','-F',str(LAUNCH/'N_coordinator.lock'),str(PROJECT/'.venv/bin/python'),
               '-B',str(entry),'base','--allow-paid']
    with (LAUNCH/'N.log').open('xb') as log:
        base = subprocess.Popen(command,cwd=PROJECT,env=env,stdin=subprocess.DEVNULL,
            stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    receipt = {'pid':base.pid,'started_utc':datetime.now(timezone.utc).isoformat(),
        'freeze_sha256':freeze_sha,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,text=True).strip(),
        'entry':str(entry),'workers':2,'profiles':['N-density','N-units'],'pairs':183,
        'new_embedding_requests':0,'reset_existing_state':False}
    write(LAUNCH/'N_launch.json',receipt)
    with (LAUNCH/'automatic_followup.log').open('xb') as log:
        follower = subprocess.Popen([str(PROJECT/'.venv/bin/python'),'-B',str(ROUND/'tools/watch_and_score.py')],
            cwd=PROJECT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    write(LAUNCH/'automatic_followup_launch.json',{'pid':follower.pid,'base_pid':base.pid,
        'new_paid_requests':0,'phases':['network-disabled verify','network-disabled score']})
    print(json.dumps({'status':'N_persistent_launch_created','base_pid':base.pid,'follower_pid':follower.pid,
        'freeze_sha256':freeze_sha,'pairs':183,'new_embedding_requests':0}),flush=True)

if __name__=='__main__': main()
