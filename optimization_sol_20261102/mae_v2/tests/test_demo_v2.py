"""Portable demo tests use synthetic reports and the two approved old demo images."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import demo
import package_demo as package


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else value.encode())
    return path


def pdf_bytes():
    """Tiny valid PDF: synthetic aggregate text, no authoring dependency."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    content = b'BT /F1 12 Tf 30 150 Td (Synthetic aggregate fixture) Tj ET'
    objects.append(b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream')
    data, offsets = b'%PDF-1.4\n', [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(data)
    data += f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def config(name='A', base='C', identity='B'):
    if name in ('A', 'B'):
        return {'profile': name, 'crop_review': name == 'B', 'portion_mode': 'direct'}
    cfg = {'profile': name, 'crop_review': identity == 'B', 'portion_mode': 'total_ratio',
           'identity_profile': identity}
    if name in ('D', 'E'):
        cfg['base_profile'] = base
        if base != 'C':
            cfg.update(crop_review=base == 'B', portion_mode='direct')
            cfg.pop('identity_profile')
    return cfg


def fixture(root):
    # Exact approved historical image bytes are the only non-synthetic data read.
    for name in ('tools/demo_inputs.json', 'tools/demo_images/asa24.png', 'tools/demo_images/nutrition5k.png'):
        write(root, name, (ROOT / name).read_bytes())
    for name in package.SOURCE_REQUIRED:
        if not (root / name).exists():
            write(root, name, b'{}\n' if name.endswith('.json') else b'# synthetic package fixture\n')
    for name in ('tools/demo.py', 'tools/package_demo.py'):
        write(root, name, (ROOT / name).read_bytes())
    write(root, demo.REPORT_STEM + '.json', json.dumps({'status': 'fixture_only', 'aggregate': {'n': 10, 'mae': 1.2}}))
    write(root, demo.REPORT_STEM + '.md', '# Synthetic aggregate fixture\n')
    write(root, demo.REPORT_STEM + '.pdf', pdf_bytes())
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, 'w') as archive:
        archive.writestr('word/document.xml', '<document>Synthetic aggregate fixture</document>')
    write(root, demo.REPORT_STEM + '.docx', docx.getvalue())
    codes = [str(10000000 + i) for i in range(5624)]
    write(root, 'data/catalog.json', json.dumps({'foods': {code: {} for code in codes}}))
    vector_data = {'embeddings.npy': b'synthetic vector payload, not used for inference',
                   'codes.json': json.dumps(codes).encode(), 'collection.json': b'{}'}
    for name, data in vector_data.items():
        write(root, 'data/vectors/' + name, data)
    write(root, 'data/vectors/manifest.json', json.dumps({'vectors': 5624, 'dimensions': 3072,
        'embedding_model': 'text-embedding-3-large', 'files': {name: hashlib.sha256(data).hexdigest() for name, data in vector_data.items()}}))
    selection = {'joint_pass': False, 'profiles': {
        'asa24': {'name': 'baseline', 'config': {'portion_modes': {'asa24': 'direct', 'nutrition5k': 'direct'}, 'examples': False}},
        'nutrition5k': {'name': 'A', 'config': config()}}}
    params = {dataset: {'dataset': dataset, 'mass_factor': 1.0, 'enabled': False,
        'fallback': {name: 1.0 for name in demo.TARGETS}, 'training_ids': ['must-not-copy']} for dataset in demo.APPROVED_IMAGES}
    profile = demo.make_demo_profile(selection, params, root)
    write(root, 'reports/demo_profile.json', json.dumps(profile))
    return profile, selection, params


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mae-v2-demo-test-')
        self.root = Path(self.temp.name) / 'package'
        self.profile, self.selection, self.params = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_offline_check_does_not_open_private_data_or_credentials(self):
        write(self.root, '.env', 'DO NOT OPEN')
        write(self.root, 'data/cohorts/sealed/validation.jsonl', 'DO NOT OPEN')
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.name == '.env' or 'cohorts' in path.parts or 'freeze' in path.parts:
                raise AssertionError('private read')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded), patch.object(socket, 'create_connection', side_effect=AssertionError('network')):
            result = demo.check(self.root, require_runtime=True)
            page = demo.render_page(self.root)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['api_calls'], 0)
        self.assertFalse(result['credentials_read'])
        self.assertFalse(result['research_cohorts_read'])
        self.assertIn(b'Exact-conditioned', page)

    def test_dry_run_never_loads_credentials(self):
        with patch.object(demo, '_local_keys', side_effect=AssertionError('credential read')):
            result = demo.live(self.root)
        self.assertEqual(result['status'], 'READY_DRY_RUN')

    def test_paid_credentials_are_strictly_local_and_permission_checked(self):
        # Synthetic credentials only; no real local .env is inspected.
        parent_env = write(self.root.parent, '.env', 'PARENT MUST NOT BE USED')
        parent_env.chmod(0o600)
        with self.assertRaises(ValueError):
            demo._local_keys(self.root)
        content = '\n'.join(('OPENAI_BASE_URL=https://api.zicc.cc/v1',
            'EMBEDDING_BASE_URL=https://api.openai.com/v1', 'CHAT_MODEL=gpt-6.1-sol',
            'VISION_MODEL=gpt-6.1-sol', 'OPENAI_API_' + 'KEY=fake-chat-value',
            'EMBEDDING_API_' + 'KEY=fake-embedding-value'))
        path = write(self.root, '.env', content)
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            demo._local_keys(self.root)
        path.chmod(0o600)
        self.assertEqual(len(demo._local_keys(self.root)), 2)
        path.write_text(content.replace('https://api.zicc.cc/v1', 'https://wrong.invalid/v1'))
        with self.assertRaises(ValueError):
            demo._local_keys(self.root)

    def test_missing_report_is_incomplete(self):
        (self.root / (demo.REPORT_STEM + '.pdf')).unlink()
        self.assertEqual(demo.check(self.root)['status'], 'INCOMPLETE')

    def test_profile_has_exact_params_and_no_training_ids(self):
        result = demo.make_demo_profile(self.selection, self.params, self.root)
        self.assertNotIn('must-not-copy', json.dumps(result))
        self.assertNotIn('training_ids', json.dumps(result))
        self.assertEqual(result['profiles']['nutrition5k']['parameters']['fallback'], self.params['nutrition5k']['fallback'])
        self.assertEqual(set(result['source_sha256']), set(demo.INFERENCE_FILES))

    def test_profile_rejects_source_change_bad_factor_bad_ancestry(self):
        for name in ('A', 'B', 'C', 'D', 'E'):
            profile = deepcopy(self.profile)
            profile['profiles']['nutrition5k'].update(name=name, config=config(name))
            demo.validate_profile(profile, self.root)
        profile['profiles']['nutrition5k']['config']['crop_review'] = False
        with self.assertRaises(ValueError):
            demo.validate_profile(profile, self.root)
        for factor in (True, float('nan'), .8, 1.2):
            profile = deepcopy(self.profile)
            profile['profiles']['nutrition5k']['parameters']['mass_factor'] = factor
            with self.assertRaises(ValueError):
                demo.validate_profile(profile, self.root)
        write(self.root, demo.INFERENCE_FILES[0], '# changed\n')
        with self.assertRaises(ValueError):
            demo.validate_profile(self.profile, self.root)

    def test_runtime_tampering_and_demo_image_tampering_fail(self):
        write(self.root, 'data/vectors/embeddings.npy', b'changed')
        with self.assertRaises(ValueError):
            demo.check(self.root, require_runtime=True)
        write(self.root, 'tools/demo_images/asa24.png', b'changed')
        with self.assertRaises(ValueError):
            demo.demo_inputs(self.root)

    def test_safe_path_and_symlink_rejected(self):
        for value in ('../secret', '/tmp/secret', 'reports/../secret', 'reports//file', 'reports/%2e%2e/file', 'a\\b'):
            with self.assertRaises(ValueError):
                demo.safe_file(self.root, value)
        (self.root / 'reports/link').symlink_to(self.root / 'tools/demo.py')
        with self.assertRaises(ValueError):
            demo.safe_file(self.root, 'reports/link')

    def test_row_results_refused(self):
        for key in ('training_ids', 'predictions', 'sample_id', 'image_path'):
            with self.assertRaises(ValueError):
                demo.aggregate_only({'nested': [{key: 'private'}]})
        write(self.root, 'reports/metrics.csv', 'sample_id,mae\nprivate,1\n')
        with self.assertRaises(ValueError):
            demo.public_files(self.root)

    def test_http_only_public_allowlist_and_revalidates_changed_json(self):
        # Exercise the actual HTTP handler over an in-memory socket. Restricted
        # offline runners may forbid even loopback sockets.
        with patch.object(demo, 'ThreadingHTTPServer', side_effect=lambda address, handler: SimpleNamespace(address=address, handler=handler)):
            server = demo.server(self.root, port=0)
        self.assertEqual(server.address, ('127.0.0.1', 0))
        class Request:
            def __init__(self, path):
                self.input = io.BytesIO(f'GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n'.encode())
                self.output = b''
            def makefile(self, *_args):
                return self.input
            def sendall(self, value):
                self.output += value
        def request(path):
            connection = Request(path)
            server.handler(connection, ('127.0.0.1', 12345), server)
            return connection.output
        self.assertIn(b'200 OK', request('/').splitlines()[0])
        for name in ('/.env', '/files/data/catalog.json', '/files/../tools/demo.py', '/files/%2e%2e/.env'):
            self.assertIn(b'404', request(name).splitlines()[0])
        write(self.root, demo.REPORT_STEM + '.json', '{"predictions": []}')
        self.assertIn(b'404', request('/files/' + demo.REPORT_STEM + '.json').splitlines()[0])

    def test_selected_component_paths_and_incomplete_base(self):
        class Pipeline:
            def __init__(self, complete=True):
                self.calls, self.complete = [], complete
            def identify(self, picture, cfg):
                self.calls.append(('identify', deepcopy(cfg)))
                return {'status': 'ok'}
            def portion(self, picture, identity, cfg):
                self.calls.append(('portion', deepcopy(cfg)))
                return {'status': 'ok' if self.complete else 'failed', 'prediction': {'weight': 10} if self.complete else None}
            def review_codes(self, picture, identity, result, cfg):
                self.calls.append(('D', deepcopy(cfg)))
                return identity, result
            def standard_portions(self, picture, identity, result, cfg):
                self.calls.append(('E', deepcopy(cfg)))
                return result
        for name in ('A', 'B', 'C', 'D', 'E'):
            pipeline = Pipeline()
            cfg = config(name)
            demo.component_inference(pipeline, Path('public.png'), cfg)
            self.assertEqual([value[0] for value in pipeline.calls], ['identify', 'portion'] + ([name] if name in ('D', 'E') else []))
            self.assertTrue(all(value[1] == cfg for value in pipeline.calls))
        for name in ('D', 'E'):
            pipeline = Pipeline(False)
            _, result = demo.component_inference(pipeline, Path('public.png'), config(name))
            self.assertEqual(len(pipeline.calls), 2)
            self.assertTrue(result['method_fallback'])

    def test_asa_legacy_has_no_reference_label_and_examples_disabled(self):
        class Adapter:
            image_path = staticmethod(lambda row: Path(row['image_path']))
            per_dataset = staticmethod(lambda cfg, dataset: cfg)
            def infer_portions(self, pipeline, row, identity, cfg, catalog, **kwargs):
                self.kwargs, self.config = kwargs, cfg
                return {'dataset': row['dataset']}
        class Pipeline:
            def identify_select(self, *args):
                return {'status': 'ok'}
        adapter = Adapter()
        original = {'examples': True}
        row = {'dataset': 'asa24', 'image_path': 'public.png'}
        _, deviation = demo.legacy_inference(adapter, Pipeline(), row, original, {}, self.params['asa24'])
        self.assertIsNone(adapter.kwargs['label'])
        self.assertEqual(adapter.kwargs['examples'], ())
        self.assertFalse(adapter.config['examples'])
        self.assertTrue(original['examples'])
        self.assertIn('method deviation', deviation)

    def test_package_ignores_unlisted_private_paths_without_opening(self):
        write(self.root, '.env', 'DO NOT READ')
        write(self.root, 'runs/row_results.json', '{"sample_id":"private"}')
        write(self.root, 'data/cohorts/dev.jsonl', 'private')
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.name == '.env' or 'cohorts' in path.parts or 'runs' in path.parts:
                raise AssertionError('private read')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            files, result = package.gather(self.root, 'complete')
        self.assertEqual(result['status'], 'READY_CANDIDATE')
        self.assertFalse(any(name.startswith(('runs/', 'data/cohorts/')) or name == '.env' for name in files))
        self.assertTrue(set(package.RESEARCH_SOURCES + package.TEST_FILES) <= set(files))

    def test_unlisted_new_source_requires_explicit_inventory_update(self):
        write(self.root, 'src/new_module.py', '# new source')
        with self.assertRaises(ValueError):
            package.gather(self.root, 'source')

    def test_generic_secret_and_csv_row_scanners(self):
        token = ('s' + 'k-' + 'x' * 30).encode()
        with self.assertRaises(ValueError):
            package.scan_bytes(token, 'README.md')
        with self.assertRaises(ValueError):
            package.scan_bytes(b'OPENAI_API_' + b'KEY=' + b'not-a-placeholder' * 2, 'README.md')
        package.scan_bytes(b'OPENAI_API_' + b'KEY=replace_with_local_value', 'tools/env.example')
        with self.assertRaises(ValueError):
            package.inspect_member('reports/metrics.csv', b'group_id,mae\nprivate,1')
        with self.assertRaises(ValueError):
            package.inspect_member('reports/report.md', ('dish_' + '1234567890').encode())

    def test_docx_embedded_secret_is_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('word/document.xml', 's' + 'k-' + 'x' * 30)
        with self.assertRaises(ValueError):
            package.inspect_member('reports/report.docx', data.getvalue())

    def test_only_exact_aggregate_freeze_provenance_reference_is_allowed(self):
        package.inspect_member('reports/report.md', b'Cohorts: `data/cohorts/dev_freeze.json`.')
        package.inspect_member('reports/report.json', b'{"source_sha256":{"data/cohorts/dev_freeze.json":"abc"}}')
        for private in ('data/cohorts/dev.jsonl', 'data/cohorts/dev_labels.json',
                        'data/cohorts/sealed/validation_labels.json',
                        'data/cohorts/dev_freeze.json/../dev_labels.json',
                        'data/cohorts/dev_freeze.json.bak', 'data/cohorts/dev_freeze.json/child',
                        'data/nutrition5k/validation/images/opaque.png', 'data/asa24/dev/images/opaque.png'):
            with self.assertRaises(ValueError, msg=private):
                package.inspect_member('reports/report.md', private.encode())

    def test_complete_candidate_manifest_and_clean_offline_execution(self):
        output = Path(self.temp.name) / 'candidate'
        result = package.build(self.root, output, 'complete')
        self.assertEqual(result['status'], 'READY_CANDIDATE')
        self.assertEqual(result['review_status'], 'see_review_ledger')
        self.assertEqual(result['publication_status'], 'not_published_by_this_tool')
        archive = output / result['archive']
        self.assertEqual(demo.sha256(archive), result['archive_sha256'])
        clean = Path(self.temp.name) / 'clean'
        with zipfile.ZipFile(archive) as handle:
            manifest = json.loads(handle.read(package.MANIFEST_NAME))
            self.assertEqual(manifest['review_status'], 'see_review_ledger')
            self.assertEqual(manifest['publication_status'], 'not_published_by_this_tool')
            self.assertEqual(set(handle.namelist()), set(manifest['files']) | {package.MANIFEST_NAME})
            for name, item in manifest['files'].items():
                self.assertEqual(hashlib.sha256(handle.read(name)).hexdigest(), item['sha256'])
            handle.extractall(clean)
        check = subprocess.run([sys.executable, '-B', str(clean / 'tools/demo.py'), '--check', '--require-runtime'],
            cwd=clean, capture_output=True, text=True, check=True)
        state = json.loads(check.stdout)
        self.assertEqual(state['status'], 'PASS')
        self.assertEqual(state['api_calls'], 0)
        self.assertEqual(state['mac_execution'], 'not_verified' if sys.platform != 'darwin' else 'offline_check_only')
        self.assertFalse((clean / '.env').exists())
        with self.assertRaises(FileExistsError):
            package.build(self.root, output, 'complete')

    def test_runtime_install_and_immutable_conflict(self):
        output = Path(self.temp.name) / 'source-output'
        package.build(self.root, output, 'source')
        clean = Path(self.temp.name) / 'source-clean'
        with zipfile.ZipFile(output / 'mae-v2-source.zip') as archive:
            archive.extractall(clean)
        self.assertFalse((clean / 'data/catalog.json').exists())
        result = package.install_runtime(clean, output / 'mae-v2-runtime.zip')
        self.assertEqual(result['status'], 'INSTALLED')
        self.assertEqual(demo.check(clean, require_runtime=True)['status'], 'PASS')
        write(clean, 'data/catalog.json', '{}')
        with self.assertRaises(ValueError):
            package.install_runtime(clean, output / 'mae-v2-runtime.zip')

    def test_runtime_archive_tamper_and_traversal_rejected(self):
        output = Path(self.temp.name) / 'source-output'
        package.build(self.root, output, 'source')
        clean = Path(self.temp.name) / 'source-clean'
        with zipfile.ZipFile(output / 'mae-v2-source.zip') as archive:
            archive.extractall(clean)
        bad = output / 'bad.zip'
        with zipfile.ZipFile(bad, 'w') as archive:
            archive.writestr('../escape', 'bad')
        release = {'bytes': bad.stat().st_size, 'sha256': demo.sha256(bad)}
        write(clean, package.RELEASE_NAME, json.dumps(release))
        with self.assertRaises(ValueError):
            package.install_runtime(clean, bad)
        self.assertFalse((clean.parent / 'escape').exists())
        with bad.open('ab') as handle:
            handle.write(b'tamper')
        with self.assertRaises(ValueError):
            package.install_runtime(clean, bad)


if __name__ == '__main__':
    unittest.main()
