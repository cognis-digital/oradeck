# Demo 02 — Plan a mirror from a declarative mirror-set file

## Where the data came from

A platform team runs a disconnected inference cluster on a factory floor. The
exact image set the cluster needs lives in version control as a **mirror-set
file** (`mirror-set.txt`) next to the GitOps manifests — the air-gap analogue
of a lockfile. When a new release is cut, an operator regenerates the copy plan
from this one file instead of re-typing a dozen image references.

The file format is the tool's real input: one image reference per line, `#`
comments and blank lines ignored, and a `registry:` directive naming the
far-side (disconnected) registry.

## What to expect

`plan --from` reads the file, applies the in-file `registry:` as the
destination, and emits one `source -> destination` mapping per image (6 here).
No network is touched — `plan` is pure reference arithmetic.

## Run it

```bash
# Human-readable plan, destination taken from the file's `registry:` line.
python -m oradeck plan --from demos/02-mirror-set-edge-stack/mirror-set.txt

# Machine-readable plan for a CI job, written to a file.
python -m oradeck plan --from demos/02-mirror-set-edge-stack/mirror-set.txt \
    --format json --out plan.json
```

## How to act

Feed `plan.json` to a copy loop (`oradeck copy <source> --store ./oci-store`
for each `plan[].source`), carry `./oci-store` across the gap, then
`oradeck push <plan[].destination> --store ./oci-store --insecure`. Keeping the
mirror-set in git makes every air-gap drop reproducible and auditable.
