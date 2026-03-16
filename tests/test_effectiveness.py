"""Academic-level archive fidelity tests.

Proves that ARC's builder preserves meaning while the loader provides
effective selective retrieval. Since the builder now preserves full fidelity
(no lossy compression), these tests verify claim preservation and
loader-side token reduction.
"""

import re

import numpy as np
import pytest

from arc.builder import build_archive
from arc.compressor import _count_tokens
from arc.embeddings import TfidfEmbedder
from arc.loader import load


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _word_overlap_score(text_a: str, text_b: str) -> float:
    """Compute word overlap (Jaccard-like) between two texts."""
    words_a = set(re.findall(r'\b\w{3,}\b', text_a.lower()))
    words_b = set(re.findall(r'\b\w{3,}\b', text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


class TestArchiveFidelity:
    """Prove: Builder preserves full semantic content from source."""

    def test_claims_preserve_semantics(self, corpus_dir, tmp_path):
        """Semantic similarity between source texts and extracted claims stays high.

        Threshold: mean cosine similarity > 0.40 (TF-IDF scale).
        """
        archive_path = tmp_path / "fidelity.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        original_texts = [tu.content for tu in result.text_units if len(tu.content) > 20]
        claim_texts = [c.text for c in result.claims]

        assert len(claim_texts) > 0, "No claims extracted"
        assert len(original_texts) > 0, "No text units found"

        embedder = TfidfEmbedder(dimensions=256)
        embedder.fit(original_texts + claim_texts)

        original_vec = embedder.embed(" ".join(original_texts))
        claims_vec = embedder.embed(" ".join(claim_texts))

        similarity = _cosine_similarity(original_vec, claims_vec)
        assert similarity > 0.40, (
            f"Semantic similarity {similarity:.3f} below threshold 0.40. "
            "Claims are diverging too far from source meaning."
        )

    def test_all_non_duplicate_claims_preserved(self, corpus_dir, tmp_path):
        """Builder preserves all unique, non-contested claims.

        With no lossy compression, claim count should equal extraction
        count minus duplicates and contested claims.
        """
        archive_path = tmp_path / "full_fidelity.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        assert result.deduplication is not None
        assert len(result.claims) == (
            result.deduplication.original_count - result.deduplication.duplicates_removed
        )

    def test_key_terms_preserved(self, corpus_dir, tmp_path):
        """Critical terminology survives extraction.

        Threshold: term coverage > 60%.
        """
        archive_path = tmp_path / "terms.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        essential_terms = [
            "sha-256", "content", "manifest", "blob", "claim", "decision",
            "security", "verification", "provenance", "archive", "layer",
            "tamper", "integrity", "evidence", "builder", "loader",
        ]

        claims_text = " ".join(c.text.lower() for c in result.claims)
        found = sum(1 for term in essential_terms if term in claims_text)
        coverage = found / len(essential_terms)

        assert coverage > 0.60, (
            f"Term coverage {coverage:.1%} below 60% threshold. "
            f"Found {found}/{len(essential_terms)} essential terms."
        )

    def test_selective_loading_reduces_tokens(self, corpus_dir, tmp_path):
        """Loader-side selective loading achieves meaningful token reduction.

        Token budget optimization is the loader's job, not the builder's.
        """
        archive_path = tmp_path / "selective.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        full_loaded = load(archive_path)
        selective_loaded = load(archive_path, task="What hash algorithm does ARC use?")

        full_tokens = sum(_count_tokens(c.text) for c in full_loaded.claims)
        selective_tokens = sum(_count_tokens(c.text) for c in selective_loaded.claims)

        if full_tokens == 0:
            pytest.skip("No tokens in full load")

        reduction = 1 - (selective_tokens / full_tokens)
        assert reduction > 0.10, (
            f"Token reduction {reduction:.1%} below 10% threshold. "
            f"Full: {full_tokens} tokens, Selective: {selective_tokens} tokens."
        )

    def test_word_overlap_with_source(self, corpus_dir, tmp_path):
        """Word overlap between source and claims stays high.

        Jaccard similarity of word sets (original vs claims).
        """
        archive_path = tmp_path / "overlap.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        original_text = " ".join(tu.content for tu in result.text_units)
        claims_text = " ".join(c.text for c in result.claims)

        overlap = _word_overlap_score(original_text, claims_text)
        assert overlap > 0.15, (
            f"Word overlap {overlap:.3f} below 0.15 threshold. "
            "Claims are diverging too far from source vocabulary."
        )
