"""M-only durable transport. Old providers/results are never modified."""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid

import httpx
from opt_provider import ROOT, Provider, ProviderStop, sanitize, stamp, fingerprint
from historical_m import checked_path, imported_embedding, load
from service_m import NAMESPACE, DIRECTORY, audit_state, audit_target, paths, spec


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def durable_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)
    sync_dir(path.parent)


class MProvider(Provider):
    def __init__(self, imports, *, root=ROOT, allow_paid=False, keys=None, transport=None, sleep=None):
        self.mroot, self.imports = Path(root).resolve(), imports
        audit_state(self.mroot)
        # In production the inherited scoped() root is fixed. Tests patch that
        # module constant only before construction; live code never changes it.
        kwargs = {} if sleep is None else {"sleep": sleep}
        super().__init__(self.mroot / DIRECTORY, allow_paid=allow_paid, namespace=NAMESPACE,
                         keys=keys, transport=transport, timeout=600, **kwargs)
        self.client.timeout = httpx.Timeout(read=600, connect=30, write=120, pool=120)
        self.cache = self.mroot / DIRECTORY / "responses"

    def _log(self, record):
        path = checked_path(self.mroot, DIRECTORY + "/requests.jsonl")
        with self.lock:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(sanitize(record, self.keys), allow_nan=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            sync_dir(path.parent)

    @contextmanager
    def lifecycle(self, role, h):
        path = checked_path(self.mroot, f"{DIRECTORY}/locks/{role}/{h}.lock")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally: os.close(fd)

    def _reserve_attempt(self, h, role):
        item = audit_target(self.mroot, role, h)
        count = item["reserved"]
        if count >= 3: raise ProviderStop("M payload exhausted its persistent budget")
        path, _ = paths(self.mroot, role, h)
        durable_json(path, {"request_hash": h, "attempts": count + 1,
                            "last_reserved": stamp(), "namespace": NAMESPACE})
        return count + 1

    def chat(self, messages, max_completion_tokens=8192):
        if max_completion_tokens != 8192:
            raise ProviderStop("M completion limit changed")
        return super().chat(messages, max_completion_tokens=8192)

    def _request(self, role, payload):
        h, url, model = spec(role, payload)
        _, cache_path = paths(self.mroot, role, h)
        with self.lifecycle(role, h):
            previous = audit_target(self.mroot, role, h)
            if role == "embedding" and h in self.imports["entries"]:
                if previous["reserved"]:
                    raise ProviderStop("M imported response conflicts with fresh service state")
                return imported_embedding(self.mroot, self.imports, h)
            if previous["value"] is not None:
                return previous["value"]
            if role == "embedding":
                # Unknown historical state must never acquire a new three-attempt
                # budget through the M directory or implicit parent-cache copy.
                for base in [self.mroot, self.mroot.parent]:
                    if any((base / f"runtime_cache/{kind}/embedding/{h}.json").exists()
                           for kind in ["responses", "attempts"]):
                        raise ProviderStop("M encountered unregistered historical embedding state")
            key = self.keys[0 if role == "chat" else 1]
            for _ in range(3):
                attempt = self._reserve_attempt(h, role)
                record = {"started": stamp(), "role": role, "endpoint": url,
                    "model_requested": model, "request_hash": h, "attempt": attempt}
                try:
                    response = self.client.post(url, json=payload, headers={"Authorization": "Bearer " + key})
                except httpx.HTTPError as exc:
                    record.update(status=None, error_type=type(exc).__name__)
                    self._log(record)
                    if attempt == 3:
                        raise ProviderStop("M connection budget exhausted; preserve pending state") from None
                    self.sleep((2, 8)[attempt - 1])
                    continue
                record["status"] = response.status_code
                try: body = response.json()
                except ValueError: body = {}
                if not isinstance(body, dict): body = {}
                record.update(model_served=body.get("model"), usage=body.get("usage"))
                if response.status_code != 200:
                    error = body.get("error")
                    record["error_type"] = error.get("type") if isinstance(error, dict) else None
                    self._log(record)
                    if (response.status_code == 429 or response.status_code >= 500) and attempt < 3:
                        self.sleep((2, 8)[attempt - 1])
                        continue
                    raise ProviderStop("M provider HTTP failure; batch stopped")
                if body.get("model") != model:
                    self._log(record)
                    raise ProviderStop("M provider returned a different model")
                if role == "chat":
                    choices = body.get("choices")
                    if (not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict)
                            or not isinstance(choices[0].get("message"), dict)):
                        self._log(record)
                        raise ProviderStop("M malformed chat envelope")
                    record["finish_reason"] = choices[0].get("finish_reason")
                    content = choices[0]["message"].get("content")
                    value = content if isinstance(content, str) and record["finish_reason"] == "stop" else ""
                    value = sanitize(value, self.keys)
                else:
                    data = body.get("data")
                    value = data[0].get("embedding") if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict) else None
                    if not self._valid_vector(value):
                        self._log(record)
                        raise ProviderStop("M incompatible official embedding")
                record["value_hash"] = fingerprint(value)
                self._log(record)
                durable_json(cache_path, {"request_hash": h, "model": model, "value": value,
                                          "value_hash": fingerprint(value)})
                return value
        raise ProviderStop("M unexpected transport state")


class LazyTrace:
    def __init__(self, imports, allow_paid=False):
        self.imports, self.allow_paid = imports, allow_paid
        self.provider, self.lock, self.local = None, threading.Lock(), threading.local()

    def state(self):
        if not hasattr(self.local, "refs"):
            self.local.refs, self.local.image_hash = [], None
        return self.local

    def get(self):
        with self.lock:
            if self.provider is None:
                self.provider = MProvider(self.imports, allow_paid=self.allow_paid)
            return self.provider

    @contextmanager
    def expect(self, image_url):
        state = self.state()
        if state.image_hash is not None: raise ValueError("M_nested_image_scope")
        state.image_hash = hashlib.sha256(image_url.encode()).hexdigest()
        try: yield
        finally: state.image_hash = None

    def mark(self): return len(self.state().refs)
    def since(self, mark): return deepcopy(self.state().refs[mark:])

    def request(self, role, payload):
        h, _, _ = spec(role, payload)
        if role == "chat":
            urls = [block.get("image_url", {}).get("url", "") for message in payload["messages"]
                    if isinstance(message.get("content"), list) for block in message["content"]
                    if block.get("type") == "image_url"]
            if self.state().image_hash is None or [hashlib.sha256(u.encode()).hexdigest() for u in urls] != [self.state().image_hash]:
                raise ValueError("M_ordered_image_payload_changed")
        imported = role == "embedding" and h in self.imports["entries"]
        _, cache = paths(ROOT, role, h)
        before = imported or cache.is_file()
        value = self.get()._request(role, payload)
        self.state().refs.append({"role": role, "request_hash": h, "value_hash": fingerprint(value),
            "status": "returned", "origin": "historical_embedding_import" if imported else "new_M",
            "cache_present_before": before})
        return value

    def chat(self, messages):
        from opt_provider import CHAT_MODEL
        return self.request("chat", {"model": CHAT_MODEL, "temperature": 1,
            "max_completion_tokens": 8192, "messages": messages})

    def embed(self, texts):
        from opt_provider import EMBED_MODEL
        if not isinstance(texts, list) or not 1 <= len(texts) <= 12:
            raise ValueError("M_embedding_batch_changed")
        return [self.request("embedding", {"model": EMBED_MODEL, "input": [text], "encoding_format": "float"}) for text in texts]

    def close(self):
        if self.provider is not None: self.provider.close()
