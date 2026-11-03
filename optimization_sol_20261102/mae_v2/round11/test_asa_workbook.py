import hashlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import openpyxl

sys.path.insert(0,str(Path(__file__).resolve().parent))
import asa_workbook as w
from asa_content_identity import build_asa_content_inventory
from test_asa_content_identity import fp,roles,png
from asa_eligibility import legal_rows


def workbook(rows=None,inventory=None,*,associated_header=None,inventory_header=None):
    book=openpyxl.Workbook();associated=book.active;associated.title='AssociatedCodes'
    associated.append(list(w.ASSOCIATED) if associated_header is None else associated_header)
    for row in ([[11111111,'a.png','PORTION',0,98,10]] if rows is None else rows):associated.append(row)
    sheet=book.create_sheet('ImageFileInventory')
    sheet.append(list(w.INVENTORY) if inventory_header is None else inventory_header)
    for row in ([['a.png','small']] if inventory is None else inventory):sheet.append(row)
    stream=io.BytesIO();book.save(stream);book.close();return stream.getvalue()


def capture(raw):return w.capture_workbook(raw,hashlib.sha256(raw).hexdigest())


class WorkbookTests(unittest.TestCase):
    @staticmethod
    def sparse_large_workbook(last_row):
        book=openpyxl.load_workbook(io.BytesIO(workbook(rows=[],inventory=[['tail.png','small']])))
        sheet=book['AssociatedCodes'];sheet.cell(1,10,'ignored_field')
        for column,value in enumerate([11111111,'tail.png','SIZE',9,'POISON','POISON'],1):
            sheet.cell(last_row,column,value)
        stream=io.BytesIO();book.save(stream);book.close();return stream.getvalue()

    def test_registered_official_geometry_retains_the_last_identity_row(self):
        raw=self.sparse_large_workbook(253072)
        try:
            _,identity,aggregate=capture(raw)
        except ValueError as exc:
            if str(exc)=='bounded_metadata_sheet_required':
                self.fail('registered official geometry was refused before its final identity row')
            raise
        self.assertEqual(identity['pairs'],[('11111111','tail.png')])
        self.assertEqual(aggregate['associated_source_rows'],1)
        self.assertNotIn('POISON',str(identity))

    def test_larger_than_registered_bound_still_refuses_before_iteration(self):
        raw=self.sparse_large_workbook(400001)
        with self.assertRaisesRegex(ValueError,'bounded_metadata_sheet_required'):
            capture(raw)

    def test_all_types_modified_codes_and_uncoded_orphan_inventory_names_remain(self):
        rows=[[11111111,'a.png','PORTION',0,98,10],
              [22222222,'size.png','SIZE',9,'POISON','POISON'],
              [33333333,'modified.png','PORTION',8,'POISON','POISON'],
              [None,'uncoded.png','SIZE',0,'POISON','POISON']]
        obj,identity,aggregate=capture(workbook(rows,[['a.png','small'],['orphan.png','POISON']]))
        self.assertEqual(identity['pairs'],[('11111111','a.png'),('22222222','size.png'),
                                            ('33333333','modified.png')])
        self.assertEqual(identity['metadata_images'],{'a.png','size.png','modified.png','uncoded.png','orphan.png'})
        self.assertEqual(aggregate['associated_uncoded_image_rows'],1)
        self.assertFalse(aggregate['eligibility_evaluated'])

    def test_size_and_modification_edges_link_core_validation_before_numeric_filtering(self):
        rows=[[11111111,'a.png','PORTION',0,98,10],
              [11111111,'bridge.png','SIZE',5,'POISON','POISON'],
              [22222222,'bridge.png','PORTION',9,'POISON','POISON']]
        _,identity,_=capture(workbook(rows,[['a.png','small'],['bridge.png','POISON']]))
        protected=roles();protected['core']['codes']={'11111111'}
        protected['validation']['codes']={'22222222'}
        private,aggregate=build_asa_content_inventory(identity['pairs'],[fp('a.png'),fp('bridge.png',png((9,8,7)))],
            protected,metadata_images=identity['metadata_images'],unknown_byte_images=[],unknown_pixel_images=[])
        self.assertEqual(aggregate['observed_protected_intersections']['core__validation'],1)

    def test_only_permitted_deferred_values_are_exported_and_original_legal_mapping_runs(self):
        rows=[[11111111,f'{index}.png','PORTION',0,98,grams]
              for index,grams in enumerate((10,20,30))]
        rows.append([22222222,'protected.png','PORTION','POISON','=1/0','=1/0'])
        inventory=[[f'{index}.png',f'portion {index}'] for index in range(3)]
        inventory.append(['protected.png','=1/0'])
        obj,_,_=capture(workbook(rows,inventory));projected=obj.eligibility_projection(['11111111'])
        result,aggregate=legal_rows(projected['metadata'],projected['inventory'],[],
            permitted_codes=['11111111'],fndds_codes=['11111111'],top_codes=['11111111'],
            image_hashes={f'{index}.png':str(index) for index in range(3)})
        self.assertEqual([float(row['Weight']) for row in result['rows']],[10,20,30])
        self.assertNotIn('protected.png',str(projected));self.assertNotIn('POISON',str(projected))
        with self.assertRaisesRegex(ValueError,'deferred_field'):
            obj.eligibility_projection(['22222222'])

    def test_duplicate_inventory_rows_are_preserved_until_eligible_conflict_check(self):
        obj,identity,_=capture(workbook(inventory=[['a.png','small'],['a.png','large']]))
        projected=obj.eligibility_projection(['11111111'])
        self.assertEqual(len(projected['inventory']),2)
        with self.assertRaisesRegex(ValueError,'conflicting_inventory'):
            legal_rows(projected['metadata'],projected['inventory'],[],permitted_codes=['11111111'],
                       fndds_codes=['11111111'],top_codes=['11111111'],image_hashes={'a.png':'a'})

    def test_numeric_code_must_be_exact_finite_integer_with_eight_digits(self):
        for value in (11111111,11111111.,'11111111'):
            self.assertEqual(w.source_code(value),'11111111')
        for value in (True,11111111.5,float('nan'),float('inf'),123,'11111111.0',' 11111111'):
            with self.subTest(value=str(value)),self.assertRaises(ValueError):w.source_code(value)

    def test_pin_mismatch_refuses_before_workbook_parser(self):
        with patch.object(w.openpyxl,'load_workbook',side_effect=AssertionError('no parser')):
            with self.assertRaisesRegex(ValueError,'source_hash'):
                w.capture_workbook(workbook(),'f'*64)

    def test_identity_formulas_missing_images_unsafe_names_and_headers_refuse(self):
        for change,code in [({'rows':[['=11111111','a.png','PORTION',0,98,10]]},'formula_identity'),
                            ({'rows':[[11111111,None,'PORTION',0,98,10]]},'image_basename'),
                            ({'rows':[[11111111,'x/a.png','PORTION',0,98,10]]},'image_basename'),
                            ({'rows':[[11111111,'a\n.png','PORTION',0,98,10]]},'control_character'),
                            ({'associated_header':['FoodCode','Image','Image','ModCode','PortionCode','Multiplier']},'headers')]:
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,code):capture(workbook(**change))

    def test_identity_and_projections_are_new_objects_not_mutable_cached_authorizations(self):
        obj,identity,_=capture(workbook());identity['pairs'].clear();identity['metadata_images'].clear()
        first=obj.eligibility_projection(['11111111']);first['metadata'][0]['Multiplier']=999
        self.assertEqual(obj.identity_projection()[0]['pairs'],[('11111111','a.png')])
        self.assertEqual(obj.eligibility_projection(['11111111'])['metadata'][0]['Multiplier'],10)
        self.assertEqual(obj.eligibility_projection([])['metadata'],[])


if __name__=='__main__':unittest.main()
