"""oradeck MCP server — stdio JSON-RPC 2.0. Standard library only.

Wire into Cognis.Studio / Claude Desktop / Cursor:

    {"command": "python", "args": ["-m", "oradeck", "mcp"]}
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from oradeck import TOOL_NAME, TOOL_VERSION
from oradeck.core import (
    OradeckError,
    copy_to_store,
    gc_store,
    inspect_store,
    load_mirror_set,
    plan_mirror,
    verify_store,
)

PROTOCOL_VERSION = "2024-11-05"

_TOOLS = [
    {
        "name": "copy",
        "description": "Copy an OCI image and its referrers (signatures, SBOMs, "
                       "attestations) from a registry into a portable local store.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Source image reference."},
                "store": {"type": "string", "description": "Local store directory."},
                "with_referrers": {"type": "boolean"},
            },
            "required": ["ref"],
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect",
        "description": "List artifacts and blob stats in a local OCI store.",
        "inputSchema": {
            "type": "object",
            "properties": {"store": {"type": "string"}},
            "required": ["store"],
            "additionalProperties": False,
        },
    },
    {
        "name": "plan",
        "description": "Plan a many-image mirror: map each source ref to a "
                       "destination registry reference. Images can be given "
                       "inline or loaded from a declarative mirror-set file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "images": {"type": "array", "items": {"type": "string"}},
                "dest_registry": {"type": "string"},
                "from_file": {"type": "string",
                              "description": "Path to a mirror-set file "
                                             "(plain list or JSON)."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "verify",
        "description": "Verify store integrity: every blob's content matches "
                       "its digest and every referenced blob is present.",
        "inputSchema": {
            "type": "object",
            "properties": {"store": {"type": "string"}},
            "required": ["store"], "additionalProperties": False,
        },
    },
    {
        "name": "gc",
        "description": "Report (dry-run) or remove blobs not reachable from the "
                       "store index.",
        "inputSchema": {
            "type": "object",
            "properties": {"store": {"type": "string"}, "apply": {"type": "boolean"}},
            "required": ["store"], "additionalProperties": False,
        },
    },
]


def _result(req_id, result): return {"jsonrpc": "2.0", "id": req_id, "result": result}
def _error(req_id, code, msg): return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}


def _call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name == "copy":
        ref = args.get("ref")
        if not isinstance(ref, str) or not ref:
            raise ValueError("`ref` (string) is required")
        payload = copy_to_store(ref, args.get("store") or "oci-store",
                                with_referrers=args.get("with_referrers", True))
        is_error = False
    elif name == "inspect":
        store = args.get("store")
        if not isinstance(store, str) or not store:
            raise ValueError("`store` (string) is required")
        payload = inspect_store(store)
        is_error = False
    elif name == "plan":
        images = [str(x) for x in (args.get("images") or [])]
        dest = args.get("dest_registry")
        from_file = args.get("from_file")
        if from_file:
            file_images, file_dest = load_mirror_set(str(from_file))
            images = images + file_images
            dest = dest or file_dest
        if not images:
            raise ValueError("`images` (array) or `from_file` required")
        if not isinstance(dest, str) or not dest:
            raise ValueError("`dest_registry` or a `registry:` in from_file required")
        plan = plan_mirror(images, dest)
        payload = {"destination_registry": dest, "count": len(plan), "plan": plan}
        is_error = False
    elif name == "verify":
        store = args.get("store")
        if not isinstance(store, str) or not store:
            raise ValueError("`store` (string) is required")
        payload = verify_store(store)
        is_error = not payload["ok"]
    elif name == "gc":
        store = args.get("store")
        if not isinstance(store, str) or not store:
            raise ValueError("`store` (string) is required")
        payload = gc_store(store, dry_run=not bool(args.get("apply", False)))
        is_error = False
    else:
        raise ValueError(f"unknown tool: {name}")
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
            "isError": is_error}


def handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}
    is_notification = "id" not in req

    if method == "initialize":
        res = _result(req_id, {"protocolVersion": PROTOCOL_VERSION,
                               "capabilities": {"tools": {"listChanged": False}},
                               "serverInfo": {"name": TOOL_NAME, "version": TOOL_VERSION}})
        return None if is_notification else res
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return None if is_notification else _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": _TOOLS})
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            return _result(req_id, _call_tool(name, args))
        except (ValueError, OSError, OradeckError) as exc:
            return _error(req_id, -32602, str(exc))
        except Exception as exc:  # pragma: no cover
            return _error(req_id, -32603, f"internal error: {exc}")
    if is_notification:
        return None
    return _error(req_id, -32601, f"method not found: {method}")


def run_mcp_server(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            stdout.flush()
            continue
        response = handle_request(req)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    run_mcp_server()
