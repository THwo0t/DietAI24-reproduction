from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import o_completion as g
from round4.src.artifacts import ArtifactError,ArtifactStore


def write(base,relative,value):
    path=base/relative;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    raw=value if isinstance(value,bytes) else (json.dumps(value,sort_keys=True)+'\n').encode()
    path.write_bytes(raw);return hashlib.sha256(raw).hexdigest()


def fixture(base,*,duplicate_oof=False,wrong_record=False):
    directory=base/'round10';directory.mkdir(mode=0o700)
    rows=[{'sample_id':f'a-{i}','dataset':'asa24','group_id':f'ag-{i%23}','fold':i%5} for i in range(99)]
    rows += [{'sample_id':f'n-{i}','dataset':'nutrition5k','group_id':f'ng-{i%78}','fold':i%5} for i in range(84)]
    source=write(base,'fixture.py',b'# synthetic trusted source\n')
    common=write(base,'round10/prepared/common.json',{'rows':rows})
    review=write(base,'round10/REVIEW.md',b'approved synthetic fixture only\n')
    frozen={'schema_version':1,'source_files':{'fixture.py':source,'round10/prepared/common.json':common},
            'review_sha256':review,'prepared_sha256':common,'rows_sha256':g.fingerprint(rows)}
    expected=write(base,'round10/prepared/freeze.json',frozen)
    name=lambda prefix,row:prefix+'-'+g.fingerprint(row['sample_id'])[:32]
    def seal(folder,binding,records):
        store=ArtifactStore(directory/'runs'/folder,binding,list(records),verify_sources=lambda:True,root=directory)
        store.finalize(records)
        return hashlib.sha256((directory/'runs'/folder/'completion.json').read_bytes()).hexdigest()
    identities={name('identity',row):{'status':'synthetic'} for row in rows};identities['service-proof']={}
    seal('identities',frozen,identities)
    raw=[{**row,'value':1} for row in rows]
    if wrong_record:raw[0]['sample_id']='wrong'
    records={name('record',row):record for row,record in zip(rows,raw)};records['service-proof']={}
    devhash=seal('development',frozen,records)
    write(base,'round10/runs/verification.json',{'completed_replay':True,'provider_constructed':False,
        'records':183,'completion_sha256':devhash,'freeze_sha256':expected})
    result={'scope':'O_development_OOF_not_independent_validation','validation_opened':False,'api_calls':0,
        'source_records_sha256':g.fingerprint(raw),'selection':{'profile':'OOF_mass','accepted':False},
        'raw':{'tolerance':{'failed_checks':10}},'OOF_mass':{'tolerance':{'failed_checks':10}},
        'calibration':{'nutrition5k':{'enabled':False,'fold_parameters':{'synthetic':1}}},
        'full_development_parameters':{'nutrition5k':{'training_ids':['private'],'eligible_ids':['private'],'factor':1}}}
    predictions=[dict(row) for row in rows]
    if duplicate_oof:predictions[0]=dict(predictions[1])
    seal('scoring',{'science':frozen,'completion_sha256':devhash},{'results':result,'OOF_predictions':predictions})
    summary=json.loads(json.dumps(result));summary['calibration']['nutrition5k'].pop('fold_parameters')
    summary['full_development_parameters']['nutrition5k'].pop('training_ids')
    summary['full_development_parameters']['nutrition5k'].pop('eligible_ids')
    write(base,'round10/development_checkpoint.json',summary)
    write(base,'round10/launch/automatic_followup.json',{'status':'development_scored','new_paid_requests':0,
        'validation_opened':False,'selection':result['selection'],'failed_checks':{'raw':10,'OOF_mass':10}})
    return expected,frozenset(frozen['source_files'])


class CompletionTests(unittest.TestCase):
    def verify(self,base,expected,names):
        return g._verify_at(base,expected,source_inventory=lambda _:names)

    def test_complete_real_store_fixture_returns_immutable_evidence_without_grant_or_disk_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);expected,names=fixture(base)
            before={p.relative_to(base):(p.stat().st_size,p.stat().st_mtime_ns) for p in base.rglob('*') if p.is_file()}
            evidence=self.verify(base,expected,names)
            self.assertEqual(evidence.records,183);self.assertFalse(evidence.grants_new_phase_action)
            with self.assertRaises(FrozenInstanceError):evidence.records=1
            after={p.relative_to(base):(p.stat().st_size,p.stat().st_mtime_ns) for p in base.rglob('*') if p.is_file()}
            self.assertEqual(before,after)

    def test_unfinished_or_fake_success_stops_before_sources_stores_or_any_action(self):
        for status in ('waiting_for_existing_base','offline_verify','offline_score'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as temp:
                base=Path(temp);write(base,'round10/launch/automatic_followup.json',{
                    'status':status,'new_paid_requests':0,'validation_opened':False})
                calls=[];original=g.Reader.raw
                def observed(reader,relative):calls.append(str(relative));return original(reader,relative)
                with patch.object(g.Reader,'raw',observed):
                    with self.assertRaisesRegex(ValueError,'complete_offline_score'):
                        self.verify(base,'f'*64,frozenset())
                self.assertEqual(calls,['round10/launch/automatic_followup.json'])
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);write(base,'round10/launch/automatic_followup.json',{
                'status':'development_scored','new_paid_requests':0,'validation_opened':False})
            with self.assertRaises(FileNotFoundError):self.verify(base,'f'*64,frozenset())

    def test_missing_each_completed_stage_rejects_even_with_success_followup(self):
        for relative in ('prepared/freeze.json','runs/identities/completion.json',
                         'runs/development/completion.json','runs/verification.json',
                         'runs/scoring/completion.json','development_checkpoint.json'):
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as temp:
                base=Path(temp);expected,names=fixture(base);(base/'round10'/relative).unlink()
                with self.assertRaises((ValueError,ArtifactError,FileNotFoundError)):
                    self.verify(base,expected,names)

    def test_stale_verification_and_wrong_boolean_types_refuse(self):
        for change in ({'completion_sha256':'f'*64},{'freeze_sha256':'f'*64},
                       {'completed_replay':1},{'provider_constructed':0},{'records':182}):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temp:
                base=Path(temp);expected,names=fixture(base)
                relative='round10/runs/verification.json';value=json.loads((base/relative).read_bytes())
                value.update(change);write(base,relative,value)
                with self.assertRaisesRegex(ValueError,'zero_Provider_replay'):
                    self.verify(base,expected,names)

    def test_same_size_restored_mtime_record_tamper_refuses_full_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);expected,names=fixture(base)
            path=next(p for p in (base/'round10/runs/development/records').glob('*.json')
                      if b'"value":1' in p.read_bytes())
            before=path.stat();path.write_bytes(path.read_bytes().replace(b'"value":1',b'"value":2'))
            os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
            with self.assertRaisesRegex(ArtifactError,'inventory_or_hash'):
                self.verify(base,expected,names)

    def test_duplicate_oof_or_changed_raw_sample_identity_refuses_semantically(self):
        for kwargs,code in [({'duplicate_oof':True},'OOF_population'),({'wrong_record':True},'record_identity')]:
            with self.subTest(kwargs=kwargs),tempfile.TemporaryDirectory() as temp:
                base=Path(temp);expected,names=fixture(base,**kwargs)
                with self.assertRaisesRegex(ValueError,code):self.verify(base,expected,names)

    def test_checkpoint_followup_source_drift_and_source_symlink_refuse(self):
        for kind in ('checkpoint','followup','source','symlink','extra_source'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                base=Path(temp);expected,names=fixture(base)
                if kind=='checkpoint':write(base,'round10/development_checkpoint.json',{'status':'success'})
                elif kind=='followup':
                    relative='round10/launch/automatic_followup.json';value=json.loads((base/relative).read_bytes())
                    value['failed_checks']={'raw':0,'OOF_mass':0};write(base,relative,value)
                elif kind=='source':(base/'fixture.py').write_bytes(b'# changed trusted source\n')
                elif kind=='symlink':
                    source=base/'fixture.py';destination=base/'target.py';source.rename(destination);source.symlink_to(destination)
                else:names=names|{'unknown.py'}
                with self.assertRaises((ValueError,ArtifactError)):self.verify(base,expected,names)

    def test_forbidden_reads_escape_duplicate_json_and_untrusted_freeze_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);reader=g.Reader(base)
            for path in ('../other.json','/tmp/other.json','.env','provider/cache.json',
                         'data/cohorts/dev_labels.json','validation/manifest.json','photo.png'):
                with self.subTest(path=path),self.assertRaisesRegex(ValueError,'unsafe_|forbidden_'):
                    reader.raw(path)
            expected,names=fixture(base)
            with self.assertRaisesRegex(ValueError,'trusted_O_freeze'):
                self.verify(base,'f'*64,names)
            write(base,'round10/launch/automatic_followup.json',b'{"status":"development_scored","status":"success"}')
            with self.assertRaisesRegex(ArtifactError,'duplicate_json_key'):
                self.verify(base,expected,names)

    def test_unexpected_store_env_or_image_is_rejected_before_body_open(self):
        for name in ('.env','secret.json','photo.png'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                base=Path(temp);expected,names=fixture(base)
                (base/'round10/runs/development'/name).write_bytes(b'POISON')
                original=ArtifactStore._bytes
                def checked(store,relative):
                    if Path(relative).name==name:raise AssertionError('forbidden body was opened')
                    return original(store,relative)
                with patch.object(ArtifactStore,'_bytes',checked):
                    with self.assertRaisesRegex(ValueError,'unexpected_O_store_read'):
                        self.verify(base,expected,names)


if __name__=='__main__':unittest.main()
