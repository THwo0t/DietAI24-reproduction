"""Scan reachable Git history and publishable working files; never print a matched value."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PATTERNS=[re.compile(p) for p in [
    rb'(?<![A-Za-z0-9_-])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}',
    rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}',
    rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    rb'AKIA[A-Z0-9]{16}']]

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-worktree',action='store_true')
    args=parser.parse_args()
    # Actual local key values are an additional exact-match check, not printed or saved.
    from dotenv import dotenv_values
    values=dotenv_values(ROOT/'.env',interpolate=False) if (ROOT/'.env').exists() else {}
    keys=[value.encode() for name,value in values.items() if 'KEY' in name.upper() and value and len(value)>12]
    def matches(data):return any(p.search(data) for p in PATTERNS) or any(key in data for key in keys)
    issues=[];blobs=0
    objects=git('rev-list','--objects','--all').splitlines()
    process=subprocess.Popen(['git','cat-file','--batch'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    for item in objects:
        oid=item.split(b' ',1)[0]
        process.stdin.write(oid+b'\n');process.stdin.flush()
        head=process.stdout.readline().split();size=int(head[2])
        data=process.stdout.read(size);process.stdout.read(1)
        if head[1]==b'blob':
            blobs+=1
            if matches(data):issues.append({'object':oid.decode(),'reason':'credential-shaped or exact local-key match'})
    process.stdin.close();process.stdout.close();process.wait()
    names=git('ls-files','-z').split(b'\0')
    if args.include_worktree:names+=git('ls-files','--others','--exclude-standard','-z').split(b'\0')
    files=0
    for name in set(names)-{b''}:
        path=ROOT/name.decode()
        if path.is_symlink():issues.append({'path':name.decode(),'reason':'review symlink before publishing'});continue
        if not path.is_file():continue
        files+=1
        if name.decode()=='.env' or any(part.startswith('.venv') for part in Path(name.decode()).parts):
            issues.append({'path':name.decode(),'reason':'private/runtime file in publication set'})
        if matches(path.read_bytes()):issues.append({'path':name.decode(),'reason':'credential-shaped or exact local-key match'})
    print(json.dumps({'status':'PASS' if not issues else 'STOP','reachable_blobs_scanned':blobs,
                      'publishable_files_scanned':files,'issues':issues},indent=2))
    if issues:raise SystemExit(1)

if __name__=='__main__':main()
