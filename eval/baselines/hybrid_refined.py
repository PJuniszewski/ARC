"""Baseline E: Hybrid + ARC refinement — post-retrieval claim extraction and code preservation.

Uses hybrid retrieval (vector + keyword + heading boost) to fetch 30 chunks,
then refines them through ARC's extraction pipeline:
- Code chunks kept verbatim (1.5x weight)
- Doc chunks → claim extraction + deduplication (0.7x weight)
- Full evidence map for traceability

This bypasses hybrid's dynamic top-k cap by scoring directly via the store.
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
)
from arc.embeddings import VectorStore, get_embedder
from arc.models import Resource, TextUnit
from arc.refinement import ChunkWithMeta, refine

from .common import RetrievalResult, chunk_snapshot, compute_total_tokens


class HybridRefinedRetriever:
    """Hybrid retrieval + ARC post-retrieval refinement.

    Fetches retrieval_k chunks via direct hybrid scoring (bypassing the
    dynamic top-k cap), then refines through code/docs classification,
    claim extraction, deduplication, and weighted ranking.
    """

    def __init__(self, source_dir: Path, retrieval_k: int = 30):
        self.resources, self.text_units = chunk_snapshot(source_dir)
        self.total_tokens = compute_total_tokens(self.text_units)
        self.retrieval_k = retrieval_k

        # Build lookup dicts
        self.text_units_by_id = {tu.id: tu for tu in self.text_units}
        self.resources_by_id = {r.id: r for r in self.resources}

        # Build embeddings (same as HybridChunkRetriever)
        texts = [tu.content for tu in self.text_units]
        self.embedder = get_embedder(force_tfidf=False)
        self.embedder.fit(texts)

        self.store = VectorStore(index_info=self.embedder.get_index_info())
        for tu in self.text_units:
            vec = self.embedder.embed(tu.content)
            self.store.add(tu.id, vec, tu.content, {"resource_id": tu.resource_id})

    def query(self, question: str, top_k: int = 10) -> RetrievalResult:
        """Retrieve and refine chunks using hybrid scoring + ARC refinement."""
        # Step 1: Direct hybrid scoring (bypass dynamic top-k cap)
        query_vec = self.embedder.embed(question)
        all_results = self.store.search(query_vec, top_k=len(self.store.ids))

        query_tokens = set(self.embedder._tokenize(question))
        content_query_tokens = query_tokens - STOP_WORDS

        scored: list[tuple[str, float, str]] = []
        for cid, vscore, text in all_results:
            chunk_tokens = set(self.embedder._tokenize(text))
            overlap = len(query_tokens & chunk_tokens)
            kw_boost = overlap / len(query_tokens) if query_tokens else 0.0

            heading_boost = 0.0
            if ": " in text:
                heading = text[: text.index(": ")]
                heading_tokens = set(self.embedder._tokenize(heading)) - STOP_WORDS
                if heading_tokens:
                    heading_match = len(heading_tokens & content_query_tokens) / len(
                        heading_tokens
                    )
                    if heading_match >= HEADING_MATCH_THRESHOLD:
                        heading_boost = HEADING_BOOST_WEIGHT * heading_match

            hybrid = vscore + KEYWORD_BOOST_WEIGHT * kw_boost + heading_boost
            scored.append((cid, hybrid, text))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Take top retrieval_k (no dynamic cap — that's the whole point)
        top_chunks = [
            (cid, s, t) for cid, s, t in scored[: self.retrieval_k] if s >= MIN_SCORE
        ]
        if not top_chunks and scored:
            top_chunks = scored[:3]

        # Step 2: Package as ChunkWithMeta
        chunks_with_meta: list[ChunkWithMeta] = []
        for cid, score, text in top_chunks:
            tu = self.text_units_by_id.get(cid)
            resource = None
            if tu:
                resource = self.resources_by_id.get(tu.resource_id)

            chunks_with_meta.append(
                ChunkWithMeta(
                    text=text,
                    chunk_id=cid,
                    score=score,
                    text_unit=tu,
                    resource=resource,
                )
            )

        # Step 3: Refine (pass question for mode-aware refinement)
        result = refine(
            chunks_with_meta,
            self.text_units_by_id,
            self.resources_by_id,
            max_items=top_k,
            question=question,
        )

        # Step 4: Convert to RetrievalResult
        texts = [item.text for item in result.items]
        ids = [item.id for item in result.items]
        metadata = [result.evidence_map.get(item.id, {}) for item in result.items]
        loaded_tokens = sum(_count_tokens(t) for t in texts)

        return RetrievalResult(
            texts=texts,
            ids=ids,
            scores=[item.confidence * item.retrieval_score for item in result.items],
            metadata=metadata,
            loaded_tokens=loaded_tokens,
            total_tokens=self.total_tokens,
            has_provenance=True,
        )
