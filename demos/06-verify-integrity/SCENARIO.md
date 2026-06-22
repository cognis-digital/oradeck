# Demo 06 — Verify store integrity after the media crosses the gap

## Where the data came from

Removable media is exactly where bit-rot, a truncated copy, or a flaky USB
controller bites you — and you only find out *after* you've carried it to a
disconnected site. `verify` re-hashes every blob in the store and confirms that
every blob referenced by an indexed manifest is actually present.

This demo builds a clean store, verifies it (PASS), then simulates corruption
by appending a byte to one blob and re-verifies (FAIL) — the content no longer
matches its content-address.

## What to expect

- First `verify` -> `RESULT: PASS`, non-zero blobs checked and reachable.
- After tampering, `verify` -> `RESULT: FAIL` with a `blob content mismatch`
  problem line, and a non-zero exit code (usable in a script gate).

## Run it

```bash
python -m oradeck copy x --demo --store /tmp/oradeck-verify
python -m oradeck verify --store /tmp/oradeck-verify      # PASS, exit 0

# Simulate transport corruption on the first blob, then re-verify.
f=$(ls /tmp/oradeck-verify/blobs/sha256 | head -1)
printf 'x' >> /tmp/oradeck-verify/blobs/sha256/$f
python -m oradeck verify --store /tmp/oradeck-verify      # FAIL, exit 1
```

## How to act

Run `verify` as the first step on the far side and gate the push on its exit
code: `oradeck verify --store ./media && oradeck push ...`. A FAIL means
re-pull the affected artifact on the connected side — never push a store that
does not verify.
