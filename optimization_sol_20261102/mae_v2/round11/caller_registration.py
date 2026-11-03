"""Finite F-through-O source registration, never historical invocation proof.

No source corpus is classified as exposure. Python injection capabilities remain
explicit unresolved boundaries, even where the conservative fixed CLI union is
known. No CLI, scanning, image/label access, provider or action permission.
"""
from copy import deepcopy
from pathlib import Path
import re

import development_identity
import training_identity
from source_census import REPO, PREFIX, bounded_read, sha, require

# Explicit finite paths only. These hashes are new prospective source evidence.
SPECS = (
 ('F', 'n5_core', 'none', 'round3/src/run_round3.py', '97-124', 'run workers/evaluate_only; fixed CLI population'),
 ('G', 'n5_core', 'n5_core', 'round3/src/run_examples.py', '158-176', 'run supplied provider; cross-fold support selection'),
 ('H', 'n5_core', 'n5_core_supervision', 'round3/src/run_catalog.py', '213-238', 'development supervised fold catalogs'),
 ('I', 'n5_core', 'n5_core', 'round3/src/run_visual.py', '519-533', 'G assignments/H catalogs; programmatic estimator calls'),
 ('J_capability', 'training_proposals', 'training_proposals', 'round4/src/capability_probe.py', '64-102', 'probe base/provider_factory/verify_train injection; fixed CLI first13 accepted'),
 ('J_gallery', 'training_proposals', 'training_proposals', 'round4/src/run_base.py', '145-188', 'gallery; load_context base/verifier injection'),
 ('J_original_interrupted', 'n5_core', 'training_proposals', 'round4/src/run_base.py', '192-205', 'pending/stopped original base; no execution claim'),
 ('J_service_continuation', 'n5_core', 'training_proposals', 'round4/continuation/runner.py', '114-139', 'original held stage import and continuation store'),
 ('training_prior_offline', 'training_proposals', 'training_proposals', 'round5/src/run_train_prior.py', '242-253', 'run base override; offline OOF, no paid image caller'),
 ('K_prefix_and_component', 'n5_core', 'training_proposals', 'round5/src/run_component.py', '58-94', 'J continuation prefix import, component supports'),
 ('L_shelved_callable', 'training_proposals', 'training_proposals', 'round6/src/run_pilot.py', '209-228', 'CLI base shelved at259-262; base root/context_loader callable remains'),
 ('M_M0', 'development', 'core_supervision', 'round7/src/run_m.py', '33-156', 'run ctx injection; imports and cross-fold fallback'),
 ('N', 'development', 'core_supervision', 'round8/src/run_n.py', '28-131', 'run ctx injection; pre-review only preflight'),
 ('round9_diagnostic_no_paid_caller', 'development', 'none', 'round9/run_diagnostic.py', '111-164', 'offline completed-N diagnostic; do not invoke label loader'),
 ('O', 'development', 'core_supervision', 'round10/run_o.py', '47-137', 'ctx/ledger/trace/adapter_runner injection and interrupted/completed paths'),
 ('O_conditional_adapter', 'asa_core', 'asa_core_protocol_codes', 'round10/adapter_o.py', '19-33', 'ASA reference code/options protocol condition; no labels opened here'),
)
DEPENDENCIES = (
 'round3/src/examples.py', 'round3/src/direct_estimator.py',
 'round3/src/example_estimator.py', 'round3/src/catalog_estimator.py',
 'round3/src/visual_estimator.py', 'round3/src/dev_ingredients.py',
 'round4/src/context.py', 'round4/src/train_data.py', 'round4/src/pipeline.py',
 'round4/src/retrieval.py', 'round4/src/vision_stages.py',
 'round4/continuation/integrity.py', 'round4/continuation/provider.py',
 'round5/src/component_supports.py', 'round5/src/component_estimator.py',
 'round5/src/component_runtime.py', 'round5/src/verified_j_prefix.py',
 'round5/src/gram_prior.py', 'round6/src/train_context.py',
 'round6/src/atlas_estimator.py', 'round6/src/runtime.py',
 'round7/src/context_m.py', 'round7/src/service_m.py', 'round7/src/runtime_m.py',
 'round7/src/historical_m.py', 'round8/src/context_n.py', 'round8/src/upstream_n.py',
 'round8/src/service_n.py', 'round8/src/runtime_n.py', 'round10/context_o.py',
 'round10/service_o.py', 'round10/runtime_o.py', 'round10/engine_o.py',
 'round10/imports_o.py', 'round10/conditional_o.py', 'round10/launch_o.py',
 'src/pipeline_v2.py', 'src/cohorts_v2.py', 'src/opt_pipeline.py', 'src/opt_provider.py',
 'src/study.py', 'round11/development_identity.py', 'round11/training_identity.py',
 'round11/n5_sources.py', 'round11/source_census.py', 'round11/caller_registration.py')
SOURCE_FILES = tuple(dict.fromkeys(tuple(r[3] for r in SPECS) + DEPENDENCIES))
CALLERS = frozenset(r[0] for r in SPECS)


def _code_pins(repo):
    return {PREFIX + p: sha(bounded_read(repo, PREFIX + p)) for p in SOURCE_FILES}


def _identities(development, training, *, populations):
    require(set(development) == {'n5_core', 'asa_rows', 'source_hashes'},
            'exact_development_projection_required')
    rows = development['asa_rows'] + development['n5_core']['rows']
    expected = {'asa24': populations[0], 'nutrition5k': populations[1]}
    folds = {}
    groups = {'asa24': set(), 'nutrition5k': set()}; ids = {k: set() for k in expected}
    for row in rows:
        require(isinstance(row, dict) and set(row) == development_identity.FIELDS,
                'identity_only_caller_manifest_required')
        dataset = row['dataset']; sample = row['sample_id']
        require(dataset in ids and isinstance(sample, str) and sample.startswith(dataset+'-')
                and sample not in ids[dataset] and row['split'] == 'dev'
                and type(row['fold']) is int and row['fold'] in range(5)
                and isinstance(row['group_id'], str) and row['group_id']
                and isinstance(row['image_path'], str) and row['image_path']
                and training_identity.n5_sources.HEX.fullmatch(row['image_sha256']),
                'registered_caller_development_identity_required')
        name = sha(('dietai24-mae-v2-20261102|sample|'+sample).encode())+'.png'
        require(row['image_path'] == f'data/{dataset}/dev/images/{name}',
                'fixed_caller_development_path_required')
        group = (dataset, row['group_id'])
        require(group not in folds or folds[group] == row['fold'],
                'caller_original_group_fold_changed')
        folds[group] = row['fold']
        ids[dataset].add(sample); groups[dataset].add(row['group_id'])
    require({d:len(v) for d,v in ids.items()} == expected
            and {d:len(v) for d,v in groups.items()} ==
                {'asa24': populations[2], 'nutrition5k': populations[3]},
            'registered_caller_development_population_required')
    proposals = training['protected_proposals_private']; train = set()
    for row in proposals:
        require(set(row) == {'dish_id', 'sample_id', 'screening_component_id',
            'original_component_id', 'recipe_sha256', 'bytes_sha256', 'rgb_sha256',
            'quarantine_reasons', 'protected_training_proposal'}, 'identity_only_training_projection_required')
        require(isinstance(row['dish_id'], str) and training_identity.DISH.fullmatch(row['dish_id'])
                and row['sample_id'] == 'nutrition5k-'+row['dish_id']
                and row['sample_id'] not in train and row['protected_training_proposal'] is True
                and all(training_identity.n5_sources.HEX.fullmatch(row[k])
                    for k in ('recipe_sha256','bytes_sha256','rgb_sha256')),
                'protected_training_proposal_identity_required')
        require(isinstance(row['screening_component_id'], str) and row['screening_component_id']
                and isinstance(row['original_component_id'], str) and row['original_component_id']
                and isinstance(row['quarantine_reasons'], list)
                and all(r in training_identity.REASONS for r in row['quarantine_reasons']),
                'caller_training_component_reason_required')
        train.add(row['sample_id'])
    require(len(train) == populations[4] == training['counts']['protected_training_proposals']
            and training['actual_api_exposure_complete'] is False
            and training['candidate_eligibility_evaluated'] is False
            and training['grants_sampling_download_or_inference'] is False,
            'complete_protected_proposal_envelope_required')
    asa, n5 = ids['asa24'], ids['nutrition5k']
    return {'asa_core': asa, 'n5_core': n5, 'development': asa | n5,
        'training_proposals': train, 'none': set(), 'n5_core_supervision': n5,
        'core_supervision': asa | n5, 'asa_core_protocol_codes': asa}


def _load_at(repo, *, populations=(99,84,23,78,230)):
    """Private synthetic-root/count hook; public entry has no overrides."""
    repo = Path(repo)
    require(repo.is_absolute() and repo.resolve() == repo, 'canonical_caller_root_required')
    code = _code_pins(repo)
    dev, dev_reader = development_identity._load_development_identity(
        repo, development_identity.ANCHORS['development_seal'])
    train, train_reader = training_identity._load_at(repo)
    held_dev, held_train = deepcopy(dev), deepcopy(train)
    def revalidate():
        dev_reader.revalidate(); train_reader.revalidate()
        require(dev == held_dev and train == held_train and _code_pins(repo) == code,
                'caller_held_source_binding_changed')
    revalidate()
    envelope = _identities(dev, train, populations=populations)
    entries = []
    for name,query,support,source,lines,capability in SPECS:
        entries.append({'caller': name, 'source_path': PREFIX+source,
            'source_lines': lines, 'source_sha256': code[PREFIX+source],
            'potential_query_ids_private': sorted(envelope[query]),
            'potential_support_or_supervision_ids_private': sorted(envelope[support]),
            'potential_envelope_is_conservative_superset': True,
            'capability_description': capability,
            'source_proves_historical_invocation': False, 'actual_execution_proven': False,
            'programmatic_injection_disposition': 'unresolved_capability_not_execution',
            'registered_CLI_external_ASA_gallery': 'none_in_this_finite_call_graph'})
    require(len(entries) == len(CALLERS) == 16 and {e['caller'] for e in entries} == CALLERS,
            'complete_finite_caller_table_required')
    revalidate()
    value = {'schema_version': 1, 'status': 'finite_caller_source_registration_unresolved',
        'entries_private': entries, 'source_sha256': code,
        'source_pin_semantics': 'prospective_current_source_not_historical_frozen_invocation',
        'identity_source_sha256': {'development': deepcopy(dev['source_hashes']),
                                  'training': deepcopy(train['source_hashes'])},
        'counts': {'registered_callers': len(entries),
            'potential_development_queries': len(envelope['development']),
            'protected_training_proposals': len(envelope['training_proposals']),
            'ASA_core_supervision': len(envelope['asa_core'])},
        'ASA_core_supervision_ids_private': sorted(envelope['asa_core']),
        'external_ASA_gallery_in_registered_CLI': [],
        'fixed_CLI_identity_union_registered': True,
        'programmatic_override_boundary_resolved': False,
        'actual_api_exposure_complete': False, 'source_association_complete': False,
        'potential_input_coverage_complete': False, 'candidate_eligibility_evaluated': False,
        'grants_sampling_download_or_inference': False, 'new_samples_selected': 0,
        'new_downloads': 0, 'api_calls': 0,
        'pending': ['bounded_project_disposition_of_listed_programmatic_injections',
            'inherited_ASA_training_retired_roles', 'unmatched_local_alias_disposition',
            'historical_invocation_proof_distinct_from_potential_envelope',
            'full_preparation_first_review']}
    return value, _BoundCaller(revalidate)


class _BoundCaller:
    def __init__(self, check): self._check = check
    def revalidate(self): self._check()


def load_caller_registration():
    return _load_at(REPO)
