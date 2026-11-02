"""Explicit external-training inputs and label-free development queries.

This loader never opens development reference labels or validation records.
Training preparation owns the blind exclusion proof. These adapters expose only
the narrow values needed by the pure inference pipeline.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image
from opt_pipeline import encode_image
from round4.src.image_guard import payload_hash

DEV_MANIFEST = "data/cohorts/dev.jsonl"
DEV_MANIFEST_SHA256 = "ec02c058653b5505b01abee882c8b04a4711ec93b0c08496b962c2faf1586fe9"
TRAIN = "round4/data/train"
DEV_N, DEV_GROUPS = 84, 78
SOURCE_NAMES = (
    "round4/PROTOCOL.md",
    "src/opt_provider.py", "src/opt_pipeline.py",
    "round4/src/vision_stages.py", "round4/src/retrieval.py",
    "round4/src/catalog_estimator.py", "round4/src/pipeline.py",
    "round4/src/artifacts.py", "round4/src/train_data.py",
    "round4/src/context.py", "round4/src/run_base.py", "round4/src/trace_provider.py",
    "round4/src/capability_probe.py",
    "round4/src/image_guard.py",
)
METHOD_CONFIG = {
    "method": "external_training_gallery_r4.1", "chat_model": "gpt-6.1-sol",
    "chat_url": "https://api.zicc.cc/v1/chat/completions",
    "embedding_model": "text-embedding-3-large",
    "embedding_url": "https://api.openai.com/v1/embeddings", "embedding_dimensions": 3072,
    "temperature": 1, "description_tokens": 4096, "rerank_tokens": 4096,
    "estimator_tokens": 8192, "format_repairs": 1,
    "max_http_attempts_per_exact_payload": 3, "retrieval_k": 12, "support_count": 4,
    "namespace": "external-gallery-r4.1", "calibration": None,
    "gallery_failure": "stop", "query_description_failure": "fixed_train_medians",
    "rerank_failure": "retrieval_top_four", "estimator_failure": "fixed_train_medians",
    "validation_opened": False,
}


class ContextError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ContextError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(values):
        out = {}
        for key, value in values:
            require(key not in out, "duplicate_json_key")
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False, "nonfinite_json"))


def safe_path(base, relative):
    base, relative = Path(base), Path(relative)
    require(base.is_dir() and base.resolve() == base, "unsafe_context_root")
    require(not relative.is_absolute() and ".." not in relative.parts, "unsafe_input_path")
    path = base / relative
    require(path.resolve() == path and path.is_file(), "missing_or_noncanonical_input")
    return path


def rgb_hash(raw):
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        return digest(str(image.size).encode() + b"\0" + image.tobytes())


class Inputs:
    def __init__(self, base):
        self.base = Path(base)
        self.hashes = {}

    def read(self, name, expected=None):
        raw = safe_path(self.base, name).read_bytes()
        value = digest(raw)
        require(expected is None or value == expected, "pinned_input_changed")
        require(name not in self.hashes or self.hashes[name] == value, "input_changed_during_load")
        self.hashes[name] = value
        return raw

    def json(self, name, expected=None):
        return decode(self.read(name, expected))

    def unchanged(self):
        for name, value in self.hashes.items():
            require(digest(safe_path(self.base, name).read_bytes()) == value, "bound_input_changed")


def load_context(base, *, verify_train=None, verify_capability=None):
    """Load frozen train assets and 84 query images, never their targets.

    The injectable verifier exists for synthetic tests. Production uses the
    training-only integrity verifier, including immutable acquisition receipts.
    """
    base = Path(base).resolve()
    if verify_train is None:
        from round4.src.train_data import verify_train_only
        verify_train = verify_train_only
    proof = verify_train(base)
    require(proof.get("status") == "accepted_external_training_verified", "training_not_released")
    if verify_capability is None:
        from round4.src.capability_probe import verify_capability
    capability = verify_capability(base)
    require(capability.get("status") == "capability_passed"
            and capability.get("training_freeze_sha256") == proof["freeze_sha256"],
            "training_capability_not_verified")
    reader = Inputs(base)
    reader.read("round4/runs/capability/completion.json", capability["completion_sha256"])
    freeze_raw = reader.read(TRAIN + "/freeze.json", proof["freeze_sha256"])
    freeze = decode(freeze_raw)
    sealed = freeze["artifacts"]
    train = [decode(line) for line in reader.read(TRAIN + "/manifest.jsonl", sealed["manifest.jsonl"]).splitlines()]
    require(len(train) == proof["accepted_images"] and len(train) >= 12, "training_population_changed")
    require(len({r["sample_id"] for r in train}) == len(train), "duplicate_training_id")
    ingredients = reader.json(TRAIN + "/ingredients.json", sealed["ingredients.json"])["records"]
    ingredient_by_id = {r["sample_id"]: r for r in ingredients}
    require(len(ingredient_by_id) == len(ingredients)
            and set(ingredient_by_id) == {r["sample_id"] for r in train}, "training_ingredient_population_changed")
    catalog = reader.json(TRAIN + "/catalog.json", sealed["catalog.json"])["ingredients"]
    canonical_catalog = [{k: r[k] for k in ("ingredient_id", "name", "density_per_100g")} for r in catalog]
    fallback = reader.json(TRAIN + "/fallback.json", sealed["fallback.json"])["prediction"]
    entries, supports, payloads = [], {}, {}
    for row in train:
        require(row["split"] == "train" and row["dataset"] == "nutrition5k", "nontraining_support")
        raw = reader.read(row["image_path"], row["image_sha256"])
        require(rgb_hash(raw) == row["rgb_sha256"], "training_rgb_changed")
        payloads[row["image_sha256"]] = payload_hash(encode_image(io.BytesIO(raw), "native"))
        entries.append({"train_id": row["sample_id"], "screening_group_id": row["group_id"],
                        "image_sha256": row["image_sha256"], "rgb_sha256": row["rgb_sha256"]})
        supports[row["sample_id"]] = {
            "image_path": str(safe_path(base, row["image_path"])),
            "ingredients": [{k: r[k] for k in ("ingredient_id", "grams")}
                            for r in ingredient_by_id[row["sample_id"]]["ingredients"] if r["grams"] > 0],
        }
    all_rows = [decode(line) for line in reader.read(DEV_MANIFEST, DEV_MANIFEST_SHA256).splitlines()]
    rows = [r for r in all_rows if r["dataset"] == "nutrition5k"]
    require(len(rows) == DEV_N and len({r["sample_id"] for r in rows}) == DEV_N
            and len({r["group_id"] for r in rows}) == DEV_GROUPS
            and {r["fold"] for r in rows} == set(range(5))
            and all(r["split"] == "dev" for r in rows), "development_population_changed")
    train_bytes, train_rgb = {r["image_sha256"] for r in entries}, {r["rgb_sha256"] for r in entries}
    queries = []
    for row in rows:
        raw = reader.read(row["image_path"], row["image_sha256"])
        pixels = rgb_hash(raw)
        payloads[row["image_sha256"]] = payload_hash(encode_image(io.BytesIO(raw), "native"))
        require(row["image_sha256"] not in train_bytes and pixels not in train_rgb, "train_query_pixel_overlap")
        queries.append({"query_id": row["sample_id"], "image_path": str(safe_path(base, row["image_path"])),
                        "image_sha256": row["image_sha256"], "rgb_sha256": pixels,
                        # Original v2 groups and training screening groups have
                        # different namespaces. The frozen exclusion proof,
                        # rather than equality here, excludes related groups.
                        "screening_group_id": row["group_id"]})
    for name in SOURCE_NAMES:
        reader.read(name)
    reader.unchanged()
    return {
        "reader": reader, "rows": rows, "queries": queries, "entries": entries, "payloads": payloads,
        "training_manifest": train, "training_proof": proof,
        "assets": {"scope": "external_train_only", "training_sha256": digest(freeze_raw),
                   "catalog": canonical_catalog, "fallback": fallback, "supports": supports},
        "binding": {"schema_version": 1, "method_config": decode(json.dumps(METHOD_CONFIG)),
                    "training_freeze_sha256": digest(freeze_raw),
                    "capability_completion_sha256": capability["completion_sha256"],
                    "training_exclusion_binding": freeze["binding"],
                    "query_count": DEV_N, "query_groups": DEV_GROUPS,
                    "encoded_image_sha256_by_source_sha256": dict(payloads),
                    "input_sha256": dict(reader.hashes)},
    }
