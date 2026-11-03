from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10')]
import test_gate_o as fixture_module
import run_o,stores_o
from opt_provider import sha,fingerprint
from service_o import Ledger,allowed_slots
from runtime_o import Trace,OProvider
from gate_o import Gate
from conditional_o import contexts_after_seal


class CompleteRunnerTests(unittest.TestCase):
    def test_coding_adapter_full_records_and_provider_free_replay(self):
        fixture=fixture_module.ExactGateTests('test_valid_initial_answer_cannot_get_repair')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        root=fixture.root;round_dir=root/'O';round_dir.mkdir(mode=0o700)
        (round_dir/'prepared').mkdir(mode=0o700)
        (round_dir/'prepared/embeddings.json').write_text('{}\n')
        manifest_sha=sha(round_dir/'prepared/embeddings.json')
        row=fixture.row;row['image_sha256']=sha(root/row['image_path'])
        ctx=fixture.ctx
        ctx.binding={'schema_version':1,'source_files':{},'labels_sha256':'synthetic-labels'}
        ctx.fallbacks={'vectors':{'asa24':{'0':dict(weight=100,energy=100,fat=1,carbs=10,protein=5)}}}
        ledger=Ledger(round_dir/'provider/O',ctx.binding,
            allowed_slots(ctx.rows,image_hashes={'a':fingerprint(fixture.image)}))
        ledger._gate=Gate(ctx,ledger,root=root)
        trace=Trace(ledger,fixture.imports,manifest_sha,allow_paid=True)
        trace.provider=OProvider(ledger,fixture.imports,allow_paid=True,
            keys=('synthetic-chat-secret','synthetic-embedding-secret'),
            transport=fixture.provider.client._transport,sleep=lambda _:None)
        phases=[]
        def adapter(context,service):
            identities,proof=stores_o.sealed_identities(context,service)
            contexts=contexts_after_seal(context.rows,identities,context.catalog,{'a':fixture.code},proof)
            store=stores_o.adapter_store(context)
            values={'contexts':contexts,'provenance':{
                'coding_completion_sha256':sha(round_dir/'runs/identities/completion.json'),
                'labels_sha256':context.binding['labels_sha256']}}
            if (store.directory/'completion.json').is_file():self.assertEqual(store.verify_completed(),values)
            else:store.finalize(values)
            phases.append('adapter_after_coding_seal')
        with patch.object(run_o,'ROOT',root),patch.object(run_o,'ROUND',round_dir), \
             patch.object(stores_o,'ROUND',round_dir):
            result=run_o.run(ctx,allow_paid=True,ledger=ledger,trace=trace,adapter_runner=adapter,
                            workers=1,emit=lambda **_:None)
            self.assertEqual(result['records'],1)
            self.assertTrue(result['provider_constructed'])
            saved=stores_o.final_store(ctx).verify_completed()
            record=saved[stores_o.name('record',row)]
            self.assertEqual(record['prediction']['energy'],240.) # mean of two identities.
            self.assertEqual(record['conditional']['prediction']['energy'],160.) # allowed truecode task.
            self.assertEqual(record['e2e']['prediction'],record['prediction'])
            count=len(fixture.seen)
            replay_trace=Trace(ledger,fixture.imports,manifest_sha,allow_paid=False)
            with patch('runtime_o.OProvider',side_effect=AssertionError('replay_constructed_provider')):
                replay=run_o.run(ctx,ledger=ledger,trace=replay_trace,adapter_runner=adapter,
                                workers=1,emit=lambda **_:None)
            self.assertTrue(replay['completed_replay'])
            self.assertFalse(replay['provider_constructed'])
            self.assertEqual(len(fixture.seen),count)
        self.assertEqual(phases,['adapter_after_coding_seal']*2)


if __name__=='__main__':unittest.main()
