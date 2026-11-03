"""End-to-end synthetic paired execution, service receipts and no-client replay."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
import numpy as np
from PIL import Image

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), str(BASE / "src"), str(BASE / "round7/src")]
import opt_provider as original
import runtime_m
import run_m
from opt_provider import CHAT_MODEL, EMBED_MODEL, sha
from opt_pipeline import Retriever
from shared_accounting import SharedAccountingPipeline, IDENTITY_CONFIG, QUANTITY_CONFIG


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "mae_v2"; self.root.mkdir()
        self.round = self.root / "round7"; self.round.mkdir()
        self.rows, self.calls = [], []
        self.catalog = {"foods": {"11111111": {"description": "cooked rice", "category": "Rice",
            "density": {"energy": 100, "fat": 1, "carbs": 20, "protein": 4}}}}
        self.retriever = Retriever(["11111111"], np.asarray([[1.] + [0.] * 3071]), self.catalog)
        for ds, color in [("asa24", "red"), ("nutrition5k", "blue")]:
            image = self.root / f"data/{ds}/dev/images/a.png"; image.parent.mkdir(parents=True)
            Image.new("RGB", (16, 16), color).save(image)
            self.rows.append({"sample_id": ds, "dataset": ds, "group_id": ds, "fold": 0, "split": "dev",
                "image_path": str(image.relative_to(self.root)), "image_sha256": sha(image)})
        self.layout = {"coverage_complete": True, "parents": [{"parent_id": "p1", "description": "rice",
            "bbox": [0, 0, 1, 1], "region_ids": ["r1"], "accounting": "composite", "components": [
                {"component_id": "p1c1", "description": "cooked rice", "broad_query": "rice"}]}]}
        self.selection = {"items": [{"component_id": "p1c1", "primary_code": "11111111"}]}
        self.joint = {"parents": [{"parent_id": "p1", "route": "keep_children", "whole_code": None,
                                   "children": [{"component_id": "p1c1", "code": "11111111"}]}]}
        self.mass = {"total_grams": 100, "parents": [{"parent_id": "p1", "ratio": 1,
                                     "components": [{"component_id": "p1c1", "ratio": 1}]}]}
        outputs = iter([self.layout, self.selection, self.mass])
        pipe = SharedAccountingPipeline(lambda _: json.dumps(next(outputs)), lambda q: [[1.] + [0.] * 3071 for _ in q],
                                        self.catalog, self.retriever)
        image = self.root / self.rows[1]["image_path"]
        identity = pipe.identify(image, IDENTITY_CONFIG)
        portion = pipe.portion(image, identity, QUANTITY_CONFIG)
        self.ctx = SimpleNamespace(rows=self.rows, catalog=self.catalog, retriever=self.retriever,
            fallbacks={"vectors": {ds: {"0": {"weight": 80, "energy": 80, "fat": 1, "carbs": 16, "protein": 3}}
                       for ds in ["asa24", "nutrition5k"]}},
            embeddings={"entries": {}, "source_files": {}},
            imported={"records": {"nutrition5k": {"identity": identity, "portion": portion}}},
            binding={"synthetic": True}, verify_sources=lambda: True)
        patches = [patch.object(original, "ROOT", self.root), patch.object(runtime_m, "ROOT", self.root),
                   patch.object(run_m, "ROOT", self.root), patch.object(run_m, "ROUND", self.round),
                   patch.object(run_m, "verify_imported_c", lambda *args: True)]
        for p in patches: p.start(); self.addCleanup(p.stop)

    def transport(self, request):
        self.calls.append(request)
        data = json.loads(request.content)
        if data["model"] == EMBED_MODEL:
            return httpx.Response(200, json={"model": EMBED_MODEL, "data": [{"embedding": [1.] + [0.] * 3071}]})
        text = data["messages"][1]["content"][0]["text"]
        answer = (self.layout if text.startswith("Describe ALL") else self.selection if text.startswith("Select exactly")
                  else self.joint if text.startswith("Choose a nutrient-accounting") else self.mass)
        return httpx.Response(200, json={"model": CHAT_MODEL, "choices": [
            {"message": {"content": json.dumps(answer)}, "finish_reason": "stop"}]})

    def factory(self, imports, allow_paid=False):
        return self.provider_class(imports, root=self.root, allow_paid=allow_paid,
            keys=("chat-fixture-private", "embedding-fixture-private"),
            transport=httpx.MockTransport(self.transport), sleep=lambda _: None)

    def inventory(self):
        return {str(p.relative_to(self.round)): (sha(p), p.stat().st_mtime_ns)
                for p in self.round.rglob("*") if p.is_file()}

    def test_two_datasets_both_arms_complete_and_replay_is_readonly(self):
        self.provider_class = runtime_m.MProvider
        with patch.object(runtime_m, "MProvider", self.factory), redirect_stdout(StringIO()):
            first = run_m.run(self.ctx, allow_paid=True)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["pairs"], 2)
        self.assertTrue(first["provider_constructed"])
        # Both ASA quantity stages are invoked, but this synthetic keep route
        # has an identical payload, so one exact response is shared explicitly.
        self.assertEqual(first["service_counts"]["chat"]["successful_payloads"], 6)
        self.assertEqual(first["service_counts"]["embedding"]["successful_payloads"], 2)
        before, calls = self.inventory(), len(self.calls)
        with patch.object(runtime_m, "MProvider", side_effect=AssertionError("no Provider on replay")), \
             patch.object(original, "read_credentials", side_effect=AssertionError("no credentials on replay")), \
             redirect_stdout(StringIO()):
            second = run_m.run(self.ctx, allow_paid=False)
        self.assertTrue(second["completed_replay"])
        self.assertFalse(second["provider_constructed"])
        self.assertEqual(self.inventory(), before)
        self.assertEqual(len(self.calls), calls)

    def test_changed_image_does_not_reuse_scientific_stage(self):
        self.provider_class = runtime_m.MProvider
        with patch.object(runtime_m, "MProvider", self.factory), redirect_stdout(StringIO()):
            run_m.run(self.ctx, allow_paid=True)
        Image.new("RGB", (16, 16), "green").save(self.root / self.rows[0]["image_path"])
        with patch.object(runtime_m, "MProvider", side_effect=AssertionError("no fresh requests")), \
             redirect_stdout(StringIO()), self.assertRaises(ValueError):
            run_m.run(self.ctx, allow_paid=False)


if __name__ == "__main__": unittest.main()
