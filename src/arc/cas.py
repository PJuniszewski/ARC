"""Content-Addressed Storage (CAS) — SHA-256 blob storage with Merkle verification.

Two backends:
- ContentAddressedStore: directory-based (blobs/sha256/<digest>, manifest.json)
- SqliteCAS: single-file SQLite (blobs table, meta table)

Factory functions:
- open_cas(path): auto-detect file vs directory
- create_cas(path, fmt): create new archive in specified format
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
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
        """Read JSON from refs/ or meta/. Returns None on missing or corrupt files."""
        target_dir = self.refs_dir if subdir == "refs" else self.meta_dir
        path = target_dir / name
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                return None
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

    # -- Test helpers (for tamper/integrity testing) --

    def _test_tamper_blob(self, digest: str, data: bytes) -> None:
        """Overwrite blob content without updating digest. For tamper tests."""
        (self.blobs_dir / digest).write_bytes(data)

    def _test_delete_blob(self, digest: str) -> None:
        """Remove a blob. For integrity tests."""
        path = self.blobs_dir / digest
        if path.exists():
            path.unlink()

    def _test_write_manifest_raw(self, text: str) -> None:
        """Overwrite manifest.json with raw text. For tamper tests."""
        (self.root / "manifest.json").write_text(text)


class SqliteCAS:
    """SQLite-backed content-addressed storage. Single-file archive.

    Schema:
        blobs(digest TEXT PK, data BLOB, size INTEGER)
        meta(key TEXT PK, value TEXT)

    Meta keys: "manifest", "refs/<name>", "meta/<name>"
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def initialize(self) -> None:
        """Create SQLite tables."""
        conn = self._connect()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS blobs "
            "(digest TEXT PRIMARY KEY, data BLOB NOT NULL, size INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.commit()

    def close(self) -> None:
        """Close the SQLite connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def store_blob(self, data: bytes) -> str:
        """Store data as a content-addressed blob. Returns the SHA-256 digest."""
        digest = sha256_digest(data)
        conn = self._connect()
        conn.execute(
            "INSERT OR IGNORE INTO blobs (digest, data, size) VALUES (?, ?, ?)",
            (digest, data, len(data)),
        )
        conn.commit()
        return digest

    def retrieve_blob(self, digest: str) -> Optional[bytes]:
        """Retrieve blob by digest. Returns None if not found."""
        row = self._connect().execute(
            "SELECT data FROM blobs WHERE digest = ?", (digest,)
        ).fetchone()
        return row[0] if row else None

    def has_blob(self, digest: str) -> bool:
        """Check if a blob exists."""
        row = self._connect().execute(
            "SELECT 1 FROM blobs WHERE digest = ?", (digest,)
        ).fetchone()
        return row is not None

    def verify_blob(self, digest: str) -> bool:
        """Verify a blob's integrity by recomputing its hash."""
        data = self.retrieve_blob(digest)
        if data is None:
            return False
        return sha256_digest(data) == digest

    def list_blobs(self) -> list[str]:
        """List all blob digests."""
        rows = self._connect().execute("SELECT digest FROM blobs").fetchall()
        return [r[0] for r in rows]

    def store_json(self, data: dict | list, name: str, subdir: str = "refs") -> str:
        """Store JSON data. Returns digest of content."""
        content = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        key = f"{subdir}/{name}"
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, content.decode("utf-8")),
        )
        conn.commit()
        return sha256_digest(content)

    def read_json(self, name: str, subdir: str = "refs") -> Optional[dict | list]:
        """Read JSON. Returns None on missing or corrupt."""
        key = f"{subdir}/{name}"
        row = self._connect().execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None
        return None

    def write_manifest(self, manifest_dict: dict) -> str:
        """Write manifest. Returns digest."""
        content = json.dumps(manifest_dict, indent=2, sort_keys=True).encode("utf-8")
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("manifest", content.decode("utf-8")),
        )
        conn.commit()
        return sha256_digest(content)

    def read_manifest(self) -> Optional[dict]:
        """Read manifest."""
        row = self._connect().execute(
            "SELECT value FROM meta WHERE key = ?", ("manifest",)
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None
        return None

    def verify_archive(self) -> VerificationResult:
        """Verify entire archive: manifest + all referenced blobs."""
        result = VerificationResult(valid=True)

        manifest_data = self.read_manifest()
        if manifest_data is None:
            result.valid = False
            result.errors.append("Missing manifest")
            return result

        # Verify root_digest
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

        # Verify layer blobs
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

    def copy_blob_from(self, other, digest: str) -> bool:
        """Copy a blob from another CAS store."""
        data = other.retrieve_blob(digest)
        if data is None:
            return False
        self.store_blob(data)
        return True

    def archive_size(self) -> int:
        """Total size of all blobs in bytes."""
        row = self._connect().execute(
            "SELECT COALESCE(SUM(size), 0) FROM blobs"
        ).fetchone()
        return row[0]

    # -- Test helpers --

    def _test_tamper_blob(self, digest: str, data: bytes) -> None:
        """Overwrite blob content without updating digest."""
        conn = self._connect()
        conn.execute(
            "UPDATE blobs SET data = ?, size = ? WHERE digest = ?",
            (data, len(data), digest),
        )
        conn.commit()

    def _test_delete_blob(self, digest: str) -> None:
        """Remove a blob."""
        conn = self._connect()
        conn.execute("DELETE FROM blobs WHERE digest = ?", (digest,))
        conn.commit()

    def _test_write_manifest_raw(self, text: str) -> None:
        """Overwrite manifest with raw text."""
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("manifest", text),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def open_cas(path: str | Path) -> ContentAddressedStore | SqliteCAS:
    """Open an existing archive, auto-detecting backend from path type."""
    path = Path(path)
    if path.is_file():
        return SqliteCAS(path)
    if path.is_dir():
        return ContentAddressedStore(path)
    raise FileNotFoundError(f"Archive not found: {path}")


def create_cas(
    path: str | Path, fmt: str = "sqlite"
) -> ContentAddressedStore | SqliteCAS:
    """Create a new archive in the specified format. Calls initialize().

    Args:
        path: Output path for the archive.
        fmt: "sqlite" (single file, default) or "directory" (legacy).
    """
    path = Path(path)
    if fmt == "sqlite":
        cas = SqliteCAS(path)
    elif fmt == "directory":
        cas = ContentAddressedStore(path)
    else:
        raise ValueError(f"Unknown format: {fmt}")
    cas.initialize()
    return cas
