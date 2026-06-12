"""Smoke tests for oradeck. Standard library only, no network."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oradeck import TOOL_NAME, TOOL_VERSION, parse_ref
from oradeck.cli import main

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestMetadata(unittest.TestCase):
    def test_metadata(self):
        self.assertEqual(TOOL_NAME, "oradeck")
        self.assertTrue(TOOL_VERSION)


class TestRefParsing(unittest.TestCase):
    def test_host_repo_tag(self):
        r = parse_ref("ghcr.io/cognis/app:1.2.3")
        self.assertEqual(r.registry, "ghcr.io")
        self.assertEqual(r.repository, "cognis/app")
        self.assertEqual(r.tag, "1.2.3")

    def test_dockerhub_default(self):
        r = parse_ref("nginx:1.27")
        self.assertEqual(r.registry, "registry-1.docker.io")
        self.assertEqual(r.repository, "nginx")
        self.assertEqual(r.tag, "1.27")

    def test_digest_pin(self):
        d = "sha256:" + "a" * 64
        r = parse_ref(f"localhost:5000/x@{d}")
        self.assertEqual(r.registry, "localhost:5000")
        self.assertEqual(r.digest, d)

    def test_default_latest(self):
        self.assertEqual(parse_ref("repo/name").tag, "latest")


class TestCli(unittest.TestCase):
    def test_demo_copy_inspect(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "store")
            self.assertEqual(main(["copy", "x", "--demo", "--store", store]), 0)
            self.assertEqual(main(["inspect", "--store", store]), 0)

    def test_plan_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "oradeck", "plan", "nginx:1.27",
             "redis:7", "--to", "reg:5000", "--format", "json"],
            cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data["plan"]), 2)
        self.assertTrue(data["plan"][0]["destination"].startswith("reg:5000/"))

    def test_no_command_exits_2(self):
        self.assertEqual(main([]), 2)

    def test_inspect_missing_store_exits_2(self):
        self.assertEqual(main(["inspect", "--store", "/no/such/store"]), 2)


if __name__ == "__main__":
    unittest.main()
