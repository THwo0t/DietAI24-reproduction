"""Detached full development run followed by offline verification and comparison."""
from pathlib import Path
import json
import subprocess
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

def main():
    codes = {}
    actions = [('run', ['run.py','--run','--allow-paid','--workers','32']),
               ('verify', ['verify_completed.py']), ('compare', ['compare_baseline.py'])]
    for name, arguments in actions:
        command = [sys.executable, '-B', str(HERE / arguments[0]), *arguments[1:]]
        codes[name] = subprocess.run(command, cwd=REPO).returncode
        if codes[name]:
            break
    if codes.get('compare') == 0:
        sys.path.insert(0,str(HERE))
        from compare_baseline import model_usage
        usage = dict(models=model_usage(HERE), includes_archived_preformat_two_calls=True,
                     third_party_cost_usd=None, price_verified=False)
        (HERE/'task_usage.json').write_text(json.dumps(usage,indent=2)+'\n')
    result = dict(status='completed' if codes.get('compare') == 0 else 'stopped',
                  exit_codes=codes, finished_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    (HERE/'batch_outcome.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return 0 if result['status']=='completed' else 1

if __name__ == '__main__':
    sys.exit(main())
