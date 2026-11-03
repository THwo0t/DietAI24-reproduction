"""Read-only historical response import; no Provider, credentials or labels."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from opt_provider import (CHAT_URL, CHAT_MODEL, EMBED_URL, EMBED_MODEL,
                          fingerprint, sha)

OLD_CHAT_NAMESPACE = "mae-v2-development"
OLD_PARENT_PROVIDER = "010ab90a8c578ae9bde258696dc3b14d83283a94d06424e22a1617ac5d1a42ea"
REVIEW_SHA = "d80987a08b81b6f1bb042260d78ee19053ad7140de5c18bb03eca6ecef1c8fce"


def load(path):
    return json.loads(Path(path).read_text())


def request_hash(role, payload, namespace):
    return fingerprint({"url": CHAT_URL if role == "chat" else EMBED_URL,
                        "payload": payload, "namespace": namespace})


def embedding_payload(text):
    return {"model": EMBED_MODEL, "input": [text], "encoding_format": "float"}


def valid_vector(value):
    import math
    return (isinstance(value, list) and len(value) == 3072 and any(value)
            and all(type(v) in (int, float) and math.isfinite(v) for v in value))


def cache_value(path, h, role):
    saved = load(path)
    model = CHAT_MODEL if role == "chat" else EMBED_MODEL
    if (set(saved) != {"request_hash", "model", "value", "value_hash"}
            or saved["request_hash"] != h or saved["model"] != model
            or saved["value_hash"] != fingerprint(saved["value"])
            or (not isinstance(saved["value"], str) if role == "chat" else not valid_vector(saved["value"]))):
        raise ValueError("historical_response_cache_changed")
    return saved["value"]


def checked_path(base, relative):
    base, relative = Path(base).resolve(), Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe_historical_path")
    path = base / relative
    current = base
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("historical_symlink_rejected")
    return path


def read_logs(paths, role):
    result = {}
    for path in sorted(set(paths)):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get("role") == role:
                result.setdefault(row["request_hash"], []).append((path, row))
    return result


def check_success(h, role, history, counter=None):
    model, url = (CHAT_MODEL, CHAT_URL) if role == "chat" else (EMBED_MODEL, EMBED_URL)
    # Identical historical log copies are one event, never extra transmissions.
    events = {fingerprint(row): row for _, row in history}
    success = [r for r in events.values() if r.get("status") == 200]
    if len(success) != 1:
        raise ValueError("historical_unique_success_required")
    row = success[0]
    if (row.get("request_hash") != h or row.get("endpoint") != url
            or row.get("model_requested") != model or row.get("model_served") != model
            or type(row.get("attempt")) is not int or not 1 <= row["attempt"] <= 3
            or (role == "chat" and row.get("finish_reason") != "stop")):
        raise ValueError("historical_success_route_changed")
    if counter is not None:
        if (set(counter) != {"request_hash", "attempts", "last_reserved", "namespace"}
                or counter["request_hash"] != h or type(counter["attempts"]) is not int
                or not 1 <= counter["attempts"] <= 3 or counter["attempts"] != row["attempt"]
                or not isinstance(counter["namespace"], str) or not counter["namespace"]
                or not isinstance(counter["last_reserved"], str) or not counter["last_reserved"]
                or any(type(r.get("attempt")) is not int or r["attempt"] > counter["attempts"]
                       for r in events.values())):
            raise ValueError("historical_success_counter_changed")
    return row


def prepare_embedding_imports(root):
    """Explicit inventory of old successes; rejects remain unusable, never reset."""
    root = Path(root).resolve()
    base = root.parent
    if sha(base / "src/opt_provider.py") != OLD_PARENT_PROVIDER:
        raise ValueError("historical_parent_provider_changed")
    paths = list((root / "runs/development").glob("*/requests.jsonl"))
    paths += list((base / "runs").glob("development*/*/requests.jsonl"))
    paths += list(root.glob("round[3-6]/**/requests.jsonl"))
    logs = read_logs(paths, "embedding")
    dirs = [root / "runtime_cache/responses/embedding", base / "runtime_cache/responses/embedding"]
    hashes = {p.stem for directory in dirs for p in directory.glob("*.json")}
    files, entries, rejected = {}, {}, []
    def pin(path):
        relative = path.relative_to(base).as_posix()
        files[relative] = sha(path)
        return relative
    pin(base / "src/opt_provider.py")
    pin(root / "src/opt_provider.py")
    for h in sorted(hashes):
        try:
            caches = [d / (h + ".json") for d in dirs if (d / (h + ".json")).is_file()]
            values = [cache_value(path, h, "embedding") for path in caches]
            if any(value != values[0] for value in values):
                raise ValueError("historical_duplicate_cache_conflict")
            counter_path = root / "runtime_cache/attempts/embedding" / (h + ".json")
            counter = load(counter_path) if counter_path.is_file() else None
            history = logs.get(h, [])
            check_success(h, "embedding", history, counter)
            if counter is None and not any(path.is_relative_to(base / "runs") for path, _ in history):
                raise ValueError("missing_historical_counter_not_parent_source")
            entry = {"cache_paths": [pin(path) for path in caches],
                "value_hash": fingerprint(values[0]),
                "counter_path": pin(counter_path) if counter is not None else None,
                "historical_counter_available": counter is not None,
                "logs": [{"path": pin(path), "record": record} for path, record in history],
                "new_M_transmissions": 0}
            entries[h] = entry
        except (ValueError, TypeError, KeyError):
            rejected.append(h)
    return {"schema_version": 1, "hash_namespace": "official-query-v1",
            "entries": entries, "source_files": files, "rejected_hashes": rejected,
            "notice": "Old parent successes can lack persistent counters; no modern receipts are manufactured."}


def imported_embedding(root, manifest, h):
    entry, base = manifest["entries"][h], Path(root).resolve().parent
    relevant = [*entry["cache_paths"], *[r["path"] for r in entry["logs"]],
                "src/opt_provider.py"]
    if entry["counter_path"] is not None:
        relevant.append(entry["counter_path"])
    for relative in relevant:
        if sha(checked_path(base, relative)) != manifest["source_files"][relative]:
            raise ValueError("historical_embedding_source_changed")
    values = [cache_value(checked_path(base, p), h, "embedding") for p in entry["cache_paths"]]
    if not values or any(v != values[0] for v in values) or fingerprint(values[0]) != entry["value_hash"]:
        raise ValueError("historical_embedding_value_changed")
    history = [(checked_path(base, r["path"]), r["record"]) for r in entry["logs"]]
    counter = load(checked_path(base, entry["counter_path"])) if entry["counter_path"] is not None else None
    check_success(h, "embedding", history, counter)
    if (counter is not None) != entry["historical_counter_available"]:
        raise ValueError("historical_counter_availability_changed")
    return values[0]


def tree_hash(directory):
    parts = [p.relative_to(directory).as_posix() + "\0" + sha(p) + "\n"
             for p in sorted(directory.rglob("*")) if p.is_file()]
    return hashlib.sha256("".join(parts).encode()).hexdigest()


def verify_imported_c(root, bundle, rows):
    """Cheap, read-only revalidation of the previously exact-replayed bundle."""
    if (sha(root / "evidence/review-one-completion.json") != REVIEW_SHA
            or bundle["provenance"]["manifest_hash"] != fingerprint(rows)
            or set(bundle["records"]) != {r["sample_id"] for r in rows}):
        raise ValueError("historical_import_bundle_changed")
    review = load(root / "evidence/review-one-completion.json")
    for name, expected in review["code_sha256"].items():
        if sha(root / "src" / name) != expected: raise ValueError("reviewed_source_changed")
    for name, expected in review["evidence_sha256"].items():
        if sha(root / "evidence" / name) != expected: raise ValueError("historical_review_evidence_changed")
    crop = load(root / "evidence/R-M2-3-1.json")
    for name in ["A", "C"]:
        if tree_hash(root / "runs/development" / name) != crop["preserved_artifacts"]["run_trees"][name]["after_sha256"]:
            raise ValueError("historical_run_tree_changed")
    for ref in bundle["provenance"]["chat_refs"]:
        for kind, field in [("responses", "cache_sha256"), ("attempts", "counter_sha256")]:
            path = root / f"runtime_cache/{kind}/chat" / (ref["request_hash"] + ".json")
            if sha(path) != ref[field]: raise ValueError("historical_chat_receipt_changed")
    for row in rows:
        key = fingerprint(row["sample_id"])[:24] + ".json"
        saved = bundle["records"][row["sample_id"]]
        if (saved["identity"] != load(root / "runs/development/A/identities" / key)
                or saved["portion"] != load(root / "runs/development/C/records" / key)["portion_result"]):
            raise ValueError("historical_bundle_record_changed")
    return True


def import_raw_c(root, rows, catalog, retriever, embeddings):
    """Reconstruct every request including exact pixels; never writes old state."""
    from pipeline_v2 import ComponentPipeline
    root = Path(root).resolve()
    review_path = root / "evidence/review-one-completion.json"
    if sha(review_path) != REVIEW_SHA:
        raise ValueError("historical_review_changed")
    review = load(review_path)
    if review["status"] != "approved_or_fixed" or review["unresolved_p1_p2"] != 0:
        raise ValueError("historical_review_not_complete")
    old, current = review["original_code_sha256"], review["code_sha256"]
    if {k for k in old if old[k] != current[k]} != {"pipeline_v2.py", "opt_metrics.py"}:
        raise ValueError("unreviewed_source_drift")
    for name, expected in current.items():
        if sha(root / "src" / name) != expected:
            raise ValueError("reviewed_source_changed")
    for name, expected in review["evidence_sha256"].items():
        if sha(root / "evidence" / name) != expected:
            raise ValueError("historical_review_evidence_changed")
    crop = load(root / "evidence/R-M2-3-1.json")
    selected = crop["selected_model_path"]
    if (selected["c_identities"] != 84 or selected["equal_to_a_identities"] != 84
            or selected["with_any_crop"] != 0
            or not all(review["review_source_compatibility"][k] for k in
                ["complete_metrics_unchanged", "raw_run_bindings_preserved", "selected_inference_path_unchanged"])):
        raise ValueError("historical_source_bridge_changed")
    for name in ["A", "C"]:
        directory = root / "runs/development" / name
        if tree_hash(directory) != crop["preserved_artifacts"]["run_trees"][name]["after_sha256"]:
            raise ValueError("historical_run_tree_changed")
        cfg = load(directory / "run_config.json")
        expected_config = ({"crop_review": False, "portion_mode": "direct", "profile": "A"} if name == "A" else
            {"crop_review": False, "portion_mode": "total_ratio", "profile": "C", "identity_profile": "A"})
        if cfg["config"] != expected_config or cfg["manifest_sha256"] != fingerprint(rows) or cfg["code_sha256"] != old:
            raise ValueError("historical_run_configuration_changed")
        for key, path in {"catalog_sha256": "data/catalog.json", "protocol_sha256": "PROTOCOL.md",
            "experiment_sha256": "config/experiment.json", "candidate_sha256": "config/candidates.json",
            "vector_sha256": "data/vectors/manifest.json"}.items():
            if cfg[key] != sha(root / path):
                raise ValueError("historical_asset_changed")
    a, c = [root / "runs/development" / n for n in ["A", "C"]]
    cfg_c = load(c / "run_config.json")
    if cfg_c["source"] != {"directory": "runs/development/A",
            "identities_sha256": sha(a / "identities_sealed.json"),
            "records_sha256": sha(a / "records_sealed.json")}:
        raise ValueError("historical_identity_source_changed")
    seals = {(name, kind): load(root / "runs/development" / name / (kind + "_sealed.json"))
             for name in ["A", "C"] for kind in ["identities", "records"]}
    for seal in seals.values():
        if set(seal) != {r["sample_id"] for r in rows}:
            raise ValueError("historical_seal_population_changed")
    logs = {name: read_logs([root / "runs/development" / name / "requests.jsonl"], "chat") for name in ["A", "C"]}
    refs, output, texts = [], {}, set()
    phase = "A"
    def chat(messages):
        payload = {"model": CHAT_MODEL, "temperature": 1, "max_completion_tokens": 8192, "messages": messages}
        h = request_hash("chat", payload, OLD_CHAT_NAMESPACE)
        path = root / "runtime_cache/responses/chat" / (h + ".json")
        value = cache_value(path, h, "chat")
        counter_path = root / "runtime_cache/attempts/chat" / (h + ".json")
        counter = load(counter_path)
        if counter["namespace"] != OLD_CHAT_NAMESPACE:
            raise ValueError("historical_chat_namespace_changed")
        check_success(h, "chat", logs[phase].get(h, []), counter)
        refs.append({"role": "chat", "request_hash": h, "cache_sha256": sha(path),
            "counter_sha256": sha(counter_path), "value_hash": fingerprint(value)})
        return value
    def embed(queries):
        out = []
        for text in queries:
            texts.add(text)
            h = request_hash("embedding", embedding_payload(text), "official-query-v1")
            out.append(imported_embedding(root, embeddings, h))
        return out
    pipe = ComponentPipeline(chat, embed, catalog, retriever)
    for row in rows:
        if row["split"] != "dev" or row["dataset"] != "nutrition5k":
            raise ValueError("historical_import_dev_only")
        key = fingerprint(row["sample_id"])[:24] + ".json"
        files = {(name, kind): root / "runs/development" / name / kind / key
                 for name in ["A", "C"] for kind in ["identities", "records"]}
        for (name, kind), path in files.items():
            if sha(path) != seals[(name, kind)][row["sample_id"]]:
                raise ValueError("historical_sealed_record_changed")
        identity = load(files[("A", "identities")])
        record = load(files[("C", "records")])
        if load(files[("C", "identities")]) != identity or record["fallback"]:
            raise ValueError("historical_identity_or_fallback_changed")
        path = checked_path(root, row["image_path"])
        if sha(path) != row["image_sha256"]:
            raise ValueError("historical_image_bytes_changed")
        phase = "A"
        rebuilt = pipe.identify(path, {"crop_review": False, "portion_mode": "direct"})
        if rebuilt != identity:
            raise ValueError("historical_identity_request_replay_changed")
        phase = "C"
        portion = pipe.portion(path, identity, {"crop_review": False, "portion_mode": "total_ratio"})
        if portion != record["portion_result"] or portion["raw_prediction"] != record["raw_prediction"]:
            raise ValueError("historical_quantity_request_replay_changed")
        output[row["sample_id"]] = {"identity": identity, "portion": portion}
    return {"records": output, "provenance": {"origin": "historical_raw_C", "new_requests": 0,
        "review_sha256": REVIEW_SHA, "manifest_hash": fingerprint(rows), "chat_refs": refs,
        "unique_exact_embedding_texts": len(texts), "no_modern_receipts_created": True}}
