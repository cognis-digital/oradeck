"""Command-line interface for oradeck."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from oradeck import TOOL_NAME, TOOL_VERSION
from oradeck.core import (
    OradeckError,
    RegistryClient,
    build_demo_fixture,
    copy_to_store,
    inspect_store,
    parse_ref,
    plan_mirror,
    push_from_store,
)


def _human(n: int) -> str:
    f = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or u == "TB":
            return f"{f:.0f}{u}" if u == "B" else f"{f:.1f}{u}"
        f /= 1024
    return f"{f:.1f}TB"


def _emit(text: str, out: Optional[str]) -> None:
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(text)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="OCI registry mirror & artifact copy — move images and "
                    "their signatures/SBOMs/attestations across an air-gap.")
    p.add_argument("--version", action="version",
                   version=f"{TOOL_NAME} {TOOL_VERSION}")
    sub = p.add_subparsers(dest="command")

    c = sub.add_parser("copy", help="Copy an image (+referrers) into a local store.")
    c.add_argument("ref", help="Source image reference (host/repo:tag).")
    c.add_argument("--store", default="oci-store", help="Local store dir.")
    c.add_argument("--insecure", action="store_true", help="Use http (plain).")
    c.add_argument("--no-referrers", action="store_true",
                   help="Skip signatures/SBOM/attestation referrers.")
    c.add_argument("--demo", action="store_true",
                   help="Use the built-in offline fixture image.")
    c.add_argument("--format", choices=("table", "json"), default="table")

    pu = sub.add_parser("push", help="Push a stored artifact to a destination registry.")
    pu.add_argument("dest", help="Destination reference (host/repo:tag).")
    pu.add_argument("--store", default="oci-store", help="Local store dir.")
    pu.add_argument("--insecure", action="store_true", help="Use http (plain).")
    pu.add_argument("--format", choices=("table", "json"), default="table")

    ins = sub.add_parser("inspect", help="List artifacts and blobs in a store.")
    ins.add_argument("--store", default="oci-store", help="Local store dir.")
    ins.add_argument("--format", choices=("table", "json"), default="table")
    ins.add_argument("--out", help="Write report to a file.")

    m = sub.add_parser("plan", help="Plan a many-image mirror (source -> dest).")
    m.add_argument("images", nargs="+", help="Source image references.")
    m.add_argument("--to", required=True, dest="dest_registry",
                   help="Destination registry host[:port].")
    m.add_argument("--format", choices=("table", "json"), default="table")

    pr = sub.add_parser("parse", help="Parse a reference into its parts.")
    pr.add_argument("ref")

    vf = sub.add_parser("verify", help="Verify store integrity (blob hashes + reachable blobs).")
    vf.add_argument("--store", default="oci-store")
    vf.add_argument("--format", choices=("table", "json"), default="table")

    gc = sub.add_parser("gc", help="Garbage-collect blobs unreachable from the index.")
    gc.add_argument("--store", default="oci-store")
    gc.add_argument("--apply", action="store_true",
                    help="Actually delete orphans (default: dry-run).")
    gc.add_argument("--format", choices=("table", "json"), default="table")

    rf = sub.add_parser("referrers", help="List stored manifests that reference a subject.")
    rf.add_argument("subject", help="Subject manifest digest (sha256:...).")
    rf.add_argument("--store", default="oci-store")

    sub.add_parser("mcp", help="Run as an MCP server (stdio JSON-RPC).")
    return p


def _run_copy(a) -> int:
    try:
        if a.demo:
            fixture, repo, tag = build_demo_fixture()
            client = RegistryClient("demo.local", fixture=fixture)
            rep = copy_to_store(f"demo.local/{repo}:{tag}", a.store,
                                client=client, with_referrers=not a.no_referrers)
        else:
            rep = copy_to_store(a.ref, a.store, insecure=a.insecure,
                                with_referrers=not a.no_referrers)
    except (OSError, OradeckError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if a.format == "json":
        _emit(json.dumps(rep, indent=2), None)
    else:
        print(f"oradeck copy — {rep['source']}")
        print("=" * 60)
        print(f"  manifest : {rep['manifest_digest'][:24]}…")
        print(f"  media    : {rep['media_type']}")
        print(f"  blobs    : {rep['blobs_copied']}")
        print(f"  manifests: {rep['manifests_copied']}")
        print(f"  referrers: {rep['referrers_copied']}  (sigs/SBOM/attestations)")
        print(f"  store    : {rep['store']}")
    return 0


def _run_push(a) -> int:
    try:
        rep = push_from_store(a.store, a.dest, insecure=a.insecure)
    except (OSError, OradeckError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if a.format == "json":
        _emit(json.dumps(rep, indent=2), None)
    else:
        print(f"oradeck push — {rep['destination']}")
        print(f"  manifest: {rep['manifest_digest'][:24]}…  blobs pushed: {rep['blobs_pushed']}")
    return 0


def _run_inspect(a) -> int:
    try:
        info = inspect_store(a.store)
    except (OSError, OradeckError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if a.format == "json":
        _emit(json.dumps(info, indent=2), a.out)
    else:
        lines = [f"oradeck store — {info['store']}", "=" * 60]
        for m in info["artifacts"]:
            ann = m.get("annotations", {})
            lines.append(f"  {m['digest'][:24]}…  {m.get('mediaType','')}")
            lines.append(f"      {ann.get('io.cognis.oradeck.source','')}")
        lines.append("-" * 60)
        lines.append(f"{info['artifact_count']} artifact(s), {info['blob_count']} "
                     f"blob(s), {_human(info['total_bytes'])}")
        _emit("\n".join(lines), a.out)
    return 0


def _run_plan(a) -> int:
    plan = plan_mirror(a.images, a.dest_registry)
    if a.format == "json":
        _emit(json.dumps({"plan": plan}, indent=2), None)
    else:
        print(f"oradeck mirror plan -> {a.dest_registry}")
        print("=" * 60)
        for step in plan:
            print(f"  {step['source']}")
            print(f"    -> {step['destination']}")
    return 0


def _run_parse(a) -> int:
    ref = parse_ref(a.ref)
    print(json.dumps({"registry": ref.registry, "repository": ref.repository,
                      "tag": ref.tag, "digest": ref.digest,
                      "canonical": str(ref)}, indent=2))
    return 0


def _run_verify(a) -> int:
    from oradeck import verify_store
    try:
        res = verify_store(a.store)
    except (OSError, OradeckError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if a.format == "json":
        _emit(json.dumps(res, indent=2), None)
    else:
        print(f"oradeck verify — {res['store']}")
        print("=" * 60)
        print(f"  blobs checked: {res['blobs_checked']}   reachable: {res['reachable']}")
        for p in res["problems"]:
            print(f"  ! {p}")
        print("RESULT: " + ("PASS" if res["ok"] else "FAIL"))
    return 0 if res["ok"] else 1


def _run_gc(a) -> int:
    from oradeck import gc_store
    try:
        res = gc_store(a.store, dry_run=not a.apply)
    except (OSError, OradeckError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if a.format == "json":
        _emit(json.dumps(res, indent=2), None)
    else:
        mode = "REMOVED" if not res["dry_run"] else "DRY RUN — would remove"
        print(f"oradeck gc — {mode} {len(res['orphans'])} orphan(s), "
              f"{_human(res['freed_bytes'])}")
        for o in res["orphans"]:
            print(f"  {o[:24]}…")
    return 0


def _run_referrers(a) -> int:
    from oradeck import list_referrers
    try:
        refs = list_referrers(a.store, a.subject)
    except (OSError, OradeckError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"oradeck referrers of {a.subject[:24]}… — {len(refs)} found")
    for r in refs:
        print(f"  {r['digest'][:24]}…  {r.get('artifactType') or r.get('mediaType')}")
    return 0


def _run_mcp() -> int:
    from oradeck.mcp_server import run_mcp_server
    run_mcp_server()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "copy":
        return _run_copy(args)
    if args.command == "push":
        return _run_push(args)
    if args.command == "inspect":
        return _run_inspect(args)
    if args.command == "plan":
        return _run_plan(args)
    if args.command == "parse":
        return _run_parse(args)
    if args.command == "verify":
        return _run_verify(args)
    if args.command == "gc":
        return _run_gc(args)
    if args.command == "referrers":
        return _run_referrers(args)
    if args.command == "mcp":
        return _run_mcp()
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
