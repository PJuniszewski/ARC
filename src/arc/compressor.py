"""Claim deduplication and text utilities for ARC archives."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Claim, TextUnit


@dataclass
class DeduplicationResult:
    """Result of claim deduplication."""

    claims: list[Claim]
    original_count: int
    duplicates_removed: int


def deduplicate_claims(
    claims: list[Claim],
) -> DeduplicationResult:
    """Deduplicate claims by normalized text and exclude contested (injection-flagged) claims.

    The builder preserves full fidelity — no lossy compression or budget-based
    selection. Only exact/near-duplicate removal and contested-claim exclusion.

    Args:
        claims: Claims to deduplicate
    """
    if not claims:
        return DeduplicationResult([], 0, 0)

    original_count = len(claims)

    # Exclude contested claims (injection-flagged)
    eligible = [c for c in claims if c.status != "contested"]

    # Deduplicate by normalized text
    selected: list[Claim] = []
    seen_keys: set[str] = set()

    for claim in eligible:
        key = _normalize_text(claim.text)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected.append(claim)

    duplicates_removed = original_count - len(selected)

    return DeduplicationResult(
        claims=selected,
        original_count=original_count,
        duplicates_removed=duplicates_removed,
    )


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return [w.lower() for w in re.findall(r'\b\w{2,}\b', text)]


def _normalize_text(text: str) -> str:
    """Normalize text for deduplication."""
    return " ".join(_tokenize(text))


def _count_tokens(text: str) -> int:
    """Approximate token count (words)."""
    return len(text.split())
