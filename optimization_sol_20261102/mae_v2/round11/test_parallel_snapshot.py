"""Synthetic next-phase concurrency evidence; never invokes a real O batch."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BASE / 'round11'), str(BASE / 'round10')]
import httpx
from PIL import Image
import identity_gate
import run_o
import stores_o
import test_gate_o as fixtures
from conditional_o import contexts_after_seal
from gate_o import Gate
from opt_pipeline import encode_image
from opt_provider import CHAT_MODEL, fingerprint, sha
from runtime_o import OProvider, Trace
from service_o import Ledger, allowed_slots


RESTART = r'''
from pathlib import Path
import json, sys
from types import SimpleNamespace
from unittest.mock import patch
root, base = map(Path, sys.argv[1:])
sys.path[:0] = [str(base/'round11'), str(base/'round10')]
import identity_gate, run_o, runtime_o, stores_o, test_gate_o
from gate_o import Gate
from service_o import Ledger, allowed_slots
from opt_pipeline import encode_image
from opt_provider import fingerprint
saved=json.loads((root/'synthetic_context.json').read_text())
assert saved.pop('kind') == 'synthetic_parallel_snapshot_fixture'
ctx=SimpleNamespace(**saved, retriever=test_gate_o.FakeRetriever(), verify_sources=lambda:True)
directory=root/'O'
images={r['sample_id']:fingerprint(encode_image(root/r['image_path'],'square256')) for r in ctx.rows}
ledger=Ledger(directory/'provider/O',ctx.binding,allowed_slots(ctx.rows,image_hashes=images))
gate=Gate(ctx,ledger,root=root); ledger._gate=gate
with patch.object(run_o,'ROOT',root),patch.object(run_o,'ROUND',directory),patch.object(stores_o,'ROUND',directory):
    with patch.object(identity_gate,'verify_proof',wraps=stores_o.verify_proof) as proof:
        snapshot=identity_gate.build_loader(ctx,ledger,stores_o.identity_store(ctx),data_root=root)
        assert proof.call_count == 1
        gate.identity_loader=snapshot.load
        with patch.object(runtime_o,'OProvider',side_effect=AssertionError('Provider_forbidden')):
            result=run_o.run(ctx,ledger=ledger,allow_paid=False,workers=2,emit=lambda **_:None)
        assert proof.call_count == 1
        snapshot.revalidate_full()
        assert proof.call_count == 2
assert result['records'] == 3 and result['completed_replay'] and not result['provider_constructed']
print(json.dumps({'provider_constructed':False,'full_proofs':proof.call_count,'records':3}))
'''


class ParallelSnapshotTests(unittest.TestCase):
    def run_fixture(self, cached, failure):
        f = fixtures.ExactGateTests('test_valid_initial_answer_cannot_get_repair')
        f.setUp()
        self.addCleanup(f.doCleanups)
        root, ctx = f.root, f.ctx
        directory = root / 'O'
        (directory / 'prepared').mkdir(parents=True)
        (directory / 'prepared/embeddings.json').write_text('{}\n')
        rows, images = [], {}
        for sid, dataset, color in [('a', 'asa24', (120, 150, 170)),
                                    ('b', 'nutrition5k', (160, 110, 140)),
                                    ('c', 'asa24', (150, 140, 100))]:
            path = root / (sid + '.png')
            Image.new('RGB', (80, 60), color).save(path)
            row = {**deepcopy(f.row), 'sample_id': sid, 'dataset': dataset,
                   'group_id': 'synthetic-' + sid, 'image_path': path.name,
                   'image_sha256': sha(path)}
            rows.append(row)
            images[sid] = fingerprint(encode_image(path, 'square256'))
        ctx.rows = rows
        ctx.binding = {'schema_version': 1, 'source_files': {}, 'labels_sha256': 'synthetic'}
        ctx.imports.update(source_files={}, legacy={'source_files': {}})
        ctx.fallbacks = {'vectors': {dataset: {'0': dict(weight=100, energy=200, fat=3,
                                                        carbs=20, protein=5)}
                                    for dataset in ('asa24', 'nutrition5k')}}
        ledger = Ledger(directory / 'provider/O', ctx.binding,
                        allowed_slots(rows, image_hashes=images))
        gate = Gate(ctx, ledger, root=root)
        ledger._gate = gate
        original = f.provider.client._transport.handler

        def handler(request):
            body = json.loads(request.content)
            if body.get('messages'):
                prompt = body['messages'][1]['content'][0]['text']
                failed = ((failure == 'whole' and prompt.startswith('Estimate the cooked edible portion'))
                          or (failure == 'conditional' and prompt.startswith('Estimate the cooked edible weight')))
                if failed:
                    return httpx.Response(200, json={'model': CHAT_MODEL, 'choices': [
                        {'message': {'content': 'invalid synthetic format'}, 'finish_reason': 'stop'}]})
            return original(request)

        trace = Trace(ledger, ctx.imports, sha(directory / 'prepared/embeddings.json'), allow_paid=True)
        trace.provider = OProvider(ledger, ctx.imports, allow_paid=True,
            keys=('synthetic-chat-secret', 'synthetic-embedding-secret'),
            transport=httpx.MockTransport(handler), sleep=lambda _: None)
        snapshots = []

        def adapter(context, service):
            ids, proof = stores_o.sealed_identities(context, service)
            contexts = contexts_after_seal(rows, ids, ctx.catalog, {'a': f.code, 'c': f.code}, proof)
            stores_o.adapter_store(context).finalize({'contexts': contexts, 'provenance': {
                'coding_completion_sha256': sha(directory / 'runs/identities/completion.json'),
                'labels_sha256': ctx.binding['labels_sha256']}})
            if cached:
                snapshot = identity_gate.build_loader(ctx, service, stores_o.identity_store(ctx), data_root=root)
                gate.identity_loader = snapshot.load
                snapshots.append(snapshot)

        with patch.object(run_o, 'ROOT', root), patch.object(run_o, 'ROUND', directory), \
                patch.object(stores_o, 'ROUND', directory):
            with patch.object(identity_gate, 'verify_proof', wraps=stores_o.verify_proof) as proof:
                result = run_o.run(ctx, ledger=ledger, trace=trace, allow_paid=True, workers=2,
                                   adapter_runner=adapter, emit=lambda **_: None)
                if cached:
                    self.assertEqual(proof.call_count, 1)
                    for _ in range(3):
                        self.assertEqual(len(snapshots[0].load()[0]), 3)
                    self.assertEqual(proof.call_count, 1)
                    snapshots[0].revalidate_full()
                    self.assertEqual(proof.call_count, 2)
            records = stores_o.final_store(ctx).verify_completed()
        self.assertEqual(result['records'], 3)
        record_rows = {r['sample_id']: records[stores_o.name('record', r)] for r in rows}
        self.assertEqual(record_rows['a']['conditional']['fallback'], failure == 'conditional')
        self.assertEqual(record_rows['c']['conditional']['fallback'], failure == 'conditional')
        for record in record_rows.values():
            self.assertEqual(record['fallback'], failure == 'whole')
        if cached:
            saved = {'kind': 'synthetic_parallel_snapshot_fixture', **{k: getattr(ctx, k) for k in
                     ('rows', 'catalog', 'imports', 'binding', 'fallbacks')}}
            (root / 'synthetic_context.json').write_text(json.dumps(saved))
            restarted = subprocess.run([sys.executable, '-B', '-c', RESTART, str(root), str(BASE)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            self.assertEqual(restarted.returncode, 0, restarted.stderr)
            self.assertEqual(json.loads(restarted.stdout), {
                'provider_constructed': False, 'full_proofs': 2, 'records': 3})
        # Independent concurrent runs assign reservation IDs/cache reuse order
        # differently. Within EACH run, original full replay checked these
        # exact refs; between runs compare every slot/payload/value/origin.
        references = {}
        for folder in ('identities', 'development'):
            for path in sorted((directory / 'runs' / folder / 'stages').glob('*/result.json')):
                envelope = json.loads(path.read_text())['parsed']
                if 'request_refs' not in envelope:
                    continue  # final record cache, verified above
                groups = {}
                for phase, refs in envelope['request_refs'].items():
                    for ref in refs:
                        self.assertEqual(set(ref), {'slot', 'payload_hash', 'value_hash',
                            'reservation_id', 'cache_present_before', 'origin'})
                    groups[phase] = [{k: v for k, v in ref.items()
                                      if k not in ('reservation_id', 'cache_present_before')} for ref in refs]
                references[folder + '/' + path.parent.name] = groups
        self.assertEqual(len(references), 8)  # 3 identities + 3 whole + 2 conditional
        # Both full ArtifactStore and ledger proofs independently passed.
        proof = records['service-proof']
        semantic_proof = {k: proof[k] for k in ('counts', 'logical_answers')}
        return record_rows, references, semantic_proof

    def test_three_rows_two_workers_match_for_success_and_both_failure_branches(self):
        for failure in (None, 'whole', 'conditional'):
            with self.subTest(failure=failure):
                self.assertEqual(self.run_fixture(False, failure), self.run_fixture(True, failure))


if __name__ == '__main__':
    unittest.main()
