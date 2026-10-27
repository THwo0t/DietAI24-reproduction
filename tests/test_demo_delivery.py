"""Delivery acceptance: archived arithmetic, restricted HTTP, bundle and paid-call guards."""
import contextlib
import hashlib
import http.client
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import demo
import runtime_bundle
import live_demo


class TestOfflineDemo(unittest.TestCase):
    def test_saved_measurements_and_hashes(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:demo.check()
        self.assertEqual(json.loads(output.getvalue())['api_calls'],0)

    def test_tampered_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'demo').mkdir();(root/'item.txt').write_text('changed')
            (root/'demo/manifest.json').write_text(json.dumps({'files':{'item.txt':hashlib.sha256(b'original').hexdigest()}}))
            with mock.patch.object(demo,'ROOT',root),self.assertRaisesRegex(ValueError,'changed'):
                demo.check()

    def test_local_http_exposes_only_demo_routes(self):
        server=demo.ThreadingHTTPServer(('127.0.0.1',0),demo.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for path,expected in [('/',200),('/api/results',200),('/.env',404),('/code/config.py',404),
                                  ('/../.env',404),('/demo/images/../../.env',404),('/reports/REPORT.pdf',200)]:
                with self.subTest(path=path):
                    conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
                    conn.request('GET',path);response=conn.getresponse();body=response.read();conn.close()
                    self.assertEqual(response.status,expected)
                    if path=='/api/results':self.assertEqual(json.loads(body)['mode'],'archived_results')
        finally:server.shutdown();server.server_close();thread.join()


class TestRuntimeBundle(unittest.TestCase):
    def archive(self,names,manifest=None):
        content=io.BytesIO()
        with zipfile.ZipFile(content,'w') as archive:
            for name in names:archive.writestr(name,b'example')
            if manifest is not None:archive.writestr('manifest.json',json.dumps(manifest))
        content.seek(0);return zipfile.ZipFile(content)

    def test_paths_cannot_escape_runtime(self):
        for name in ['../outside','/absolute','FNDDS/../../outside','C:\\outside']:
            with self.subTest(name=name),self.archive([name]) as archive,self.assertRaises(ValueError):
                runtime_bundle.safe_members(archive)

    def test_unlisted_entry_is_rejected(self):
        with self.archive(['unexpected'],{'files':{}}) as archive,self.assertRaisesRegex(ValueError,'membership'):
            runtime_bundle.safe_members(archive)

    def test_manifest_and_file_are_verified_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);assets=root/'assets';assets.mkdir();spec=root/'release.json'
            (assets/'manifest.json').write_text('{"files":{}}')
            spec.write_text(json.dumps({'manifest_sha256':hashlib.sha256(b'expected').hexdigest()}))
            with mock.patch.object(runtime_bundle,'ASSETS',assets),mock.patch.object(runtime_bundle,'SPEC',spec),self.assertRaisesRegex(ValueError,'manifest'):
                runtime_bundle.verify_assets()


class TestPaidDemoGuards(unittest.TestCase):
    def test_no_implicit_paid_call(self):
        result=subprocess.run([sys.executable,str(ROOT/'tools/live_demo.py')],capture_output=True,text=True)
        self.assertEqual(result.returncode,2);self.assertIn('--allow-paid',result.stderr)

    def test_invalid_threshold_stops_before_key_or_data(self):
        for value in ['nan','-1','2']:
            with self.subTest(value=value):
                result=subprocess.run([sys.executable,str(ROOT/'tools/live_demo.py'),'--allow-paid','--max-usd',value],capture_output=True,text=True)
                self.assertEqual(result.returncode,2);self.assertIn('positive and at most 1',result.stderr)

    def test_budget_escapes_semantic_exception_retry(self):
        budget=live_demo.Budget(.01,requests=1);budget.before_request()
        with self.assertRaises(live_demo.DemoStop):budget.before_request()
        self.assertEqual(budget.requests,1)
        self.assertFalse(issubclass(live_demo.DemoStop,Exception))


if __name__=='__main__':unittest.main()
