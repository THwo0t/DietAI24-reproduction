#!/usr/bin/env python3
"""Read-only, completed-F audit; the sole write is one immutable safe receipt.

The as-run driver has two provenance gaps: it does not bind its preserved ASA/C
references, and resume does not check an existing external records seal before
overwriting it. This independent audit checks those boundaries after completion.
It never invokes driver.run, a provider, validation, or a prediction generator.
Future rounds should correct their driver separately; F's source stays as run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import cohorts_v2
import opt_metrics as metrics
from opt_pipeline import ContractError
from opt_provider import fingerprint
from direct_estimator import _parse, _macro_mass_excess

AS_RUN_COMMIT = "8f7aac6"
# Portable trust anchors from the checked-in as-run evidence; no Git dependency.
TRUSTED_ANCHORS = {
    "round3/evidence/preflight.json": "66b68b9018f22a0df3f76bb6e79bb700dad32340ec5429d8abaf2f185a4a4928",
    "evidence/review-one-completion.json": "d80987a08b81b6f1bb042260d78ee19053ad7140de5c18bb03eca6ecef1c8fce",
    "evidence/R-M2-4-1.json": "c742414a52f1b57a0bfe1273f973194736d28986210f067c4e28ef9f7096aa46",
}
RUN = "round3/runs/F"
OUTPUT = "round3/evidence/F_audit.json"


class AuditError(ValueError):
    """Safe, non-row-identifying audit failure."""


def _file(root, relative):
    path = root / relative
    if root not in path.resolve().parents or path.is_symlink():
        raise AuditError("Audit input escapes the project or is a symlink")
    return path


def _bytes(root, relative):
    try:
        return _file(root, relative).read_bytes()
    except OSError:
        raise AuditError("Required audit input is unavailable") from None


def _sha(root, relative):
    return hashlib.sha256(_bytes(root, relative)).hexdigest()


def _decode(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise AuditError("Audit input is not strict finite JSON") from None


def _load(root, relative):
    return _decode(_bytes(root, relative))


def _require(condition, reason):
    if not condition:
        raise AuditError(reason)


def _record_name(row):
    return fingerprint(row["sample_id"])[:24] + ".json"


def _recompute_record(row, record, fallback):
    raw = record.get("raw_outputs")
    _require(isinstance(raw, list) and 1 <= len(raw) <= 2
             and all(isinstance(text, str) for text in raw), "Invalid raw answer history")
    parsed, failure = None, None
    for index, text in enumerate(raw):
        try:
            parsed = _parse(text)
        except ContractError as exc:
            failure = str(exc)
        else:
            _require(index == len(raw) - 1, "A valid answer was unnecessarily resampled")
    failed = parsed is None
    _require(not failed or len(raw) == 2, "Failure did not exhaust the single format repair")
    if failed:
        items, prediction = [], None
        audit = {"macro_mass_excess_items": [], "macro_mass_excess_total": None}
    else:
        items, prediction = parsed
        audit = {"macro_mass_excess_items": [item["item_id"] for item in items
                                             if _macro_mass_excess(item)],
                 "macro_mass_excess_total": _macro_mass_excess(prediction)}
    repaired = len(raw) == 2
    expected = {key: row[key] for key in ("sample_id", "dataset", "group_id", "fold")}
    expected.update({"prediction": deepcopy(fallback if failed else prediction),
        "raw_prediction": prediction, "fallback": failed,
        "fallback_reason": failure if failed else None,
        "native_complete": not failed and not repaired,
        "repair_used": repaired, "final_codes": [], "primary_code": None,
        "items": items, "raw_outputs": raw, "audit": audit,
        "method": "F_direct_visual_nutrients"})
    _require(fingerprint(record) == fingerprint(expected),
             "Record differs from raw-item sums, repair state or training-fold fallback")
    return expected


def audit(root=ROOT):
    """Read completed records and return only safe counts and integrity hashes."""
    root = Path(root).resolve()
    snapshots = {}
    def read(relative):
        payload = _bytes(root, relative)
        snapshots[relative] = hashlib.sha256(payload).hexdigest()
        return _decode(payload)
    completion = read(RUN + "/completion.json")  # Must precede dev access.
    for relative, digest in TRUSTED_ANCHORS.items():
        _require(_sha(root, relative) == digest, "Trusted evidence hash mismatch")
    preflight = read("round3/evidence/preflight.json")
    reviewed = read("evidence/review-one-completion.json")
    metric_review = read("evidence/R-M2-4-1.json")
    sources = dict(reviewed["code_sha256"])
    _require(len(sources) == 9 and all(Path(name).name == name for name in sources),
             "Invalid reviewed core source inventory")
    for name, digest in sources.items():
        _require(_sha(root, "src/" + name) == digest, "As-run core source hash mismatch")
    for name in ("run_round3.py", "direct_estimator.py"):
        digest = preflight["sha256"]["src/" + name]
        _require(_sha(root, "round3/src/" + name) == digest, "As-run round source hash mismatch")
        sources["round3/" + name] = digest
    protocol_hash = preflight["sha256"]["PROTOCOL.md"]
    _require(_sha(root, "round3/PROTOCOL.md") == protocol_hash, "As-run protocol hash mismatch")
    try:
        cohorts_v2.verify_dev_only(root)
    except (cohorts_v2.AuditError, ValueError, OSError):
        raise AuditError("Development-only integrity verification failed") from None
    all_rows = [_decode(line) for line in _bytes(root, "data/cohorts/dev.jsonl").splitlines() if line]
    labels = read("data/cohorts/dev_labels.json")
    n5 = [row for row in all_rows if row["dataset"] == "nutrition5k"]
    asa_rows = [row for row in all_rows if row["dataset"] == "asa24"]
    _require(len(all_rows) == 183 and len(n5) == 84 and len(asa_rows) == 99
             and len({row["group_id"] for row in n5}) == 78,
             "Registered 84 Nutrition5k and 99 ASA24 population is incomplete")
    expected = {"candidate": "F", "scope": "development_only",
        "model": "gpt-6.1-sol", "temperature": 1, "max_completion_tokens": 8192,
        "protocol_sha256": protocol_hash, "source_sha256": sources,
        "dev_freeze_sha256": _sha(root, "data/cohorts/dev_freeze.json"),
        "manifest_sha256": fingerprint(n5), "validation_access": False}
    binding = read(RUN + "/binding.json")
    _require(binding == expected, "As-run binding differs from trusted sources or population")
    _require(set(completion) == {"completed", "n", "groups", "binding_sha256", "validation_opened"}
             and isinstance(completion["completed"], str) and bool(completion["completed"])
             and completion["n"] == 84 and completion["groups"] == 78
             and completion["binding_sha256"] == fingerprint(binding)
             and completion["validation_opened"] is False, "Invalid F completion marker")
    selected_path = "runs/development/selected_oof_predictions.json"
    selection_path = "runs/development/selection.json"
    _require(_sha(root, selected_path) == metric_review["input_sha256"][selected_path],
             "Preserved ASA prediction source hash mismatch")
    _require(_sha(root, selection_path) == reviewed["selection_sha256"],
             "Preserved C selection source hash mismatch")
    for relative in ("data/cohorts/dev.jsonl", "data/cohorts/dev_labels.json", "data/cohorts/dev_freeze.json"):
        _require(_sha(root, relative) == metric_review["input_sha256"][relative],
                 "Reviewed development input hash mismatch")
    seal = read(RUN + "/records_sealed.json")
    _require(isinstance(seal, dict) and set(seal) == {row["sample_id"] for row in n5},
             "External record seal does not contain the full population")
    names = {path.name for path in _file(root, RUN + "/records").glob("*.json")}
    _require(names == {_record_name(row) for row in n5}, "Record file population differs from 84")
    fallbacks = {fold: metrics.fold_medians(n5, labels, heldout_fold=fold)
                 for fold in {row["fold"] for row in n5}}
    records = []
    for row in n5:
        relative = RUN + "/records/" + _record_name(row)
        _require(_sha(root, relative) == seal[row["sample_id"]], "Record differs from external seal")
        envelope = _load(root, relative)
        _require(set(envelope) == {"binding_sha256", "record", "record_sha256"}
                 and envelope["binding_sha256"] == fingerprint(binding)
                 and envelope["record_sha256"] == fingerprint(envelope["record"]),
                 "Record envelope checksum or source binding mismatch")
        records.append(_recompute_record(row, envelope["record"], fallbacks[row["fold"]]))
    _require(read(RUN + "/predictions.json") == records,
             "Saved prediction aggregate differs from externally sealed records")
    fixed = read(selected_path)
    asa = [prediction for prediction in fixed if prediction["dataset"] == "asa24"]
    n5_metrics = metrics.evaluate(n5, labels, records, bootstrap=0)
    joint = metrics.evaluate(all_rows, labels, asa + records, bootstrap=0)
    recomputed = {"scope": "development_not_independent_validation", "candidate": "F",
        "nutrition5k": n5_metrics["datasets"]["nutrition5k"],
        "joint_metrics_with_preserved_asa": joint,
        "selected_C_reference": read(selection_path)["metrics"]["datasets"]["nutrition5k"],
        "validation_opened": False}
    _require(read(RUN + "/metrics.json") == recomputed,
             "Saved metrics differ from complete full-precision recomputation")
    guarded = {**TRUSTED_ANCHORS,
        **{"src/" + name: digest for name, digest in reviewed["code_sha256"].items()},
        **{"round3/src/" + name: sources["round3/" + name]
           for name in ("run_round3.py", "direct_estimator.py")},
        "round3/PROTOCOL.md": protocol_hash,
        **{path: metric_review["input_sha256"][path] for path in (selected_path,
            "data/cohorts/dev.jsonl", "data/cohorts/dev_labels.json", "data/cohorts/dev_freeze.json")},
        selection_path: reviewed["selection_sha256"],
        **{RUN + "/" + name: snapshots[RUN + "/" + name] for name in (
            "binding.json", "records_sealed.json", "predictions.json", "metrics.json", "completion.json")}}
    # Catch changes during this audit, including a concurrent completed-run resume.
    for relative, digest in guarded.items():
        _require(_sha(root, relative) == digest, "Audit input changed during verification")
    for row in n5:
        _require(_sha(root, RUN + "/records/" + _record_name(row)) == seal[row["sample_id"]],
                 "Record changed during verification")
    return {"schema_version": 1, "status": "PASS", "candidate": "F",
        "scope": "completed_development_integrity_audit", "as_run_commit": AS_RUN_COMMIT,
        "counts": {"nutrition5k": 84, "nutrition5k_groups": 78, "asa24": 99,
                   "fallback": sum(record["fallback"] for record in records),
                   "repaired": sum(record["repair_used"] for record in records)},
        "source_binding_sha256": fingerprint(binding), "input_sha256": guarded,
        "metrics_sha256": fingerprint(recomputed), "metrics_match": True,
        "api_calls": 0, "validation_read": False, "credentials_read": False,
        "run_files_modified": False}


def run(root=ROOT):
    """Audit first, then create the fixed receipt; never replace a different one."""
    root = Path(root).resolve()
    result = audit(root)
    path = _file(root, OUTPUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        _require(_load(root, OUTPUT) == result, "Existing audit receipt differs; refusing overwrite")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = run(args.root)
    except (AuditError, ValueError, KeyError, TypeError, OSError):
        print(json.dumps({"status": "FAIL", "reason": "Completed F integrity audit failed",
                          "api_calls": 0, "validation_read": False}))
        return 1
    print(json.dumps({"status": result["status"], "counts": result["counts"],
                      "api_calls": 0, "validation_read": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
