# oradeck

**OCI registry mirror & artifact copy for air-gapped clusters.** Pull container
images **and their referrers** — signatures, SBOMs, attestations — into a
portable content-addressable store, carry it across the gap, and push it back
into a disconnected registry.

Part of the **Cognis Neural Suite**. Pure Python standard library — no Docker
daemon, no external registry client, no pip dependencies.

---

## Why

Air-gapped and classified environments can't reach Docker Hub or GHCR at deploy
time. oradeck speaks the **OCI Distribution Spec** directly, so you can mirror
exactly the artifacts you need — *with their supply-chain metadata intact* —
onto removable media and seed a private registry on the far side.

## Commands

```bash
# Copy an image (and its sigs/SBOMs/attestations) into a local OCI store.
python -m oradeck copy ghcr.io/cognis/app:1.0.0 --store ./oci-store

# List artifacts + blob stats in a store.
python -m oradeck inspect --store ./oci-store

# Push a stored artifact into a destination registry.
python -m oradeck push localhost:5000/cognis/app:1.0.0 --store ./oci-store --insecure

# Plan a many-image mirror (source -> destination).
python -m oradeck plan nginx:1.27 redis:7 --to localhost:5000

# Plan from a declarative mirror-set FILE (plain list or JSON) kept in git.
python -m oradeck plan --from mirror-set.txt --format json

# Parse any reference (handles host:port, tags, @sha256 digests).
python -m oradeck parse ghcr.io/cognis/app:1.0.0

# Try it with zero network using the built-in fixture image.
python -m oradeck copy x --demo --store /tmp/oci-store

# Run as a local MCP server (stdio JSON-RPC).
python -m oradeck mcp
```

## What sets oradeck apart

- **Referrers-aware.** Discovers and copies detached signatures and
  SBOM/attestation referrers (Referrers API + digest-tag fallback) so your
  supply-chain evidence crosses the air-gap with the image.
- **OCI layout store.** Blobs are content-addressed and deduplicated; the store
  is a standard OCI image layout other tools can read.
- **Bearer + basic auth** flows handled (Docker-style `WWW-Authenticate`).
- **MCP-native** (`copy` / `inspect` / `plan`) and an opt-in local-fleet AI hook
  (default OFF) that suggests a mirror image-set from a plain-English stack.
- **Pairs with [airlock](https://github.com/cognis-digital/airlock).** oradeck
  moves the registry artifacts; airlock bundles the whole declarative app.

## Mirror-set files (declarative, version-controlled)

`plan --from FILE` reads the exact image set to carry across the gap from a
**mirror-set file** — the air-gap analogue of a lockfile, kept in git next to
the app it serves. Two shapes, auto-detected by content:

```text
# mirror-set.txt — one ref per line; `#` comments and blank lines ignored
registry: factory-registry.local:5000      # sets the destination
nginx:1.27-alpine
ghcr.io/cognis/inference-app:2.3.1
```

```json
{ "registry": "registry.internal:5000",
  "images": ["prom/prometheus:v2.54.1", "grafana/grafana:11.2.0"] }
```

A `--to` on the command line overrides the in-file `registry`. The same
`from_file` argument is exposed on the MCP `plan` tool.

## Demos

Runnable, zero-network walkthroughs under [`demos/`](demos/) — each has a
realistic input file in the tool's real format and a `SCENARIO.md` with the
exact run command and what to expect:

| Demo | Shows |
| --- | --- |
| [01-basic](demos/01-basic) | Mirror the offline fixture image + its SBOM into a store |
| [02-mirror-set-edge-stack](demos/02-mirror-set-edge-stack) | `plan --from` a plain mirror-set with an in-file `registry:` |
| [03-mirror-set-json-observability](demos/03-mirror-set-json-observability) | JSON mirror-set + a `--to` CI override |
| [04-reference-shapes](demos/04-reference-shapes) | `parse` every real reference shape (ports, tags, `@sha256` pins) |
| [05-inspect-store](demos/05-inspect-store) | Inventory a store before transport |
| [06-verify-integrity](demos/06-verify-integrity) | Detect transport corruption with `verify` (exit-code gate) |
| [07-gc-orphans](demos/07-gc-orphans) | Garbage-collect orphan blobs to shrink the media |
| [08-referrers-supply-chain](demos/08-referrers-supply-chain) | Confirm SBOM/signature referrers crossed the gap |
| [09-offline-copy-walkthrough](demos/09-offline-copy-walkthrough) | The full copy -> inspect -> verify -> push loop |
| [10-mcp-agent](demos/10-mcp-agent) | Drive `plan` over the MCP stdio JSON-RPC server |

## Tests

```bash
python -m pytest -q     # or: python -m unittest discover -s tests
```

## Interoperability

`oradeck` composes with the 300+ tool Cognis suite — JSON in/out and a shared
OpenAI-compatible `/v1` backbone. See **[INTEROP.md](INTEROP.md)** for the
suite map, composition patterns, and reference stacks.

## Integrations

Forward `oradeck`'s findings to STIX/MISP/Sigma/Splunk/Elastic/Slack/webhooks via
[`cognis-connect`](https://github.com/cognis-digital/cognis-connect). See **[INTEGRATIONS.md](INTEGRATIONS.md)**.

## License

Cognis Open Collaboration License (COCL) 1.0 — see [`LICENSE`](LICENSE).
© 2026 Cognis Digital LLC. Original Cognis work implementing the open OCI
Distribution Spec; no third-party code, names, or branding.

<!-- cognis:domains:start -->
## Domains

**Primary domain:** AI & ML  ·  **JTF MERIDIAN division:** ATHENA-PRIME · SAGE

**Topics:** `cognis` `ai` `llm` `machine-learning` `sbom`

Part of the **Cognis Neural Suite** — 300+ source-available tools organized across 12 domains under the JTF MERIDIAN command structure. See the [suite on GitHub](https://github.com/cognis-digital) and [jtf-meridian](https://github.com/cognis-digital/jtf-meridian) for how the pieces fit together.
<!-- cognis:domains:end -->

## Usage — step by step

`oradeck` mirrors OCI images **and their referrers** (signatures, SBOMs, attestations) into a portable store you can carry across an air-gap.

1. **Install** (pure stdlib, Python 3.10+):
   ```bash
   pip install "git+https://github.com/cognis-digital/oradeck.git"
   ```
2. **Copy an image + referrers** into a local content-addressable store (try `--demo` first for a zero-network fixture):
   ```bash
   oradeck copy ghcr.io/cognis/app:1.0.0 --store ./oci-store
   oradeck copy x --demo --store /tmp/oci-store
   ```
3. **Inspect and verify** the store before you move it:
   ```bash
   oradeck inspect --store ./oci-store
   oradeck verify  --store ./oci-store
   ```
4. **Push it** into the disconnected destination registry on the far side:
   ```bash
   oradeck push localhost:5000/cognis/app:1.0.0 --store ./oci-store --insecure
   ```
5. **Automate a bulk mirror** — plan many images (or a version-controlled mirror-set file; `--format json` for tooling) and garbage-collect orphan blobs:
   ```bash
   oradeck plan nginx:1.27 redis:7 --to localhost:5000 --format json
   oradeck plan --from mirror-set.txt --format json --out plan.json
   oradeck gc --store ./oci-store --apply
   ```
   Or run it as a local MCP server (stdio JSON-RPC): `oradeck mcp`.
