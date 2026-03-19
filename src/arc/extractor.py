"""Claim, Decision, and Operational extraction from text and config files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from .models import (
    Claim,
    Decision,
    EvidencePointer,
    PolicyRule,
    Resource,
    TextUnit,
    ToolDeclaration,
    WorkflowStep,
    _generate_id,
)

# Patterns that indicate assertions / claims
CLAIM_PATTERNS = [
    re.compile(r"(?:^|\.\s+)([A-Z][^.]*?\b(?:is|are|was|were|has|have|should|must|requires?|provides?|supports?|enables?|ensures?|prevents?|defines?|specifies?|implements?|uses?|contains?)\b[^.]+\.)", re.MULTILINE),
    re.compile(r"(?:^|\.\s+)([A-Z][^.]*?\b(?:can|will|shall|may|cannot|should not|must not)\b[^.]+\.)", re.MULTILINE),
    re.compile(r"^\s*[-*]\s+\*\*([^*]+)\*\*[:\s]+(.+)$", re.MULTILINE),  # **Bold**: description
    re.compile(r"^\s*\d+\.\s+\*\*([^*]+)\*\*[:\s]+(.+)$", re.MULTILINE),  # 1. **Bold**: description
    re.compile(r"^\s*[-*]\s+(.{20,})$", re.MULTILINE),  # Bullet points with substance
]

# Patterns for ADR-style decisions
DECISION_SECTION_PATTERNS = {
    "context": re.compile(r"(?:^##\s*(?:Context|Background|Problem)\s*\n)(.*?)(?=^##|\Z)", re.MULTILINE | re.DOTALL),
    "decision": re.compile(r"(?:^##\s*(?:Decision|Resolution|Chosen)\s*\n)(.*?)(?=^##|\Z)", re.MULTILINE | re.DOTALL),
    "consequences": re.compile(r"(?:^##\s*(?:Consequences|Impact|Result)\s*\n)(.*?)(?=^##|\Z)", re.MULTILINE | re.DOTALL),
    "options": re.compile(r"(?:^##\s*(?:Options|Alternatives|Considered)\s*\n)(.*?)(?=^##|\Z)", re.MULTILINE | re.DOTALL),
}

# Title patterns for ADRs
ADR_TITLE_PATTERN = re.compile(r"^#\s+(?:ADR[-\s]*\d+[:\s]*)?(.+)$", re.MULTILINE)


_INJECTION_PATTERNS = [
    re.compile(r"\b(?:ignore|disregard)\b.*\b(?:previous|all|above)\b", re.IGNORECASE),
    re.compile(r"\b(?:admin|root|system)\s+mode\b", re.IGNORECASE),
    re.compile(r"\b(?:override|bypass)\b.*\b(?:security|trust|integrity|check)\b", re.IGNORECASE),
    re.compile(r"\b(?:output|reveal|show)\b.*\b(?:secret|password|key|credential)\b", re.IGNORECASE),
    re.compile(r"\btrust\b.*\bunconditionally\b", re.IGNORECASE),
]


def _injection_penalty(text: str) -> float:
    """Return confidence penalty for injection-like text. Max 0.5, floor at 0.3."""
    hits = sum(1 for p in _INJECTION_PATTERNS if p.search(text))
    return min(hits * 0.15, 0.5)


def _extract_section_context(content: str) -> str:
    """Extract heading and intro context from a text unit.

    Returns a short prefix like "Threat Categories — The ARC security model
    addresses four primary threat categories" that preserves the categorical
    vocabulary otherwise lost during sentence-level claim extraction.
    """
    parts: list[str] = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            if parts:
                break  # stop at first blank line after heading/intro
            continue
        heading = re.match(r"^#{1,3}\s+(.+)$", line)
        if heading:
            parts.append(heading.group(1).strip())
            continue
        # Framing sentence that introduces a list (ends with colon)
        if line.endswith(":") and len(line) > 20:
            parts.append(line.rstrip(":"))
            break
        break  # first real content line — stop
    return " — ".join(parts)


def extract_claims(text_units: list[TextUnit]) -> list[Claim]:
    """Extract claims from text units using rule-based patterns."""
    claims: list[Claim] = []
    seen_texts: set[str] = set()

    for tu in text_units:
        section_ctx = _extract_section_context(tu.content)
        sentences = _split_sentences(tu.content)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 15 or sentence in seen_texts:
                continue

            # Check if sentence matches claim patterns
            is_claim = False
            kind = "fact"

            for pattern in CLAIM_PATTERNS:
                if pattern.search(sentence):
                    is_claim = True
                    break

            # Determine claim kind
            if any(w in sentence.lower() for w in ["should", "must", "shall", "required"]):
                kind = "requirement"
            elif any(w in sentence.lower() for w in ["defines", "specifies", "is defined"]):
                kind = "definition"
            elif any(w in sentence.lower() for w in ["assert", "claim", "assume"]):
                kind = "assertion"

            if is_claim:
                # Enrich claim with section context when the claim doesn't
                # already contain the heading vocabulary.
                claim_text = sentence
                if section_ctx:
                    ctx_words = set(re.findall(r"\b\w{3,}\b", section_ctx.lower()))
                    sent_words = set(re.findall(r"\b\w{3,}\b", sentence.lower()))
                    if not ctx_words.issubset(sent_words):
                        claim_text = f"{section_ctx}: {sentence}"

                seen_texts.add(sentence)
                claim_id = _generate_id(f"claim:{sentence}")
                penalty = _injection_penalty(claim_text)
                claims.append(
                    Claim(
                        id=claim_id,
                        text=claim_text,
                        kind=kind,
                        evidence=[
                            EvidencePointer(
                                source_unit_id=tu.id,
                                span=tu.span,
                                weight=1.0,
                            )
                        ],
                        confidence=0.8 - penalty,
                        status="contested" if penalty > 0 else "observed",
                        derived_from=tu.id,
                    )
                )

    return claims


def extract_decisions(text_units: list[TextUnit]) -> list[Decision]:
    """Extract ADR-style decisions from text units."""
    decisions: list[Decision] = []

    # Group text units by resource
    by_resource: dict[str, list[TextUnit]] = {}
    for tu in text_units:
        by_resource.setdefault(tu.resource_id, []).append(tu)

    for resource_id, units in by_resource.items():
        full_text = "\n\n".join(tu.content for tu in units)

        # Check if this looks like a decision document
        title_match = ADR_TITLE_PATTERN.search(full_text)
        if not title_match:
            continue

        title = title_match.group(1).strip()

        # Extract sections
        context = _extract_section(full_text, "context")
        decision_text = _extract_section(full_text, "decision")
        consequences_text = _extract_section(full_text, "consequences")
        options_text = _extract_section(full_text, "options")

        # Need at least a title and one section to count as a decision
        if not (context or decision_text):
            continue

        # Parse options and consequences as lists
        options = _parse_list_items(options_text) if options_text else []
        consequences = _parse_list_items(consequences_text) if consequences_text else []

        evidence = [
            EvidencePointer(source_unit_id=tu.id, span=tu.span) for tu in units
        ]

        decisions.append(
            Decision(
                id=_generate_id(f"decision:{title}"),
                title=title,
                context=context or "",
                options=options,
                decision=decision_text or "",
                consequences=consequences,
                evidence=evidence,
                status="accepted",
            )
        )

    return decisions


def _extract_section(text: str, section_name: str) -> Optional[str]:
    """Extract a named section from markdown text."""
    pattern = DECISION_SECTION_PATTERNS.get(section_name)
    if pattern:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _parse_list_items(text: str) -> list[str]:
    """Parse markdown list items from text."""
    items = []
    for line in text.split("\n"):
        line = line.strip()
        match = re.match(r"^[-*]\s+(.+)$", line)
        if match:
            items.append(match.group(1).strip())
        elif line and not line.startswith("#"):
            # Non-list paragraph as single item
            if line not in items:
                items.append(line)
    return items


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences. Simple rule-based splitter."""
    # Remove markdown headers for cleaner sentences
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    # Also split on newlines that start new paragraphs
    result = []
    for s in sentences:
        parts = re.split(r'\n\s*\n', s)
        result.extend(parts)
    return [s.strip() for s in result if s.strip()]


# ---------------------------------------------------------------------------
# Operational extraction: tools, policies, workflow
# ---------------------------------------------------------------------------


def _parse_yaml_file(resource: Resource, source_dir: Path) -> Optional[dict]:
    """Safely load YAML from a resource. Returns None for non-YAML or parse errors."""
    if resource.metadata.get("extension") not in (".yaml", ".yml"):
        return None
    fpath = source_dir / resource.locator
    if not fpath.exists():
        return None
    try:
        data = yaml.safe_load(fpath.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, dict):
            return data
    except (yaml.YAMLError, OSError):
        pass
    return None


def extract_tools(
    text_units: list[TextUnit],
    resources: list[Resource],
    source_dir: str | Path,
) -> list[ToolDeclaration]:
    """Extract tool declarations from YAML configs and markdown."""
    source_dir = Path(source_dir)
    tools: list[ToolDeclaration] = []
    seen_names: set[str] = set()

    # Primary: parse YAML files for tool references
    for resource in resources:
        data = _parse_yaml_file(resource, source_dir)
        if data is None:
            continue

        # CrewAI-style: top-level agent defs with tools lists
        for key, value in data.items():
            if isinstance(value, dict) and "tools" in value:
                tool_list = value["tools"]
                if isinstance(tool_list, list):
                    for tool_name in tool_list:
                        if isinstance(tool_name, str) and tool_name not in seen_names:
                            seen_names.add(tool_name)
                            tools.append(ToolDeclaration(
                                name=tool_name,
                                description=f"Tool used by {key}",
                                source_ref=resource.id,
                            ))

        # Top-level "tools:" key with list of dicts
        if "tools" in data and isinstance(data["tools"], list):
            for entry in data["tools"]:
                if isinstance(entry, str):
                    if entry not in seen_names:
                        seen_names.add(entry)
                        tools.append(ToolDeclaration(
                            name=entry,
                            source_ref=resource.id,
                        ))
                elif isinstance(entry, dict) and "name" in entry:
                    name = entry["name"]
                    if name not in seen_names:
                        seen_names.add(name)
                        tools.append(ToolDeclaration(
                            name=name,
                            description=entry.get("description", ""),
                            parameters=entry.get("parameters", []),
                            returns=entry.get("returns", ""),
                            source_ref=resource.id,
                        ))

    # Markdown fallback: match "- **tool_name**: description" within ## Tools sections
    tools_section_pattern = re.compile(
        r"^##\s+Tools?\s*\n(.*?)(?=^##|\Z)", re.MULTILINE | re.DOTALL
    )
    tool_md_pattern = re.compile(r"^\s*[-*]\s+\*\*(\w+)\*\*\s*[-—:]\s*(.+)$", re.MULTILINE)
    for tu in text_units:
        for section_match in tools_section_pattern.finditer(tu.content):
            section_text = section_match.group(1)
            for m in tool_md_pattern.finditer(section_text):
                name = m.group(1)
                if name not in seen_names:
                    seen_names.add(name)
                    tools.append(ToolDeclaration(
                        name=name,
                        description=m.group(2).strip(),
                        source_ref=tu.resource_id,
                    ))

    return tools


def extract_policies(
    text_units: list[TextUnit],
    resources: list[Resource],
    source_dir: str | Path,
) -> list[PolicyRule]:
    """Extract policy rules from YAML configs and markdown conventions."""
    source_dir = Path(source_dir)
    policies: list[PolicyRule] = []
    seen: set[str] = set()

    # Primary: parse YAML for permissions/policy/constraints keys
    for resource in resources:
        data = _parse_yaml_file(resource, source_dir)
        if data is None:
            continue

        for key in ("permissions", "policy", "constraints"):
            if key in data and isinstance(data[key], list):
                for entry in data[key]:
                    if isinstance(entry, str) and entry not in seen:
                        seen.add(entry)
                        policies.append(PolicyRule(
                            scope="*",
                            effect="deny",
                            description=entry,
                            source_ref=resource.id,
                        ))
                    elif isinstance(entry, dict):
                        desc = entry.get("description", entry.get("rule", ""))
                        if desc and desc not in seen:
                            seen.add(desc)
                            policies.append(PolicyRule(
                                scope=entry.get("scope", "*"),
                                effect=entry.get("effect", "deny"),
                                description=desc,
                                priority=entry.get("priority", 0),
                                source_ref=resource.id,
                            ))

    # Markdown: extract rules from "## Conventions" or "## Security" sections
    convention_pattern = re.compile(
        r"^##\s+(?:Conventions|Security|Constraints|Rules|Permissions)\s*\n(.*?)(?=^##|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for tu in text_units:
        for section_match in convention_pattern.finditer(tu.content):
            section_text = section_match.group(1)
            for line in section_text.split("\n"):
                line = line.strip()
                rule_match = re.match(r"^[-*]\s+(.{15,})$", line)
                if rule_match:
                    rule_text = rule_match.group(1).strip()
                    if rule_text not in seen:
                        seen.add(rule_text)
                        # Determine effect from keywords
                        effect = "deny"
                        lower = rule_text.lower()
                        if any(w in lower for w in ["must", "require", "should", "always"]):
                            effect = "require_approval"
                        if any(w in lower for w in ["never", "do not", "don't", "forbidden"]):
                            effect = "deny"
                        if any(w in lower for w in ["may", "can", "allowed", "permit"]):
                            effect = "allow"
                        policies.append(PolicyRule(
                            scope="*",
                            effect=effect,
                            description=rule_text,
                            source_ref=tu.resource_id,
                        ))

    return policies


def extract_workflow(
    text_units: list[TextUnit],
    resources: list[Resource],
    source_dir: str | Path,
) -> list[WorkflowStep]:
    """Extract workflow steps from YAML agent/task definitions."""
    source_dir = Path(source_dir)
    steps: list[WorkflowStep] = []
    seen_names: set[str] = set()

    for resource in resources:
        data = _parse_yaml_file(resource, source_dir)
        if data is None:
            continue

        for key, value in data.items():
            if not isinstance(value, dict):
                continue

            # Agent definitions: have role + goal
            if "role" in value and "goal" in value:
                if key not in seen_names:
                    seen_names.add(key)
                    tools = value.get("tools", [])
                    if not isinstance(tools, list):
                        tools = []
                    config = {}
                    if "max_iterations" in value:
                        config["max_iterations"] = value["max_iterations"]
                    if "verbose" in value:
                        config["verbose"] = value["verbose"]
                    steps.append(WorkflowStep(
                        name=key,
                        kind="agent",
                        description=f"{value['role']}: {value['goal']}",
                        tools=[str(t) for t in tools],
                        config=config,
                        source_ref=resource.id,
                    ))

            # Task definitions: have description + agent
            elif "description" in value and "agent" in value:
                if key not in seen_names:
                    seen_names.add(key)
                    deps = value.get("depends_on", [])
                    if not isinstance(deps, list):
                        deps = []
                    steps.append(WorkflowStep(
                        name=key,
                        kind="task",
                        description=str(value["description"]).strip(),
                        agent_ref=str(value["agent"]),
                        depends_on=[str(d) for d in deps],
                        expected_output=str(value.get("expected_output", "")).strip(),
                        source_ref=resource.id,
                    ))

    # Config files: YAML with model/edit-format style keys
    for resource in resources:
        data = _parse_yaml_file(resource, source_dir)
        if data is None:
            continue
        if "model" in data or "edit-format" in data:
            name = Path(resource.locator).stem.lstrip(".")
            if name not in seen_names:
                seen_names.add(name)
                config = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
                steps.append(WorkflowStep(
                    name=name,
                    kind="config",
                    description=f"Configuration from {resource.locator}",
                    config=config,
                    source_ref=resource.id,
                ))

    return steps
