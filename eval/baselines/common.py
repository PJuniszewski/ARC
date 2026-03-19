"""Shared infrastructure for large-repo benchmark baselines."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from arc.builder import _chunk, _ingest
from arc.compressor import _count_tokens
from arc.config import STOP_WORDS
from arc.models import Resource, TextUnit
from arc.provenance import BuildProvenance


@dataclass
class RetrievalResult:
    """Standard result from any retrieval system."""

    texts: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    metadata: list[dict] = field(default_factory=list)
    loaded_tokens: int = 0
    total_tokens: int = 0
    has_provenance: bool = False

    def to_dict(self) -> dict:
        return {
            "num_results": len(self.texts),
            "loaded_tokens": self.loaded_tokens,
            "total_tokens": self.total_tokens,
            "has_provenance": self.has_provenance,
            "top_scores": self.scores[:5],
        }


def chunk_snapshot(source_dir: Path) -> tuple[list[Resource], list[TextUnit]]:
    """Chunk a snapshot directory using ARC's chunkers.

    Reuses arc.builder._ingest and _chunk for identical chunking across
    all retrieval systems.

    Returns:
        (resources, text_units)
    """
    provenance = BuildProvenance(parameters={"source_dir": str(source_dir)})
    resources = _ingest(source_dir, provenance)
    text_units = _chunk(resources, source_dir)
    return resources, text_units


def compute_total_tokens(text_units: list[TextUnit]) -> int:
    """Total tokens across all text units."""
    return sum(_count_tokens(tu.content) for tu in text_units)


def keyword_overlap(query_tokens: set[str], text_tokens: set[str]) -> float:
    """Fraction of query tokens found in text tokens."""
    if not query_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens)


def tokenize_query(text: str) -> set[str]:
    """Tokenize and stem a query string, removing stop words."""
    words = re.findall(r'\b\w{2,}\b', text.lower())
    return {_stem(w) for w in words} - STOP_WORDS


def _stem(word: str) -> str:
    """Minimal suffix stemmer matching TfidfEmbedder._stem."""
    if word.endswith('ing') and len(word) > 5:
        stem = word[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if word.endswith('tion') and len(word) > 5:
        return word[:-4]
    if word.endswith('ness') and len(word) > 5:
        return word[:-4]
    if word.endswith('ment') and len(word) > 5:
        return word[:-4]
    if word.endswith('ies') and len(word) > 4:
        return word[:-3] + 'y'
    if word.endswith('es') and len(word) > 4:
        return word[:-2]
    if word.endswith('s') and not word.endswith('ss') and len(word) > 3:
        return word[:-1]
    if word.endswith('ed') and len(word) > 4:
        return word[:-2]
    return word
