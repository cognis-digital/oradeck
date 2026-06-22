# Demo 04 — Reference parsing across every real shape

## Where the data came from

Before mirroring, operators paste image references from many sources — Helm
charts, `docker-compose.yml`, CI logs. They look similar but parse differently:
`localhost:5000/app:1.0.0` has a *port* and a *tag*; `nginx` is a bare Hub
image; a `@sha256:` pin is immutable. `references.txt` collects one of each
real shape.

## What to expect

`oradeck parse <ref>` prints JSON with `registry`, `repository`, `tag`,
`digest`, and the `canonical` form. Key behaviours to confirm:

- `nginx` -> registry `registry-1.docker.io`, tag `latest`.
- `localhost:5000/cognis/app:1.0.0` -> registry `localhost:5000` (port, not a
  tag), tag `1.0.0`.
- the `@sha256:...` ref -> `digest` set, `tag` null (digest pins win).

## Run it

```bash
# Parse one reference.
python -m oradeck parse localhost:5000/cognis/app:1.0.0

# Parse every shape in the list (skips comments/blank lines).
grep -v '^\s*#' demos/04-reference-shapes/references.txt | grep . | while read ref; do
    echo "== $ref"
    python -m oradeck parse "$ref"
done
```

## How to act

Use `parse` to sanity-check references before a bulk `plan`/`copy`: a wrong
registry split (port mistaken for a tag) is the most common air-gap mirror bug,
and `parse` surfaces it in one line.
