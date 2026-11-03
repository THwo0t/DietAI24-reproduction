"""Isolated post-coding ASA task adapter; no current portion truth leaves here."""
from copy import deepcopy

from opt_pipeline import _code, validate_options
from opt_provider import fingerprint


def contexts_after_seal(rows, identities, catalog, code_map, coding_proof):
    expected = {r['sample_id'] for r in rows}
    if (not isinstance(coding_proof,dict) or coding_proof.get('complete') is not True
            or coding_proof.get('identity_records_sha256') != fingerprint(identities)
            or set(identities) != expected):
        raise ValueError('O_complete_all_identity_seal_required_before_conditional')
    asa = {r['sample_id'] for r in rows if r['dataset']=='asa24'}
    if set(code_map) != asa:
        raise ValueError('O_conditional_code_population_changed')
    result = {}
    for sid in sorted(asa):
        code = _code(code_map[sid])
        identity = identities[sid]
        if code not in identity.get('final_codes',[]):
            continue
        if identity.get('status') != 'ok':
            raise ValueError('O_failed_identity_contains_conditional_code')
        # Entire code-level catalogue is supplied, never an option chosen using
        # the current label, a size bin, target weight or target nutrients.
        options = validate_options(catalog['asa_options'][code])
        result[sid] = {'code':code,'options':deepcopy(options)}
    return result


def code_only(labels, rows):
    """Call only in the isolated adapter process after the coding proof check."""
    asa = {r['sample_id'] for r in rows if r['dataset']=='asa24'}
    return {sid:_code(labels[sid]['food_code']) for sid in asa}
