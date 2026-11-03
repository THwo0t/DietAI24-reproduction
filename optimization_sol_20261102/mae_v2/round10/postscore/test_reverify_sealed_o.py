from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import reverify_sealed_o as r
from o_completion import CompletedOEvidence
from round4.src.artifacts import ArtifactStore,key_path


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class RecoveryTests(unittest.TestCase):
    entry_cases=('none','label','truncate','utime','chmod','chown','setxattr')
    def fixture(self,*,wrong_point=False,extra_input=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        base=Path(temp.name)
        def save(relative,value):
            path=base/relative;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            path.write_text(json.dumps(value,sort_keys=True)+'\n');return path
        metric={k:{'mae':1.,'per_unit':.01,'reference_mean':100.}
                for k in ('weight','energy','fat','carbs','protein')}
        summary=lambda n:{'n':n,'metrics':deepcopy(metric)}
        checkpoint={'selection':{'profile':'OOF_mass','accepted':False}}
        for arm in ('raw','OOF_mass'):
            checkpoint[arm]={'metrics':{'datasets':{
                'asa24':{'primary':summary(17),'e2e':summary(99)},
                'nutrition5k':{'primary':summary(84)}}}}
        freeze=save('round10/prepared/freeze.json',{'labels_sha256':'a'*64,'source_files':{}})
        common=save('round10/prepared/common.json',{'catalog_sha256':'b'*64})
        cp=save('round10/development_checkpoint.json',checkpoint)
        for name in ('runs/development/completion.json','runs/scoring/completion.json','runs/verification.json'):
            save('round10/'+name,{'synthetic':name})
        helper=base/'round7/tools/diagnose_completed_m.py'
        helper.parent.mkdir(parents=True,mode=0o700);helper.write_text('# synthetic helper\n')
        inputs={p:digest(base/p) for p in r.INPUTS if not p.startswith('data/')}
        inputs.update({'data/cohorts/dev_labels.json':'a'*64,'data/catalog.json':'b'*64})
        if extra_input:inputs['credentials.json']='c'*64
        source='d'*64;helper_sha=digest(helper)
        binding={'scope':r.SCOPE,'inputs':inputs,'source_sha256':source,'helper_sha256':helper_sha}
        aggregate={'scope':r.SCOPE,'api_calls':0,'validation_opened':False,'new_fit_or_selection':False,
            'new_bootstrap_replicates':0,'existing_selection':checkpoint['selection'],
            'provenance_sha256':{'inputs':r.fingerprint(inputs),'source':source,'helper':helper_sha},
            'physical_accounting':{'asa24':{'population_n':99},'nutrition5k':{'population_n':84}},'arms':{}}
        for arm in ('raw','OOF_mass'):
            aggregate['arms'][arm]={}
            for ds,n in (('asa24',99),('nutrition5k',84)):
                saved=checkpoint[arm]['metrics']['datasets'][ds]
                aggregate['arms'][arm][ds]={task:{'n':ref['n'],'targets':deepcopy(ref['metrics'])}
                    for task,ref in (('primary',saved['primary']),
                                    ('full_serving',saved['e2e'] if ds=='asa24' else saved['primary']))}
        if wrong_point:aggregate['arms']['raw']['nutrition5k']['primary']['targets']['weight']['mae']=2.
        store=ArtifactStore(base/'round10/diagnostics/completed_o',binding,['aggregate'],
                            verify_sources=lambda:True,root=base/'round10')
        store.finalize({'aggregate':aggregate})
        e=CompletedOEvidence(digest(freeze),'e'*64,'f'*64,'0'*64,digest(cp),'1'*64,'2'*64)
        options={'expected_freeze':digest(freeze),'expected_source':source,'expected_helper':helper_sha}
        return base,e,options,store

    def test_existing_seal_reverified_without_data_files_or_recompute(self):
        base,e,options,store=self.fixture()
        before={p.relative_to(base).as_posix():(digest(p),p.stat().st_mtime_ns)
                for p in base.rglob('*') if p.is_file()}
        result,_=r._verify_at(base,e,**options)
        self.assertFalse(result['original_guard_passed'])
        self.assertFalse(result['label_or_catalog_file_opened'])
        self.assertFalse(result['recomputed_diagnostic'])
        self.assertFalse(result['grants_new_phase_action'])
        self.assertFalse((base/'data').exists())
        self.assertEqual(before,{p.relative_to(base).as_posix():(digest(p),p.stat().st_mtime_ns)
                                for p in base.rglob('*') if p.is_file()})

    def test_closed_inputs_refuse_unknown_credential_path_before_open(self):
        base,e,options,_=self.fixture(extra_input=True)
        with self.assertRaisesRegex(ValueError,'closed_input_inventory'):
            r._verify_at(base,e,**options)

    def test_valid_seal_with_different_point_does_not_override_original_score(self):
        base,e,options,_=self.fixture(wrong_point=True)
        with self.assertRaisesRegex(ValueError,'diagnostic_point_changed'):
            r._verify_at(base,e,**options)

    def test_changed_source_same_size_and_mtime_refuses(self):
        base,e,options,_=self.fixture();path=base/'round10/prepared/common.json'
        stat=path.stat();raw=path.read_bytes();path.write_bytes(raw.replace(b'b'*64,b'c'*64))
        os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'original_input_changed'):
            r._verify_at(base,e,**options)

    def test_changed_legacy_source_binding_refuses(self):
        base,e,options,_=self.fixture();options['expected_source']='0'*64
        with self.assertRaisesRegex(ValueError,'legacy_source_binding_changed'):
            r._verify_at(base,e,**options)

    def test_unexpected_store_secret_is_refused_before_body_read(self):
        base,e,options,store=self.fixture();secret=store.directory/'unexpected.env'
        secret.write_text('synthetic should not be read');secret.chmod(0o600)
        original=Path.read_bytes;opened=[]
        def read(path):
            opened.append(path);return original(path)
        with patch.object(Path,'read_bytes',read):
            with self.assertRaisesRegex(ValueError,'unexpected_O_store_read_refused'):
                r._verify_at(base,e,**options)
        self.assertNotIn(secret,opened)

    def test_fresh_process_guard_writes_only_recovery_receipt_and_blocks_label_attempt(self):
        script=r'''
from dataclasses import asdict
import importlib.util,json,sys
from pathlib import Path
base,original,case=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
sys.path[:0]=[str(original/'round10/postscore'),str(original/'round11'),str(original)]
from o_completion import CompletedOEvidence
context=json.loads((base/'synthetic_context.json').read_text())
path=base/'round10/postscore/reverify_sealed_o.py'
spec=importlib.util.spec_from_file_location('synthetic_recovery_entry',path)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
e=CompletedOEvidence(**context['evidence']);options=context['options']
r.O_FREEZE=options['expected_freeze']
actual=r._verify_at
r._verify_at=lambda base,evidence:actual(base,evidence,**options)
def completed():
    victim=base/'outside_policy.txt'
    if case=='label':(base/'data/cohorts/dev_labels.json').read_bytes()
    elif case=='truncate':r.os.truncate(victim,0)
    elif case=='utime':r.os.utime(victim,ns=(1,2))
    elif case=='chmod':r.os.chmod(victim,0o777)
    elif case=='chown':r.os.chown(victim,-1,-1)
    elif case=='setxattr':r.os.setxattr(victim,'user.synthetic',b'1')
    return e
r.verify_completed_o=completed
sys.argv=['synthetic_recovery_entry']
if case!='none':
    try:r.main()
    except AssertionError as error:
        assert str(error)==('recovery_closed_read_policy' if case=='label' else 'recovery_mutation_forbidden')
        assert not (base/'round10/evidence/postscore_guard_recovery.json').exists()
        print('synthetic_forbidden_attempt_refused')
    else:raise AssertionError('forbidden_attempt_not_blocked')
else:r.main()
'''
        from dataclasses import asdict
        for case in self.entry_cases:
            with self.subTest(case=case):
                base,e,options,store=self.fixture()
                for relative in ('round10/postscore/reverify_sealed_o.py',
                                 'round10/postscore/guarded_diagnose_o.py','round11/o_completion.py'):
                    target=base/relative;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    shutil.copyfile(r.BASE/relative,target)
                (base/'round10/evidence').mkdir(mode=0o700)
                (base/'synthetic_context.json').write_text(json.dumps({'evidence':asdict(e),'options':options}))
                victim=base/'outside_policy.txt';victim.write_bytes(b'synthetic immutable bytes')
                info=victim.stat()
                victim_before=(victim.read_bytes(),info.st_mode,info.st_uid,info.st_gid,info.st_mtime_ns,info.st_ctime_ns)
                before={p.relative_to(store.directory).as_posix():digest(p)
                        for p in store.directory.rglob('*') if p.is_file()}
                child=subprocess.run([sys.executable,'-B','-c',script,str(base),str(r.BASE),
                                      case],capture_output=True,text=True)
                self.assertEqual(child.returncode,0,child.stderr)
                if case!='none':self.assertEqual(child.stdout.strip(),'synthetic_forbidden_attempt_refused')
                else:
                    receipt=json.loads((base/'round10/evidence/postscore_guard_recovery.json').read_text())
                    self.assertFalse(receipt['original_guard_passed'])
                    self.assertEqual(receipt['policy']['forbidden_open_or_mutation'],0)
                    self.assertEqual(receipt['policy']['socket_events'],0)
                info=victim.stat()
                self.assertEqual(victim_before,(victim.read_bytes(),info.st_mode,info.st_uid,info.st_gid,info.st_mtime_ns,info.st_ctime_ns))
                self.assertEqual(before,{p.relative_to(store.directory).as_posix():digest(p)
                    for p in store.directory.rglob('*') if p.is_file()})


if __name__=='__main__':unittest.main()
