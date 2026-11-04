"""Detached fixed 32-process continuation, followed by isolated old postscore."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p_parallel_registration as registration
from opt_provider import ROOT, fingerprint, sha

LAUNCH = HERE/'launch'


def emit(**value):
    print(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      **value}, sort_keys=True), flush=True)


def execute():
    from p_parallel_transition import write_once
    engineering = registration.runtime_engineering()
    write_once(LAUNCH/'started.json', {'pid':os.getpid(),
        'engineering_sha256':fingerprint(engineering),
        'science_freeze_sha256':engineering['science_freeze_sha256'], 'workers':32})
    emit(status='P_parallel_continuation_started', workers=32)
    from p_parallel_controller import run
    result = run(allow_paid=True, workers=32)
    emit(status='P_parallel_inference_complete', result=result)
    from adapter_p import CLEAN_ENV
    emit(status='P_postscore_zero_provider_verification_started')
    output = LAUNCH/'postscore.log'
    fd = os.open(output, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        child = subprocess.run(['/usr/bin/unshare','-Urn',sys.executable,'-B',
                str(ROOT/'round11/postscore_p.py')], cwd=ROOT, env=dict(CLEAN_ENV),
                stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, check=False)
    if child.returncode != 0:
        raise ValueError('P_parallel_isolated_postscore_failed')
    summary = json.loads(output.read_text().splitlines()[-1])
    if (type(summary) is not dict or set(summary) != {'status','rows','selected_profile',
            'private_result_sha256','api_calls','validation_opened'} or
            summary.get('status') != 'P_development_postscore_complete' or
            summary.get('rows') != 843 or summary.get('api_calls') != 0 or
            summary.get('validation_opened') is not False or
            summary.get('selected_profile') not in (None,'O','Q','D','Q+D') or
            not registration._digest(summary.get('private_result_sha256'))):
        raise ValueError('P_parallel_postscore_summary_changed')
    write_once(LAUNCH/'terminal.json', summary)
    emit(status='P_parallel_scoring_complete', result=summary)


if __name__ == '__main__':
    try:
        execute()
    except BaseException as error:
        # Never include exception messages: provider/transport exceptions can
        # carry user content or credentials. Keep enough source location to fix.
        failure = {'status':'P_parallel_stopped_preserve_state',
            'error_type':type(error).__name__, 'frames':[
                {'module':Path(frame.filename).name, 'line':frame.lineno}
                for frame in traceback.extract_tb(error.__traceback__)[-8:]]}
        emit(**failure)
        try:
            from p_parallel_transition import write_once
            if not (LAUNCH/'terminal.json').exists():
                write_once(LAUNCH/'terminal.json', failure)
        except BaseException:
            emit(status='P_parallel_terminal_receipt_write_failed')
        raise SystemExit(1) from None
