"""Pure captured-byte membership/weight CSV projection for future ASA prep.

No paths, phase permissions, code selection, numeric weight interpretation or
inference. Only the later isolated reader may authenticate and supply real
sources. Protected-code deferred fields are not exported or converted.
"""
import csv
import hashlib
import io

from asa_identity import require,sha_value
from asa_workbook import source_code
from qualification import code8

MAX_TABLE_BYTES=32*1024*1024
MAX_TABLE_ROWS=1000000


def _rows(raw,expected_sha256,required):
    expected=sha_value(expected_sha256)
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_TABLE_BYTES,'bounded_csv_bytes_required')
    require(hashlib.sha256(raw).hexdigest()==expected,'csv_source_hash_changed')
    try:
        source=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''),strict=True)
        header=source.fieldnames
        require(header is not None and len(header)==len(set(header)) and set(required)<=set(header),
                'unique_required_csv_headers_required')
        rows=[]
        for row in source:
            require(None not in row and all(value is not None for value in row.values()),
                    'csv_field_count_mismatch')
            if not any(value for value in row.values()):continue
            require(len(rows)<MAX_TABLE_ROWS,'csv_row_count_bound_exceeded')
            rows.append({key:row[key] for key in required})
        return rows,expected
    except (UnicodeError,csv.Error):
        raise ValueError('csv_decode_failed') from None


def code_membership(raw,expected_sha256):
    rows,digest=_rows(raw,expected_sha256,['Food code'])
    codes={source_code(row['Food code']) for row in rows}
    require(codes,'nonempty_food_code_membership_required')
    return {'codes':codes,'source_sha256':digest},{'source_rows':len(rows),'unique_codes':len(codes),
        'numerical_targets_interpreted':False,'source_or_phase_authorized':False,'api_calls':0}


def weight_projection(raw,expected_sha256,permitted_codes):
    rows,digest=_rows(raw,expected_sha256,['Food Code','Portion Code','Portion Weight'])
    permitted={code8(value) for value in permitted_codes};selected=[]
    for row in rows:
        code=source_code(row['Food Code'])
        if code not in permitted:continue
        selected.append({**row,'Food Code':code})
    # Keep duplicates and zero mappings; legal_rows must detect exact-key
    # conflicts before sentinel exclusion. No premature dict or float cast.
    return {'food_weights':selected,'source_sha256':digest},{'source_rows':len(rows),
        'permitted_weight_rows':len(selected),'numerical_targets_interpreted':False,
        'source_or_phase_authorized':False,'api_calls':0}
