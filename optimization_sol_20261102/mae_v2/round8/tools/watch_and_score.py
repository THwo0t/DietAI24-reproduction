#!/usr/bin/env python3
"""Wait for the existing N coordinator, then run frozen offline verify/score.

Never starts paid inference, resets counters, changes scientific source, opens
labels before the full completion seal, or publishes anything. Own lock prevents
duplicate followers. Phase logs and status remain private.
"""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[4]
ROUND = ROOT / "optimization_sol_20261102/mae_v2/round8"
LAUNCH = ROUND / "launch"


def status(value):
    temporary = LAUNCH / "automatic_followup.json.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, LAUNCH / "automatic_followup.json")


def own_process(pid, entry):
    proc = Path("/proc") / str(pid)
    try:
        return (proc / "stat").read_text().split()[2] != "Z" and str(entry).encode() in (proc / "cmdline").read_bytes().split(b"\0")
    except (FileNotFoundError, ProcessLookupError):
        return False


def main():
    os.umask(0o077)
    entry = ROUND / "src/run_n.py"
    lock = os.open(LAUNCH / "automatic_followup.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise SystemExit("An automatic follower already owns this run")
    receipt = json.loads((LAUNCH / "N_launch.json").read_text())
    pid = receipt["pid"]
    while own_process(pid, entry):
        status({"status": "waiting_for_existing_base", "base_pid": pid, "new_paid_requests": 0})
        time.sleep(30)
    if not (ROUND / "runs/development/completion.json").is_file():
        status({"status": "stopped_base_incomplete", "new_paid_requests": 0,
                "action": "Preserve existing state and inspect service/source evidence; no automatic inference restart."})
        return 1
    for phase in ["verify", "score"]:
        status({"status": "offline_" + phase, "new_paid_requests": 0})
        fd = os.open(LAUNCH / ("automatic_" + phase + ".log"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            result = subprocess.run(["unshare", "-rn", str(ROOT / ".venv/bin/python"), "-B", str(entry), phase],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
        if result.returncode:
            status({"status": "stopped_" + phase, "returncode": result.returncode, "new_paid_requests": 0})
            return 1
    checkpoint = json.loads((ROUND / "development_checkpoint.json").read_text())
    status({"status": "development_scored", "selection": checkpoint["selection"],
        "failed_checks": {name: arm["tolerance"]["failed_checks"] for name, arm in checkpoint["arms"].items()},
        "new_paid_requests": 0, "validation_accessed": False,
        "next": "Review the complete two-dataset result and project trajectory before the next method or independent validation."})
    return 0


if __name__ == "__main__": raise SystemExit(main())
