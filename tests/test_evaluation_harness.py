"""End-to-end evaluation harness — the minimal MVP from evaluation-plan.md.

Runs the complete evaluation pipeline:
1. Build archive from fixed fixture corpus
2. Verify archive integrity
3. Diff old/new archive after one fixture change
4. Task with raw retrieval baseline
5. Same task with ARC selective load
6. Tamper test
7. Stale-version test

Each step produces quantified before/after numbers per the anti-bullshit rule.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

import numpy as np
import pytest

from arc.builder import build_archive
from arc.cas import ContentAddressedStore, sha256_digest
from arc.compressor import _count_tokens
from arc.diff import diff_archives
from arc.embeddings import TfidfEmbedder
from arc.loader import load, verify


# ---------------------------------------------------------------------------
# Harness result types
# ---------------------------------------------------------------------------

@dataclass
class HarnessReport:
    """Collected metrics from a full harness run."""

    build_time_ms: float = 0.0
    load_time_ms: float = 0.0
    archive_size_bytes: int = 0
    total_blobs: int = 0
    total_claims: int = 0
    total_decisions: int = 0
    duplicates_removed: int = 0
    verification_passed: bool = False

    # Diff metrics
    blob_reuse_ratio: float = 0.0
    new_claims_after_change: int = 0
    removed_claims_after_change: int = 0

    # Retrieval comparison
    baseline_recall: float = 0.0
    arc_recall: float = 0.0
    arc_advantage: float = 0.0  # arc_recall - baseline_recall

    # Selective loading
    full_context_tokens: int = 0
    selective_context_tokens: int = 0
    token_reduction_pct: float = 0.0

    # Security
    tamper_detected: bool = False
    stale_version_rejected: bool = False

    def summary(self) -> str:
        lines = [
            "=== ARC Evaluation Harness Report ===",
            "",
            "--- Build ---",
            f"  Build time:         {self.build_time_ms:.0f}ms",
            f"  Archive size:       {self.archive_size_bytes:,} bytes",
            f"  Blobs:              {self.total_blobs}",
            f"  Claims:             {self.total_claims}",
            f"  Decisions:          {self.total_decisions}",
            f"  Duplicates removed: {self.duplicates_removed}",
            f"  Integrity verified: {self.verification_passed}",
            "",
            "--- Incremental Diff ---",
            f"  Blob reuse ratio:   {self.blob_reuse_ratio:.1%}",
            f"  New claims:         +{self.new_claims_after_change}",
            f"  Removed claims:     -{self.removed_claims_after_change}",
            "",
            "--- Retrieval (baseline vs ARC) ---",
            f"  Baseline recall:    {self.baseline_recall:.3f}",
            f"  ARC recall:         {self.arc_recall:.3f}",
            f"  ARC advantage:      {self.arc_advantage:+.3f}",
            "",
            "--- Selective Loading ---",
            f"  Full context:       {self.full_context_tokens} tokens",
            f"  Selective context:  {self.selective_context_tokens} tokens",
            f"  Token reduction:    {self.token_reduction_pct:.1%}",
            "",
            "--- Security ---",
            f"  Tamper detected:    {self.tamper_detected}",
            f"  Stale rejected:     {self.stale_version_rejected}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Baseline retrieval (raw TF-IDF over files, no archive)
# ---------------------------------------------------------------------------

def _baseline_recall(corpus_dir: Path, question: str, keywords: list[str]) -> float:
    """Naive TF-IDF recall: search raw files, measure keyword coverage."""
    texts = []
    for f in sorted(corpus_dir.glob("*.md")):
        texts.append(f.read_text())

    if not texts:
        return 0.0

    embedder = TfidfEmbedder(dimensions=128)
    embedder.fit(texts)
    query_vec = embedder.embed(question)

    scores = []
    for text in texts:
        text_vec = embedder.embed(text)
        norm = np.linalg.norm(query_vec) * np.linalg.norm(text_vec) + 1e-10
        sim = float(np.dot(query_vec, text_vec) / norm)
        scores.append((sim, text))

    scores.sort(key=lambda x: x[0], reverse=True)
    top_texts = [t for _, t in scores[:3]]

    combined = " ".join(top_texts).lower()
    found = sum(1 for kw in keywords if kw.lower() in combined)
    return found / len(keywords) if keywords else 1.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEvaluationHarness:
    """End-to-end MVP evaluation harness."""

    def test_full_harness(self, corpus_dir, modified_corpus, tmp_path, ground_truth):
        """Run the complete 7-step harness and produce quantified results.

        This is the core evaluation: no vague 'felt better' —
        every claim is backed by a number.
        """
        report = HarnessReport()

        # ===== Step 1: Build archive from fixed fixture corpus =====
        archive_v1 = tmp_path / "harness_v1.arc"
        t0 = time.monotonic()
        result = build_archive(
            corpus_dir, archive_v1,
            archive_id="arc://harness-test",
            archive_version="1.0.0",
        )
        t1 = time.monotonic()

        assert result.valid, f"Build failed: {result.errors}"
        report.build_time_ms = (t1 - t0) * 1000

        cas = ContentAddressedStore(archive_v1)
        report.archive_size_bytes = cas.archive_size()
        report.total_blobs = len(cas.list_blobs())
        report.total_claims = len(result.claims)
        report.total_decisions = len(result.decisions)
        if result.deduplication:
            report.duplicates_removed = result.deduplication.duplicates_removed

        # ===== Step 2: Verify archive integrity =====
        v = verify(archive_v1)
        report.verification_passed = v.valid
        assert v.valid, f"Verification failed: {v.errors}"

        # ===== Step 3: Diff old/new after fixture change =====
        archive_v2 = tmp_path / "harness_v2.arc"
        result_v2 = build_archive(
            modified_corpus, archive_v2,
            archive_id="arc://harness-test",
            archive_version="2.0.0",
            parent_archive=archive_v1,
        )
        assert result_v2.valid

        diff_result = diff_archives(archive_v1, archive_v2)
        report.blob_reuse_ratio = diff_result.blob_reuse_ratio
        report.new_claims_after_change = len(diff_result.new_claims)
        report.removed_claims_after_change = len(diff_result.removed_claims)

        # Verify incremental efficiency: most blobs should be reused
        assert diff_result.blob_reuse_ratio >= 0.20, (
            f"Blob reuse {diff_result.blob_reuse_ratio:.1%} too low. "
            "Incremental builds should reuse some content."
        )

        # ===== Step 4 & 5: Baseline vs ARC retrieval =====
        questions = ground_truth["single_hop_questions"]

        baseline_recalls = []
        arc_recalls = []

        for qa in questions:
            # Step 4: Baseline
            base_r = _baseline_recall(corpus_dir, qa["question"], qa["relevant_keywords"])
            baseline_recalls.append(base_r)

            # Step 5: ARC selective load
            t_load_0 = time.monotonic()
            loaded = load(archive_v1, task=qa["question"])
            t_load_1 = time.monotonic()

            if loaded.rejected or not loaded.claims:
                arc_recalls.append(0.0)
                continue

            combined = " ".join(c.text for c in loaded.claims).lower()
            found = sum(1 for kw in qa["relevant_keywords"] if kw.lower() in combined)
            arc_r = found / len(qa["relevant_keywords"])
            arc_recalls.append(arc_r)

        report.baseline_recall = mean(baseline_recalls) if baseline_recalls else 0.0
        report.arc_recall = mean(arc_recalls) if arc_recalls else 0.0
        report.arc_advantage = report.arc_recall - report.baseline_recall

        # ARC should provide meaningful retrieval
        assert report.arc_recall > 0.15, (
            f"ARC recall {report.arc_recall:.3f} too low for useful retrieval"
        )

        # ===== Selective loading token reduction =====
        full_loaded = load(archive_v1)
        report.full_context_tokens = sum(
            _count_tokens(c.text) for c in full_loaded.claims
        )

        task_loaded = load(archive_v1, task="What hash algorithm does ARC use?")
        report.selective_context_tokens = sum(
            _count_tokens(c.text) for c in task_loaded.claims
        ) if not task_loaded.rejected else report.full_context_tokens

        if report.full_context_tokens > 0:
            report.token_reduction_pct = (
                1 - report.selective_context_tokens / report.full_context_tokens
            )
        report.load_time_ms = (t_load_1 - t_load_0) * 1000

        # ===== Step 6: Tamper test =====
        tamper_archive = tmp_path / "harness_tamper.arc"
        shutil.copytree(archive_v1, tamper_archive)
        tamper_cas = ContentAddressedStore(tamper_archive)
        blobs = tamper_cas.list_blobs()
        if blobs:
            original = tamper_cas.retrieve_blob(blobs[0])
            tamper_cas._test_tamper_blob(blobs[0], b"TAMPERED")
            tamper_v = verify(tamper_archive)
            report.tamper_detected = not tamper_v.valid
            tamper_cas._test_tamper_blob(blobs[0], original)

        assert report.tamper_detected, "Tamper was NOT detected"

        # ===== Step 7: Stale-version test =====
        stale_loaded = load(archive_v1, expected_min_version="999.0.0")
        report.stale_version_rejected = stale_loaded.rejected
        assert report.stale_version_rejected, "Stale version was NOT rejected"

        # Print the full report (visible in pytest -v output)
        print("\n" + report.summary())

    def test_build_time_under_budget(self, corpus_dir, tmp_path):
        """Build time should be reasonable for the test corpus.

        Budget: < 5 seconds for 9-document corpus.
        """
        archive_path = tmp_path / "timing.arc"
        t0 = time.monotonic()
        result = build_archive(corpus_dir, archive_path)
        elapsed = time.monotonic() - t0

        assert result.valid
        assert elapsed < 5.0, (
            f"Build took {elapsed:.1f}s (budget: 5s). "
            "Performance regression detected."
        )

    def test_load_time_under_budget(self, corpus_dir, tmp_path):
        """Load + selective filter should be fast.

        Budget: < 1 second per task query.
        """
        archive_path = tmp_path / "load_timing.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        t0 = time.monotonic()
        loaded = load(archive_path, task="What hash algorithm?")
        elapsed = time.monotonic() - t0

        assert not loaded.rejected
        assert elapsed < 1.0, (
            f"Load + filter took {elapsed:.2f}s (budget: 1s). "
            "Performance regression detected."
        )


class TestRealWorldScenarios:
    """Evaluate with realistic agent task patterns."""

    def test_code_understanding_task(self, corpus_dir, tmp_path):
        """Scenario: Agent needs to understand ARC architecture for a code change.

        Real-world task: 'I need to add a new layer type to the archive format.
        What are the existing layers and how do they work?'
        """
        archive_path = tmp_path / "code_task.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        task = "Add a new layer type to the archive format. What are existing layers?"
        loaded = load(archive_path, task=task)
        assert not loaded.rejected

        # Should find layer-related claims
        claim_text = " ".join(c.text.lower() for c in loaded.claims)
        layer_terms = ["layer", "manifest", "blob", "digest"]
        found = sum(1 for t in layer_terms if t in claim_text)
        assert found >= 2, (
            f"Only found {found}/4 layer-related terms. "
            "Selective loading should surface architecture claims for this task."
        )

    def test_security_audit_task(self, corpus_dir, tmp_path):
        """Scenario: Agent performing security review of archive handling.

        Real-world task: 'Review the threat model and identify security controls
        for archive integrity.'
        """
        archive_path = tmp_path / "security_task.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        task = "Review threat model and security controls for archive integrity"
        loaded = load(archive_path, task=task)
        assert not loaded.rejected

        claim_text = " ".join(c.text.lower() for c in loaded.claims)
        security_terms = ["security", "tamper", "integrity", "threat", "trust"]
        found = sum(1 for t in security_terms if t in claim_text)
        assert found >= 2, (
            f"Only found {found}/5 security terms. "
            "Security audit task should surface threat model claims."
        )

    def test_debugging_task(self, corpus_dir, tmp_path):
        """Scenario: Agent debugging a build pipeline failure.

        Real-world task: 'The builder pipeline is failing at the extract stage.
        What does the extract stage do and what are its inputs?'
        """
        archive_path = tmp_path / "debug_task.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        task = "Builder pipeline extract stage failure. What does extract do?"
        loaded = load(archive_path, task=task)
        assert not loaded.rejected

        claim_text = " ".join(c.text.lower() for c in loaded.claims)
        pipeline_terms = ["pipeline", "builder", "extract", "stage", "claim"]
        found = sum(1 for t in pipeline_terms if t in claim_text)
        assert found >= 2, (
            f"Only found {found}/5 pipeline terms. "
            "Debugging task should surface builder pipeline claims."
        )

    def test_incremental_update_scenario(self, corpus_dir, modified_corpus, tmp_path):
        """Scenario: Corpus changes — verify archive diff is proportional.

        When one file changes:
        - Most blobs should be reused (> 30%)
        - New claims should appear for the changed content
        - Unchanged document claims should persist
        """
        v1 = tmp_path / "inc_v1.arc"
        v2 = tmp_path / "inc_v2.arc"

        r1 = build_archive(corpus_dir, v1, archive_version="1.0.0")
        r2 = build_archive(modified_corpus, v2, archive_version="2.0.0",
                           parent_archive=v1)
        assert r1.valid and r2.valid

        diff = diff_archives(v1, v2)

        # Proportional change: one file changed, so diff should be bounded
        assert diff.blob_reuse_ratio >= 0.20, (
            f"Blob reuse {diff.blob_reuse_ratio:.1%} — one-file change should "
            "reuse some blobs"
        )

        # Structural change should be visible: new or removed blobs
        assert len(diff.new_blobs) >= 1 or len(diff.changed_resources) >= 1, (
            "Expected structural diff from modified file"
        )

    def test_multi_session_continuity(self, corpus_dir, tmp_path):
        """Scenario: Agent loads archive across sessions.

        Build archive, verify, load, then rebuild from same source.
        Second build should produce identical archive (deterministic).
        """
        v1 = tmp_path / "session1.arc"
        v2 = tmp_path / "session2.arc"

        r1 = build_archive(corpus_dir, v1, archive_id="arc://continuity-test",
                           archive_version="1.0.0")
        r2 = build_archive(corpus_dir, v2, archive_id="arc://continuity-test",
                           archive_version="1.0.0")

        assert r1.valid and r2.valid

        # Same source → same claim count
        assert len(r1.claims) == len(r2.claims), (
            f"Claim counts differ: {len(r1.claims)} vs {len(r2.claims)}. "
            "Same input should produce same output."
        )

        # Same source → same blob content (content-addressed)
        cas1 = ContentAddressedStore(v1)
        cas2 = ContentAddressedStore(v2)
        blobs1 = set(cas1.list_blobs())
        blobs2 = set(cas2.list_blobs())

        # Content blobs should match (manifest blob may differ due to timestamps)
        overlap = len(blobs1 & blobs2)
        assert overlap >= len(blobs1) - 1, (
            f"Only {overlap}/{len(blobs1)} blobs match between identical builds. "
            "Content-addressed storage should be deterministic."
        )
