"""Reasoning detection for post-retrieval refinement.

Identifies reasoning-bearing text (causal connectives, decision rationale,
ADR headings) so the refinement layer can boost these chunks in modes
where reasoning recall matters (decision, security, cross_file).

Zero external dependencies beyond `re`.
"""

from __future__ import annotations

import re

# Causal connectives, decision verbs, contrastive markers, constraint language
REASONING_MARKERS = re.compile(
    r"\b(?:because|since|therefore|thus|hence|consequently|"
    r"so\s+that|in\s+order\s+to|due\s+to|as\s+a\s+result|"
    r"for\s+this\s+reason|the\s+reason|"
    r"chose|chosen|decided|opted|selected|preferred|"
    r"rather\s+than|instead\s+of|in\s+favor\s+of|over\s+(?:the|other)|"
    r"tradeoff|trade-off|constraint|limitation|"
    r"whereas|although|however|despite|"
    r"we\s+chose|we\s+decided|we\s+use)\b",
    re.IGNORECASE,
)

# ADR-style section headings that signal reasoning content
ADR_HEADING_PATTERNS = re.compile(
    r"^#+\s*(?:Context|Decision|Consequences|Rationale|"
    r"Alternatives|Trade-offs|Why|Motivation)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def has_reasoning(text: str) -> bool:
    """Return True if text contains reasoning markers or ADR headings."""
    return bool(REASONING_MARKERS.search(text) or ADR_HEADING_PATTERNS.search(text))


def count_reasoning_markers(text: str) -> int:
    """Return count of reasoning marker matches (for diagnostics)."""
    return len(REASONING_MARKERS.findall(text)) + len(ADR_HEADING_PATTERNS.findall(text))
