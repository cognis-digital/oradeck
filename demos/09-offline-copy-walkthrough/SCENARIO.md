# Demo 09 — End-to-end offline copy walkthrough (zero network)

## Where the data came from

This is the canonical air-gap loop, exercised end to end with **no network and
no Docker** using the built-in fixture image. It mirrors what you do for real:
copy an image plus its referrers into a store, inspect it, verify it, then (on
the far side) push it. Only the final push needs a live destination registry,
so this demo runs everything up to that line offline.

## What to expect

`copy --demo` reports `blobs: 2` (config + layer), `referrers: 1` (the SBOM
attestation). `inspect` then shows 1 artifact and several blobs; `verify`
returns PASS. The store directory is a valid OCI image layout (note the
`oci-layout` marker and `index.json`).

## Run it

```bash
S=/tmp/oradeck-walk

# 1. Copy image + referrers into a content-addressable store (offline fixture).
python -m oradeck copy x --demo --store "$S"

# 2. See the OCI layout it produced.
ls "$S" && cat "$S/oci-layout"

# 3. Inventory and integrity-check before transport.
python -m oradeck inspect --store "$S"
python -m oradeck verify  --store "$S"

# 4. On the far side, push into the disconnected registry (needs a live target):
#    python -m oradeck push localhost:5000/cognis/demo:1.0.0 --store "$S" --insecure
```

## How to act

Script steps 1-3 into your "prepare media" job and step 4 into the
"seed registry" job on the disconnected side. Because the store is a standard
OCI layout, other OCI tooling on the far side can read it too if needed.
