import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE/'round11'),str(BASE/'round10')]
import httpx
import test_gate_o as fixtures
import run_o,stores_o
from identity_gate import build_loader
from opt_provider import sha,fingerprint,CHAT_MODEL
from runtime_o import Trace,OProvider
from service_o import Ledger,allowed_slots
from gate_o import Gate
from conditional_o import contexts_after_seal


REPLAY_SCRIPT='''
from pathlib import Path
import json,sys
from types import SimpleNamespace
from unittest.mock import patch
root=Path(sys.argv[1]);base=Path(sys.argv[2])
sys.path[:0]=[str(base/'round11'),str(base/'round10')]
import run_o,stores_o,runtime_o,test_gate_o
from service_o import Ledger,allowed_slots
from gate_o import Gate
from identity_gate import build_loader
from opt_pipeline import encode_image
from opt_provider import sha,fingerprint
saved=json.loads((root/'synthetic_context.json').read_text())
assert saved.pop('kind')=='synthetic_complete_runner_fixture'
ctx=SimpleNamespace(**saved,retriever=test_gate_o.FakeRetriever())
def verify_sources():
    if not all(sha(root/p)==h for p,h in ctx.binding['source_files'].items()):
        raise ValueError('synthetic_source_pin_changed')
ctx.verify_sources=verify_sources
directory=root/'O'
ledger=Ledger(directory/'provider/O',ctx.binding,allowed_slots(ctx.rows,
    image_hashes={'a':fingerprint(encode_image(root/'synthetic.png','square256'))}))
gate=Gate(ctx,ledger,root=root);ledger._gate=gate
with patch.object(run_o,'ROOT',root),patch.object(run_o,'ROUND',directory),patch.object(stores_o,'ROUND',directory):
    snapshot=build_loader(ctx,ledger,stores_o.identity_store(ctx),data_root=root)
    gate.identity_loader=snapshot.load
    with patch.object(runtime_o,'OProvider',side_effect=AssertionError('no_provider_on_restart')):
        result=run_o.run(ctx,ledger=ledger,allow_paid=False,emit=lambda **_:None)
    snapshot.revalidate_full()
assert result['completed_replay'] is True and result['provider_constructed'] is False
print(json.dumps({'status':'synthetic_distinct_process_replay_passed','provider_constructed':False}))
'''


class FullRunnerEquivalenceTests(unittest.TestCase):
    def run_fixture(self,cached,failure):
        f=fixtures.ExactGateTests('test_valid_initial_answer_cannot_get_repair')
        f.setUp();self.addCleanup(f.doCleanups)
        root=f.root;directory=root/'O';directory.mkdir(mode=0o700)
        (directory/'prepared').mkdir(mode=0o700)
        (directory/'prepared/embeddings.json').write_text('{}\n')
        source=root/'synthetic_source.py';source.write_text('# fixed synthetic source\n')
        imported=root/'synthetic_import.json';imported.write_text('{"synthetic": true}\n')
        legacy=root/'synthetic_legacy.json';legacy.write_text('{"legacy": true}\n')
        f.imports.update(source_files={'synthetic_import.json':sha(imported)},
            legacy={'source_files':{root.name+'/synthetic_legacy.json':sha(legacy)}})
        f.row['image_sha256']=sha(root/'synthetic.png')
        ctx=f.ctx;ctx.binding={'schema_version':1,'source_files':{'synthetic_source.py':sha(source)},
                              'labels_sha256':'synthetic-labels'}
        def verify_sources():
            if not all(sha(root/p)==h for p,h in ctx.binding['source_files'].items()):
                raise ValueError('synthetic_source_pin_changed')
        ctx.verify_sources=verify_sources
        ctx.fallbacks={'vectors':{'asa24':{'0':dict(weight=100,energy=200,fat=3,carbs=20,protein=5)}}}
        ledger=Ledger(directory/'provider/O',ctx.binding,allowed_slots(ctx.rows,image_hashes={'a':fingerprint(f.image)}))
        gate=Gate(ctx,ledger,root=root);ledger._gate=gate
        original=f.provider.client._transport.handler
        def handler(request):
            value=json.loads(request.content)
            if value.get('messages'):
                prompt=value['messages'][1]['content'][0]['text']
                failed=(failure=='whole' and prompt.startswith('Estimate the cooked edible portion')
                        or failure=='conditional' and prompt.startswith('Estimate the cooked edible weight'))
                if failed:
                    f.seen.append(value)
                    return httpx.Response(200,json={'model':CHAT_MODEL,'choices':[
                        {'message':{'content':'invalid synthetic format'},'finish_reason':'stop'}]})
            return original(request)
        trace=Trace(ledger,ctx.imports,sha(directory/'prepared/embeddings.json'),allow_paid=True)
        trace.provider=OProvider(ledger,ctx.imports,allow_paid=True,
            keys=('synthetic-chat-secret','synthetic-embedding-secret'),transport=httpx.MockTransport(handler),sleep=lambda _:None)
        snapshots=[]
        def adapter(context,service):
            ids,proof=stores_o.sealed_identities(context,service)
            contexts=contexts_after_seal(context.rows,ids,context.catalog,{'a':f.code},proof)
            store=stores_o.adapter_store(context)
            store.finalize({'contexts':contexts,'provenance':{
                'coding_completion_sha256':sha(directory/'runs/identities/completion.json'),
                'labels_sha256':context.binding['labels_sha256']}})
            if cached:
                snapshot=build_loader(context,service,stores_o.identity_store(context),data_root=root)
                gate.identity_loader=snapshot.load;snapshots.append(snapshot)
        with patch.object(run_o,'ROOT',root),patch.object(run_o,'ROUND',directory),patch.object(stores_o,'ROUND',directory):
            result=run_o.run(ctx,ledger=ledger,trace=trace,allow_paid=True,workers=1,
                            adapter_runner=adapter,emit=lambda **_:None)
            record=stores_o.final_store(ctx).verify_completed()[stores_o.name('record',f.row)]
            for snapshot in snapshots:
                for dependency in (source,imported,legacy):
                    before=dependency.read_bytes()
                    dependency.write_bytes(before+b' ')
                    try:
                        with self.assertRaisesRegex(ValueError,'source_pin_changed|dependency_changed'):
                            snapshot.load()
                    finally:dependency.write_bytes(before)
                snapshot.revalidate_full()
        self.assertEqual(result['records'],1)
        if cached:
            saved={'kind':'synthetic_complete_runner_fixture',**{k:getattr(ctx,k) for k in
                    ('rows','catalog','imports','binding','fallbacks')}}
            (root/'synthetic_context.json').write_text(json.dumps(saved))
            replay=subprocess.run([sys.executable,'-B','-c',REPLAY_SCRIPT,str(root),str(BASE)],
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=False)
            self.assertEqual(replay.returncode,0,replay.stderr)
            self.assertEqual(json.loads(replay.stdout)['provider_constructed'],False)
        return record,result['service_counts']

    def test_complete_records_success_and_two_fallback_paths_match_uncached_and_restart_without_provider(self):
        for failure in (None,'whole','conditional'):
            with self.subTest(failure=failure):
                original,old_counts=self.run_fixture(False,failure)
                cached,new_counts=self.run_fixture(True,failure)
                self.assertEqual(cached,original)
                self.assertEqual(new_counts,old_counts)
                self.assertEqual(cached['fallback'],failure=='whole')
                self.assertEqual(cached['conditional']['fallback'],failure=='conditional')


if __name__=='__main__':unittest.main()
