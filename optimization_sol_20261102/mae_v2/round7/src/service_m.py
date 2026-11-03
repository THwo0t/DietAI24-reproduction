"""Role-separated service evidence, with explicit read-only historical imports."""
import json
import math
from pathlib import Path

from opt_provider import CHAT_URL, CHAT_MODEL, EMBED_URL, EMBED_MODEL, fingerprint, sha
from historical_m import cache_value, checked_path, imported_embedding, load, request_hash

NAMESPACE = "shared-accounting-r7-m.1"
DIRECTORY = "round7/provider/M"


def spec(role, payload):
    if role == "chat":
        if (set(payload) != {"model", "temperature", "max_completion_tokens", "messages"}
                or payload["model"] != CHAT_MODEL or type(payload["temperature"]) is not int or payload["temperature"] != 1
                or payload["max_completion_tokens"] != 8192):
            raise ValueError("M_chat_payload_changed")
        ns, url, model = NAMESPACE, CHAT_URL, CHAT_MODEL
    elif role == "embedding":
        if (set(payload) != {"model", "input", "encoding_format"} or payload["model"] != EMBED_MODEL
                or payload["encoding_format"] != "float" or not isinstance(payload["input"], list)
                or len(payload["input"]) != 1 or not isinstance(payload["input"][0], str)
                or not payload["input"][0].strip() or len(payload["input"][0]) > 12000):
            raise ValueError("M_embedding_payload_changed")
        ns, url, model = "official-query-v1", EMBED_URL, EMBED_MODEL
    else:
        raise ValueError("M_unknown_service_role")
    return request_hash(role, payload, ns), url, model


def paths(root, role, h):
    if role not in ("chat", "embedding") or len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        raise ValueError("M_invalid_service_key")
    base = checked_path(root, DIRECTORY)
    return (checked_path(base, f"attempts/{role}/{h}.json"),
            checked_path(base, f"responses/{role}/{h}.json"))


def logs(root, role=None, h=None):
    path = checked_path(root, DIRECTORY + "/requests.jsonl")
    result = []
    for line in path.read_text().splitlines() if path.is_file() else []:
        row = json.loads(line)
        if (role is None or row.get("role") == role) and (h is None or row.get("request_hash") == h):
            result.append(row)
    return result


def audit_target(root, role, h, allow_absent=True, allow_incomplete=True):
    counter_path, cache_path = paths(root, role, h)
    history = logs(root, role, h)
    present = counter_path.exists() or cache_path.exists() or bool(history)
    if not present and allow_absent:
        return {"value": None, "files": {}, "reserved": 0, "logged": 0}
    if not counter_path.is_file():
        raise ValueError("M_service_counter_missing")
    state = load(counter_path)
    if (set(state) != {"request_hash", "attempts", "last_reserved", "namespace"}
            or state["request_hash"] != h or state["namespace"] != NAMESPACE
            or type(state["attempts"]) is not int or not 1 <= state["attempts"] <= 3
            or not isinstance(state["last_reserved"], str) or not state["last_reserved"]):
        raise ValueError("M_service_counter_invalid")
    model, url = (CHAT_MODEL, CHAT_URL) if role == "chat" else (EMBED_MODEL, EMBED_URL)
    previous, successes = 0, []
    for row in history:
        attempt = row.get("attempt")
        if (type(attempt) is not int or not previous < attempt <= state["attempts"]
                or row.get("endpoint") != url or row.get("model_requested") != model
                or row.get("status") is not None and type(row["status"]) is not int):
            raise ValueError("M_service_log_counter_mismatch")
        previous = attempt
        if row["status"] == 200:
            if row.get("model_served") != model:
                raise ValueError("M_service_model_changed")
            successes.append(row)
    files = {str(counter_path.relative_to(root)): sha(counter_path)}
    value = None
    if cache_path.is_file():
        if len(successes) != 1 or successes[0] is not history[-1] or previous != state["attempts"]:
            raise ValueError("M_success_cache_without_final_log")
        value = cache_value(cache_path, h, role)
        if successes[0].get("value_hash") != fingerprint(value):
            raise ValueError("M_success_log_return_value_changed")
        files[str(cache_path.relative_to(root))] = sha(cache_path)
    elif successes:
        raise ValueError("M_success_log_cache_missing")
    elif not allow_incomplete or state["attempts"] >= 3:
        raise ValueError("M_pending_payload_exhausted_or_incomplete")
    return {"value": value, "files": files, "reserved": state["attempts"], "logged": len(history)}


def audit_state(root, allow_incomplete=True):
    keys = {(r["role"], r["request_hash"]) for r in logs(root)}
    for role in ("chat", "embedding"):
        for kind in ("responses", "attempts"):
            directory = checked_path(root, f"{DIRECTORY}/{kind}/{role}")
            keys.update((role, p.stem) for p in directory.glob("*.json"))
    files, counts = {}, {role: {"payloads": 0, "successful_payloads": 0, "reserved_attempts": 0,
                                "logged_transmissions": 0} for role in ("chat", "embedding")}
    for role, h in sorted(keys):
        item = audit_target(root, role, h, allow_absent=False, allow_incomplete=allow_incomplete)
        files.update(item["files"])
        out = counts[role]
        out["payloads"] += 1
        out["successful_payloads"] += item["value"] is not None
        out["reserved_attempts"] += item["reserved"]
        out["logged_transmissions"] += item["logged"]
    path = checked_path(root, DIRECTORY + "/requests.jsonl")
    if path.is_file(): files[str(path.relative_to(root))] = sha(path)
    for role in counts:
        counts[role]["unlogged_reservations"] = counts[role]["reserved_attempts"] - counts[role]["logged_transmissions"]
    return {"namespace": NAMESPACE, "files": files, "counts": counts}


def verify_ref(root, imports, ref):
    if (set(ref) != {"role", "request_hash", "value_hash", "status", "origin", "cache_present_before"}
            or ref["status"] != "returned" or type(ref["cache_present_before"]) is not bool):
        raise ValueError("M_service_ref_fields_changed")
    role, h = ref["role"], ref["request_hash"]
    if ref["origin"] == "historical_embedding_import":
        if role != "embedding": raise ValueError("M_chat_import_forbidden")
        value = imported_embedding(root, imports, h)
    elif ref["origin"] == "new_M":
        value = audit_target(root, role, h, allow_absent=False, allow_incomplete=False)["value"]
    else:
        raise ValueError("M_unknown_service_origin")
    if value is None or fingerprint(value) != ref["value_hash"]:
        raise ValueError("M_referenced_return_value_changed")
    return value


def completion_proof(root, imports, stage_refs):
    for refs in stage_refs.values():
        for ref in refs: verify_ref(root, imports, ref)
    # Pin every imported source at completion, even imports not queried by M.
    for relative, expected in imports["source_files"].items():
        if sha(checked_path(Path(root).parent, relative)) != expected:
            raise ValueError("M_import_inventory_changed")
    proof = audit_state(root, allow_incomplete=False)
    proof.update(import_manifest_hash=fingerprint(imports), stage_refs_hash=fingerprint(stage_refs),
        imported_logical_hits=sum(r["origin"] == "historical_embedding_import" for refs in stage_refs.values() for r in refs))
    return proof


class Replay:
    def __init__(self, root, imports, refs):
        self.root, self.imports, self.refs, self.index = root, imports, refs, 0

    def request(self, role, payload):
        h, _, _ = spec(role, payload)
        if self.index >= len(self.refs): raise ValueError("M_replay_missing_request")
        ref = self.refs[self.index]
        self.index += 1
        if (ref["role"], ref["request_hash"]) != (role, h):
            raise ValueError("M_exact_payload_or_order_changed")
        return verify_ref(self.root, self.imports, ref)

    def chat(self, messages):
        return self.request("chat", {"model": CHAT_MODEL, "temperature": 1,
            "max_completion_tokens": 8192, "messages": messages})

    def embed(self, texts):
        return [self.request("embedding", {"model": EMBED_MODEL, "input": [text], "encoding_format": "float"})
                for text in texts]

    def finish(self):
        if self.index != len(self.refs): raise ValueError("M_replay_extra_request")
