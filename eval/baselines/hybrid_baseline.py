"""Baseline C: Hybrid chunk retrieval — vector + keyword + heading boost, no semantic layer.

This is the critical ablation baseline. It uses the exact same hybrid scoring
formula as arc.loader._filter_by_task (line 325) but applied to raw chunks
instead of extracted claims, and without evidence graph expansion.

If ARC beats this baseline, the advantage comes from claim extraction and/or
the evidence graph — not just the hybrid scoring formula.
"""

from __future__ import annotations

from pathlib import Path

from arc.compressor import _count_tokens
from arc.config import (
    HEADING_BOOST_WEIGHT,
    HEADING_MATCH_THRESHOLD,
    KEYWORD_BOOST_WEIGHT,
    MIN_SCORE,
    STOP_WORDS,
    TOP_K_BASE,
    TOP_K_FLOOR,
    TOP_K_RATIO,
)
from arc.embeddings import VectorStore, get_embedder

from .common import RetrievalResult, chunk_snapshot, compute_total_tokens


class HybridChunkRetriever:
    """Chunks -> vector + 0.3*keyword + heading boost -> top-k hybrid.

    Same scoring formula as loader._filter_by_task but on raw chunks,
    no claim extraction, no evidence graph.
    """

    def __init__(self, source_dir: Path):
        self.resources, self.text_units = chunk_snapshot(source_dir)
        self.total_tokens = compute_total_tokens(self.text_units)

        texts = [tu.content for tu in self.text_units]
        self.embedder = get_embedder(force_tfidf=False)
        self.embedder.fit(texts)

        self.store = VectorStore(index_info=self.embedder.get_index_info())
        for tu in self.text_units:
            vec = self.embedder.embed(tu.content)
            self.store.add(tu.id, vec, tu.content, {"resource_id": tu.resource_id})

    def query(self, question: str, top_k: int = 10) -> RetrievalResult:
        """Retrieve chunks using hybrid vector + keyword + heading scoring."""
        query_vec = self.embedder.embed(question)

        # Search all, then re-score with hybrid formula
        all_results = self.store.search(query_vec, top_k=len(self.store.ids))

        query_tokens = set(self.embedder._tokenize(question))
        content_query_tokens = query_tokens - STOP_WORDS

        scored: list[tuple[str, float, str]] = []
        for cid, vscore, text in all_results:
            chunk_tokens = set(self.embedder._tokenize(text))
            overlap = len(query_tokens & chunk_tokens)
            kw_boost = overlap / len(query_tokens) if query_tokens else 0.0

            # Heading boost — same logic as loader._filter_by_task
            heading_boost = 0.0
            if ": " in text:
                heading = text[:text.index(": ")]
                heading_tokens = set(self.embedder._tokenize(heading)) - STOP_WORDS
                if heading_tokens:
                    heading_match = len(heading_tokens & content_query_tokens) / len(heading_tokens)
                    if heading_match >= HEADING_MATCH_THRESHOLD:
                        heading_boost = HEADING_BOOST_WEIGHT * heading_match

            hybrid = vscore + KEYWORD_BOOST_WEIGHT * kw_boost + heading_boost
            scored.append((cid, hybrid, text))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Dynamic top-K with minimum score — same as loader
        dynamic_k = min(TOP_K_BASE, max(TOP_K_FLOOR, int(len(self.text_units) * TOP_K_RATIO)))
        effective_k = min(top_k, dynamic_k)

        results = [(cid, s, t) for cid, s, t in scored[:effective_k] if s >= MIN_SCORE]
        if not results and scored:
            results = scored[:3]

        texts = [text for _, _, text in results]
        ids = [cid for cid, _, _ in results]
        scores = [score for _, score, _ in results]
        loaded_tokens = sum(_count_tokens(t) for t in texts)

        return RetrievalResult(
            texts=texts,
            ids=ids,
            scores=scores,
            loaded_tokens=loaded_tokens,
            total_tokens=self.total_tokens,
            has_provenance=False,
        )
