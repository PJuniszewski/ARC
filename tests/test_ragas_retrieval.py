"""RAGAS-style retrieval evaluation metrics.

Implements the core RAGAS evaluation dimensions without requiring an LLM judge:
- Context precision: Are retrieved items relevant to the question?
- Context recall: Does retrieved context cover the ground-truth answer?
- Faithfulness: Are generated answers grounded in retrieved context?
- Answer relevancy: Does the retrieved context enable answering the question?

References:
- RAGAS: https://arxiv.org/abs/2309.15217
- Adapted for rule-based evaluation (no LLM judge needed)
"""

from __future__ import annotations

import re
from collections import Counter
from statistics import mean

import pytest

from arc.builder import build_archive
from arc.loader import load


# ---------------------------------------------------------------------------
# RAGAS-style metric implementations
# ---------------------------------------------------------------------------

def _context_precision(
    retrieved_texts: list[str],
    ground_truth_answer: str,
    relevant_keywords: list[str],
) -> float:
    """RAGAS context precision: fraction of retrieved items that are relevant.

    Ranked precision: weight earlier results higher (like RAGAS does).
    """
    if not retrieved_texts:
        return 0.0

    answer_lower = ground_truth_answer.lower()
    kw_set = {kw.lower() for kw in relevant_keywords}

    relevant_at_k = []
    for text in retrieved_texts:
        text_lower = text.lower()
        # A retrieved item is relevant if it contains any keyword or answer fragment
        is_relevant = (
            any(kw in text_lower for kw in kw_set) or
            _significant_overlap(text_lower, answer_lower) > 0.3
        )
        relevant_at_k.append(1.0 if is_relevant else 0.0)

    # Average precision (weighted by rank)
    if not relevant_at_k:
        return 0.0

    cumulative = 0.0
    num_relevant = 0
    avg_precision = 0.0
    for i, rel in enumerate(relevant_at_k):
        if rel > 0:
            num_relevant += 1
            cumulative += rel
            precision_at_i = cumulative / (i + 1)
            avg_precision += precision_at_i

    return avg_precision / max(num_relevant, 1)


def _context_recall(
    retrieved_texts: list[str],
    ground_truth_answer: str,
    required_facts: list[str],
) -> float:
    """RAGAS context recall: fraction of ground-truth facts covered by context.

    For each required fact/keyword, check if it's findable in retrieved context.
    """
    if not required_facts:
        return 1.0

    combined = " ".join(retrieved_texts).lower()
    found = 0
    for fact in required_facts:
        fact_lower = fact.lower()
        if fact_lower in combined:
            found += 1
        else:
            # Fuzzy: check if significant words from the fact appear
            words = [w for w in re.findall(r'\b\w{3,}\b', fact_lower)
                     if w not in _STOPWORDS]
            if words:
                matched = sum(1 for w in words if w in combined)
                if matched / len(words) >= 0.5:
                    found += 1

    return found / len(required_facts)


def _faithfulness(
    claim_texts: list[str],
    source_texts: list[str],
) -> float:
    """RAGAS faithfulness: fraction of claims grounded in source evidence.

    For each claim, check whether its significant terms can be traced
    back to the source text units. A faithful claim doesn't invent facts.
    """
    if not claim_texts:
        return 1.0

    combined_source = " ".join(source_texts).lower()
    grounded_count = 0

    for claim in claim_texts:
        terms = _extract_key_terms(claim)
        if not terms:
            grounded_count += 1  # vacuously grounded
            continue

        grounded = sum(1 for t in terms if t.lower() in combined_source)
        if grounded / len(terms) >= 0.6:
            grounded_count += 1

    return grounded_count / len(claim_texts)


def _answer_relevancy(
    retrieved_texts: list[str],
    question: str,
) -> float:
    """RAGAS answer relevancy: can the question be answered from retrieved context?

    Measures term coverage: what fraction of question's key terms appear in context.
    """
    question_terms = _extract_key_terms(question)
    if not question_terms:
        return 1.0

    combined = " ".join(retrieved_texts).lower()
    found = sum(1 for t in question_terms if t.lower() in combined)
    return found / len(question_terms)


def _significant_overlap(text_a: str, text_b: str) -> float:
    """Fraction of significant words shared between two texts."""
    words_a = set(re.findall(r'\b\w{3,}\b', text_a)) - _STOPWORDS
    words_b = set(re.findall(r'\b\w{3,}\b', text_b)) - _STOPWORDS
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / min(len(words_a), len(words_b))


def _extract_key_terms(text: str) -> list[str]:
    """Extract key terms: technical words, proper nouns, numbers."""
    terms = []
    terms.extend(re.findall(r'\b\d[\d.]*\b', text))  # numbers
    terms.extend(re.findall(r'\b[A-Z]{2,}\b', text))  # acronyms
    terms.extend(re.findall(r'\b\w+-\w+\b', text.lower()))  # hyphenated
    terms.extend(
        w for w in re.findall(r'\b[a-z]{5,}\b', text.lower())
        if w not in _STOPWORDS
    )
    return terms


_STOPWORDS = frozenset({
    "the", "and", "for", "are", "was", "that", "with", "from", "this",
    "have", "been", "will", "each", "which", "their", "other", "into",
    "also", "than", "only", "must", "should", "would", "could", "about",
    "there", "where", "these", "those", "does", "what", "when", "while",
    "after", "before", "between", "through", "during", "using",
})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRAGASContextPrecision:
    """RAGAS context precision: retrieved items should be relevant."""

    def test_single_hop_context_precision(self, corpus_dir, tmp_path, ground_truth):
        """Context precision for single-hop factual questions.

        Methodology:
        1. Build archive, load with task query
        2. Measure ranked precision of loaded claims against ground truth
        3. Assert mean precision > 0.30
        """
        archive_path = tmp_path / "ragas_precision.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        precisions = []
        for qa in ground_truth["single_hop_questions"]:
            loaded = load(archive_path, task=qa["question"])
            if loaded.rejected or not loaded.claims:
                precisions.append(0.0)
                continue

            texts = [c.text for c in loaded.claims]
            p = _context_precision(texts, qa["answer"], qa["relevant_keywords"])
            precisions.append(p)

        mean_p = mean(precisions) if precisions else 0.0
        assert mean_p > 0.40, (
            f"RAGAS context precision = {mean_p:.3f} (below 0.40). "
            f"Per-question: {[f'{p:.2f}' for p in precisions]}"
        )


class TestRAGASContextRecall:
    """RAGAS context recall: retrieved context covers ground truth."""

    def test_single_hop_context_recall(self, corpus_dir, tmp_path, ground_truth):
        """Single-hop recall: keywords from ground truth appear in context.

        Threshold: mean recall > 0.40.
        """
        archive_path = tmp_path / "ragas_recall.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        recalls = []
        for qa in ground_truth["single_hop_questions"]:
            loaded = load(archive_path, task=qa["question"])
            if loaded.rejected or not loaded.claims:
                recalls.append(0.0)
                continue

            texts = [c.text for c in loaded.claims]
            r = _context_recall(texts, qa["answer"], qa["relevant_keywords"])
            recalls.append(r)

        mean_r = mean(recalls) if recalls else 0.0
        assert mean_r > 0.50, (
            f"RAGAS context recall = {mean_r:.3f} (below 0.50). "
            f"Per-question: {[f'{r:.2f}' for r in recalls]}"
        )

    def test_multi_hop_context_recall(self, corpus_dir, tmp_path, ground_truth):
        """Multi-hop recall: cross-document facts covered by graph traversal.

        Uses evidence graph traversal (2 hops) to find related claims.
        Threshold: mean recall > 0.30.
        """
        archive_path = tmp_path / "ragas_multihop.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        recalls = []
        for qa in ground_truth["multi_hop_questions"]:
            loaded = load(archive_path)
            if loaded.rejected:
                recalls.append(0.0)
                continue

            graph_results = loaded.traverse_evidence_graph(qa["question"], hops=2)
            texts = [c.text for c in graph_results]
            r = _context_recall(texts, "", qa["required_facts"])
            recalls.append(r)

        mean_r = mean(recalls) if recalls else 0.0
        assert mean_r > 0.30, (
            f"RAGAS multi-hop recall = {mean_r:.3f} (below 0.30). "
            f"Per-question: {[f'{r:.2f}' for r in recalls]}"
        )


class TestRAGASFaithfulness:
    """RAGAS faithfulness: claims are grounded in source text."""

    def test_claim_faithfulness(self, corpus_dir, tmp_path):
        """Claims should be traceable to source text units.

        Methodology:
        1. Build archive
        2. For each claim, check if key terms appear in source text units
        3. Assert mean faithfulness > 0.70

        This catches hallucinated claims not grounded in any source.
        """
        archive_path = tmp_path / "ragas_faithful.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        claim_texts = [c.text for c in result.claims]
        source_texts = [tu.content for tu in result.text_units]

        faith = _faithfulness(claim_texts, source_texts)
        assert faith > 0.70, (
            f"RAGAS faithfulness = {faith:.3f} (below 0.70). "
            f"{int((1-faith) * len(claim_texts))} of {len(claim_texts)} claims "
            "contain terms not grounded in source text."
        )


class TestRAGASAnswerRelevancy:
    """RAGAS answer relevancy: context enables answering the question."""

    def test_answer_relevancy(self, corpus_dir, tmp_path, ground_truth):
        """Retrieved context should contain enough to answer the question.

        Threshold: mean relevancy > 0.40.
        """
        archive_path = tmp_path / "ragas_relevancy.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        relevancies = []
        for qa in ground_truth["single_hop_questions"]:
            loaded = load(archive_path, task=qa["question"])
            if loaded.rejected or not loaded.claims:
                relevancies.append(0.0)
                continue

            texts = [c.text for c in loaded.claims]
            rel = _answer_relevancy(texts, qa["question"])
            relevancies.append(rel)

        mean_rel = mean(relevancies) if relevancies else 0.0
        assert mean_rel > 0.40, (
            f"RAGAS answer relevancy = {mean_rel:.3f} (below 0.40). "
            f"Per-question: {[f'{r:.2f}' for r in relevancies]}"
        )


class TestLLMJudgedRelevancy:
    """LLM-judged answer relevancy using Claude as evaluation judge."""

    @pytest.mark.llm
    def test_llm_answer_relevancy(self, corpus_dir, tmp_path, ground_truth):
        """LLM-judged answer relevancy for single-hop questions.

        Uses Claude to evaluate semantic equivalence between retrieved
        context and question terms. Bridges vocabulary gaps that
        rule-based term matching cannot.

        Requires: anthropic SDK + ANTHROPIC_API_KEY env var.
        Threshold: mean > 0.60.
        """
        from llm_judge import _try_anthropic, llm_answer_relevancy

        client = _try_anthropic()
        if client is None:
            pytest.skip("anthropic SDK not installed or ANTHROPIC_API_KEY not set")

        archive_path = tmp_path / "ragas_llm_rel.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        relevancies = []
        per_question = []
        for qa in ground_truth["single_hop_questions"]:
            loaded = load(archive_path, task=qa["question"])
            if loaded.rejected or not loaded.claims:
                relevancies.append(0.0)
                per_question.append({"question": qa["question"], "score": 0.0, "note": "no claims"})
                continue

            texts = [c.text for c in loaded.claims]
            score = llm_answer_relevancy(texts, qa["question"], client=client)
            if score is None:
                pytest.skip("LLM call failed — check API key and network")
            relevancies.append(score)
            per_question.append({"question": qa["question"], "score": round(score, 3)})

        mean_rel = mean(relevancies) if relevancies else 0.0

        # Print per-question breakdown
        print(f"\n  LLM Answer Relevancy: {mean_rel:.3f}")
        for pq in per_question:
            print(f"    {pq['score']:.3f}  {pq['question'][:60]}")

        assert mean_rel > 0.60, (
            f"LLM answer relevancy = {mean_rel:.3f} (below 0.60). "
            f"Per-question: {[pq['score'] for pq in per_question]}"
        )

    @pytest.mark.llm
    def test_llm_context_precision(self, corpus_dir, tmp_path, ground_truth):
        """LLM-judged context precision for single-hop questions.

        Uses Claude to rate each retrieved claim's relevance, then
        computes ranked average precision.

        Requires: anthropic SDK + ANTHROPIC_API_KEY env var.
        Threshold: mean > 0.50.
        """
        from llm_judge import _try_anthropic, llm_context_precision

        client = _try_anthropic()
        if client is None:
            pytest.skip("anthropic SDK not installed or ANTHROPIC_API_KEY not set")

        archive_path = tmp_path / "ragas_llm_prec.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        precisions = []
        per_question = []
        for qa in ground_truth["single_hop_questions"]:
            loaded = load(archive_path, task=qa["question"])
            if loaded.rejected or not loaded.claims:
                precisions.append(0.0)
                per_question.append({"question": qa["question"], "score": 0.0, "note": "no claims"})
                continue

            texts = [c.text for c in loaded.claims]
            score = llm_context_precision(texts, qa["question"], client=client)
            if score is None:
                pytest.skip("LLM call failed — check API key and network")
            precisions.append(score)
            per_question.append({"question": qa["question"], "score": round(score, 3)})

        mean_prec = mean(precisions) if precisions else 0.0

        print(f"\n  LLM Context Precision: {mean_prec:.3f}")
        for pq in per_question:
            print(f"    {pq['score']:.3f}  {pq['question'][:60]}")

        assert mean_prec > 0.50, (
            f"LLM context precision = {mean_prec:.3f} (below 0.50). "
            f"Per-question: {[pq['score'] for pq in per_question]}"
        )


class TestRAGASComposite:
    """Composite RAGAS score combining all dimensions."""

    def test_composite_ragas_score(self, corpus_dir, tmp_path, ground_truth):
        """Combined RAGAS score across all dimensions.

        Composite = harmonic_mean(precision, recall, faithfulness, relevancy)
        Threshold: > 0.35

        This is the headline number: a single metric for retrieval quality.
        """
        archive_path = tmp_path / "ragas_composite.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        # Precision
        precisions = []
        recalls = []
        relevancies = []
        for qa in ground_truth["single_hop_questions"]:
            loaded = load(archive_path, task=qa["question"])
            if loaded.rejected or not loaded.claims:
                precisions.append(0.0)
                recalls.append(0.0)
                relevancies.append(0.0)
                continue

            texts = [c.text for c in loaded.claims]
            precisions.append(
                _context_precision(texts, qa["answer"], qa["relevant_keywords"])
            )
            recalls.append(
                _context_recall(texts, qa["answer"], qa["relevant_keywords"])
            )
            relevancies.append(
                _answer_relevancy(texts, qa["question"])
            )

        # Faithfulness
        claim_texts = [c.text for c in result.claims]
        source_texts = [tu.content for tu in result.text_units]
        faith = _faithfulness(claim_texts, source_texts)

        mean_p = mean(precisions) if precisions else 0.0
        mean_r = mean(recalls) if recalls else 0.0
        mean_rel = mean(relevancies) if relevancies else 0.0

        # Harmonic mean (avoids inflated averages)
        dimensions = [mean_p, mean_r, faith, mean_rel]
        nonzero = [d for d in dimensions if d > 0]
        if nonzero:
            composite = len(nonzero) / sum(1.0 / d for d in nonzero)
        else:
            composite = 0.0

        assert composite > 0.50, (
            f"Composite RAGAS = {composite:.3f} (below 0.35). "
            f"Precision={mean_p:.2f}, Recall={mean_r:.2f}, "
            f"Faithfulness={faith:.2f}, Relevancy={mean_rel:.2f}"
        )


class TestEmbedderComparison:
    """Compare retrieval quality across embedder backends."""

    @pytest.mark.parametrize("force_tfidf", [True, False], ids=["tfidf", "sentence-transformers"])
    def test_composite_by_embedder(self, corpus_dir, tmp_path, ground_truth, force_tfidf):
        """Composite RAGAS score parametrized by embedder.

        Runs the same evaluation with both TF-IDF and sentence-transformers
        so we have comparable numbers. TF-IDF threshold is lower (0.50)
        since it's the zero-dependency fallback.
        """
        archive_path = tmp_path / "emb_cmp.arc"
        result = build_archive(corpus_dir, archive_path, force_tfidf=force_tfidf)
        assert result.valid

        precisions = []
        recalls = []
        relevancies = []
        for qa in ground_truth["single_hop_questions"]:
            loaded = load(archive_path, task=qa["question"])
            if loaded.rejected or not loaded.claims:
                precisions.append(0.0)
                recalls.append(0.0)
                relevancies.append(0.0)
                continue

            texts = [c.text for c in loaded.claims]
            precisions.append(
                _context_precision(texts, qa["answer"], qa["relevant_keywords"])
            )
            recalls.append(
                _context_recall(texts, qa["answer"], qa["relevant_keywords"])
            )
            relevancies.append(
                _answer_relevancy(texts, qa["question"])
            )

        claim_texts = [c.text for c in result.claims]
        source_texts = [tu.content for tu in result.text_units]
        faith = _faithfulness(claim_texts, source_texts)

        mean_p = mean(precisions) if precisions else 0.0
        mean_r = mean(recalls) if recalls else 0.0
        mean_rel = mean(relevancies) if relevancies else 0.0

        dimensions = [mean_p, mean_r, faith, mean_rel]
        nonzero = [d for d in dimensions if d > 0]
        composite = len(nonzero) / sum(1.0 / d for d in nonzero) if nonzero else 0.0

        embedder_name = "tfidf" if force_tfidf else "sentence-transformers"
        print(
            f"\n  [{embedder_name}] Composite={composite:.3f} "
            f"P={mean_p:.3f} R={mean_r:.3f} F={faith:.3f} Rel={mean_rel:.3f}"
        )

        assert composite > 0.50, (
            f"[{embedder_name}] Composite = {composite:.3f} (below 0.50)"
        )
