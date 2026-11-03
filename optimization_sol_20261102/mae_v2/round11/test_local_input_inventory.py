import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import local_input_inventory as inv


def fixture(*pairs):
    return {'entries': [{'path': p, 'kind': k, **({'bytes': 1} if k == 'file' else {})}
                        for p, k in pairs]}


class Tests(unittest.TestCase):
    def test_pure_projection(self):
        data = fixture(('.tools/a.png', 'file'), ('research/reports/a.png', 'file'), ('my-report/x.jpg', 'file'), ('.git', 'excluded'), ('link', 'symlink_unresolved'))
        data['entries'].append({'kind': 'credential_name_excluded'})
        with patch('builtins.open', side_effect=AssertionError), patch.object(os, 'open', side_effect=AssertionError):
            got = inv.project_paths(data)
        self.assertEqual(got['counts']['entries'], 6)
        self.assertEqual(got['counts']['named_entries'] + got['credential_name_excluded_count'], 6)
        self.assertEqual(got['image_paths'], got['potential_image_paths'])
        self.assertEqual(len(got['image_paths']), 3)
        self.assertFalse(any(got['claims'].values()))
        self.assertEqual(inv.classification('other/.tools/a.png'), 'research_potential')
        self.assertEqual(inv.classification('optimization_sol_20261102/delivery/clean-final/.tools/a.png'), 'dependency')
        self.assertEqual(inv.classification('my-report/x.jpg'), 'research_potential')

    def test_bad_paths(self):
        for path in ('/tmp/a', '../a', 'a/../b', './a', 'a//b', 'a/', 'a\\b', ''):
            with self.subTest(path=path), self.assertRaises(ValueError):
                inv.project_paths(fixture((path, 'file')))
        with self.assertRaises(ValueError):
            inv.project_paths(fixture(('a', 'file'), ('a', 'directory')))
        with self.assertRaises(ValueError):
            inv.project_paths({'entries': [{'kind': 'credential_name_excluded', 'path': '.env'}]})
        for value in (None, True, -1, '5'):
            with self.subTest(size=value), self.assertRaisesRegex(ValueError, 'census_file_size_required'):
                inv.project_paths({'entries': [{'path': 'a.png', 'kind': 'file', 'bytes': value}]})

    def test_links_without_body_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / 'image.png').write_bytes(b'protected')
            (repo / 'labels.csv').write_bytes(b'protected')
            pairs = [('inside', 'image.png'), ('label', 'labels.csv'), ('outside', '/outside/secret'), ('missing', 'absent'), ('chain', 'inside')]
            for name, target in pairs:
                (repo / name).symlink_to(target)
            projected = inv.project_paths(fixture(('image.png', 'file'), *((n, 'symlink_unresolved') for n, _ in pairs)))
            original = os.open
            def directories(path, flags, *args, **kwargs):
                self.assertTrue(flags & os.O_DIRECTORY)
                self.assertTrue(flags & os.O_NOFOLLOW)
                return original(path, flags, *args, **kwargs)
            with patch('builtins.open', side_effect=AssertionError), patch.object(os, 'open', side_effect=directories):
                got = inv.inspect_links(repo, projected)
            self.assertEqual({r['path']: r['status'] for r in got['links']}, {'inside': 'internal_already_covered', 'label': 'internal_uncovered', 'outside': 'outside', 'missing': 'missing', 'chain': 'unresolved'})
            self.assertFalse(any(got['claims'].values()))

    def test_parent_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / 'real').mkdir()
            (repo / 'real/link').symlink_to('../secret')
            (repo / 'alias').symlink_to('real', target_is_directory=True)
            got = inv.inspect_links(repo, inv.project_paths(fixture(('alias/link', 'symlink_unresolved'))))
            self.assertEqual(got['links'][0]['status'], 'unresolved')
            with patch.object(inv.sc, 'same_directory', return_value=False), patch.object(os, 'readlink', side_effect=AssertionError):
                got = inv.inspect_links(repo, inv.project_paths(fixture(('real/link', 'symlink_unresolved'))))
            self.assertEqual(got['links'][0]['status'], 'unresolved')

    def test_control_before_after(self):
        raw = inv.sc.encoded({'status': 'path_census_complete_not_exposure_closure', 'research_file_bodies_opened': 0, 'grants_sampling_download_or_inference': False, 'entries': []})
        with patch.object(inv, 'CENSUS_SHA', inv.sc.sha(raw)), patch.object(inv.sc, 'bounded_read', side_effect=[raw, raw]) as reader:
            inv.load_projected(Path('/synthetic'))
            self.assertEqual(reader.call_count, 2)
        with patch.object(inv, 'CENSUS_SHA', inv.sc.sha(raw)), patch.object(inv.sc, 'bounded_read', side_effect=[raw, b'changed']):
            with self.assertRaises(ValueError):
                inv.load_projected(Path('/synthetic'))


class DependencyGifPolicyTests(unittest.TestCase):
    def test_actual_runtime_child_directories_without_parent_admission(self):
        for root in inv.DEPENDENCY_GIF_LIB_ROOTS:
            for directory in ('Tix8.4.3/bitmaps', 'python3.10/idlelib/Icons',
                              'tk8.6/demos/images', 'tk8.6/images'):
                self.assertTrue(inv.dependency_gif_path(root + directory + '/asset.gif'))
            for directory in ('python3.10/idlelib', 'tk8.6/demos',
                              'python3.10/idlelib/Icons/other', 'tk8.6/demos/images/other'):
                self.assertFalse(inv.dependency_gif_path(root + directory + '/asset.gif'))

    def test_exact_five_roots_and_directories_only(self):
        for root in inv.DEPENDENCY_GIF_LIB_ROOTS:
            for directory in inv.DEPENDENCY_GIF_DIRECTORIES:
                self.assertTrue(inv.dependency_gif_path(root + directory + '/asset.gif'))
                self.assertFalse(inv.dependency_gif_path(root + directory + '/nested/asset.gif'))
                self.assertFalse(inv.dependency_gif_path(root + directory + '/asset.png'))
        for path in ('.tools/other/a.gif', 'research/a.gif',
                     'other/' + inv.DEPENDENCY_GIF_LIB_ROOTS[0] + 'tk8.6/images/a.gif'):
            self.assertFalse(inv.dependency_gif_path(path))
        self.assertEqual(len(inv.DEPENDENCY_GIF_LIB_ROOTS), 5)


if __name__ == '__main__':
    unittest.main()
