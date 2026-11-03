"""Pure finite available-source disposition; no eligibility or action grants.

Consumes existing identity projections, not files. Receipt hashes below name the
registered external evidence; checking a supplied hash is NOT authentication.
A reviewed outer reader must authenticate/revalidate those bytes and identities.
The original global guard stays stopped and its false closure flags stay false.
"""
from copy import deepcopy
import re

from asa_phase_graph import _build_phase_graph
from asa_content_identity import ALGORITHM,ANCHOR_TYPES
from asa_identity import ROLES,require,sha_value
from source_capture import plain
from caller_registration import CALLERS,SPECS,_identities
from n5_sources import PATHS
from lineage_pool_v3 import BASE_FIELDS,OVERLAY_FIELDS

PREFIX='optimization_sol_20261102/mae_v2/'
INVENTORY=PREFIX+'round11/preparation/source_inventory/source_inventory.json'
AUDIT=PREFIX+'round11/preparation/source_role_audit/source_role_audit.json'
PINS={'inventory':'203bbb7c9f26f2bf6a4bf3846151fe068c3399f61efbb3f1a0b41c830dc9892d',
      'audit':'075931a1172269c1ed998ca06f686d99b7a5fa1bd7bda387d02c3270a82971e7'}
COUNTS={'asa_core':99,'n5_core':84,'asa_core_groups':23,'n5_core_groups':78,'training':230,
        'asa_validation':78,'asa_validation_groups':23,'legacy_reserved':200,
        'local':3168,'n5_local':1282,'asa_local':1638,'unassigned':248,
        'dependency':213,'rendered_evidence':26,'research_potential':9,'unresolved_links':10,
        'missing_names':114,'missing_components':18,'core_validation_components':1,'affected_validation':3}
NO_GRANTS=('actual_api_exposure_complete','candidate_eligibility_evaluated','grants_sampling_download_or_inference')


def _false_claims(value):
    for key in NO_GRANTS:
        require(value.get(key) is False,'false_closure_and_action_flags_required')
    for key in ('source_association_complete','potential_input_coverage_complete',
                'supplied_byte_closure_complete','supplied_pixel_closure_complete',
                'global_supplied_byte_closure_complete','global_supplied_pixel_closure_complete',
                'source_completeness_proven','latest_exposure_completeness_proven'):
        if key in value:require(value[key] is False,'global_closure_must_remain_false')
    for key in ('new_samples_selected','new_downloads','api_calls'):
        if key in value:require(type(value[key]) is int and value[key]==0,'zero_action_counts_required')


def _anchors_union(*roles):
    return {k:sorted(set().union(*(set(r[k]) for r in roles))) for k in ANCHOR_TYPES}


def _disposition(mechanical,asa_audit,callers,training,local_disposition,repair_registration,*,counts,pins):
    require(set(counts)==set(COUNTS) and all(type(v) is int and v>=0 for v in counts.values()),'registered_finite_counts_required')
    require(set(pins)==set(PINS) and all(sha_value(v) for v in pins.values()),'registered_receipt_bindings_required')
    for value in (mechanical,asa_audit,callers,training,local_disposition):_false_claims(value)
    require(mechanical.get('original_linkage_guard_remains_stopped') is True and
            asa_audit.get('inventory_sha256')==pins['inventory'],'fixed_mechanical_inventory_binding_required')
    require(local_disposition.get('input_sha256',{}).get(INVENTORY)==pins['inventory'] and
            local_disposition['input_sha256'].get(AUDIT)==pins['audit'],'fixed_local_disposition_inputs_required')
    require(callers.get('fixed_CLI_identity_union_registered') is True and
            callers.get('programmatic_override_boundary_resolved') is False and
            callers.get('external_ASA_gallery_in_registered_CLI')==[], 'finite_source_callers_not_invocations_required')
    development=mechanical['development_identity']
    require(callers['identity_source_sha256']=={'development':development['source_hashes'],
            'training':training['source_hashes']},'caller_identity_source_bindings_changed')
    for key,h in mechanical['n5_source_sha256'].items():
        require(key in PATHS and training['source_hashes'].get(PATHS[key])==h,'mechanical_training_identity_source_changed')
    envelopes=_identities(development,training,populations=(counts['asa_core'],counts['n5_core'],
        counts['asa_core_groups'],counts['n5_core_groups'],counts['training']))
    entries=callers['entries_private'];require(type(entries) is list and len(entries)==16 and
        {e['caller'] for e in entries}==CALLERS,'all_sixteen_registered_callers_required')
    specs={s[0]:s for s in SPECS}
    for entry in entries:
        spec=specs[entry['caller']]
        require(entry['potential_query_ids_private']==sorted(envelopes[spec[1]]) and
                entry['potential_support_or_supervision_ids_private']==sorted(envelopes[spec[2]]) and
                entry['potential_envelope_is_conservative_superset'] is True and
                entry['source_proves_historical_invocation'] is False and entry['actual_execution_proven'] is False and
                entry['programmatic_injection_disposition']=='unresolved_capability_not_execution' and
                entry['registered_CLI_external_ASA_gallery']=='none_in_this_finite_call_graph' and
                entry['source_path']==PREFIX+spec[3] and
                callers['source_sha256'].get(entry['source_path'])==entry['source_sha256'],
                'finite_caller_identity_or_source_registration_changed')
    require(callers['counts']=={'registered_callers':16,'potential_development_queries':counts['asa_core']+counts['n5_core'],
        'protected_training_proposals':counts['training'],'ASA_core_supervision':counts['asa_core']} and
        callers['ASA_core_supervision_ids_private']==sorted(envelopes['asa_core']),'caller_population_changed')
    n5=mechanical['n5_identity_state_private']
    require(type(n5) is dict and set(n5)==BASE_FIELDS|OVERLAY_FIELDS and
            set(n5['mapping'])==set(n5['raw_mapping']) and
            set(n5['blocked_screening_components'])<=set(n5['mapping'].values()) and
            set(n5['allowed_ids'])<=set(n5['mapping']) and
            all(n5['mapping'][d] not in set(n5['blocked_screening_components']) for d in n5['allowed_ids']),
            'complete_unchanged_N5_lineage_overlay_required')
    require(set(n5['protected'])=={'core','history','legacy_reserved','training','retired','potential_extra'} and
            all(n5.get(k) is False for k in ('source_completeness_proven','latest_exposure_completeness_proven',
                'download_authorized','inference_authorized','freeze_authorized','frozen','eligibility_established')),
            'unchanged_provisional_n5_overlay_required')
    require(all(set(r)=={'dish_ids','recipe_hashes'} and
            set(r['dish_ids'])<=set(n5['mapping']) and
            {n5['mapping'][d] for d in r['dish_ids']}<=set(n5['blocked_screening_components'])
            for r in n5['protected'].values()),'all_N5_protected_components_must_stay_blocked')
    require(len(n5['protected']['core']['dish_ids'])==counts['n5_core'] and len(n5['protected']['legacy_reserved']['dish_ids'])==counts['legacy_reserved'] and
            {'nutrition5k-'+d for d in n5['protected']['training']['dish_ids']}>=envelopes['training_proposals'],
            'all_legacy_and_training_proposals_must_remain_protected')
    roles=asa_audit['asa_role_sources_private'];require(set(roles['roleanchors'])==ROLES,'all_five_original_ASA_roles_required')
    local=mechanical['local_content_private'];rows=local['rows_private']
    require(type(rows) is list and len(rows)==counts['local'] and len({r['path'] for r in rows})==len(rows),
            'complete_finite_local_inventory_required')
    graph,summary=_build_phase_graph(mechanical['asa_mechanical_sources'],roles,local,
        expected_counts={'core':(counts['asa_core'],counts['asa_core_groups']),
                         'validation':(counts['asa_validation'],counts['asa_validation_groups'])})
    require(plain(graph)==plain(asa_audit['asa_phase_graph_private']) and plain(summary)==plain(asa_audit['asa_summary_private']),
            'supplied_ASA_phase_audit_changed')
    require(not any(summary['unmatched_protected_anchor_counts'].values()),'unmatched_protected_anchor_fatal')
    require(not graph['old_core_fold_bridges'] and summary['old_core_fold_bridge_components']==0 and
            summary['unverified_original_image_bindings']==0 and
            all(v['source_image_hash_verified'] for rs in graph['manifest_bindings'].values() for v in rs),
            'complete_original_core_binding_and_zero_old_fold_bridges_required')
    oldroles=deepcopy(roles['roleanchors'])
    upper_training=_anchors_union(oldroles['core'],oldroles['history']);upper_retired=_anchors_union(oldroles['history'])
    mapping=graph['node_groups'];protected=set().union(*(set(v) for v in graph['protected_groups'].values()))
    missing=set(graph['unknown_byte_images'])|set(graph['unknown_pixel_images'])
    missing_groups={mapping['i:'+name] for name in missing}
    require(len(missing)==counts['missing_names'] and len(missing_groups)==counts['missing_components'],
            'complete_registered_missing_source_quarantine_required')
    # Match every local byte and compatible V3 RGB identity, irrespective of
    # basename or whether the earlier audit attached a local byte alias.
    local_groups=set()
    for row in rows:
        nodes=['b:'+sha_value(row['bytes_sha256'])]
        if row['asa_compatible']:
            require(row['asa_algorithm']==ALGORITHM,'registered_local_ASA_RGB_semantics_required')
            nodes.append('r:'+sha_value(row['asa_rgb_sha256']))
        local_groups.update(mapping[node] for node in nodes if node in mapping)
    n5paths={path for paths in n5['potential_path_aliases_private'].values() for path in paths}
    asapaths={r['local_path'] for r in graph['local_attachments']}
    allpaths={r['path'] for r in rows}
    require(n5paths<=allpaths and asapaths<=allpaths and not n5paths&asapaths and
            len(n5paths)==counts['n5_local'] and len(asapaths)==counts['asa_local'],'finite_local_partition_changed')
    unassigned=allpaths-n5paths-asapaths
    research=local_disposition['research_dispositions_private'];other=local_disposition['other_unassigned_identity_metadata_private']
    require(type(research) is list and type(other) is list,'all_unassigned_digests_required')
    retained=[]
    for item in research:
        require(item['source_writer_proven'] is False and item['actual_api_exposure_proven'] is False and
                item['excluded_from_potential_inputs'] is False and item['retained_for_collision_checks'] is True,
                'unknown_research_inputs_must_stay_protected')
        retained.append(item['identity_metadata'])
    retained+=other
    bypath={r['path']:r for r in rows}
    require(len(unassigned)==counts['unassigned'] and len(retained)==len(unassigned) and
            {r['path'] for r in retained}==unassigned and all(r==bypath[r['path']] for r in retained) and
            local_disposition['all_unassigned_byte_and_rgb_digests_retained'] is True,
            'all_unknown_digests_must_be_retained')
    classes={k:sum(r['classification']==k for r in retained) for k in ('dependency','rendered_evidence','research_potential')}
    require(classes=={k:counts[k] for k in classes} and len(research)==counts['research_potential'] and
            all(r['identity_metadata']['classification']=='research_potential' for r in research),
            'finite_unassigned_classification_counts_changed')
    dc=local_disposition['counts']
    require(type(dc) is dict and all(dc.get(k)==v for k,v in {
            'unassigned_local_images':counts['unassigned'],'dependency':classes['dependency'],
            'rendered_evidence':classes['rendered_evidence'],'research_potential':classes['research_potential'],
            'research_unknown':len(research),'research_source_writer_proven':0}.items()),
            'local_disposition_counts_changed')
    links=local_disposition['unresolved_link_metadata_private']
    require(type(links) is list and len(links)==counts['unresolved_links'] and
            len({r['path'] for r in links})==len(links) and all(r['followed'] is False and r['body_opened'] is False and
            r['suffix_in_image_allowlist'] is False for r in links),'unresolved_links_must_not_be_followed')
    bridged=set(graph['protected_groups']['core'])&set(graph['protected_groups']['validation'])
    affected=[v['original']['sample_id'] for v in graph['manifest_bindings']['validation'] if v['component'] in bridged]
    require(len(bridged)==counts['core_validation_components'] and len(affected)==counts['affected_validation'],
            'registered_core_validation_bridge_changed')
    require(type(repair_registration) is dict and set(repair_registration)=={
            'source_disposition_design_sha256','original_linkage_guard_remains_stopped','ASA_bridge_pending_replacement'} and
            sha_value(repair_registration['source_disposition_design_sha256']) and
            repair_registration['original_linkage_guard_remains_stopped'] is True and
            repair_registration['ASA_bridge_pending_replacement']=={
                'affected_validation_records':counts['affected_validation'],'old_validation_records':counts['asa_validation'],
                'status':'proposal_only_pending_boundary_confirmation'},'explicit_pending_bridge_repair_registration_required')
    blocked=protected|missing_groups|local_groups
    permitted=set(graph['members'])-blocked
    codes={node[2:] for node,g in mapping.items() if node.startswith('c:') and g in permitted}
    return {'status':'provisional_bounded_available_source_disposition_not_eligibility',
        'original_role_anchors_private':plain(oldroles),
        'potential_training_upper_bound_anchors_private':upper_training,
        'potential_retired_upper_bound_anchors_private':upper_retired,
        'role_upper_bounds_are_actual_training_or_retirement_claims':False,
        'asa_permitted_components_private':sorted(permitted),'asa_permitted_codes_private':sorted(codes),
        'asa_blocked_components_private':sorted(blocked),'missing_source_names_private':sorted(missing),
        'missing_source_quarantine_components_private':sorted(missing_groups),
        'local_collision_components_private':sorted(local_groups),
        'all_unassigned_identity_metadata_private':deepcopy(retained),'unresolved_link_metadata_private':deepcopy(links),
        'n5_identity_state_private':deepcopy(n5),'original_ASA_validation_bindings_private':deepcopy(graph['manifest_bindings']['validation']),
        'ASA_pending_repair_private':{'bridged_components':sorted(bridged),'affected_old_validation_sample_ids':sorted(affected),
            'retained_unlinked_old_validation_sample_ids':sorted(v['original']['sample_id'] for v in graph['manifest_bindings']['validation']
                                                               if v['component'] not in bridged),
            'registration':deepcopy(repair_registration),'new_acceptance_designated':False},
        'known_scope':{'registered_callers':16,'development_queries':counts['asa_core']+counts['n5_core'],
            'training_proposals':counts['training'],'project_local_images':len(rows),
            'available_ASA_components_only':True,'source_corpus_is_not_prior_API_exposure':True,
            'arbitrary_external_filesystem_certified':False},
        'source_hash_binding_authentication':'external_secure_reader_obligation_not_proven_by_hash_form',
        'global_supplied_byte_closure_complete':False,'global_supplied_pixel_closure_complete':False,
        'actual_api_exposure_complete':False,'original_linkage_guard_remains_stopped':True,
        'postdownload_blind_exact_collision_check_required':True,'candidate_eligibility_evaluated':False,
        'download_authorized':False,'inference_authorized':False,'freeze_authorized':False,'frozen':False,
        'grants_sampling_download_or_inference':False,'new_samples_selected':0,'new_downloads':0,'api_calls':0,
        'remaining_policy_obligations':['first_integrated_preparation_review_and_fixes',
            'authenticate_and_revalidate_fixed_source_projections','blind_postdownload_unknown_digest_collision_check',
            'concrete_ASA_replacement_triplet_proposal_and_boundary_confirmation',
            'N5_acceptance_boundary_confirmation','historical_actual_API_use_not_certified']}


def disposition(mechanical,asa_audit,callers,training,local_disposition,*,repair_registration):
    return _disposition(mechanical,asa_audit,callers,training,local_disposition,repair_registration,counts=COUNTS,pins=PINS)
