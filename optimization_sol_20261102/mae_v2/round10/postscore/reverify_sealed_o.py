#!/usr/bin/env python3
"""Read-only recovery of the already sealed O diagnostic; never recompute it."""
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE/'round11'))
from o_completion import (CompletedStore,Reader,O_FREEZE,fingerprint,
                         verify_completed_o,require)
from guarded_diagnose_o import kernel_loopback_only

LEGACY_SOURCE='6eb2802b313bf0f04859db1f9cc95d42e6e1f253dd4510ff33af6b01dc83f2bc'
HELPER_SHA='41ba7c857f8d00c673ae697ff926b49fcc7cdb5928d134b928cad4d0f9e58f16'
SCOPE='posthoc_O_development_accounting_diagnostic_not_selection_or_acceptance'
INPUTS={'data/catalog.json','data/cohorts/dev_labels.json',
    'round10/prepared/freeze.json','round10/prepared/common.json',
    'round10/runs/development/completion.json','round10/runs/scoring/completion.json',
    'round10/runs/verification.json','round10/development_checkpoint.json'}


def _same_number(a,b):
    return type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) \
        and math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9)


def _verify_at(base,evidence,*,expected_freeze=O_FREEZE,
               expected_source=LEGACY_SOURCE,expected_helper=HELPER_SHA):
    """Private synthetic-fixture hook. Production exposes no path/pin overrides."""
    reader=Reader(base);directory=reader.base/'round10'
    require(evidence.freeze_sha256==expected_freeze and evidence.records==183
            and evidence.grants_new_phase_action is False,'recovery_completed_O_evidence_required')
    frozen=reader.value('round10/prepared/freeze.json')
    require(reader.hashes['round10/prepared/freeze.json']==expected_freeze,'recovery_O_freeze_changed')
    prepared=reader.value('round10/prepared/common.json')
    checkpoint=reader.value('round10/development_checkpoint.json')
    require(reader.hashes['round10/development_checkpoint.json']==evidence.checkpoint_sha256,
            'recovery_O_checkpoint_changed')
    intent=reader.value('round10/diagnostics/completed_o/intent.json');binding=intent['binding']
    require(set(binding)=={'scope','inputs','source_sha256','helper_sha256'}
            and binding['scope']==SCOPE and binding['source_sha256']==expected_source
            and binding['helper_sha256']==expected_helper,'recovery_legacy_source_binding_changed')
    inputs=binding['inputs']
    require(set(inputs)==INPUTS and all(isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v)
            for v in inputs.values()),'recovery_closed_input_inventory_required')
    for relative,expected in inputs.items():
        if relative.startswith('data/'):continue
        reader.raw(relative)
        require(reader.hashes[relative]==expected,'recovery_original_input_changed')
    # These are prior score/freeze anchors, NOT a fresh read of either data file.
    require(inputs['data/cohorts/dev_labels.json']==frozen['labels_sha256']
            and inputs['data/catalog.json']==prepared['catalog_sha256'],
            'recovery_unopened_data_anchor_changed')
    reader.raw('round7/tools/diagnose_completed_m.py')
    require(reader.hashes['round7/tools/diagnose_completed_m.py']==expected_helper,'recovery_helper_changed')
    store=CompletedStore(directory/'diagnostics/completed_o',binding,['aggregate'],
                         verify_sources=reader.revalidate,root=directory)
    aggregate=store.verify_completed()['aggregate']
    require(aggregate.get('scope')==SCOPE and aggregate.get('api_calls')==0
            and aggregate.get('validation_opened') is False
            and aggregate.get('new_fit_or_selection') is False
            and aggregate.get('new_bootstrap_replicates')==0,'recovery_diagnostic_scope_changed')
    require(aggregate['provenance_sha256']=={'inputs':fingerprint(inputs),
            'source':expected_source,'helper':expected_helper},'recovery_diagnostic_provenance_changed')
    require(aggregate['existing_selection']==checkpoint['selection'],'recovery_selection_changed')
    for arm in ('raw','OOF_mass'):
        for ds,n in (('asa24',99),('nutrition5k',84)):
            saved=checkpoint[arm]['metrics']['datasets'][ds]
            actual=aggregate['arms'][arm][ds]
            for task,reference in (('primary',saved['primary']),
                    ('full_serving',saved['e2e'] if ds=='asa24' else saved['primary'])):
                require(actual[task]['n']==reference['n'],'recovery_diagnostic_population_changed')
                for target in ('weight','energy','fat','carbs','protein'):
                    require(all(_same_number(actual[task]['targets'][target][key],
                        reference['metrics'][target][key]) for key in ('mae','per_unit','reference_mean')),
                        'recovery_diagnostic_point_changed')
            require(aggregate['physical_accounting'][ds]['population_n']==n,
                    'recovery_physical_population_changed')
    require(store.verify_completed()=={'aggregate':aggregate},'recovery_diagnostic_store_changed')
    reader.raw('round10/diagnostics/completed_o/completion.json');reader.revalidate()
    return {'status':'O_sealed_diagnostic_reverified','freeze_sha256':expected_freeze,
        'diagnostic_completion_sha256':reader.hashes['round10/diagnostics/completed_o/completion.json'],
        'checked_sources_sha256':fingerprint(reader.hashes),
        'historical_diagnostic_source_sha256':expected_source,'helper_sha256':expected_helper,
        'original_guard_receipt_missing':True,'original_guard_passed':False,
        'original_guard_counts_or_mtime_snapshot_recovered':False,
        'label_or_catalog_file_opened':False,'unopened_data_file_integrity_reverified':False,
        'recomputed_diagnostic':False,'recomputed_score':False,'new_fit_or_selection':False,
        'api_calls':0,'validation_opened':False,'grants_new_phase_action':False},aggregate


def main():
    require(len(sys.argv)==1,'recovery_no_root_or_pin_overrides')
    require(kernel_loopback_only(Path('/proc/self/net/dev').read_bytes()),'recovery_network_namespace_required')
    receipt=BASE/'round10/evidence/postscore_guard_recovery.json'
    require(not receipt.exists() and not (BASE/'round10/evidence/postscore_guard.json').exists(),
            'recovery_receipt_already_exists')
    frozen_raw=(BASE/'round10/prepared/freeze.json').read_bytes()
    require(hashlib.sha256(frozen_raw).hexdigest()==O_FREEZE,'recovery_trusted_O_freeze_required')
    frozen=json.loads(frozen_raw)
    allowed={BASE/p for p in frozen['source_files']}|{BASE/p for p in (
        'round10/prepared/freeze.json','round10/prepared/common.json','round10/REVIEW.md','round10/launch/automatic_followup.json',
        'round10/runs/verification.json','round10/development_checkpoint.json',
        'round7/tools/diagnose_completed_m.py','round11/o_completion.py',
        'round10/postscore/reverify_sealed_o.py','round10/postscore/guarded_diagnose_o.py')}
    trees=[BASE/'round10/runs'/p for p in ('identities','development','scoring')]
    trees.append(BASE/'round10/diagnostics/completed_o')
    counts={'forbidden_open_or_mutation':0,'socket_events':0,'open_policy_checks':0}
    write_receipt=False
    recovery_sources={p.relative_to(BASE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__),BASE/'round11/o_completion.py',BASE/'round10/postscore/guarded_diagnose_o.py')}
    own_sha=recovery_sources[Path(__file__).relative_to(BASE).as_posix()]
    def audit(event,args):
        if event.startswith('socket.'):
            counts['socket_events']+=1;raise AssertionError('recovery_network_forbidden')
        if event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn','os.spawn',
                     'os.fork','os.forkpty','pty.spawn','os.startfile','os.startfile/2'):
            counts['forbidden_open_or_mutation']+=1;raise AssertionError('recovery_child_process_forbidden')
        # CPython 3.10 documented audit events, including fd aliases:
        # https://docs.python.org/3.10/library/audit_events.html
        if event.startswith(('shutil.','ctypes.')) or event in (
                'mmap.__new__','os.remove','os.rename','os.mkdir','os.rmdir','os.link','os.symlink',
                'os.chmod','os.chown','os.chflags','os.truncate','os.utime','os.setxattr',
                'os.removexattr','os.chdir','os.putenv','os.unsetenv','os.kill','os.killpg',
                'signal.pthread_kill'):
            counts['forbidden_open_or_mutation']+=1;raise AssertionError('recovery_mutation_forbidden')
        if event!='open':return
        counts['open_policy_checks']+=1
        target,mode,flags=args
        path=Path(os.readlink('/proc/self/fd/'+str(target)) if type(target) is int else os.fsdecode(target)).absolute()
        canonical=path.resolve()
        writing=bool((flags or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)) \
            or any(c in (mode or '') for c in 'wax+')
        safe=path==canonical and not set(path.parts)&{'provider','validation','.git','.codex'} \
            and not path.name.startswith(('.env','val_','validation_','credentials'))
        if writing:safe=safe and write_receipt and path==receipt
        else:safe=safe and (path in allowed or any(path==p or p in path.parents for p in trees))
        if not safe:
            counts['forbidden_open_or_mutation']+=1;raise AssertionError('recovery_closed_read_policy')
    sys.addaudithook(audit)
    evidence=verify_completed_o()
    result,_=_verify_at(BASE,evidence)
    require(verify_completed_o()==evidence,'recovery_O_evidence_changed')
    require(all(hashlib.sha256((BASE/p).read_bytes()).hexdigest()==h for p,h in recovery_sources.items()),
            'recovery_source_changed')
    require(counts['forbidden_open_or_mutation']==counts['socket_events']==0,'recovery_policy_failed')
    result.update(completed_O_evidence=asdict(evidence),policy=counts,source_sha256=own_sha,
                  recovery_source_pins=recovery_sources)
    write_receipt=True
    fd=os.open(receipt,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write('\n')
    print(json.dumps({'status':result['status'],'api_calls':0,'validation_opened':False,
                     'original_guard_passed':False,'recomputed_diagnostic':False}))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        code=str(exc)
        print(json.dumps({'status':'O_diagnostic_reverify_refused','error_type':type(exc).__name__,
            'error_code':code if re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,120}',code) else 'non_safe_code_omitted'}))
        raise SystemExit(1)
