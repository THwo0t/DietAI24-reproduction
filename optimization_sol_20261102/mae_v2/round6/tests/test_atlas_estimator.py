"""Synthetic-only atlas contracts, deterministic crops and request boundaries."""
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from round6.src import atlas_estimator as atlas
from opt_pipeline import ContractError, encode_image
from opt_provider import ProviderStop

IDS = [f"ingr_{number:010d}" for number in range(1, 5)]
NAMES = [{"ingredient_id": identifier, "name": "synthetic food " + str(index)}
         for index, identifier in enumerate(IDS[:3])]
CATALOG = [{**row, "density_per_100g": {"energy": 120 + 20 * index,
    "fat": 1 + index, "carbs": 25, "protein": 3 + index}}
    for index, row in enumerate(NAMES)]


def annotation(identifier=IDS[0], **changes):
    row = {"ingredient_id": identifier, "status": "separable", "boxes": [[.2, .2, .8, .8]],
           "evidence": "Visible synthetic shape.", "uncertainty": "Boundary is approximate.",
           "shared_region_group": None}
    row.update(changes)
    return row


def annotation_raw(rows=None):
    return json.dumps({"annotations": rows if rows is not None else [annotation(i) for i in IDS[:3]]})


def atlas_result(rows=None):
    raw = annotation_raw(rows)
    return {"raw_outputs": [raw], "annotations": atlas.parse_annotations(raw, NAMES),
            "repair_used": False, "failure": None}


def failed_atlas():
    raw = "{}"
    try:
        atlas.parse_annotations(raw, NAMES)
    except ContractError as exc:
        return {"raw_outputs": [raw, raw], "annotations": [], "repair_used": True, "failure": str(exc)}
    raise AssertionError("Fixture should be invalid")


def item(identifier="i1", **changes):
    row = {"item_id": identifier, "description": "synthetic visible food", "grams": 100,
           "ingredient_id": IDS[0], "estimated_density": None}
    row.update(changes)
    return row


def estimate_raw(*rows):
    return json.dumps({"items": list(rows or [item()])})


def png(width=200, height=120, color=(10, 40, 80)):
    image = Image.new("RGB", (width, height), color)
    image.paste((200, 100, 20), (width // 3, height // 3, 2 * width // 3, 2 * height // 3))
    info = PngImagePlugin.PngInfo(); info.add_text("private_metadata", "DO_NOT_SEND_SYNTHETIC_MARKER")
    buffer = BytesIO(); image.save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def sha(value):
    return hashlib.sha256(value).hexdigest()


class FakeProvider:
    def __init__(self, *outputs, expected_urls=None):
        self.outputs, self.requests, self.expected_urls = list(outputs), [], expected_urls

    def chat(self, messages, **kwargs):
        if self.expected_urls is not None:
            if atlas.ordered_image_urls(messages) != self.expected_urls:
                raise RuntimeError("image_payload_changed")
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        if not self.outputs:
            raise AssertionError("Unexpected model call")
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class AtlasEstimatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.paths = [self.directory / f"PRIVATE_SAMPLE_{index}.png" for index in range(5)]
        self.raws = [png(color=(index * 30, 40, 80)) for index in range(5)]
        for path, raw in zip(self.paths, self.raws):
            path.write_bytes(raw)
        self.query = self.paths[4]
        self.examples = [{"image_path": path, "ingredients": [
            {"ingredient_id": identifier, "grams": 100 + index}
            for index, identifier in enumerate(IDS[:3])]} for path in self.paths[:4]]
        self.atlases = [atlas_result() for _ in range(4)]

    def call(self, *outputs, atlases=None):
        provider = FakeProvider(*outputs)
        result = atlas.infer(provider, self.query, self.examples, CATALOG,
                             self.atlases if atlases is None else atlases)
        return result, provider

    def test_names_reject_supervision_extra_keys_and_bad_ids_before_reads(self):
        invalid = [[], None, {}, NAMES + NAMES[:1]]
        for key in ("grams", "density", "targets", "sample_id", "image_path"):
            value = deepcopy(NAMES); value[0][key] = "not_allowed"; invalid.append(value)
        for key, value in (("ingredient_id", "wrong"), ("ingredient_id", True), ("name", " "), ("name", 3)):
            rows = deepcopy(NAMES); rows[0][key] = value; invalid.append(rows)
        for names in invalid:
            with self.subTest(names=names), patch.object(Path, "read_bytes") as read:
                provider = FakeProvider(annotation_raw())
                with self.assertRaises(ContractError):
                    atlas.annotate(provider, self.query, names)
                read.assert_not_called(); self.assertEqual(provider.requests, [])

    def test_annotation_exact_once_all_ids_and_four_statuses(self):
        rows = [annotation(IDS[0]), annotation(IDS[1], status="partially_visible"),
                annotation(IDS[2], status="mixed_not_separable", shared_region_group="mixed1")]
        self.assertEqual(len(atlas.parse_annotations(annotation_raw(rows), NAMES)), 3)
        rows[2] = annotation(IDS[2], status="not_visible_or_uncertain", boxes=[])
        self.assertEqual(atlas.parse_annotations(annotation_raw(list(reversed(rows))), NAMES), rows)
        invalid = [rows[:2], rows + rows[:1], rows + [annotation(IDS[3])],
                   [annotation(IDS[3]), *rows[1:]], [annotation(status="maybe"), *rows[1:]]]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ContractError):
                atlas.parse_annotations(annotation_raw(values), NAMES)

    def test_annotation_strict_json_and_text_fields(self):
        invalid = ["", "null", "[]", '{"annotations":[],"annotations":[]}',
                   json.dumps({"annotations": [], "targets": {}})]
        for key, value in (("evidence", " "), ("uncertainty", None), ("shared_region_group", 7),
                           ("status", []), ("grams", 10), ("boxes", {})):
            row = annotation(); row[key] = value
            invalid.append(annotation_raw([row, annotation(IDS[1]), annotation(IDS[2])]))
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                atlas.parse_annotations(raw, NAMES)

    def test_box_shapes_bounds_and_numbers_are_strict(self):
        invalid = [[0, 0, 1], "box", [0, 0, 1, 1, 1], [0, 0, 0, 1], [.5, 0, .2, 1],
                   [0, .5, 1, .2], [0, 0, 1.01, 1]]
        invalid += [[v, 0, 1, 1] for v in (-.1, True, "0", None, float("nan"), float("inf"))]
        for box in invalid:
            with self.subTest(box=box), self.assertRaises(ContractError):
                atlas.parse_annotations(annotation_raw([annotation(boxes=[box])]), NAMES[:1])
        self.assertEqual(atlas.parse_annotations(annotation_raw([annotation(boxes=[[0, 0, 1, 1]])]),
                                                NAMES[:1])[0]["boxes"], [[0, 0, 1, 1]])

    def test_separable_requires_locations_and_no_shared_entity(self):
        for row in (annotation(boxes=[]), annotation(shared_region_group="shared")):
            with self.assertRaises(ContractError):
                atlas.parse_annotations(annotation_raw([row]), NAMES[:1])
        for status in atlas.STATUSES - {"separable"}:
            row = annotation(status=status, boxes=[], shared_region_group="mixed")
            self.assertEqual(atlas.parse_annotations(annotation_raw([row]), NAMES[:1]), [row])

    def test_annotation_request_contains_names_only_and_one_clean_image(self):
        provider = FakeProvider(annotation_raw())
        result = atlas.annotate(provider, self.paths[0], list(reversed(NAMES)))
        self.assertFalse(result["repair_used"]); self.assertIsNone(result["failure"])
        self.assertEqual(provider.requests[0]["max_completion_tokens"], 4096)
        content = provider.requests[0]["messages"][1]["content"]
        self.assertEqual(json.loads(content[1]["text"].split(": ", 1)[1]), NAMES)
        text = json.dumps(provider.requests)
        for marker in ("PRIVATE_SAMPLE", str(self.directory), "image_path", "density_per_100g", '"grams":'):
            self.assertNotIn(marker, text)
        urls = atlas.ordered_image_urls(provider.requests[0]["messages"])
        self.assertEqual(len(urls), 1)
        with Image.open(BytesIO(base64.b64decode(urls[0].split(",", 1)[1]))) as image:
            self.assertEqual(image.mode, "RGB"); self.assertEqual(image.size, (200, 120))
            self.assertNotIn("private_metadata", image.info)

    def test_annotation_repair_is_bounded_and_retains_exact_image(self):
        provider = FakeProvider("{}", annotation_raw())
        result = atlas.annotate(provider, self.paths[0], NAMES)
        self.assertEqual(result["raw_outputs"], ["{}", annotation_raw()])
        self.assertTrue(result["repair_used"]); self.assertIsNone(result["failure"])
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(atlas.ordered_image_urls(provider.requests[0]["messages"]),
                         atlas.ordered_image_urls(provider.requests[1]["messages"]))
        self.assertIn("FORMAT only", provider.requests[1]["messages"][-1]["content"])
        provider = FakeProvider("{}", "{}", annotation_raw())
        failed = atlas.annotate(provider, self.paths[0], NAMES)
        self.assertEqual(failed, failed_atlas()); self.assertEqual(len(provider.requests), 2)

    def test_provider_failures_propagate_without_contract_fallback(self):
        for error in (ProviderStop("synthetic_stop"), RuntimeError("synthetic_integrity_error")):
            provider = FakeProvider(error)
            with self.assertRaises(type(error)):
                atlas.annotate(provider, self.paths[0], NAMES)
            self.assertEqual(len(provider.requests), 1)
            provider = FakeProvider(error)
            with self.assertRaises(type(error)):
                atlas.infer(provider, self.query, self.examples, CATALOG, self.atlases)
            self.assertEqual(len(provider.requests), 1)

    def test_annotation_replay_rejects_tampering_and_unexhausted_failure(self):
        good = atlas_result(); invalid = []
        for field, value in (("annotations", []), ("repair_used", True), ("failure", "fake"),
                             ("targets", {}), ("raw_outputs", []),
                             ("raw_outputs", good["raw_outputs"] * 2),
                             ("raw_outputs", ["{}", "{}", "{}"])):
            modified = deepcopy(good); modified[field] = value; invalid.append(modified)
        short = failed_atlas(); short["raw_outputs"] = ["{}"]; short["repair_used"] = False
        invalid.append(short)
        forged = failed_atlas(); forged["annotations"] = good["annotations"]; invalid.append(forged)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                atlas.validate_annotation_result(value, NAMES)
        self.assertEqual(atlas.validate_annotation_result(good, NAMES), good)
        self.assertEqual(atlas.validate_annotation_result(failed_atlas(), NAMES), failed_atlas())

    def test_crop_union_all_occurrences_and_top_two_area_order(self):
        rows = [annotation(IDS[0], boxes=[[.1, .1, .2, .2], [.8, .8, .9, .9]]),
                annotation(IDS[1], boxes=[[.1, .1, .6, .6]]),
                annotation(IDS[2], boxes=[[.2, .2, .8, .8]])]
        cards = atlas.crop_cards_from_bytes(self.raws[0], list(reversed(rows)))
        self.assertEqual([card["ingredient_id"] for card in cards], [IDS[0], IDS[2]])
        self.assertEqual(cards[0]["proof"]["union_bbox"], [.1, .1, .9, .9])
        self.assertEqual(cards[0]["proof"]["boxes"], rows[0]["boxes"])

    def test_crop_area_ties_use_id_and_nonseparable_never_crop(self):
        rows = [annotation(identifier) for identifier in reversed(IDS)]
        self.assertEqual([c["ingredient_id"] for c in atlas.crop_cards_from_bytes(self.raws[0], rows)], IDS[:2])
        for row in rows:
            row["status"] = "partially_visible"
        self.assertEqual(atlas.crop_cards_from_bytes(self.raws[0], rows), [])
        self.assertEqual(atlas.crop_cards_from_bytes(self.raws[0], []), [])

    def test_margin_floor_ceil_and_clipping_are_exact(self):
        raw = png(100, 80)
        card = atlas.crop_cards_from_bytes(raw, [annotation(boxes=[[.2, .25, .6, .75]])])[0]
        proof = card["proof"]
        self.assertEqual(proof["pixel_bounds"], [18, 18, 62, 62])
        self.assertEqual(proof["native_crop_size"], [44, 44])
        self.assertEqual(proof["output_size"], [44, 44])
        clipped = atlas.crop_cards_from_bytes(raw, [annotation(boxes=[[0, 0, 1, 1]])])[0]
        self.assertEqual(clipped["proof"]["pixel_bounds"], [0, 0, 100, 80])
        self.assertEqual(clipped["proof"]["expanded_bbox"], [0, 0, 1, 1])
        frac = atlas.crop_cards_from_bytes(raw, [annotation(boxes=[[.123, .234, .567, .789]])])[0]
        coords = frac["proof"]["expanded_bbox"]
        self.assertEqual(frac["proof"]["pixel_bounds"], [math.floor(coords[0] * 100),
            math.floor(coords[1] * 80), math.ceil(coords[2] * 100), math.ceil(coords[3] * 80)])

    def test_crops_native_aspect_no_upscale_and_max_1024(self):
        row = [annotation(boxes=[[0, 0, 1, 1]])]
        for size, expected in (((80, 40), [80, 40]), ((2200, 1100), [1024, 512]),
                               ((700, 2100), [341, 1024])):
            with self.subTest(size=size):
                card = atlas.crop_cards_from_bytes(png(*size), row)[0]
                self.assertEqual(card["proof"]["native_crop_size"], list(size))
                self.assertEqual(card["proof"]["output_size"], expected)
                self.assertLessEqual(max(expected), 1024)

    def test_crop_proof_hashes_clean_png_deterministic_and_no_writes(self):
        before = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        rows = [annotation()]; raw = self.raws[0]
        first = atlas.crop_cards_from_bytes(raw, rows)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected read")), \
                patch.object(Path, "write_bytes", side_effect=AssertionError("unexpected write")):
            second = atlas.crop_cards_from_bytes(raw, rows)
        self.assertEqual(first, second)
        card = first[0]; proof = card["proof"]
        self.assertEqual(proof["source_image_sha256"], sha(raw))
        self.assertEqual(proof["crop_bytes_sha256"], sha(card["png_bytes"]))
        self.assertEqual(proof["payload_sha256"], sha(card["image_url"].encode("ascii")))
        self.assertEqual(base64.b64decode(card["image_url"].split(",", 1)[1]), card["png_bytes"])
        with Image.open(BytesIO(raw)) as source:
            self.assertEqual(proof["source_rgb_sha256"], sha(str(source.size).encode() + b"\0" + source.convert("RGB").tobytes()))
        with Image.open(BytesIO(card["png_bytes"])) as image:
            self.assertEqual(image.mode, "RGB"); self.assertEqual(image.format, "PNG")
            self.assertEqual(image.info, {})
            self.assertEqual(proof["crop_rgb_sha256"], sha(str(image.size).encode() + b"\0" + image.tobytes()))
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.directory.iterdir()})

    def test_bytes_helpers_do_not_open_paths_and_equal_path_payloads(self):
        expected = atlas.build_messages(self.query, self.examples, CATALOG, self.atlases)
        annotation_expected = atlas.annotation_messages(self.paths[0], NAMES)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("path read forbidden")):
            actual = atlas.build_messages_from_bytes(self.raws[4], self.raws[:4], self.examples,
                CATALOG, self.atlases, query_image_path=self.query)
            self.assertEqual(atlas.annotation_messages_from_bytes(self.raws[0], NAMES), annotation_expected)
        self.assertEqual(actual, expected)

    def test_candidate_13_image_order_wholes_crops_query_last(self):
        messages = atlas.build_messages(self.query, self.examples, CATALOG, self.atlases)
        expected = []
        for raw, result in zip(self.raws[:4], self.atlases):
            expected.append(encode_image(BytesIO(raw), "native"))
            expected += [card["image_url"] for card in atlas.crop_cards_from_bytes(raw, result["annotations"])]
        expected.append(encode_image(BytesIO(self.raws[4]), "native"))
        self.assertEqual(atlas.ordered_image_urls(messages), expected)
        self.assertEqual(len(expected), 13)
        self.assertEqual(messages[-1]["content"][-2]["text"], atlas.j.QUERY_PROMPT)
        self.assertNotIn("fifth and final", messages[-1]["content"][0]["text"])

    def test_whole_recipe_totals_unchanged_crop_text_has_no_mass_fields(self):
        messages = atlas.build_messages(self.query, self.examples, CATALOG, self.atlases)
        _, supports = atlas.j._examples(self.query, self.examples, atlas.j._catalog(CATALOG))
        content = messages[1]["content"]
        whole = [block["text"] for block in content if block["type"] == "text" and " WHOLE PHOTO recipe" in block["text"]]
        crop = [block["text"] for block in content if block["type"] == "text" and block["text"].startswith("ADDITIONAL VIEW")]
        self.assertEqual(len(whole), 4); self.assertEqual(len(crop), 8)
        for text, support in zip(whole, supports):
            self.assertEqual(json.loads(text.split(": ", 1)[1]),
                {"ingredients": support["ingredients"], "reference_totals": support["reference_totals"]})
        for text in crop:
            row = json.loads(text.split(": ", 1)[1])
            self.assertEqual(set(row), {"ingredient_id", "name", "boxes", "union_bbox"})
        for marker in ("PRIVATE_SAMPLE", str(self.directory), "image_path", "crop_grams"):
            self.assertNotIn(marker, json.dumps(messages))
        self.assertIn("including unseen mass", atlas.ATLAS_NOTE)

    def test_failed_atlas_preserves_all_whole_photos_and_full_recipes(self):
        failed = [failed_atlas() for _ in range(4)]
        result, provider = self.call(estimate_raw(), atlases=failed)
        self.assertIsNone(result["failure"])
        messages = provider.requests[0]["messages"]
        self.assertEqual(len(atlas.ordered_image_urls(messages)), 5)
        texts = [b["text"] for b in messages[1]["content"] if b["type"] == "text"]
        self.assertEqual(sum(" WHOLE PHOTO recipe" in text for text in texts), 4)
        self.assertEqual(sum('"available": false' in text for text in texts), 4)
        self.assertFalse(any(text.startswith("ADDITIONAL VIEW") for text in texts))

    def test_candidate_retains_exact_j_parse_programmatic_nutrients_and_unknowns(self):
        density = {"energy": 90, "fat": 1, "carbs": 12, "protein": 3}
        raw = estimate_raw(item(grams=150), item("i2", grams=50, ingredient_id=IDS[1]),
                           item("i3", grams=20, ingredient_id=None, estimated_density=density))
        expected = atlas.j._parse(raw, atlas.j._catalog(CATALOG))
        result, provider = self.call(raw)
        self.assertEqual((result["items"], result["prediction"], result["audit"]), expected)
        self.assertEqual(result["prediction"], {"weight": 220, "energy": 268,
                                               "fat": 2.7, "carbs": 52.4, "protein": 7.1})
        self.assertEqual(provider.requests[0]["max_completion_tokens"], 8192)
        self.assertEqual(atlas.validate_candidate_result(result, CATALOG), result)

    def test_candidate_contract_invalid_ids_density_counts_and_nonfinite(self):
        bad = [estimate_raw(item(ingredient_id=IDS[3])), estimate_raw(item(grams=0)),
               estimate_raw(item(grams=float("nan"))), estimate_raw(item(estimated_density={})),
               estimate_raw(item(ingredient_id=None)), estimate_raw(item(), item()),
               estimate_raw(*(item(f"i{i}") for i in range(1, 22))),
               json.dumps({"items": [item()], "group_id": "not_allowed"})]
        for raw in bad:
            with self.subTest(raw=raw):
                result, provider = self.call(raw, raw, estimate_raw())
                self.assertIsNone(result["prediction"]); self.assertEqual(result["items"], [])
                self.assertIsNotNone(result["failure"]); self.assertEqual(len(provider.requests), 2)
        valid = estimate_raw(*(item(f"i{i}") for i in range(1, 21)))
        self.assertEqual(len(self.call(valid)[0]["items"]), 20)

    def test_candidate_repair_preserves_order_and_replay_rejects_forgery(self):
        result, provider = self.call("{}", estimate_raw())
        self.assertEqual(result["raw_outputs"], ["{}", estimate_raw()])
        self.assertTrue(result["repair_used"])
        self.assertEqual(atlas.ordered_image_urls(provider.requests[0]["messages"]),
                         atlas.ordered_image_urls(provider.requests[1]["messages"]))
        self.assertIn("FORMAT only", provider.requests[1]["messages"][-1]["content"])
        changed = deepcopy(result); changed["prediction"]["weight"] += 1
        with self.assertRaises(ValueError):
            atlas.validate_candidate_result(changed, CATALOG)

    def test_supplied_extra_fields_fail_before_reads_or_api(self):
        bad = []
        examples = deepcopy(self.examples); examples[0]["query_labels"] = {}; bad.append((examples, CATALOG, self.atlases))
        examples = deepcopy(self.examples); examples[0]["ingredients"][0]["targets"] = {}; bad.append((examples, CATALOG, self.atlases))
        catalog = deepcopy(CATALOG); catalog[0]["support_count"] = 1; bad.append((self.examples, catalog, self.atlases))
        atlases = deepcopy(self.atlases); atlases[0]["sample_id"] = "private"; bad.append((self.examples, CATALOG, atlases))
        atlases = deepcopy(self.atlases); atlases[0]["annotations"][0]["boxes"] = [[0, 0, 1, 1]]
        bad.append((self.examples, CATALOG, atlases))
        bad += [(self.examples[:3], CATALOG, self.atlases), (self.examples, CATALOG, self.atlases[:3])]
        for examples, catalog, atlases in bad:
            with self.subTest(case=(len(examples), len(atlases))), patch.object(Path, "read_bytes") as read:
                provider = FakeProvider(estimate_raw())
                with self.assertRaises(ValueError):
                    atlas.infer(provider, self.query, examples, catalog, atlases)
                read.assert_not_called(); self.assertEqual(provider.requests, [])

    def test_duplicate_resolved_image_paths_are_rejected(self):
        for path in (self.query, self.paths[0], self.directory / "unused/../PRIVATE_SAMPLE_0.png"):
            examples = deepcopy(self.examples); examples[1]["image_path"] = path
            with self.subTest(path=path), patch.object(Path, "read_bytes") as read:
                with self.assertRaises(ContractError):
                    atlas.build_messages(self.query, examples, CATALOG, self.atlases)
                read.assert_not_called()

    def test_expected_frozen_byte_payload_detects_later_path_change(self):
        messages = atlas.build_messages_from_bytes(self.raws[4], self.raws[:4], self.examples,
            CATALOG, self.atlases, query_image_path=self.query)
        provider = FakeProvider(estimate_raw(), expected_urls=atlas.ordered_image_urls(messages))
        self.paths[0].write_bytes(png(color=(200, 200, 200)))
        with self.assertRaisesRegex(RuntimeError, "image_payload_changed"):
            atlas.infer(provider, self.query, self.examples, CATALOG, self.atlases)
        self.assertEqual(provider.requests, [])

    def test_large_catalog_text_does_not_invalidate_image_order_extraction(self):
        catalog = deepcopy(CATALOG)
        for number in range(4, 100):
            catalog.append({"ingredient_id": f"ingr_{number:010d}", "name": "synthetic extra ingredient",
                            "density_per_100g": dict(CATALOG[0]["density_per_100g"])})
        messages = atlas.build_messages(self.query, self.examples, catalog, self.atlases)
        self.assertGreater(len(messages[1]["content"][1]["text"]), 4000)
        self.assertEqual(len(atlas.ordered_image_urls(messages)), 13)

    def test_order_extractor_rejects_extra_fields_non_inline_and_over_budget(self):
        url = "data:image/png;base64,synthetic"
        valid = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}]
        invalid = [[], valid * 14, [{**valid[0], "targets": {}}],
                   [{"role": "user", "content": [{"type": "text", "text": 7}]}],
                   [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://invalid/image"}}]}]]
        for messages in invalid:
            with self.subTest(messages=messages), self.assertRaises(ContractError):
                atlas.ordered_image_urls(messages)

    def test_all_supplied_inputs_are_unchanged(self):
        names, examples, catalog, atlases = deepcopy((NAMES, self.examples, CATALOG, self.atlases))
        before = deepcopy((names, examples, catalog, atlases))
        atlas.annotate(FakeProvider(annotation_raw()), self.paths[0], names)
        atlas.infer(FakeProvider(estimate_raw()), self.query, examples, catalog, atlases)
        atlas.crop_cards_from_bytes(self.raws[0], atlases[0]["annotations"])
        self.assertEqual((names, examples, catalog, atlases), before)


if __name__ == "__main__":
    unittest.main()
