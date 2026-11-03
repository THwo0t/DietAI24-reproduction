"""Pure captured-byte ASA workbook projection, not an actual audit/entry point.

Only identity fields affect the initial topology. Deferred values remain
private; permitted-code filtering precedes any deferred field validation or
numeric eligibility. A future reviewed reader must authorize the phase and
authenticate the expected source hash. No path or network is opened here.
"""
from dataclasses import dataclass
from decimal import Decimal,InvalidOperation
import hashlib
import io

import openpyxl

from asa_identity import require,sha_value
from asa_content_identity import image_name
from qualification import code8

MAX_WORKBOOK_BYTES=32*1024*1024
MAX_ROWS=1000000
MAX_COLUMNS=128
# The authenticated official AssociatedCodes sheet declares 253072 x 10.
# Bound its complete range without truncating the association graph.
MAX_CELLS=4000000
ASSOCIATED=('FoodCode','Image','ImageType','ModCode','PortionCode','Multiplier')
INVENTORY=('FileName','Portion')


def source_code(value):
    """Accept exact eight-digit identities, never truncate a fractional code."""
    if isinstance(value,str):return code8(value)
    require(type(value) in (int,float,Decimal),'exact_numeric_food_code_required')
    try:number=Decimal(str(value))
    except (InvalidOperation,ValueError):raise ValueError('invalid_numeric_food_code') from None
    require(number.is_finite() and number==number.to_integral_value(),
            'finite_integer_food_code_required')
    return code8(str(int(number)))


def _sheet(book,name,fields):
    require(name in book.sheetnames,'required_metadata_sheet_missing')
    sheet=book[name]
    require(sheet.max_row is not None and sheet.max_column is not None
            and 1<=sheet.max_row<=MAX_ROWS and 1<=sheet.max_column<=MAX_COLUMNS
            and sheet.max_row*sheet.max_column<=MAX_CELLS,'bounded_metadata_sheet_required')
    iterator=sheet.iter_rows();header=next(iterator)
    names=[cell.value for cell in header]
    nonempty=[value for value in names if value is not None]
    require(all(isinstance(value,str) for value in nonempty) and len(nonempty)==len(set(nonempty))
            and set(fields)<=set(nonempty),'unique_required_metadata_headers_required')
    columns={field:names.index(field) for field in fields};rows=[]
    for index,cells in enumerate(iterator,2):
        selected={field:(cells[column].value,cells[column].data_type) for field,column in columns.items()}
        if all(value is None for value,kind in selected.values()):continue
        rows.append((index,selected))
    return rows


@dataclass(frozen=True)
class WorkbookCapture:
    raw:bytes
    source_sha256:str

    def _tables(self):
        require(hashlib.sha256(self.raw).hexdigest()==self.source_sha256,'captured_workbook_changed')
        book=openpyxl.load_workbook(io.BytesIO(self.raw),read_only=True,data_only=False,keep_links=False)
        try:return _sheet(book,'AssociatedCodes',ASSOCIATED),_sheet(book,'ImageFileInventory',INVENTORY)
        finally:book.close()

    @staticmethod
    def _identity(row):
        require(row['FoodCode'][1]!='f' and row['Image'][1]!='f','formula_identity_refused')
        image=image_name(row['Image'][0])
        code=None if row['FoodCode'][0] is None else source_code(row['FoodCode'][0])
        return code,image

    def identity_projection(self):
        associated,inventory=self._tables();pairs=[];names=set();uncoded=0
        for position,row in associated:
            code,image=self._identity(row);names.add(image)
            if code is None:uncoded+=1
            else:pairs.append((code,image))
        for position,row in inventory:
            require(row['FileName'][1]!='f','formula_identity_refused')
            names.add(image_name(row['FileName'][0]))
        require(pairs,'nonempty_metadata_associations_required')
        return {'pairs':pairs,'metadata_images':names,'source_sha256':self.source_sha256}, {
            'associated_source_rows':len(associated),'associated_code_image_rows':len(pairs),
            'associated_uncoded_image_rows':uncoded,'inventory_source_rows':len(inventory),
            'full_metadata_image_names':len(names),'eligibility_evaluated':False,
            'source_or_exposure_completeness_proven':False,'api_calls':0}

    def eligibility_projection(self,permitted_codes):
        """Caller must first prove complete identity isolation; no grant here."""
        permitted={code8(value) for value in permitted_codes}
        associated,inventory=self._tables();metadata=[];images=set();portions=[]
        for position,row in associated:
            code,image=self._identity(row)
            if code not in permitted:continue
            require(all(kind!='f' for value,kind in row.values()),'formula_deferred_field_refused')
            record={key:value for key,(value,kind) in row.items()};record['FoodCode']=code
            metadata.append(record);images.add(image)
        for position,row in inventory:
            require(row['FileName'][1]!='f','formula_identity_refused')
            image=image_name(row['FileName'][0])
            if image not in images:continue
            require(row['Portion'][1]!='f','formula_deferred_field_refused')
            portions.append({key:value for key,(value,kind) in row.items()})
        return {'metadata':metadata,'inventory':portions,'source_sha256':self.source_sha256}


def capture_workbook(raw,expected_sha256):
    expected=sha_value(expected_sha256)
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_WORKBOOK_BYTES,'bounded_workbook_bytes_required')
    require(hashlib.sha256(raw).hexdigest()==expected,'workbook_source_hash_changed')
    capture=WorkbookCapture(raw,expected)
    identity,aggregate=capture.identity_projection()
    return capture,identity,aggregate
