"""Blind Q/D stage predictors; injected chat owns provider and ledger policy.

No composition, scoring, fallback, calibration or conditional ASA adapter.
"""
from copy import deepcopy

from opt_pipeline import ContractError, encode_image
from source_portions import SourcePortionPipeline
import paired_accounting as p

VERSION = 'paired-stages.1'
IMAGE_MODE = 'square256'


class PairedStagePipeline(SourcePortionPipeline):
    def _fixed(self, identity, dataset):
        # Preserve O's complete candidate/final-code proof, then enforce the
        # stricter ordered paired-item contract. Ignore unrelated label metadata.
        try:
            items = p.checked_items(self.checked_items(identity, dataset))
            foods = {code: {'description': self.foods[code]['description']}
                     for item in items
                     for code in [item['primary_code']] + item['alternative_codes']}
            p.contexts(items, foods)
            binding = {'items': items, 'candidates': deepcopy(identity['candidates']),
                       'final_codes': deepcopy(identity['final_codes']), 'foods': foods}
            p.fingerprint(binding)
            return binding
        except p.PairContractError as exc:
            raise ContractError('paired_' + str(exc)) from None
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
            if isinstance(exc, ContractError):
                raise
            raise ContractError('paired_invalid_fixed_identity') from None

    def _intervention(self, image_path, identity, dataset, kind):
        fixed = self._fixed(identity, dataset)
        prompt_fn, parse_fn = ((p.quantity_prompt, p.parse_quantity) if kind == 'quantity'
                               else (p.density_prompt, p.parse_density))
        prompt = prompt_fn(fixed['items'], fixed['foods'])
        def parse(raw):
            if self._fixed(identity, dataset) != fixed:
                raise ContractError('paired_fixed_identity_changed')
            try:
                return parse_fn(raw, fixed['items'])
            except p.PairContractError as exc:
                raise ContractError('paired_' + str(exc)) from None
        stages = []
        value = self._stage('paired_' + kind, prompt, encode_image(image_path, IMAGE_MODE), parse, stages)
        status = ('failed' if value is None else
                  'repaired' if len(stages[0]['attempts']) == 2 else 'native')
        return self._result(stages, status=status, value=value,
            failure='paired_' + kind + '_contract' if value is None else None,
            method_version=VERSION, dataset=dataset, image_mode=IMAGE_MODE,
            source_binding=deepcopy(fixed), fixed_source_sha256=p.fingerprint(fixed),
            prompt=prompt, prompt_sha256=p.fingerprint(prompt),
            parsed_sha256=None if value is None else p.fingerprint(value))

    def quantity_intervention(self, image_path, identity, dataset):
        return self._intervention(image_path, identity, dataset, 'quantity')

    def density_intervention(self, image_path, identity, dataset):
        return self._intervention(image_path, identity, dataset, 'density')
