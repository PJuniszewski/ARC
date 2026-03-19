"""Baseline F: Scoped + ARC refinement — two-phase retrieval for large repos.

Wraps ScopedRetrievalPipeline in the RetrievalResult interface for
benchmark comparison. Scope reduction narrows the search space via
heuristics before hybrid scoring + ARC refine.

Designed for 100k+ LOC repos where full-corpus retrieval suffers
from claim dilution.
"""

from __future__ import annotations

from pathlib import Path

from arc.compressor import _count_tokens
from arc.retrieval_pipeline import PipelineConfig, ScopedRetrievalPipeline

from .common import RetrievalResult, chunk_snapshot, compute_total_tokens


class ScopedRefinedRetriever:
    """Scoped + ARC refinement (EXPERIMENTAL).

    Two-phase scoped retrieval. Works on small repos (<30K LOC) but scope
    inference fails on deep directory structures (>100K LOC). See Django
    benchmark: recall 0.242 vs hybrid_arc 0.762.

    Not recommended for production use. Use HybridRefinedRetriever instead.

    Phase 1: Scope reduction (path/symbol/directory heuristics)
    Phase 2: Hybrid scoring on scoped chunks
    Refine: ARC claim extraction + code preservation + evidence map
    """

    def __init__(self, source_dir: Path, config: PipelineConfig | None = None):
        self.resources, self.text_units = chunk_snapshot(source_dir)
        self.total_tokens = compute_total_tokens(self.text_units)
        self.pipeline = ScopedRetrievalPipeline(
            self.resources, self.text_units, config,
        )

    def query(self, question: str, top_k: int = 10) -> RetrievalResult:
        """Retrieve via scoped pipeline, return standard RetrievalResult."""
        result = self.pipeline.query(question, top_k)
        refinement = result.refinement

        # Convert RefinementResult → RetrievalResult (same as hybrid_refined.py)
        texts = [item.text for item in refinement.items]
        ids = [item.id for item in refinement.items]
        metadata = [
            refinement.evidence_map.get(item.id, {}) for item in refinement.items
        ]
        loaded_tokens = sum(_count_tokens(t) for t in texts)

        return RetrievalResult(
            texts=texts,
            ids=ids,
            scores=[item.confidence * item.retrieval_score for item in refinement.items],
            metadata=metadata,
            loaded_tokens=loaded_tokens,
            total_tokens=self.total_tokens,
            has_provenance=True,
        )
