import hashlib
import unittest

import public_manifest as p


class PublicManifestTests(unittest.TestCase):
    def fixture(self):
        raw=b'ID-free count receipt\n';name='round11/evidence/count.json'
        return raw,name,{'file_count':1,'files':{name:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}}

    def test_exact_committed_payload_passes(self):
        raw,name,m=self.fixture()
        self.assertEqual(p.validate(m,{p.PREFIX+name},lambda _:raw)['committed_payloads_verified'],1)

    def test_ignored_working_file_does_not_prove_publication(self):
        raw,name,m=self.fixture();opened=[]
        with self.assertRaisesRegex(ValueError,'payload_missing_from_git'):
            p.validate(m,set(),lambda name:opened.append(name) or raw)
        self.assertEqual(opened,[])

    def test_committed_contents_must_match_not_working_copy(self):
        raw,name,m=self.fixture()
        with self.assertRaisesRegex(ValueError,'committed_blob_drift'):
            p.validate(m,{p.PREFIX+name},lambda _:raw+b'changed')

    def test_count_and_path_validation(self):
        raw,name,m=self.fixture();m['file_count']=2
        with self.assertRaisesRegex(ValueError,'count_mismatch'):p.validate(m,{p.PREFIX+name},lambda _:raw)
        m['file_count']=1;m['files']['../escape']=m['files'].pop(name)
        with self.assertRaisesRegex(ValueError,'noncanonical_path'):p.validate(m,set(),lambda _:raw)


if __name__=='__main__':unittest.main()
