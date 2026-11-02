"""G: four training-reference RGB examples plus one independently judged query.

This supervised visual-example variant explicitly departs from the original
FNDDS nutrient-density calculation. The driver/selector must exclude the query
fold and association group from all four supports and bind their provenance.
This boundary receives only support paths and five reference quantities, never
sample IDs, query labels, earlier predictions, retrieved codes or dataset IDs.
It verifies four distinct support paths, distinct from the query, before any
image encoding or provider call. Each image uses native <=1024 encoding.

F's source is unchanged: its strict item parser and audit functions are reused.
There is one main call and at most one structural repair, always 8192 completion
tokens and five images. Provider errors propagate without median substitution;
training-only fallback is the caller's responsibility.
"""
from __future__ import annotations

import json
from pathlib import Path

from direct_estimator import (COMPLETION_TOKENS, PROMPT as DIRECT_PROMPT,
                              SYSTEM_PROMPT, TARGETS, _parse, _macro_mass_excess)
from opt_pipeline import ContractError, _number, _object, encode_image

METHOD_VERSION = "four-visual-examples-r3.1"
SUPPORT_COUNT = 4
INTRODUCTION = (
    "The first four images are separate labeled training examples. Each example "
    "has the total cooked edible weight in grams, energy in kilocalories, and "
    "fat, carbohydrate and protein in grams for its whole meal. Use these "
    "examples to compare portion size, food type and food scale. They are not "
    "parts of the query meal. Do not copy their foods, weights or nutrient "
    "amounts into the query answer. Judge the query independently from its own "
    "visible evidence. The fifth and final image alone is the query."
)
QUERY_PROMPT = (
    "QUERY IMAGE follows. Return item estimates ONLY for this final image. "
    "In the instruction below, 'this single RGB image' means this query alone, "
    "never the four preceding reference images. " + DIRECT_PROMPT
)


def _path(value):
    if not isinstance(value, (str, Path)) or not str(value):
        raise ContractError("invalid_image_path")
    return Path(value).resolve()


def _validated_examples(query_image_path, examples):
    query = _path(query_image_path)
    if not isinstance(examples, list) or len(examples) != SUPPORT_COUNT:
        raise ContractError("exactly_four_training_examples_required")
    checked, seen = [], {query}
    for example in examples:
        _object(example, {"image_path", "reference"})
        picture = _path(example["image_path"])
        if picture in seen:
            raise ContractError("duplicate_support_or_query_image_path")
        seen.add(picture)
        values = _object(example["reference"], set(TARGETS))
        reference = {key: _number(values[key]) for key in TARGETS}
        if reference["weight"] <= 0:
            raise ContractError("nonpositive_reference_weight")
        checked.append({"image_path": picture, "reference": reference})
    return query, checked


def infer(provider, query_image_path, examples):
    """Estimate the query from exactly four pre-isolated training references.

    Return ``raw_outputs/items/prediction/repair_used/failure/audit`` as in F.
    Reference validation errors precede all image reads and provider requests.
    Numeric macro-mass concerns in the model answer are audit flags only.
    """
    query, supports = _validated_examples(query_image_path, examples)
    content = [{"type": "text", "text": INTRODUCTION}]
    for index, support in enumerate(supports, 1):
        content += [
            {"type": "text", "text": "Training example " + str(index) +
             " whole-meal reference amounts: " + json.dumps(support["reference"], allow_nan=False)},
            {"type": "image_url", "image_url": {"url": encode_image(support["image_path"], "native")}},
        ]
    content += [{"type": "text", "text": QUERY_PROMPT},
                {"type": "image_url", "image_url": {"url": encode_image(query, "native")}}]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]
    raw_outputs, failure = [], None
    for attempt in range(2):
        raw = provider.chat(messages, max_completion_tokens=COMPLETION_TOKENS)
        raw_outputs.append(raw)
        try:
            items, prediction = _parse(raw)
        except ContractError as exc:
            failure = str(exc)
            if attempt == 0:
                messages += [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": (
                        "Correct JSON FORMAT only to satisfy the original contract for "
                        "the final query image. Preserve the original visual estimates; "
                        "do not reconsider accuracy, copy a training example or add a new "
                        "interpretation. Return only the requested JSON. Contract error: " + failure)},
                ]
        else:
            return {"raw_outputs": raw_outputs, "items": items, "prediction": prediction,
                "repair_used": bool(attempt), "failure": None,
                "audit": {"macro_mass_excess_items": [item["item_id"] for item in items
                                                       if _macro_mass_excess(item)],
                          "macro_mass_excess_total": _macro_mass_excess(prediction)}}
    return {"raw_outputs": raw_outputs, "items": [], "prediction": None,
        "repair_used": True, "failure": failure,
        "audit": {"macro_mass_excess_items": [], "macro_mass_excess_total": None}}
