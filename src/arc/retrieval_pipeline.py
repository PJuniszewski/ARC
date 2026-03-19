"""Two-phase scoped retrieval pipeline for large repositories.

Reduces search space via scope heuristics before hybrid scoring,
then feeds ARC refine() unchanged. Designed for 100k+ LOC repos
where naive full-corpus retrieval suffers from claim dilution.

Pipeline:
    query → infer_scope() → phase 1 (path filtering)
          → phase 2 (hybrid scoring on scoped chunks)
          → refine() → structured output

Key design decisions:
1. Embeddings built once over full corpus (not per-scope)
2. Phase 1 is O(n) string matching — no embeddings, no ML
3. Phase 2 reuses exact hybrid scoring from hybrid_refined.py
4. refine() called unchanged
5. Fallback: skip phase 1 when scope includes >80% of chunks
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import (
    HEADING_BOOST_WEIGHT,
    HEADING_MATCH_THRESHOLD,
    KEYWORD_BOOST_WEIGHT,
    MAX_PHASE1_CHUNKS,
    MAX_PHASE2_CHUNKS,
    MAX_SCOPE_FILES,
    MIN_SCORE,
    SCOPED_TOKEN_BUDGET,
    STOP_WORDS,
)
from .embeddings import VectorStore, get_embedder
from .models import Resource, TextUnit
from .refinement import ChunkWithMeta, RefinementResult, refine
from .scope import RepoMetadata, ScopePlan, build_repo_metadata, infer_scope


# ── Configuration ────────────────────────────────────────────────


@dataclass
class PipelineConfig:
    """Configuration for the scoped retrieval pipeline."""

    max_scope_files: int = MAX_SCOPE_FILES
    max_phase1_chunks: int = MAX_PHASE1_CHUNKS
    max_phase2_chunks: int = MAX_PHASE2_CHUNKS
    token_budget: int = SCOPED_TOKEN_BUDGET
    max_refined_items: int = 15
    mode: str = "auto"
    enable_cache: bool = False


# ── Result ───────────────────────────────────────────────────────


@dataclass
class PipelineResult:
    """Output of the scoped retrieval pipeline."""

    refinement: RefinementResult = field(default_factory=RefinementResult)
    scope_plan: ScopePlan = field(default_factory=ScopePlan)
    phase1_chunk_count: int = 0
    phase2_chunk_count: int = 0
    total_chunks: int = 0
    scope_reduction_ratio: float = 0.0


# ── Pipeline ─────────────────────────────────────────────────────


class ScopedRetrievalPipeline:
    """Two-phase retrieval: scope reduction → hybrid scoring → ARC refine.

    Phase 1: Pure path/string matching to filter chunks by scope.
    Phase 2: Hybrid vector + keyword scoring on scoped chunks only.
    Refine: Existing ARC refinement (unchanged).
    """

    def __init__(
        self,
        resources: list[Resource],
        text_units: list[TextUnit],
        config: PipelineConfig | None = None,
    ):
        self.config = config or PipelineConfig()
        self.resources = resources
        self.text_units = text_units

        # Build lookup dicts (same pattern as HybridRefinedRetriever)
        self.text_units_by_id = {tu.id: tu for tu in text_units}
        self.resources_by_id = {r.id: r for r in resources}

        # Build repo metadata for scope inference
        self.repo_meta = build_repo_metadata(resources, text_units)

        # Resource ID → locator for path-based filtering
        self._resource_id_to_path = {r.id: r.locator for r in resources}

        # Build embeddings over ALL chunks (once, not per-scope)
        texts = [tu.content for tu in text_units]
        self.embedder = get_embedder(force_tfidf=False)
        self.embedder.fit(texts)

        self.store = VectorStore(index_info=self.embedder.get_index_info())
        for tu in text_units:
            vec = self.embedder.embed(tu.content)
            self.store.add(tu.id, vec, tu.content, {"resource_id": tu.resource_id})

    def query(self, question: str, top_k: int = 10) -> PipelineResult:
        """Execute scoped retrieval pipeline.

        1. Infer scope from question
        2. Phase 1: filter chunks to scope (path matching)
        3. Phase 2: hybrid score scoped chunks
        4. Refine via existing ARC pipeline
        """
        total_chunks = len(self.text_units)

        # Step 1: Infer scope
        scope_plan = infer_scope(question, self.repo_meta, mode=self.config.mode)

        # Step 2: Phase 1 — path-based chunk filtering
        scoped_ids = self._phase1(scope_plan)

        # Fallback: if scope includes >80% of chunks, skip (no benefit)
        if len(scoped_ids) > 0.8 * total_chunks:
            scoped_ids = {tu.id for tu in self.text_units}

        phase1_count = len(scoped_ids)

        # Step 3: Phase 2 — hybrid scoring on scoped chunks
        chunks_with_meta = self._phase2(question, scoped_ids)
        phase2_count = len(chunks_with_meta)

        # Step 4: Refine (EXISTING, UNCHANGED)
        result = refine(
            chunks_with_meta,
            self.text_units_by_id,
            self.resources_by_id,
            max_items=top_k,
            token_budget=self.config.token_budget,
            question=question,
        )

        scope_reduction = 1.0 - (phase1_count / total_chunks) if total_chunks > 0 else 0.0

        return PipelineResult(
            refinement=result,
            scope_plan=scope_plan,
            phase1_chunk_count=phase1_count,
            phase2_chunk_count=phase2_count,
            total_chunks=total_chunks,
            scope_reduction_ratio=scope_reduction,
        )

    def _phase1(self, scope_plan: ScopePlan) -> set[str]:
        """Phase 1: Pure path/string matching — no embeddings.

        Filters text unit IDs to those belonging to scoped file paths.
        Applies preferred_source_types filter.
        Caps at max_phase1_chunks.
        Falls back to full corpus if too few chunks match.
        """
        if not scope_plan.candidate_paths:
            # No scope signals — return all chunks
            return {tu.id for tu in self.text_units}

        # Map candidate paths to their chunk IDs
        scoped_ids: set[str] = set()
        for path in scope_plan.candidate_paths:
            chunk_ids = self.repo_meta.path_to_chunk_ids.get(path, [])
            # Apply source type filter
            ext = self.repo_meta.path_to_extension.get(path, "")
            source_type = _ext_to_source_type(ext)
            if source_type in scope_plan.preferred_source_types or not scope_plan.preferred_source_types:
                scoped_ids.update(chunk_ids)

        # Fallback: if too few, expand to full corpus
        if len(scoped_ids) < 5:
            return {tu.id for tu in self.text_units}

        # Cap at max_phase1_chunks
        if len(scoped_ids) > self.config.max_phase1_chunks:
            # Keep chunks from highest-priority paths first
            limited: set[str] = set()
            for path in scope_plan.candidate_paths:
                for cid in self.repo_meta.path_to_chunk_ids.get(path, []):
                    limited.add(cid)
                    if len(limited) >= self.config.max_phase1_chunks:
                        return limited
            return limited

        return scoped_ids

    def _phase2(
        self, question: str, scoped_tu_ids: set[str],
    ) -> list[ChunkWithMeta]:
        """Phase 2: Hybrid scoring restricted to scoped chunks.

        Same scoring formula as HybridRefinedRetriever.query():
            hybrid = vscore + 0.3 * kw_boost + heading_boost

        But only scores chunks in scoped_tu_ids.
        """
        # Score all chunks in store
        query_vec = self.embedder.embed(question)
        all_results = self.store.search(query_vec, top_k=len(self.store.ids))

        query_tokens = set(self.embedder._tokenize(question))
        content_query_tokens = query_tokens - STOP_WORDS

        scored: list[tuple[str, float, str]] = []
        for cid, vscore, text in all_results:
            # Restrict to scoped chunks
            if cid not in scoped_tu_ids:
                continue

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

        # Take top max_phase2_chunks, filter by MIN_SCORE
        top_chunks = [
            (cid, s, t) for cid, s, t in scored[: self.config.max_phase2_chunks]
            if s >= MIN_SCORE
        ]
        if not top_chunks and scored:
            top_chunks = scored[:3]

        # Package as ChunkWithMeta (same as hybrid_refined.py)
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

        return chunks_with_meta


# ── Helpers ──────────────────────────────────────────────────────


_CODE_EXTS = frozenset({".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".rb"})
_DOCS_EXTS = frozenset({".md", ".rst", ".txt", ".html"})


def _ext_to_source_type(ext: str) -> str:
    """Map file extension to source type category."""
    if ext in _CODE_EXTS:
        return "code"
    if ext in _DOCS_EXTS:
        return "docs"
    return "code"  # default to code for unknown
