"""Snapshot — lightweight .arc from the last N claims of an existing archive."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .assembly import assemble_archive, validate_evidence
from .cas import create_cas
from .models import Manifest

logger = logging.getLogger(__name__)


def snapshot(
    source_archive: str | Path,
    output_path: str | Path,
    last: int = 10,
    claim_type: Optional[str] = None,
    source: Optional[str] = None,
) -> Manifest:
    """Build a lightweight snapshot .arc from the last N claims of an existing archive.

    The snapshot is a valid .arc: same format, same Merkle integrity, loadable
    by ``arc load``. It contains only the selected claims, their referenced
    source units, and a minimal embeddings index.

    Args:
        source_archive: Path to the source .arc to snapshot from.
        output_path: Where to write the snapshot .arc.
        last: Number of most-recent claims to include (by timestamp, then list order).
        claim_type: Optional filter — only snapshot claims of this type.
        source: Optional filter — only snapshot claims from this source.

    Returns:
        The manifest of the snapshot archive.
    """
    from .loader import load

    loaded = load(str(source_archive))
    if loaded.rejected:
        raise ValueError(f"Cannot snapshot: {loaded.reason}")

    # Filter claims
    claims = loaded.claims
    if claim_type:
        claims = [c for c in claims if c.claim_type == claim_type]
    if source:
        claims = [c for c in claims if c.source == source]

    # Sort by timestamp (non-empty timestamps first, then lexicographic), take last N
    claims = sorted(claims, key=lambda c: (c.timestamp or "", c.id))
    claims = claims[-last:]

    # Filter decisions
    decisions = loaded.decisions
    if source:
        decisions = [d for d in decisions if d.source == source]
    decisions = decisions[-last:]

    # Collect referenced source units
    needed_su_ids = set()
    for c in claims:
        for ep in c.evidence:
            needed_su_ids.add(ep.source_unit_id)
        if c.derived_from:
            needed_su_ids.add(c.derived_from)
    for d in decisions:
        for ep in d.evidence:
            needed_su_ids.add(ep.source_unit_id)

    su_by_id = {tu.id: tu for tu in loaded.source_units}
    source_units = [su_by_id[sid] for sid in needed_su_ids if sid in su_by_id]

    # Collect referenced resources
    needed_res_ids = {tu.resource_id for tu in source_units}
    res_by_id = {r.id: r for r in loaded.resources}
    resources = [res_by_id[rid] for rid in needed_res_ids if rid in res_by_id]

    # Validate evidence pointers
    actual_su_ids = {tu.id for tu in source_units}
    warnings = validate_evidence(claims, actual_su_ids)
    for w in warnings:
        logger.warning("snapshot: %s", w)

    # Assemble
    out = Path(output_path)
    cas = create_cas(out)

    return assemble_archive(
        cas=cas,
        claims=claims,
        resources=resources,
        source_units=source_units,
        decisions=decisions,
        archive_id=f"{loaded.manifest.archive_id}/snapshot",
        archive_version=loaded.manifest.archive_version,
        provenance={
            "builder_id": "arc-snapshot",
            "source_archive": str(source_archive),
            "last": last,
        },
        parent_archive=loaded.manifest.root_digest,
    )
