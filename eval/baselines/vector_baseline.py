"""Baseline B: Vector chunk retrieval — sentence-transformers, no semantic layer."""

from __future__ import annotations

from pathlib import Path

from arc.compressor import _count_tokens
from arc.embeddings import VectorStore, get_embedder

from .common import RetrievalResult, chunk_snapshot, compute_total_tokens


class VectorChunkRetriever:
    """Chunks -> all-MiniLM-L6-v2(384) -> VectorStore -> top-k cosine.

    Falls back to TF-IDF if sentence-transformers is not installed.
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
        """Retrieve top-k chunks by vector cosine similarity."""
        query_vec = self.embedder.embed(question)
        results = self.store.search(query_vec, top_k=top_k)

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
