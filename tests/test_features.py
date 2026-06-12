"""Feature tests for oradeck — verify, gc, referrers, CLI, MCP."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oradeck import (
    RegistryClient, build_demo_fixture, copy_to_store, gc_store, inspect_store,
    list_referrers, verify_store,
)
from oradeck.core import OradeckError, _blob_path, digest_of, store_blob
from oradeck.cli import main
from oradeck import mcp_server


def _populated_store(tmp):
    fixture, repo, tag = build_demo_fixture()
    client = RegistryClient("demo.local", fixture=fixture)
    copy_to_store(f"demo.local/{repo}:{tag}", tmp, client=client)
    return tmp


class TestVerifyStore(unittest.TestCase):
    def test_clean_store_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _populated_store(tmp)
            res = verify_store(tmp)
            self.assertTrue(res["ok"], res["problems"])
            self.assertGreater(res["blobs_checked"], 0)
            self.assertGreater(res["reachable"], 0)

    def test_corrupt_blob_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _populated_store(tmp)
            # Corrupt one blob's bytes (filename stays = its claimed digest).
            blobs = os.path.join(tmp, "blobs", "sha256")
            fn = sorted(os.listdir(blobs))[0]
            with open(os.path.join(blobs, fn), "ab") as fh:
                fh.write(b"tampered")
            res = verify_store(tmp)
            self.assertFalse(res["ok"])
            self.assertTrue(any("mismatch" in p for p in res["problems"]))

    def test_missing_store_raises(self):
        with self.assertRaises(OradeckError):
            verify_store("/no/such/store")


class TestGc(unittest.TestCase):
    def test_orphan_detected_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _populated_store(tmp)
            orphan = store_blob(tmp, b"unreferenced-junk-blob")
            res = gc_store(tmp, dry_run=True)
            self.assertIn(orphan, res["orphans"])
            self.assertTrue(res["dry_run"])
            self.assertEqual(res["removed"], 0)
            # dry-run leaves the file in place
            self.assertTrue(os.path.isfile(_blob_path(tmp, orphan)))

    def test_apply_removes_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            _populated_store(tmp)
            orphan = store_blob(tmp, b"junk")
            res = gc_store(tmp, dry_run=False)
            self.assertEqual(res["removed"], len(res["orphans"]))
            self.assertFalse(os.path.isfile(_blob_path(tmp, orphan)))
            # the real artifacts survive GC
            self.assertTrue(verify_store(tmp)["ok"])

    def test_clean_store_no_orphans(self):
        with tempfile.TemporaryDirectory() as tmp:
            _populated_store(tmp)
            self.assertEqual(gc_store(tmp)["orphans"], [])


class TestReferrers(unittest.TestCase):
    def test_list_referrers_finds_sbom(self):
        with tempfile.TemporaryDirectory() as tmp:
            _populated_store(tmp)
            info = inspect_store(tmp)
            subject = info["artifacts"][0]["digest"]
            refs = list_referrers(tmp, subject)
            self.assertTrue(refs)
            self.assertTrue(any(r.get("artifactType") == "application/spdx+json"
                                for r in refs))


class TestCliFeatures(unittest.TestCase):
    def test_verify_and_gc_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "s")
            self.assertEqual(main(["copy", "x", "--demo", "--store", store]), 0)
            self.assertEqual(main(["verify", "--store", store]), 0)
            self.assertEqual(main(["gc", "--store", store]), 0)

    def test_verify_fails_on_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "s")
            main(["copy", "x", "--demo", "--store", store])
            blobs = os.path.join(store, "blobs", "sha256")
            fn = sorted(os.listdir(blobs))[0]
            with open(os.path.join(blobs, fn), "ab") as fh:
                fh.write(b"x")
            self.assertEqual(main(["verify", "--store", store]), 1)


class TestMcpFeatures(unittest.TestCase):
    def test_verify_and_gc_tools_present(self):
        tl = mcp_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in tl["result"]["tools"]}
        self.assertTrue({"verify", "gc"}.issubset(names))

    def test_verify_via_mcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            _populated_store(tmp)
            r = mcp_server.handle_request({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "verify", "arguments": {"store": tmp}}})
            self.assertFalse(r["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
