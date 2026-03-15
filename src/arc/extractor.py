"""Claim and Decision extraction from text — rule-based with NLP fallback."""

from __future__ import annotations

import re
from typing import Optional

from .models import Claim, Decision, EvidencePointer, TextUnit, _generate_id

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


def extract_claims(text_units: list[TextUnit]) -> list[Claim]:
    """Extract claims from text units using rule-based patterns."""
    claims: list[Claim] = []
    seen_texts: set[str] = set()

    for tu in text_units:
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
                seen_texts.add(sentence)
                claim_id = _generate_id(f"claim:{sentence}")
                claims.append(
                    Claim(
                        id=claim_id,
                        text=sentence,
                        kind=kind,
                        evidence=[
                            EvidencePointer(
                                source_unit_id=tu.id,
                                span=tu.span,
                                weight=1.0,
                            )
                        ],
                        confidence=0.8 - _injection_penalty(sentence),
                        status="observed",
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
