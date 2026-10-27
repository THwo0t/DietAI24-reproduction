"""Export an explicit public tree without old Git history or raw request/process logs."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'.publication/DietAI24-reproduction'

def included(name):
    if name.startswith('logs/'):return False
    if name.startswith('runs/'):
        if not name.startswith(('runs/test/','runs/test-gpt-6.1-sol/','runs/comparison-gpt-4o-vs-sol/')):return False
        if name.endswith(('.log','.jsonl','.out')):return False
        if name.endswith('_checkpoint.txt'):return False
    return True

def main():
    if DEST.exists():raise SystemExit('Export destination already exists; preserve or rename it first.')
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    selected=[name for name in names if name and included(name)]
    manifest={}
    for name in selected:
        source=ROOT/name
        if source.is_symlink():raise ValueError('No symlinks in the public tree')
        target=DEST/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
        manifest[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    (DEST/'PUBLICATION_MANIFEST.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'scope':'Current source, documentation, reports, selected archived measurements and four public image previews. No previous Git objects or raw API/process logs.',
        'files':manifest},indent=2)+'\n')
    print(json.dumps({'export':str(DEST),'files':len(selected),'bytes':sum((DEST/name).stat().st_size for name in selected),
                      'old_git_history':False,'raw_logs':False},indent=2))

if __name__=='__main__':main()
