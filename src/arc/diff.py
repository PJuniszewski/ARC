"""Archive diff — structural and semantic comparison between two archives."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .cas import ContentAddressedStore
from .loader import load
from .models import Claim, Decision, PolicyRule, ToolDeclaration, WorkflowStep


@dataclass
class DiffResult:
    """Result of comparing two archives."""

    # Structural
    new_blobs: list[str] = field(default_factory=list)
    removed_blobs: list[str] = field(default_factory=list)
    unchanged_blobs: list[str] = field(default_factory=list)

    # Semantic
    new_claims: list[Claim] = field(default_factory=list)
    removed_claims: list[Claim] = field(default_factory=list)
    new_decisions: list[Decision] = field(default_factory=list)
    removed_decisions: list[Decision] = field(default_factory=list)

    # Operational
    new_tools: list[ToolDeclaration] = field(default_factory=list)
    removed_tools: list[ToolDeclaration] = field(default_factory=list)
    new_policies: list[PolicyRule] = field(default_factory=list)
    removed_policies: list[PolicyRule] = field(default_factory=list)
    new_workflow: list[WorkflowStep] = field(default_factory=list)
    removed_workflow: list[WorkflowStep] = field(default_factory=list)

    # Resources
    changed_resources: list[str] = field(default_factory=list)

    # Summary
    blob_reuse_ratio: float = 0.0

    def to_dict(self) -> dict:
        return {
            "structural": {
                "new_blobs": len(self.new_blobs),
                "removed_blobs": len(self.removed_blobs),
                "unchanged_blobs": len(self.unchanged_blobs),
                "blob_reuse_ratio": self.blob_reuse_ratio,
            },
            "semantic": {
                "new_claims": len(self.new_claims),
                "removed_claims": len(self.removed_claims),
                "new_decisions": len(self.new_decisions),
                "removed_decisions": len(self.removed_decisions),
            },
            "operational": {
                "new_tools": len(self.new_tools),
                "removed_tools": len(self.removed_tools),
                "new_policies": len(self.new_policies),
                "removed_policies": len(self.removed_policies),
                "new_workflow": len(self.new_workflow),
                "removed_workflow": len(self.removed_workflow),
            },
            "changed_resources": self.changed_resources,
        }

    def summary(self) -> str:
        lines = [
            "=== ARC Diff Summary ===",
            f"Blobs: +{len(self.new_blobs)} -{len(self.removed_blobs)} ={len(self.unchanged_blobs)}"
            f" (reuse: {self.blob_reuse_ratio:.1%})",
            f"Claims: +{len(self.new_claims)} -{len(self.removed_claims)}",
            f"Decisions: +{len(self.new_decisions)} -{len(self.removed_decisions)}",
            f"Tools: +{len(self.new_tools)} -{len(self.removed_tools)}",
            f"Policies: +{len(self.new_policies)} -{len(self.removed_policies)}",
            f"Workflow: +{len(self.new_workflow)} -{len(self.removed_workflow)}",
        ]
        if self.changed_resources:
            lines.append(f"Changed resources: {', '.join(self.changed_resources)}")
        return "\n".join(lines)


def diff_archives(
    archive_a: str | Path,
    archive_b: str | Path,
) -> DiffResult:
    """Compare two archives structurally and semantically."""
    cas_a = ContentAddressedStore(Path(archive_a))
    cas_b = ContentAddressedStore(Path(archive_b))

    result = DiffResult()

    # Structural diff: blob sets
    blobs_a = set(cas_a.list_blobs())
    blobs_b = set(cas_b.list_blobs())

    result.new_blobs = sorted(blobs_b - blobs_a)
    result.removed_blobs = sorted(blobs_a - blobs_b)
    result.unchanged_blobs = sorted(blobs_a & blobs_b)

    if blobs_a:
        result.blob_reuse_ratio = len(result.unchanged_blobs) / len(blobs_a)

    # Semantic diff: load and compare claims/decisions
    loaded_a = load(archive_a)
    loaded_b = load(archive_b)

    if not loaded_a.rejected and not loaded_b.rejected:
        # Claims diff by text
        claims_a_texts = {c.text for c in loaded_a.claims}
        claims_b_texts = {c.text for c in loaded_b.claims}

        result.new_claims = [c for c in loaded_b.claims if c.text not in claims_a_texts]
        result.removed_claims = [c for c in loaded_a.claims if c.text not in claims_b_texts]

        # Decisions diff by title
        decisions_a_titles = {d.title for d in loaded_a.decisions}
        decisions_b_titles = {d.title for d in loaded_b.decisions}

        result.new_decisions = [d for d in loaded_b.decisions if d.title not in decisions_a_titles]
        result.removed_decisions = [d for d in loaded_a.decisions if d.title not in decisions_b_titles]

        # Tools diff by name
        tools_a_names = {t.name for t in loaded_a.tools}
        tools_b_names = {t.name for t in loaded_b.tools}
        result.new_tools = [t for t in loaded_b.tools if t.name not in tools_a_names]
        result.removed_tools = [t for t in loaded_a.tools if t.name not in tools_b_names]

        # Policies diff by description
        policies_a_descs = {p.description for p in loaded_a.policies}
        policies_b_descs = {p.description for p in loaded_b.policies}
        result.new_policies = [p for p in loaded_b.policies if p.description not in policies_a_descs]
        result.removed_policies = [p for p in loaded_a.policies if p.description not in policies_b_descs]

        # Workflow diff by name
        workflow_a_names = {w.name for w in loaded_a.workflow}
        workflow_b_names = {w.name for w in loaded_b.workflow}
        result.new_workflow = [w for w in loaded_b.workflow if w.name not in workflow_a_names]
        result.removed_workflow = [w for w in loaded_a.workflow if w.name not in workflow_b_names]

        # Find changed resources by comparing text unit content digests
        digest_by_resource_a: dict[str, set[str]] = {}
        for tu in loaded_a.source_units:
            digest_by_resource_a.setdefault(tu.resource_id, set()).add(tu.content_digest)

        digest_by_resource_b: dict[str, set[str]] = {}
        for tu in loaded_b.source_units:
            digest_by_resource_b.setdefault(tu.resource_id, set()).add(tu.content_digest)

        # New or changed resources
        for rid in digest_by_resource_b:
            if rid not in digest_by_resource_a:
                result.changed_resources.append(rid)
            elif digest_by_resource_b[rid] != digest_by_resource_a[rid]:
                result.changed_resources.append(rid)

    return result
