"""Only invented complete cohorts/seals; never call the real K verifier."""
from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
from types import FunctionType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from opt_provider import ProviderStop
from round4.src.artifacts import ArtifactStore, ArtifactError, canonical, decode, key_path
from round5.src import score_component as s


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ComponentScoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-K-score-", dir=Path(__file__).resolve().parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name in ("round4", "round5"):
            (self.root / name).mkdir(mode=0o700)
        self.rows, self.labels, self.records, self.preserved = [], {}, {}, []
        for dataset, count, groups in (("nutrition5k", 84, 78), ("asa24", 99, 23)):
            for index in range(count):
                sid = f"synthetic-{dataset}-{index:03d}"
                row = {"sample_id": sid, "dataset": dataset, "group_id": f"{dataset}-group-{index % groups:03d}",
                       "fold": index % groups % 5, "split": "dev"}
                self.rows.append(row)
                truth = {"weight": 100, "energy": 200, "fat": 10, "carbs": 30, "protein": 15}
                self.labels[sid] = {"truth": deepcopy(truth), "split": "dev"}
                pred = {key: row[key] for key in ("sample_id", "dataset", "group_id", "fold")}
                pred.update(prediction=deepcopy(truth), raw_prediction=deepcopy(truth), fallback=False,
                            method_fallback=False, repair_used=False, native_complete=True,
                            final_codes=[], primary_code=None, failure=None)
                if dataset == "nutrition5k":
                    pred["query_id"] = sid
                    self.records[sid] = pred
                else:
                    self.labels[sid].update(food_code="12345678", size="synthetic")
                    pred.update(final_codes=["12345678"], primary_code="12345678",
                                conditional={"prediction": deepcopy(truth), "fallback": False},
                                e2e={"prediction": deepcopy(truth), "fallback": False})
                    self.preserved.append(pred)
        self.contract = {"sources": ("round5/K_PROTOCOL.md", "round5/src/run_component.py"),
                         "method_config": {"candidate": "K", "calibration": None, "synthetic": True},
                         "protocol": "round5/K_PROTOCOL.md", "protocol_sha256": None,
                         "parent_completion_sha256": "a" * 64}
        for name in set(s.SOURCE_NAMES) | set(self.contract["sources"]):
            self.put(name, ("synthetic-bound-source:" + name).encode())
        self.contract["protocol_sha256"] = sha((self.root / self.contract["protocol"]).read_bytes())
        self.put(s.scorer.MANIFEST, b"".join(canonical(row) for row in self.rows))
        self.put(s.scorer.LABELS, canonical(self.labels))
        self.put(s.scorer.PRESERVED, canonical(self.preserved))
        freeze = {"status": "accepted_external_training_frozen", "binding": {"synthetic_exclusion": True}}
        freeze_sha = self.put(s.TRAIN_FREEZE, canonical(freeze))
        self.binding = {"phase": "development_component_base", "method_config": deepcopy(self.contract["method_config"]),
                        "query_count": 84, "query_groups": 78, "training_freeze_sha256": freeze_sha,
                        "training_exclusion_binding": freeze["binding"],
                        "parent_provenance": {"parent_completion_sha256": "a" * 64,
                                              "training_freeze_sha256": freeze_sha},
                        "input_sha256": {name: sha((self.root / name).read_bytes())
                            for name in (s.scorer.MANIFEST, s.TRAIN_FREEZE, *self.contract["sources"])}}
        self.reseal_base()
        # Execute the actual reviewed metric function with a separate globals
        # dictionary, leaving production BOOTSTRAP=10000 untouched.
        self.summary = FunctionType(s.scorer._summary.__code__,
            {**s.scorer._summary.__globals__, "BOOTSTRAP": 0}, name="synthetic_summary")
        old_predictions = deepcopy(list(self.records.values()))
        for item in old_predictions:
            item["prediction"] = {"weight": 250, "energy": 400, "fat": 20, "carbs": 75, "protein": 30}
        n5 = [row for row in self.rows if row["dataset"] == "nutrition5k"]
        self.raw_j = self.summary(self.rows, self.labels, n5, old_predictions, self.preserved)
        self.raw_j.update(candidate="J_service_continuation", calibration_applied=False)
        self.baseline = ArtifactStore(self.root / s.BASELINE_OUTPUT, {"synthetic_frozen_old_scoring": True},
            ["metrics"], verify_sources=lambda: None, root=self.root / "round4")
        self.baseline.finalize({"metrics": {"raw": self.raw_j,
            "calibrated": {"must_not_use": True}, "selection": {"selected_profile": "calibrated"}}})
        self.pins = {name: sha((self.root / name).read_bytes()) for name in s.PINNED_INPUTS}
        self.reads, self.base_calls = [], []
        outer = self

        class TrackingInputs(s.Inputs):
            def read(self, relative):
                outer.reads.append(relative)
                return super().read(relative)

        for item in (patch.object(s, "ROOT", self.root), patch.object(s, "PINNED_INPUTS", self.pins),
                     patch.object(s, "Inputs", TrackingInputs), patch.object(s, "verified_base", self.base),
                     patch.object(s, "driver_contract", lambda: deepcopy(self.contract)),
                     patch.object(s, "summarize", self.summary)):
            item.start()
            self.addCleanup(item.stop)

    def put(self, name, raw):
        path = self.root / name
        parent = self.root
        for part in path.parent.relative_to(self.root).parts:
            parent /= part
            parent.mkdir(mode=0o700, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)
        return sha(raw)

    def reseal_base(self):
        if (self.root / s.BASE_OUTPUT).exists():
            shutil.rmtree(self.root / s.BASE_OUTPUT)
        self.base_store = ArtifactStore(self.root / s.BASE_OUTPUT, self.binding, self.records,
                                       verify_sources=lambda: None, root=self.root / "round5")
        self.base_store.finalize(self.records)

    def base(self):
        self.base_calls.append(True)
        records = self.base_store.verify_completed()
        return {"status": "base_verified", "n": len(records), "records": records,
                "binding": deepcopy(self.binding), "completion_sha256": sha((self.root / s.BASE_COMPLETION).read_bytes()),
                "provider_constructed": False, "validation_opened": False}

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob("*") if path.is_file()}

    def test_complete_score_reuses_exact_raw_j_and_preserved_asa_no_calibration(self):
        result = s.score()
        value = result["metrics"]
        self.assertEqual(result["status"], "component_scoring_complete")
        self.assertEqual(len(self.base_calls), 2)
        self.assertEqual(value["raw_j"], self.raw_j)
        self.assertEqual(value["comparison_to_raw_j"]["selected_candidate"], "K")
        self.assertEqual(value["comparison_to_raw_j"]["K"]["check_count"], 10)
        self.assertEqual(value["comparison_to_raw_j"]["K_joint"]["check_count"], 20)
        self.assertEqual(value["nutrition5k"]["primary"]["n"], 84)
        self.assertEqual(value["joint_metrics_with_preserved_asa"]["datasets"]["asa24"]["primary"]["n"], 99)
        self.assertEqual(value["joint_metrics_with_preserved_asa"]["passed_checks"], 20)
        self.assertFalse(value["calibration_applied"] or result["provider_constructed"] or result["validation_opened"])
        self.assertEqual(s.scorer.BOOTSTRAP, 10000)
        self.assertFalse((self.root / "round5/calibration").exists())

    def test_partial_invalid_status_or_provider_construction_blocks_before_reader(self):
        good = self.base()
        variants = [{**good, "n": 83}, {**good, "provider_constructed": True},
                    {**good, "validation_opened": True}, {**good, "status": "base_complete_unscored"},
                    {**good, "records": dict(list(good["records"].items())[:-1])}]
        for value in variants:
            with self.subTest(value=value["status"]), patch.object(s, "verified_base", return_value=value):
                with self.assertRaises(s.ScoreError):
                    s.score()
        self.assertEqual(self.reads, [])

    def test_counter_or_authentication_stop_propagates_without_reader_or_fallback(self):
        for error in (ProviderStop("synthetic budget exhausted"), ProviderStop("synthetic auth failure"),
                      ValueError("synthetic counter audit failure")):
            with self.subTest(error=type(error).__name__), patch.object(s, "verified_base", side_effect=error):
                with self.assertRaises(type(error)):
                    s.score()
        self.assertEqual(self.reads, [])
        self.assertFalse((self.root / s.OUTPUT).exists())

    def test_K_record_tamper_rejected_before_any_label_read(self):
        path = self.root / s.BASE_OUTPUT / "records" / (key_path(next(iter(self.records))) + ".json")
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ArtifactError):
            s.score()
        self.assertEqual(self.reads, [])

    def test_old_J_record_or_completion_mutation_rejected_before_labels(self):
        path = self.root / s.BASELINE_OUTPUT / "records" / (key_path("metrics") + ".json")
        path.write_bytes(path.read_bytes() + b" ")
        before = self.snapshot()
        with self.assertRaises(ArtifactError):
            s.score()
        self.assertNotIn(s.scorer.LABELS, self.reads)
        self.assertEqual(self.snapshot(), before)

    def test_resealed_different_J_cannot_replace_fixed_baseline_pin(self):
        shutil.rmtree(self.root / s.BASELINE_OUTPUT)
        replacement = deepcopy(self.raw_j)
        replacement["candidate"] = "different-J"
        self.baseline.finalize({"metrics": {"raw": replacement}})
        with self.assertRaisesRegex(s.ScoreError, "pinned_scoring_input_changed"):
            s.score()
        self.assertNotIn(s.scorer.LABELS, self.reads)

    def test_method_training_and_label_binding_gates_precede_labels(self):
        original = deepcopy(self.binding)
        mutations = [lambda b: b["method_config"].update(calibration="forbidden"),
                     lambda b: b["input_sha256"].update({s.scorer.LABELS: "f" * 64}),
                     lambda b: b.update(training_freeze_sha256="f" * 64),
                     lambda b: b["parent_provenance"].update(parent_completion_sha256="f" * 64)]
        for mutate in mutations:
            self.binding = deepcopy(original)
            mutate(self.binding)
            self.reseal_base()
            self.reads.clear()
            with self.assertRaises(s.ScoreError):
                s.score()
            self.assertNotIn(s.scorer.LABELS, self.reads)

    def test_source_and_manifest_pin_changes_rejected_before_labels(self):
        for name in ("round4/src/score_dev.py", s.scorer.MANIFEST, "round5/src/run_component.py"):
            with self.subTest(name=name):
                original = (self.root / name).read_bytes()
                self.put(name, original + b" ")
                self.reads.clear()
                with self.assertRaises(s.ScoreError):
                    s.score()
                self.assertNotIn(s.scorer.LABELS, self.reads)
                self.put(name, original)

    def test_preserved_ASA_change_rejected_before_labels(self):
        self.put(s.scorer.PRESERVED, canonical(self.preserved[:-1]))
        with self.assertRaises(s.ScoreError):
            s.score()
        self.assertNotIn(s.scorer.LABELS, self.reads)

    def test_missing_prediction_rejected_before_labels_and_fallbacks_keep_all84(self):
        first = next(iter(self.records))
        saved = self.records[first]["prediction"]
        self.records[first]["prediction"] = None
        self.reseal_base()
        with self.assertRaises(ValueError):
            s.score()
        self.assertNotIn(s.scorer.LABELS, self.reads)
        self.records[first]["prediction"] = saved
        for pred in self.records.values():
            pred.update(raw_prediction=None, fallback=True, native_complete=False,
                        failure="synthetic_contract_failure")
        self.reseal_base()
        value = s.score()["metrics"]
        self.assertEqual(value["nutrition5k"]["primary"]["n"], 84)
        self.assertEqual(value["nutrition5k"]["primary"]["available_n"], 84)
        self.assertEqual(value["nutrition5k"]["fallback_n"], 84)
        self.assertEqual(value["nutrition5k"]["complete_subset"]["n"], 0)

    def test_missing_label_rejected_without_scoring_artifacts(self):
        del self.labels[next(iter(self.labels))]
        self.pins[s.scorer.LABELS] = self.put(s.scorer.LABELS, canonical(self.labels))
        with self.assertRaisesRegex(s.ScoreError, "registered_development_label_population"):
            s.score()
        self.assertFalse((self.root / s.OUTPUT).exists())

    def test_repeat_is_readonly_and_checks_existing_score_seal_before_labels(self):
        first = s.score()
        before = self.snapshot()
        second = s.score()
        self.assertEqual(second["status"], "component_scoring_verified")
        self.assertEqual(second["metrics"], first["metrics"])
        self.assertEqual(self.snapshot(), before)
        path = self.root / s.OUTPUT / "records" / (key_path("metrics") + ".json")
        path.write_bytes(path.read_bytes() + b" ")
        before = self.snapshot()
        self.reads.clear()
        with self.assertRaises(ArtifactError):
            s.score()
        self.assertNotIn(s.scorer.LABELS, self.reads)
        self.assertEqual(self.snapshot(), before)

    def test_second_K_verification_blocks_seal_when_base_changes_during_summary(self):
        def changed(*args):
            result = self.summary(*args)
            path = self.root / s.BASE_OUTPUT / "records" / (key_path(next(iter(self.records))) + ".json")
            path.write_bytes(path.read_bytes() + b" ")
            return result
        with patch.object(s, "summarize", changed), self.assertRaises(ArtifactError):
            s.score()
        self.assertFalse((self.root / s.OUTPUT).exists())

    def test_same_inputs_but_recomputed_metric_drift_is_rejected_without_write(self):
        s.score()
        before = self.snapshot()
        def changed(*args):
            result = self.summary(*args)
            result["nutrition5k_failure_audit"]["repair_used_n"] = 1
            return result
        with patch.object(s, "summarize", changed), self.assertRaisesRegex(s.ScoreError, "recomputed_K_metrics"):
            s.score()
        self.assertEqual(self.snapshot(), before)


class WholeProfileTests(unittest.TestCase):
    def metrics(self, ratio=2.0):
        checks = []
        for dataset in s.scorer.metrics.DATASETS:
            for target in s.scorer.metrics.KEYS:
                for index, stat in enumerate(("mae", "per_unit")):
                    cap = s.scorer.metrics.THRESHOLDS[dataset][target][index]
                    value = cap * (.5 if dataset == "asa24" else ratio)
                    checks.append({"dataset": dataset, "target": target, "statistic": stat,
                                   "value": value, "threshold": cap, "pass": value <= cap})
        return {"checks": checks, "datasets": {"asa24": {"fixed": True}}}

    def test_tie_keeps_J_and_any_cap_regression_blocks_other_improvements(self):
        raw = self.metrics()
        self.assertEqual(s.compare_raw_j(raw, deepcopy(raw))["selected_candidate"], "J")
        candidate = self.metrics(1.5)
        raw["checks"][10].update(value=raw["checks"][10]["threshold"], **{"pass": True})
        result = s.compare_raw_j(raw, candidate)
        self.assertEqual(result["selected_candidate"], "J")
        self.assertEqual(result["reason"], "K_crossed_a_previously_passed_cap")

    def test_full_precision_improvement_and_equal_max_lower_mean(self):
        raw = self.metrics()
        self.assertEqual(s.compare_raw_j(raw, self.metrics(2 - 1e-12))["selected_candidate"], "K")
        candidate = deepcopy(raw)
        candidate["checks"][10]["value"] *= .9
        result = s.compare_raw_j(raw, candidate)
        self.assertEqual(result["selected_candidate"], "K")
        self.assertEqual(result["reason"], "equal_worst_and_strictly_lower_mean_ratio")

    def test_undefined_zero_reference_is_not_zero_or_pass_and_ASA_cannot_change(self):
        raw, candidate = self.metrics(), self.metrics(1.5)
        candidate["checks"][11].update(value=None, **{"pass": False})
        result = s.compare_raw_j(raw, candidate)
        self.assertEqual(result["selected_candidate"], "J")
        self.assertIsNone(result["K"]["worst_ratio"])
        self.assertEqual(result["K"]["undefined_checks"], 1)
        candidate["checks"][11]["pass"] = True
        with self.assertRaises(s.ScoreError):
            s.compare_raw_j(raw, candidate)
        candidate = self.metrics(1.5)
        candidate["datasets"]["asa24"] = {"fixed": False}
        with self.assertRaisesRegex(s.ScoreError, "preserved_ASA"):
            s.compare_raw_j(raw, candidate)


if __name__ == "__main__":
    unittest.main()
