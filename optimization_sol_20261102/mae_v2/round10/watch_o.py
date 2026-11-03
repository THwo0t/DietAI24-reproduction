#!/usr/bin/env python3
"""Wait for the one existing O base, then isolated verify and score once."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode=True
ROUND=Path(__file__).resolve().parent;BASE=ROUND.parent
sys.path[:0]=[str(BASE/'src')]
from opt_provider import atomic_json


def alive(pid):
    try:
        value=Path(f'/proc/{pid}/stat').read_text()
        return value.rsplit(')',1)[1].split()[0]!='Z'
    except FileNotFoundError:return False


def follow(pid):
    status=ROUND/'launch/automatic_followup.json'
    if status.exists() and json.loads(status.read_text()).get('status')=='development_scored':
        raise ValueError('O_follower_already_completed')
    while not (ROUND/'runs/development/completion.json').is_file():
        atomic_json(status,{'status':'waiting_for_existing_base','base_pid':pid,
                            'new_paid_requests':0,'validation_opened':False})
        if not alive(pid):
            atomic_json(status,{'status':'base_stopped_incomplete','base_pid':pid,
                                'new_paid_requests':0,'validation_opened':False})
            return 1
        time.sleep(5)
    for phase in ('verify','score'):
        atomic_json(status,{'status':'offline_'+phase,'base_pid':pid,'new_paid_requests':0,
                            'validation_opened':False})
        logfile=ROUND/'launch'/('automatic_'+phase+'.log')
        if logfile.exists():raise ValueError('O_follower_phase_log_already_exists')
        fd=os.open(logfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:
            result=subprocess.run(['unshare','-Urn',sys.executable,'-B',str(ROUND/'run_o.py'),phase],
                                  stdout=stream,stderr=subprocess.STDOUT,check=False)
        if result.returncode!=0:
            atomic_json(status,{'status':'offline_'+phase+'_failed','base_pid':pid,
                                'new_paid_requests':0,'validation_opened':False})
            return result.returncode
    checkpoint=json.loads((ROUND/'development_checkpoint.json').read_text())
    atomic_json(status,{'status':'development_scored','selection':checkpoint['selection'],
        'failed_checks':{k:checkpoint[k]['tolerance']['failed_checks'] for k in ('raw','OOF_mass')},
        'new_paid_requests':0,'validation_opened':False,
        'next':'Review both full cohorts, back up failure, then continue the registered project.'})
    return 0


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-pid',type=int,required=True);args=p.parse_args()
    try:raise SystemExit(follow(args.base_pid))
    except Exception as exc:
        atomic_json(ROUND/'launch/automatic_followup.json',{'status':'follower_refused',
                    'error_type':type(exc).__name__,'new_paid_requests':0,'validation_opened':False})
        raise SystemExit(1)
