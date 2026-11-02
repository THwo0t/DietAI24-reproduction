"""Synthetic driver integration: finite tree, provenance, resume, no live data."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import metrics_v2
import opt_provider
import study

CODE = "12345678"
DENSITY = {"energy": 200, "fat": 10, "carbs": 20, "protein": 10}
CATALOG = {"foods": {CODE: {"density": DENSITY}}, "asa_options": {
    CODE: [{"option_id": "one", "grams": 100}]}, "standard_options": {
    CODE: [{"option_id": "one", "grams": 100, "description": "1 cup"}]}}


def vector(weight=100):
    return {"weight": weight, **{k: weight * v / 100 for k, v in DENSITY.items()}}


def population(dataset="nutrition5k", n=2):
    rows, labels, preds = [], {}, []
    for i in range(n):
        sid = f"{dataset}_{i}"
        row = {"sample_id": sid, "dataset": dataset, "group_id": f"plate_{i}", "fold": i % 2,
               "split": "dev", "image_sha256": "a" * 64, "image_path": "synthetic.png"}
        rows.append(row)
        labels[sid] = {"truth": vector(), "food_code": CODE, "split": "dev", "size": "medium"}
        pred = {"sample_id": sid, "dataset": dataset, "group_id": row["group_id"], "fold": row["fold"],
                "prediction": vector(), "raw_prediction": vector(), "fallback": False,
                "native_complete": True, "repair_used": False, "final_codes": [CODE],
                "primary_code": CODE, "retrieved_codes": [CODE]}
        if dataset == "asa24":
            pred.update(conditional={"code": CODE, "prediction": vector(), "continuous_grams": 100,
                                     "option_id": "one", "fallback": False},
                        e2e={"code": CODE, "prediction": vector(), "option_id": "one", "fallback": False})
        preds.append(pred)
    return rows, labels, preds


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


class FakeProvider:
    instances = []

    def __init__(self, *args, **kwargs):
        self.closed = False
        self.instances.append(self)

    def close(self):
        self.closed = True


class FakePipeline:
    def __init__(self, root, rows):
        self.root, self.rows = root, rows
        self.identifications, self.portions, self.reviews, self.standard = [], [], [], []

    def identify(self, picture, config, layout=None):
        self.identifications.append((config["profile"], deepcopy(layout)))
        item = {"component_id": "leaf", "item_id": "leaf", "parent_id": "plate", "primary_code": CODE}
        return {"status": "ok", "items": [item], "retrieved_codes": [CODE],
                "layout_result": {"origin": config["profile"], "layout": "synthetic"}, "repaired": False}

    def portion(self, picture, identity, config):
        profile = config["profile"]
        # Every population identity must be sealed before the first portion.
        seal = study.load(self.root / "runs/development" / profile / "identities_sealed.json")
        if set(seal) != {r["sample_id"] for r in self.rows}:
            raise AssertionError("portions started before all identities were sealed")
        self.portions.append((profile, deepcopy(identity)))
        weight = {"A": 100, "B": 200, "C": 300}.get(profile, 100)
        leaf = {"component_id": "leaf", "item_id": "leaf", "parent_id": "plate",
                "code": CODE, "grams": weight, "density": deepcopy(DENSITY)}
        return {"status": "ok", "prediction": vector(weight), "portions": [leaf],
                "raw_leaves": [deepcopy(leaf)], "parents": [{"parent_id": "plate", "grams": weight}],
                "repaired": False, "source_profile": profile}

    def review_codes(self, picture, identity, base, config):
        self.reviews.append((deepcopy(identity), deepcopy(base), deepcopy(config)))
        return deepcopy(identity), deepcopy(base)

    def standard_portions(self, picture, identity, base, config):
        self.standard.append((deepcopy(identity), deepcopy(base), deepcopy(config)))
        return deepcopy(base)


class IsolatedDriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dietai-v2-study-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "historical" / "mae_v2"
        self.root.mkdir(parents=True)
        for name, value in (("data/catalog.json", CATALOG), ("config/experiment.json", {}),
                            ("config/candidates.json", {}), ("data/vectors/manifest.json", {})):
            dump(self.root / name, value)
        (self.root / "PROTOCOL.md").write_text("Synthetic test fixture only.\n")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(study, "ROOT", self.root))
        self.stack.enter_context(patch.object(opt_provider, "ROOT", self.root))
        self.stack.enter_context(patch.object(study, "source_hashes", return_value={"fixture": "fixed"}))
        self.stack.enter_context(patch.object(study, "event"))
        self.stack.enter_context(patch.object(study, "usage", return_value={"api_calls": 0}))
        self.stack.enter_context(patch.object(study, "Provider", FakeProvider))
        self.stack.enter_context(patch.object(study.legacy, "image_path", return_value=self.root / "synthetic.png"))
        self.rows, self.labels, self.preds = population()
        self.pipeline = FakePipeline(self.root, self.rows)
        self.stack.enter_context(patch.object(study, "component_pipeline", return_value=self.pipeline))
        FakeProvider.instances.clear()

    def run_profile(self, name, source=None):
        return study.run_component(name, {"profile": name, "portion_mode": "total_ratio" if name == "C" else "direct"},
                                   self.rows, self.labels, CATALOG, False, workers=1, source=source)

    def test_b_c_d_e_reuse_only_their_registered_sources(self):
        a = self.run_profile("A")
        b = self.run_profile("B", a)
        c = self.run_profile("C", b)
        self.run_profile("D", c)
        self.run_profile("E", c)
        self.assertEqual([p for p, _ in self.pipeline.identifications], ["A", "A", "B", "B"])
        self.assertEqual([layout["origin"] for p, layout in self.pipeline.identifications if p == "B"], ["A", "A"])
        self.assertEqual([p for p, _ in self.pipeline.portions], ["A", "A", "B", "B", "C", "C"])
        self.assertEqual([base["source_profile"] for _, base, _ in self.pipeline.reviews], ["C", "C"])
        self.assertEqual([base["source_profile"] for _, base, _ in self.pipeline.standard], ["C", "C"])
        self.assertTrue(all(p.closed for p in FakeProvider.instances))
        for row in self.rows:
            self.assertEqual(study.read_identity(b, row), study.read_identity(c, row))

    def test_completed_run_resume_does_not_repeat_successful_stages(self):
        directory = self.run_profile("A")
        before = (len(self.pipeline.identifications), len(self.pipeline.portions))
        seal = study.load(directory / "records_sealed.json")
        self.run_profile("A")
        self.assertEqual((len(self.pipeline.identifications), len(self.pipeline.portions)), before)
        self.assertEqual(study.load(directory / "records_sealed.json"), seal)

    def test_systemic_stop_retains_sealed_identity_and_resume_does_not_resample_it(self):
        with patch.object(self.pipeline, "portion", side_effect=study.ProviderStop("Synthetic transport stop")):
            with self.assertRaises(study.ProviderStop):
                self.run_profile("A")
        directory = self.root / "runs/development/A"
        self.assertEqual(study.load(directory / "status.json")["status"], "interrupted")
        self.assertTrue((directory / "identities_sealed.json").is_file())
        self.assertFalse((directory / "records_sealed.json").exists())
        identity_calls = len(self.pipeline.identifications)
        self.run_profile("A")
        self.assertEqual(len(self.pipeline.identifications), identity_calls)
        self.assertEqual(study.load(directory / "status.json")["status"], "completed")

    def test_real_calibration_wrapper_preserves_raw_records_and_uses_shared_mass_factor(self):
        self.rows, self.labels, self.preds = population(n=12)
        self.pipeline.rows = self.rows
        for label in self.labels.values():
            label["truth"] = vector(125)
        directory = self.run_profile("A")
        candidate = study.score_run(directory, self.rows, self.labels, CATALOG, 3, study.ORDER.index("A"))
        selected = study.calibrate_winner(candidate, self.rows, self.labels, CATALOG, "round1")
        self.assertTrue(selected["calibrated"])
        self.assertEqual((selected["name"], selected["registration_index"]), ("A", study.ORDER.index("A")))
        saved = study.load(self.root / selected["calibration_artifact"])
        self.assertEqual(saved["selected_parameters"]["mass_factor"], 1.125)
        self.assertTrue(all(p["prediction"] == vector(112.5) for p in saved["predictions"]))
        self.assertTrue(all(p["prediction"] == vector(100) for p in study.completed_records(directory, self.rows)))

    def test_incomplete_source_is_visible_method_fallback_without_enhancement_call(self):
        with patch.object(self.pipeline, "portion", return_value={"status": "failed", "failure": "synthetic", "prediction": None}):
            source = self.run_profile("A")
        destination = self.run_profile("D", source)
        records = study.completed_records(destination, self.rows)
        self.assertEqual(self.pipeline.reviews, [])
        self.assertTrue(all(p["fallback"] and p["method_fallback"] for p in records))
        self.assertTrue(all(p["method_fallback_reason"] == "base_incomplete" for p in records))
        metrics = metrics_v2.evaluate(self.rows, self.labels, records)["datasets"]["nutrition5k"]
        self.assertEqual((metrics["primary"]["n"], metrics["method_fallback_n"], metrics["fallback_n"]), (2, 2, 2))

    def test_identity_mutation_and_resume_config_drift_are_rejected(self):
        directory = self.run_profile("A")
        path = directory / "identities" / study.artifact(self.rows[0])
        value = study.load(path)
        value["description"] = "mutated after seal"
        dump(path, value)
        with self.assertRaisesRegex(ValueError, "seal|sealing"):
            self.run_profile("B", directory)
        with self.assertRaisesRegex(ValueError, "drift"):
            study.run_component("A", {"profile": "A", "portion_mode": "changed"}, self.rows,
                                self.labels, CATALOG, False, workers=1)

    def test_source_record_tampering_rejected_before_enhancement(self):
        directory = self.run_profile("A")
        path = directory / "records" / study.artifact(self.rows[0])
        value = study.load(path)
        value["description"] = "tampered source record"
        dump(path, value)
        with self.assertRaisesRegex(ValueError, "record|seal|Source"):
            self.run_profile("D", directory)
        self.assertEqual(self.pipeline.reviews, [])

    def test_historical_import_uses_dev_raw_only_and_rebinds_new_groups(self):
        old_root = self.root.parent
        source = old_root / "runs/development/baseline"
        old_rows = deepcopy(self.rows)
        for row in old_rows:
            row["group_id"] = "historical_" + row["group_id"]
        manifest = old_root / "data/cohorts/dev.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("".join(json.dumps(r) + "\n" for r in old_rows))
        dump(old_root / "data/cohorts/dev_labels.json", self.labels)
        dump(source / "run_config.json", {"config": study.BASE})
        dump(source / "status.json", {"status": "completed"})
        dump(source / "predictions.json", self.preds)
        dump(source / "oof_predictions.json", [{"forbidden_old_oof": True}])
        dump(source / "calibration.json", {"forbidden_old_fit": True})
        seals = {}
        for row, pred in zip(self.rows, self.preds):
            identity = source / "identities" / study.artifact(row)
            dump(identity, {"status": "ok", "description": "synthetic identity"})
            seals[row["sample_id"]] = study.sha(identity)
            pred = deepcopy(pred)
            pred["group_id"] = "obsolete"
            pred["portion_result"] = {"portions": [{"item_id": "old", "grams": 100}]}
            dump(source / "records" / study.artifact(row), pred)
        dump(source / "identities_sealed.json", seals)
        real_load, reads = study.load, []
        def guarded(path):
            path = Path(path)
            reads.append(path)
            if "sealed" in path.parts or "validation" in path.name or path.name in {"oof_predictions.json", "calibration.json"}:
                raise AssertionError("development import opened forbidden evidence")
            return real_load(path)
        with patch.object(study, "load", side_effect=guarded):
            imported = study.import_historical("baseline", "baseline", self.rows, self.labels, CATALOG)
        records = study.completed_records(imported, self.rows)
        self.assertEqual([p["group_id"] for p in records], [r["group_id"] for r in self.rows])
        score = study.score_run(imported, self.rows, self.labels, CATALOG, 4, 0)
        self.assertEqual(score["metrics"]["datasets"]["nutrition5k"]["primary"]["metrics"]["weight"]["mae"], 0)
        self.assertTrue(all("validation" not in str(path) for path in reads))
        self.assertEqual(study.load(imported / "status.json")["new_api_calls"], 0)

    def test_dev_loader_refuses_a_validation_record(self):
        import cohorts_v2
        with patch.object(cohorts_v2, "verify_dev_only") as verify, \
                patch.object(cohorts_v2, "load_dev", return_value=(self.rows, self.labels)):
            rows, labels, catalog = study.dev_inputs()
            verify.assert_called_once_with()
            self.assertEqual((rows, labels, catalog), (self.rows, self.labels, CATALOG))
        bad = deepcopy(self.rows)
        bad[0]["split"] = "validation"
        with patch.object(cohorts_v2, "verify_dev_only"), \
                patch.object(cohorts_v2, "load_dev", return_value=(bad, self.labels)):
            with self.assertRaisesRegex(ValueError, "sealed"):
                study.dev_inputs()


class FiniteDevelopmentTreeTests(unittest.TestCase):
    def exercise(self, errors, usable_options=True):
        with tempfile.TemporaryDirectory(prefix="dietai-v2-tree-") as tmp, ExitStack() as stack:
            root = Path(tmp)
            ar, al, _ = population("asa24")
            nr, nl, _ = population()
            rows, labels = ar + nr, {**al, **nl}
            configs, component_calls, calibrations, saved = {}, [], [], {}
            stack.enter_context(patch.object(study, "ROOT", root))
            stack.enter_context(patch.object(opt_provider, "ROOT", root))
            stack.enter_context(patch.object(study, "dev_inputs", return_value=(rows, labels, CATALOG)))
            stack.enter_context(patch.object(study, "save", side_effect=lambda p, v: saved.__setitem__(str(p), deepcopy(v))))
            stack.enter_context(patch.object(study, "event"))
            def import_old(name, source, subset, supplied_labels, catalog):
                configs[name] = deepcopy(study.ASA if name.startswith("asa-") else study.BASE)
                return root / "runs/development" / name
            stack.enter_context(patch.object(study, "import_historical", side_effect=import_old))
            def legacy(name, config, *args, **kwargs):
                configs[name] = deepcopy(config)
                return root / "runs/development" / name
            stack.enter_context(patch.object(study, "run_legacy", side_effect=legacy))
            def component(name, config, *args, **kwargs):
                configs[name] = deepcopy(config)
                component_calls.append((name, deepcopy(config), kwargs.get("source")))
                return root / "runs/development" / name
            stack.enter_context(patch.object(study, "run_component", side_effect=component))
            def score(directory, subset, supplied_labels, catalog, calls, index, examples=False):
                name = directory.name
                predictions = []
                for ds in ("asa24", "nutrition5k"):
                    if any(r["dataset"] == ds for r in subset):
                        predictions.extend(population(ds)[2])
                metric = metrics_v2.evaluate(subset, supplied_labels, predictions)
                for ds in ("asa24", "nutrition5k"):
                    for key, limits in metrics_v2.THRESHOLDS[ds].items():
                        value = errors.get(name, 3)
                        value = value.get(key, value.get("default", 3)) if isinstance(value, dict) else value
                        current = metric["datasets"][ds]["primary"]["metrics"][key]
                        for statistic, threshold in zip(("mae", "per_unit"), limits):
                            if metric["datasets"][ds]["n"]:
                                current[statistic] = threshold * value
                                current["pass_" + statistic] = value <= 1
                return {"name": name, "directory": str(directory.relative_to(root)), "config": configs[name],
                        "metrics": metric, "estimated_chat_calls": calls, "registration_index": index,
                        "examples": examples, "calibrated": False}
            stack.enter_context(patch.object(study, "score_run", side_effect=score))
            def calibrate(candidate, *args):
                calibrations.append((candidate["name"], args[-1]))
                return deepcopy(candidate)
            stack.enter_context(patch.object(study, "calibrate_winner", side_effect=calibrate))
            def choose_profiles(candidates, *args, **kwargs):
                profiles = {ds: metrics_v2.select_profile(candidates, ds) for ds in ("asa24", "nutrition5k")}
                passed = all(p and max(metrics_v2.ratios(p["metrics"], ds)) <= 1 for ds, p in profiles.items())
                return {"joint_pass": passed, "profiles": profiles, "status": "development_selection"}
            stack.enter_context(patch.object(study, "selection", side_effect=choose_profiles))
            stack.enter_context(patch.object(study, "read_identity", return_value={"synthetic": True}))
            from pipeline_v2 import ComponentPipeline
            stack.enter_context(patch.object(ComponentPipeline, "standard_portion_coverage",
                                             return_value={"eligible_leaf_count": int(usable_options)}))
            study.develop(SimpleNamespace(allow_paid=False, workers=1))
            return component_calls, calibrations, saved

    def test_at_most_three_core_two_expansions_and_only_raw_winner_calibration(self):
        calls, calibrations, saved = self.exercise({"asa-retrieval-portion": .2, "A": 2, "B": 1.5,
                                                   "C": 1.2, "D": .8, "E": 1.0})
        self.assertEqual([name for name, _, _ in calls], ["A", "B", "C", "D", "E"])
        source_names = {name: source.name if source else None for name, _, source in calls}
        self.assertEqual(source_names, {"A": None, "B": "A", "C": "B", "D": "C", "E": "C"})
        self.assertEqual(calibrations, [("asa-retrieval-portion", "asa"), ("C", "round1"), ("D", "round2")])
        completion = next(v for p, v in saved.items() if p.endswith("completion.json"))
        self.assertTrue(completion["joint_pass"])
        self.assertFalse(completion["validation_opened_for_inference_or_scoring"])

    def test_core_pass_does_not_run_expansions(self):
        calls, calibrations, _ = self.exercise({"asa-retrieval-portion": .2, "A": 2, "B": 1.5, "C": .7})
        self.assertEqual([name for name, _, _ in calls], ["A", "B", "C"])
        self.assertEqual(calibrations, [("asa-retrieval-portion", "asa"), ("C", "round1")])

    def test_weight_only_failure_without_usable_units_does_not_trigger_d_or_e(self):
        calls, _, saved = self.exercise({"asa-retrieval-portion": .2, "A": 2, "B": 1.5,
                                        "C": {"default": .7, "weight": 1.2}}, usable_options=False)
        self.assertEqual([name for name, _, _ in calls], ["A", "B", "C"])
        decision = next(v for p, v in saved.items() if p.endswith("round2_decision.json"))
        self.assertFalse(decision["D"])
        self.assertFalse(decision["E"])


if __name__ == "__main__":
    unittest.main()
