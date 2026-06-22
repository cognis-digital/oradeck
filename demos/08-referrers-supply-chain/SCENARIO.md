# Demo 08 — Confirm supply-chain referrers crossed the gap

## Where the data came from

The whole point of oradeck over a plain `docker pull | docker save` is that
**referrers travel too**: detached signatures, SBOMs, and attestations that
point at an image via their `subject` field. On the far side, a security
reviewer needs to confirm those artifacts actually made it — an image with no
SBOM next to it is a finding, not a mirror.

`referrers <subject-digest>` lists every manifest in the store whose `subject`
points at the given image manifest digest. The fixture image ships with an
SPDX SBOM attestation, so this is a real, grounded check.

## What to expect

1. `inspect --format json` gives you the image's manifest digest.
2. `referrers <that-digest>` lists the SBOM attestation
   (`artifactType: application/spdx+json`).

## Run it

```bash
python -m oradeck copy x --demo --store /tmp/oradeck-ref

# Pull the subject (image) manifest digest out of the store index.
SUBJECT=$(python -m oradeck inspect --store /tmp/oradeck-ref --format json \
          | python -c "import sys,json; print(json.load(sys.stdin)['artifacts'][0]['digest'])")

# List what references it — the SBOM attestation should appear.
python -m oradeck referrers "$SUBJECT" --store /tmp/oradeck-ref
```

## How to act

Gate acceptance on the presence of the expected referrer types: if an image is
supposed to carry an SBOM and a signature, `referrers` listing fewer than
expected means the supply-chain evidence did not cross the gap — re-pull with
referrers enabled (the default) before seeding the disconnected registry.
