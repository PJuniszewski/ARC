"""Create — build a .arc directly from typed claims (no source directory needed)."""

from __future__ import annotations

from pathlib import Path

from .assembly import assemble_archive
from .cas import ContentAddressedStore
from .models import Claim, Decision, Manifest, Resource, TextUnit, ToolDeclaration, PolicyRule, WorkflowStep


def create_archive(
    output_path: str | Path,
    claims: list[Claim],
    archive_id: str = "arc://agent-output",
    archive_version: str = "1.0.0",
    decisions: list[Decision] | None = None,
    resources: list[Resource] | None = None,
    source_units: list[TextUnit] | None = None,
    tools: list[ToolDeclaration] | None = None,
    policies: list[PolicyRule] | None = None,
    workflow: list[WorkflowStep] | None = None,
    source: str | None = None,
    parent_archive: str | None = None,
) -> Manifest:
    """Create a .arc archive directly from a list of claims.

    This is the primary API for agents producing artifacts. No source directory
    needed — just provide claims with their types and evidence.

    If ``source`` is provided, all claims without an explicit source get stamped
    with this value.

    Args:
        output_path: Where to write the .arc directory.
        claims: List of Claim objects to include.
        archive_id: Archive identifier.
        archive_version: Semantic version.
        decisions: Optional structured Decision objects.
        resources: Optional Resource objects for evidence tracing.
        source_units: Optional TextUnit objects for evidence tracing.
        tools: Optional tool declarations.
        policies: Optional policy rules.
        workflow: Optional workflow steps.
        source: Default source label for claims missing one.
        parent_archive: Root digest of parent archive (for incremental context).

    Returns:
        The manifest of the created archive.
    """
    # Stamp source on copies to avoid mutating caller's objects
    if source:
        import copy
        claims = [copy.copy(c) for c in claims]
        for c in claims:
            if c.source == "builder":
                c.source = source
        if decisions:
            decisions = [copy.copy(d) for d in decisions]
            for d in decisions:
                if d.source == "builder":
                    d.source = source

    out = Path(output_path)
    cas = ContentAddressedStore(out)
    cas.initialize()

    return assemble_archive(
        cas=cas,
        claims=claims,
        resources=resources,
        source_units=source_units,
        decisions=decisions,
        tools=tools,
        policies=policies,
        workflow=workflow,
        archive_id=archive_id,
        archive_version=archive_version,
        provenance={"builder_id": "arc-create", "source": source or "unknown"},
        parent_archive=parent_archive,
    )
