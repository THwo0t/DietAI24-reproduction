"""Completed-F audit tests use only synthetic development data and artifacts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import audit_round3 as audit
from direct_estimator import _parse, _macro_mass_excess


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, bytes) else (json.dumps(value, allow_nan=False) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def fixture(root):
    core_names = ("cohorts_v2.py", "legacy_adapter.py", "metrics_v2.py", "opt_metrics.py",
                  "opt_pipeline.py", "opt_provider.py", "pipeline_v2.py", "study.py", "validation_adapter.py")
    source_hashes = {name: write(root, "src/" + name, ("# synthetic " + name).encode())
                     for name in core_names}
    round_hashes = {"src/" + name: write(root, "round3/src/" + name, ("# synthetic " + name).encode())
                    for name in ("run_round3.py", "direct_estimator.py")}
    round_hashes["PROTOCOL.md"] = write(root, "round3/PROTOCOL.md", b"synthetic protocol")
    rows, labels, artifacts = [], {}, {}
    for dataset, count, groups in (("nutrition5k", 84, 78), ("asa24", 99, 23)):
        for index in range(count):
            sid = dataset + "-synthetic-" + str(index)
            pixels = ("synthetic image bytes " + sid).encode()
            digest = hashlib.sha256(pixels).hexdigest()
            relative = "data/" + dataset + "/dev/images/" + digest + ".png"
            artifacts[relative] = write(root, relative, pixels)
            row = {"sample_id": sid, "dataset": dataset, "group_id": dataset + str(index % groups),
                   "fold": (index % groups) % 5, "split": "dev", "image_path": relative,
                   "image_sha256": digest}
            rows.append(row)
            truth = dict(zip(audit.metrics.KEYS, (200.0 + row["fold"], 200.0, 8.0, 20.0, 12.0)))
            labels[sid] = {"split": "dev", "truth": truth}
            if dataset == "asa24":
                labels[sid].update(food_code="10000001", size="medium")
    manifest = b"".join((json.dumps(row) + "\n").encode() for row in rows)
    artifacts["data/cohorts/dev.jsonl"] = write(root, "data/cohorts/dev.jsonl", manifest)
    artifacts["data/cohorts/dev_labels.json"] = write(root, "data/cohorts/dev_labels.json", labels)
    freeze = {"seed": audit.cohorts_v2.SEED,
              "rules_sha256": audit.cohorts_v2.digest(audit.cohorts_v2.json_bytes(audit.cohorts_v2.RULES)),
              "artifacts": artifacts, "counts": {"nutrition5k": 84, "asa24": 99}}
    freeze_hash = write(root, "data/cohorts/dev_freeze.json", freeze)
    n5 = [row for row in rows if row["dataset"] == "nutrition5k"]
    binding = {"candidate": "F", "scope": "development_only", "model": "gpt-6.1-sol",
               "temperature": 1, "max_completion_tokens": 8192,
               "protocol_sha256": round_hashes["PROTOCOL.md"],
               "source_sha256": {**source_hashes, **{"round3/" + name: round_hashes["src/" + name]
                   for name in ("run_round3.py", "direct_estimator.py")}},
               "dev_freeze_sha256": freeze_hash, "manifest_sha256": audit.fingerprint(n5),
               "validation_access": False}
    write(root, audit.RUN + "/binding.json", binding)
    raw = json.dumps({"items": [{"item_id": "i1", "description": "synthetic food",
        "weight": 170, "energy": 150, "fat": 5, "carbs": 17, "protein": 10}]})
    items, prediction = _parse(raw)
    records, seal = [], {}
    for index, row in enumerate(n5):
        record = {key: row[key] for key in ("sample_id", "dataset", "group_id", "fold")}
        failed = index == 0
        repaired = index in (0, 1)
        record.update({"prediction": audit.metrics.fold_medians(n5, labels, row["fold"]) if failed else prediction,
            "raw_prediction": None if failed else prediction, "fallback": failed,
            "fallback_reason": "invalid_json" if failed else None,
            "native_complete": not failed and not repaired, "repair_used": repaired,
            "final_codes": [], "primary_code": None, "items": [] if failed else items,
            "raw_outputs": ["bad", "bad"] if failed else (["bad", raw] if repaired else [raw]),
            "audit": {"macro_mass_excess_items": [], "macro_mass_excess_total": None if failed else False},
            "method": "F_direct_visual_nutrients"})
        records.append(deepcopy(record))
        envelope = {"binding_sha256": audit.fingerprint(binding), "record": record,
                    "record_sha256": audit.fingerprint(record)}
        seal[row["sample_id"]] = write(root, audit.RUN + "/records/" + audit._record_name(row), envelope)
    write(root, audit.RUN + "/records_sealed.json", seal)
    write(root, audit.RUN + "/predictions.json", records)
    fixed = []
    for row in rows:
        p = {key: row[key] for key in ("sample_id", "dataset", "group_id", "fold")}
        p.update(prediction=labels[row["sample_id"]]["truth"], native_complete=True,
                 fallback=False, repair_used=False)
        if row["dataset"] == "asa24":
            p.update(final_codes=["10000001"], primary_code="10000001",
                     conditional={"prediction": p["prediction"]}, e2e={"prediction": p["prediction"]})
        fixed.append(p)
    selected_path, selection_path = "runs/development/selected_oof_predictions.json", "runs/development/selection.json"
    selected_hash = write(root, selected_path, fixed)
    selection = {"metrics": audit.metrics.evaluate(rows, labels, fixed)}
    selection_hash = write(root, selection_path, selection)
    review_metric = {"input_sha256": {selected_path: selected_hash, selection_path: selection_hash,
        **{name: audit._sha(root, name) for name in ("data/cohorts/dev.jsonl", "data/cohorts/dev_labels.json",
                                                   "data/cohorts/dev_freeze.json")}}}
    anchors = {"evidence/R-M2-4-1.json": write(root, "evidence/R-M2-4-1.json", review_metric),
               "evidence/review-one-completion.json": write(root, "evidence/review-one-completion.json",
                    {"code_sha256": source_hashes, "selection_sha256": selection_hash}),
               "round3/evidence/preflight.json": write(root, "round3/evidence/preflight.json", {"sha256": round_hashes})}
    asa = [p for p in fixed if p["dataset"] == "asa24"]
    result = {"scope": "development_not_independent_validation", "candidate": "F",
              "nutrition5k": audit.metrics.evaluate(n5, labels, records)["datasets"]["nutrition5k"],
              "joint_metrics_with_preserved_asa": audit.metrics.evaluate(rows, labels, asa + records),
              "selected_C_reference": selection["metrics"]["datasets"]["nutrition5k"], "validation_opened": False}
    write(root, audit.RUN + "/metrics.json", result)
    write(root, audit.RUN + "/completion.json", {"completed": "2026-11-03T00:00:00+00:00", "n": 84,
        "groups": 78, "binding_sha256": audit.fingerprint(binding), "validation_opened": False})
    return anchors, n5, records


class AuditRound3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r3-audit-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        anchors, self.rows, self.records = fixture(self.root)
        self.anchor_patch = patch.object(audit, "TRUSTED_ANCHORS", anchors)
        self.anchor_patch.start()
        self.addCleanup(self.anchor_patch.stop)

    def test_complete_synthetic_population_audits_and_writes_only_receipt(self):
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        original = Path.open
        def guarded(path, *args, **kwargs):
            if any(word in path.parts for word in ("validation", "sealed")) or path.name == ".env":
                raise AssertionError("Forbidden validation or credential access")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            result = audit.run(self.root)
            self.assertEqual(audit.run(self.root), result)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["counts"], {"nutrition5k": 84, "nutrition5k_groups": 78,
                                          "asa24": 99, "fallback": 1, "repaired": 2})
        for relative, data in before.items():
            self.assertEqual((self.root / relative).read_bytes(), data)
        after_names = {str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after_names - set(before), {audit.OUTPUT})
        self.assertNotIn("nutrition5k-synthetic", json.dumps(result))
        self.assertNotIn("raw_outputs", json.dumps(result))

    def test_completion_required_before_any_development_access(self):
        (self.root / audit.RUN / "completion.json").unlink()
        with patch.object(audit.cohorts_v2, "verify_dev_only", side_effect=AssertionError("dev opened")):
            with self.assertRaises(audit.AuditError):
                audit.audit(self.root)

    def test_changed_asa_source_is_rejected(self):
        relative = "runs/development/selected_oof_predictions.json"
        value = audit._load(self.root, relative)
        value[-1]["conditional"]["prediction"]["weight"] += 1
        write(self.root, relative, value)
        with self.assertRaisesRegex(audit.AuditError, "ASA prediction"):
            audit.audit(self.root)

    def test_changed_c_selection_source_is_rejected(self):
        relative = "runs/development/selection.json"
        value = audit._load(self.root, relative)
        value["metrics"]["datasets"]["nutrition5k"]["n"] = 1
        write(self.root, relative, value)
        with self.assertRaisesRegex(audit.AuditError, "C selection"):
            audit.audit(self.root)

    def test_self_consistent_envelope_tamper_still_fails_external_seal(self):
        relative = audit.RUN + "/records/" + audit._record_name(self.rows[2])
        value = audit._load(self.root, relative)
        value["record"]["prediction"]["weight"] += 1
        value["record_sha256"] = audit.fingerprint(value["record"])
        write(self.root, relative, value)
        with self.assertRaisesRegex(audit.AuditError, "external seal"):
            audit.audit(self.root)

    def test_missing_record_cannot_be_scored(self):
        (self.root / audit.RUN / "records" / audit._record_name(self.rows[-1])).unlink()
        with patch.object(audit.metrics, "evaluate", side_effect=AssertionError("partial scoring")):
            with self.assertRaisesRegex(audit.AuditError, "population differs"):
                audit.audit(self.root)

    def test_metric_mismatch_fails_without_writing_receipt(self):
        relative = audit.RUN + "/metrics.json"
        value = audit._load(self.root, relative)
        value["nutrition5k"]["primary"]["metrics"]["protein"]["mae"] += 1e-10
        write(self.root, relative, value)
        with self.assertRaisesRegex(audit.AuditError, "full-precision"):
            audit.run(self.root)
        self.assertFalse((self.root / audit.OUTPUT).exists())

    def test_resealed_wrong_fallback_still_fails_training_fold_recomputation(self):
        row = self.rows[0]
        relative = audit.RUN + "/records/" + audit._record_name(row)
        value = audit._load(self.root, relative)
        value["record"]["prediction"]["weight"] = 999.0
        value["record_sha256"] = audit.fingerprint(value["record"])
        digest = write(self.root, relative, value)
        seal = audit._load(self.root, audit.RUN + "/records_sealed.json")
        seal[row["sample_id"]] = digest
        write(self.root, audit.RUN + "/records_sealed.json", seal)
        with self.assertRaisesRegex(audit.AuditError, "training-fold fallback"):
            audit.audit(self.root)

    def test_resealed_wrong_item_totals_still_fail_raw_recomputation(self):
        row = self.rows[2]
        relative = audit.RUN + "/records/" + audit._record_name(row)
        value = audit._load(self.root, relative)
        value["record"]["items"][0]["energy"] += 1
        value["record_sha256"] = audit.fingerprint(value["record"])
        digest = write(self.root, relative, value)
        seal = audit._load(self.root, audit.RUN + "/records_sealed.json")
        seal[row["sample_id"]] = digest
        write(self.root, audit.RUN + "/records_sealed.json", seal)
        with self.assertRaisesRegex(audit.AuditError, "raw-item sums"):
            audit.audit(self.root)

    def test_source_or_evidence_drift_is_rejected(self):
        for relative in ("src/opt_metrics.py", "round3/src/direct_estimator.py", "round3/evidence/preflight.json"):
            path = self.root / relative
            old = path.read_bytes()
            path.write_bytes(old + b" ")
            with self.subTest(relative=relative), self.assertRaises(audit.AuditError):
                audit.audit(self.root)
            path.write_bytes(old)

    def test_dev_image_hash_drift_is_rejected(self):
        (self.root / self.rows[0]["image_path"]).write_bytes(b"changed image")
        with self.assertRaises(audit.AuditError):
            audit.audit(self.root)

    def test_different_receipt_is_never_overwritten(self):
        write(self.root, audit.OUTPUT, {"status": "unrelated old receipt"})
        before = (self.root / audit.OUTPUT).read_bytes()
        with self.assertRaisesRegex(audit.AuditError, "refusing overwrite"):
            audit.run(self.root)
        self.assertEqual((self.root / audit.OUTPUT).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
