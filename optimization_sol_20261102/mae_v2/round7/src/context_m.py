"""M development preparation and a separate label-free runtime loader."""
from collections import Counter
import json
import os
from pathlib import Path
from types import SimpleNamespace

from opt_provider import ROOT, fingerprint, sha
from historical_m import checked_path, import_raw_c, load, prepare_embedding_imports, verify_imported_c

ROUND = ROOT / "round7"
PREPARED = ROUND / "prepared"


def manifest(root=ROOT):
    if sha(root / "data/cohorts/dev.jsonl") != "ec02c058653b5505b01abee882c8b04a4711ec93b0c08496b962c2faf1586fe9":
        raise ValueError("M_frozen_development_manifest_changed")
    rows = [json.loads(line) for line in (root / "data/cohorts/dev.jsonl").read_text().splitlines()]
    keys = {"sample_id", "dataset", "split", "fold", "group_id", "image_path", "image_sha256"}
    if (any(set(r) != keys or r["split"] != "dev" or type(r["fold"]) is not int
            or r["fold"] not in range(5) for r in rows)
            or len({r["sample_id"] for r in rows}) != len(rows)
            or Counter(r["dataset"] for r in rows) != {"asa24": 99, "nutrition5k": 84}):
        raise ValueError("M_registered_development_population_changed")
    groups = {}
    for row in rows:
        key = (row["dataset"], row["group_id"])
        if key in groups and groups[key] != row["fold"]:
            raise ValueError("M_group_crosses_folds")
        groups[key] = row["fold"]
        if "/dev/images/" not in row["image_path"] or sha(checked_path(root, row["image_path"])) != row["image_sha256"]:
            raise ValueError("M_development_image_changed")
    if Counter(ds for ds, _ in groups) != {"asa24": 23, "nutrition5k": 78}:
        raise ValueError("M_frozen_association_groups_changed")
    return rows


def assets(root=ROOT):
    import numpy as np
    from opt_pipeline import Retriever
    catalog = load(root / "data/catalog.json")
    directory = root / "data/vectors"
    description = load(directory / "manifest.json")
    if (description["vectors"] != 5624 or description["dimensions"] != 3072
            or description["embedding_model"] != "text-embedding-3-large"):
        raise ValueError("M_vector_descriptor_changed")
    for name, expected in description["files"].items():
        if sha(checked_path(directory, name)) != expected:
            raise ValueError("M_vector_file_changed")
    codes = load(directory / "codes.json")
    if set(codes) != set(catalog["foods"]):
        raise ValueError("M_catalog_vector_codes_changed")
    matrix = np.load(directory / "embeddings.npy", allow_pickle=False)
    if matrix.shape != (5624, 3072):
        raise ValueError("M_vector_shape_changed")
    retriever = Retriever(codes, matrix, catalog)
    retriever.vectors.setflags(write=False)
    return catalog, retriever


def write_once(path, value):
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists():
        if path.read_text() != raw:
            raise ValueError("M_prepared_artifact_conflict")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def prepare():
    # This isolated stage is allowed to read development labels, never validation.
    from cohorts_v2 import load_dev
    from opt_metrics import fold_medians
    verified_rows, labels = load_dev()
    rows = manifest()
    if verified_rows != rows:
        raise ValueError("M_prepare_manifest_changed")
    fallbacks = {"manifest_sha256": sha(ROOT / "data/cohorts/dev.jsonl"),
        "labels_sha256": sha(ROOT / "data/cohorts/dev_labels.json"),
        "vectors": {ds: {str(f): fold_medians(rows, labels, f, ds) for f in range(5)}
                    for ds in ["asa24", "nutrition5k"]},
        "policy": "componentwise other-fold medians; no query label supplied to runner"}
    write_once(PREPARED / "fallbacks.json", fallbacks)
    embeddings = prepare_embedding_imports(ROOT)
    write_once(PREPARED / "embeddings.json", embeddings)
    catalog, retriever = assets()
    imported = import_raw_c(ROOT, [r for r in rows if r["dataset"] == "nutrition5k"],
                            catalog, retriever, embeddings)
    write_once(PREPARED / "raw_c.json", imported)
    return {"development_rows": len(rows), "imported_raw_c": len(imported["records"]),
        "imported_embeddings": len(embeddings["entries"]),
        "unusable_historical_embeddings": len(embeddings["rejected_hashes"]),
        "new_requests": 0, "validation_accessed": False}


def source_pins():
    files = list((ROUND / "src").glob("*.py"))
    files += [ROOT / "src" / name for name in ["opt_provider.py", "opt_pipeline.py", "pipeline_v2.py",
        "opt_metrics.py", "metrics_v2.py", "diagnostics_v2.py"]]
    files += [ROOT / "round4/src/artifacts.py", ROUND / "PROTOCOL.md"]
    files += [ROUND / "review_gate.json"]
    files += [PREPARED / n for n in ["fallbacks.json", "embeddings.json", "raw_c.json"]]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in files}


def freeze():
    gate = load(ROUND / "review_gate.json")
    if (gate.get("status") != "approved_or_fixed" or gate.get("unresolved_p1_p2") != 0
            or gate.get("review_sha256") != sha(ROUND / "REVIEW.md")):
        raise ValueError("M_independent_review_gate_incomplete")
    rows = manifest()
    assets()  # Verify full generic catalog/vector association before freezing.
    value = {"schema_version": 1, "source_files": source_pins(),
        "manifest_sha256": sha(ROOT / "data/cohorts/dev.jsonl"),
        "catalog_sha256": sha(ROOT / "data/catalog.json"),
        "vector_manifest_sha256": sha(ROOT / "data/vectors/manifest.json"),
        "dev_freeze_sha256": sha(ROOT / "data/cohorts/dev_freeze.json"),
        "rows_sha256": fingerprint(rows), "rows": len(rows),
        "review_sha256": sha(ROUND / "REVIEW.md")}
    write_once(PREPARED / "freeze.json", value)
    return value


def runtime_context():
    """No label loader, scorer, validation adapter or credential reader."""
    frozen = load(PREPARED / "freeze.json")
    if sha(ROUND / "REVIEW.md") != frozen["review_sha256"]:
        raise ValueError("M_frozen_review_changed")
    def verify_sources():
        for relative, expected in frozen["source_files"].items():
            if sha(checked_path(ROOT, relative)) != expected:
                raise ValueError("M_frozen_source_changed")
        return True
    verify_sources()
    rows = manifest()
    for key, relative in {"manifest_sha256": "data/cohorts/dev.jsonl", "catalog_sha256": "data/catalog.json",
        "vector_manifest_sha256": "data/vectors/manifest.json", "dev_freeze_sha256": "data/cohorts/dev_freeze.json"}.items():
        if sha(ROOT / relative) != frozen[key]:
            raise ValueError("M_frozen_input_changed")
    if fingerprint(rows) != frozen["rows_sha256"]:
        raise ValueError("M_frozen_population_changed")
    catalog, retriever = assets()
    imported = load(PREPARED / "raw_c.json")
    verify_imported_c(ROOT, imported, [r for r in rows if r["dataset"] == "nutrition5k"])
    return SimpleNamespace(rows=rows, catalog=catalog, retriever=retriever,
        fallbacks=load(PREPARED / "fallbacks.json"), embeddings=load(PREPARED / "embeddings.json"),
        imported=imported, binding=frozen, verify_sources=verify_sources)
