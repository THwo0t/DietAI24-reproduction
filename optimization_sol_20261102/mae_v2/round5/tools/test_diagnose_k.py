"""Invented cohorts and genuine ArtifactStore seals; no real K/data/API access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import FunctionType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from round4.src.artifacts import ArtifactStore, ArtifactError, canonical, decode, fingerprint, key_path
from round5.tools import diagnose_k as d


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def totals(weight):
    return {"weight": weight, "energy": weight * 2, "fat": weight / 10,
            "carbs": weight * .3, "protein": weight * .2}


def leaves(weight):
    # K's extra group fields must not change the old accounting mathematics.
    return [{"ingredient_id": "synthetic-a", "grams": weight,
             "density": {key: value for key, value in totals(100).items() if key != "weight"},
             "group_id": "visible-group-0", "item_id": "component-0", "region": [0, 0, 1, 1]}]


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="synthetic-K-diagnostic-", dir=Path(__file__).resolve().parent)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        for relative in ("round4/diagnostics", "round5"):
            self.mkdir(relative)
        self.rows, self.labels, self.records, self.preserved, self.metadata = [], {}, {}, [], []
        for dataset, count, groups in (("nutrition5k", 84, 78), ("asa24", 99, 23)):
            for index in range(count):
                sid = f"synthetic-{dataset}-{index:03d}"
                row = {"sample_id": sid, "dataset": dataset, "group_id": f"{dataset}-group-{index % groups}",
                       "fold": index % groups % 5, "split": "dev"}
                self.rows.append(row)
                self.labels[sid] = {"truth": totals(100), "split": "dev"}
                pred = {**row, "query_id": sid, "prediction": totals(90), "raw_prediction": totals(90),
                        "fallback": False, "method_fallback": False, "repair_used": False,
                        "native_complete": True, "final_codes": [], "primary_code": None, "failure": None}
                if dataset == "nutrition5k":
                    pred["raw_leaves"] = leaves(90)
                    self.records[sid] = pred
                    ingredients = [{"ingredient_id": name, "grams": grams,
                        "nutrients": {key: value for key, value in totals(grams).items() if key != "weight"}}
                        for name, grams in (("synthetic-a", 50), ("synthetic-b", 30), ("not-in-catalog", 20))]
                    self.metadata.append({**row, "ingredients": ingredients})
                else:
                    self.labels[sid].update(food_code="12345678", size="synthetic")
                    pred.update(final_codes=["12345678"], primary_code="12345678",
                                conditional={"prediction": totals(90), "fallback": False},
                                e2e={"prediction": totals(90), "fallback": False})
                    self.preserved.append(pred)
        self.contract = {"sources": ("round5/K_PROTOCOL.md", "round5/src/run_component.py"),
            "method_config": {"candidate": "K", "calibration": None}, "protocol": "round5/K_PROTOCOL.md",
            "protocol_sha256": None, "parent_completion_sha256": d.J_BASE_SHA256}
        for name in set(d.SOURCES) | set(d.k_score.SOURCE_NAMES) | set(self.contract["sources"]):
            self.put(name, ("synthetic-source:" + name).encode())
        self.contract["protocol_sha256"] = sha((self.root / self.contract["protocol"]).read_bytes())
        math_pins = {name: sha((self.root / name).read_bytes()) for name in d.MATH_PINS}
        self.put(d.scorer.MANIFEST, b"".join(canonical(row) for row in self.rows))
        self.put(d.scorer.LABELS, canonical(self.labels))
        self.put(d.scorer.PRESERVED, canonical(self.preserved))
        self.ingredient_hash = self.put(d.INGREDIENTS, canonical({"records": self.metadata}))
        self.catalog_hash = self.put(d.CATALOG, canonical({"schema_version": 1,
            "scope": "accepted_external_training_only_domain_catalog", "ingredients": [
                {"ingredient_id": name} for name in ["synthetic-a", "synthetic-b"]
                + [f"catalog-only-{index}" for index in range(162)]]}))
        freeze = {"status": "accepted_external_training_frozen", "binding": {"synthetic_exclusion": True}}
        freeze_hash = self.put(d.k_score.TRAIN_FREEZE, canonical(freeze))
        self.binding = {"phase": "development_component_base", "method_config": self.contract["method_config"],
            "query_count": 84, "query_groups": 78, "training_freeze_sha256": freeze_hash,
            "training_exclusion_binding": freeze["binding"],
            "parent_provenance": {"parent_completion_sha256": d.J_BASE_SHA256, "training_freeze_sha256": freeze_hash},
            "input_sha256": {name: sha((self.root / name).read_bytes()) for name in
                (d.scorer.MANIFEST, d.k_score.TRAIN_FREEZE, d.CATALOG, *self.contract["sources"])}}
        self.reseal_base()
        summary = FunctionType(d.scorer._summary.__code__, {**d.scorer._summary.__globals__, "BOOTSTRAP": 0})
        old_records = deepcopy(self.records)
        for pred in old_records.values():
            pred.update(prediction=totals(80), raw_prediction=totals(80), raw_leaves=leaves(80))
        n5 = [row for row in self.rows if row["dataset"] == "nutrition5k"]
        self.raw_j = summary(self.rows, self.labels, n5, list(old_records.values()), self.preserved)
        self.raw_j.update(candidate="J_service_continuation", calibration_applied=False)
        ArtifactStore(self.root / d.k_score.BASELINE_OUTPUT, {"synthetic_J_scoring": True}, ["metrics"],
            verify_sources=lambda: None, root=self.root / "round4").finalize({"metrics": {"raw": self.raw_j}})
        pins = {name: sha((self.root / name).read_bytes()) for name in d.k_score.PINNED_INPUTS}
        self.reads, self.base_calls = [], []
        outer = self

        class Reader(d.k_score.Inputs):
            def read(self, name):
                outer.reads.append(name)
                return super().read(name)

        for mock in (patch.object(d, "ROOT", self.root), patch.object(d.k_score, "ROOT", self.root),
                     patch.object(d, "Inputs", Reader), patch.object(d.k_score, "Inputs", Reader),
                     patch.object(d.k_score, "PINNED_INPUTS", pins), patch.object(d, "MATH_PINS", math_pins),
                     patch.object(d, "INGREDIENTS_SHA256", self.ingredient_hash),
                     patch.object(d.k_score, "verified_base", self.base),
                     patch.object(d.k_score, "driver_contract", lambda: deepcopy(self.contract)),
                     patch.object(d.k_score, "summarize", summary)):
            mock.start()
            self.addCleanup(mock.stop)
        # Real scorer code, only mocked synthetic base/read roots and zero bootstrap.
        d.k_score.score()
        labels = {sid: self.labels[sid] for sid in old_records}
        oracle = d.math_core.true_weight_oracle(old_records, labels)
        old_decomposition = d.math_core.aggregate_decomposition([
            d.math_core.decompose(old_records[row["sample_id"]], row["ingredients"],
                labels[row["sample_id"]]["truth"], {"synthetic-a", "synthetic-b"}) for row in self.metadata])
        old = {"scope": d.SCOPE, "candidate_source": "J_service_continuation", "n": 84, "groups": 78,
            "training_catalog_sha256": self.catalog_hash, "training_catalog_size": 164,
            "raw_point_metrics": self.raw_j["nutrition5k"]["primary"]["metrics"],
            "true_weight_oracle_point_metrics": d.scorer.metrics.evaluate(n5, labels, list(oracle.values()),
                bootstrap=0)["datasets"]["nutrition5k"]["primary"]["metrics"],
            "decomposition": old_decomposition, "new_profile_selected": False, "validation_opened": False}
        j_binding = {"phase": "posthoc_service_continuation_diagnostic", "scope": d.SCOPE,
            "base_completion_sha256": d.J_BASE_SHA256, "ingredient_source_sha256": self.ingredient_hash,
            "input_sha256": math_pins}
        ArtifactStore(self.root / d.J_OUTPUT, j_binding, ["aggregate"], verify_sources=lambda: None,
            root=self.root / "round4/diagnostics").finalize({"aggregate": old})
        mock = patch.object(d, "J_COMPLETION_SHA256", sha((self.root / d.J_COMPLETION).read_bytes()))
        mock.start(); self.addCleanup(mock.stop)
        self.reads.clear(); self.base_calls.clear()

    def mkdir(self, relative):
        parent = self.root
        for part in Path(relative).parts:
            parent /= part
            parent.mkdir(mode=0o700, exist_ok=True)

    def put(self, relative, raw):
        self.mkdir(str(Path(relative).parent))
        path = self.root / relative
        path.write_bytes(raw); path.chmod(0o600)
        return sha(raw)

    def reseal_base(self):
        path = self.root / d.k_score.BASE_OUTPUT
        if path.exists(): shutil.rmtree(path)
        self.base_store = ArtifactStore(path, self.binding, self.records,
            verify_sources=lambda: None, root=self.root / "round5")
        self.base_store.finalize(self.records)

    def base(self):
        self.base_calls.append(True)
        return {"status": "base_verified", "n": 84, "records": self.base_store.verify_completed(),
            "binding": deepcopy(self.binding), "completion_sha256": sha((self.root / d.k_score.BASE_COMPLETION).read_bytes()),
            "provider_constructed": False, "validation_opened": False}

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def assert_no_labels(self):
        self.assertNotIn(d.scorer.LABELS, self.reads)
        self.assertNotIn(d.INGREDIENTS, self.reads)

    def reseal(self, directory, key, mutate_binding=lambda _: None, mutate_record=lambda _: None):
        intent = decode((self.root / directory / "intent.json").read_bytes())
        parent = self.root / ("round4/diagnostics" if directory == d.J_OUTPUT else "round5")
        store = ArtifactStore(self.root / directory, intent["binding"], [key],
                              verify_sources=lambda: None, root=parent)
        saved = store.verify_completed()
        mutate_binding(intent["binding"]); mutate_record(saved[key])
        shutil.rmtree(self.root / directory)
        ArtifactStore(self.root / directory, intent["binding"], [key],
                      verify_sources=lambda: None, root=parent).finalize(saved)

    def test_aggregate_only_complete_repeat_is_byte_and_mtime_readonly(self):
        result = d.run(); before = self.snapshot(); value = result["aggregate"]
        self.assertEqual(result["status"], "diagnostic_complete")
        self.assertEqual((value["n"], value["decomposition"]["population_n"]), (84, 84))
        self.assertEqual(value["true_weight_oracle_point_metrics"]["weight"]["mae"], 0)
        self.assertEqual(value["raw_J_point_metrics"], self.raw_j["nutrition5k"]["primary"]["metrics"])
        mechanism = value["mechanism_comparison"]["raw_K"]
        self.assertEqual(mechanism["available_id_reference_mass_fraction"], 50 / 80)
        self.assertEqual(mechanism["exact_id_overlap_reference_fraction"], .5)
        self.assertEqual(mechanism["shared_id_absolute_mass_error_g_per_population_row"], 40)
        self.assertNotIn("synthetic-nutrition5k", json.dumps(value))
        self.assertNotIn("synthetic-a", json.dumps(value))
        second = d.run()
        self.assertEqual(second["aggregate"], value)
        self.assertEqual(second["status"], "diagnostic_verified")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(self.base_calls), 4)

    def test_partial_or_failed_base_stops_before_reader(self):
        complete = self.base(); self.base_calls.clear()
        for value in ({**complete, "n": 83}, {**complete, "validation_opened": True},
                      {**complete, "provider_constructed": True},
                      {**complete, "records": dict(list(complete["records"].items())[:-1])}):
            with self.subTest(), patch.object(d.k_score, "verified_base", return_value=value):
                with self.assertRaises(ValueError): d.run()
        with patch.object(d.k_score, "verified_base", side_effect=ArtifactError("synthetic_failure")):
            with self.assertRaises(ArtifactError): d.run()
        self.assertEqual(self.reads, [])

    def test_missing_or_tampered_score_seal_precedes_labels(self):
        path = self.root / d.k_score.OUTPUT / "completion.json"
        original = path.read_bytes(); path.unlink()
        with self.assertRaises(ArtifactError): d.run()
        self.assert_no_labels()
        self.put(str(path.relative_to(self.root)), original)
        record = self.root / d.k_score.OUTPUT / "records" / (key_path("metrics") + ".json")
        record.write_bytes(record.read_bytes() + b" ")
        with self.assertRaises(ArtifactError): d.run()
        self.assert_no_labels()

    def test_score_binding_scope_drift_rejected_before_labels(self):
        self.reseal(d.k_score.OUTPUT, "metrics", mutate_binding=lambda value: value.update(scope="validation"))
        with self.assertRaises(ArtifactError): d.run()
        self.assert_no_labels()

    def test_score_record_scope_drift_rejected_before_labels(self):
        self.reseal(d.k_score.OUTPUT, "metrics", mutate_record=lambda value: value.update(scope="validation"))
        with self.assertRaisesRegex(d.DiagnosticError, "scoring_scope_changed"): d.run()
        self.assert_no_labels()

    def test_external_inference_binding_drift_precedes_labels(self):
        self.binding["method_config"] = {"candidate": "K", "calibration": "forbidden"}
        self.reseal_base()
        with self.assertRaises(ValueError): d.run()
        self.assert_no_labels()

    def test_zero_or_nan_prediction_rejects_full_population_no_drop(self):
        first = next(iter(self.records))
        self.records[first]["prediction"]["weight"] = 0
        self.reseal_base()
        with self.assertRaisesRegex(d.DiagnosticError, "nonpositive_weight_invalid_full_population"):
            d.run()
        self.assert_no_labels()
        self.records[first]["prediction"]["weight"] = 90
        self.reseal_base()
        complete = self.base()
        for bad in (float("nan"), float("inf")):
            value = deepcopy(complete)
            value["records"][next(iter(self.records))]["prediction"]["weight"] = bad
            with self.subTest(value=bad), patch.object(d.k_score, "verified_base", return_value=value):
                with self.assertRaises(ValueError): d.run()
            self.assert_no_labels()
        self.assertFalse((self.root / d.OUTPUT).exists())

    def test_missing_sample_and_mismatched_metadata_rejected(self):
        record = self.records.pop(next(iter(self.records))); self.reseal_base()
        with self.assertRaises(ValueError): d.run()
        self.assert_no_labels()
        self.records[record["sample_id"]] = record
        record["fold"] = (record["fold"] + 1) % 5; self.reseal_base()
        with self.assertRaises(ValueError): d.run()
        self.assert_no_labels()

    def test_catalog_digest_and_math_source_drift_precede_labels(self):
        for name in (d.CATALOG, next(iter(d.MATH_PINS))):
            original = (self.root / name).read_bytes()
            self.put(name, original + b" ")
            with self.subTest(name=name), self.assertRaises(ValueError): d.run()
            self.assert_no_labels()
            self.put(name, original)

    def test_fixed_J_completion_pin_blocks_resealed_scope_change(self):
        self.reseal(d.J_OUTPUT, "aggregate", mutate_record=lambda value: value.update(scope="validation"))
        with self.assertRaisesRegex(d.DiagnosticError, "pinned_J_diagnostic_completion_changed"): d.run()
        self.assert_no_labels()

    def test_J_record_byte_tamper_is_rejected_before_labels(self):
        path = self.root / d.J_OUTPUT / "records" / (key_path("aggregate") + ".json")
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ArtifactError): d.run()
        self.assert_no_labels()

    def test_existing_own_seal_checked_before_labels(self):
        d.run(); self.reads.clear()
        path = self.root / d.OUTPUT / "records" / (key_path("aggregate") + ".json")
        path.write_bytes(path.read_bytes() + b" ")
        before = self.snapshot()
        with self.assertRaises(ArtifactError): d.run()
        self.assert_no_labels()
        self.assertEqual(before, self.snapshot())

    def test_labels_and_ingredients_require_original_pins(self):
        for name in (d.scorer.LABELS, d.INGREDIENTS):
            original = (self.root / name).read_bytes()
            self.put(name, original + b" ")
            with self.subTest(name=name), self.assertRaises(ValueError): d.run()
            self.assertFalse((self.root / d.OUTPUT).exists())
            self.put(name, original)

    def test_all_fallbacks_stay_in_84_oracle_without_fake_decomposition(self):
        for record in self.records.values():
            record.update(fallback=True, method_fallback=True, raw_prediction=None,
                          native_complete=False, raw_leaves=[], failure="synthetic_failure")
        self.reseal_base(); shutil.rmtree(self.root / d.k_score.OUTPUT)
        d.k_score.score(); self.reads.clear()
        value = d.run()["aggregate"]
        self.assertEqual(value["true_weight_oracle_point_metrics"]["weight"]["mae"], 0)
        self.assertEqual(value["decomposition"]["population_n"], 84)
        self.assertEqual(value["decomposition"]["whole_fallback_n"], 84)
        self.assertEqual(value["decomposition"]["decomposable_n"], 0)
        self.assertIsNone(value["mechanism_comparison"]["raw_K"]["available_id_reference_mass_fraction"])

    def test_output_has_only_independent_scope_and_no_arbitrary_binding_reads(self):
        self.binding["input_sha256"]["validation/private-labels.json"] = "f" * 64
        self.reseal_base()
        with self.assertRaises(ValueError): d.run()
        self.assertNotIn("validation/private-labels.json", self.reads)
        self.assert_no_labels()


if __name__ == "__main__":
    unittest.main()
