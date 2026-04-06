"""Baseline E: Hybrid + ARC refinement — post-retrieval claim extraction and code preservation.

Uses hybrid retrieval (vector + keyword + heading boost) to fetch 30 chunks,
then refines them through ARC's extraction pipeline:
- Code chunks kept verbatim (1.5x weight)
- Doc chunks → claim extraction + deduplication (0.7x weight)
- Full evidence map for traceability

This bypasses hybrid's dynamic top-k cap by scoring directly via the store.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from arc.compressor import _count_tokens
import re as _re

from arc.config import (
    BOILERPLATE_PENALTY,
    CROSS_FILE_RETRIEVAL_K,
    FEATURE_RETRIEVAL_K,
    HEADING_BOOST_WEIGHT,
    HEADING_MATCH_THRESHOLD,
    KEYWORD_BOOST_WEIGHT,
    MAX_EXPANSION_TOTAL,
    MAX_SIBLINGS_PER_FILE,
    MIGRATION_SCORE_PENALTY,
    MIN_SCORE,
    PATH_BOOST_WEIGHT,
    SHORT_CHUNK_PENALTY,
    SHORT_CHUNK_TOKEN_THRESHOLD,
    SIBLING_MIN_SCORE,
    STOP_WORDS,
)
from arc.embeddings import VectorStore, get_embedder
from arc.imports import build_import_graph, ImportGraph
from arc.models import Resource, TextUnit
from arc.refinement import ChunkWithMeta, detect_mode, refine

from .common import RetrievalResult, chunk_snapshot, compute_total_tokens


_EXT_RE = _re.compile(r'\.\w+$')


def _path_tokens(locator: str) -> set[str]:
    """Extract stemmed tokens from a file path (directory names + filename without extension)."""
    from arc.embeddings import TfidfEmbedder
    stem = TfidfEmbedder._stem
    parts = locator.replace("\\", "/").split("/")
    tokens: set[str] = set()
    for part in parts:
        clean = _EXT_RE.sub("", part).lower()
        for word in _re.findall(r'\b\w{2,}\b', clean):
            if word not in ("__init__", "py", "js", "ts"):
                tokens.add(stem(word))
    return tokens


def _path_boost(
    path_toks: set[str],
    content_query_tokens: set[str],
    idf: dict[str, float],
    max_idf: float,
) -> float:
    """IDF-weighted path-component boost.

    For each query token that prefix-matches a path token, add a boost
    proportional to the query token's IDF (rare tokens → stronger signal).
    """
    if not path_toks or not content_query_tokens or max_idf <= 0:
        return 0.0
    boost = 0.0
    for qt in content_query_tokens:
        for pt in path_toks:
            if len(pt) >= 3 and len(qt) >= 3 and (qt.startswith(pt) or pt.startswith(qt)):
                token_idf = idf.get(qt, 1.0) / max_idf
                boost += PATH_BOOST_WEIGHT * token_idf
                break  # one match per query token
    return min(boost, 0.5)  # cap total path boost


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

        # Reverse lookup: resource_id -> text units (sorted by span start)
        self.tus_by_resource: dict[str, list[TextUnit]] = defaultdict(list)
        for tu in self.text_units:
            self.tus_by_resource[tu.resource_id].append(tu)
        for rid in self.tus_by_resource:
            self.tus_by_resource[rid].sort(key=lambda tu: tu.span[0])

        # Build embeddings (same as HybridChunkRetriever)
        texts = [tu.content for tu in self.text_units]
        self.embedder = get_embedder(force_tfidf=False)
        self.embedder.fit(texts)

        self.store = VectorStore(index_info=self.embedder.get_index_info())
        for tu in self.text_units:
            vec = self.embedder.embed(tu.content)
            self.store.add(tu.id, vec, tu.content, {"resource_id": tu.resource_id})

        # Precompute path tokens per resource for path-based scoring
        self._resource_path_tokens: dict[str, set[str]] = {}
        for r in self.resources:
            self._resource_path_tokens[r.id] = _path_tokens(r.locator)

        # IDF stats for path boost weighting (works for both TF-IDF and ST embedders)
        self._idf = getattr(self.embedder, 'idf', {})
        self._max_idf = max(self._idf.values()) if self._idf else 1.0

        # Import graph for cross-file boost
        self._import_graph = build_import_graph(self.resources, source_dir)
        # Locator → resource_id mapping for graph lookups
        self._locator_to_rid: dict[str, str] = {r.locator: r.id for r in self.resources}

    def query(self, question: str, top_k: int = 10) -> RetrievalResult:
        """Retrieve and refine chunks using hybrid scoring + ARC refinement."""
        # Step 0: Dynamic retrieval_k based on query mode
        mode = detect_mode(question)
        if mode.name == "cross_file":
            effective_k = max(self.retrieval_k, CROSS_FILE_RETRIEVAL_K)
        elif mode.name == "feature":
            effective_k = max(self.retrieval_k, FEATURE_RETRIEVAL_K)
        else:
            effective_k = self.retrieval_k

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

            # Retrieval hygiene: penalize noisy chunks
            penalty = 1.0
            tu = self.text_units_by_id.get(cid)
            if tu:
                res = self.resources_by_id.get(tu.resource_id)
                if res:
                    loc = res.locator
                    fname = loc.rsplit("/", 1)[-1] if "/" in loc else loc
                    # Migration data files (digit-prefixed like 0001_initial.py)
                    if "/migrations/" in loc and fname[:1].isdigit():
                        penalty *= MIGRATION_SCORE_PENALTY
                    # Boilerplate __init__.py with trivial content
                    if fname == "__init__.py" and _count_tokens(text) <= SHORT_CHUNK_TOKEN_THRESHOLD:
                        penalty *= BOILERPLATE_PENALTY
            # Short chunks rarely contain cross-file reasoning context
            if _count_tokens(text) <= SHORT_CHUNK_TOKEN_THRESHOLD:
                penalty *= SHORT_CHUNK_PENALTY

            hybrid *= penalty

            # Path-based scoring: boost chunks whose file path matches query terms.
            # Uses IDF-weighted prefix matching so rare terms (e.g. "csrf", "auth")
            # get stronger boost than common ones (e.g. "views", "models").
            if tu and tu.resource_id in self._resource_path_tokens:
                pb = _path_boost(
                    self._resource_path_tokens[tu.resource_id],
                    content_query_tokens,
                    self._idf,
                    self._max_idf,
                )
                hybrid += pb

            scored.append((cid, hybrid, text))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Step 1a: Import-graph boost (cross_file mode only).
        # Identify files in the tentative top-k, then boost chunks from
        # files that import (or are imported by) those files.  Only for
        # cross_file queries — other modes don't need import chain discovery
        # and the boost disrupts their ranking.
        if mode.name == "cross_file" and (self._import_graph.forward or self._import_graph.reverse):
            scored = self._apply_import_boost(scored, effective_k)

        # Take top effective_k (no dynamic cap — that's the whole point)
        top_chunks = [
            (cid, s, t) for cid, s, t in scored[:effective_k] if s >= MIN_SCORE
        ]
        if not top_chunks and scored:
            top_chunks = scored[:3]

        # Step 1b: Sibling chunk expansion
        all_scored_dict = {cid: s for cid, s, _ in scored}
        top_chunks = self._expand_siblings(top_chunks, all_scored_dict)

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

    # -- Import-graph scoring ----------------------------------------

    _IMPORT_BOOST_WEIGHT = 0.12  # fraction of anchor file's best score to add

    def _apply_import_boost(
        self,
        scored: list[tuple[str, float, str]],
        top_k: int,
    ) -> list[tuple[str, float, str]]:
        """Boost chunks from files that are import-connected to top-scoring files.

        Two-pass approach:
        1. Identify files with chunks in the tentative top-k.
        2. For each such file, find its import neighbors (depth 1).
        3. Add a score boost to ALL chunks from neighbor files, weighted
           by the anchor file's best chunk score.

        This lets ``dispatch/dispatcher.py`` get boosted when
        ``models/signals.py`` is already in top-k (because signals.py
        imports from dispatch).
        """
        # Build locator → best score from tentative top-k
        anchor_scores: dict[str, float] = {}
        for cid, score, _ in scored[:top_k]:
            tu = self.text_units_by_id.get(cid)
            if not tu:
                continue
            res = self.resources_by_id.get(tu.resource_id)
            if not res:
                continue
            loc = res.locator
            if loc not in anchor_scores or score > anchor_scores[loc]:
                anchor_scores[loc] = score

        # Collect neighbor locators with their boost
        neighbor_boost: dict[str, float] = {}  # locator → boost amount
        for anchor_loc, anchor_score in anchor_scores.items():
            for neighbor_loc in self._import_graph.neighbors(anchor_loc):
                if neighbor_loc in anchor_scores:
                    continue  # already in top-k, no boost needed
                boost = self._IMPORT_BOOST_WEIGHT * anchor_score
                if neighbor_loc not in neighbor_boost or boost > neighbor_boost[neighbor_loc]:
                    neighbor_boost[neighbor_loc] = boost

        if not neighbor_boost:
            return scored

        # Apply boost only to chunks that already have SOME relevance.
        # A file with zero query overlap shouldn't surface just because
        # it's imported somewhere.
        rid_to_boost = {}
        for loc, boost in neighbor_boost.items():
            rid = self._locator_to_rid.get(loc)
            if rid:
                rid_to_boost[rid] = boost

        # Build a map of best current score per resource_id for the floor check
        best_score_by_rid: dict[str, float] = {}
        for cid, score, _ in scored:
            tu = self.text_units_by_id.get(cid)
            if tu:
                rid = tu.resource_id
                if rid not in best_score_by_rid or score > best_score_by_rid[rid]:
                    best_score_by_rid[rid] = score

        new_scored: list[tuple[str, float, str]] = []
        for cid, score, text in scored:
            tu = self.text_units_by_id.get(cid)
            if tu and tu.resource_id in rid_to_boost:
                # Only boost if the file already has at least minimal relevance
                if best_score_by_rid.get(tu.resource_id, 0) >= 0.05:
                    score += rid_to_boost[tu.resource_id]
            new_scored.append((cid, score, text))

        new_scored.sort(key=lambda x: x[1], reverse=True)
        return new_scored

    # -- Sibling expansion -------------------------------------------

    def _expand_siblings(
        self,
        top_chunks: list[tuple[str, float, str]],
        all_scored: dict[str, float],
    ) -> list[tuple[str, float, str]]:
        """Pull in highest-scoring unselected sibling chunks from files already represented."""
        selected_ids = {cid for cid, _, _ in top_chunks}

        # Map resource_id -> selected chunk ids
        files_represented: dict[str, list[str]] = defaultdict(list)
        for cid, _, _ in top_chunks:
            tu = self.text_units_by_id.get(cid)
            if tu:
                files_represented[tu.resource_id].append(cid)

        expansion: list[tuple[str, float, str]] = []
        total_added = 0
        # Process files by highest selected chunk score so that the most
        # query-relevant files get their siblings expanded first.
        file_max_score = {
            rid: max(all_scored.get(cid, 0.0) for cid in cids)
            for rid, cids in files_represented.items()
        }
        sorted_files = sorted(files_represented.items(), key=lambda x: file_max_score[x[0]], reverse=True)
        for resource_id, selected_cids in sorted_files:
            if total_added >= MAX_EXPANSION_TOTAL:
                break

            # Get selected spans for adjacency scoring
            selected_spans: list[int] = []
            for cid in selected_cids:
                tu = self.text_units_by_id.get(cid)
                if tu:
                    selected_spans.append(tu.span[0])

            # Find unselected siblings with minimum score
            candidates: list[tuple[str, float, str, int]] = []
            for tu in self.tus_by_resource.get(resource_id, []):
                if tu.id in selected_ids:
                    continue
                score = all_scored.get(tu.id, 0.0)
                if score < SIBLING_MIN_SCORE:
                    continue
                min_dist = (
                    min(abs(tu.span[0] - s) for s in selected_spans)
                    if selected_spans
                    else 999
                )
                candidates.append((tu.id, score, tu.content, min_dist))

            # Sort by adjacency first (nearest to selected chunk), then score
            candidates.sort(key=lambda x: (x[3], -x[1]))
            budget = min(MAX_SIBLINGS_PER_FILE, MAX_EXPANSION_TOTAL - total_added)
            for tu_id, score, text, _ in candidates[:budget]:
                expansion.append((tu_id, score, text))
                selected_ids.add(tu_id)
                total_added += 1

        return top_chunks + expansion
