"""Core engine for oradeck — OCI registry mirror & artifact copy.

oradeck moves OCI artifacts (container images and their *referrers* — signatures,
SBOMs, attestations) between registries and a portable on-disk store, so they
can cross an air-gap and seed a disconnected registry.

It speaks the OCI Distribution Spec directly over HTTP(S) using only the Python
standard library:

  * resolve a tag to a manifest (or manifest index / image index)
  * walk an image's config + layer blobs by digest
  * discover *referrers* (the Referrers API, with a fallback tag scheme) so
    detached signature and attestation artifacts travel with the image
  * copy all of that into a content-addressable local store (an OCI layout)
  * push a local store back up into a destination registry

When a real registry is unreachable (the common offline-demo case) every
function degrades gracefully: planning still works from the local store, and a
small built-in fixture registry lets the demos and tests run with no network.

This is original Cognis Digital work. It implements the open OCI Distribution
Spec; it contains no third-party code, names, or branding.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

TOOL_NAME = "oradeck"
TOOL_VERSION = "0.1.0"

# Media types we recognize when walking a manifest tree.
MT_MANIFEST_V2 = "application/vnd.docker.distribution.manifest.v2+json"
MT_MANIFEST_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
MT_OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
MT_OCI_INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST_ACCEPT = ", ".join([
    MT_OCI_INDEX, MT_OCI_MANIFEST, MT_MANIFEST_LIST, MT_MANIFEST_V2,
])

_INDEX_TYPES = {MT_MANIFEST_LIST, MT_OCI_INDEX}

DEFAULT_TIMEOUT = 30


class OradeckError(Exception):
    """User-facing error for registry/store problems."""


# --------------------------------------------------------------------------- #
# Reference parsing
# --------------------------------------------------------------------------- #

@dataclass
class Ref:
    """A parsed OCI reference: registry / repository : tag-or-@digest."""
    registry: str
    repository: str
    tag: Optional[str] = None
    digest: Optional[str] = None

    @property
    def reference(self) -> str:
        return self.digest or self.tag or "latest"

    def __str__(self) -> str:
        base = f"{self.registry}/{self.repository}"
        if self.digest:
            return f"{base}@{self.digest}"
        return f"{base}:{self.tag or 'latest'}"


def parse_ref(ref: str, default_registry: str = "registry-1.docker.io") -> Ref:
    """Parse an image reference into its parts.

    Handles ``host[:port]/repo[:tag][@digest]`` and bare ``repo:tag`` (which
    falls back to ``default_registry``). Digest pins win over tags.
    """
    if not ref or not ref.strip():
        raise OradeckError("empty reference")
    s = ref.strip()
    digest = None
    if "@" in s:
        s, digest = s.split("@", 1)
        if not re.match(r"^[a-z0-9]+:[0-9a-f]{32,}$", digest):
            raise OradeckError(f"malformed digest: {digest}")
    # Split registry from the path. The first path segment is a registry only
    # if it contains a '.' or ':' or equals 'localhost'.
    parts = s.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry = parts[0]
        rest = "/".join(parts[1:])
    else:
        registry = default_registry
        rest = s
    tag = None
    # A ':' in the LAST path segment denotes a tag.
    seg = rest.rsplit("/", 1)
    last = seg[-1]
    if ":" in last:
        name, tag = last.rsplit(":", 1)
        rest = (seg[0] + "/" + name) if len(seg) > 1 else name
    if not digest and not tag:
        tag = "latest"
    return Ref(registry=registry, repository=rest, tag=tag, digest=digest)


# --------------------------------------------------------------------------- #
# Digests / store
# --------------------------------------------------------------------------- #

def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _blob_path(store: str, digest: str) -> str:
    algo, hexd = digest.split(":", 1)
    return os.path.join(store, "blobs", algo, hexd)


def store_blob(store: str, data: bytes) -> str:
    """Write a blob into the local OCI-layout store; return its digest."""
    dig = digest_of(data)
    path = _blob_path(store, dig)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(data)
    return dig


def read_blob(store: str, digest: str) -> bytes:
    path = _blob_path(store, digest)
    if not os.path.isfile(path):
        raise OradeckError(f"blob not in store: {digest}")
    with open(path, "rb") as fh:
        return fh.read()


def _index_path(store: str) -> str:
    return os.path.join(store, "index.json")


def load_store_index(store: str) -> Dict[str, Any]:
    p = _index_path(store)
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"schemaVersion": 2,
            "mediaType": MT_OCI_INDEX, "manifests": []}


def save_store_index(store: str, index: Dict[str, Any]) -> None:
    os.makedirs(store, exist_ok=True)
    with open(_index_path(store), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2)
    # OCI layout marker.
    with open(os.path.join(store, "oci-layout"), "w", encoding="utf-8") as fh:
        json.dump({"imageLayoutVersion": "1.0.0"}, fh)


def add_to_index(store: str, ref: Ref, manifest_digest: str,
                 media_type: str, size: int) -> None:
    index = load_store_index(store)
    annotations = {
        "org.opencontainers.image.ref.name": ref.reference,
        "io.cognis.oradeck.source": str(ref),
    }
    entry = {"mediaType": media_type, "digest": manifest_digest,
             "size": size, "annotations": annotations}
    # Replace any existing entry for the same source ref.
    index["manifests"] = [m for m in index.get("manifests", [])
                          if m.get("annotations", {}).get(
                              "io.cognis.oradeck.source") != str(ref)]
    index["manifests"].append(entry)
    save_store_index(store, index)


# --------------------------------------------------------------------------- #
# Registry client (OCI Distribution Spec over urllib)
# --------------------------------------------------------------------------- #

class RegistryClient:
    """Minimal pull/push client for an OCI registry.

    Supports anonymous and bearer-token (Docker-style WWW-Authenticate) flows
    and basic auth. ``insecure`` selects http. A ``fixture`` mapping can stand
    in for a live registry so demos/tests run offline.
    """

    def __init__(self, registry: str, insecure: bool = False,
                 username: Optional[str] = None, password: Optional[str] = None,
                 timeout: int = DEFAULT_TIMEOUT,
                 fixture: Optional[Dict[str, bytes]] = None):
        self.registry = registry
        self.scheme = "http" if insecure else "https"
        self.username = username
        self.password = password
        self.timeout = timeout
        self._token: Optional[str] = None
        self.fixture = fixture  # path("/v2/...") -> bytes, for offline use

    # ---- low level ---------------------------------------------------- #
    def _url(self, path: str) -> str:
        return f"{self.scheme}://{self.registry}{path}"

    def _auth_header(self, www_auth: str) -> Optional[str]:
        # Parse: Bearer realm="...",service="...",scope="..."
        m = dict(re.findall(r'(\w+)="([^"]*)"', www_auth or ""))
        realm = m.get("realm")
        if not realm:
            return None
        q = []
        if m.get("service"):
            q.append("service=" + urllib.request.quote(m["service"]))
        if m.get("scope"):
            q.append("scope=" + urllib.request.quote(m["scope"]))
        token_url = realm + ("?" + "&".join(q) if q else "")
        req = urllib.request.Request(token_url)
        if self.username:
            cred = base64.b64encode(
                f"{self.username}:{self.password or ''}".encode()).decode()
            req.add_header("Authorization", "Basic " + cred)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                tok = json.loads(resp.read().decode())
                return tok.get("token") or tok.get("access_token")
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def _request(self, method: str, path: str, accept: Optional[str] = None,
                 data: Optional[bytes] = None,
                 content_type: Optional[str] = None) -> Tuple[int, Dict[str, str], bytes]:
        # Offline fixture short-circuit (GET only).
        if self.fixture is not None and method == "GET":
            if path in self.fixture:
                body = self.fixture[path]
                ct = MANIFEST_ACCEPT.split(", ")[1] if "/manifests/" in path else "application/octet-stream"
                return 200, {"content-type": ct,
                             "docker-content-digest": digest_of(body)}, body
            return 404, {}, b""

        url = self._url(path)
        headers = {}
        if accept:
            headers["Accept"] = accept
        if content_type:
            headers["Content-Type"] = content_type
        if self._token:
            headers["Authorization"] = "Bearer " + self._token

        def _do() -> Tuple[int, Dict[str, str], bytes]:
            req = urllib.request.Request(url, data=data, method=method,
                                         headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return (resp.status,
                            {k.lower(): v for k, v in resp.headers.items()},
                            resp.read())
            except urllib.error.HTTPError as exc:
                return (exc.code,
                        {k.lower(): v for k, v in (exc.headers or {}).items()},
                        exc.read() if exc.fp else b"")

        status, hdrs, body = _do()
        if status == 401 and not self._token:
            tok = self._auth_header(hdrs.get("www-authenticate", ""))
            if tok:
                self._token = tok
                headers["Authorization"] = "Bearer " + tok
                status, hdrs, body = _do()
        return status, hdrs, body

    # ---- pull --------------------------------------------------------- #
    def get_manifest(self, repository: str, reference: str) -> Tuple[bytes, str, str]:
        path = f"/v2/{repository}/manifests/{reference}"
        status, hdrs, body = self._request("GET", path, accept=MANIFEST_ACCEPT)
        if status != 200:
            raise OradeckError(
                f"manifest fetch failed ({status}) for {repository}:{reference}")
        media = hdrs.get("content-type", MT_OCI_MANIFEST).split(";")[0].strip()
        dig = hdrs.get("docker-content-digest") or digest_of(body)
        return body, media, dig

    def get_blob(self, repository: str, digest: str) -> bytes:
        path = f"/v2/{repository}/blobs/{digest}"
        status, _hdrs, body = self._request("GET", path,
                                            accept="application/octet-stream")
        if status != 200:
            raise OradeckError(f"blob fetch failed ({status}) for {digest}")
        return body

    def get_referrers(self, repository: str, digest: str) -> List[Dict[str, Any]]:
        """Discover referrers (signatures/attestations) for a subject digest.

        Tries the Referrers API; on 404 falls back to the digest-tag scheme
        (``sha256-<hex>``) used by detached-signature tooling. Returns descriptors.
        """
        path = f"/v2/{repository}/referrers/{digest}"
        status, _hdrs, body = self._request("GET", path, accept=MT_OCI_INDEX)
        if status == 200 and body:
            try:
                idx = json.loads(body.decode())
                return idx.get("manifests", []) or []
            except json.JSONDecodeError:
                return []
        # Fallback tag scheme.
        algo, hexd = digest.split(":", 1)
        fallback_tag = f"{algo}-{hexd}"
        try:
            mbody, media, mdig = self.get_manifest(repository, fallback_tag)
            return [{"mediaType": media, "digest": mdig, "size": len(mbody),
                     "annotations": {"io.cognis.oradeck.referrer_tag": fallback_tag}}]
        except OradeckError:
            return []

    # ---- push --------------------------------------------------------- #
    def put_blob(self, repository: str, digest: str, data: bytes) -> None:
        # Check existence first.
        head_path = f"/v2/{repository}/blobs/{digest}"
        status, _h, _b = self._request("GET", head_path,
                                       accept="application/octet-stream")
        if status == 200:
            return
        # Start an upload session.
        status, hdrs, _b = self._request("POST", f"/v2/{repository}/blobs/uploads/")
        if status not in (202, 201):
            raise OradeckError(f"could not start blob upload ({status})")
        location = hdrs.get("location", "")
        sep = "&" if "?" in location else "?"
        put_path = f"{location}{sep}digest={digest}"
        if put_path.startswith("http"):
            put_path = re.sub(r"^https?://[^/]+", "", put_path)
        status, _h, _b = self._request("PUT", put_path, data=data,
                                       content_type="application/octet-stream")
        if status not in (201, 202):
            raise OradeckError(f"blob upload failed ({status}) for {digest}")

    def put_manifest(self, repository: str, reference: str,
                     data: bytes, media_type: str) -> str:
        path = f"/v2/{repository}/manifests/{reference}"
        status, hdrs, _b = self._request("PUT", path, data=data,
                                         content_type=media_type)
        if status not in (201, 202):
            raise OradeckError(f"manifest upload failed ({status})")
        return hdrs.get("docker-content-digest") or digest_of(data)


# --------------------------------------------------------------------------- #
# Manifest walking
# --------------------------------------------------------------------------- #

def _referenced_blobs(manifest: Dict[str, Any]) -> List[str]:
    digs: List[str] = []
    cfg = manifest.get("config")
    if isinstance(cfg, dict) and cfg.get("digest"):
        digs.append(cfg["digest"])
    for layer in manifest.get("layers", []) or []:
        if isinstance(layer, dict) and layer.get("digest"):
            digs.append(layer["digest"])
    return digs


def _child_manifests(index: Dict[str, Any]) -> List[str]:
    return [m["digest"] for m in index.get("manifests", [])
            if isinstance(m, dict) and m.get("digest")]


# --------------------------------------------------------------------------- #
# copy (registry -> store) / push (store -> registry)
# --------------------------------------------------------------------------- #

def copy_to_store(ref_str: str, store: str, *, client: Optional[RegistryClient] = None,
                  insecure: bool = False, with_referrers: bool = True,
                  username: Optional[str] = None,
                  password: Optional[str] = None) -> Dict[str, Any]:
    """Copy an artifact (and optionally its referrers) into a local store.

    Returns a copy report. Raises OradeckError on a hard registry failure.
    """
    ref = parse_ref(ref_str)
    client = client or RegistryClient(ref.registry, insecure=insecure,
                                      username=username, password=password)
    os.makedirs(store, exist_ok=True)

    copied_blobs: List[str] = []
    copied_manifests: List[str] = []

    def _walk(reference: str) -> str:
        body, media, dig = client.get_manifest(ref.repository, reference)
        store_blob(store, body)  # manifests live as blobs in OCI layout
        copied_manifests.append(dig)
        manifest = json.loads(body.decode())
        if media in _INDEX_TYPES:
            for child in _child_manifests(manifest):
                _walk(child)
        else:
            for bdig in _referenced_blobs(manifest):
                data = client.get_blob(ref.repository, bdig)
                store_blob(store, data)
                copied_blobs.append(bdig)
        return dig, media, len(body)  # type: ignore[return-value]

    top_dig, top_media, top_size = _walk(ref.reference)  # type: ignore[misc]
    add_to_index(store, ref, top_dig, top_media, top_size)

    referrers_copied = 0
    if with_referrers:
        for desc in client.get_referrers(ref.repository, top_dig):
            try:
                rbody, rmedia, rdig = client.get_manifest(ref.repository,
                                                          desc["digest"])
                store_blob(store, rbody)
                rmani = json.loads(rbody.decode())
                for bdig in _referenced_blobs(rmani):
                    store_blob(store, client.get_blob(ref.repository, bdig))
                referrers_copied += 1
            except (OradeckError, json.JSONDecodeError):
                continue

    return {
        "source": str(ref),
        "store": store,
        "manifest_digest": top_dig,
        "media_type": top_media,
        "blobs_copied": len(copied_blobs),
        "manifests_copied": len(copied_manifests),
        "referrers_copied": referrers_copied,
    }


def push_from_store(store: str, dest_ref_str: str, *,
                    client: Optional[RegistryClient] = None,
                    insecure: bool = False,
                    username: Optional[str] = None,
                    password: Optional[str] = None) -> Dict[str, Any]:
    """Push a stored artifact up to a destination registry.

    The store entry is matched by its ref.name annotation (tag) or by digest.
    """
    dest = parse_ref(dest_ref_str)
    client = client or RegistryClient(dest.registry, insecure=insecure,
                                      username=username, password=password)
    index = load_store_index(store)

    # Find the manifest descriptor to push.
    target = None
    for m in index.get("manifests", []):
        ann = m.get("annotations", {})
        if dest.digest and m.get("digest") == dest.digest:
            target = m
            break
        if ann.get("org.opencontainers.image.ref.name") == dest.reference:
            target = m
            break
    if target is None and index.get("manifests"):
        target = index["manifests"][-1]  # default to most recent
    if target is None:
        raise OradeckError("store is empty — nothing to push")

    pushed_blobs = 0

    def _push_manifest(digest: str) -> None:
        nonlocal pushed_blobs
        body = read_blob(store, digest)
        manifest = json.loads(body.decode())
        media = manifest.get("mediaType") or target["mediaType"]
        if media in _INDEX_TYPES:
            for child in _child_manifests(manifest):
                _push_manifest(child)
        else:
            for bdig in _referenced_blobs(manifest):
                client.put_blob(dest.repository, bdig, read_blob(store, bdig))
                pushed_blobs += 1
        client.put_manifest(dest.repository, digest, body, media)

    _push_manifest(target["digest"])
    # Finally tag it.
    body = read_blob(store, target["digest"])
    client.put_manifest(dest.repository, dest.reference, body,
                        target["mediaType"])

    return {
        "destination": str(dest),
        "manifest_digest": target["digest"],
        "blobs_pushed": pushed_blobs,
    }


# --------------------------------------------------------------------------- #
# mirror plan (declarative many-image copy)
# --------------------------------------------------------------------------- #

def plan_mirror(images: List[str], dest_registry: str) -> List[Dict[str, str]]:
    """Compute a copy plan: each source ref -> its destination ref."""
    plan = []
    for img in images:
        ref = parse_ref(img)
        dest = f"{dest_registry}/{ref.repository}:{ref.tag or 'latest'}"
        plan.append({"source": str(ref), "destination": dest})
    return plan


def load_mirror_set(path: str) -> Tuple[List[str], Optional[str]]:
    """Load a declarative mirror-set file -> ``(images, dest_registry)``.

    A mirror-set is the air-gap analogue of a lockfile: the exact image set to
    carry across the gap, kept in version control next to the app it serves.
    Two on-disk shapes are accepted, auto-detected by content:

    * **Plain list** — one image reference per line. Blank lines and ``#``
      comments are ignored; an inline ``# ...`` trailing comment is stripped.
      A ``registry: <host[:port]>`` directive line sets the destination.
    * **JSON** — ``{"registry": "host:port", "images": ["nginx:1.27", ...]}``.
      ``destination``/``dest`` are accepted as aliases for ``registry``.

    The returned ``dest_registry`` is the in-file destination if present, else
    ``None`` (so a CLI ``--to`` can supply or override it). Raises
    ``OradeckError`` on a missing file or a malformed mirror-set.
    """
    if not os.path.isfile(path):
        raise OradeckError(f"mirror-set file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OradeckError(f"malformed mirror-set JSON: {exc}") from exc
        if not isinstance(doc, dict):
            raise OradeckError("mirror-set JSON must be an object")
        raw = doc.get("images")
        if not isinstance(raw, list):
            raise OradeckError("mirror-set JSON needs an `images` array")
        images = [str(x).strip() for x in raw if str(x).strip()]
        dest = doc.get("registry") or doc.get("destination") or doc.get("dest")
        dest = str(dest).strip() if dest else None
        if not images:
            raise OradeckError("mirror-set has no images")
        return images, (dest or None)

    images = []
    dest = None
    for line in text.splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("registry:"):
            dest = line.split(":", 1)[1].strip() or None
            continue
        images.append(line)
    if not images:
        raise OradeckError("mirror-set has no images")
    return images, dest


# --------------------------------------------------------------------------- #
# inspect store
# --------------------------------------------------------------------------- #

def inspect_store(store: str) -> Dict[str, Any]:
    if not os.path.isdir(store):
        raise OradeckError(f"store not found: {store}")
    index = load_store_index(store)
    blobs_dir = os.path.join(store, "blobs", "sha256")
    blob_count = len(os.listdir(blobs_dir)) if os.path.isdir(blobs_dir) else 0
    total = 0
    if os.path.isdir(blobs_dir):
        for fn in os.listdir(blobs_dir):
            total += os.path.getsize(os.path.join(blobs_dir, fn))
    return {
        "store": store,
        "artifacts": index.get("manifests", []),
        "artifact_count": len(index.get("manifests", [])),
        "blob_count": blob_count,
        "total_bytes": total,
    }


# --------------------------------------------------------------------------- #
# Reachability: walk the manifest trees from the index to find live blobs
# --------------------------------------------------------------------------- #

def _reachable_digests(store: str) -> set:
    """All blob digests reachable from the store index (manifests + their blobs)."""
    index = load_store_index(store)
    reachable: set = set()

    def walk(digest: str) -> None:
        if digest in reachable:
            return
        reachable.add(digest)
        try:
            body = read_blob(store, digest)
        except OradeckError:
            return
        try:
            manifest = json.loads(body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        media = manifest.get("mediaType", "")
        if media in _INDEX_TYPES:
            for child in _child_manifests(manifest):
                walk(child)
        else:
            for b in _referenced_blobs(manifest):
                reachable.add(b)
        # subject (referrers) link
        subj = manifest.get("subject")
        if isinstance(subj, dict) and subj.get("digest"):
            reachable.add(subj["digest"])

    for entry in index.get("manifests", []):
        if entry.get("digest"):
            walk(entry["digest"])

    # Also keep referrer manifests (and their blobs) whose `subject` points at
    # anything already reachable — these are the sigs/SBOMs/attestations copied
    # alongside the image; they are linked from the image, not from the index.
    blobs_dir = os.path.join(store, "blobs", "sha256")
    if os.path.isdir(blobs_dir):
        changed = True
        while changed:
            changed = False
            for fn in os.listdir(blobs_dir):
                dig = "sha256:" + fn
                if dig in reachable:
                    continue
                try:
                    m = json.loads(read_blob(store, dig).decode())
                except (OradeckError, json.JSONDecodeError, UnicodeDecodeError):
                    continue
                subj = m.get("subject")
                if isinstance(subj, dict) and subj.get("digest") in reachable:
                    walk(dig)
                    changed = True
    return reachable


def verify_store(store: str) -> Dict[str, Any]:
    """Verify store integrity: every blob's content matches its digest, and
    every digest referenced by an indexed manifest is present.
    """
    if not os.path.isdir(store):
        raise OradeckError(f"store not found: {store}")
    blobs_dir = os.path.join(store, "blobs", "sha256")
    problems: List[str] = []
    checked = 0
    if os.path.isdir(blobs_dir):
        for fn in os.listdir(blobs_dir):
            path = os.path.join(blobs_dir, fn)
            with open(path, "rb") as fh:
                actual = hashlib.sha256(fh.read()).hexdigest()
            checked += 1
            if actual != fn:
                problems.append(f"blob content mismatch: {fn[:16]}… (got {actual[:16]}…)")
    reachable = _reachable_digests(store)
    for dig in reachable:
        if not os.path.isfile(_blob_path(store, dig)):
            problems.append(f"missing referenced blob: {dig}")
    return {"store": store, "ok": not problems, "blobs_checked": checked,
            "reachable": len(reachable), "problems": problems}


def gc_store(store: str, dry_run: bool = True) -> Dict[str, Any]:
    """Garbage-collect blobs not reachable from the store index.

    With ``dry_run`` (default) it only reports what would be removed; pass
    ``dry_run=False`` to actually delete the orphaned blobs.
    """
    if not os.path.isdir(store):
        raise OradeckError(f"store not found: {store}")
    blobs_dir = os.path.join(store, "blobs", "sha256")
    reachable = {d.split(":", 1)[1] for d in _reachable_digests(store)
                 if d.startswith("sha256:")}
    orphans: List[str] = []
    freed = 0
    if os.path.isdir(blobs_dir):
        for fn in os.listdir(blobs_dir):
            if fn not in reachable:
                path = os.path.join(blobs_dir, fn)
                freed += os.path.getsize(path)
                orphans.append("sha256:" + fn)
                if not dry_run:
                    os.remove(path)
    return {"store": store, "dry_run": dry_run, "orphans": orphans,
            "removed": 0 if dry_run else len(orphans),
            "freed_bytes": freed}


def list_referrers(store: str, subject_digest: str) -> List[Dict[str, Any]]:
    """List manifests in the store whose ``subject`` points at a digest."""
    blobs_dir = os.path.join(store, "blobs", "sha256")
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(blobs_dir):
        return out
    for fn in os.listdir(blobs_dir):
        try:
            body = read_blob(store, "sha256:" + fn)
            m = json.loads(body.decode())
        except (OradeckError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        subj = m.get("subject")
        if isinstance(subj, dict) and subj.get("digest") == subject_digest:
            out.append({"digest": "sha256:" + fn,
                        "artifactType": m.get("artifactType"),
                        "mediaType": m.get("mediaType")})
    return out


# --------------------------------------------------------------------------- #
# AI hook (opt-in, default OFF) — reused suite pattern
# --------------------------------------------------------------------------- #

def suggest_mirror_set(description: str) -> Dict[str, Any]:
    """Suggest a mirror image set from a plain-English stack description.

    Off by default: returns a deterministic empty plan unless the shared Cognis
    AI backend is configured (COGNIS_AI_*). Never raises.
    """
    out = {"description": description.strip()[:200], "images": [],
           "_ai": "disabled — set COGNIS_AI_BACKEND to enable"}
    backend = _load_ai_backend()
    if backend is None or not backend.is_enabled() or not backend.health():
        return out
    prompt = ("Given a stack description, output ONLY a JSON array of container "
              "image references (with tags) needed to run it air-gapped. No prose.\n\n"
              f"STACK:\n{description}\n")
    try:
        content = backend._chat("Return strict JSON only.", prompt)
    except Exception:
        return out
    arr = _extract_json_array(content or "")
    if isinstance(arr, list):
        out["images"] = [str(x) for x in arr if isinstance(x, (str,))]
        out["_ai"] = "suggested by local fleet"
    return out


def _load_ai_backend():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.abspath(os.path.join(here, "..", "..", "..", "_shared",
                                        "cognis_ai_backend.py"))
    if os.path.isfile(cand):
        try:
            spec = importlib.util.spec_from_file_location("cognis_ai_backend", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return mod.CognisAIBackend()
        except Exception:
            return None
    return None


def _extract_json_array(text: str) -> Any:
    text = (text or "").strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# Offline demo fixture — a tiny synthetic image, no network required.
# --------------------------------------------------------------------------- #

def build_demo_fixture() -> Tuple[Dict[str, bytes], str, str]:
    """Return (fixture_map, repository, tag) for a synthetic 1-layer image.

    The map is keyed by request path so a RegistryClient(fixture=...) can serve
    a complete pull (config + layer + manifest + a detached-signature referrer)
    entirely offline.
    """
    repo, tag = "cognis/demo", "1.0.0"
    config = json.dumps({"architecture": "amd64", "os": "linux",
                         "config": {}, "rootfs": {"type": "layers",
                         "diff_ids": []}}).encode()
    layer = b"cognis-oradeck-demo-layer\n"
    cfg_dig, lay_dig = digest_of(config), digest_of(layer)
    manifest = json.dumps({
        "schemaVersion": 2, "mediaType": MT_OCI_MANIFEST,
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                   "digest": cfg_dig, "size": len(config)},
        "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar",
                    "digest": lay_dig, "size": len(layer)}],
    }).encode()
    man_dig = digest_of(manifest)

    # A referrer (e.g. an SBOM attestation) pointing at the image via subject.
    sbom_blob = json.dumps({"sbom": "demo", "packages": ["alpine", "busybox"]}).encode()
    sbom_dig = digest_of(sbom_blob)
    referrer = json.dumps({
        "schemaVersion": 2, "mediaType": MT_OCI_MANIFEST,
        "artifactType": "application/spdx+json",
        "config": {"mediaType": "application/vnd.oci.empty.v1+json",
                   "digest": digest_of(b"{}"), "size": 2},
        "layers": [{"mediaType": "application/spdx+json",
                    "digest": sbom_dig, "size": len(sbom_blob)}],
        "subject": {"mediaType": MT_OCI_MANIFEST, "digest": man_dig,
                    "size": len(manifest)},
    }).encode()
    ref_dig = digest_of(referrer)
    referrers_index = json.dumps({
        "schemaVersion": 2, "mediaType": MT_OCI_INDEX,
        "manifests": [{"mediaType": MT_OCI_MANIFEST, "digest": ref_dig,
                       "size": len(referrer),
                       "artifactType": "application/spdx+json"}],
    }).encode()

    fixture = {
        f"/v2/{repo}/manifests/{tag}": manifest,
        f"/v2/{repo}/manifests/{man_dig}": manifest,
        f"/v2/{repo}/blobs/{cfg_dig}": config,
        f"/v2/{repo}/blobs/{lay_dig}": layer,
        f"/v2/{repo}/referrers/{man_dig}": referrers_index,
        f"/v2/{repo}/manifests/{ref_dig}": referrer,
        f"/v2/{repo}/blobs/{sbom_dig}": sbom_blob,
        f"/v2/{repo}/blobs/{digest_of(b'{}')}": b"{}",
    }
    return fixture, repo, tag
