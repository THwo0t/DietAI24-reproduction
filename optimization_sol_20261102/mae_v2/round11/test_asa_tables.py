import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import asa_tables as t
from asa_eligibility import legal_rows


def digest(raw):return hashlib.sha256(raw).hexdigest()


class TableTests(unittest.TestCase):
    def test_membership_reads_only_exact_code_column_and_accepts_bom_index_and_extra_text(self):
        raw=b'\xef\xbb\xbf,Food code,description\n0,11111111,non-numeric text\n1,11111111,another\n2,22222222,POISON\n'
        private,aggregate=t.code_membership(raw,digest(raw))
        self.assertEqual(private['codes'],{'11111111','22222222'})
        self.assertEqual(aggregate['source_rows'],3)
        self.assertFalse(aggregate['numerical_targets_interpreted'])

    def test_protected_bad_weight_fields_are_not_converted_or_exported(self):
        raw=b'Food Code,Portion Code,Portion Weight\n11111111,1,5\n22222222,POISON,POISON\n'
        private,aggregate=t.weight_projection(raw,digest(raw),['11111111'])
        self.assertEqual(private['food_weights'],[{'Food Code':'11111111','Portion Code':'1','Portion Weight':'5'}])
        self.assertNotIn('POISON',str(private));self.assertEqual(aggregate['permitted_weight_rows'],1)

    def test_zero_positive_key_conflict_survives_projection_and_refuses_in_legal_stage(self):
        for weights in [('0','10'),('10','0')]:
            raw=('Food Code,Portion Code,Portion Weight\n'
                 +''.join(f'11111111,1,{v}\n' for v in weights)).encode()
            private,_=t.weight_projection(raw,digest(raw),['11111111'])
            self.assertEqual(len(private['food_weights']),2)
            with self.assertRaisesRegex(ValueError,'conflicting_exact_food_weight'):
                legal_rows([],[],private['food_weights'],permitted_codes=['11111111'],
                           fndds_codes=['11111111'],top_codes=['11111111'],image_hashes={})

    def test_wrong_pin_refuses_before_csv_parser(self):
        with patch.object(t.csv,'DictReader',side_effect=AssertionError('no parser')):
            with self.assertRaisesRegex(ValueError,'source_hash'):
                t.code_membership(b'Food code\n11111111\n','f'*64)

    def test_duplicate_missing_columns_extra_fields_and_broken_quotes_refuse(self):
        for raw,code in [(b'Food code,Food code\n11111111,22222222\n','headers'),
                         (b'Food Code\n11111111\n','headers'),
                         (b'Food code,description\n11111111\n','field_count'),
                         (b'Food code\n11111111,extra\n','field_count'),
                         (b'Food code\n"11111111\n','decode_failed')]:
            with self.subTest(raw=raw),self.assertRaisesRegex(ValueError,code):
                t.code_membership(raw,digest(raw))

    def test_fractional_nonfinite_and_boolean_looking_codes_are_not_coerced(self):
        for value in ('11111111.5','NaN','True','11111111.0'):
            raw=f'Food code\n{value}\n'.encode()
            with self.subTest(value=value),self.assertRaises(ValueError):t.code_membership(raw,digest(raw))


if __name__=='__main__':unittest.main()
