#!/usr/bin/env python3
"""One gated zero-API diagnostic. Private witnesses are never a predictor."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROUND = Path(__file__).resolve().parent
BASE = ROUND.parent
sys.path[:0] = [str(ROUND/'runtime/packages'), str(ROUND), str(BASE), str(BASE/'src'),
               str(BASE/'round7/src'), str(BASE/'round8/src'), str(BASE/'round7/tools')]

import numpy as np
import scipy
from joint_lp import TARGETS, OPTIONS, analyze, point_metrics, require
from opt_provider import ROOT, sha, fingerprint
from opt_metrics import THRESHOLDS, nearest_option, option_prediction, _stats
from pipeline_v2 import _flatten
from round4.src.artifacts import ArtifactStore, decode
from context_n import source_pins
from run_n import record_name
from scoring_n import PROFILES, shared_identity, score as score_n
from records_n import validate_leaves
from diagnose_completed_m import require_scored

SCOPE = 'R9_reference_informed_joint_feasibility_not_prediction_or_acceptance'
N_FREEZE = 'e581d24372a4ad1f4d8baf5f0f26e1490242c949368a48cb5107c3165945011d'


def ordered_banks(identity):
    leaves = _flatten(identity['parents'])
    areas = {p['parent_id']: (p['bbox'][2]-p['bbox'][0])*(p['bbox'][3]-p['bbox'][1])
             for p in identity['parents']}
    ordered = sorted(leaves, key=lambda l: (-areas[l['parent_id']], l['parent_id'], l['component_id']))
    banks = identity['candidates']
    require(len(ordered) == len(banks) and {l['component_id'] for l in ordered} == set(banks),
            'candidate_physical_join_changed')
    return [banks[l['component_id']] for l in ordered]


def reachable_in_three(banks, code):
    """Exact existential bound under N's primary-first stable dedup rule."""
    first = next((i for i, bank in enumerate(banks) if code in bank), None)
    if first is None:
        return False
    if first == 0:
        return True
    masks = {}
    for index, bank in enumerate(banks[:first]):
        for c in bank:
            masks[c] = masks.get(c, 0) | (1 << index)
    full = (1 << first) - 1
    values = list(masks.values())
    return any(a == full or any((a | b) == full for b in values) for a in values)


def source_files():
    return {p.relative_to(BASE).as_posix(): sha(p) for p in
            (ROUND/'joint_lp.py', ROUND/'run_diagnostic.py', ROUND/'guarded_run.py', ROUND/'PROTOCOL.md',
             ROUND/'review_gate.json', BASE/'round7/tools/diagnose_completed_m.py')}


def verify_source_freeze(frozen):
    require(frozen['source_files'] == source_files(), 'R9_source_freeze_changed')


def runtime_members(root):
    members = {}
    for prefix, directory in (('package',root), ('native-libs',root.parent/(root.name+'.libs'))):
        for p in sorted(directory.rglob('*')):
            # Wheel test pictures are not executed runtime members. Do not
            # open them even for hashing in this image-free diagnostic.
            if (p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'
                    and p.suffix.lower() not in ('.jpg','.jpeg','.png','.webp','.bmp')):
                members[prefix+'/'+p.relative_to(directory).as_posix()] = sha(p)
    return members


def runtime_manifest():
    require(sys.version_info[:2] == (3,10), 'R9_requires_Python_3_10')
    libraries = {}
    for name, module in (('numpy',np), ('scipy',scipy)):
        root = Path(module.__file__).resolve().parent
        if name == 'scipy':
            require(root == ROUND/'runtime/packages/scipy', 'isolated_solver_not_loaded')
        members = runtime_members(root)
        libraries[name] = {'version':module.__version__, 'members':len(members),
                           'content_sha256':fingerprint(members)}
    wheels = list((ROUND/'runtime/wheels').glob('scipy-1.15.3-*.whl'))
    require(len(wheels) == 1, 'one_pinned_solver_wheel_required')
    return {'python_version':list(sys.version_info[:3]), 'python_sha256':sha(Path(sys.executable).resolve()),
            'libraries':libraries, 'wheel_name':wheels[0].name, 'wheel_sha256':sha(wheels[0])}


def verify_point_statistics(actual, saved):
    # Do not repeat historical bootstrap draws. Every point statistic, count,
    # Exact/size membership aggregate, pass flag and tolerance must reproduce.
    metrics = decode(json.dumps(saved['metrics']))
    for dataset in metrics['datasets'].values():
        dataset.pop('bootstrap',None)
    require(actual['metrics'] == metrics and actual['tolerance'] == saved['tolerance'],
            'N_sealed_predictions_do_not_reproduce_saved_point_statistics')


def label_gate_passed():
    """Read-only instrumentation hook; all scientific checks precede this."""


def load_completed_n():
    """No label open before complete base, score, follower and replay proofs."""
    old = BASE/'round8'
    require_scored(old)
    inputs = {}
    def read(relative):
        path = BASE/relative
        require(path.resolve() == path and not path.is_symlink(), 'symlink_input_rejected')
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        require(relative not in inputs or inputs[relative] == digest, 'input_changed')
        inputs[relative] = digest
        return decode(raw)
    frozen = read('round8/prepared/freeze.json')
    require(inputs['round8/prepared/freeze.json'] == N_FREEZE
            and source_pins() == frozen['source_files']
            and sha(old/'REVIEW.md') == frozen['review_sha256'], 'frozen_N_changed')
    manifest = BASE/'data/cohorts/dev.jsonl'
    rows = [decode(line) for line in manifest.read_text().splitlines()]
    inputs['data/cohorts/dev.jsonl'] = sha(manifest)
    require(inputs['data/cohorts/dev.jsonl'] == frozen['manifest_sha256']
            and fingerprint(rows) == frozen['rows_sha256']
            and Counter(r['dataset'] for r in rows) == {'asa24':99, 'nutrition5k':84}
            and len({r['sample_id'] for r in rows}) == 183, 'full_N_cohorts_required')
    names = [record_name(p, r) for r in rows for p in PROFILES] + ['service-proof']
    store = ArtifactStore(old/'runs/development', frozen, names,
                          verify_sources=lambda: source_pins() == frozen['source_files'], root=old)
    sealed = store.verify_completed()
    read('round8/runs/development/completion.json')
    proof = sealed['service-proof']
    for relative, expected in proof['files'].items():
        path = old/'provider/N'/relative
        require(path.resolve() == path and sha(path) == expected, 'N_service_evidence_changed')
    score = read('round8/runs/scoring/results.json')
    checkpoint = read('round8/development_checkpoint.json')
    require(checkpoint == {k:v for k,v in score.items() if k != 'service_proof'}
            and score['service_proof'] == proof, 'N_full_scores_disagree')
    replay = old/'launch/automatic_verify.log'
    verified = decode(replay.read_text().splitlines()[-1])
    inputs['round8/launch/automatic_verify.log'] = sha(replay)
    require(verified.get('completed_replay') is True and verified.get('provider_constructed') is False
            and verified.get('status') == 'completed' and verified.get('pairs') == 183
            and verified.get('service_counts') == proof['counts'], 'N_zero_Provider_replay_required')
    by_profile = {p:[sealed[record_name(p,r)] for r in rows] for p in PROFILES}
    shared_identity(by_profile)
    imported = read('round8/prepared/upstream.json')
    require(imported['rows'] == rows, 'N_import_population_changed')
    # First development label open is deliberately after all completed-N gates.
    label_gate_passed()
    labels = read('data/cohorts/dev_labels.json')
    require(inputs['data/cohorts/dev_labels.json'] == imported['fallbacks']['labels_sha256']
            and set(labels) == {r['sample_id'] for r in rows}, 'N_label_binding_changed')
    catalog = read('data/catalog.json')
    require(inputs['data/catalog.json'] == frozen['catalog_sha256'], 'N_catalog_changed')
    for profile in PROFILES:
        actual = score_n(rows,labels,by_profile[profile],catalog,bootstrap=0)
        verify_point_statistics(actual,score['arms'][profile])
    return rows, by_profile['N-density'], imported, labels, catalog, inputs, store, sealed


def prepare_n5(rows, records, imported, labels, catalog, candidates=False):
    by_id = {r['sample_id']:r for r in records}
    density, fallbacks, truth = [], [], []
    population = [r for r in rows if r['dataset'] == 'nutrition5k']
    for row in population:
        sid = row['sample_id']; record = by_id[sid]
        truth.append([labels[sid]['truth'][k] for k in TARGETS])
        if record['fallback']:
            require(record['identity_status'] == 'failed' and not record['raw_leaves'],
                    'unexpected_N_failure_population')
            density.append([]); fallbacks.append([record['prediction'][k] for k in TARGETS])
            continue
        validate_leaves({'status':record['identity_status'], 'leaves':record['items']},
                        {'raw_leaves':record['raw_leaves'], 'prediction':record['prediction']})
        if candidates:
            old_identity = imported['records'][sid]['identity']
            banks = ordered_banks(old_identity)
            d = [[1.0]+[catalog['foods'][code]['density'][k]/100 for k in TARGETS[1:]]
                 for bank in banks for code in bank]
        else:
            d = [[1.0]+[leaf['density'][k]/100 for k in TARGETS[1:]] for leaf in record['raw_leaves']]
        density.append(d); fallbacks.append(None)
    require(len(population) == 84 and sum(v is not None for v in fallbacks) == 4,
            'N5_84_with_four_fixed_fallbacks_required')
    return density, fallbacks, np.asarray(truth, dtype=float)


def asa_bounds(rows, records, imported, labels, catalog):
    by_id = {r['sample_id']:r for r in records}
    asa = [r for r in rows if r['dataset'] == 'asa24']
    populations = {k:[] for k in ('current_exact', 'candidate', 'top_three', 'primary')}
    refs, predictions = [], []
    for row in asa:
        sid = row['sample_id']; code = labels[sid]['food_code']
        banks = ordered_banks(imported['records'][sid]['identity'])
        if any(code in b for b in banks): populations['candidate'].append(row)
        if reachable_in_three(banks, code): populations['top_three'].append(row)
        if code in banks[0]: populations['primary'].append(row)
        if code not in by_id[sid]['final_codes']:
            continue
        populations['current_exact'].append(row)
        option = nearest_option(labels[sid]['truth']['weight'], catalog['asa_options'][code])
        predictions.append(option_prediction(option, catalog['foods'][code]['density']))
        refs.append(labels[sid])
    require(len(asa) == 99 and len(refs) == 10, 'fixed_ASA_Exact_population_required')
    stats = _stats(refs, predictions, 'asa24')
    return {'recognition': {name:{'n':len(v), 'groups':len({r['group_id'] for r in v}),
              'fraction_of_all_99':len(v)/99, 'guard15_pass':len(v)>=15}
              for name,v in populations.items()},
            'fixed_exact_quantity_oracle': stats,
            'failed_checks': sum(not v[k] for v in stats['metrics'].values()
                                 for k in ('pass_mae','pass_per_unit')),
            'reference_informed_nearest_legal_option_not_prediction': True,
            'exact_population_chosen_from_frozen_N_codes': True}


def run(*, execution_boundary=None):
    require(not (ROUND/'diagnostics/joint/completion.json').exists(),
            'R9_already_completed_use_existing_evidence')
    require(callable(execution_boundary), 'R9_use_guarded_network_isolated_entrypoint')
    execution_boundary()
    gate = decode((ROUND/'review_gate.json').read_bytes())
    require(gate.get('status') == 'approved_or_fixed' and gate.get('unresolved_p1_p2') == 0
            and sha(ROUND/'REVIEW.md') == gate['review_sha256'], 'R9_review_gate_required')
    frozen = decode((ROUND/'prepared/freeze.json').read_bytes())
    verify_source_freeze(frozen)
    require(frozen['review_sha256'] == gate['review_sha256'],
            'R9_source_freeze_changed')
    require(np.__version__ == '1.26.4' and scipy.__version__ == '1.15.3'
            and runtime_manifest() == frozen['runtime'], 'R9_runtime_version_or_content_changed')
    rows, records, imported, labels, catalog, inputs, parent_store, sealed = load_completed_n()
    density, fallbacks, truth = prepare_n5(rows, records, imported, labels, catalog)
    fixed, witness = analyze(density, fallbacks, truth, THRESHOLDS['nutrition5k'])
    out = {'schema_version':1, 'scope':SCOPE, 'fixed_N_density':fixed,
           'asa24':asa_bounds(rows, records, imported, labels, catalog),
           'api_calls':0, 'validation_opened':False, 'images_opened':False,
           'original_N_point_statistics_reproduced':list(PROFILES), 'new_bootstrap_replicates':0,
           'new_predictor_selected':False, 'oracle_witness_exported':False,
           'runtime':frozen['runtime'], 'solver_method':'highs-ds', 'solver_options':OPTIONS}
    witnesses = {'fixed_N_density':witness}
    if fixed['classification'] == 'verified_numerical_negative':
        density, fallbacks, truth = prepare_n5(rows, records, imported, labels, catalog, candidates=True)
        cone, value = analyze(density, fallbacks, truth, THRESHOLDS['nutrition5k'])
        out['candidate_cone_fixed_failures'] = cone; witnesses['candidate_cone_fixed_failures'] = value
    else:
        out['candidate_cone_fixed_failures'] = {'status':'skipped', 'reason':fixed['classification']}
    out['failure_relaxed_C_witness'] = {'status':'not_recomputed',
        'reason':'Earlier C uses a different representation; no unverified containment claim.'}
    out['fallback_error_budget'] = {}
    for j,k in enumerate(TARGETS):
        absolute_sum = sum(abs(v[j]-t[j]) for v,t in zip(fallbacks,truth) if v is not None)
        ref = sum(float(t[j])/84 for t in truth)
        out['fallback_error_budget'][k] = {'fixed_absolute_error_sum':float(absolute_sum),
            'fraction_of_absolute_cap_budget':float(absolute_sum/(84*THRESHOLDS['nutrition5k'][k][0])),
            'fraction_of_per_unit_cap_budget':float(absolute_sum/(84*ref*THRESHOLDS['nutrition5k'][k][1]))}
    binding = {'scope':SCOPE, 'source_files':source_files(), 'inputs':inputs,
               'R9_freeze_sha256':sha(ROUND/'prepared/freeze.json')}
    def unchanged():
        return source_files() == frozen['source_files'] and all(sha(BASE/p)==h for p,h in inputs.items())
    require(unchanged() and parent_store.verify_completed() == sealed, 'N_or_diagnostic_inputs_changed')
    out['provenance_sha256'] = fingerprint(binding)
    store = ArtifactStore(ROUND/'diagnostics/joint', binding, ['aggregate','private-witness'],
                          verify_sources=unchanged, root=ROUND)
    payload = {'aggregate':out, 'private-witness':witnesses}
    store.finalize(payload)
    require(store.verify_completed() == payload, 'R9_seal_changed')
    return out


if __name__ == '__main__':
    print(json.dumps({'status':'R9_direct_execution_refused', 'entrypoint':'guarded_run.py'}))
    raise SystemExit(1)
