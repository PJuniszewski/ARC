"""Semantic compression — extractive (TF-IDF) + clustering-based selection."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from .models import Claim, EvidencePointer, TextUnit, _generate_id


@dataclass
class CompressionResult:
    """Result of semantic compression."""

    compressed_claims: list[Claim]
    original_token_count: int
    compressed_token_count: int
    compression_ratio: float


def compress_claims(
    claims: list[Claim],
    text_units: list[TextUnit],
    budget: float = 0.5,
) -> CompressionResult:
    """Compress claims using TF-IDF ranking + deduplication.

    Args:
        claims: Claims to compress
        text_units: Source text units for context
        budget: Fraction of original claims to keep (0.0 to 1.0)
    """
    if not claims:
        return CompressionResult([], 0, 0, 1.0)

    original_tokens = sum(_count_tokens(c.text) for c in claims)

    # Score claims by importance (TF-IDF of claim terms vs corpus)
    corpus_texts = [tu.content for tu in text_units]
    scored = []
    for claim in claims:
        score = _tfidf_importance(claim.text, corpus_texts)
        # Boost requirements and definitions
        if claim.kind in ("requirement", "definition"):
            score *= 1.5
        # Boost high-confidence claims
        score *= claim.confidence
        scored.append((score, claim))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Select top claims within budget
    target_count = max(1, int(len(claims) * budget))
    selected: list[Claim] = []
    seen_keys: set[str] = set()

    for _score, claim in scored:
        if len(selected) >= target_count:
            break
        # Deduplicate by normalized text
        key = _normalize_text(claim.text)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected.append(claim)

    compressed_tokens = sum(_count_tokens(c.text) for c in selected)
    ratio = original_tokens / compressed_tokens if compressed_tokens > 0 else float("inf")

    return CompressionResult(
        compressed_claims=selected,
        original_token_count=original_tokens,
        compressed_token_count=compressed_tokens,
        compression_ratio=ratio,
    )


def compress_text_units(
    text_units: list[TextUnit],
    budget: float = 0.5,
) -> list[TextUnit]:
    """Compress text units by selecting the most important ones via TF-IDF."""
    if not text_units:
        return []

    all_texts = [tu.content for tu in text_units]
    scored = []
    for tu in text_units:
        score = _tfidf_importance(tu.content, all_texts)
        # Boost frontmatter and sections with headers
        if tu.kind == "frontmatter":
            score *= 2.0
        elif tu.content.strip().startswith("#"):
            score *= 1.3
        scored.append((score, tu))

    scored.sort(key=lambda x: x[0], reverse=True)
    target = max(1, int(len(text_units) * budget))
    return [tu for _, tu in scored[:target]]


def _tfidf_importance(text: str, corpus: list[str]) -> float:
    """Compute TF-IDF-based importance score for a text against a corpus."""
    words = _tokenize(text)
    if not words:
        return 0.0

    tf = Counter(words)
    max_tf = max(tf.values()) if tf else 1

    # Document frequencies
    n_docs = len(corpus) + 1  # +1 smoothing
    doc_freq: Counter[str] = Counter()
    for doc in corpus:
        doc_words = set(_tokenize(doc))
        for w in doc_words:
            doc_freq[w] += 1

    score = 0.0
    for word, count in tf.items():
        tf_norm = count / max_tf
        idf = math.log((n_docs + 1) / (doc_freq.get(word, 0) + 1)) + 1
        score += tf_norm * idf

    # Normalize by text length to avoid bias toward longer texts
    return score / (len(words) ** 0.5) if words else 0.0


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return [w.lower() for w in re.findall(r'\b\w{2,}\b', text)]


def _normalize_text(text: str) -> str:
    """Normalize text for deduplication."""
    return " ".join(_tokenize(text))


def _count_tokens(text: str) -> int:
    """Approximate token count (words)."""
    return len(text.split())
