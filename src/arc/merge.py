"""Merge — combine two .arc artifacts into one."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .assembly import assemble_archive, validate_evidence
from .cas import ContentAddressedStore
from .embeddings import get_embedder
from .models import (
    Claim, Decision, Manifest, PolicyRule,
    Resource, TextUnit, ToolDeclaration, WorkflowStep, _generate_id,
)

logger = logging.getLogger(__name__)

CONFLICT_SIMILARITY_THRESHOLD = 0.45


def _cosine_similarity(a, b) -> float:
    """Cosine similarity between two vectors."""
    import numpy as np
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def merge(
    archive_a: str | Path,
    archive_b: str | Path,
    output_path: str | Path,
) -> tuple["MergeResult", Manifest]:
    """Merge two .arc artifacts into a combined archive.

    Rules:
    - Observations from different sources coexist (both valid).
    - Duplicate claims (same text) are deduplicated.
    - Conflicting decisions from different sources are flagged as CONFLICT claims.
    - Resources, source units, and operational layers are merged with dedup by ID.

    Returns:
        Tuple of (MergeResult with stats, manifest of merged archive).
    """
    from .loader import load

    a = load(str(archive_a))
    b = load(str(archive_b))
    if a.rejected:
        raise ValueError(f"Cannot load archive A: {a.reason}")
    if b.rejected:
        raise ValueError(f"Cannot load archive B: {b.reason}")

    # --- Merge resources (dedup by id) ---
    res_by_id: dict[str, Resource] = {}
    for r in a.resources + b.resources:
        res_by_id[r.id] = r
    resources = list(res_by_id.values())

    # --- Merge source units (dedup by id) ---
    su_by_id: dict[str, TextUnit] = {}
    for tu in a.source_units + b.source_units:
        su_by_id[tu.id] = tu
    source_units = list(su_by_id.values())

    # --- Merge claims (dedup by text) ---
    seen_texts: dict[str, Claim] = {}
    id_remap: dict[str, str] = {}  # dropped_id → surviving_id
    decisions_a: list[Claim] = []
    decisions_b: list[Claim] = []
    merged_claims: list[Claim] = []

    for c in a.claims:
        key = c.text.strip().lower()
        if key not in seen_texts:
            seen_texts[key] = c
            merged_claims.append(c)
            if c.claim_type == "decision":
                decisions_a.append(c)

    duplicates = 0
    for c in b.claims:
        key = c.text.strip().lower()
        if key in seen_texts:
            duplicates += 1
            id_remap[c.id] = seen_texts[key].id
        else:
            seen_texts[key] = c
            merged_claims.append(c)
            if c.claim_type == "decision":
                decisions_b.append(c)

    # Rewrite references that point to deduped (dropped) claim IDs
    if id_remap:
        for c in merged_claims:
            c.references = [id_remap.get(r, r) for r in c.references]

    # --- Detect conflicting decisions using embeddings ---
    conflicts: list[Claim] = []
    merge_ts = datetime.now(timezone.utc).isoformat()

    if decisions_a and decisions_b:
        # Fit on all merged claims for better IDF estimates, not just decisions
        all_texts = [c.text for c in merged_claims]
        embedder = get_embedder(dimensions=256, force_tfidf=True)
        embedder.fit(all_texts)
        vecs_a = [embedder.embed(d.text) for d in decisions_a]
        vecs_b = [embedder.embed(d.text) for d in decisions_b]

        for i, da in enumerate(decisions_a):
            for j, db in enumerate(decisions_b):
                if da.source == db.source:
                    continue
                sim = _cosine_similarity(vecs_a[i], vecs_b[j])
                if sim >= CONFLICT_SIMILARITY_THRESHOLD:
                    conflict = Claim(
                        id=_generate_id(f"conflict:{da.id}:{db.id}"),
                        text=f"Conflicting decisions: [{da.source}] {da.text} vs [{db.source}] {db.text}",
                        kind="assertion",
                        claim_type="conflict",
                        source="arc-merge",
                        timestamp=merge_ts,
                        confidence=round(sim, 3),
                        status="contested",
                        references=[da.id, db.id],
                    )
                    conflicts.append(conflict)

    merged_claims.extend(conflicts)

    # --- Merge rich Decision objects (dedup by title) ---
    dec_by_title: dict[str, Decision] = {}
    for d in a.decisions + b.decisions:
        dec_by_title[d.title] = d
    decisions = list(dec_by_title.values())

    # --- Merge operational layers (dedup by id/name) ---
    tools = _dedup_by_attr(a.tools + b.tools, "name")
    policies = _dedup_by_attr(a.policies + b.policies, "description")
    workflow = _dedup_by_attr(a.workflow + b.workflow, "name")

    # --- Validate evidence ---
    actual_su_ids = set(su_by_id.keys())
    warnings = validate_evidence(merged_claims, actual_su_ids)
    for w in warnings:
        logger.warning("merge: %s", w)

    # --- Assemble ---
    out = Path(output_path)
    cas = ContentAddressedStore(out)
    cas.initialize()

    manifest = assemble_archive(
        cas=cas,
        claims=merged_claims,
        resources=resources,
        source_units=source_units,
        decisions=decisions,
        tools=tools,
        policies=policies,
        workflow=workflow,
        archive_id=f"{a.manifest.archive_id}+{b.manifest.archive_id}",
        archive_version="1.0.0",
        provenance={
            "builder_id": "arc-merge",
            "source_a": str(archive_a),
            "source_b": str(archive_b),
        },
    )

    result = MergeResult(
        claims_a=len(a.claims),
        claims_b=len(b.claims),
        merged_claims=len(merged_claims),
        duplicates_removed=duplicates,
        conflicts_detected=len(conflicts),
        conflict_claims=conflicts,
    )
    return result, manifest


def _dedup_by_attr(items: list, attr: str) -> list:
    """Deduplicate a list of objects by a named attribute.

    Items with empty/missing keys are always kept (no dedup key to match on).
    """
    seen: dict[str, object] = {}
    result: list = []
    for item in items:
        key = getattr(item, attr, "")
        if not key:
            result.append(item)  # keep items without dedup key
        elif key not in seen:
            seen[key] = item
            result.append(item)
    return result


@dataclass
class MergeResult:
    """Statistics from a merge operation."""

    claims_a: int = 0
    claims_b: int = 0
    merged_claims: int = 0
    duplicates_removed: int = 0
    conflicts_detected: int = 0
    conflict_claims: list[Claim] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Merge complete:",
            f"  Archive A: {self.claims_a} claims",
            f"  Archive B: {self.claims_b} claims",
            f"  Merged:    {self.merged_claims} claims",
            f"  Deduped:   {self.duplicates_removed}",
            f"  Conflicts: {self.conflicts_detected}",
        ]
        if self.conflict_claims:
            lines.append("")
            lines.append("  Conflicts:")
            for c in self.conflict_claims:
                lines.append(f"    - {c.text}")
        return "\n".join(lines)
