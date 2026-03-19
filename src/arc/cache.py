"""Lightweight file-system cache for retrieval artifacts.

Content-addressed by source directory hash. Caches chunking results
and embedding vectors to avoid recomputation on repeated queries.

Off by default. Degrades gracefully on cache miss.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CacheConfig:
    """Configuration for the retrieval cache."""

    enabled: bool = False
    cache_dir: Path = Path(".arc_cache")


class RetrievalCache:
    """File-system cache for chunking and embedding artifacts.

    Layout:
        .arc_cache/
            chunks/{source_hash}.json
            embeddings/{chunks_hash}.json
    """

    def __init__(self, config: CacheConfig | None = None):
        self.config = config or CacheConfig()
        if self.config.enabled:
            self.config.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.config.cache_dir / "chunks").mkdir(exist_ok=True)
            (self.config.cache_dir / "embeddings").mkdir(exist_ok=True)

    def get_chunks(self, source_hash: str) -> Optional[tuple[list, list]]:
        """Load cached chunk data. Returns (resources_dicts, text_units_dicts) or None."""
        if not self.config.enabled:
            return None
        path = self.config.cache_dir / "chunks" / f"{source_hash}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return data["resources"], data["text_units"]
        except (json.JSONDecodeError, KeyError):
            return None

    def put_chunks(
        self, source_hash: str, resources: list[dict], text_units: list[dict],
    ) -> None:
        """Cache chunk data."""
        if not self.config.enabled:
            return
        path = self.config.cache_dir / "chunks" / f"{source_hash}.json"
        data = {"resources": resources, "text_units": text_units}
        path.write_text(json.dumps(data))

    def get_embeddings(self, chunks_hash: str) -> Optional[dict]:
        """Load cached embedding store dict, or None on miss."""
        if not self.config.enabled:
            return None
        path = self.config.cache_dir / "embeddings" / f"{chunks_hash}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    def put_embeddings(self, chunks_hash: str, store_dict: dict) -> None:
        """Cache embedding store dict."""
        if not self.config.enabled:
            return
        path = self.config.cache_dir / "embeddings" / f"{chunks_hash}.json"
        path.write_text(json.dumps(store_dict))

    @staticmethod
    def hash_directory(source_dir: Path) -> str:
        """Compute a stable hash of a source directory.

        Hashes sorted file paths + sizes (not contents, for speed).
        """
        hasher = hashlib.sha256()
        try:
            entries = sorted(source_dir.rglob("*"))
            for entry in entries:
                if entry.is_file():
                    rel = str(entry.relative_to(source_dir))
                    size = entry.stat().st_size
                    hasher.update(f"{rel}:{size}\n".encode())
        except OSError:
            hasher.update(str(source_dir).encode())
        return hasher.hexdigest()[:16]
