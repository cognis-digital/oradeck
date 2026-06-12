"""Deep tests for oradeck — fixture pull, referrers, store round-trip, MCP."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oradeck import (
    RegistryClient,
    build_demo_fixture,
    copy_to_store,
    digest_of,
    inspect_store,
    push_from_store,
    suggest_mirror_set,
)
from oradeck.core import (
    OradeckError,
    load_store_index,
    read_blob,
    parse_ref,
)
from oradeck import mcp_server


def _demo_client():
    fixture, repo, tag = build_demo_fixture()
    return RegistryClient("demo.local", fixture=fixture), repo, tag


class TestFixtureCopy(unittest.TestCase):
    def test_copy_pulls_config_layer_and_referrer(self):
        client, repo, tag = _demo_client()
        with tempfile.TemporaryDirectory() as tmp:
            rep = copy_to_store(f"demo.local/{repo}:{tag}", tmp, client=client)
            self.assertEqual(rep["blobs_copied"], 2)  # config + 1 layer
            self.assertEqual(rep["referrers_copied"], 1)  # the SBOM attestation
            idx = load_store_index(tmp)
            self.assertEqual(len(idx["manifests"]), 1)
            # manifest blob is retrievable by its digest
            data = read_blob(tmp, rep["manifest_digest"])
            self.assertEqual(digest_of(data), rep["manifest_digest"])

    def test_copy_no_referrers(self):
        client, repo, tag = _demo_client()
        with tempfile.TemporaryDirectory() as tmp:
            rep = copy_to_store(f"demo.local/{repo}:{tag}", tmp, client=client,
                                with_referrers=False)
            self.assertEqual(rep["referrers_copied"], 0)


class TestStoreInspect(unittest.TestCase):
    def test_inspect_counts(self):
        client, repo, tag = _demo_client()
        with tempfile.TemporaryDirectory() as tmp:
            copy_to_store(f"demo.local/{repo}:{tag}", tmp, client=client)
            info = inspect_store(tmp)
            self.assertEqual(info["artifact_count"], 1)
            self.assertGreaterEqual(info["blob_count"], 4)
            self.assertGreater(info["total_bytes"], 0)

    def test_inspect_missing_raises(self):
        with self.assertRaises(OradeckError):
            inspect_store("/no/such/store")


class TestRoundTrip(unittest.TestCase):
    def test_copy_then_push_to_capture_registry(self):
        client, repo, tag = _demo_client()
        with tempfile.TemporaryDirectory() as tmp:
            copy_to_store(f"demo.local/{repo}:{tag}", tmp, client=client)

            # Capture-everything destination client (records PUTs as a tiny reg).
            uploaded = {}

            class CaptureClient(RegistryClient):
                def put_blob(self, repository, digest, data):
                    uploaded[digest] = data

                def put_manifest(self, repository, reference, data, media_type):
                    uploaded[reference] = data
                    return digest_of(data)

            dest_client = CaptureClient("dest.local")
            rep = push_from_store(tmp, "dest.local/mirror/app:1.0.0",
                                  client=dest_client)
            self.assertEqual(rep["blobs_pushed"], 2)
            # The tag and the manifest digest were both PUT.
            self.assertIn("1.0.0", uploaded)


class TestReferrersFallback(unittest.TestCase):
    def test_fallback_tag_scheme(self):
        # Build a fixture with NO referrers API (404) but a digest-tag manifest.
        fixture, repo, tag = build_demo_fixture()
        man = fixture[f"/v2/{repo}/manifests/{tag}"]
        man_dig = digest_of(man)
        # Remove the referrers API entry to force the fallback path.
        del fixture[f"/v2/{repo}/referrers/{man_dig}"]
        algo, hexd = man_dig.split(":", 1)
        # Point the fallback tag at the existing referrer manifest.
        ref_manifest = None
        for k, v in fixture.items():
            if k.startswith(f"/v2/{repo}/manifests/sha256:") and v != man:
                ref_manifest = v
        if ref_manifest is not None:
            fixture[f"/v2/{repo}/manifests/{algo}-{hexd}"] = ref_manifest
        client = RegistryClient("demo.local", fixture=fixture)
        refs = client.get_referrers(repo, man_dig)
        self.assertTrue(refs)  # found via fallback tag


class TestMcp(unittest.TestCase):
    def test_initialize_and_list(self):
        init = mcp_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(init["result"]["serverInfo"]["name"], "oradeck")
        tl = mcp_server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in tl["result"]["tools"]}
        self.assertTrue({"copy", "inspect", "plan"}.issubset(names))

    def test_plan_call(self):
        r = mcp_server.handle_request({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "plan",
                       "arguments": {"images": ["nginx:1.27"],
                                     "dest_registry": "reg:5000"}}})
        self.assertFalse(r["result"]["isError"])
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(len(payload["plan"]), 1)

    def test_unknown_method(self):
        r = mcp_server.handle_request({"jsonrpc": "2.0", "id": 9, "method": "nope"})
        self.assertIn("error", r)


class TestAiHook(unittest.TestCase):
    def test_off_by_default(self):
        for v in ("COGNIS_AI_BACKEND", "COGNIS_AI_ENDPOINT"):
            os.environ.pop(v, None)
        out = suggest_mirror_set("a redis + nginx web stack")
        self.assertEqual(out["images"], [])
        self.assertTrue(out["_ai"].startswith("disabled"))


if __name__ == "__main__":
    unittest.main()
