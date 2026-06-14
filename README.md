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
5. **Automate a bulk mirror** — plan many images (`--format json` for tooling) and garbage-collect orphan blobs:
   ```bash
   oradeck plan nginx:1.27 redis:7 --to localhost:5000 --format json
   oradeck gc --store ./oci-store --apply
   ```
   Or run it as a local MCP server (stdio JSON-RPC): `oradeck mcp`.
