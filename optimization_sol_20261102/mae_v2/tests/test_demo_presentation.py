"""Offline homepage presentation using synthetic aggregate snapshots only."""
from html.parser import HTMLParser
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import demo


def snapshot_fixture(ratio=2):
    targets = {'weight': (58.63, .2028), 'energy': (88.66, .2561), 'fat': (5.213, .2938),
               'carbs': (7.774, .2756), 'protein': (5.044, .2444)}
    metrics = {'passed_checks': 20, 'joint_pass': True, 'datasets': {}}
    thresholds = {}
    for dataset in ('asa24', 'nutrition5k'):
        thresholds[dataset] = {key: {'mae': absolute, 'per_unit': unit} for key, (absolute, unit) in targets.items()}
        metrics['datasets'][dataset] = {'n': 99 if dataset == 'asa24' else 84,
            'groups': 23 if dataset == 'asa24' else 78,
            'primary': {'n': 15 if dataset == 'asa24' else 84, 'metrics': {
                key: {'mae': absolute * ratio, 'per_unit': unit * ratio,
                      'threshold_mae': absolute, 'threshold_per_unit': unit,
                      'pass_mae': True, 'pass_per_unit': True} for key, (absolute, unit) in targets.items()}}}
    metrics['datasets']['asa24'].update(exact_n=15, exact_rate=.99, recognition_pass=True)
    return {'schema_version': 2, 'generated_utc': '2026-11-02T12:00:00+00:00', 'thresholds': thresholds,
            'development': {'status': 'development_targets_not_met', 'metrics': metrics,
                            'profiles': {'asa24': 'asa-retrieval-portion', 'nutrition5k': 'B'}},
            'validation': {'status': 'not_run_or_not_completed', 'metrics': None},
            'unused_big_audit_payload': 'DO_NOT_DUMP_' * 5000}


class Structure(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags, self.links, self.images = [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if tag == 'a':
            self.links.append(attrs.get('href'))
        if tag == 'img':
            self.images.append(attrs)


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mae-v2-presentation-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / (demo.REPORT_STEM + '.json')
        self.path.parent.mkdir(parents=True)
        self.files = {demo.REPORT_STEM + '.json': self.path}
        for relative in demo.REPORTS:
            path = self.root / relative
            path.write_text('synthetic report placeholder')
            self.files[relative] = path
        self.images = [{'dataset': dataset, 'image_path': f'tools/demo_images/{dataset}.png'}
                       for dataset in ('asa24', 'nutrition5k')]

    def render(self, snapshot=None):
        self.path.write_text(json.dumps(snapshot if snapshot is not None else snapshot_fixture()))
        with patch.object(demo, 'public_files', return_value=self.files), patch.object(demo, 'demo_inputs', return_value=self.images):
            return demo.render_page(self.root).decode()

    def test_values_are_readable_and_stored_success_flags_do_not_override_errors(self):
        text = self.render()
        self.assertIn('0 / 20', text)
        self.assertIn('15 / 99', text)
        self.assertIn('15.15% Exact', text)
        self.assertIn('117.26', text)
        self.assertIn('58.63', text)
        self.assertIn('0.4056', text)
        self.assertEqual(text.count('<th scope="row">'), 10)
        self.assertIn('Targets not met', text)
        self.assertIn('Not run or not completed', text)
        self.assertIn('Exact-conditioned', text)
        self.assertIn('not independent validation', text)
        self.assertNotIn('DO_NOT_DUMP_', text)
        self.assertNotIn('<pre', text)

    def test_missing_values_and_zero_population_never_appear_as_passing(self):
        snapshot = snapshot_fixture(.5)
        snapshot['development']['metrics']['datasets']['asa24']['n'] = 0
        snapshot['development']['metrics']['datasets']['nutrition5k']['primary']['metrics']['weight']['mae'] = None
        text = self.render(snapshot)
        self.assertIn('— / 20', text)
        self.assertIn('19 of 20 checks have complete evidence', text)
        self.assertIn('Recognition not assessed', text)
        self.assertIn('Incomplete', text)
        self.assertNotIn('Recognition floor met', text)
        self.assertNotIn('20 / 20', text)

    def test_empty_snapshot_has_unavailable_tables_and_no_success_claim(self):
        text = self.render({})
        self.assertIn('0 of 20 checks have complete evidence', text)
        self.assertIn('Not available', text)
        self.assertNotIn('Within both caps', text)
        self.assertEqual(text.count('<th scope="row">'), 10)

    def test_completed_formal_arm_is_explicit_and_incomplete_formal_does_not_replace_dev(self):
        snapshot = snapshot_fixture()
        snapshot['validation'] = {'status': 'completed', 'metrics': {'optimized': snapshot_fixture(.5)['development']['metrics']}}
        text = self.render(snapshot)
        self.assertIn('20 / 20', text)
        self.assertIn('class="scope-badge">Formal validation', text)
        snapshot['validation']['metrics'] = None
        text = self.render(snapshot)
        self.assertIn('Incomplete aggregate evidence', text)
        self.assertIn('class="scope-badge">Development selection', text)
        self.assertIn('0 / 20', text)

    def test_all_external_labels_and_attributes_are_escaped(self):
        snapshot = snapshot_fixture()
        dangerous = '\"><script>alert(1)</script><img src=x onerror=alert(2)>'
        snapshot['generated_utc'] = dangerous
        snapshot['development']['status'] = dangerous
        snapshot['development']['profiles']['nutrition5k'] = dangerous
        self.images[0]['dataset'] = dangerous
        self.images[0]['image_path'] = 'picture.png" onerror="alert(3)'
        text = self.render(snapshot)
        self.assertNotIn('<script>', text)
        self.assertNotIn('<img src=x', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('&quot;', text)
        parsed = Structure(text)
        self.assertEqual(len(parsed.images), 2)
        self.assertNotIn('script', parsed.tags)
        self.assertTrue(all('onerror' not in image for image in parsed.images))

    def test_downloads_and_images_are_local_and_raw_audit_is_download_only(self):
        text = self.render()
        parsed = Structure(text)
        for suffix in ('.pdf', '.docx', '.md', '.json'):
            self.assertIn('/files/' + demo.REPORT_STEM + suffix, parsed.links)
        self.assertIn('download>Download full aggregate JSON', text)
        self.assertEqual(len(parsed.images), 2)
        self.assertTrue(all(href.startswith('/files/') for href in parsed.links))
        self.assertTrue(all(image['src'].startswith('/files/') for image in parsed.images))
        self.assertNotIn('script', parsed.tags)
        self.assertNotIn('iframe', parsed.tags)

    def test_unavailable_reports_are_not_broken_download_links(self):
        self.files.pop(demo.REPORT_STEM + '.pdf')
        text = self.render()
        self.assertNotIn('/files/' + demo.REPORT_STEM + '.pdf', Structure(text).links)
        self.assertIn('Read PDF · unavailable', text)

    def test_zero_and_close_boundary_use_full_precision(self):
        snapshot = snapshot_fixture(.5)
        metric = snapshot['development']['metrics']['datasets']['nutrition5k']['primary']['metrics']['weight']
        metric['mae'] = 0
        text = self.render(snapshot)
        self.assertIn('Value: 0; cap: 58.63', text)
        self.assertIn('20 / 20', text)
        metric['mae'] = 58.63001
        text = self.render(snapshot)
        self.assertIn('19 / 20', text)
        self.assertIn('Above cap', text)
        self.assertIn('Value: 58.63001; cap: 58.63', text)

    def test_invalid_numbers_do_not_render_nan_or_acceptance(self):
        snapshot = snapshot_fixture(.5)
        metric = snapshot['development']['metrics']['datasets']['asa24']['primary']['metrics']['fat']
        metric['mae'] = float('nan')
        metric['per_unit'] = True
        text = self.render(snapshot)
        self.assertIn('18 of 20 checks have complete evidence', text)
        self.assertNotIn('Value: nan', text)
        self.assertNotIn('20 / 20', text)

    def test_rendering_never_calls_network_credentials_or_inference(self):
        with (patch.object(socket, 'create_connection', side_effect=AssertionError('network access')),
             patch.object(demo, '_local_keys', side_effect=AssertionError('credential access')),
             patch.object(demo, 'live', side_effect=AssertionError('inference'))):
            text = self.render()
        self.assertIn('0 API calls', text)


if __name__ == '__main__':
    unittest.main()
