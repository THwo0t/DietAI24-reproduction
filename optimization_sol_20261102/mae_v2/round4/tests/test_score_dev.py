"""Completed-development scoring with synthetic sealed 84+99 populations."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

V2 = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(V2), str(V2 / "src")]
from round4.src import score_dev as score
from round4.src.artifacts import ArtifactStore, ArtifactError, canonical, key_path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ScoreDevTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="r4-score-synthetic-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "round4").mkdir(mode=0o700)
        self.rows, self.labels, self.records, self.preserved = [], {}, {}, []
        for dataset, count, groups in (("nutrition5k", 84, 78), ("asa24", 99, 23)):
            for index in range(count):
                sid, group = f"synthetic-{dataset}-{index:03d}", f"group-{dataset}-{index % groups:03d}"
                row = {"sample_id": sid, "dataset": dataset, "group_id": group,
                       "fold": index % groups % 5, "split": "dev"}
                self.rows.append(row)
                truth = {"weight": 100, "energy": 200, "fat": 10, "carbs": 30, "protein": 15}
                self.labels[sid] = {"truth": truth, "split": "dev"}
                pred = {key: row[key] for key in ("sample_id", "dataset", "group_id", "fold")}
                pred.update(prediction=deepcopy(truth), raw_prediction=deepcopy(truth),
                            fallback=False, method_fallback=False, repair_used=False,
                            native_complete=True, final_codes=[], primary_code=None, failure=None)
                if dataset == "nutrition5k":
                    pred["query_id"] = sid
                    self.records[sid] = pred
                    # The old N5 branch must never enter candidate J scoring.
                    self.preserved.append({**deepcopy(pred), "prediction": dict.fromkeys(truth, 999999)})
                else:
                    self.labels[sid].update(food_code="12345678", size="synthetic")
                    pred.update(final_codes=["12345678"], primary_code="12345678",
                                conditional={"prediction": deepcopy(truth), "fallback": False},
                                e2e={"prediction": deepcopy(truth), "fallback": False})
                    self.preserved.append(pred)
        for relative in score.SOURCE_NAMES:
            self.put(relative, (V2 / relative).read_bytes())
        self.put(score.MANIFEST, b"".join(canonical(row) for row in self.rows))
        self.put(score.LABELS, canonical(self.labels))
        self.put(score.PRESERVED, canonical(self.preserved))
        self.pins = {relative: sha((self.root / relative).read_bytes()) for relative in score.PINNED_INPUTS}
        self.base_store = ArtifactStore(self.root / "round4/runs/J", {"synthetic_base": 1},
            self.records, verify_sources=lambda: None, root=self.root / "round4")
        self.base_store.finalize(self.records)
        self.base_calls, self.bootstrap_calls, self.reads = [], [], []
        def base(**kwargs):
            self.base_calls.append(kwargs)
            self.assertEqual(kwargs, {"verify_only": True})
            records = self.base_store.verify_completed()
            return {"status": "base_verified", "n": len(records), "records": records,
                    "provider_constructed": False, "validation_opened": False}
        self.verified_base = base
        def bootstrap(rows, dataset, count, seed):
            # Metric arithmetic still uses the reviewed real evaluate function.
            # The expensive, already-tested bootstrap sampler is replaced only
            # here; verify that the scoring entry point requests exactly 10,000.
            self.bootstrap_calls.append((dataset, len(rows), count, seed))
            return {"replicates": count, "seed": seed, "confidence": .95,
                    "unit": "manifest_group_id", "intervals": {"synthetic": {"low": 0, "high": 0}}}
        original_read = score.Inputs.read
        def read(reader, relative):
            self.reads.append(relative)
            return original_read(reader, relative)
        for patcher in (patch.object(score, "ROOT", self.root),
                        patch.object(score, "PINNED_INPUTS", self.pins),
                        patch.object(score.run_base, "base", base),
                        patch.object(score.metrics, "_bootstrap", bootstrap),
                        patch.object(score.Inputs, "read", read)):
            patcher.start(); self.addCleanup(patcher.stop)

    def put(self, relative, raw):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def repin(self, relative, raw):
        self.put(relative, raw)
        self.pins[relative] = sha(raw)

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): (path.stat().st_mtime_ns, path.read_bytes())
                for path in self.root.rglob("*") if path.is_file()}

    @contextmanager
    def base_result(self, result):
        with patch.object(score.run_base, "base", return_value=result):
            yield

    def test_fixed_full_populations_metrics_checks_and_bootstrap_are_sealed(self):
        with patch.object(score.run_base, "_provider", side_effect=AssertionError("no provider")):
            result = score.score()
        self.assertEqual(result["status"], "scoring_complete")
        summary = result["metrics"]
        self.assertEqual(summary["scope"], "development_not_independent_validation")
        self.assertEqual(summary["candidate"], "J")
        self.assertFalse(summary["validation_opened"] or summary["calibration_applied"])
        self.assertFalse(result["provider_constructed"])
        self.assertEqual(summary["populations"], {"nutrition5k": {"n": 84, "groups": 78},
                                                 "asa24": {"n": 99, "groups": 23}})
        self.assertEqual(summary["nutrition5k"]["primary"]["n"], 84)
        self.assertEqual(summary["nutrition5k_passed_checks"], 10)
        self.assertEqual(len(summary["nutrition5k_checks"]), 10)
        joint = summary["joint_metrics_with_preserved_asa"]
        self.assertEqual(joint["datasets"]["asa24"]["n"], 99)
        self.assertEqual(joint["datasets"]["asa24"]["exact_n"], 99)
        self.assertEqual(joint["passed_checks"], 20)
        self.assertEqual(joint["datasets"]["nutrition5k"]["primary"]["metrics"]["weight"]["mae"], 0)
        self.assertEqual(self.bootstrap_calls, [("asa24", 0, 10000, 20261102),
            ("nutrition5k", 84, 10000, 20261102), ("asa24", 99, 10000, 20261102),
            ("nutrition5k", 84, 10000, 20261102)])
        self.assertEqual(len(self.base_calls), 2)
        binding = json.loads((self.root / score.OUTPUT / "intent.json").read_text())["binding"]
        self.assertEqual(binding["input_sha256"][score.LABELS], self.pins[score.LABELS])
        self.assertEqual(binding["input_sha256"]["src/opt_metrics.py"], self.pins["src/opt_metrics.py"])
        self.assertIn("round4/src/score_dev.py", binding["input_sha256"])
        self.assertEqual(binding["base_completion_sha256"], sha((self.root / score.BASE_COMPLETION).read_bytes()))

    def test_failed_base_seal_is_rejected_before_any_label_read(self):
        with patch.object(score.run_base, "base", side_effect=ArtifactError("missing seal")):
            with self.assertRaises(ArtifactError):
                score.score()
        self.assertEqual(self.reads, [])
        self.assertFalse((self.root / score.OUTPUT).exists())

    def test_incomplete_or_paid_base_status_is_rejected_before_label_reader(self):
        valid = self.verified_base(verify_only=True)
        cases = [{**valid, "n": 83}, {**valid, "provider_constructed": True},
                 {**valid, "validation_opened": True}, {**valid, "status": "base_complete_unscored"},
                 {**valid, "records": dict(list(valid["records"].items())[:-1])}]
        for result in cases:
            with self.subTest(fields=list(result)), self.base_result(result), self.assertRaises(score.ScoreError):
                score.score()
        self.assertEqual(self.reads, [])

    def test_changed_pinned_inputs_and_reviewed_metric_source_are_rejected(self):
        for relative in score.PINNED_INPUTS:
            before = (self.root / relative).read_bytes()
            self.put(relative, before + b" ")
            self.reads.clear()
            with self.subTest(relative=relative), self.assertRaisesRegex(score.ScoreError, "pinned_scoring_input_changed"):
                score.score()
            if relative != score.LABELS:
                self.assertNotIn(score.LABELS, self.reads)
            self.put(relative, before)
        self.assertFalse((self.root / score.OUTPUT).exists())

    def test_registered_manifest_counts_groups_folds_and_split_cannot_change(self):
        variants = []
        rows = deepcopy(self.rows); rows.pop(); variants.append(rows)
        rows = deepcopy(self.rows); rows[0]["sample_id"] = rows[1]["sample_id"]; variants.append(rows)
        rows = deepcopy(self.rows); rows[0]["group_id"] = "different"; variants.append(rows)
        rows = deepcopy(self.rows); rows[0]["fold"] = 4; variants.append(rows)
        rows = deepcopy(self.rows); rows[0]["split"] = "validation"; variants.append(rows)
        rows = deepcopy(self.rows); rows[-1]["dataset"] = "nutrition5k"; variants.append(rows)
        for index, rows in enumerate(variants):
            self.repin(score.MANIFEST, b"".join(canonical(row) for row in rows))
            self.reads.clear()
            with self.subTest(case=index), self.assertRaises(score.ScoreError):
                score.score()
            self.assertNotIn(score.LABELS, self.reads)

    def test_incomplete_prediction_never_silently_shrinks_the_84_denominator(self):
        valid = self.verified_base(verify_only=True)
        sid = next(iter(valid["records"]))
        for mutation in (lambda p: p.update(prediction=None),
                         lambda p: p.update(group_id="changed"),
                         lambda p: p.update(query_id="changed"),
                         lambda p: p.update(fallback="yes")):
            changed = deepcopy(valid); mutation(changed["records"][sid]); self.reads.clear()
            with self.base_result(changed), self.assertRaises(score.ScoreError):
                score.score()
            self.assertNotIn(score.LABELS, self.reads)

    def test_whole_fallback_stays_in_all84_metrics_and_failure_counts(self):
        valid = self.verified_base(verify_only=True)
        sid = next(iter(valid["records"]))
        valid["records"][sid].update(prediction=dict.fromkeys(score.metrics.KEYS, 0), raw_prediction=None,
            fallback=True, repair_used=True, native_complete=False, failure="estimate:contract_failure")
        with self.base_result(valid):
            summary = score.score()["metrics"]
        n5 = summary["nutrition5k"]
        self.assertEqual(n5["primary"]["n"], 84)
        self.assertEqual(n5["primary"]["available_n"], 84)
        self.assertEqual(n5["complete_subset"]["n"], 83)
        self.assertEqual(n5["fallback_n"], 1)
        self.assertAlmostEqual(n5["primary"]["metrics"]["weight"]["mae"], 100 / 84)
        self.assertEqual(summary["nutrition5k_failure_audit"], {"whole_fallback_n": 1,
            "method_fallback_n": 0, "repair_used_n": 1, "nonempty_failure_n": 1, "missing_prediction_n": 0})

    def test_preserved_asa_population_and_metadata_must_match_manifest(self):
        variants = []
        selected = deepcopy(self.preserved); selected.pop(); variants.append(selected)
        selected = deepcopy(self.preserved); selected[-1] = selected[-2]; variants.append(selected)
        selected = deepcopy(self.preserved); selected[-1]["group_id"] = "changed"; variants.append(selected)
        for selected in variants:
            self.repin(score.PRESERVED, canonical(selected)); self.reads.clear()
            with self.assertRaises(score.ScoreError):
                score.score()
            self.assertNotIn(score.LABELS, self.reads)

    def test_label_population_and_sealed_provenance_are_rejected(self):
        variants = []
        labels = deepcopy(self.labels); labels.pop(next(iter(labels))); variants.append(labels)
        labels = deepcopy(self.labels); labels["extra"] = next(iter(labels.values())); variants.append(labels)
        labels = deepcopy(self.labels); labels[next(iter(labels))]["sealed"] = True; variants.append(labels)
        for labels in variants:
            self.repin(score.LABELS, canonical(labels))
            with self.assertRaises(ValueError):
                score.score()
        self.assertFalse((self.root / score.OUTPUT).exists())

    def test_record_tamper_breaks_real_base_artifact_seal_before_labels(self):
        sid = next(iter(self.records))
        path = self.root / "round4/runs/J/records" / (key_path(sid) + ".json")
        value = json.loads(path.read_text()); value["record"]["prediction"]["weight"] = 999
        path.write_bytes(canonical(value))
        with self.assertRaises(ArtifactError):
            score.score()
        self.assertEqual(self.reads, [])

    def test_repeated_completed_score_recomputes_and_is_strictly_read_only(self):
        first = score.score(); before = self.snapshot(); calls = len(self.bootstrap_calls)
        second = score.score()
        self.assertEqual(second["status"], "scoring_verified")
        self.assertEqual(first["metrics"], second["metrics"])
        self.assertEqual(len(self.bootstrap_calls), calls + 4)
        self.assertEqual(before, self.snapshot())

    def test_recomputed_metric_mismatch_rejects_and_does_not_rewrite(self):
        score.score(); before = self.snapshot()
        evaluate = score.metrics.evaluate
        def changed(*args, **kwargs):
            value = evaluate(*args, **kwargs)
            value["datasets"]["nutrition5k"]["primary"]["metrics"]["weight"]["mae"] = .001
            return value
        with patch.object(score.metrics, "evaluate", changed), self.assertRaisesRegex(
                score.ScoreError, "recomputed_metrics_differ_from_seal"):
            score.score()
        self.assertEqual(before, self.snapshot())

    def test_completed_scoring_source_drift_refuses_new_binding(self):
        score.score()
        path = self.root / "round4/src/score_dev.py"
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
        before = self.snapshot()
        with self.assertRaises(ArtifactError):
            score.score()
        self.assertEqual(before, self.snapshot())

    def test_base_changed_during_score_is_rejected_without_scoring_output(self):
        first = self.verified_base(verify_only=True); second = deepcopy(first)
        second["records"][next(iter(second["records"]))]["prediction"]["weight"] = 999
        with patch.object(score.run_base, "base", side_effect=[first, second]), self.assertRaisesRegex(
                score.ScoreError, "base_changed_during_scoring"):
            score.score()
        self.assertFalse((self.root / score.OUTPUT).exists())


if __name__ == "__main__":
    unittest.main()
