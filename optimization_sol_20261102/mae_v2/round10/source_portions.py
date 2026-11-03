"""O's label-blind flat-food quantity core and explicit conditional task.

No dataset loader, provider, credentials, labels, examples or oracle weights.
Callers must seal identities before enabling the conditional adapter.
"""
from copy import deepcopy
import json

from opt_pipeline import (Pipeline, ContractError, TARGETS, NUTRIENTS,
                          _object, _json, _number, _code, encode_image)
from pipeline_v2 import ComponentPipeline, _positive
from uncertain_portions import canonical_options

VERSION = 'source-portions-O.1'
CONFIG = {'variant':'optimized','candidate_cap':32,'image_mode':'square256'}


class SourcePortionPipeline(Pipeline):
    def checked_items(self, identity, dataset):
        if identity.get('status') != 'ok' or dataset not in ('asa24','nutrition5k'):
            raise ContractError('O_complete_identity_required')
        raw_items = identity.get('items',[])
        initial = [{k:item[k] for k in ('item_id','description','broad_query','region_ids')}
                   for item in raw_items]
        parsed = self._identity_items(json.dumps({'items':initial}),dataset)
        banks = identity.get('candidates',{})
        if set(banks) != {item['item_id'] for item in parsed}:
            raise ContractError('O_candidate_item_join_changed')
        for bank in banks.values():
            if (not isinstance(bank,list) or not 1 <= len(bank) <= 32 or len(set(bank)) != len(bank)
                    or any(_code(code) not in self.foods for code in bank)):
                raise ContractError('O_invalid_candidate_bank')
        choices = [{k:item[k] for k in ('item_id','primary_code','alternative_codes')} for item in raw_items]
        materialized = self._selection(json.dumps({'items':choices}),parsed,banks,dataset)
        if materialized != raw_items:
            raise ContractError('O_identity_item_fields_changed')
        expected = ([materialized[0]['primary_code']]+materialized[0]['alternative_codes'] if dataset == 'asa24'
                    else list(dict.fromkeys(item['primary_code'] for item in materialized)))
        if identity.get('final_codes') != expected:
            raise ContractError('O_final_coding_changed')
        return materialized

    def portion_context(self, identity, dataset):
        items = self.checked_items(identity,dataset)
        catalogue = ComponentPipeline(None,None,self.catalog,None)
        context = []
        for item in items:
            code = item['primary_code']
            options = catalogue.usable_standard_options(code)
            converted = canonical_options(options,code)
            context.append({'item_id':item['item_id'],'description':item['description'],
                'region_ids':deepcopy(item['region_ids']), 'primary_code':code,
                'selected_food':self.foods[code]['description'], 'standard_options':options,
                'canonical_units':converted['units'], 'excluded_unit_conflicts':converted['conflicts'],
                'direct_grams_allowed':not options and not converted['units']})
        return context

    @staticmethod
    def quantity_prompt(context):
        return ('Estimate the cooked edible portion of EACH fixed physical food in the RGB. '
            'Use the following state machine separately for every item. FIRST, if a complete standard '
            'description fits the visible portion, choose mode=standard and its option_id; the program '
            'uses exactly that option weight, with no multiplier. ONLY when no standard fits, choose '
            'mode=adjusted, no_standard_fit=true, a listed canonical unit_id and a strictly positive count. '
            'The unit describes ONE unit; do not multiply the original fractional source description. '
            'Direct mode=grams is permitted only for items explicitly marked direct_grams_allowed. '
            'Use visible scale clues; do not invent dimensions or hidden ingredients. Do not change '
            'identities, remove a food, split a compound serving, or add its ingredients again. '
            'Alternatives are uncertain identities of the SAME physical food, not extra portions. '
            'Catalogue text is general data, not a label for this image. Return all fixed item IDs once '
            'and ONLY JSON {"items":[{"item_id":"i1","mode":"standard","option_id":"s1"}]} '
            'or the corresponding item shape {"item_id":"i1","mode":"adjusted",'
            '"no_standard_fit":true,"unit_id":"u...","count":1.5} or '
            '{"item_id":"i1","mode":"grams","grams":100}. Fixed context: '+json.dumps(context))

    def aggregate_quantities(self, identity, dataset, choices):
        items = self.checked_items(identity,dataset)
        by_id = {row['item_id']:row for row in choices}
        if len(by_id) != len(choices) or set(by_id) != {i['item_id'] for i in items}:
            raise ContractError('O_incomplete_or_duplicate_physical_quantities')
        totals, leaves = dict.fromkeys(TARGETS,0.0), []
        for item in items:
            codes = [item['primary_code']]+item['alternative_codes']
            density = {k:_number(sum(_number(self.foods[c]['density'][k])/len(codes) for c in codes))
                       for k in NUTRIENTS}
            grams = _positive(by_id[item['item_id']]['grams'])
            contribution = {k:_number(grams*(density[k]/100)) for k in NUTRIENTS}
            totals['weight'] = _number(totals['weight']+grams)
            for k in NUTRIENTS:
                totals[k] = _number(totals[k]+contribution[k])
            leaves.append({'item_id':item['item_id'],'component_id':item['item_id'],
                'parent_id':item['item_id'],'code':codes[0],'codes':codes,'grams':grams,
                'density':density,'nutrient_contribution':contribution,
                'quantity':deepcopy(by_id[item['item_id']])})
        return {'status':'ok','failure':None,'method_version':VERSION,'prediction':totals,
                'raw_prediction':deepcopy(totals),'raw_leaves':leaves,'portions':deepcopy(choices)}

    def parse_quantities(self, raw, identity, dataset, context):
        if context != self.portion_context(identity,dataset):
            raise ContractError('O_quantity_context_changed')
        data = _object(_json(raw),{'items'})
        if not isinstance(data['items'],list) or len(data['items']) != len(context):
            raise ContractError('O_missing_or_extra_quantity')
        fixed = {c['item_id']:c for c in context}
        seen, choices = set(), []
        for value in data['items']:
            if not isinstance(value,dict):
                raise ContractError('O_quantity_item_object_required')
            cid,mode = value.get('item_id'),value.get('mode')
            if not isinstance(cid,str) or cid not in fixed or cid in seen:
                raise ContractError('O_invalid_or_duplicate_quantity_item')
            seen.add(cid); item = fixed[cid]
            if mode == 'standard':
                _object(value,{'item_id','mode','option_id'})
                option = next((o for o in item['standard_options'] if o['option_id']==value['option_id']),None)
                if option is None:
                    raise ContractError('O_illegal_standard_option')
                choice = {**value,'grams':_positive(option['grams']),
                          'option_description':option['description'],'source_option':deepcopy(option)}
            elif mode == 'adjusted':
                _object(value,{'item_id','mode','no_standard_fit','unit_id','count'})
                if value['no_standard_fit'] is not True:
                    raise ContractError('O_adjustment_requires_no_standard_fit')
                unit = next((u for u in item['canonical_units'] if u['unit_id']==value['unit_id']),None)
                if unit is None:
                    raise ContractError('O_illegal_canonical_unit')
                count = _positive(value['count'])
                choice = {**value,'count':count,'grams':_positive(count*unit['grams_per_unit']),
                          'source_unit':deepcopy(unit)}
            elif mode == 'grams':
                _object(value,{'item_id','mode','grams'})
                if not item['direct_grams_allowed']:
                    raise ContractError('O_direct_grams_forbidden_when_standard_available')
                choice = {**value,'grams':_positive(value['grams'])}
            else:
                raise ContractError('O_unknown_quantity_mode')
            choices.append(choice)
        # Check the complete five-vector inside the parser/repair contract.
        return self.aggregate_quantities(identity,dataset,choices)

    def whole_portions(self, image_path, identity, dataset):
        context = self.portion_context(identity,dataset)
        stages = []
        result = self._stage('source_standard_first',self.quantity_prompt(context),
            encode_image(image_path,'square256'),lambda raw:self.parse_quantities(raw,identity,dataset,context),stages)
        if result is None:
            result = {'status':'failed','failure':'O_quantity_contract','prediction':None,
                      'raw_prediction':None,'raw_leaves':[],'portions':[],'method_version':VERSION}
        return self._result(stages,**result)

    def conditional_portion(self, image_path, identity, context):
        # The caller's isolated post-seal adapter is the only source of this
        # allowed task context. The main/E2E core never receives it.
        self.checked_items(identity,'asa24')
        _object(context,{'code','options'})
        return self.portion(image_path,identity,'asa24',
            {**CONFIG,'portion_mode':'continuous_option'},conditional_context=context)
