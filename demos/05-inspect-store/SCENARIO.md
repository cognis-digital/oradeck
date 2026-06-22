# Demo 05 — Inspect a portable store before you cross the gap

## Where the data came from

After `copy`, you hold a content-addressable OCI-layout store on removable
media. Before you walk it to the disconnected side you want a manifest: which
artifacts, how many blobs, total bytes — so you can confirm the media has
everything and size your transfer.

This demo builds a real store with zero network using the built-in fixture
image (an image + a one-layer config + an SBOM attestation referrer), then
inspects it.

## What to expect

`inspect` lists each indexed artifact (manifest digest + its source ref
annotation) and prints `N artifact(s), M blob(s), <size>`. The fixture yields
1 artifact and several blobs (config, layer, manifest, SBOM, empty config).
`--format json` gives the same data for tooling; `--out` writes it to a file.

## Run it

```bash
# Build a real store offline, then inspect it.
python -m oradeck copy x --demo --store /tmp/oradeck-store
python -m oradeck inspect --store /tmp/oradeck-store

# JSON manifest written to a file (e.g. to ship alongside the media).
python -m oradeck inspect --store /tmp/oradeck-store --format json --out store-manifest.json
```

## How to act

Compare `artifact_count` / `blob_count` against your mirror-set size. A short
count means a `copy` failed mid-pull — re-run it before you disconnect, not
after.
