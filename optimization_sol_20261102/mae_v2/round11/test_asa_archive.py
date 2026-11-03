import hashlib
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import asa_archive as a
import asa_content_identity as c
from test_asa_content_identity import png,roles


class ArchiveTests(unittest.TestCase):
    def write(self,root,entries):
        path=root/a.RELATIVE;path.parent.mkdir(parents=True,exist_ok=True)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(path,'w') as archive:
                for name,raw in entries:archive.writestr(name,raw)
        return path,hashlib.sha256(path.read_bytes()).hexdigest()

    def test_all_pngs_including_unassociated_members_enter_content_graph(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);raw=png();_,digest=self.write(root,[('folder/a.PNG',raw),
                ('unassociated/copy.png',png(level=9,text='copy')),('readme.txt',b'notice')])
            private,aggregate=a.capture_archive(root,digest)
            self.assertEqual(aggregate['png_members'],2);self.assertEqual(aggregate['other_members'],1)
            protected=roles();protected['history']['images']={'copy.png'}
            graph,summary=c.build_asa_content_inventory([('11111111','a.PNG')],
                private['image_fingerprints'],protected,metadata_images=['a.PNG'],
                unknown_byte_images=[],unknown_pixel_images=[])
            self.assertEqual(graph['node_groups']['c:11111111'],graph['node_groups']['i:copy.png'])
            self.assertFalse(summary['external_source_completeness_proven'])
            self.assertFalse(aggregate['metadata_coverage_proven'])
            self.assertNotIn('copy.png',str(aggregate))

    def test_duplicate_members_are_read_by_zipinfo_and_conflicts_refuse(self):
        for same in (True,False):
            with self.subTest(same=same),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);_,digest=self.write(root,[('a.png',png()),
                    ('a.png',png() if same else png((9,8,7)))])
                if same:
                    private,aggregate=a.capture_archive(root,digest)
                    self.assertEqual(aggregate['duplicate_basename_members'],1)
                    self.assertEqual([r['member_index'] for r in private['members']],[0,1])
                else:
                    with self.assertRaisesRegex(ValueError,'basename_content'):
                        a.capture_archive(root,digest)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,digest=self.write(root,[('x/a.png',png()),('y/a.png',png(level=9))])
            with self.assertRaisesRegex(ValueError,'basename_content'):
                a.capture_archive(root,digest)

    def test_wrong_pin_refuses_before_decoder(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.write(root,[('a.png',png())])
            with patch.object(a,'png_fingerprint',side_effect=AssertionError('decoder must not run')):
                with self.assertRaisesRegex(ValueError,'source_hash'):
                    a.capture_archive(root,'f'*64)

    def test_member_paths_and_symlink_members_refuse_without_extraction(self):
        for name in ('../a.png','/a.png','x/../a.png','x\\a.png','x//a.png','bad\n/a.png'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);_,digest=self.write(root,[(name,png())])
                with self.assertRaisesRegex(ValueError,'unsafe_archive_member'):
                    a.capture_archive(root,digest)
                self.assertFalse((root/'a.png').exists())
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);link=zipfile.ZipInfo('link.png');link.create_system=3
            link.external_attr=(stat.S_IFLNK|0o777)<<16
            _,digest=self.write(root,[(link,b'elsewhere')])
            with self.assertRaisesRegex(ValueError,'member_type'):
                a.capture_archive(root,digest)

    def test_fixed_archive_file_and_parent_symlinks_refuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,digest=self.write(root,[('a.png',png())])
            real=path.with_name('real.zip');path.rename(real);path.symlink_to(real)
            with self.assertRaisesRegex(ValueError,'linked_archive'):
                a.capture_archive(root,digest)
            path.unlink();real.rename(path);folder=root/'actual';path.parent.rename(folder)
            (root/'ASA24').symlink_to(folder,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'linked_archive'):
                a.capture_archive(root,digest)

    def test_same_size_mtime_restoration_during_capture_does_not_hide_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,digest=self.write(root,[('a.png',png())]);before=path.stat()
            original=a.png_fingerprint
            def mutate(raw):
                result=original(raw);data=bytearray(path.read_bytes());data[-1]^=1
                path.write_bytes(data)
                import os
                os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
                return result
            with patch.object(a,'png_fingerprint',side_effect=mutate):
                with self.assertRaisesRegex(ValueError,'changed_during_capture'):
                    a.capture_archive(root,digest)

    def test_member_crc_and_registered_size_or_count_bounds_refuse_before_partial_return(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);raw=png();path,_=self.write(root,[('a.png',raw)])
            damaged=bytearray(path.read_bytes());offset=damaged.index(raw);damaged[offset+len(raw)//2]^=1
            path.write_bytes(damaged)
            with self.assertRaisesRegex(ValueError,'archive_or_member_decode_failed'):
                a.capture_archive(root,hashlib.sha256(damaged).hexdigest())
            _,digest=self.write(root,[('a.png',raw),('b.png',raw)])
            for limit,code in [('MAX_MEMBERS','member_count'),('MAX_BYTES','member_size')]:
                with self.subTest(limit=limit),patch.object(a,limit,1),\
                     patch.object(a,'png_fingerprint',side_effect=AssertionError('no decoder')):
                    with self.assertRaisesRegex(ValueError,code):a.capture_archive(root,digest)

    def test_corrupt_or_unsupported_png_member_fails_whole_capture(self):
        for raw in (b'not PNG',png()[:-12],png((1,2,3,255),mode='RGBA')):
            with self.subTest(length=len(raw)),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);_,digest=self.write(root,[('a.png',raw)])
                with self.assertRaises(ValueError):a.capture_archive(root,digest)

    def test_only_fixed_local_archive_and_no_png_or_bad_archive_refuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,digest=self.write(root,[('readme.txt',b'notice')])
            with self.assertRaisesRegex(ValueError,'nonempty_png'):
                a.capture_archive(root,digest)
            raw=b'not a ZIP';path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'decode_failed'):
                a.capture_archive(root,hashlib.sha256(raw).hexdigest())


if __name__=='__main__':unittest.main()
