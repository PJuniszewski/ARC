"""Lexical retrieval metrics over external corpora (aider, crewai).

Tests ARC's pipeline on small external fixture directories (3 files each,
~500 bytes-1KB) to check basic generalization beyond the internal corpus.

Limitations:
- Fixtures are tiny (not real projects)
- Metrics are lexical (keyword matching), not semantic
- Low threshold (composite > 0.40) reflects the small corpus size
"""

from __future__ import annotations

import re
from pathlib import Path
from statistics import mean

import pytest

from arc.builder import build_archive
from arc.loader import LoadedArchive, load


# ---------------------------------------------------------------------------
# Lexical metric implementations (shared pattern with test_retrieval_metrics.py)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "the", "and", "for", "are", "was", "that", "with", "from", "this",
    "have", "been", "will", "each", "which", "their", "other", "into",
    "also", "than", "only", "must", "should", "would", "could", "about",
    "there", "where", "these", "those", "does", "what", "when", "while",
    "after", "before", "between", "through", "during", "using",
})


def _extract_key_terms(text: str) -> list[str]:
    terms = []
    terms.extend(re.findall(r'\b\d[\d.]*\b', text))
    terms.extend(re.findall(r'\b[A-Z]{2,}\b', text))
    terms.extend(re.findall(r'\b\w+-\w+\b', text.lower()))
    terms.extend(
        w for w in re.findall(r'\b[a-z]{5,}\b', text.lower())
        if w not in _STOPWORDS
    )
    return terms


def _significant_overlap(text_a: str, text_b: str) -> float:
    words_a = set(re.findall(r'\b\w{3,}\b', text_a)) - _STOPWORDS
    words_b = set(re.findall(r'\b\w{3,}\b', text_b)) - _STOPWORDS
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / min(len(words_a), len(words_b))


def _context_precision(
    retrieved_texts: list[str],
    ground_truth_answer: str,
    relevant_keywords: list[str],
) -> float:
    if not retrieved_texts:
        return 0.0
    answer_lower = ground_truth_answer.lower()
    kw_set = {kw.lower() for kw in relevant_keywords}
    relevant_at_k = []
    for text in retrieved_texts:
        text_lower = text.lower()
        is_relevant = (
            any(kw in text_lower for kw in kw_set)
            or _significant_overlap(text_lower, answer_lower) > 0.3
        )
        relevant_at_k.append(1.0 if is_relevant else 0.0)
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
    if not required_facts:
        return 1.0
    combined = " ".join(retrieved_texts).lower()
    found = 0
    for fact in required_facts:
        fact_lower = fact.lower()
        if fact_lower in combined:
            found += 1
        else:
            words = [w for w in re.findall(r'\b\w{3,}\b', fact_lower)
                     if w not in _STOPWORDS]
            if words:
                matched = sum(1 for w in words if w in combined)
                if matched / len(words) >= 0.5:
                    found += 1
    return found / len(required_facts)


def _faithfulness(claim_texts: list[str], source_texts: list[str]) -> float:
    if not claim_texts:
        return 1.0
    combined_source = " ".join(source_texts).lower()
    grounded_count = 0
    for claim in claim_texts:
        terms = _extract_key_terms(claim)
        if not terms:
            grounded_count += 1
            continue
        grounded = sum(1 for t in terms if t.lower() in combined_source)
        if grounded / len(terms) >= 0.6:
            grounded_count += 1
    return grounded_count / len(claim_texts)


def _answer_relevancy(retrieved_texts: list[str], question: str) -> float:
    question_terms = _extract_key_terms(question)
    if not question_terms:
        return 1.0
    combined = " ".join(retrieved_texts).lower()
    found = sum(1 for t in question_terms if t.lower() in combined)
    return found / len(question_terms)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _retrieval_texts(loaded: LoadedArchive, question: str = "") -> list[str]:
    """Collect retrieval-relevant text from a loaded archive.

    Includes claims always. Adds operational content (tools, policies,
    workflow) only when the question has keyword overlap — avoids
    diluting precision with irrelevant operational noise.
    """
    texts = [c.text for c in loaded.claims]

    q_lower = question.lower()

    for t in loaded.tools:
        entry = f"{t.name}: {t.description}"
        if not question or _has_overlap(entry, q_lower):
            texts.append(entry)

    for p in loaded.policies:
        if not question or _has_overlap(p.description, q_lower):
            texts.append(p.description)

    for w in loaded.workflow:
        parts = [w.name, w.description]
        if w.agent_ref:
            parts.append(f"agent={w.agent_ref}")
        if w.tools:
            parts.append(f"tools={','.join(w.tools)}")
        if w.depends_on:
            parts.append(f"depends_on={','.join(w.depends_on)}")
        if w.expected_output:
            parts.append(w.expected_output)
        entry = " ".join(parts)
        if not question or _has_overlap(entry, q_lower):
            texts.append(entry)

    return texts


def _has_overlap(text: str, query_lower: str, min_words: int = 2) -> bool:
    """Check if text shares enough significant words with query."""
    text_words = set(re.findall(r'\b\w{3,}\b', text.lower())) - _STOPWORDS
    query_words = set(re.findall(r'\b\w{3,}\b', query_lower)) - _STOPWORDS
    return len(text_words & query_words) >= min_words


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExternalCorpusRetrieval:
    """Lexical retrieval metrics over aider and crewai fixture corpora."""

    @pytest.mark.parametrize("force_tfidf", [True, False], ids=["tfidf", "sentence-transformers"])
    def test_aider_retrieval_quality(self, tmp_path, external_ground_truth, force_tfidf):
        """Lexical metrics for aider corpus."""
        corpus_dir = FIXTURES_DIR / "aider"
        self._run_corpus_eval(
            corpus_dir, tmp_path, external_ground_truth["aider"], "aider", force_tfidf,
        )

    @pytest.mark.parametrize("force_tfidf", [True, False], ids=["tfidf", "sentence-transformers"])
    def test_crewai_retrieval_quality(self, tmp_path, external_ground_truth, force_tfidf):
        """Lexical metrics for crewai corpus."""
        corpus_dir = FIXTURES_DIR / "crewai"
        self._run_corpus_eval(
            corpus_dir, tmp_path, external_ground_truth["crewai"], "crewai", force_tfidf,
        )

    def test_cross_corpus_composite(self, tmp_path, external_ground_truth):
        """Aggregated composite across both external corpora."""
        composites = []
        for corpus_name in ["aider", "crewai"]:
            corpus_dir = FIXTURES_DIR / corpus_name
            archive_path = tmp_path / f"{corpus_name}_cross.arc"
            result = build_archive(corpus_dir, archive_path)
            assert result.valid, f"Build failed for {corpus_name}: {result.errors}"

            gt = external_ground_truth[corpus_name]
            precisions, recalls, relevancies = [], [], []

            for qa in gt["single_hop_questions"]:
                loaded = load(archive_path, task=qa["question"])
                if loaded.rejected or (not loaded.claims and not loaded.tools):
                    precisions.append(0.0)
                    recalls.append(0.0)
                    relevancies.append(0.0)
                    continue

                texts = _retrieval_texts(loaded, qa["question"])
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

            dims = [mean_p, mean_r, faith, mean_rel]
            nonzero = [d for d in dims if d > 0]
            composite = len(nonzero) / sum(1.0 / d for d in nonzero) if nonzero else 0.0
            composites.append(composite)

            print(
                f"\n  [{corpus_name}] Composite={composite:.3f} "
                f"P={mean_p:.3f} R={mean_r:.3f} F={faith:.3f} Rel={mean_rel:.3f}"
            )

        overall = mean(composites) if composites else 0.0
        print(f"\n  Cross-corpus composite: {overall:.3f}")
        assert overall > 0.40, (
            f"Cross-corpus composite = {overall:.3f} (below 0.40). "
            f"Per-corpus: {[f'{c:.3f}' for c in composites]}"
        )

    def _run_corpus_eval(
        self,
        corpus_dir: Path,
        tmp_path: Path,
        ground_truth: dict,
        corpus_name: str,
        force_tfidf: bool,
    ):
        archive_path = tmp_path / f"{corpus_name}.arc"
        result = build_archive(corpus_dir, archive_path, force_tfidf=force_tfidf)
        assert result.valid, f"Build failed for {corpus_name}: {result.errors}"

        precisions = []
        recalls = []
        relevancies = []

        for qa in ground_truth["single_hop_questions"]:
            loaded = load(archive_path, task=qa["question"])
            if loaded.rejected or (not loaded.claims and not loaded.tools):
                precisions.append(0.0)
                recalls.append(0.0)
                relevancies.append(0.0)
                continue

            texts = _retrieval_texts(loaded)
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

        dims = [mean_p, mean_r, faith, mean_rel]
        nonzero = [d for d in dims if d > 0]
        composite = len(nonzero) / sum(1.0 / d for d in nonzero) if nonzero else 0.0

        embedder_name = "tfidf" if force_tfidf else "sentence-transformers"
        print(
            f"\n  [{corpus_name}/{embedder_name}] Composite={composite:.3f} "
            f"P={mean_p:.3f} R={mean_r:.3f} F={faith:.3f} Rel={mean_rel:.3f}"
        )

        assert composite > 0.40, (
            f"[{corpus_name}/{embedder_name}] Composite = {composite:.3f} (below 0.40). "
            f"P={mean_p:.3f} R={mean_r:.3f} F={faith:.3f} Rel={mean_rel:.3f}"
        )
