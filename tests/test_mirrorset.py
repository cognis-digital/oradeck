"""Tests for the declarative mirror-set feature (`plan --from FILE`)."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oradeck import load_mirror_set
from oradeck.core import OradeckError
from oradeck.cli import main
from oradeck import mcp_server


def _write(tmp, name, text):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


PLAIN = """\
# air-gap mirror-set for the edge inference stack
registry: localhost:5000

nginx:1.27-alpine          # ingress
redis:7.4                   # cache
ghcr.io/cognis/app:1.0.0    # the app itself
"""

JSON_SET = json.dumps({
    "registry": "registry.internal:5000",
    "images": ["postgres:16.4", "grafana/grafana:11.2.0", "prom/prometheus:v2.54.1"],
})


class TestLoadMirrorSet(unittest.TestCase):
    def test_plain_list_with_comments_and_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "mirror-set.txt", PLAIN)
            images, dest = load_mirror_set(p)
            self.assertEqual(dest, "localhost:5000")
            self.assertEqual(images,
                             ["nginx:1.27-alpine", "redis:7.4",
                              "ghcr.io/cognis/app:1.0.0"])

    def test_json_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "mirror-set.json", JSON_SET)
            images, dest = load_mirror_set(p)
            self.assertEqual(dest, "registry.internal:5000")
            self.assertEqual(len(images), 3)
            self.assertIn("postgres:16.4", images)

    def test_json_dest_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "m.json",
                       json.dumps({"dest": "r:5000", "images": ["a:1"]}))
            _images, dest = load_mirror_set(p)
            self.assertEqual(dest, "r:5000")

    def test_plain_no_registry_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "m.txt", "nginx:1.27\nredis:7\n")
            images, dest = load_mirror_set(p)
            self.assertIsNone(dest)
            self.assertEqual(images, ["nginx:1.27", "redis:7"])

    def test_missing_file_raises(self):
        with self.assertRaises(OradeckError):
            load_mirror_set("/no/such/mirror-set.txt")

    def test_empty_set_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "m.txt", "# only comments\n\n")
            with self.assertRaises(OradeckError):
                load_mirror_set(p)

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "m.json", "{ not valid json ")
            with self.assertRaises(OradeckError):
                load_mirror_set(p)


class TestPlanFromCli(unittest.TestCase):
    def test_plan_from_file_uses_in_file_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "mirror-set.txt", PLAIN)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["plan", "--from", p, "--format", "json"])
            self.assertEqual(rc, 0)
            doc = json.loads(buf.getvalue())
            self.assertEqual(doc["destination_registry"], "localhost:5000")
            self.assertEqual(doc["count"], 3)
            self.assertTrue(doc["plan"][0]["destination"].startswith("localhost:5000/"))

    def test_explicit_to_overrides_in_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "mirror-set.txt", PLAIN)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["plan", "--from", p, "--to", "other:5000",
                           "--format", "json"])
            self.assertEqual(rc, 0)
            doc = json.loads(buf.getvalue())
            self.assertEqual(doc["destination_registry"], "other:5000")

    def test_cli_and_file_images_combine(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "m.txt", "registry: r:5000\nnginx:1.27\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["plan", "busybox:1.36", "--from", p, "--format", "json"])
            self.assertEqual(rc, 0)
            doc = json.loads(buf.getvalue())
            self.assertEqual(doc["count"], 2)

    def test_plan_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "m.json", JSON_SET)
            out = os.path.join(tmp, "plan.json")
            rc = main(["plan", "--from", p, "--format", "json", "--out", out])
            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as fh:
                doc = json.load(fh)
            self.assertEqual(doc["count"], 3)

    def test_no_destination_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "m.txt", "nginx:1.27\n")  # no registry, no --to
            rc = main(["plan", "--from", p])
            self.assertEqual(rc, 2)

    def test_no_images_errors(self):
        rc = main(["plan", "--to", "r:5000"])
        self.assertEqual(rc, 2)


class TestPlanFromMcp(unittest.TestCase):
    def test_plan_from_file_via_mcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "m.json", JSON_SET)
            r = mcp_server.handle_request({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "plan", "arguments": {"from_file": p}}})
            self.assertFalse(r["result"]["isError"])
            payload = json.loads(r["result"]["content"][0]["text"])
            self.assertEqual(payload["destination_registry"], "registry.internal:5000")
            self.assertEqual(payload["count"], 3)

    def test_plan_inline_still_works_via_mcp(self):
        r = mcp_server.handle_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "plan",
                       "arguments": {"images": ["nginx:1.27"],
                                     "dest_registry": "r:5000"}}})
        self.assertFalse(r["result"]["isError"])
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(payload["count"], 1)

    def test_plan_no_args_is_error_via_mcp(self):
        r = mcp_server.handle_request({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "plan", "arguments": {}}})
        self.assertIn("error", r)


if __name__ == "__main__":
    unittest.main()
