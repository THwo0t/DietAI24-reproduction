"""Read-only K service provenance (R5-K4-1); no Provider or credential I/O.

Startup/finalization use audit_state; while workers run, audit_request and
verify_refs inspect only their target hashes. The original per-payload request
lock must still surround reserve/send/cache publication. A global audit must
not run while another request is between reservation, log and cache writes.

Only the fixed K log, chat-attempt directory and matching chat caches are read.
Other namespaces' counter objects are used only to exclude them from the K
inventory; their caches and counter semantics are not audited. Cache files do
not contain namespaces: an orphan cache with neither counter nor log can only
be attributed to K by an explicit request hash/ref, which is checked strictly.

Unlogged reservations consume the existing budget but are NOT claimed as
known transmissions. cache_present_before is merely a trace observation and
never waives successful-log evidence. A structural model failure still has
successful HTTP responses, and those empty/malformed response strings remain
ordinary successful-cache evidence. No exception creates a model fallback.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from opt_provider import CHAT_MODEL, CHAT_URL, fingerprint as response_fingerprint
from round4.src.artifacts import fingerprint as artifact_fingerprint

NAMESPACE = "component-comparison-r5-k.1"
LOG = "round5/provider/K/requests.jsonl"
ATTEMPTS = "runtime_cache/attempts/chat"
RESPONSES = "runtime_cache/responses/chat"
HEX = re.compile(r"[0-9a-f]{64}\Z")
REF_KEYS = {"role", "request_hash", "value_hash", "status", "cache_present_before"}
COUNTER_KEYS = {"request_hash", "attempts", "last_reserved", "namespace"}
CACHE_KEYS = {"request_hash", "model", "value", "value_hash"}


class ServiceEvidenceError(ValueError):
    """Fixed, non-sensitive error codes; never include paths or response text."""


def _require(condition, code):
    if not condition:
        raise ServiceEvidenceError(code)


def _hash(value):
    _require(isinstance(value, str) and HEX.fullmatch(value) is not None, "invalid_request_hash")
    return value


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_evidence_json_key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: _require(False, "nonfinite_evidence_json"))
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ServiceEvidenceError):
            raise
        raise ServiceEvidenceError("malformed_service_evidence_json") from None


class _Reader:
    def __init__(self, root):
        self.root = Path(root)
        _require(self.root.is_absolute() and self.root.is_dir() and not self.root.is_symlink()
                 and self.root.resolve() == self.root, "canonical_service_root_required")

    def path(self, relative, *, directory=False):
        relative = Path(relative)
        _require(not relative.is_absolute() and ".." not in relative.parts, "fixed_service_scope_required")
        current = self.root
        for index, part in enumerate(relative.parts):
            current /= part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                return None
            except OSError:
                raise ServiceEvidenceError("service_evidence_unreadable") from None
            _require(not stat.S_ISLNK(mode), "service_evidence_symlink_rejected")
            if index < len(relative.parts) - 1 or directory:
                _require(stat.S_ISDIR(mode), "service_evidence_directory_required")
            else:
                _require(stat.S_ISREG(mode), "service_evidence_regular_file_required")
        _require(current.resolve() == current, "service_evidence_path_changed")
        return current

    def read(self, relative):
        path = self.path(relative)
        if path is None:
            return None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                _require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "service_evidence_regular_file_required")
                return stream.read()
        except OSError:
            raise ServiceEvidenceError("service_evidence_unreadable") from None


def _refs(refs):
    _require(isinstance(refs, list), "service_reference_list_required")
    for ref in refs:
        _require(isinstance(ref, dict) and set(ref) == REF_KEYS, "service_reference_fields_changed")
        _hash(ref["request_hash"])
        _hash(ref["value_hash"])
        _require(ref["role"] == "chat" and ref["status"] == "returned"
                 and type(ref["cache_present_before"]) is bool, "successful_chat_reference_required")
    return refs


def _logs(reader, target=None):
    raw = reader.read(LOG)
    if raw is None:
        return {}, None
    _require(not raw or raw.endswith(b"\n"), "truncated_service_log")
    rows = {}
    for line in raw.splitlines():
        value = _decode(line)
        _require(isinstance(value, dict), "service_log_object_required")
        h = value.get("request_hash")
        if target is not None and h != target:
            continue
        _hash(h)
        _require(value.get("role") == "chat" and value.get("endpoint") == CHAT_URL
                 and value.get("model_requested") == CHAT_MODEL, "service_log_route_or_requested_model_changed")
        attempt, status = value.get("attempt"), value.get("status")
        _require(type(attempt) is int and 1 <= attempt <= 3, "service_log_attempt_out_of_budget")
        _require("status" in value and (status is None or (type(status) is int and 100 <= status <= 599)),
                 "invalid_service_log_status")
        if status == 200:
            _require(value.get("model_served") == CHAT_MODEL, "successful_service_model_changed")
        history = rows.setdefault(h, [])
        _require(not history or attempt > history[-1]["attempt"], "duplicate_or_reordered_service_attempt")
        history.append(value)
    return rows, hashlib.sha256(raw).hexdigest()


def _counter(reader, h):
    raw = reader.read(f"{ATTEMPTS}/{h}.json")
    _require(raw is not None, "service_attempt_counter_missing")
    value = _decode(raw)
    _require(isinstance(value, dict) and set(value) == COUNTER_KEYS
             and value["request_hash"] == h and value["namespace"] == NAMESPACE
             and type(value["attempts"]) is int and 1 <= value["attempts"] <= 3
             and isinstance(value["last_reserved"], str) and bool(value["last_reserved"].strip()),
             "service_attempt_counter_invalid")
    return value, hashlib.sha256(raw).hexdigest()


def _cache(reader, h):
    raw = reader.read(f"{RESPONSES}/{h}.json")
    if raw is None:
        return None, None
    value = _decode(raw)
    _require(isinstance(value, dict) and set(value) == CACHE_KEYS
             and value["request_hash"] == h and value["model"] == CHAT_MODEL
             and isinstance(value["value"], str)
             and value["value_hash"] == response_fingerprint(value["value"]), "successful_cache_changed")
    return value, hashlib.sha256(raw).hexdigest()


def _inspect(reader, hashes, rows, log_sha, refs, *, allow_incomplete):
    _require(type(allow_incomplete) is bool, "boolean_incomplete_policy_required")
    counters, caches, values = {}, {}, {}
    reserved = logged = pending = 0
    for h in sorted(hashes):
        state, counters[h] = _counter(reader, h)
        count = state["attempts"]
        history = rows.get(h, [])
        _require(not history or history[-1]["attempt"] <= count, "service_log_exceeds_reserved_attempts")
        successful = [row for row in history if row["status"] == 200]
        _require(len(successful) <= 1, "multiple_successes_for_same_payload")
        cache, cache_sha = _cache(reader, h)
        if cache is not None:
            _require(len(successful) == 1 and successful[0] is history[-1]
                     and successful[0]["attempt"] == count, "successful_cache_counter_or_log_mismatch")
            caches[h], values[h] = cache_sha, cache
        else:
            _require(not successful, "successful_log_cache_missing")
            pending += 1
            _require(count < 3, "pending_payload_attempts_exhausted")
            _require(allow_incomplete, "unfinished_service_request")
        reserved += count
        logged += len(history)
    for ref in refs:
        _require(ref["request_hash"] in values, "referenced_success_cache_missing")
        _require(ref["value_hash"] == values[ref["request_hash"]]["value_hash"], "reference_cache_value_hash_changed")
    return {"schema_version": 1, "namespace": NAMESPACE, "log_sha256": log_sha,
            "counter_sha256": counters, "cache_sha256": caches,
            "counts": {"request_count": len(hashes), "success_count": len(caches), "pending_count": pending,
                       "exhausted_pending_count": 0, "reserved_attempts": reserved, "logged_attempts": logged,
                       "unlogged_attempts": reserved - logged, "transmissions": logged}}


def audit_state(root, *, require_success_refs=None, allow_incomplete=True):
    """Audit all known K state at startup or after worker join, without writes.

    require_success_refs, when supplied, is a list of the original five-key
    returned chat references. Missing referenced state is always an error.
    Pending counters below three are allowed only with allow_incomplete=True;
    an exhausted pending payload always stops a paid resume.
    """
    reader = _Reader(root)
    refs = _refs([] if require_success_refs is None else require_success_refs)
    rows, log_sha = _logs(reader)
    hashes = set(rows) | {ref["request_hash"] for ref in refs}
    directory = reader.path(ATTEMPTS, directory=True)
    if directory is not None:
        for path in sorted(directory.iterdir()):
            if not path.name.endswith(".json"):
                continue  # Per-payload locks and unpublished temporary files.
            raw = reader.read(f"{ATTEMPTS}/{path.name}")
            _require(raw is not None, "attempt_inventory_changed_during_read")
            state = _decode(raw)
            _require(isinstance(state, dict), "attempt_inventory_object_required")
            if state.get("namespace") == NAMESPACE:
                hashes.add(_hash(path.name[:-5]))
    return _inspect(reader, hashes, rows, log_sha, refs, allow_incomplete=allow_incomplete)


def audit_request(root, request_hash, *, allow_incomplete=True):
    """Audit only one locked payload, ignoring other workers' pending requests.

    Only this targeted entry point allows an explicitly requested new hash to
    have no counter, log or cache and returns an empty aggregate for that hash.
    """
    h, reader = _hash(request_hash), _Reader(root)
    rows, log_sha = _logs(reader, target=h)
    counter = reader.read(f"{ATTEMPTS}/{h}.json")
    cache = reader.read(f"{RESPONSES}/{h}.json")
    hashes = {h} if counter is not None or cache is not None or h in rows else set()
    return _inspect(reader, hashes, rows, log_sha, [], allow_incomplete=allow_incomplete)


def verify_refs(root, refs, values):
    """Validate returned values against their target cache/counter/success log.

    No global inventory scan: unrelated requests may currently be in flight.
    Reused references still require the original successful transmission log.
    """
    refs = _refs(refs)
    _require(isinstance(values, list) and len(values) == len(refs), "reference_value_count_changed")
    reader = _Reader(root)
    for ref, value in zip(refs, values):
        _require(isinstance(value, str) and response_fingerprint(value) == ref["value_hash"],
                 "reference_returned_value_changed")
        h = ref["request_hash"]
        rows, log_sha = _logs(reader, target=h)
        _inspect(reader, {h}, rows, log_sha, [ref], allow_incomplete=False)
    return None


def completion_proof(root, stage_refs):
    """Freeze complete K service state plus hashes of explicitly supplied refs.

    stage_refs maps opaque stage names to exactly {refs, values}; only the
    hypotheses/mass stages belong here. Caller supplies their sealed envelopes,
    invokes this after all workers join, and binds the returned proof to its own
    ArtifactStore stage. Recomputing against that sealed proof detects removed
    files, changed bytes and increased counters, without constructing a Provider.
    """
    _require(isinstance(stage_refs, Mapping) and bool(stage_refs), "completed_stage_references_required")
    refs, ref_count = [], 0
    for name, item in stage_refs.items():
        _require(isinstance(name, str) and bool(name) and isinstance(item, Mapping)
                 and set(item) == {"refs", "values"}, "completed_stage_reference_fields_changed")
        _require(isinstance(item["refs"], list) and 1 <= len(item["refs"]) <= 2,
                 "completed_stage_response_count_changed")
        verify_refs(root, item["refs"], item["values"])
        refs.extend(item["refs"])
        ref_count += len(item["refs"])
    proof = audit_state(root, require_success_refs=refs, allow_incomplete=False)
    proof.update(stage_refs_sha256=artifact_fingerprint(dict(stage_refs)),
                 stage_count=len(stage_refs), ref_count=ref_count)
    return proof
