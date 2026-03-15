"""Content-Addressed Storage (CAS) — SHA-256 blob storage with Merkle verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def sha256_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class VerificationResult:
    """Result of archive verification."""

    valid: bool
    failed_digests: list[str] = field(default_factory=list)
    missing_blobs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid


class ContentAddressedStore:
    """SHA-256 content-addressed blob storage.

    Layout:
        <root>/
            manifest.json
            blobs/sha256/<digest>
            refs/
            meta/
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.blobs_dir = self.root / "blobs" / "sha256"
        self.refs_dir = self.root / "refs"
        self.meta_dir = self.root / "meta"

    def initialize(self) -> None:
        """Create the archive directory structure."""
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.refs_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def store_blob(self, data: bytes) -> str:
        """Store data as a content-addressed blob. Returns the SHA-256 digest."""
        digest = sha256_digest(data)
        blob_path = self.blobs_dir / digest
        if not blob_path.exists():
            blob_path.write_bytes(data)
        return digest

    def retrieve_blob(self, digest: str) -> Optional[bytes]:
        """Retrieve blob by digest. Returns None if not found."""
        blob_path = self.blobs_dir / digest
        if blob_path.exists():
            return blob_path.read_bytes()
        return None

    def has_blob(self, digest: str) -> bool:
        """Check if a blob exists."""
        return (self.blobs_dir / digest).exists()

    def verify_blob(self, digest: str) -> bool:
        """Verify a blob's integrity by recomputing its hash."""
        data = self.retrieve_blob(digest)
        if data is None:
            return False
        return sha256_digest(data) == digest

    def list_blobs(self) -> list[str]:
        """List all blob digests."""
        if not self.blobs_dir.exists():
            return []
        return [f.name for f in self.blobs_dir.iterdir() if f.is_file()]

    def store_json(self, data: dict | list, name: str, subdir: str = "refs") -> str:
        """Store JSON data in refs/ or meta/. Returns digest of content."""
        content = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        target_dir = self.refs_dir if subdir == "refs" else self.meta_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / name).write_bytes(content)
        return sha256_digest(content)

    def read_json(self, name: str, subdir: str = "refs") -> Optional[dict | list]:
        """Read JSON from refs/ or meta/."""
        target_dir = self.refs_dir if subdir == "refs" else self.meta_dir
        path = target_dir / name
        if path.exists():
            return json.loads(path.read_text())
        return None

    def write_manifest(self, manifest_dict: dict) -> str:
        """Write manifest.json to archive root. Returns digest."""
        content = json.dumps(manifest_dict, indent=2, sort_keys=True).encode("utf-8")
        (self.root / "manifest.json").write_bytes(content)
        return sha256_digest(content)

    def read_manifest(self) -> Optional[dict]:
        """Read manifest.json from archive root."""
        path = self.root / "manifest.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def verify_archive(self) -> VerificationResult:
        """Verify entire archive: manifest + all referenced blobs."""
        result = VerificationResult(valid=True)

        # Check manifest exists
        manifest_data = self.read_manifest()
        if manifest_data is None:
            result.valid = False
            result.errors.append("Missing manifest.json")
            return result

        # Verify manifest root_digest
        root_digest = manifest_data.get("root_digest", "")
        manifest_copy = dict(manifest_data)
        manifest_copy.pop("root_digest", None)
        expected_digest = sha256_digest(
            json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
        )
        if root_digest != expected_digest:
            result.valid = False
            result.errors.append(
                f"Manifest root_digest mismatch: expected {expected_digest}, got {root_digest}"
            )

        # Verify all layer blobs
        for layer in manifest_data.get("layers", []):
            digest = layer.get("digest", "")
            if not digest:
                continue
            if not self.has_blob(digest):
                result.valid = False
                result.missing_blobs.append(digest)
            elif not self.verify_blob(digest):
                result.valid = False
                result.failed_digests.append(digest)

        return result

    def copy_blob_from(self, other: ContentAddressedStore, digest: str) -> bool:
        """Copy a blob from another CAS store (for incremental builds)."""
        data = other.retrieve_blob(digest)
        if data is None:
            return False
        self.store_blob(data)
        return True

    def archive_size(self) -> int:
        """Total size of all blobs in bytes."""
        total = 0
        for blob in self.blobs_dir.iterdir():
            if blob.is_file():
                total += blob.stat().st_size
        return total
