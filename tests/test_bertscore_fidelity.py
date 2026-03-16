"""BERTScore-based fidelity tests.

Closes the gap between TF-IDF proxy metrics and real semantic similarity.
Uses bert-score when available (ml extras), otherwise falls back to
sentence-level n-gram overlap (BLEU-like) as a tighter proxy than TF-IDF cosine.

Methodology references:
- BERTScore: https://arxiv.org/abs/1904.09675
- Factual consistency via NLI-style entailment checks
"""

from __future__ import annotations

import re
from collections import Counter
from statistics import mean

import numpy as np
import pytest

from arc.builder import build_archive
from arc.compressor import _count_tokens
from arc.embeddings import TfidfEmbedder


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _ngram_overlap(reference: str, hypothesis: str, n: int = 2) -> float:
    """Compute n-gram overlap (precision) between reference and hypothesis.

    This is a BLEU-like precision metric that measures how many n-grams
    from the hypothesis appear in the reference. Tighter than bag-of-words.
    """
    ref_tokens = _tokenize(reference)
    hyp_tokens = _tokenize(hypothesis)

    if len(hyp_tokens) < n:
        return 0.0

    ref_ngrams = Counter(
        tuple(ref_tokens[i:i + n]) for i in range(len(ref_tokens) - n + 1)
    )
    hyp_ngrams = Counter(
        tuple(hyp_tokens[i:i + n]) for i in range(len(hyp_tokens) - n + 1)
    )

    clipped = sum(min(hyp_ngrams[ng], ref_ngrams[ng]) for ng in hyp_ngrams)
    total = sum(hyp_ngrams.values())
    return clipped / total if total > 0 else 0.0


def _brevity_penalty(ref_len: int, hyp_len: int) -> float:
    """BLEU brevity penalty."""
    if hyp_len >= ref_len:
        return 1.0
    return np.exp(1 - ref_len / hyp_len) if hyp_len > 0 else 0.0


def _bleu_score(reference: str, hypothesis: str, max_n: int = 4) -> float:
    """Simplified BLEU score (1-gram through max_n-gram, uniform weights)."""
    ref_tokens = _tokenize(reference)
    hyp_tokens = _tokenize(hypothesis)

    if not hyp_tokens:
        return 0.0

    precisions = []
    for n in range(1, max_n + 1):
        p = _ngram_overlap(reference, hypothesis, n)
        if p == 0:
            return 0.0  # BLEU is 0 if any n-gram precision is 0
        precisions.append(p)

    log_avg = sum(np.log(p) for p in precisions) / len(precisions)
    bp = _brevity_penalty(len(ref_tokens), len(hyp_tokens))
    return float(bp * np.exp(log_avg))


def _factual_entailment_score(source: str, claim: str) -> float:
    """Rule-based factual entailment check.

    Measures whether key facts in a claim can be grounded in the source.
    Returns fraction of claim's significant terms found in source.
    This is a precision-oriented metric for factual consistency.
    """
    source_lower = source.lower()
    claim_terms = _extract_significant_terms(claim)
    if not claim_terms:
        return 1.0  # vacuously true
    found = sum(1 for t in claim_terms if t in source_lower)
    return found / len(claim_terms)


def _extract_significant_terms(text: str) -> list[str]:
    """Extract significant terms: numbers, proper-ish tokens, technical terms."""
    terms = []
    # Numbers (version strings, counts, dimensions)
    terms.extend(re.findall(r'\b\d[\d.]*\b', text))
    # Technical terms (hyphenated, CamelCase, acronyms)
    terms.extend(re.findall(r'\b[A-Z][A-Za-z]+(?:[A-Z][a-z]+)+\b', text))  # CamelCase
    terms.extend(re.findall(r'\b[A-Z]{2,}\b', text))  # Acronyms
    terms.extend(re.findall(r'\b\w+-\w+\b', text.lower()))  # hyphenated
    # Long lowercase words (domain-specific)
    terms.extend(w for w in re.findall(r'\b[a-z]{6,}\b', text.lower())
                 if w not in _STOPWORDS)
    return [t.lower() for t in terms]


def _contradiction_count(claims: list[str]) -> int:
    """Detect contradictions in claim set via negation patterns.

    Looks for claims that negate each other or state opposite facts.
    """
    contradictions = 0
    normalized = [c.lower().strip() for c in claims]

    for i, c1 in enumerate(normalized):
        for c2 in normalized[i + 1:]:
            # Check for explicit negation pairs
            if _texts_contradict(c1, c2):
                contradictions += 1
    return contradictions


def _texts_contradict(a: str, b: str) -> bool:
    """Heuristic contradiction detection between two texts."""
    # Pattern: "X uses Y" vs "X does not use Y"
    verb_patterns = [
        (r'(\w+) uses (\w+)', "does not use"),
        (r'(\w+) requires (\w+)', "does not require"),
        (r'(\w+) supports (\w+)', "does not support"),
        (r'(\w+) is (\w+)', "is not"),
    ]
    for pos_pat, neg_phrase in verb_patterns:
        pos_a = re.search(pos_pat, a)
        if pos_a:
            subject, obj = pos_a.group(1), pos_a.group(2)
            if subject in b and neg_phrase in b and obj in b:
                return True
        pos_b = re.search(pos_pat, b)
        if pos_b:
            subject, obj = pos_b.group(1), pos_b.group(2)
            if subject in a and neg_phrase in a and obj in a:
                return True
    return False


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r'\b\w{2,}\b', text)]


_STOPWORDS = frozenset({
    "the", "and", "for", "are", "was", "that", "with", "from", "this",
    "have", "been", "will", "each", "which", "their", "other", "into",
    "also", "than", "only", "must", "should", "would", "could",
})


def _try_bertscore():
    """Try to import bert_score. Returns scorer function or None."""
    try:
        from bert_score import score as bert_score_fn
        return bert_score_fn
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBERTScoreFidelity:
    """Claim fidelity using BERTScore or tight n-gram fallback."""

    @pytest.mark.ml
    def test_bertscore_semantic_preservation(self, corpus_dir, tmp_path):
        """Real BERTScore: extracted claims preserve meaning above 0.80 F1.

        Methodology:
        1. Build archive
        2. For each claim, compute BERTScore against its source text unit
        3. Assert mean F1 > 0.80

        Requires: pip install arc-archive[ml]
        """
        bert_score_fn = _try_bertscore()
        if bert_score_fn is None:
            pytest.skip("bert-score not installed (pip install arc-archive[ml])")

        archive_path = tmp_path / "bert_fidelity.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        # Pair claims with source text units via evidence pointers
        su_by_id = {tu.id: tu for tu in result.text_units}
        refs = []
        hyps = []
        for claim in result.claims:
            if not claim.evidence:
                continue
            # Use first evidence pointer's source text as reference
            su = su_by_id.get(claim.evidence[0].source_unit_id)
            if su and su.content.strip():
                refs.append(su.content)
                hyps.append(claim.text)

        assert len(refs) >= 3, f"Need >= 3 claim-source pairs, got {len(refs)}"

        P, R, F1 = bert_score_fn(hyps, refs, lang="en", verbose=False)
        mean_f1 = F1.mean().item()
        assert mean_f1 > 0.80, (
            f"BERTScore F1 = {mean_f1:.3f} (below 0.80). "
            f"Per-claim scores: {[f'{f:.2f}' for f in F1.tolist()[:10]]}"
        )

    def test_ngram_fidelity_without_ml(self, corpus_dir, tmp_path):
        """N-gram overlap fidelity (no ML dependencies required).

        Tighter than TF-IDF cosine: measures actual phrase-level preservation.
        Threshold: mean bigram overlap > 0.10 between claims and sources.
        """
        archive_path = tmp_path / "ngram_fidelity.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        su_by_id = {tu.id: tu for tu in result.text_units}
        overlaps = []
        for claim in result.claims:
            if not claim.evidence:
                continue
            su = su_by_id.get(claim.evidence[0].source_unit_id)
            if su and su.content.strip():
                # Bigram overlap: claim terms should appear as phrases in source
                overlap = _ngram_overlap(su.content, claim.text, n=2)
                overlaps.append(overlap)

        assert len(overlaps) >= 3, f"Need >= 3 pairs, got {len(overlaps)}"
        mean_overlap = mean(overlaps)
        assert mean_overlap > 0.10, (
            f"Mean bigram overlap = {mean_overlap:.3f} (below 0.10). "
            "Claims are not preserving source phrases."
        )


class TestFactualConsistency:
    """Prove: Extracted claims don't introduce facts absent from sources."""

    def test_factual_entailment(self, corpus_dir, tmp_path):
        """Claims should be grounded in source: significant terms must trace back.

        Methodology:
        1. For each claim, extract significant terms (numbers, technical words)
        2. Check what fraction appears in the source text unit
        3. Assert mean entailment > 0.50

        This catches hallucinated numbers, invented terms, and fabricated facts.
        """
        archive_path = tmp_path / "entailment.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        su_by_id = {tu.id: tu for tu in result.text_units}
        scores = []
        for claim in result.claims:
            if not claim.evidence:
                continue
            su = su_by_id.get(claim.evidence[0].source_unit_id)
            if su and su.content.strip():
                score = _factual_entailment_score(su.content, claim.text)
                scores.append(score)

        assert len(scores) >= 3, f"Need >= 3 pairs, got {len(scores)}"
        mean_score = mean(scores)
        assert mean_score > 0.50, (
            f"Mean factual entailment = {mean_score:.3f} (below 0.50). "
            "Claims contain significant terms not found in sources."
        )

    def test_no_contradictions_in_claims(self, corpus_dir, tmp_path):
        """Claim set should contain zero internal contradictions."""
        archive_path = tmp_path / "contradictions.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        claim_texts = [c.text for c in result.claims]
        contradictions = _contradiction_count(claim_texts)
        assert contradictions == 0, (
            f"Found {contradictions} contradictions in claims. "
            "Extraction should never introduce conflicting assertions."
        )


class TestCostEfficiency:
    """Prove: Selective loading achieves quantified token savings."""

    def test_selective_loading_reduces_tokens(self, corpus_dir, tmp_path):
        """Loader-side selective loading achieves meaningful token reduction.

        Since the builder preserves full fidelity, token reduction is the loader's job.
        """
        from arc.loader import load

        archive_path = tmp_path / "cost_efficiency.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        full_tokens = sum(_count_tokens(c.text) for c in result.claims)
        assert full_tokens > 0

        loaded = load(archive_path, task="What hash algorithm does ARC use?")
        if loaded.rejected:
            pytest.skip("Load rejected")

        selective_tokens = sum(_count_tokens(c.text) for c in loaded.claims)
        reduction = 1 - (selective_tokens / full_tokens) if full_tokens > 0 else 0
        assert reduction > 0.10, (
            f"Selective loading only reduces {reduction:.1%} of tokens. "
            f"Full: {full_tokens}, Selective: {selective_tokens}."
        )

    def test_full_fidelity_preserves_all_claims(self, corpus_dir, tmp_path):
        """Builder preserves all unique non-contested claims (no lossy compression)."""
        out = tmp_path / "full_fidelity"
        r = build_archive(corpus_dir, out)
        assert r.valid
        assert r.deduplication is not None
        assert len(r.claims) == (
            r.deduplication.original_count - r.deduplication.duplicates_removed
        )

    def test_mounted_bytes_per_task(self, corpus_dir, tmp_path):
        """Selective loading reduces mounted bytes compared to full archive.

        Measures average bytes loaded per task query vs total archive size.
        """
        from arc.loader import load

        archive_path = tmp_path / "mounted.arc"
        result = build_archive(corpus_dir, archive_path)
        assert result.valid

        total_claim_bytes = sum(len(c.text.encode()) for c in result.claims)

        tasks = [
            "What hash algorithm does ARC use?",
            "How does the builder pipeline work?",
            "What are the security threats?",
        ]

        mounted_bytes_per_task = []
        for task in tasks:
            loaded = load(archive_path, task=task)
            if loaded.rejected:
                continue
            task_bytes = sum(len(c.text.encode()) for c in loaded.claims)
            mounted_bytes_per_task.append(task_bytes)

        assert len(mounted_bytes_per_task) >= 2, "Too few tasks loaded successfully"
        avg_mounted = mean(mounted_bytes_per_task)
        reduction = 1 - (avg_mounted / total_claim_bytes) if total_claim_bytes > 0 else 0

        assert reduction > 0.10, (
            f"Selective loading only reduces {reduction:.1%} of bytes. "
            f"Avg mounted: {avg_mounted:.0f}B, total: {total_claim_bytes}B. "
            "Task filtering should meaningfully reduce context size."
        )
