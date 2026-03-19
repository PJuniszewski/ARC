"""RAGAS evaluation — semantic retrieval quality using Claude as LLM judge.

This is the primary evaluation for ARC's retrieval pipeline. Uses the actual
RAGAS library (https://docs.ragas.io/) with Claude as the LLM judge and
sentence-transformers for embeddings.

Unlike the lexical smoke tests (test_retrieval_metrics.py) which use keyword
matching, RAGAS evaluates semantic understanding: can the LLM judge confirm
that retrieved context actually answers the question?

Requires:
    pip install arc-context[eval]
    ANTHROPIC_API_KEY environment variable

Metrics:
    - Context Precision: are retrieved items relevant to the question? (LLM-judged)
    - Context Recall: does retrieved context cover the ground-truth answer? (LLM-judged)
    - Faithfulness: are claims grounded in the retrieved source text? (LLM-judged)
    - Response Relevancy: does the response address the question? (LLM + embeddings)
"""

from __future__ import annotations

import os
from statistics import harmonic_mean, mean

import pytest

from arc.builder import build_archive
from arc.loader import load

# ---------------------------------------------------------------------------
# Conditional imports — skip cleanly if ragas is not installed
# ---------------------------------------------------------------------------

try:
    from ragas.llms import llm_factory

    HAS_RAGAS = True
except ImportError:
    HAS_RAGAS = False

try:
    from ragas.metrics.collections import (
        AnswerRelevancy as ResponseRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    HAS_METRICS = True
except ImportError:
    try:
        from ragas.metrics import (
            Faithfulness,
            LLMContextPrecisionWithReference as ContextPrecisionWithReference,
            LLMContextRecall as ContextRecall,
            ResponseRelevancy,
        )

        HAS_METRICS = True
    except ImportError:
        HAS_METRICS = False


def _require_ragas():
    if not HAS_RAGAS:
        pytest.skip("ragas not installed (pip install arc-context[eval])")
    if not HAS_METRICS:
        pytest.skip("ragas metrics not available — check ragas version")


def _require_anthropic_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")


def _make_llm():
    """Create RAGAS LLM wrapper using Claude via Anthropic."""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()
    llm = llm_factory(
        "claude-haiku-4-5-20251001",
        provider="anthropic",
        client=client,
    )
    # RAGAS defaults to temperature=0.01 + top_p=0.1, but Anthropic's API
    # rejects requests with both set. Remove top_p.
    llm.model_args.pop("top_p", None)
    # Increase max_tokens — default 1024 is too low for faithfulness NLI on
    # responses with many statements.
    llm.model_args["max_tokens"] = 4096
    return llm


def _make_embeddings():
    """Create RAGAS embeddings wrapper using sentence-transformers."""
    try:
        from ragas.embeddings import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model="sentence-transformers/all-MiniLM-L6-v2")
    except (ImportError, Exception):
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_samples(archive_path, ground_truth):
    """Build evaluation samples from ARC archive + ground truth.

    For each ground truth question:
    1. Load the archive with task=question (selective loading)
    2. Collect retrieved claims as contexts
    3. Construct a "response" from top claims
    """
    samples = []

    for qa in ground_truth["single_hop_questions"]:
        loaded = load(archive_path, task=qa["question"])
        if loaded.rejected or not loaded.claims:
            continue

        retrieved_contexts = [c.text for c in loaded.claims]
        response = " ".join(c.text for c in loaded.claims[:3])

        samples.append({
            "user_input": qa["question"],
            "retrieved_contexts": retrieved_contexts,
            "response": response,
            "reference": qa["answer"],
        })

    return samples


def _score_metric(metric, samples):
    """Score a metric across all samples, return mean score.

    Each RAGAS metric accepts different kwargs — only pass what it needs.
    """
    import inspect

    accepted = set(inspect.signature(metric.ascore).parameters.keys()) - {"self"}

    scores = []
    for s in samples:
        kwargs = {k: v for k, v in s.items() if k in accepted}
        result = metric.score(**kwargs)
        scores.append(result.value if hasattr(result, "value") else float(result))
    return mean(scores) if scores else 0.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestRAGASContextPrecision:
    """LLM-judged context precision: are retrieved items actually relevant?"""

    def test_context_precision(self, corpus_dir, tmp_path, ground_truth):
        """RAGAS ContextPrecisionWithReference using Claude.

        For each question, the LLM judges whether each retrieved claim
        is relevant given the reference answer.
        Threshold: mean > 0.50
        """
        _require_ragas()
        _require_anthropic_key()

        archive_path = tmp_path / "ragas_cp.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        samples = _build_samples(archive_path, ground_truth)
        assert len(samples) >= 5, f"Too few samples: {len(samples)}"

        llm = _make_llm()
        metric = ContextPrecisionWithReference(llm=llm)
        score = _score_metric(metric, samples)

        print(f"\n  RAGAS Context Precision: {score:.3f} ({len(samples)} samples)")
        assert score > 0.50, (
            f"RAGAS context precision = {score:.3f} (below 0.50). "
            "LLM judge found retrieved claims are not sufficiently relevant."
        )


@pytest.mark.eval
class TestRAGASContextRecall:
    """LLM-judged context recall: does retrieved context cover the answer?"""

    def test_context_recall(self, corpus_dir, tmp_path, ground_truth):
        """RAGAS ContextRecall using Claude.

        The LLM checks whether all facts in the reference answer
        can be found in the retrieved contexts.
        Threshold: mean > 0.50
        """
        _require_ragas()
        _require_anthropic_key()

        archive_path = tmp_path / "ragas_cr.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        samples = _build_samples(archive_path, ground_truth)
        assert len(samples) >= 5

        llm = _make_llm()
        metric = ContextRecall(llm=llm)
        score = _score_metric(metric, samples)

        print(f"\n  RAGAS Context Recall: {score:.3f} ({len(samples)} samples)")
        assert score > 0.50, (
            f"RAGAS context recall = {score:.3f} (below 0.50). "
            "Retrieved context doesn't cover the reference answer."
        )


@pytest.mark.eval
class TestRAGASFaithfulness:
    """LLM-judged faithfulness: are claims grounded in source context?"""

    def test_faithfulness(self, corpus_dir, tmp_path, ground_truth):
        """RAGAS Faithfulness using Claude.

        The LLM checks whether each statement in the response can be
        traced back to the retrieved context (no hallucination).
        Threshold: mean > 0.70
        """
        _require_ragas()
        _require_anthropic_key()

        archive_path = tmp_path / "ragas_faith.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        samples = _build_samples(archive_path, ground_truth)
        assert len(samples) >= 5

        llm = _make_llm()
        metric = Faithfulness(llm=llm)
        score = _score_metric(metric, samples)

        print(f"\n  RAGAS Faithfulness: {score:.3f} ({len(samples)} samples)")
        assert score > 0.70, (
            f"RAGAS faithfulness = {score:.3f} (below 0.70). "
            "Response contains statements not grounded in retrieved context."
        )


@pytest.mark.eval
class TestRAGASComposite:
    """All RAGAS metrics combined — the headline evaluation number."""

    def test_composite_ragas(self, corpus_dir, tmp_path, ground_truth):
        """Full RAGAS evaluation: all metrics scored per-sample then averaged.

        Composite = harmonic_mean(precision, recall, faithfulness[, relevancy])
        Threshold: > 0.50

        This is the number that matters. If this passes, ARC's retrieval
        pipeline is producing semantically meaningful results as judged by
        an independent LLM — not just matching keywords.
        """
        _require_ragas()
        _require_anthropic_key()

        archive_path = tmp_path / "ragas_full.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        samples = _build_samples(archive_path, ground_truth)
        assert len(samples) >= 5, f"Too few samples: {len(samples)}"

        llm = _make_llm()
        embeddings = _make_embeddings()

        # Score each metric across all samples
        precision = _score_metric(ContextPrecisionWithReference(llm=llm), samples)
        recall = _score_metric(ContextRecall(llm=llm), samples)
        faithfulness = _score_metric(Faithfulness(llm=llm), samples)

        relevancy = 0.0
        if embeddings is not None:
            relevancy = _score_metric(ResponseRelevancy(llm=llm, embeddings=embeddings), samples)

        scores = [s for s in [precision, recall, faithfulness, relevancy] if s > 0]
        composite = harmonic_mean(scores) if scores else 0.0

        print("\n  === RAGAS Evaluation (Claude as judge) ===")
        print(f"  Context Precision:  {precision:.3f}")
        print(f"  Context Recall:     {recall:.3f}")
        print(f"  Faithfulness:       {faithfulness:.3f}")
        print(f"  Response Relevancy: {relevancy:.3f}")
        print(f"  Composite:          {composite:.3f}")
        print(f"  Samples evaluated:  {len(samples)}")

        assert composite > 0.50, (
            f"RAGAS composite = {composite:.3f} (below 0.50). "
            f"P={precision:.2f} R={recall:.2f} F={faithfulness:.2f} Rel={relevancy:.2f}"
        )
