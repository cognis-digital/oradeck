# oradeck — Usage Guide

oradeck moves OCI artifacts (images + their referrers) between registries and a
portable, content-addressable store, and keeps that store healthy.

## The store

oradeck's store is a standard **OCI image layout**: blobs under
`blobs/sha256/<hex>`, an `index.json`, and an `oci-layout` marker. Blobs are
content-addressed, so identical layers across images are stored once.

## Commands

### copy — registry -> store
```bash
python -m oradeck copy ghcr.io/cognis/app:1.0.0 --store ./oci-store
# offline demo (no network, no Docker):
python -m oradeck copy x --demo --store ./oci-store
```
Referrers (detached signatures, SBOMs, attestations) are discovered via the
Referrers API (with a digest-tag fallback) and copied alongside the image.
Use `--no-referrers` to skip them.

### push — store -> registry
```bash
python -m oradeck push localhost:5000/cognis/app:1.0.0 --store ./oci-store --insecure
```

### inspect
```bash
python -m oradeck inspect --store ./oci-store
```

### verify — store integrity
```bash
python -m oradeck verify --store ./oci-store
```
Recomputes every blob's sha256 against its filename **and** confirms every
digest referenced by an indexed manifest is present. Exits non-zero on any
mismatch or missing blob — run it after carrying a store across an air-gap.

### gc — reclaim space
```bash
python -m oradeck gc --store ./oci-store          # dry-run: report orphans
python -m oradeck gc --store ./oci-store --apply  # delete unreachable blobs
```
"Reachable" = anything walked from the index manifests (config, layers, child
manifests in an index, and `subject` links). Everything else is an orphan.

### referrers
```bash
python -m oradeck referrers sha256:<subject-digest> --store ./oci-store
```
Lists stored manifests whose `subject` points at a given image digest (its
signatures/SBOMs/attestations).

### plan / parse
```bash
python -m oradeck plan nginx:1.27 redis:7 --to localhost:5000
python -m oradeck parse ghcr.io/cognis/app@sha256:...
```

## MCP server

```bash
python -m oradeck mcp   # copy / inspect / plan / verify / gc over stdio JSON-RPC
```

## Air-gap workflow

```bash
# Connected side:
python -m oradeck copy ghcr.io/cognis/app:1.0.0 --store ./carry
python -m oradeck gc   --store ./carry --apply     # trim
python -m oradeck verify --store ./carry           # sanity
# ...carry ./carry across the gap...
# Disconnected side:
python -m oradeck verify --store ./carry           # confirm integrity
python -m oradeck push localhost:5000/cognis/app:1.0.0 --store ./carry --insecure
```
