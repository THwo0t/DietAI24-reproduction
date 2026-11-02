"""Fixed, fully offline semantic kNN exploration; see sibling PROTOCOL.md.

No inference/provider import, image read, validation access, or new embedding.
Raw C code/grams determine retrieval. Only selected training references enter
the per-query estimator. This is supervised posthoc development exploration.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path
import platform
from statistics import median
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "round3/src")]
import opt_metrics as metrics
from examples import build_features

KEYS = metrics.KEYS
KS = (3, 7, 15)
SPECS = tuple((f"{family}_k{k}_{'blend50' if blend else 'pure'}", family, k, blend)
              for family in ("A", "B") for k in KS for blend in (False, True))
FIXED_INPUTS = (
    "data/cohorts/dev_freeze.json", "data/cohorts/dev.jsonl", "data/cohorts/dev_labels.json",
    "runs/development/C/run_config.json", "runs/development/C/records_sealed.json",
    "runs/development/C/predictions.json", "data/vectors/manifest.json",
    "data/vectors/embeddings.npy", "data/vectors/codes.json", "data/vectors/collection.json",
    "evidence/review-one-completion.json", "src/opt_metrics.py", "round3/src/examples.py",
    "analysis/next_round_semantic/PROTOCOL.md", "analysis/next_round_semantic/explore.py",
    "analysis/next_round_semantic/test_explore.py",
)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def index_rows(rows):
    indexed = {}
    for row in rows:
        sid = row.get("sample_id")
        if (not isinstance(sid, str) or not sid or sid in indexed
                or row.get("dataset") != "nutrition5k" or row.get("split") != "dev"
                or not isinstance(row.get("group_id"), str) or not row["group_id"]
                or type(row.get("fold")) is not int or row["fold"] not in range(5)):
            raise ValueError("Unique Nutrition5k development rows with group/fold are required")
        indexed[sid] = row
    if not indexed:
        raise ValueError("Empty development population")
    return indexed


def rank_neighbors(rows, features, query_id, k):
    """Label-free rank, then distinct-group selection, then top k."""
    if type(k) is not int or k not in KS:
        raise ValueError("Only registered k values are allowed")
    by_id = index_rows(rows)
    if query_id not in by_id or set(features) != set(by_id):
        raise ValueError("Complete aligned feature population required")
    arrays = {sid: np.asarray(value, dtype=np.float64) for sid, value in features.items()}
    shape = arrays[query_id].shape
    if (len(shape) != 1 or shape[0] == 0 or any(v.shape != shape or not np.isfinite(v).all()
            or not math.isclose(float(np.linalg.norm(v)), 1.0, rel_tol=1e-10, abs_tol=1e-10)
            for v in arrays.values())):
        raise ValueError("Finite unit feature vectors required")
    query = by_id[query_id]
    eligible = []
    for sid, row in by_id.items():
        if row["fold"] == query["fold"] or row["group_id"] == query["group_id"]:
            continue
        cosine = float(np.dot(arrays[query_id], arrays[sid]))
        eligible.append((-cosine, sid))
    selected, groups = [], set()
    for negative_cosine, sid in sorted(eligible):
        group = by_id[sid]["group_id"]
        if group in groups:
            continue
        groups.add(group)
        selected.append((sid, -negative_cosine))
        if len(selected) == k:
            return selected
    raise ValueError("Insufficient distinct eligible training groups; no relaxation")


def vector(value):
    if not isinstance(value, dict) or set(value) != set(KEYS):
        raise ValueError("Exactly five target values required")
    result = metrics._vector(value, "reference_or_raw_prediction")
    if result["weight"] <= 0:
        raise ValueError("Positive weight required; invalid rows cannot be dropped")
    return result


def predict_query(query, neighbors, training_labels, raw_prediction, family, blend):
    """Narrow boundary: only selected isolated training references are accepted."""
    if family not in ("A", "B") or type(blend) is not bool or len(neighbors) not in KS:
        raise ValueError("Unregistered candidate")
    indexed = index_rows(neighbors)
    index_rows([query])
    if (set(training_labels) != set(indexed)
            or len({r["group_id"] for r in neighbors}) != len(neighbors)
            or any(r["fold"] == query["fold"] or r["group_id"] == query["group_id"]
                   or r["sample_id"] == query["sample_id"] for r in neighbors)):
        raise ValueError("References must be exactly the distinct isolated training neighbors")
    refs = [vector(training_labels[r["sample_id"]]["truth"]) for r in neighbors]
    raw = vector(raw_prediction)
    if family == "A":
        answer = {key: float(median(r[key] for r in refs)) for key in KEYS}
    else:
        weight = float(median(r["weight"] for r in refs))
        answer = {"weight": weight}
        answer.update({key: weight * float(median(r[key] / r["weight"] for r in refs))
                       for key in KEYS[1:]})
    if blend:
        answer = {key: 0.5 * answer[key] + 0.5 * raw[key] for key in KEYS}
    return vector(answer)


def predict_all(rows, features, raw_records, labels):
    """Produce all 12 fixed OOF vectors; no scoring or adaptive choice here."""
    by_id = index_rows(rows)
    raw = {r["sample_id"]: r for r in raw_records}
    if len(raw_records) != len(rows) or set(raw) != set(by_id):
        raise ValueError("Complete raw C population required")
    outputs = {name: [] for name, *_ in SPECS}
    assignments = {}
    cosine_values = {k: [] for k in KS}
    for query in rows:
        sid = query["sample_id"]
        ranked = rank_neighbors(rows, features, sid, max(KS))
        assignments[sid] = {str(k): [s for s, _ in ranked[:k]] for k in KS}
        for k in KS:
            cosine_values[k].extend(cosine for _, cosine in ranked[:k])
        for name, family, k, blend in SPECS:
            neighbors = [by_id[s] for s, _ in ranked[:k]]
            # Do not pass the full labels object across the estimation boundary.
            train_only = {r["sample_id"]: labels[r["sample_id"]] for r in neighbors}
            prediction = predict_query(query, neighbors, train_only, raw[sid]["raw_prediction"], family, blend)
            outputs[name].append({**{key: query[key] for key in ("sample_id", "dataset", "group_id", "fold")},
                                  "prediction": prediction, "raw_prediction": deepcopy(prediction),
                                  "native_complete": True, "fallback": False,
                                  "final_codes": [], "primary_code": None})
    diagnostics = {str(k): {"queries": len(rows), "neighbors_per_query": k,
                           "distinct_groups_per_query": k,
                           "mean_cosine": math.fsum(cosine_values[k]) / len(cosine_values[k]),
                           "minimum_cosine": min(cosine_values[k]),
                           "maximum_cosine": max(cosine_values[k])} for k in KS}
    return outputs, {"assignment_sha256": fingerprint(assignments), "by_k": diagnostics,
                     "same_fold_neighbors": 0, "same_group_neighbors": 0}


class Inputs:
    def __init__(self, root):
        self.root, self.hashes = root, {}

    def read(self, name):
        record = name.startswith("runs/development/C/records/") and name.endswith(".json")
        if name not in FIXED_INPUTS and not record:
            raise ValueError("Input path is outside this diagnostic's allowlist")
        path = self.root / name
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise ValueError("Only fixed regular in-root inputs allowed")
        data = path.read_bytes()
        self.hashes[name] = hashlib.sha256(data).hexdigest()
        return data

    def json(self, name):
        return json.loads(self.read(name))

    def unchanged(self):
        before = dict(self.hashes)
        for name, expected in before.items():
            self.read(name)
            if self.hashes[name] != expected:
                raise ValueError("Input changed during analysis")


def load_inputs(root=ROOT):
    reader = Inputs(root)
    freeze = reader.json("data/cohorts/dev_freeze.json")
    all_rows = [json.loads(line) for line in reader.read("data/cohorts/dev.jsonl").splitlines() if line]
    rows = [r for r in all_rows if r["dataset"] == "nutrition5k"]
    labels_all = reader.json("data/cohorts/dev_labels.json")
    labels = {r["sample_id"]: labels_all[r["sample_id"]] for r in rows}
    for name in ("data/cohorts/dev.jsonl", "data/cohorts/dev_labels.json"):
        if freeze["artifacts"].get(name) != reader.hashes[name]:
            raise ValueError("Development manifest/labels differ from freeze")
    if len(rows) != 84 or len({r["group_id"] for r in rows}) != 78 or {r["fold"] for r in rows} != set(range(5)):
        raise ValueError("Fixed 84-row/78-group development population required")
    metrics._training(rows, labels)
    config = reader.json("runs/development/C/run_config.json")
    reviewed = reader.json("evidence/review-one-completion.json")
    if (config.get("name") != "C" or config.get("manifest_sha256") != fingerprint(rows)
            or config.get("code_sha256") != reviewed["original_code_sha256"]
            or config.get("protocol_sha256") != reviewed["protocol_sha256"]
            or reader.hashes["data/cohorts/dev_freeze.json"] != reviewed["dev_freeze_sha256"]):
        raise ValueError("Raw C provenance differs from reviewed run")
    seal = reader.json("runs/development/C/records_sealed.json")
    if set(seal) != {r["sample_id"] for r in rows}:
        raise ValueError("C external seal population differs")
    raw = []
    for row in rows:
        name = "runs/development/C/records/" + fingerprint(row["sample_id"])[:24] + ".json"
        record = reader.json(name)
        if (reader.hashes[name] != seal[row["sample_id"]]
                or any(record.get(k) != row[k] for k in ("sample_id", "dataset", "group_id", "fold"))
                or record.get("fallback") or record.get("method_fallback")
                or record.get("prediction") != record.get("raw_prediction")):
            raise ValueError("Complete original uncalibrated C record required")
        raw.append(record)
    original = reader.json("runs/development/C/predictions.json")
    if len(original) != len(rows) or {p["sample_id"]: p for p in original} != {p["sample_id"]: p for p in raw}:
        raise ValueError("Raw C aggregate differs from external record seal")
    metrics._validate(rows, labels, raw)
    vm = reader.json("data/vectors/manifest.json")
    if (set(vm["files"]) != {"codes.json", "embeddings.npy", "collection.json"}
            or config["vector_sha256"] != reader.hashes["data/vectors/manifest.json"]):
        raise ValueError("C frozen vector manifest differs")
    blobs = {name: reader.read("data/vectors/" + name) for name in vm["files"]}
    if any(reader.hashes["data/vectors/" + name] != sha for name, sha in vm["files"].items()):
        raise ValueError("Frozen embedding checksum differs")
    codes = json.loads(blobs["codes.json"])
    vectors = np.load(io.BytesIO(blobs["embeddings.npy"]), allow_pickle=False)
    if vectors.shape != (vm["vectors"], vm["dimensions"]):
        raise ValueError("Frozen embedding shape differs")
    for name in FIXED_INPUTS:
        if name not in reader.hashes:
            reader.read(name)
    if reader.hashes["src/opt_metrics.py"] != reviewed["code_sha256"]["opt_metrics.py"]:
        raise ValueError("Scoring source differs from reviewed version")
    return reader, rows, labels, raw, codes, vectors


def score(rows, labels, predictions):
    ds = metrics.evaluate(rows, labels, predictions, bootstrap=0)["datasets"]["nutrition5k"]
    result = deepcopy(ds["primary"])
    by_id = {r["sample_id"]: r for r in predictions}
    for key, values in result["metrics"].items():
        values["mean_signed_error"] = math.fsum(by_id[r["sample_id"]]["prediction"][key]
            - labels[r["sample_id"]]["truth"][key] for r in rows) / len(rows)
    ratios = [m[s] / m["threshold_" + s] for m in result["metrics"].values() for s in ("mae", "per_unit")]
    result.update({"groups": len({r["group_id"] for r in rows}),
                   "passed_checks": sum(m["pass_" + s] for m in result["metrics"].values() for s in ("mae", "per_unit")),
                   "total_checks": 10, "maximum_ratio_to_cap": max(ratios),
                   "mean_ratio_to_cap": math.fsum(ratios) / len(ratios)})
    return result


def run(root=ROOT):
    reader, rows, labels, raw, codes, vectors = load_inputs(root)
    features = build_features(rows, raw, codes, vectors)
    predictions, isolation = predict_all(rows, features, raw, labels)
    candidates = {}
    for name, family, k, blend in SPECS:
        records = predictions[name]
        by_id = {p["sample_id"]: p for p in records}
        folds = []
        for fold in range(5):
            subset = [r for r in rows if r["fold"] == fold]
            folds.append({"fold": fold, **score(subset, labels, [by_id[r["sample_id"]] for r in subset])})
        candidates[name] = {"family": family, "k": k, "raw_C_blend_fraction": 0.5 if blend else 0.0,
                            **score(rows, labels, records), "by_fold": folds}
    output = {
        "schema_version": 1, "scope": "posthoc_supervised_development_exploration_not_independent_acceptance",
        "n": 84, "groups": 78, "fixed_candidate_count": 12,
        "prior_eight_families_do_not_include_semantic_knn": True,
        "features": "unchanged examples.build_features: normalized raw C leaf-code embedding mean weighted by raw grams",
        "retrieval": "exclude query fold and group; descending cosine then sample_id; first per group before top k",
        "families": {"A": "componentwise ordinary median of neighbor five-target truth",
                     "B": "median weight times ordinary median of per-neighbor nutrient/weight ratios"},
        "raw_C_reference": score(rows, labels, raw), "candidates": candidates,
        "neighbor_diagnostics": isolation,
        "verification": {"all_84_records_scored_in_every_candidate": True, "filtered_records": 0,
                         "raw_C_external_seal_verified_n": 84, "new_embedding_calls": 0, "api_calls": 0,
                         "images_opened": False, "validation_opened": False,
                         "H_G_I_predictions_used": False, "query_truth_used_in_estimation": False,
                         "query_or_train_errors_used_in_retrieval": False, "selection_changed": False,
                         "row_predictions_or_reference_labels_exported": False},
        "limitations": ["Supervised retrieval departs from original FNDDS inference.",
                        "C was previously selected on these development data; comparing these 12 OOF outcomes is posthoc model exploration, not independent acceptance.",
                        "No per-target winner mixing or automatic candidate selection is performed.",
                        "Componentwise medians and blended totals need not form one coherent leaf-level mass/density decomposition."],
        "input_sha256": {k: v for k, v in reader.hashes.items() if not k.startswith("runs/development/C/records/")},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__},
    }
    reader.unchanged()
    path = root / "analysis/next_round_semantic/aggregate.json"
    payload = json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if path.exists():
        if path.is_symlink() or path.read_text() != payload:
            raise ValueError("Refusing to overwrite a different aggregate")
    else:
        with path.open("x") as handle:
            handle.write(payload)
    return output


if __name__ == "__main__":
    result = run()
    print(json.dumps({name: {"passed_checks": c["passed_checks"],
                            "mae": {k: c["metrics"][k]["mae"] for k in KEYS},
                            "maximum_ratio_to_cap": c["maximum_ratio_to_cap"]}
                      for name, c in result["candidates"].items()}, indent=2, allow_nan=False))
