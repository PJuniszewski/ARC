"""Manifest creation, validation, and serialization."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .cas import ContentAddressedStore, sha256_digest
from .models import Layer, Manifest


def build_manifest(
    archive_id: str,
    archive_version: str,
    layers: list[Layer],
    provenance: dict | None = None,
    parent_archive: str | None = None,
) -> Manifest:
    """Build a manifest from layers and metadata."""
    manifest = Manifest(
        archive_id=archive_id,
        archive_version=archive_version,
        created_at=datetime.now(timezone.utc).isoformat(),
        layers=layers,
        provenance=provenance or {},
        compatibility={"requires_loader": ">=0.1.0"},
        parent_archive=parent_archive,
    )
    manifest.root_digest = manifest.compute_root_digest()
    return manifest


def validate_manifest(manifest: Manifest) -> list[str]:
    """Validate manifest schema. Returns list of errors (empty = valid)."""
    errors = []

    if not manifest.schema_version:
        errors.append("Missing schema_version")
    if not manifest.archive_id:
        errors.append("Missing archive_id")
    if not manifest.archive_version:
        errors.append("Missing archive_version")
    if not manifest.created_at:
        errors.append("Missing created_at")
    if not manifest.layers:
        errors.append("No layers defined")

    # Check for dependency cycles
    layer_names = {l.name for l in manifest.layers}
    for layer in manifest.layers:
        for dep in layer.depends_on:
            if dep not in layer_names:
                errors.append(f"Layer '{layer.name}' depends on unknown layer '{dep}'")

    # Simple cycle detection (topological sort)
    if not errors:
        visited: set[str] = set()
        in_stack: set[str] = set()
        deps_map = {l.name: l.depends_on for l in manifest.layers}

        def has_cycle(name: str) -> bool:
            if name in in_stack:
                return True
            if name in visited:
                return False
            visited.add(name)
            in_stack.add(name)
            for dep in deps_map.get(name, []):
                if has_cycle(dep):
                    return True
            in_stack.discard(name)
            return False

        for layer in manifest.layers:
            if has_cycle(layer.name):
                errors.append(f"Dependency cycle detected involving layer '{layer.name}'")
                break

    # Verify root_digest if set
    if manifest.root_digest:
        expected = manifest.compute_root_digest()
        if manifest.root_digest != expected:
            errors.append(f"root_digest mismatch: got {manifest.root_digest}, expected {expected}")

    return errors


def write_manifest_to_cas(manifest: Manifest, cas: ContentAddressedStore) -> str:
    """Write manifest to CAS archive. Returns digest of manifest."""
    return cas.write_manifest(manifest.to_dict())


def read_manifest_from_cas(cas: ContentAddressedStore) -> Manifest | None:
    """Read manifest from CAS archive."""
    data = cas.read_manifest()
    if data is None:
        return None
    return Manifest.from_dict(data)
