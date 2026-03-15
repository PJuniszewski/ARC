"""Provenance and attestation model for ARC archives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import __version__


@dataclass
class BuildProvenance:
    """Records who/what built the archive and from what sources."""

    builder_version: str = __version__
    build_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_inventory: list[dict[str, str]] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    builder_id: str = "arc-builder"

    def add_source(self, locator: str, digest: str, kind: str = "file") -> None:
        self.source_inventory.append({
            "locator": locator,
            "digest": digest,
            "kind": kind,
        })

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> BuildProvenance:
        return cls(**d)
