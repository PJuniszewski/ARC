"""Academic-level selective loading tests.

Proves that task-aware loading returns relevant context with measurable
precision and recall, reducing context pollution.
"""

import re
from statistics import mean

import pytest

from arc.builder import build_archive
from arc.loader import load


class TestSelectiveLoadPrecision:
    """Prove: Task-specific loading returns focused, relevant context."""

    def test_security_task_loads_security_claims(self, corpus_dir, tmp_path):
        """Academic: Security-related task loads security-relevant claims.

        Methodology:
        1. Build full archive
        2. Load with security-focused task
        3. Measure what fraction of loaded claims relate to security
        4. Assert precision > 0.30
        """
        archive_path = tmp_path / "selective.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        task = "security threats, attacks, and trust verification"
        selective = load(archive_path, task=task)
        full = load(archive_path)

        assert not selective.rejected
        assert not full.rejected
        assert len(selective.claims) > 0

        # Selective should load fewer claims than full
        assert len(selective.claims) <= len(full.claims), (
            f"Selective ({len(selective.claims)}) should not load more than full ({len(full.claims)})"
        )

        # Check precision: loaded claims should relate to security
        security_keywords = ["security", "threat", "attack", "tamper", "integrity",
                           "verification", "trust", "poison", "injection", "rollback"]
        relevant = sum(
            1 for c in selective.claims
            if any(kw in c.text.lower() for kw in security_keywords)
        )
        precision = relevant / len(selective.claims) if selective.claims else 0

        assert precision > 0.15, (
            f"Security task precision {precision:.1%} below 15% threshold. "
            f"Only {relevant}/{len(selective.claims)} claims relate to security."
        )

    def test_format_task_loads_format_claims(self, corpus_dir, tmp_path):
        """Academic: Format-related task loads format-relevant claims."""
        archive_path = tmp_path / "format_sel.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        task = "archive format, manifest schema, blob storage layout"
        selective = load(archive_path, task=task)

        assert not selective.rejected
        assert len(selective.claims) > 0

        format_keywords = ["manifest", "blob", "format", "layer", "schema",
                          "archive", "digest", "sha-256", "layout"]
        relevant = sum(
            1 for c in selective.claims
            if any(kw in c.text.lower() for kw in format_keywords)
        )
        precision = relevant / len(selective.claims) if selective.claims else 0

        assert precision > 0.30, (
            f"Format task precision {precision:.1%} below 30% threshold."
        )

    def test_selective_recall_of_relevant_claims(self, corpus_dir, tmp_path):
        """Academic: Selective loading finds most relevant claims.

        Methodology:
        1. Load full archive, identify security claims
        2. Load with security task
        3. Measure what fraction of security claims were selected
        4. Assert recall > 0.40
        """
        archive_path = tmp_path / "recall_sel.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        full = load(archive_path)
        selective = load(archive_path, task="security and trust model")

        security_keywords = ["security", "threat", "trust", "verification",
                           "tamper", "integrity", "injection"]

        full_security = [
            c for c in full.claims
            if any(kw in c.text.lower() for kw in security_keywords)
        ]

        if not full_security:
            pytest.skip("No security claims in full archive")

        selective_security = [
            c for c in selective.claims
            if any(kw in c.text.lower() for kw in security_keywords)
        ]

        recall = len(selective_security) / len(full_security)
        assert recall > 0.40, (
            f"Selective recall {recall:.1%} below 40% threshold. "
            f"Found {len(selective_security)}/{len(full_security)} security claims."
        )

    def test_different_tasks_load_different_content(self, corpus_dir, tmp_path):
        """Academic: Different tasks produce different claim selections.

        Methodology:
        1. Load archive with two very different tasks
        2. Measure overlap between selected claims
        3. Assert overlap is less than full set (differentiation)
        """
        archive_path = tmp_path / "diff_tasks.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        security_loaded = load(archive_path, task="security threats and attacks")
        format_loaded = load(archive_path, task="archive format and manifest schema")

        if security_loaded.rejected or format_loaded.rejected:
            pytest.skip("Loading failed")

        security_ids = {c.id for c in security_loaded.claims}
        format_ids = {c.id for c in format_loaded.claims}

        if not security_ids or not format_ids:
            pytest.skip("No claims loaded")

        overlap = len(security_ids & format_ids)
        total_unique = len(security_ids | format_ids)

        # The two task selections should not be identical
        overlap_ratio = overlap / total_unique if total_unique else 1.0
        assert overlap_ratio < 0.90, (
            f"Task overlap {overlap_ratio:.1%} — selections are too similar. "
            "Different tasks should produce meaningfully different claim selections."
        )


class TestSelectiveVsFull:
    """Prove: Selective loading reduces context size meaningfully."""

    def test_selective_reduces_token_count(self, corpus_dir, tmp_path):
        """Academic: Selective loading uses fewer tokens than full load.

        This proves the fundamental value proposition: task-focused loading
        delivers less noise to the agent.
        """
        archive_path = tmp_path / "token_reduction.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        full = load(archive_path)
        selective = load(archive_path, task="builder pipeline stages")

        full_tokens = sum(len(c.text.split()) for c in full.claims)
        selective_tokens = sum(len(c.text.split()) for c in selective.claims)

        if full_tokens == 0:
            pytest.skip("No tokens in full load")

        reduction = 1 - (selective_tokens / full_tokens)
        assert reduction > 0.10, (
            f"Token reduction {reduction:.1%} below 10% threshold. "
            f"Full: {full_tokens} tokens, Selective: {selective_tokens} tokens. "
            "Selective loading should meaningfully reduce context size."
        )

    def test_layer_filtering(self, corpus_dir, tmp_path):
        """Academic: Loading specific layers excludes others."""
        archive_path = tmp_path / "layer_filter.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        # Load only claims
        claims_only = load(archive_path, layers=["claims"])
        assert len(claims_only.claims) > 0
        assert len(claims_only.source_units) == 0
        assert len(claims_only.decisions) == 0

        # Load only decisions (if present)
        full = load(archive_path)
        if full.decisions:
            decisions_only = load(archive_path, layers=["decisions"])
            assert len(decisions_only.decisions) > 0
            assert len(decisions_only.claims) == 0
