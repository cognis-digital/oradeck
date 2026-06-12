# Demo 01 — Mirror an image (with its SBOM) into a portable store

oradeck pulls an OCI image **and its referrers** (signatures, SBOMs,
attestations) into a content-addressable local store you can carry across an
air-gap, then pushes it back up into a disconnected registry.

This demo uses the built-in **offline fixture** image — no network, no Docker.

## Run it

```bash
# Copy the demo image + its SBOM attestation into a local OCI store.
python -m oradeck copy x --demo --store /tmp/oci-store

# See what landed: artifacts, blobs, total size.
python -m oradeck inspect --store /tmp/oci-store

# Plan a real many-image mirror (source -> destination registry).
python -m oradeck plan nginx:1.27-alpine redis:7 ghcr.io/cognis/app:1.0.0 \
    --to localhost:5000

# Parse any reference into its parts.
python -m oradeck parse ghcr.io/cognis/app@sha256:0000...0000
```

For a real registry, drop `--demo` and give a live reference:

```bash
python -m oradeck copy ghcr.io/cognis/app:1.0.0 --store ./oci-store
# ...carry ./oci-store across the gap...
python -m oradeck push localhost:5000/cognis/app:1.0.0 --store ./oci-store --insecure
```

## What makes it useful

- **Referrers travel too.** Detached signatures and SBOM/attestation
  artifacts are discovered (Referrers API, with a digest-tag fallback) and
  copied alongside the image — so your supply-chain metadata survives the gap.
- **Plain OCI Distribution Spec over the standard library.** No Docker daemon,
  no external client, no pip dependencies.
- **Content-addressable store.** Blobs are deduplicated by digest; the store is
  a valid OCI image layout.
