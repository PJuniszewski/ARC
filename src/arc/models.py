"""Data models for ARC Archive — Resource, TextUnit, Claim, Decision, Layer, Manifest."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _generate_id(seed: str = "") -> str:
    """Generate an ID. If seed is provided, ID is deterministic (content-based)."""
    if seed:
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return uuid.uuid4().hex[:16]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class EvidencePointer:
    """Link from a Claim/Decision to a supporting source unit."""

    source_unit_id: str
    span: Optional[tuple[int, int]] = None  # (start_line, end_line)
    weight: float = 1.0

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"source_unit_id": self.source_unit_id, "weight": self.weight}
        if self.span is not None:
            d["span"] = list(self.span)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> EvidencePointer:
        span = tuple(d["span"]) if d.get("span") else None
        return cls(
            source_unit_id=d.get("source_unit_id", ""),
            span=span,
            weight=d.get("weight", 1.0),
        )


@dataclass
class Resource:
    """A source object (file, document, ticket) ingested into the archive."""

    id: str = field(default_factory=_generate_id)
    kind: str = "file"  # file | document | ticket
    locator: str = ""  # path or URI
    content_digest: str = ""  # sha256 of raw content
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Resource:
        known = {"id", "kind", "locator", "content_digest", "metadata"}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class TextUnit:
    """An addressable chunk derived from a Resource with provenance."""

    id: str = field(default_factory=_generate_id)
    resource_id: str = ""
    kind: str = "section"  # section | function | paragraph | frontmatter
    content: str = ""
    span: tuple[int, int] = (0, 0)  # (start_line, end_line)
    content_digest: str = ""

    def __post_init__(self):
        if not self.content_digest and self.content:
            self.content_digest = _sha256(self.content.encode("utf-8"))
        # Make ID deterministic based on content + resource
        if self.content and self.resource_id:
            self.id = _generate_id(f"tu:{self.resource_id}:{self.content_digest}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "resource_id": self.resource_id,
            "kind": self.kind,
            "content": self.content,
            "span": list(self.span),
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TextUnit:
        d = dict(d)
        d["span"] = tuple(d.get("span", [0, 0]))
        # Filter to known fields to tolerate future schema additions
        known = {"id", "resource_id", "kind", "content", "span", "content_digest"}
        d = {k: v for k, v in d.items() if k in known}
        return cls(**d)


CLAIM_STATUSES = {"observed", "derived", "verified", "deprecated", "contested"}


@dataclass
class Claim:
    """An atomic assertion extracted from source units."""

    id: str = field(default_factory=_generate_id)
    text: str = ""
    kind: str = "fact"  # fact | assertion | requirement | definition
    evidence: list[EvidencePointer] = field(default_factory=list)
    confidence: float = 1.0
    status: str = "observed"  # observed | derived | verified | deprecated | contested
    derived_from: Optional[str] = None  # source_unit_id for simple cases

    def __post_init__(self):
        if self.status not in CLAIM_STATUSES:
            raise ValueError(f"Invalid claim status: {self.status}")

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "evidence": [e.to_dict() for e in self.evidence],
            "confidence": self.confidence,
            "status": self.status,
        }
        if self.derived_from:
            d["derived_from"] = self.derived_from
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Claim:
        d = dict(d)
        d["evidence"] = [EvidencePointer.from_dict(e) for e in d.get("evidence", [])]
        return cls(**d)


DECISION_STATUSES = {"proposed", "accepted", "superseded", "rejected"}


@dataclass
class Decision:
    """A structured record of rationale, options, and chosen path."""

    id: str = field(default_factory=_generate_id)
    title: str = ""
    context: str = ""
    options: list[str] = field(default_factory=list)
    decision: str = ""
    consequences: list[str] = field(default_factory=list)
    evidence: list[EvidencePointer] = field(default_factory=list)
    status: str = "accepted"  # proposed | accepted | superseded | rejected

    def __post_init__(self):
        if self.status not in DECISION_STATUSES:
            raise ValueError(f"Invalid decision status: {self.status}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "context": self.context,
            "options": self.options,
            "decision": self.decision,
            "consequences": self.consequences,
            "evidence": [e.to_dict() for e in self.evidence],
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Decision:
        d = dict(d)
        d["evidence"] = [EvidencePointer.from_dict(e) for e in d.get("evidence", [])]
        return cls(**d)


TOOL_STATUSES = {"active", "deprecated", "experimental"}


@dataclass
class ToolDeclaration:
    """A tool or capability available to an agent."""

    id: str = field(default_factory=_generate_id)
    name: str = ""
    description: str = ""
    parameters: list[dict] = field(default_factory=list)
    returns: str = ""
    constraints: list[str] = field(default_factory=list)
    source_ref: str = ""
    status: str = "active"

    def __post_init__(self):
        if self.status not in TOOL_STATUSES:
            raise ValueError(f"Invalid tool status: {self.status}")
        if self.name:
            self.id = _generate_id(f"tool:{self.name}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
            "constraints": self.constraints,
            "source_ref": self.source_ref,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ToolDeclaration:
        known = {"id", "name", "description", "parameters", "returns", "constraints", "source_ref", "status"}
        return cls(**{k: v for k, v in d.items() if k in known})


POLICY_EFFECTS = {"allow", "deny", "require_approval"}


@dataclass
class PolicyRule:
    """A policy constraint governing agent behavior."""

    id: str = field(default_factory=_generate_id)
    scope: str = ""
    effect: str = "deny"
    conditions: list[str] = field(default_factory=list)
    priority: int = 0
    description: str = ""
    source_ref: str = ""

    def __post_init__(self):
        if self.effect not in POLICY_EFFECTS:
            raise ValueError(f"Invalid policy effect: {self.effect}")
        if self.description:
            self.id = _generate_id(f"policy:{self.scope}:{self.description}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scope": self.scope,
            "effect": self.effect,
            "conditions": self.conditions,
            "priority": self.priority,
            "description": self.description,
            "source_ref": self.source_ref,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PolicyRule:
        known = {"id", "scope", "effect", "conditions", "priority", "description", "source_ref"}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class WorkflowStep:
    """A step in an agent workflow — agent, task, or config."""

    id: str = field(default_factory=_generate_id)
    name: str = ""
    kind: str = "task"
    description: str = ""
    agent_ref: str = ""
    depends_on: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    expected_output: str = ""
    source_ref: str = ""

    def __post_init__(self):
        if self.name:
            self.id = _generate_id(f"workflow:{self.name}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "agent_ref": self.agent_ref,
            "depends_on": self.depends_on,
            "tools": self.tools,
            "config": self.config,
            "expected_output": self.expected_output,
            "source_ref": self.source_ref,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WorkflowStep:
        known = {
            "id", "name", "kind", "description", "agent_ref", "depends_on",
            "tools", "config", "expected_output", "source_ref",
        }
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Layer:
    """A named layer in the archive manifest."""

    name: str
    type: str  # semantic.source_units | semantic.claims | semantic.decisions | ...
    digest: str
    media_type: str = "application/arc+json"
    required: bool = True
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Layer:
        known = {"name", "type", "digest", "media_type", "required", "depends_on"}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Manifest:
    """Root manifest describing the archive composition."""

    schema_version: str = "0.1.0"
    archive_id: str = ""
    archive_version: str = "0.1.0"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    root_digest: str = ""
    layers: list[Layer] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    compatibility: dict = field(default_factory=dict)
    parent_archive: Optional[str] = None  # digest of parent for incremental builds

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "archive_id": self.archive_id,
            "archive_version": self.archive_version,
            "created_at": self.created_at,
            "root_digest": self.root_digest,
            "layers": [l.to_dict() for l in self.layers],
            "provenance": self.provenance,
            "compatibility": self.compatibility,
            "parent_archive": self.parent_archive,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Manifest:
        d = dict(d)
        d["layers"] = [Layer.from_dict(l) for l in d.get("layers", [])]
        return cls(**d)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, data: str) -> Manifest:
        return cls.from_dict(json.loads(data))

    def compute_root_digest(self) -> str:
        """Compute root digest from manifest content (excluding root_digest itself)."""
        d = self.to_dict()
        d.pop("root_digest", None)
        content = json.dumps(d, sort_keys=True).encode("utf-8")
        return _sha256(content)
