# Demo 07 — Garbage-collect orphan blobs to shrink the media

## Where the data came from

A store accumulates cruft: you re-`copy` a `:latest` tag that moved, or drop an
image from the mirror-set, and the old blobs linger — content-addressed but no
longer reachable from any indexed manifest. On size-constrained removable media
that dead weight matters.

`gc` walks every manifest tree from the index (including SBOM/signature
referrers linked by `subject`) to compute the reachable set, then reports blobs
outside it. It is **dry-run by default**; `--apply` actually deletes.

## What to expect

This demo builds a real store, injects an unreferenced junk blob, then GCs:

- `gc` (dry-run) -> lists the orphan, reports bytes that *would* be freed,
  leaves files in place.
- `gc --apply` -> removes the orphan; a follow-up `verify` still PASSES (real
  artifacts are untouched).

## Run it

```bash
python -m oradeck copy x --demo --store /tmp/oradeck-gc
# Inject an orphan blob (simulates a stale layer left behind by a moved tag).
mkdir -p /tmp/oradeck-gc/blobs/sha256
printf 'stale-unreferenced-layer' > /tmp/oradeck-gc/blobs/sha256/$(printf 'stale-unreferenced-layer' | sha256sum | cut -d' ' -f1)

python -m oradeck gc --store /tmp/oradeck-gc            # DRY RUN — would remove 1
python -m oradeck gc --store /tmp/oradeck-gc --apply    # REMOVED 1
python -m oradeck verify --store /tmp/oradeck-gc        # still PASS
```

## How to act

Run `gc` (dry-run) to preview, then `gc --apply` before imaging the media.
Always follow with `verify` to confirm GC only touched orphans.
